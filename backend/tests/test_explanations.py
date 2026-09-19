"""Displacement evidence in the schedule explanation read model (AT-14, EXP-01)."""

from __future__ import annotations

from app.modules.runs.service import _explanation_summary
from app.workers import rail_solver_worker


def _upload(client, files):
    return client.post(
        "/api/v1/runs",
        files=[("files", (name, data, "text/csv")) for name, data in files.items()],
    )


def _submit(client, run_id, scenario="A"):
    return client.post(f"/api/v1/runs/{run_id}/jobs", json={"scenario": scenario})


def test_summary_cites_each_displacement_reason():
    summary = _explanation_summary(
        "A1",
        [
            "BUFFER_CLOSURE",
            "CAPACITY",
            "CO_SHARE_PACKED",
            "INTERCHANGE",
            "LIVE_MIRROR",
            "POSSESSION_MIX",
        ],
        first_week=3,
        planned_start_week=2,
        predecessor_activity_id=None,
        predecessor_last_week=None,
        horizon_weeks=4,
        displacement={
            "displaced": True,
            "planned_earliest_week": 1,
            "binding_week": 1,
            "binding_constraints": ["CAPACITY"],
        },
    )
    assert "kept on a separate physical slot by a closure buffer" in summary
    assert "used a location at its capacity limit" in summary
    assert "packed into a co-shared possession" in summary
    assert "kept separate by an interchange closure" in summary
    assert "kept separate by Live opposite-bound mirroring" in summary
    assert "packed under possession-mix rules" in summary
    assert "earliest start week 1 blocked at week 1 by capacity pressure" in summary


def test_summary_never_claims_an_unproven_capacity_cause():
    summary = _explanation_summary(
        "A1",
        ["CAPACITY", "WEEKLY_CAP", "WORKFRONT"],
        first_week=3,
        planned_start_week=1,
        predecessor_activity_id=None,
        predecessor_last_week=None,
        horizon_weeks=4,
    )
    assert "capacity" not in summary.lower()
    assert "weekly access limit" not in summary
    assert "workfront limit" not in summary


def test_summary_stays_generic_without_supporting_facts():
    summary = _explanation_summary(
        "A1",
        ["BUFFER_CLOSURE"],
        first_week=1,
        planned_start_week=1,
        predecessor_activity_id=None,
        predecessor_last_week=None,
        horizon_weeks=4,
    )
    assert summary == (
        "A1 first access week 1; planned start week 1; kept on a separate "
        "physical slot by a closure buffer."
    )


def test_schedule_explanations_withhold_unsupported_span_facts(
    client,
    worker_session,
    minimal_instance_files,
    fake_solver_result,
    monkeypatch,
):
    codes = ["BUFFER_CLOSURE", "LIVE_MIRROR", "INTERCHANGE", "POSSESSION_MIX"]

    def with_displacement(compiled, scenario, **kwargs):
        return fake_solver_result(
            compiled, scenario, binding_reasons={"A1": list(codes)}
        )

    monkeypatch.setattr(rail_solver_worker, "solve", with_displacement)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    assert rail_solver_worker.process_next_job() is True

    body = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}/schedule").json()
    explanations = {item["activity_id"]: item for item in body["explanations"]}
    item = explanations["A1"]

    assert item["reason_codes"] == sorted(codes)
    evidence = item["evidence"]
    assert evidence["access_type"] == "C"
    assert evidence["buffer_sectors"] == 0
    assert evidence["closure_location_count"] >= 1

    # A1 carries no mirror or interchange spans of its own, so those codes must
    # degrade rather than report a false or zero fact as support.
    assert "opposite_bound_required" not in evidence
    assert "mirrored_location_count" not in evidence
    assert "interchange_location_count" not in evidence

    # A single-activity schedule at capacity 4 cannot justify capacity pressure
    # or co-sharing, so the read model must not claim either.
    assert "capacity_limit" not in evidence
    assert "co_share_partners" not in evidence
