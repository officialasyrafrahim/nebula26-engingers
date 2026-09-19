"""Fail-closed calendar projection and RFC 5545 export."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.domain.enums import JobState
from app.domain.models import AuditLog, CalendarVersion
from app.domain.rail.nights import in_physical_night_universe
from app.modules.compiler import compile_instance
from app.modules.compiler.policy import get_policy
from app.modules.runs import service as runs
from app.modules.validator import check_physical_witness, validate_bundle


class CalendarPossession(BaseModel):
    possession_id: str
    job_id: str
    scenario: str
    schedule_version: str
    week: int
    physical_night: int
    location_ids: list[str]
    activity_ids: list[str]
    contract_numbers: list[str]
    co_share_group: str
    access_type: list[str]
    nature_of_works: list[str]
    eclo: bool
    local_access_nights: dict[str, int]
    status: Literal["DRAFT", "VALIDATED", "PUBLISHED", "SUPERSEDED"] = "VALIDATED"
    validator_status: str = "PASSED"
    evidence: list[dict] = Field(default_factory=list)
    date: str | None = None


def blocked(message):
    raise HTTPException(409, message)


def assured(db, run_id, job_id):
    job = runs.get_job(db, run_id, job_id)
    report = runs.get_report(db, run_id, job_id)
    if (
        job.state != JobState.COMPLETED
        or job.cancel_requested
        or (job.result or {}).get("status") not in {"OPTIMAL", "FEASIBLE", "FEASIBLE_GREEDY"}
        or not report.feasible
        or not report.workload_complete
        or not report.ready_for_submission
        or report.scenario != job.scenario.value
        or report.report.get("hard_violations", None) != []
    ):
        blocked("Calendar requires completed workload and zero hard validator violations.")
    schedule = runs.get_schedule(db, run_id, job_id)
    instance = runs.instance_for_run(job.run)
    compiled = compile_instance(instance)
    witness = check_physical_witness(
        compiled, get_policy(job.scenario.value), schedule["access"], schedule["occupancy"]
    )
    validation = validate_bundle(instance, runs._bundle_for_job(db, job), job.scenario.value)
    if not witness.passed or not validation.ready_for_submission:
        blocked("Persisted witness or workload/validator recheck failed.")
    # A slot is a witness label, never a contract-local access-night or an inferred date.
    # It must be one of the shared seven-night universe, not merely a positive integer.
    if any(
        r.physical_night is None or not in_physical_night_universe(r.physical_night)
        for r in schedule["access"]
    ):
        blocked("Missing or invalid physical night.")
    fingerprint = {
        "source": job.run.source_files,
        "access": [
            (r.activity_id, r.access_seq, r.week, r.access_night, r.physical_night, r.eclo)
            for r in schedule["access"]
        ],
        "occupancy": [
            (r.activity_id, r.week, r.location_id, r.co_share_group) for r in schedule["occupancy"]
        ],
        "results": [
            (r.contract_number, str(r.simulated_completion_date), r.overrun_days)
            for r in schedule["results"]
        ],
    }
    digest = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    return job, instance, schedule, report, digest


def project(job, instance, schedule, version_id):
    """Join location witnesses into connected possessions within one slot/group.

    Same group labels at disconnected locations are NOT sufficient to merge.
    Activities linking multiple occupied locations join those footprints. Thus
    PC+C+C at a shared footprint is one event, never three activity events.
    """
    access = {(r.activity_id, r.week): r for r in schedule["access"]}
    if len(access) != len(schedule["access"]):
        blocked("Ambiguous activity/week witness.")
    atoms = defaultdict(lambda: defaultdict(set))
    covered = set()
    group_at_slot = {}
    for row in schedule["occupancy"]:
        key = (row.activity_id, row.week)
        if key not in access or not row.co_share_group:
            blocked("Occupancy has no matching physical witness/group.")
        a = access[key]
        slot = (row.location_id, row.week, a.physical_night)
        if slot in group_at_slot and group_at_slot[slot] != row.co_share_group:
            blocked("Conflicting possession groups occupy the same physical location/night.")
        group_at_slot[slot] = row.co_share_group
        atoms[(row.week, a.physical_night, row.co_share_group)][row.location_id].add(
            row.activity_id
        )
        covered.add(key)
    if covered != set(access):
        blocked("Every witnessed access must have an occupied footprint.")
    evidence = {e.activity_id: e.model_dump(mode="json") for e in schedule["explanations"]}
    events = []
    for (week, night, group), locations in sorted(atoms.items()):
        pending = list(sorted(locations))
        while pending:
            first = pending.pop(0)
            footprint, activities = {first}, set(locations[first])
            changed = True
            while changed:
                changed = False
                for loc in pending[:]:
                    if activities & locations[loc]:
                        footprint.add(loc)
                        activities |= locations[loc]
                        pending.remove(loc)
                        changed = True
            ids = sorted(activities)
            contracts = sorted({instance.activities[a].contract_number for a in ids})
            identity = json.dumps([week, night, group, sorted(footprint), ids])
            possession_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
            events.append(
                CalendarPossession(
                    possession_id=possession_id,
                    job_id=str(job.id),
                    scenario=job.scenario.value,
                    schedule_version=version_id,
                    week=week,
                    physical_night=night,
                    location_ids=sorted(footprint),
                    activity_ids=ids,
                    contract_numbers=contracts,
                    co_share_group=group,
                    access_type=[
                        instance.contracts[instance.activities[a].contract_number].access_type
                        for a in ids
                    ],
                    nature_of_works=sorted(
                        {instance.contracts[c].nature_of_activity for c in contracts}
                    ),
                    eclo=any(access[(a, week)].eclo for a in ids),
                    local_access_nights={a: access[(a, week)].access_night for a in ids},
                    evidence=[evidence[a] for a in ids if a in evidence],
                ).model_dump()
            )
    return events


def calendar(db, run_id, job_id):
    job, instance, schedule, report, digest = assured(db, run_id, job_id)
    version = db.scalar(select(CalendarVersion).where(CalendarVersion.job_id == job.id))
    version_id = str(uuid.uuid5(job.id, digest))
    if version and version.witness_hash != digest:
        blocked("Witness changed after versioning; solve a new job to create a new version.")
    events = version.snapshot["events"] if version else project(job, instance, schedule, version_id)
    state = version.state if version else "VALIDATED"
    bindings = version.date_bindings if version else {}
    return {
        "job_id": str(job.id),
        "run_id": str(job.run_id),
        "scenario": job.scenario.value,
        "schedule_version": version_id,
        "status": state,
        "horizon_start": str(instance.horizon_start),
        "validator_authority": report.authority,
        "scores": report.report.get("soft_scores", {}),
        "events": [
            dict(e, status=state, date=bindings.get(f"{e['week']}:{e['physical_night']}"))
            for e in events
        ],
    }


def publish(db, run_id, job_id, bindings, actor):
    # Lock the run to serialize publishing among different scenario jobs on PostgreSQL.
    from app.domain.models import PlanningRun

    db.execute(select(PlanningRun).where(PlanningRun.id == run_id).with_for_update())
    data = calendar(db, run_id, job_id)
    job, instance, _, _, digest = assured(db, run_id, job_id)
    if data["status"] == "SUPERSEDED":
        blocked("Superseded versions cannot be republished; create a new solve.")
    slots = {f"{e['week']}:{e['physical_night']}" for e in data["events"]}
    if set(bindings) != slots:
        blocked("Provide exactly one date for every week:physical_night slot.")
    normalized = {k: v.isoformat() for k, v in bindings.items()}
    for key, value in bindings.items():
        week = int(key.split(":")[0])
        start = instance.horizon_start + timedelta(weeks=week - 1)
        if not start <= value <= start + timedelta(days=6):
            blocked(f"Date for {key} must be within its planning week.")
    if len(set(normalized.values())) != len(normalized):
        blocked("Distinct physical nights must be assigned distinct dates.")
    version = db.scalar(select(CalendarVersion).where(CalendarVersion.job_id == job.id))
    if version:
        if version.date_bindings != normalized:
            blocked("Published date bindings are immutable; create a new schedule job.")
        return data
    version = CalendarVersion(
        id=uuid.UUID(data["schedule_version"]),
        job_id=job.id,
        run_id=job.run_id,
        scenario=job.scenario.value,
        witness_hash=digest,
        snapshot=data,
        date_bindings=normalized,
        state="DRAFT",
    )
    for state in ("DRAFT", "VALIDATED", "PUBLISHED"):
        version.state = state
        db.add(
            AuditLog(
                actor=actor,
                action=f"calendar.{state.lower()}",
                entity_type="calendar_version",
                entity_id=str(version.id),
                after={"state": state, "job_id": str(job.id)},
            )
        )
    for old in db.scalars(
        select(CalendarVersion).where(
            CalendarVersion.run_id == job.run_id,
            CalendarVersion.scenario == job.scenario.value,
            CalendarVersion.state == "PUBLISHED",
            CalendarVersion.id != version.id,
        )
    ):
        old.state = "SUPERSEDED"
        db.add(
            AuditLog(
                actor=actor,
                action="calendar.superseded",
                entity_type="calendar_version",
                entity_id=str(old.id),
                after={"replacement": str(version.id)},
            )
        )
    try:
        db.flush()  # Supersede old version before activating the new one.
        db.add(version)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Concurrent publication; reload the calendar and retry.") from exc
    return calendar(db, run_id, job_id)


def ics_text(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def fold(line):
    """RFC 5545 lines are at most 75 octets, preserving UTF-8 codepoints."""
    chunks, current = [], ""
    for char in line:
        if len((current + char).encode()) > 75:
            chunks.append(current)
            current = " "
        current += char
    return "\r\n".join([*chunks, current])


def export_ics(db, run_id, job_id):
    data = calendar(db, run_id, job_id)
    if data["status"] != "PUBLISHED":
        blocked("Publish the assured calendar with confirmed dates before ICS export.")
    version = db.get(CalendarVersion, uuid.UUID(data["schedule_version"]))
    stamp = version.created_at.strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RAO//Possession Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for e in data["events"]:
        day = date.fromisoformat(e["date"])
        description = (
            f"Job {e['job_id']}; physical night {e['physical_night']}; "
            f"activities {', '.join(e['activity_ids'])}; "
            f"contracts {', '.join(e['contract_numbers'])}; "
            f"group {e['co_share_group']}; ECLO {e['eclo']}. "
            "Date-only possession: operating hours are not supplied. "
            f"Validator: {data['validator_authority']}."
        )
        lines += [
            "BEGIN:VEVENT",
            f"UID:{data['schedule_version']}.{e['possession_id']}@rao",
            f"DTSTAMP:{stamp}",
            "SEQUENCE:0",
            "STATUS:CONFIRMED",
            "TRANSP:TRANSPARENT",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
            f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
            "SUMMARY:"
            + ics_text(
                f"RAO {e['scenario']} · {' + '.join(e['access_type'])}"
                f" · {', '.join(e['activity_ids'])}"
            ),
            "LOCATION:" + ics_text(", ".join(e["location_ids"])),
            "DESCRIPTION:" + ics_text(description),
            "END:VEVENT",
        ]
    lines += ["END:VCALENDAR"]
    return ("\r\n".join(fold(line) for line in lines) + "\r\n").encode()
