"""Independent physical witness check (F-VALIDATOR-005).

Unit cases build a tiny synthetic compiled instance and witness rows directly so
every check can be violated in isolation. The integration case solves a real
scenario and asserts the solver's own persisted physical slots pass the witness.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.modules.compiler.policy import get_policy
from app.modules.solver import cp_sat_available, solve
from app.modules.validator.witness import check_physical_witness
from tests.test_rail_solver import _single_sector, make_compiled

SECTOR = "SEC:ALP:S01_S02:EB"
INTERCHANGE = "SEC:ALP:H01_H02:EB"

CHECK_NAMES = [
    "slot_mix",
    "closure_simultaneity",
    "capacity_slots",
    "workfront_slots",
    "witness_available",
]


def _access(activity_id: str, week: int, physical_night: int | None):
    return SimpleNamespace(
        activity_id=activity_id, week=week, physical_night=physical_night
    )


def _occ(
    activity_id: str,
    week: int,
    location_id: str,
    co_share_group: str = "b1",
):
    return SimpleNamespace(
        activity_id=activity_id,
        week=week,
        location_id=location_id,
        co_share_group=co_share_group,
    )


def _checks(report):
    return {check.name: check for check in report.checks}


def _c_contract(contract_number: str = "C1"):
    return {
        "contract_number": contract_number,
        "access_type": "C",
        "nature_of_activity": "Non-live (Others)",
    }


def test_legal_witness_passes_every_check():
    compiled = make_compiled(
        [_c_contract()],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            }
        ],
    )

    report = check_physical_witness(
        compiled,
        get_policy("A"),
        [_access("A1", 1, 3)],
        [_occ("A1", 1, SECTOR)],
    )

    assert report.passed is True
    assert [check.name for check in report.checks] == CHECK_NAMES
    assert all(check.passed for check in report.checks)


def test_missing_physical_night_fails_closed():
    compiled = make_compiled(
        [_c_contract()],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            }
        ],
    )

    report = check_physical_witness(
        compiled,
        get_policy("A"),
        [_access("A1", 1, None)],
        [_occ("A1", 1, SECTOR)],
    )

    assert report.passed is False
    check = _checks(report)["witness_available"]
    assert check.passed is False
    assert check.detail["rows_without_physical_night"] == 1
    assert check.detail["activities_without_physical_night"] == ["A1"]


def test_no_access_rows_fails_closed():
    compiled = make_compiled(
        [_c_contract()],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            }
        ],
    )

    report = check_physical_witness(compiled, get_policy("A"), [], [])

    assert report.passed is False
    check = _checks(report)["witness_available"]
    assert check.passed is False
    assert check.detail["reason"] == "no access rows to witness"


def test_slot_mix_rejects_illegal_possession():
    contracts = [
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
    ]
    compiled = make_compiled(
        contracts,
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                **_single_sector(),
                "total_accesses": 1,
            },
        ],
    )

    report = check_physical_witness(
        compiled,
        get_policy("A"),
        [_access("A1", 1, 1), _access("A2", 1, 1)],
        [_occ("A1", 1, SECTOR), _occ("A2", 1, SECTOR)],
    )

    assert report.passed is False
    check = _checks(report)["slot_mix"]
    assert check.passed is False
    assert check.detail["violations"][0]["access_types"] == ["PM", "PM"]
    assert _checks(report)["closure_simultaneity"].passed is True


def test_closure_simultaneity_flags_unshared_simultaneous_conflict():
    contracts = [_c_contract("C1"), _c_contract("C2")]
    compiled = make_compiled(
        contracts,
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                **_single_sector(),
                "total_accesses": 1,
            },
        ],
    )

    report = check_physical_witness(
        compiled,
        get_policy("A"),
        [_access("A1", 1, 1), _access("A2", 1, 1)],
        [_occ("A1", 1, SECTOR, "b1"), _occ("A2", 1, SECTOR, "b2")],
    )

    assert report.passed is False
    check = _checks(report)["closure_simultaneity"]
    assert check.passed is False
    assert check.detail["strongest_rule"] == "closure"
    violation = check.detail["violations"][0]
    assert violation["rule"] == "closure"
    assert violation["physical_nights"] == [1]


def test_closure_simultaneity_waives_shared_possession():
    contracts = [_c_contract("C1"), _c_contract("C2")]
    compiled = make_compiled(
        contracts,
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                **_single_sector(),
                "total_accesses": 1,
            },
        ],
    )

    report = check_physical_witness(
        compiled,
        get_policy("A"),
        [_access("A1", 1, 1), _access("A2", 1, 1)],
        [_occ("A1", 1, SECTOR, "b1"), _occ("A2", 1, SECTOR, "b1")],
    )

    assert report.passed is True
    assert _checks(report)["closure_simultaneity"].passed is True


def test_capacity_slots_enforces_hard_limit_and_records_soft_excess():
    compiled = make_compiled(
        [_c_contract()],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            },
        ],
        capacities={SECTOR: 1},
        horizon_weeks=2,
    )

    report = check_physical_witness(
        compiled,
        get_policy("A"),
        [_access("A1", 1, 1), _access("A2", 1, 2)],
        [_occ("A1", 1, SECTOR, "b1"), _occ("A2", 1, SECTOR, "b2")],
    )

    check = _checks(report)["capacity_slots"]
    assert report.passed is False
    assert check.passed is False
    assert check.detail["hard_violations"][0]["hard_limit"] == 1
    assert check.detail["soft_excess_total"] == 1


def test_capacity_slots_records_soft_excess_without_hard_failure_under_b():
    compiled = make_compiled(
        [_c_contract()],
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            },
        ],
        capacities={SECTOR: 1},
        horizon_weeks=2,
    )

    report = check_physical_witness(
        compiled,
        get_policy("B"),
        [_access("A1", 1, 1), _access("A2", 1, 2)],
        [_occ("A1", 1, SECTOR, "b1"), _occ("A2", 1, SECTOR, "b2")],
    )

    check = _checks(report)["capacity_slots"]
    assert check.passed is True
    assert check.detail["hard_violations"] == []
    assert check.detail["soft_excess_total"] == 1
    assert report.passed is True


def test_workfront_slots_enforces_contract_cap():
    compiled = make_compiled(
        [_c_contract()],
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
                "start_location_id": INTERCHANGE,
                "end_location_id": INTERCHANGE,
                "total_accesses": 1,
            },
        ],
    )

    report = check_physical_witness(
        compiled,
        get_policy("A"),
        [_access("A1", 1, 1), _access("A2", 1, 1)],
        [_occ("A1", 1, SECTOR), _occ("A2", 1, INTERCHANGE)],
    )

    check = _checks(report)["workfront_slots"]
    assert report.passed is False
    assert check.passed is False
    violation = check.detail["violations"][0]
    assert violation["contract_number"] == "C1"
    assert violation["concurrent_activities"] == 2
    assert violation["workfront_cap"] == 1


@pytest.mark.skipif(
    not cp_sat_available(), reason="native OR-Tools CP-SAT runtime is unavailable"
)
def test_solved_schedule_passes_physical_witness():
    contracts = [
        {"contract_number": "C1", "access_type": "PC", "nature_of_activity": "Non-live (Others)"},
        {"contract_number": "C2", "access_type": "C", "nature_of_activity": "Non-live (Others)"},
    ]
    compiled = make_compiled(
        contracts,
        [
            {
                "activity_id": "A1",
                "contract_number": "C1",
                **_single_sector(),
                "total_accesses": 1,
            },
            {
                "activity_id": "A2",
                "contract_number": "C2",
                **_single_sector(),
                "total_accesses": 1,
            },
        ],
        capacities={SECTOR: 1},
        horizon_weeks=1,
    )

    result = solve(compiled, "A", time_limit_seconds=10, horizon_extension_weeks=0)

    assert result.feasible
    report = check_physical_witness(
        compiled,
        get_policy("A"),
        result.access,
        result.occupancy,
    )
    failed = [check for check in report.checks if not check.passed]
    assert report.passed is True, failed
