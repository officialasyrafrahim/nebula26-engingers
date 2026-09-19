"""Deterministic schedule query layer (F-BONUS-003).

The layer answers a small, closed grammar over persisted schedule evidence. It
never calls a language model, never reaches an external service and never lets a
query select data outside the completed job it is asked about. A well-formed
query whose evidence is missing is reported as unanswerable; a query that does
not match the grammar is rejected outright.

Supported forms (case-insensitive, aliases in brackets):

* ``why <activity_id>`` -- why the activity's first access landed where it did.
* ``downstream <activity_id>`` -- delay risk for the activities that follow it.
* ``capacity <location_id> week <n>`` [``co-share``] -- possession and co-sharing
  check for one location-week.
* ``milestone <contract_number>`` [``handover``] -- planned versus simulated
  completion brief for one contract.

Every answer carries the underlying evidence and citations to the persisted rows
it was derived from. No answer is invented: an unknown activity, contract or
location is reported as unanswerable rather than guessed.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.domain.rail.compiled import CompiledInstance

MAX_QUERY_LENGTH = 200
_TOKEN = r"[A-Za-z0-9_.:-]+"

_WHY_RE = re.compile(rf"^why\s+({_TOKEN})$", re.IGNORECASE)
_DOWNSTREAM_RE = re.compile(rf"^downstream\s+({_TOKEN})$", re.IGNORECASE)
_CAPACITY_RE = re.compile(
    rf"^(?:capacity|co-?share)\s+({_TOKEN})\s+week\s+(\d+)$", re.IGNORECASE
)
_MILESTONE_RE = re.compile(rf"^(?:milestone|handover)\s+({_TOKEN})$", re.IGNORECASE)

GRAMMAR_HELP = (
    "supported queries: 'why <activity_id>', 'downstream <activity_id>', "
    "'capacity <location_id> week <n>' and 'milestone <contract_number>'"
)

_BINDING_LABELS = {
    "CAPACITY": "capacity pressure",
    "WEEKLY_CAP": "the contract weekly access cap",
    "WORKFRONT": "the contract workfront limit",
    "BUFFER_CLOSURE": "a closure buffer",
    "LIVE_MIRROR": "Live opposite-bound mirroring",
    "INTERCHANGE": "an interchange closure",
    "POSSESSION_MIX": "possession-mix rules",
}


class QuerySyntaxError(ValueError):
    """A query that does not match the supported grammar."""


@dataclass(frozen=True)
class ParsedQuery:
    """One query reduced to a typed form the answerer can dispatch on."""

    kind: str
    text: str
    activity_id: str | None = None
    location_id: str | None = None
    week: int | None = None
    contract_number: str | None = None


@dataclass(frozen=True)
class Citation:
    """A pointer back to one persisted evidence source."""

    source: str
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class QueryResult:
    """The answer text plus the evidence and citations behind it."""

    query: str
    kind: str
    answerable: bool
    answer: str
    evidence: Mapping[str, Any]
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True)
class AccessEvidence:
    """One persisted access placement."""

    activity_id: str
    access_seq: int
    week: int
    eclo: bool
    access_night: int
    physical_night: int | None = None


@dataclass(frozen=True)
class OccupancyEvidence:
    """One persisted occupancy placement."""

    activity_id: str
    week: int
    location_id: str
    co_share_group: str


@dataclass(frozen=True)
class ContractEvidence:
    """One persisted contract completion result."""

    contract_number: str
    simulated_completion_date: date
    overrun_days: int


@dataclass(frozen=True)
class QueryContext:
    """Everything a query may read, already scoped to one completed job."""

    scenario: str
    horizon_weeks: int
    horizon_start: date
    compiled: CompiledInstance
    access: tuple[AccessEvidence, ...] = ()
    occupancy: tuple[OccupancyEvidence, ...] = ()
    contracts: tuple[ContractEvidence, ...] = ()
    binding_reasons: Mapping[str, Sequence[str]] = field(default_factory=dict)
    displacement_evidence: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )

    def access_for(self, activity_id: str) -> tuple[AccessEvidence, ...]:
        return tuple(row for row in self.access if row.activity_id == activity_id)

    def first_week(self, activity_id: str) -> int | None:
        weeks = [row.week for row in self.access if row.activity_id == activity_id]
        return min(weeks) if weeks else None

    def last_week(self, activity_id: str) -> int | None:
        weeks = [row.week for row in self.access if row.activity_id == activity_id]
        return max(weeks) if weeks else None


def parse_query(text: str) -> ParsedQuery:
    """Reduce one query string to a typed intent or raise :class:`QuerySyntaxError`."""

    if not isinstance(text, str):
        raise QuerySyntaxError("query must be a string")
    normalized = " ".join(text.split())
    if not normalized:
        raise QuerySyntaxError(f"empty query; {GRAMMAR_HELP}")
    if len(normalized) > MAX_QUERY_LENGTH:
        raise QuerySyntaxError(f"query exceeds {MAX_QUERY_LENGTH} characters")

    match = _WHY_RE.match(normalized)
    if match:
        return ParsedQuery("why_moved", normalized, activity_id=match.group(1))

    match = _DOWNSTREAM_RE.match(normalized)
    if match:
        return ParsedQuery(
            "downstream_risk", normalized, activity_id=match.group(1)
        )

    match = _CAPACITY_RE.match(normalized)
    if match:
        week = int(match.group(2))
        if week < 1:
            raise QuerySyntaxError("week must be a positive integer")
        return ParsedQuery(
            "capacity_check",
            normalized,
            location_id=match.group(1),
            week=week,
        )

    match = _MILESTONE_RE.match(normalized)
    if match:
        return ParsedQuery(
            "milestone_brief", normalized, contract_number=match.group(1)
        )

    raise QuerySyntaxError(f"unsupported query; {GRAMMAR_HELP}")


def answer_query(context: QueryContext, parsed: ParsedQuery) -> QueryResult:
    """Answer a parsed query from persisted evidence only."""

    if parsed.kind == "why_moved":
        return _why_moved(context, parsed)
    if parsed.kind == "downstream_risk":
        return _downstream_risk(context, parsed)
    if parsed.kind == "capacity_check":
        return _capacity_check(context, parsed)
    if parsed.kind == "milestone_brief":
        return _milestone_brief(context, parsed)
    raise QuerySyntaxError(f"unsupported query kind {parsed.kind!r}")


def _unanswerable(parsed: ParsedQuery, reason: str) -> QueryResult:
    return QueryResult(
        query=parsed.text,
        kind=parsed.kind,
        answerable=False,
        answer=f"Cannot answer from persisted evidence: {reason}.",
        evidence={"reason": reason},
        citations=(),
    )


def _why_moved(context: QueryContext, parsed: ParsedQuery) -> QueryResult:
    activity_id = parsed.activity_id
    assert activity_id is not None
    activity = context.compiled.activities.get(activity_id)
    if activity is None:
        return _unanswerable(parsed, f"activity {activity_id!r} is not part of this run")

    rows = context.access_for(activity_id)
    if not rows:
        return _unanswerable(
            parsed, f"activity {activity_id!r} has no persisted schedule rows"
        )

    codes = tuple(context.binding_reasons.get(activity_id, ()))
    displacement = dict(context.displacement_evidence.get(activity_id, {}))
    weeks = [row.week for row in rows]
    first_week = min(weeks)
    last_week = max(weeks)
    planned_start_week = max(1, activity.planned_start_week)
    predecessor_id = activity.predecessor_activity_id
    predecessor_last_week = (
        context.last_week(predecessor_id) if predecessor_id is not None else None
    )

    parts = [f"first access week {first_week}"]
    parts.append(f"planned start week {planned_start_week}")
    if predecessor_id is not None and predecessor_last_week is not None:
        parts.append(
            f"predecessor {predecessor_id} last access week {predecessor_last_week}"
        )
    if first_week > context.horizon_weeks:
        parts.append(f"beyond the nominal {context.horizon_weeks}-week horizon")
    displaced = bool(displacement.get("displaced"))
    binding_week = displacement.get("binding_week")
    binding_constraints = list(displacement.get("binding_constraints", ()))
    if displaced and binding_week is not None and binding_constraints:
        labels = [_BINDING_LABELS.get(code, code) for code in binding_constraints]
        parts.append(
            f"earliest start week {displacement.get('planned_earliest_week')} "
            f"blocked at week {binding_week} by " + " and ".join(labels)
        )
    elif codes:
        parts.append("reason codes " + ", ".join(codes))
    answer = f"{activity_id} " + "; ".join(parts) + "."

    evidence: dict[str, Any] = {
        "activity_id": activity_id,
        "first_week": first_week,
        "last_week": last_week,
        "planned_start_week": planned_start_week,
        "predecessor_activity_id": predecessor_id,
        "predecessor_last_week": predecessor_last_week,
        "horizon_weeks": context.horizon_weeks,
        "horizon_extended": first_week > context.horizon_weeks,
        "reason_codes": list(codes),
        "displaced": displaced,
    }
    if displacement:
        evidence["displacement"] = displacement

    citations: list[Citation] = [
        Citation(
            "schedule_access",
            {
                "activity_id": row.activity_id,
                "access_seq": row.access_seq,
                "week": row.week,
                "access_night": row.access_night,
                "physical_night": row.physical_night,
                "eclo": row.eclo,
            },
        )
        for row in rows
    ]
    citations.append(
        Citation(
            "job_result.binding_reasons",
            {"activity_id": activity_id, "reason_codes": list(codes)},
        )
    )
    if displacement:
        citations.append(
            Citation(
                "job_result.displacement_evidence",
                {"activity_id": activity_id, **displacement},
            )
        )
    return QueryResult(
        query=parsed.text,
        kind=parsed.kind,
        answerable=True,
        answer=answer,
        evidence=evidence,
        citations=tuple(citations),
    )


def _transitive_successors(compiled: CompiledInstance, activity_id: str) -> list[str]:
    """Deterministic breadth-first list of every downstream activity."""

    order: list[str] = []
    seen: set[str] = set()
    queue: deque[str] = deque(compiled.activities[activity_id].successor_activity_ids)
    while queue:
        current = queue.popleft()
        if current in seen or current not in compiled.activities:
            continue
        seen.add(current)
        order.append(current)
        queue.extend(compiled.activities[current].successor_activity_ids)
    return order


def _downstream_risk(context: QueryContext, parsed: ParsedQuery) -> QueryResult:
    activity_id = parsed.activity_id
    assert activity_id is not None
    if activity_id not in context.compiled.activities:
        return _unanswerable(parsed, f"activity {activity_id!r} is not part of this run")

    last_week = context.last_week(activity_id)
    if last_week is None:
        return _unanswerable(
            parsed, f"activity {activity_id!r} has no persisted schedule rows"
        )

    successors = _transitive_successors(context.compiled, activity_id)
    entries: list[dict[str, Any]] = []
    citations: list[Citation] = [
        Citation(
            "schedule_access",
            {
                "activity_id": activity_id,
                "week": last_week,
                "role": "upstream_last_week",
            },
        )
    ]
    for successor_id in successors:
        successor = context.compiled.activities[successor_id]
        first_week = context.first_week(successor_id)
        immediate = successor.predecessor_activity_id
        immediate_last = (
            context.last_week(immediate) if immediate is not None else None
        )
        slack = (
            first_week - (immediate_last + 1)
            if first_week is not None and immediate_last is not None
            else None
        )
        if first_week is None:
            coupling = "not_scheduled"
        elif slack == 0:
            coupling = "direct"
        elif slack is not None and slack > 0:
            coupling = "buffered"
        else:
            coupling = "unknown"
        planned_start_week = max(1, successor.planned_start_week)
        delay_vs_plan = (
            first_week - planned_start_week if first_week is not None else None
        )
        entries.append(
            {
                "activity_id": successor_id,
                "first_week": first_week,
                "planned_start_week": planned_start_week,
                "predecessor_activity_id": immediate,
                "predecessor_last_week": immediate_last,
                "slack_weeks": slack,
                "delay_vs_plan_weeks": delay_vs_plan,
                "coupling": coupling,
            }
        )
        for row in context.access_for(successor_id):
            citations.append(
                Citation(
                    "schedule_access",
                    {
                        "activity_id": row.activity_id,
                        "week": row.week,
                        "access_night": row.access_night,
                        "physical_night": row.physical_night,
                        "role": "successor",
                    },
                )
            )

    direct = [entry["activity_id"] for entry in entries if entry["coupling"] == "direct"]
    evidence = {
        "activity_id": activity_id,
        "last_week": last_week,
        "successors": entries,
        "direct_successors": direct,
        "successor_count": len(entries),
    }
    if not entries:
        answer = (
            f"{activity_id} ends at week {last_week} and has no downstream "
            "activities in this run."
        )
    else:
        fragments = [
            f"{entry['activity_id']} first week {entry['first_week']} "
            f"({entry['coupling']}"
            + (
                f", {entry['delay_vs_plan_weeks']} weeks after its planned start"
                if entry["delay_vs_plan_weeks"]
                else ""
            )
            + ")"
            for entry in entries
        ]
        answer = (
            f"{activity_id} ends at week {last_week}; downstream "
            + "; ".join(fragments)
            + f". {len(direct)} directly coupled."
        )
    return QueryResult(
        query=parsed.text,
        kind=parsed.kind,
        answerable=True,
        answer=answer,
        evidence=evidence,
        citations=tuple(citations),
    )


def _capacity_check(context: QueryContext, parsed: ParsedQuery) -> QueryResult:
    location_id = parsed.location_id
    week = parsed.week
    assert location_id is not None and week is not None
    capacities = context.compiled.location_capacities
    if location_id not in capacities:
        return _unanswerable(
            parsed, f"location {location_id!r} is not part of this run"
        )

    capacity = int(capacities[location_id])
    groups: dict[str, set[str]] = {}
    rows = [
        row
        for row in context.occupancy
        if row.location_id == location_id and row.week == week
    ]
    for row in rows:
        groups.setdefault(row.co_share_group, set()).add(row.activity_id)
    used = len(groups)
    excess = max(0, used - capacity)
    shared = {
        group: sorted(members)
        for group, members in sorted(groups.items())
        if len(members) > 1
    }

    if not rows:
        answer = (
            f"{location_id} week {week} has no scheduled occupancy; 0 possessions "
            f"used against supply {capacity}."
        )
    else:
        answer = (
            f"{location_id} week {week} uses {used} possession(s) against supply "
            f"{capacity} (excess {excess})."
        )
        if shared:
            listing = ", ".join(
                f"{group}=[{'/'.join(members)}]" for group, members in shared.items()
            )
            answer += f" Co-shared groups: {listing}."

    evidence = {
        "location_id": location_id,
        "week": week,
        "supply_capacity": capacity,
        "possessions_used": used,
        "excess": excess,
        "co_share_groups": {
            group: sorted(members) for group, members in sorted(groups.items())
        },
        "co_shared_groups": shared,
    }
    citations: list[Citation] = [
        Citation(
            "compiled.location_capacities",
            {"location_id": location_id, "supply_capacity": capacity},
        )
    ]
    for row in rows:
        citations.append(
            Citation(
                "schedule_occupancy",
                {
                    "activity_id": row.activity_id,
                    "week": row.week,
                    "location_id": row.location_id,
                    "co_share_group": row.co_share_group,
                },
            )
        )
    return QueryResult(
        query=parsed.text,
        kind=parsed.kind,
        answerable=True,
        answer=answer,
        evidence=evidence,
        citations=tuple(citations),
    )


def _milestone_brief(context: QueryContext, parsed: ParsedQuery) -> QueryResult:
    contract_number = parsed.contract_number
    assert contract_number is not None
    contract = context.compiled.instance.contracts.get(contract_number)
    if contract is None:
        return _unanswerable(
            parsed, f"contract {contract_number!r} is not part of this run"
        )

    result = next(
        (
            item
            for item in context.contracts
            if item.contract_number == contract_number
        ),
        None,
    )
    if result is None:
        return _unanswerable(
            parsed,
            f"contract {contract_number!r} has no persisted completion result",
        )

    activities = sorted(
        activity_id
        for activity_id, activity in context.compiled.activities.items()
        if activity.contract_number == contract_number
    )
    last_weeks = {
        activity_id: context.last_week(activity_id) for activity_id in activities
    }
    scheduled_last_weeks = [
        week for week in last_weeks.values() if week is not None
    ]
    last_week = max(scheduled_last_weeks) if scheduled_last_weeks else None
    overrun_days = int(result.overrun_days)
    planned = contract.planned_completion_date
    simulated = result.simulated_completion_date

    answer = (
        f"{contract_number} planned completion {planned.isoformat()}, simulated "
        f"{simulated.isoformat()}, overrun {overrun_days} day(s). "
        f"Last access week {last_week}; {len(activities)} activity(ies) in scope."
    )

    evidence = {
        "contract_number": contract_number,
        "planned_completion_date": planned.isoformat(),
        "simulated_completion_date": simulated.isoformat(),
        "overrun_days": overrun_days,
        "last_access_week": last_week,
        "activity_count": len(activities),
        "activity_last_weeks": last_weeks,
    }
    citations: list[Citation] = [
        Citation(
            "contract_result",
            {
                "contract_number": contract_number,
                "simulated_completion_date": simulated.isoformat(),
                "overrun_days": overrun_days,
            },
        ),
        Citation(
            "compiled.contract",
            {
                "contract_number": contract_number,
                "planned_completion_date": planned.isoformat(),
            },
        ),
    ]
    for activity_id in activities:
        for row in context.access_for(activity_id):
            citations.append(
                Citation(
                    "schedule_access",
                    {
                        "activity_id": row.activity_id,
                        "week": row.week,
                        "access_night": row.access_night,
                        "physical_night": row.physical_night,
                        "contract_number": contract_number,
                    },
                )
            )
    return QueryResult(
        query=parsed.text,
        kind=parsed.kind,
        answerable=True,
        answer=answer,
        evidence=evidence,
        citations=tuple(citations),
    )


__all__ = [
    "AccessEvidence",
    "Citation",
    "ContractEvidence",
    "GRAMMAR_HELP",
    "MAX_QUERY_LENGTH",
    "OccupancyEvidence",
    "ParsedQuery",
    "QueryContext",
    "QueryResult",
    "QuerySyntaxError",
    "answer_query",
    "parse_query",
]
