"""Truthfulness regressions for the solver explanation engine (F-EXPLAIN-001).

These tests build real CP-SAT schedules. They never inject reason codes, so the
evidence they check is the evidence the solver actually produced.

* Genuinely displaced work must cite the earlier rejected week and the
  constraint that blocked it, not a limit the chosen placement merely touched.
* A pair-level closure code must carry the conflicting counterpart's facts when
  the activity's own spans do not support it.
* Possession mix and co-share packing must only be claimed by an activity that
  actually shares a co_share_group with another activity.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.modules.runs.service import (
    _activity_evidence,
    _explanation_summary,
    _possession_conflict_facts,
)
from app.modules.solver import cp_sat_available, reasons, solve
from tests.test_rail_solver import HORIZON_START, make_compiled

pytestmark = pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)

SECTOR = "SEC:ALP:S01_S02:EB"


def _group_members(result) -> dict[tuple[str, int, str], set[str]]:
    members: dict[tuple[str, int, str], set[str]] = {}
    for row in result.occupancy:
        members.setdefault((row.location_id, row.week, row.co_share_group), set()).add(
            row.activity_id
        )
    return members


def _weeks_by_activity(result) -> dict[str, set[int]]:
    weeks: dict[str, set[int]] = {}
    for row in result.access:
        weeks.setdefault(row.activity_id, set()).add(row.week)
    return weeks


def _displaced_source_compiled():
    """Two incompatible contracts contending for one possession slot.

    Priority forces A1 into weeks 1 and 2, so A2 cannot start until week 3 even
    though its own planned start is week 1.
    """

    return make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Others)",
                "contract_priority": 1,
                "planned_completion_date": HORIZON_START + timedelta(days=6),
            },
            {
                "contract_number": "C2",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Others)",
                "contract_priority": 3,
                "planned_completion_date": HORIZON_START + timedelta(days=6),
            },
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 2,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 2,
            },
        ],
        capacities={SECTOR: 1},
    )


def test_genuinely_displaced_work_cites_rejected_week_and_constraint():
    compiled = _displaced_source_compiled()
    result = solve(compiled, "A", time_limit_seconds=10)

    assert result.feasible
    evidence = result.objective_breakdown["displacement_evidence"]
    displaced = {
        activity_id: item for activity_id, item in evidence.items() if item["displaced"]
    }
    assert displaced, "the solver should report at least one displaced activity"

    for activity_id, item in displaced.items():
        assert item["actual_first_week"] > item["planned_earliest_week"]
        assert item["earliest_possible_week"] == item["actual_first_week"]
        assert item["rejected_weeks"]
        assert item["binding_week"] == item["planned_earliest_week"]
        assert item["binding_constraints"]
        # Every code the gap cites must be a real code on the activity.
        for code in item["binding_constraints"]:
            assert code in result.binding_reasons[activity_id]
        # The binding details name the constraint with concrete facts.
        assert item["binding_details"]

    # The activity placed at its planned earliest is not displaced and must not
    # claim capacity or workfront pressure it never suffered.
    assert evidence["A1"]["displaced"] is False
    assert reasons.CAPACITY not in result.binding_reasons["A1"]
    assert reasons.WORKFRONT not in result.binding_reasons["A1"]


def test_displacement_evidence_names_a_real_binding_constraint():
    compiled = _displaced_source_compiled()
    result = solve(compiled, "A", time_limit_seconds=10)

    evidence = result.objective_breakdown["displacement_evidence"]["A2"]
    assert evidence["displaced"] is True
    assert evidence["binding_week"] == 1
    assert evidence["rejected_weeks"] == [1, 2]
    constraints = set(evidence["binding_constraints"])
    assert constraints
    assert constraints <= set(result.binding_reasons["A2"])
    assert "week" in next(iter(evidence["binding_details"].values()))


def _mirror_conflict_compiled():
    """A Live activity's opposite-bound mirror reaches a Non-live activity's route.

    A2 is dragged into a mirror conflict even though it has no mirrored span of
    its own (``opposite_bound_required`` is false and its mirrored list is empty).
    """

    return make_compiled(
        [
            {"contract_number": "C1", "access_type": "PC", "nature_of_activity": "Live"},
            {
                "contract_number": "C2",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
            },
        ],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                "start_location_id": "SEC:ALP:S01_S02:WB",
                "end_location_id": "SEC:ALP:S01_S02:WB",
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                "start_location_id": "SEC:ALP:S02_H01:EB",
                "end_location_id": "SEC:ALP:S02_H01:EB",
                "total_accesses": 1,
            },
        ],
        horizon_weeks=2,
    )


def test_pair_level_mirror_evidence_names_counterpart_not_own_zero():
    compiled = _mirror_conflict_compiled()
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    assert reasons.LIVE_MIRROR in result.binding_reasons["A2"]
    assert not compiled.activities["A2"].mirrored_locations

    facts = _possession_conflict_facts(compiled, _weeks_by_activity(result))
    evidence = _activity_evidence(
        result.binding_reasons["A2"],
        compiled.activities["A2"],
        [row for row in result.occupancy if row.activity_id == "A2"],
        _group_members(result),
        compiled,
        facts.get("A2", []),
        result.objective_breakdown["displacement_evidence"].get("A2"),
    )

    # The activity's own zero mirror span must not be presented as support.
    assert "opposite_bound_required" not in evidence
    assert "mirrored_location_count" not in evidence

    conflicts = evidence["possession_conflicts"]
    counterpart = next(
        item for item in conflicts if item["counterpart_activity_id"] == "A1"
    )
    assert counterpart["code"] == reasons.LIVE_MIRROR
    assert counterpart["counterpart_mirrored_location_count"] > 0
    assert counterpart["counterpart_opposite_bound_required"] is True


def _alone_in_group_compiled():
    return make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "PM",
                "nature_of_activity": "Non-live (Others)",
            },
            {
                "contract_number": "C2",
                "access_type": "PM",
                "nature_of_activity": "Non-live (Others)",
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
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
        capacities={SECTOR: 2},
        horizon_weeks=1,
    )


def test_alone_in_group_never_claims_possession_mix():
    compiled = _alone_in_group_compiled()
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    groups = {
        row.co_share_group
        for row in result.occupancy
        if row.location_id == SECTOR and row.week == 1
    }
    # The scenario really does hold two single-member groups; the old code
    # claimed possession mix purely because more than one group existed.
    assert len(groups) == 2
    members = _group_members(result)
    assert all(len(group) == 1 for group in members.values())
    for activity_id in ("A1", "A2"):
        assert reasons.POSSESSION_MIX not in result.binding_reasons[activity_id]
        assert reasons.CO_SHARE_PACKED not in result.binding_reasons[activity_id]


def test_shared_group_still_claims_possession_mix():
    compiled = make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "PC",
                "nature_of_activity": "Non-live (Others)",
            },
            {
                "contract_number": "C2",
                "access_type": "C",
                "nature_of_activity": "Non-live (Others)",
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
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )
    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    for activity_id in ("A1", "A2"):
        assert reasons.POSSESSION_MIX in result.binding_reasons[activity_id]
        assert reasons.CO_SHARE_PACKED in result.binding_reasons[activity_id]


def test_summary_reports_the_proven_gap_and_withholds_unproven_causes():
    proven = _explanation_summary(
        "A2",
        ["CAPACITY", "WORKFRONT"],
        first_week=3,
        planned_start_week=1,
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
    assert "earliest start week 1 blocked at week 1 by capacity pressure" in proven
    assert "used a location at its capacity limit" in proven
    assert "workfront limit" not in proven

    unproven = _explanation_summary(
        "A2",
        ["CAPACITY", "WORKFRONT"],
        first_week=3,
        planned_start_week=1,
        predecessor_activity_id=None,
        predecessor_last_week=None,
        horizon_weeks=4,
    )
    assert "capacity" not in unproven.lower()
    assert "workfront limit" not in unproven
