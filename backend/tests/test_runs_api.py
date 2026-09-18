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
