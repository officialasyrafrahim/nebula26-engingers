"""Smoke tests for the Rail Access Optimisation application shell."""

from sqlalchemy import inspect

from app.domain.enums import JobState, RunState, Scenario, UserRole

KEY_TABLES = (
    "planning_runs",
    "scenario_jobs",
    "schedule_access_rows",
    "schedule_occupancy_rows",
    "contract_result_rows",
    "validator_report_rows",
    "audit_logs",
)


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_title_and_version(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    info = response.json()["info"]
    assert info["title"] == "Rail Access Optimisation"
    assert info["version"] == "2.0.0"


def test_rail_tables_created(engine):
    tables = set(inspect(engine).get_table_names())
    for name in KEY_TABLES:
        assert name in tables


def test_obsolete_tables_absent(engine):
    tables = set(inspect(engine).get_table_names())
    assert "assets" not in tables
    assert "plan_jobs" not in tables
    assert "telemetry_readings" not in tables


def test_enums_serialize():
    assert Scenario.A.value == "A"
    assert JobState.QUEUED.value == "QUEUED"
    assert RunState.QUEUED is JobState.QUEUED
    assert UserRole.PLANNER.value == "PLANNER"
