"""Regression tests for the backend safety and acceptance review fixes.

One shared seven-slot physical-night universe, stricter fallback physical
admissibility, congestion-safe adaptive horizon growth, hardened official
report parsing and reliable queue/worker lifecycle.
"""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from app.domain.enums import JobState
from app.domain.rail.nights import (
    PHYSICAL_NIGHT_SLOTS,
    PHYSICAL_NIGHTS_PER_WEEK,
    in_physical_night_universe,
)
from app.modules.compiler.policy import get_policy
from app.modules.solver.results import AccessPlacement
from app.modules.solver.variables import physical_night_count, physical_nights
from app.modules.validator import validate_bundle
from app.modules.validator.adapter import (
    OfficialValidatorError,
    report_from_official_payload,
    run_official_validator,
    validate_with_adapter,
)
from app.modules.validator.checks import physical as physical_check
from app.modules.validator.witness import check_physical_witness
from app.workers import rail_solver_worker
from tests.helpers_rail import PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR
from tests.test_physical_witness import _access, _checks, _occ
from tests.test_rail_solver import make_compiled
from tests.test_validator_fallback import (
    _bundle_for,
    _single_line_instance,
    _write_validator_script,
)

SECTOR = "SEC:ALP:S01_S02:EB"
DISJOINT_SECTOR = "SEC:ALP:S03_S04:EB"


# ---------------------------------------------------------------------------
# Shared physical-night universe
# ---------------------------------------------------------------------------


def test_the_physical_night_universe_is_exactly_seven_slots():
    assert PHYSICAL_NIGHTS_PER_WEEK == 7
    assert PHYSICAL_NIGHT_SLOTS == (1, 2, 3, 4, 5, 6, 7)
    assert in_physical_night_universe(1)
    assert in_physical_night_universe(7)
    assert not in_physical_night_universe(0)
    assert not in_physical_night_universe(8)


def test_solver_variables_consume_the_shared_universe():
    compiled = make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
                "number_of_maximum_access_per_week": 20,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            }
        ],
        capacities={SECTOR: 30, "PLAT:ALP:S01:EB": 30, "PLAT:ALP:S02:EB": 30},
    )

    assert physical_night_count(compiled) == 7
    assert physical_nights(compiled) == PHYSICAL_NIGHT_SLOTS


def test_access_placement_rejects_physical_night_outside_one_to_seven():
    base = {
        "activity_id": "A1",
        "access_seq": 1,
        "week": 1,
        "eclo": False,
        "access_night": 1,
    }
    assert AccessPlacement(**base, physical_night=7).physical_night == 7
    assert AccessPlacement(**base, physical_night=None).physical_night is None
    with pytest.raises(ValidationError):
        AccessPlacement(**base, physical_night=8)
    with pytest.raises(ValidationError):
        AccessPlacement(**base, physical_night=0)


def test_fallback_physical_check_uses_the_shared_universe():
    assert physical_check.PHYSICAL_NIGHTS_PER_WEEK is PHYSICAL_NIGHTS_PER_WEEK


# ---------------------------------------------------------------------------
# Witness physical-slot universe
# ---------------------------------------------------------------------------


def _single_activity_compiled():
    return make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            }
        ],
    )


def test_witness_accepts_all_seven_slots():
    compiled = _single_activity_compiled()
    report = check_physical_witness(
        compiled, get_policy("A"), [_access("A1", 1, 7)], [_occ("A1", 1, SECTOR)]
    )
    assert report.passed is True
    assert _checks(report)["physical_slot_universe"].passed is True


def test_witness_rejects_physical_night_outside_universe():
    compiled = _single_activity_compiled()
    report = check_physical_witness(
        compiled, get_policy("A"), [_access("A1", 1, 8)], [_occ("A1", 1, SECTOR)]
    )
    assert report.passed is False
    check = _checks(report)["physical_slot_universe"]
    assert check.passed is False
    assert check.detail["rows_outside_universe"] == 1
    assert check.detail["activities_outside_universe"] == ["A1"]


# ---------------------------------------------------------------------------
# Fallback same-class physical admissibility
# ---------------------------------------------------------------------------


def _reported_rules(report) -> set[str]:
    return set(report.rules)


def test_same_contract_incompatible_buffer_only_conflict_is_rejected():
    """PC+PC cannot co-share, so a same-class buffer overlap is provable."""

    instance = _single_line_instance(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Consist)",
                "number_of_workfronts": 2,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                "start_location_id": DISJOINT_SECTOR,
                "end_location_id": DISJOINT_SECTOR,
                "total_accesses": 1,
            },
        ],
    )
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )

    report = validate_bundle(instance, bundle, "A")
    assert report.feasible is False
    assert "closure" in _reported_rules(report)


def test_same_contract_compatible_buffer_only_conflict_stays_provisional():
    """C+C can co-share, so local-night identity alone is not a proof."""

    instance = _single_line_instance(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
                "nature_of_activity": "Non-live (Consist)",
                "number_of_workfronts": 2,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                "start_location_id": DISJOINT_SECTOR,
                "end_location_id": DISJOINT_SECTOR,
                "total_accesses": 1,
            },
        ],
    )
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )

    report = validate_bundle(instance, bundle, "A")
    assert report.feasible is True
    assert "closure" not in _reported_rules(report)


def test_cross_contract_incompatible_buffer_only_conflict_stays_provisional():
    """Unrelated local-night namespaces cannot prove cross-contract simultaneity."""

    instance = _single_line_instance(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Consist)",
                "number_of_workfronts": 1,
            },
            {
                "contract_number": "C2",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Consist)",
                "number_of_workfronts": 1,
            },
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                "start_location_id": DISJOINT_SECTOR,
                "end_location_id": DISJOINT_SECTOR,
                "total_accesses": 1,
            },
        ],
    )
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )

    report = validate_bundle(instance, bundle, "A")
    assert report.feasible is True
    assert "closure" not in _reported_rules(report)


def test_same_contract_opposite_bound_mirror_buffer_only_is_rejected():
    """Live EB mirroring onto WB is enforced even when the routes are disjoint."""

    instance = _single_line_instance(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Live",
                "number_of_workfronts": 2,
            }
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": "SEC:ALP:S01_S02:EB",
                "end_location_id": "SEC:ALP:S01_S02:EB",
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                "start_location_id": "SEC:ALP:S01_S02:WB",
                "end_location_id": "SEC:ALP:S01_S02:WB",
                "total_accesses": 1,
            },
        ],
    )
    bundle = _bundle_for(
        instance,
        {"A1": [(1, 1, 0)], "A2": [(1, 1, 0)]},
        groups={"A1": "b1", "A2": "b2"},
    )

    report = validate_bundle(instance, bundle, "A")
    assert report.feasible is False
    assert "mirror" in _reported_rules(report)


# ---------------------------------------------------------------------------
# Adaptive horizon safety
# ---------------------------------------------------------------------------


def test_unknown_attempt_expands_horizon_while_time_remains(monkeypatch):
    from app.modules.solver import engine
    from app.modules.solver.results import SolverResult

    compiled = make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "PM",
                "nature_of_activity": "Non-live (Others)",
            }
        ],
        [
            {
                "activity_id": f"A{index}",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            }
            for index in range(1, 6)
        ],
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )

    horizons: list[int] = []

    def fake_attempt(cp, compiled, policy, total_weeks, budget, seed, *, incumbent=None):
        horizons.append(total_weeks)
        if len(horizons) == 1:
            return SolverResult(
                feasible=False,
                scenario=policy.scenario,
                status="UNKNOWN",
                horizon_weeks_used=0,
                objective_breakdown={},
                infeasibility_reasons=("timeout",),
            )
        return SolverResult(
            feasible=True,
            scenario=policy.scenario,
            status="FEASIBLE",
            horizon_weeks_used=total_weeks,
            objective_breakdown={},
        )

    monkeypatch.setattr(engine, "load_cp_model", lambda: None)
    monkeypatch.setattr(engine, "_attempt", fake_attempt)

    result = engine.solve(
        compiled, "A", time_limit_seconds=10, horizon_extension_weeks=2
    )

    assert result.feasible is True
    assert len(horizons) >= 2
    assert horizons[1] > horizons[0]


# ---------------------------------------------------------------------------
# Official validator report hardening
# ---------------------------------------------------------------------------


def _official_payload(**overrides) -> dict:
    payload = {
        "scenario": "A",
        "feasible": True,
        "workload_complete": True,
        "ready_for_submission": True,
        "hard_violations": [],
        "soft_scores": {},
        "detail": {},
    }
    payload.update(overrides)
    return payload


def test_adapter_rejects_non_object_payload():
    with pytest.raises(OfficialValidatorError):
        report_from_official_payload(["not", "an", "object"])


def test_adapter_rejects_unknown_scenario():
    with pytest.raises(OfficialValidatorError):
        report_from_official_payload(_official_payload(scenario="Z"))


def test_adapter_rejects_request_mismatched_scenario():
    with pytest.raises(OfficialValidatorError):
        report_from_official_payload(
            _official_payload(scenario="B"), requested_scenario="A"
        )


def test_adapter_hard_violation_cannot_yield_ready():
    report = report_from_official_payload(
        _official_payload(
            hard_violations=[{"rule": "closure", "detail": "wk1 overlap"}],
            feasible=True,
            workload_complete=True,
            ready_for_submission=True,
        )
    )
    assert report.feasible is False
    assert report.ready_for_submission is False
    assert report.hard_violations


def test_adapter_infeasible_status_cannot_yield_ready():
    report = report_from_official_payload(_official_payload(status="INFEASIBLE"))
    assert report.feasible is False
    assert report.ready_for_submission is False


def test_adapter_workload_violation_cannot_yield_ready():
    report = report_from_official_payload(
        _official_payload(
            hard_violations=[{"rule": "workload", "detail": "missing access"}],
            ready_for_submission=True,
        )
    )
    assert report.workload_complete is False
    assert report.ready_for_submission is False


def test_adapter_contradictory_readiness_is_forced_false():
    report = report_from_official_payload(
        _official_payload(feasible=False, ready_for_submission=True)
    )
    assert report.feasible is False
    assert report.ready_for_submission is False


def test_adapter_malformed_hard_violations_raise():
    with pytest.raises(OfficialValidatorError):
        report_from_official_payload(_official_payload(hard_violations={"rule": "x"}))
    with pytest.raises(OfficialValidatorError):
        report_from_official_payload(_official_payload(hard_violations=[42]))


def test_adapter_malformed_soft_scores_raise():
    with pytest.raises(OfficialValidatorError):
        report_from_official_payload(_official_payload(soft_scores=[1, 2, 3]))


def test_run_official_validator_rejects_mismatched_scenario(tmp_path):
    command = _write_validator_script(
        tmp_path,
        stdout=json.dumps(
            {
                "scenario": "B",
                "feasible": True,
                "workload_complete": True,
                "ready_for_submission": True,
                "hard_violations": [],
            }
        ),
    )
    with pytest.raises(OfficialValidatorError):
        run_official_validator(command, PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR, "A")


def test_adapter_never_labels_a_contradictory_report_ready(tmp_path):
    command = _write_validator_script(
        tmp_path,
        stdout=json.dumps(
            {
                "scenario": "A",
                "feasible": True,
                "workload_complete": True,
                "ready_for_submission": True,
                "hard_violations": [{"rule": "closure", "detail": "wk1 overlap"}],
            }
        ),
    )
    outcome = validate_with_adapter(
        PUBLIC_INSTANCE_DIR, SUBMISSION_SAMPLE_DIR, "A", command=command
    )
    assert outcome.report.authority == "official"
    assert outcome.report.feasible is False
    assert outcome.report.ready_for_submission is False


# ---------------------------------------------------------------------------
# Queue and worker reliability
# ---------------------------------------------------------------------------


def _upload(client, files):
    return client.post(
        "/api/v1/runs",
        files=[("files", (name, data, "text/csv")) for name, data in files.items()],
    )


def _submit(client, run_id, scenario="A"):
    return client.post(f"/api/v1/runs/{run_id}/jobs", json={"scenario": scenario})


def test_enqueue_failure_marks_job_failed(client, minimal_instance_files, monkeypatch):
    from app.modules.runs import service

    class BrokenQueue:
        def enqueue(self, job_id):
            raise RuntimeError("queue unreachable")

        def dequeue(self, timeout=None):
            return None

    monkeypatch.setattr(service, "get_queue", lambda: BrokenQueue())
    run_id = _upload(client, minimal_instance_files).json()["id"]

    response = _submit(client, run_id, "A")

    assert response.status_code == 503
    jobs = client.get(f"/api/v1/runs/{run_id}/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["state"] == JobState.FAILED.value
    assert "could not enqueue" in jobs[0]["error"]


def test_terminal_state_mapping_separates_errors_from_infeasibility():
    assert (
        rail_solver_worker._terminal_state_for_solver("INFEASIBLE")
        == JobState.INFEASIBLE
    )
    assert rail_solver_worker._terminal_state_for_solver("UNKNOWN") == JobState.TIMED_OUT
    assert (
        rail_solver_worker._terminal_state_for_solver("MODEL_INVALID")
        == JobState.FAILED
    )


def test_worker_marks_model_error_failed_not_infeasible(
    client, worker_session, minimal_instance_files, fake_solver_result, monkeypatch
):
    def model_error(compiled, scenario, **kwargs):
        return fake_solver_result(
            compiled, scenario, status="MODEL_INVALID", feasible=False
        )

    monkeypatch.setattr(rail_solver_worker, "solve", model_error)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    assert rail_solver_worker.process_next_job() is True

    job = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}").json()
    assert job["state"] == JobState.FAILED.value
    assert "MODEL_INVALID" in job["error"]


def test_worker_honours_cancel_requested_during_solve(
    client, worker_session, minimal_instance_files, fake_solver_result, monkeypatch
):
    from app.domain.models import ScenarioJob

    def solve_then_cancel(compiled, scenario, **kwargs):
        job = worker_session.get(ScenarioJob, uuid.UUID(job_holder["id"]))
        job.cancel_requested = True
        worker_session.commit()
        return fake_solver_result(compiled, scenario)

    job_holder: dict[str, str] = {}
    monkeypatch.setattr(rail_solver_worker, "solve", solve_then_cancel)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]
    job_holder["id"] = job_id

    assert rail_solver_worker.process_next_job() is True

    job = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}").json()
    assert job["state"] == JobState.CANCELLED.value


def test_persistence_failure_marks_job_failed_and_keeps_loop_alive(
    client, worker_session, minimal_instance_files, fake_solver_result, monkeypatch
):
    monkeypatch.setattr(rail_solver_worker, "solve", fake_solver_result)

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(rail_solver_worker, "_persist_success", boom)
    run_id = _upload(client, minimal_instance_files).json()["id"]
    job_id = _submit(client, run_id, "A").json()["id"]

    assert rail_solver_worker.process_next_job() is True

    job = client.get(f"/api/v1/runs/{run_id}/jobs/{job_id}").json()
    assert job["state"] == JobState.FAILED.value
    assert "could not persist result" in job["error"]


def test_run_worker_initializes_schema_before_consuming(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(
        rail_solver_worker, "initialize_database", lambda: calls.append("init")
    )

    def stop(timeout):
        raise KeyboardInterrupt

    monkeypatch.setattr(rail_solver_worker, "process_next_job", stop)

    rail_solver_worker.run_worker()

    assert calls == ["init"]
