"""Smoke tests for the application skeleton."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect

from app.domain.enums import DataQualityState, JobState, UserRole
from app.modules.ingestion.service import evaluate_source_state

KEY_TABLES = (
    "assets",
    "components",
    "condition_events",
    "assessments",
    "work_packages",
    "plan_jobs",
    "schedule_proposals",
    "approvals",
    "published_schedules",
    "maintenance_outcomes",
    "model_versions",
    "audit_logs",
)


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Rail Maintenance Intelligence System"


def test_tables_created(engine):
    tables = set(inspect(engine).get_table_names())
    for name in KEY_TABLES:
        assert name in tables


def test_enums_serialize():
    assert JobState.QUEUED.value == "QUEUED"
    assert DataQualityState.CURRENT.value == "CURRENT"
    assert UserRole.PLANNER.value == "PLANNER"


def test_evaluate_source_state():
    now = datetime.now(timezone.utc)
    fresh = now - timedelta(seconds=10)
    stale = now - timedelta(seconds=600)
    assert evaluate_source_state(None, now, 300, 0.0) == DataQualityState.MISSING
    assert evaluate_source_state(stale, now, 300, 0.0) == DataQualityState.STALE
    assert evaluate_source_state(fresh, now, 300, 0.5) == DataQualityState.DEGRADED
    assert evaluate_source_state(fresh, now, 300, 0.0) == DataQualityState.CURRENT
