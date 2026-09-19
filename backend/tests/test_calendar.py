"""Calendar must remain a fail-closed projection of persisted physical evidence."""

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from icalendar import Calendar
from sqlalchemy import select

from app.domain.enums import JobState
from app.domain.models import CalendarVersion, ScenarioJob, ScheduleAccessRow, ValidatorReportRow
from app.modules.calendar.service import fold, project
from app.workers import rail_solver_worker
from tests.test_runs_api import _submit, _upload


@pytest.fixture
def solved(client, minimal_instance_files, worker_session, monkeypatch, fake_solver_result):
    monkeypatch.setattr(rail_solver_worker, "solve", fake_solver_result)
    run = _upload(client, minimal_instance_files).json()["id"]
    job = _submit(client, run).json()["id"]
    assert rail_solver_worker.process_next_job(timeout=0)
    return run, job, f"/api/v1/runs/{run}/jobs/{job}/calendar"


def test_publish_and_ics_round_trip(client, solved, db_session):
    run, job, path = solved
    response = client.get(path)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["events"]) == 1  # one activity across three occupied locations
    event = data["events"][0]
    assert len(event["location_ids"]) == 3
    assert event["physical_night"] == 1
    assert event["local_access_nights"] == {"A1": 1}
    assert client.get(path + "/ics").status_code == 409
    published = client.post(path + "/publish", json={"date_bindings": {"1:1": "2027-01-08"}})
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "PUBLISHED"
    raw = client.get(path + "/ics")
    assert raw.status_code == 200
    parsed = Calendar.from_ical(raw.content)
    events = parsed.walk("VEVENT")
    assert len(events) == len(data["events"])
    assert events[0].decoded("DTSTART") == date(2027, 1, 8)
    assert events[0].decoded("DTEND") == date(2027, 1, 9)
    assert str(events[0]["UID"]) == f"{data['schedule_version']}.{event['possession_id']}@rao"
    assert raw.content == client.get(path + "/ics").content
    assert (
        client.post(path + "/publish", json={"date_bindings": {"1:1": "2027-01-09"}}).status_code
        == 409
    )
    assert db_session.scalar(select(CalendarVersion)).state == "PUBLISHED"


@pytest.mark.parametrize(
    "state",
    [
        JobState.FAILED,
        JobState.TIMED_OUT,
        JobState.INFEASIBLE,
        JobState.CANCELLED,
        JobState.RUNNING,
    ],
)
def test_noncompleted_job_never_serves_calendar(client, solved, db_session, state):
    _, job, path = solved
    db_session.get(ScenarioJob, uuid.UUID(job)).state = state
    db_session.commit()
    assert client.get(path).status_code == 409
    assert client.get(path + "/ics").status_code == 409


def test_stale_green_report_does_not_allow_missing_witness(client, solved, db_session):
    _, _, path = solved
    row = db_session.scalar(select(ScheduleAccessRow))
    row.physical_night = None
    db_session.commit()
    assert client.get(path).status_code == 409


def test_forged_green_report_does_not_allow_incomplete_workload(client, solved, db_session):
    _, _, path = solved
    db_session.delete(db_session.scalar(select(ScheduleAccessRow)))
    db_session.commit()
    assert client.get(path).status_code == 409


def test_red_validator_report_blocks_calendar(client, solved, db_session):
    _, _, path = solved
    report = db_session.scalar(select(ValidatorReportRow))
    report.report = dict(report.report, hard_violations=[{"rule": "test"}])
    db_session.commit()
    assert client.get(path).status_code == 409


def test_date_binding_and_cross_run_isolation(client, solved):
    _, job, path = solved
    assert client.get(f"/api/v1/runs/{uuid.uuid4()}/jobs/{job}/calendar").status_code == 404
    for bindings in ({}, {"1:1": "2027-02-01"}, {"1:2": "2027-01-08"}):
        assert client.post(path + "/publish", json={"date_bindings": bindings}).status_code == 409


def test_co_shared_pc_c_c_is_one_event_and_disconnected_group_stays_separate():
    contracts = {
        str(i): SimpleNamespace(access_type=t, nature_of_activity="Non-live (Others)")
        for i, t in enumerate(["PC", "C", "C", "C"])
    }
    instance = SimpleNamespace(
        contracts=contracts,
        activities={f"A{i}": SimpleNamespace(contract_number=str(i)) for i in range(4)},
    )
    schedule = {
        "explanations": [],
        "access": [
            SimpleNamespace(
                activity_id=f"A{i}", week=1, physical_night=3, access_night=i + 1, eclo=False
            )
            for i in range(4)
        ],
        "occupancy": [
            SimpleNamespace(
                activity_id=f"A{i}",
                week=1,
                location_id="shared" if i < 3 else "separate",
                co_share_group="b1",
            )
            for i in range(4)
        ],
    }
    job = SimpleNamespace(id=uuid.uuid4(), scenario=SimpleNamespace(value="A"))
    events = project(job, instance, schedule, "version")
    assert sorted(len(e["activity_ids"]) for e in events) == [1, 3]
    shared = next(e for e in events if len(e["activity_ids"]) == 3)
    assert shared["access_type"] == ["PC", "C", "C"]
    assert shared["physical_night"] == 3
    assert shared["local_access_nights"] == {"A0": 1, "A1": 2, "A2": 3}


def test_ics_folds_unicode_by_octets():
    value = "SUMMARY:" + "夜間🚆" * 50
    folded = fold(value)
    assert all(len(line.encode()) <= 75 for line in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == value


def test_unknown_solver_status_is_not_publishable(client, solved, db_session):
    _, job, path = solved
    record = db_session.get(ScenarioJob, uuid.UUID(job))
    record.result = dict(record.result, status="UNKNOWN")
    db_session.commit()
    assert client.get(path).status_code == 409


def test_new_version_supersedes_only_same_scenario(client, solved, worker_session, db_session):
    run, _, path = solved
    dates = {"date_bindings": {"1:1": "2027-01-08"}}
    assert client.post(path + "/publish", json=dates).status_code == 200
    for scenario in ["B", "A"]:
        new_job = _submit(client, run, scenario).json()["id"]
        assert rail_solver_worker.process_next_job(timeout=0)
        new_path = f"/api/v1/runs/{run}/jobs/{new_job}/calendar"
        response = client.post(new_path + "/publish", json=dates)
        assert response.status_code == 200, response.text
        if scenario == "B":
            assert client.get(path).json()["status"] == "PUBLISHED"
    assert client.get(path).json()["status"] == "SUPERSEDED"
    assert client.get(path + "/ics").status_code == 409
    assert client.post(path + "/publish", json=dates).status_code == 409


def test_mutated_witness_cannot_reuse_published_version(client, solved, db_session):
    _, _, path = solved
    assert client.post(path + "/publish", json={
        "date_bindings": {"1:1": "2027-01-08"},
    }).status_code == 200
    row = db_session.scalar(select(ScheduleAccessRow))
    row.physical_night = 2
    db_session.commit()
    assert client.get(path).status_code == 409
