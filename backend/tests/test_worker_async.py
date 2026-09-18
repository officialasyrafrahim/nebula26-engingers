"""Async worker lifecycle and native end-to-end tests (AT-11, AT-15)."""

from __future__ import annotations

import pytest

from app.domain.enums import JobState
from app.modules.solver import cp_sat_available
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


def test_job_creation_returns_before_solving(client, minimal_instance_files):
    run_id = _upload(client, minimal_instance_files).json()["id"]
    response = _submit(client, run_id, "A")

    assert response.status_code == 202
    job = response.json()
    assert job["state"] == JobState.QUEUED.value
    assert job["started_at"] is None
    assert job["finished_at"] is None

    fetched = client.get(f"/api/v1/runs/{run_id}/jobs/{job['id']}").json()
    assert fetched["state"] == JobState.QUEUED.value


def test_worker_completes_job_with_stubbed_solver(
    client, worker_session, minimal_instance_files, fake_solver_result, monkeypatch
):
    monkeypatch.setattr(rail_solver_worker, "solve", fake_solver_result)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    assert rail_solver_worker.process_next_job() is True

    job = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}").json()
    assert job["state"] == JobState.COMPLETED.value
    assert job["started_at"] is not None
    assert job["finished_at"] is not None
    assert job["error"] is None
    assert job["result"]["ready_for_submission"] is True
    assert job["result"]["access_count"] == 1


def test_worker_marks_timed_out_when_no_incumbent(
    client, worker_session, minimal_instance_files, fake_solver_result, monkeypatch
):
    def timed_out(compiled, scenario, **kwargs):
        return fake_solver_result(compiled, scenario, status="UNKNOWN", feasible=False)

    monkeypatch.setattr(rail_solver_worker, "solve", timed_out)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    assert rail_solver_worker.process_next_job() is True

    job = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}").json()
    assert job["state"] == JobState.TIMED_OUT.value
    assert job["finished_at"] is not None


def test_worker_marks_infeasible_when_infeasible(
    client, worker_session, minimal_instance_files, fake_solver_result, monkeypatch
):
    def infeasible(compiled, scenario, **kwargs):
        return fake_solver_result(
            compiled, scenario, status="INFEASIBLE", feasible=False
        )

    monkeypatch.setattr(rail_solver_worker, "solve", infeasible)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    assert rail_solver_worker.process_next_job() is True

    job = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}").json()
    assert job["state"] == JobState.INFEASIBLE.value
    assert job["result"]["infeasibility_reasons"]


def test_worker_marks_failed_on_solver_error(
    client, worker_session, minimal_instance_files, monkeypatch
):
    def boom(compiled, scenario, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(rail_solver_worker, "solve", boom)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    assert rail_solver_worker.process_next_job() is True

    job = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}").json()
    assert job["state"] == JobState.FAILED.value
    assert "kaboom" in job["error"]


def test_cancel_before_processing_is_skipped(
    client, worker_session, minimal_instance_files
):
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]
    assert (
        client.post(f"/api/v1/runs/{run_id}/jobs/{job_id}/cancel").status_code == 200
    )

    assert rail_solver_worker.process_next_job() is True

    job = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}").json()
    assert job["state"] == JobState.CANCELLED.value


def test_cancel_during_validation_is_honoured(
    client, worker_session, minimal_instance_files, fake_solver_result, monkeypatch
):
    """A cancel requested while VALIDATING must win over COMPLETED (M1)."""
    import uuid

    from app.domain.models import ScenarioJob

    monkeypatch.setattr(rail_solver_worker, "solve", fake_solver_result)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    real_validate = rail_solver_worker._validate

    def cancel_mid_validation(run, compiled, bundle, scenario):
        job = worker_session.get(ScenarioJob, uuid.UUID(job_id))
        job.cancel_requested = True
        worker_session.commit()
        return real_validate(run, compiled, bundle, scenario)

    monkeypatch.setattr(rail_solver_worker, "_validate", cancel_mid_validation)

    assert rail_solver_worker.process_next_job() is True

    job = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}").json()
    assert job["state"] == JobState.CANCELLED.value
    assert client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}/export").status_code == 409


@pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)
def test_native_end_to_end_worker(client, worker_session, minimal_instance_files):
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    assert rail_solver_worker.process_next_job() is True

    job = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}").json()
    assert job["state"] == JobState.COMPLETED.value
    assert job["result"]["authority"] == "fallback"
    assert job["result"]["ready_for_submission"] is True

    schedule = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}/schedule").json()
    assert schedule["access"]
    assert client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}/export").status_code == 200
