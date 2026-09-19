"""Run upload, job lifecycle, schedule/report/export gate tests (AT-01, AT-11)."""

from __future__ import annotations

import uuid

from app.modules.export import archive_members
from app.workers import rail_solver_worker


def _upload(client, files):
    return client.post(
        "/api/v1/runs",
        files=[
            ("files", (name, data, "text/csv")) for name, data in files.items()
        ],
    )


def _submit(client, run_id, scenario="A"):
    return client.post(f"/api/v1/runs/{run_id}/jobs", json={"scenario": scenario})


def test_upload_valid_instance(client, minimal_instance_files):
    response = _upload(client, minimal_instance_files)
    assert response.status_code == 201
    body = response.json()
    assert body["parse_status"] == "OK"
    assert body["parse_summary"]["counts"]["activities"] == 1
    assert body["parse_summary"]["horizon_weeks"] == 4
    assert uuid.UUID(body["id"])


def test_get_run_and_network(client, minimal_instance_files):
    run_id = _upload(client, minimal_instance_files).json()["id"]

    run = client.get(f"/api/v1/runs/{run_id}")
    assert run.status_code == 200
    assert run.json()["id"] == run_id

    network = client.get(f"/api/v1/runs/{run_id}/network")
    assert network.status_code == 200
    body = network.json()
    assert {line["line_code"] for line in body["lines"]} == {"ALP"}
    assert body["routes"]["A1"]
    assert body["location_capacities"]["SEC:ALP:S01_S02:EB"] == 4


def test_upload_missing_file_is_422(client, minimal_instance_files):
    files = dict(minimal_instance_files)
    files.pop("03_SECTORS.csv")
    response = _upload(client, files)
    assert response.status_code == 422
    issues = response.json()["detail"]["issues"]
    assert any(issue["file"] == "03_SECTORS.csv" for issue in issues)
    assert any("missing" in issue["message"] for issue in issues)


def test_upload_unexpected_file_is_422(client, minimal_instance_files):
    files = dict(minimal_instance_files)
    files["extra.csv"] = b"a,b\n1,2\n"
    response = _upload(client, files)
    assert response.status_code == 422
    assert any(
        issue["file"] == "extra.csv" for issue in response.json()["detail"]["issues"]
    )


def test_upload_malformed_file_is_actionable_422(client, minimal_instance_files):
    files = dict(minimal_instance_files)
    files["01_LINES.csv"] = b"line_code\nALP\n"
    response = _upload(client, files)
    assert response.status_code == 422
    issues = response.json()["detail"]["issues"]
    target = [issue for issue in issues if issue["file"] == "01_LINES.csv"]
    assert target
    assert any("line_name" in issue["message"] for issue in target)


def test_job_lifecycle_and_duplicate_active_guard(client, minimal_instance_files):
    run_id = _upload(client, minimal_instance_files).json()["id"]

    first = _submit(client, run_id, "A")
    assert first.status_code == 202
    job = first.json()
    assert job["state"] == "QUEUED"
    assert job["started_at"] is None

    assert _submit(client, run_id, "A").status_code == 409
    assert _submit(client, run_id, "B").status_code == 202

    fetched = client.get(f"/api/v1/runs/{run_id}/jobs/{job['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["state"] == "QUEUED"

    cancelled = client.post(f"/api/v1/runs/{run_id}/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "CANCELLED"

    assert _submit(client, run_id, "A").status_code == 202


def test_job_request_rejects_seed_outside_database_range(client, minimal_instance_files):
    run_id = _upload(client, minimal_instance_files).json()["id"]

    negative = client.post(
        f"/api/v1/runs/{run_id}/jobs", json={"scenario": "A", "seed": -1}
    )
    too_large = client.post(
        f"/api/v1/runs/{run_id}/jobs",
        json={"scenario": "A", "seed": 2_147_483_648},
    )

    assert negative.status_code == 422
    assert too_large.status_code == 422


def test_partial_unique_index_blocks_duplicate_active_job(
    client, db_session, minimal_instance_files
):
    """Database backstop for the concurrent duplicate-job race (M2)."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.domain.enums import JobState, Scenario
    from app.domain.models import ScenarioJob

    run_id = _upload(client, minimal_instance_files).json()["id"]
    assert _submit(client, run_id, "A").status_code == 202

    duplicate = ScenarioJob(
        run_id=uuid.UUID(run_id), scenario=Scenario.A, state=JobState.QUEUED
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unknown_run_and_job_are_404(client, minimal_instance_files):
    assert client.get(f"/api/v1/runs/{uuid.uuid4()}").status_code == 404
    run_id = _upload(client, minimal_instance_files).json()["id"]
    assert client.get(f"/api/v1/runs/{run_id}/jobs/{uuid.uuid4()}").status_code == 404


def test_list_jobs_newest_first_and_scoped_to_run(client, minimal_instance_files):
    run_id = _upload(client, minimal_instance_files).json()["id"]
    other_run_id = _upload(client, minimal_instance_files).json()["id"]

    first = _submit(client, run_id, "A").json()["id"]
    second = _submit(client, run_id, "B").json()["id"]
    third = _submit(client, run_id, "C").json()["id"]
    other = _submit(client, other_run_id, "A").json()["id"]

    response = client.get(f"/api/v1/runs/{run_id}/jobs")
    assert response.status_code == 200
    ids = [job["id"] for job in response.json()]
    assert ids == [third, second, first]
    assert other not in ids

    assert client.get(f"/api/v1/runs/{uuid.uuid4()}/jobs").status_code == 404


def test_schedule_report_export_gate(
    client,
    worker_session,
    minimal_instance_files,
    fake_solver_result,
    monkeypatch,
):
    monkeypatch.setattr(rail_solver_worker, "solve", fake_solver_result)

    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]
    base = f"/api/v1/runs/{run_id}/jobs/{job_id}"

    assert client.get(f"{base}/schedule").status_code == 409
    assert client.get(f"{base}/report").status_code == 409
    assert client.get(f"{base}/export").status_code == 409

    assert rail_solver_worker.process_next_job() is True

    schedule = client.get(f"{base}/schedule")
    assert schedule.status_code == 200
    body = schedule.json()
    assert body["scenario"] == "A"
    assert body["access"]
    assert body["occupancy"]
    assert body["results"]
    explanations = {item["activity_id"]: item for item in body["explanations"]}
    assert explanations["A1"]["evidence"]["first_week"] == 1
    assert explanations["A1"]["evidence"]["planned_start_week"] == 1
    assert explanations["A1"]["reason_codes"] == []
    assert explanations["A1"]["summary"].startswith("A1 first access week 1")

    report = client.get(f"{base}/report")
    assert report.status_code == 200
    assert report.json()["ready_for_submission"] is True
    assert report.json()["authority"] == "fallback"

    export = client.get(f"{base}/export")
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/zip"
    members = set(archive_members(export.content))
    assert members == {
        "SCHEDULE_ACCESS.csv",
        "SCHEDULE_OCCUPANCY.csv",
        "RESULTS.csv",
    }


def test_schedule_explanations_from_persisted_solver_evidence(
    client,
    worker_session,
    minimal_instance_files,
    fake_solver_result,
    monkeypatch,
):
    def with_reasons(compiled, scenario, **kwargs):
        return fake_solver_result(
            compiled,
            scenario,
            binding_reasons={
                "A1": ["PLANNED_START", "PREDECESSOR", "HORIZON_EXTENDED"]
            },
        )

    monkeypatch.setattr(rail_solver_worker, "solve", with_reasons)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    assert rail_solver_worker.process_next_job() is True

    job = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}").json()
    assert job["result"]["binding_reasons"] == {
        "A1": ["PLANNED_START", "PREDECESSOR", "HORIZON_EXTENDED"]
    }

    worker_session.expunge_all()
    body = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}/schedule").json()
    explanations = {item["activity_id"]: item for item in body["explanations"]}
    item = explanations["A1"]
    assert item["reason_codes"] == [
        "HORIZON_EXTENDED",
        "PLANNED_START",
        "PREDECESSOR",
    ]
    assert item["evidence"]["first_week"] == 1
    assert item["evidence"]["planned_start_week"] == 1
    assert item["evidence"]["horizon_weeks"] == 4
    assert item["evidence"]["horizon_extended"] is False
    assert "A1 first access week 1" in item["summary"]


def test_network_exposes_compiled_activity_spans(client, minimal_instance_files):
    """The additive control-board spans match the compiled instance exactly."""

    from app.modules.compiler import compile_instance
    from app.modules.instance import parse_mapping
    from app.modules.instance.service import build_planning_instance

    run_id = _upload(client, minimal_instance_files).json()["id"]
    body = client.get(f"/api/v1/runs/{run_id}/network").json()

    assert body["activity_spans"]
    expected_keys = {
        "occupied_locations",
        "closure_locations",
        "mirrored_locations",
        "interchange_locations",
    }
    for span in body["activity_spans"].values():
        assert set(span) == expected_keys

    sources = {
        name: data.decode("utf-8") for name, data in minimal_instance_files.items()
    }
    compiled = compile_instance(build_planning_instance(parse_mapping(sources)))
    assert set(body["activity_spans"]) == set(compiled.activities)
    for activity_id, activity in compiled.activities.items():
        assert body["activity_spans"][activity_id] == {
            "occupied_locations": list(activity.occupied_locations),
            "closure_locations": list(activity.closure_locations),
            "mirrored_locations": list(activity.mirrored_locations),
            "interchange_locations": list(activity.interchange_locations),
        }


def test_network_response_still_parses_with_activity_spans(
    client, minimal_instance_files
):
    """The network payload stays parseable against the published schema."""

    from app.domain.schemas import NetworkResponse

    run_id = _upload(client, minimal_instance_files).json()["id"]
    response = client.get(f"/api/v1/runs/{run_id}/network")
    assert response.status_code == 200

    parsed = NetworkResponse.model_validate(response.json())
    assert set(parsed.activity_spans) == {"A1"}
    assert parsed.activity_spans["A1"].occupied_locations


def test_schedule_access_physical_night_round_trips(
    client,
    worker_session,
    minimal_instance_files,
    fake_solver_result,
    monkeypatch,
):
    """The solver's internal physical slot survives persistence and retrieval."""

    def with_physical_night(compiled, scenario, **kwargs):
        base = fake_solver_result(compiled, scenario, **kwargs)
        access = tuple(
            row.model_copy(update={"physical_night": 5}) for row in base.access
        )
        return base.model_copy(update={"access": access})

    monkeypatch.setattr(rail_solver_worker, "solve", with_physical_night)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    assert rail_solver_worker.process_next_job() is True

    worker_session.expunge_all()
    body = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}/schedule").json()
    assert body["access"]
    assert all(row["physical_night"] == 5 for row in body["access"])


def _solve_with_physical_night(fake_solver_result, monkeypatch, night: int):
    def with_physical_night(compiled, scenario, **kwargs):
        base = fake_solver_result(compiled, scenario, **kwargs)
        access = tuple(
            row.model_copy(update={"physical_night": night}) for row in base.access
        )
        return base.model_copy(update={"access": access})

    monkeypatch.setattr(rail_solver_worker, "solve", with_physical_night)


def test_schedule_surfaces_passed_physical_witness_checks(
    client,
    worker_session,
    minimal_instance_files,
    fake_solver_result,
    monkeypatch,
):
    """The schedule response exposes the additive physical witness report."""

    _solve_with_physical_night(fake_solver_result, monkeypatch, 5)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    assert rail_solver_worker.process_next_job() is True

    worker_session.expunge_all()
    body = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}/schedule").json()
    report = body["physical_checks"]
    assert report["passed"] is True
    checks = {check["name"]: check for check in report["checks"]}
    assert list(checks) == [
        "slot_mix",
        "closure_simultaneity",
        "capacity_slots",
        "workfront_slots",
        "witness_available",
    ]
    assert all(check["passed"] for check in checks.values())


def test_schedule_physical_witness_fails_closed_without_witness(
    client,
    worker_session,
    minimal_instance_files,
    fake_solver_result,
    monkeypatch,
):
    """Witness-free solver output is surfaced as a failed witness, not silence."""

    def without_physical_witness(compiled, scenario, **kwargs):
        base = fake_solver_result(compiled, scenario, **kwargs)
        access = tuple(
            row.model_copy(update={"physical_night": None}) for row in base.access
        )
        return base.model_copy(update={"access": access})

    monkeypatch.setattr(rail_solver_worker, "solve", without_physical_witness)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    assert rail_solver_worker.process_next_job() is True

    worker_session.expunge_all()
    body = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}/schedule").json()
    report = body["physical_checks"]
    assert report["passed"] is False
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["witness_available"]["passed"] is False
    validator = client.get(
        f"/api/v1/runs/{run_id}/jobs/{job_id}/report"
    ).json()
    assert validator["feasible"] is True
    assert validator["ready_for_submission"] is False
    job = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}").json()
    assert job["result"]["ready_for_submission"] is False
    assert client.get(
        f"/api/v1/runs/{run_id}/jobs/{job_id}/export"
    ).status_code == 409
