"""Exact export schemas, stable order and zip members (AT-13, OUT-01..OUT-04)."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

import pytest

from app.modules.export import (
    ACCESS_FILE,
    ACCESS_HEADER,
    OCCUPANCY_FILE,
    OCCUPANCY_HEADER,
    RESULTS_FILE,
    RESULTS_HEADER,
    SUBMISSION_FILES,
    AccessRow,
    OccupancyRow,
    ResultRow,
    SubmissionParseError,
    archive_members,
    export_scenario_zip,
    export_scenarios_zip,
    load_bundle,
    parse_access,
    parse_results,
    render_access,
    render_occupancy,
    render_results,
    scenario_archive_name,
)
from app.modules.export.bundle import bundle_from_solver_result, parse_bundle
from app.modules.solver.results import (
    AccessPlacement,
    ContractResult,
    OccupancyPlacement,
    SolverResult,
)
from tests.helpers_rail import SUBMISSION_SAMPLE_DIR


def _sample_sources() -> dict[str, str]:
    return {
        name: (SUBMISSION_SAMPLE_DIR / name).read_text(encoding="utf-8")
        for name in SUBMISSION_FILES
    }


def test_headers_are_exact_and_ordered():
    assert ACCESS_HEADER == (
        "activity_id",
        "access_seq",
        "week",
        "eclo",
        "access_night",
    )
    assert OCCUPANCY_HEADER == (
        "activity_id",
        "week",
        "location_id",
        "co_share_group",
    )
    assert RESULTS_HEADER == (
        "scenario",
        "contract_number",
        "simulated_completion_date",
        "overrun_days",
    )
    assert SUBMISSION_FILES == (ACCESS_FILE, OCCUPANCY_FILE, RESULTS_FILE)


def test_sample_round_trips_byte_for_byte():
    sources = _sample_sources()
    bundle = parse_bundle(sources)
    rendered = bundle.render_files()
    for name in SUBMISSION_FILES:
        assert rendered[name] == sources[name]


def test_rendered_files_use_lf_trailing_newline_and_no_bom():
    bundle = load_bundle(SUBMISSION_SAMPLE_DIR)
    for name, text in bundle.render_files().items():
        assert not text.startswith("\ufeff"), name
        assert "\r\n" not in text, name
        assert text.endswith("\n"), name


def test_stable_order_is_independent_of_input_order():
    bundle = load_bundle(SUBMISSION_SAMPLE_DIR)
    reversed_access = tuple(reversed(bundle.access))
    reversed_occupancy = tuple(reversed(bundle.occupancy))
    reversed_results = tuple(reversed(bundle.results))
    shuffled = bundle.model_copy(
        update={
            "access": reversed_access,
            "occupancy": reversed_occupancy,
            "results": reversed_results,
        }
    )
    assert shuffled.render_files() == bundle.render_files()


def test_access_render_sorts_by_activity_then_sequence():
    rows = [
        AccessRow(activity_id="A2", access_seq=1, week=1, eclo=0, access_night=1),
        AccessRow(activity_id="A1", access_seq=2, week=2, eclo=1, access_night=2),
        AccessRow(activity_id="A1", access_seq=1, week=1, eclo=0, access_night=1),
    ]
    text = render_access(rows)
    parsed = list(csv.reader(io.StringIO(text)))
    assert parsed[1] == ["A1", "1", "1", "0", "1"]
    assert parsed[2] == ["A1", "2", "2", "1", "2"]
    assert parsed[3] == ["A2", "1", "1", "0", "1"]


def test_occupancy_render_sorts_by_activity_week_location():
    rows = [
        OccupancyRow(activity_id="A1", week=2, location_id="PLAT:ALP:S02:EB", co_share_group="b1"),
        OccupancyRow(activity_id="A1", week=1, location_id="PLAT:ALP:S01:EB", co_share_group="b2"),
        OccupancyRow(activity_id="A1", week=1, location_id="PLAT:ALP:S02:EB", co_share_group="b1"),
    ]
    lines = render_occupancy(rows).strip().splitlines()
    assert lines[1].startswith("A1,1,PLAT:ALP:S01:EB")
    assert lines[2].startswith("A1,1,PLAT:ALP:S02:EB")
    assert lines[3].startswith("A1,2,PLAT:ALP:S02:EB")


def test_results_render_sorts_by_contract():
    rows = [
        ResultRow(
            scenario="A",
            contract_number="C002",
            simulated_completion_date=date(2027, 1, 10),
            overrun_days=0,
        ),
        ResultRow(
            scenario="A",
            contract_number="C001",
            simulated_completion_date=date(2027, 1, 3),
            overrun_days=2,
        ),
    ]
    parsed = list(csv.reader(io.StringIO(render_results(rows))))
    assert parsed[1] == ["A", "C001", "2027-01-03", "2"]
    assert parsed[2] == ["A", "C002", "2027-01-10", "0"]


def test_bad_header_is_rejected():
    with pytest.raises(SubmissionParseError):
        parse_access("activity_id,access_seq,week,eclo\nA1,1,1,0\n")


def test_bad_eclo_value_is_rejected():
    with pytest.raises(SubmissionParseError):
        parse_access(
            "activity_id,access_seq,week,eclo,access_night\nA1,1,1,7,1\n"
        )


def test_results_parse_rejects_bad_date():
    with pytest.raises(SubmissionParseError):
        parse_results(
            "scenario,contract_number,simulated_completion_date,overrun_days\n"
            "A,C001,not-a-date,0\n"
        )


def test_zip_members_are_exactly_the_three_files():
    bundle = load_bundle(SUBMISSION_SAMPLE_DIR)
    payload = export_scenario_zip(bundle)
    assert archive_members(payload) == SUBMISSION_FILES
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in SUBMISSION_FILES:
            assert archive.read(name).decode("utf-8") == bundle.render_files()[name]


def test_multi_scenario_zip_prefixes_each_scenario():
    bundle = load_bundle(SUBMISSION_SAMPLE_DIR)
    payload = export_scenarios_zip([bundle])
    assert archive_members(payload) == tuple(
        f"scenario_A/{name}" for name in SUBMISSION_FILES
    )


def test_scenario_archive_name():
    assert scenario_archive_name("B") == "scenario_B_submission.zip"


def test_bundle_from_solver_result_preserves_rows():
    result = SolverResult(
        feasible=True,
        scenario="A",
        status="OPTIMAL",
        horizon_weeks_used=2,
        access=(
            AccessPlacement(
                activity_id="A1", access_seq=1, week=1, eclo=False, access_night=1
            ),
            AccessPlacement(
                activity_id="A1", access_seq=2, week=2, eclo=True, access_night=2
            ),
        ),
        occupancy=(
            OccupancyPlacement(
                activity_id="A1",
                week=1,
                location_id="SEC:ALP:S01_S02:EB",
                co_share_group="b1",
            ),
        ),
        contract_results=(
            ContractResult(
                contract_number="C001",
                contract_priority=3,
                planned_completion_date=date(2027, 1, 10),
                simulated_completion_date=date(2027, 1, 17),
                overrun_days=7,
                last_week=2,
            ),
        ),
    )
    bundle = bundle_from_solver_result(result)
    assert bundle.scenario == "A"
    assert bundle.access[1].eclo == 1
    assert bundle.occupancy[0].co_share_group == "b1"
    assert bundle.results[0].overrun_days == 7
