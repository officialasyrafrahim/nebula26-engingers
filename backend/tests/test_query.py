"""Deterministic schedule query layer (F-BONUS-003).

The unit tests build a query context from synthetic persisted evidence, so they
need no CP-SAT runtime and no database. They pin four promises:

* the closed grammar parses the supported forms and rejects everything else;
* a supported query with evidence answers from that evidence and cites it;
* a supported query without evidence is reported unanswerable, never guessed;
* the answers are deterministic and the module performs no data egress.

An API round trip proves the query layer is reachable from the existing runs
router against a real persisted schedule.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from app.modules.explain import query as query_module
from app.modules.explain.query import (
    AccessEvidence,
    ContractEvidence,
    OccupancyEvidence,
    QueryContext,
    QuerySyntaxError,
)
from app.workers import rail_solver_worker
from tests.conftest import MINIMAL_INSTANCE_FILES
from tests.test_rail_solver import make_compiled

SECTOR = "SEC:ALP:S01_S02:EB"
PLANNED_COMPLETION = date(2027, 1, 31)


def _context() -> QueryContext:
    compiled = make_compiled(
        [
            {
                "contract_number": "C1",
                "access_type": "C",
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
                "contract_number": "C1",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
                "predecessor_activity_id": "A1",
            },
            {
                "activity_id": "B1",
                "contract_number": "C2",
                "start_location_id": SECTOR,
                "end_location_id": SECTOR,
                "total_accesses": 1,
            },
        ],
        capacities={SECTOR: 4},
        horizon_weeks=4,
    )
    return QueryContext(
        scenario="A",
        horizon_weeks=4,
        horizon_start=compiled.instance.horizon_start,
        compiled=compiled,
        access=(
            AccessEvidence("A1", 1, 1, False, 1, 1),
            AccessEvidence("A2", 1, 2, False, 1, 1),
            AccessEvidence("B1", 1, 1, False, 2, 2),
        ),
        occupancy=(
            OccupancyEvidence("A1", 1, SECTOR, "b1"),
            OccupancyEvidence("A2", 2, SECTOR, "b1"),
            OccupancyEvidence("B1", 1, SECTOR, "b1"),
        ),
        contracts=(
            ContractEvidence("C1", PLANNED_COMPLETION, 0),
            ContractEvidence("C2", PLANNED_COMPLETION, 0),
        ),
        binding_reasons={"A2": ("PREDECESSOR",)},
        displacement_evidence={
            "A2": {
                "displaced": True,
                "planned_earliest_week": 1,
                "actual_first_week": 2,
                "binding_week": 1,
                "binding_constraints": ["CAPACITY"],
                "rejected_weeks": [1],
            }
        },
    )


def _answer(context: QueryContext, text: str):
    return query_module.answer_query(context, query_module.parse_query(text))


def test_parse_supported_forms():
    assert query_module.parse_query("why A1").kind == "why_moved"
    assert query_module.parse_query("WHY A1").activity_id == "A1"
    assert query_module.parse_query("downstream A1").kind == "downstream_risk"
    capacity = query_module.parse_query("capacity SEC:ALP:S01_S02:EB week 3")
    assert capacity.kind == "capacity_check"
    assert capacity.week == 3
    assert capacity.location_id == SECTOR
    assert query_module.parse_query("co-share SEC:ALP:S01_S02:EB week 3").kind == (
        "capacity_check"
    )
    assert query_module.parse_query("milestone C1").kind == "milestone_brief"
    assert query_module.parse_query("handover C1").kind == "milestone_brief"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "why",
        "why A1 A2",
        "capacity SEC:ALP:S01_S02:EB",
        "capacity SEC:ALP:S01_S02:EB week zero",
        "drop table schedule",
        "explain why A1 moved",
    ],
)
def test_parse_rejects_unsupported_shapes(text):
    with pytest.raises(QuerySyntaxError):
        query_module.parse_query(text)


def test_why_answer_cites_persisted_evidence():
    result = _answer(_context(), "why A2")

    assert result.answerable is True
    assert result.kind == "why_moved"
    assert "A2 first access week 2" in result.answer
    assert "blocked at week 1 by capacity pressure" in result.answer
    assert result.evidence["reason_codes"] == ["PREDECESSOR"]
    assert result.evidence["displaced"] is True

    sources = {citation.source for citation in result.citations}
    assert "schedule_access" in sources
    assert "job_result.binding_reasons" in sources
    assert "job_result.displacement_evidence" in sources


def test_why_without_evidence_is_reported_unanswerable():
    result = _answer(_context(), "why Z9")

    assert result.answerable is False
    assert result.answer.startswith("Cannot answer")
    assert result.citations == ()


def test_downstream_risk_reports_direct_coupling():
    result = _answer(_context(), "downstream A1")

    assert result.answerable is True
    assert result.evidence["direct_successors"] == ["A2"]
    successor = result.evidence["successors"][0]
    assert successor["activity_id"] == "A2"
    assert successor["slack_weeks"] == 0
    assert successor["coupling"] == "direct"
    assert any(
        citation.fields.get("role") == "successor" for citation in result.citations
    )


def test_capacity_check_reports_co_sharing():
    result = _answer(_context(), f"capacity {SECTOR} week 1")

    assert result.answerable is True
    assert result.evidence["possessions_used"] == 1
    assert result.evidence["supply_capacity"] == 4
    assert result.evidence["excess"] == 0
    assert result.evidence["co_shared_groups"] == {"b1": ["A1", "B1"]}
    assert any(
        citation.source == "schedule_occupancy" for citation in result.citations
    )


def test_capacity_check_without_work_is_clear_but_honest():
    result = _answer(_context(), f"capacity {SECTOR} week 4")

    assert result.answerable is True
    assert result.evidence["possessions_used"] == 0
    assert "no scheduled occupancy" in result.answer


def test_capacity_check_for_unknown_location_is_unanswerable():
    result = _answer(_context(), "capacity NOPE week 1")

    assert result.answerable is False


def test_milestone_brief_uses_persisted_result():
    result = _answer(_context(), "milestone C1")

    assert result.answerable is True
    assert result.evidence["overrun_days"] == 0
    assert result.evidence["last_access_week"] == 2
    assert result.evidence["activity_count"] == 2
    assert result.evidence["planned_completion_date"] == PLANNED_COMPLETION.isoformat()
    assert any(citation.source == "contract_result" for citation in result.citations)


def test_milestone_for_unknown_contract_is_unanswerable():
    result = _answer(_context(), "milestone NOPE")

    assert result.answerable is False


def test_answers_are_deterministic():
    context = _context()
    first = _answer(context, "why A2")
    second = _answer(context, "why A2")

    assert first.answer == second.answer
    assert dict(first.evidence) == dict(second.evidence)
    assert first.citations == second.citations


def test_query_module_performs_no_data_egress():
    source = inspect.getsource(query_module)

    for forbidden in ("httpx", "requests", "urllib", "aiohttp", "socket", "open("):
        assert forbidden not in source


def _minimal_files() -> dict[str, bytes]:
    return {
        name: text.encode("utf-8") for name, text in MINIMAL_INSTANCE_FILES.items()
    }


def test_query_api_round_trip(
    client, worker_session, fake_solver_result, monkeypatch
):
    monkeypatch.setattr(rail_solver_worker, "solve", fake_solver_result)

    run = client.post(
        "/api/v1/runs",
        files=[
            ("files", (name, data, "text/csv"))
            for name, data in _minimal_files().items()
        ],
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    job = client.post(f"/api/v1/runs/{run_id}/jobs", json={"scenario": "A"})
    assert job.status_code == 202
    job_id = job.json()["id"]
    assert rail_solver_worker.process_next_job() is True

    response = client.post(
        f"/api/v1/runs/{run_id}/jobs/{job_id}/query",
        json={"query": "why A1"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "why_moved"
    assert body["answerable"] is True
    assert body["citations"]

    capacity = client.post(
        f"/api/v1/runs/{run_id}/jobs/{job_id}/query",
        json={"query": f"capacity {SECTOR} week 1"},
    )
    assert capacity.status_code == 200
    assert capacity.json()["answerable"] is True

    unsupported = client.post(
        f"/api/v1/runs/{run_id}/jobs/{job_id}/query",
        json={"query": "tell me everything"},
    )
    assert unsupported.status_code == 422


def test_query_api_rejects_a_job_that_has_not_completed(client):
    run = client.post(
        "/api/v1/runs",
        files=[
            ("files", (name, data, "text/csv"))
            for name, data in _minimal_files().items()
        ],
    )
    run_id = run.json()["id"]
    job = client.post(f"/api/v1/runs/{run_id}/jobs", json={"scenario": "A"})
    job_id = job.json()["id"]

    response = client.post(
        f"/api/v1/runs/{run_id}/jobs/{job_id}/query",
        json={"query": "why A1"},
    )
    assert response.status_code == 409
