"""Detection-side condition and assessment tests (DET-01, DET-02, ASM-01..03, WPK-01)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.domain.enums import DataQualityState, EvidenceType
from app.domain.models import ConditionEvent, DataSource, DataSourceState
from app.modules.ingestion.service import refresh_source_states


def _register(client, label: str) -> dict:
    asset = client.post(
        "/api/v1/assets",
        json={"fleet": "FLT-1", "label": label, "asset_type": "EMU"},
    ).json()
    component = client.post(
        f"/api/v1/assets/{asset['id']}/components",
        json={"asset_id": asset["id"], "component_type": "BOGIE"},
    ).json()
    return component


def _ingest(client, component_id: str, values: list[float], source_key: str) -> dict:
    now = datetime.now(timezone.utc)
    rows = [
        {
            "source_key": source_key,
            "component_id": component_id,
            "ts": (now + timedelta(seconds=index)).isoformat(),
            "channel": "vibration",
            "value": value,
        }
        for index, value in enumerate(values)
    ]
    response = client.post("/api/v1/ingest/telemetry", json=rows)
    assert response.status_code == 200
    return response.json()


def _detect(client, label: str, values: list[float]) -> dict:
    component = _register(client, label)
    result = _ingest(client, component["id"], values, f"feed-{label}")
    assert result["accepted"] == len(values)
    response = client.post(f"/api/v1/conditions/detect/{component['id']}")
    assert response.status_code == 201
    return response.json()


def test_detect_current_produces_scored_event_with_evidence(client, db_session):
    component = _register(client, "T-300")
    values = [10.0 + (index % 3 - 1) * 0.1 for index in range(20)] + [100.0]
    assert _ingest(client, component["id"], values, "feed-T-300")["accepted"] == len(values)

    response = client.post(f"/api/v1/conditions/detect/{component['id']}")

    assert response.status_code == 201
    body = response.json()
    assert body["score"] > 0
    assert body["data_quality"] == "CURRENT"
    assert body["evidence"]["window"]

    evidence = client.get(f"/api/v1/conditions/{body['id']}/evidence").json()
    types = {item["type"] for item in evidence}
    assert EvidenceType.OBSERVATION.value in types
    assert EvidenceType.MODEL_INFERENCE.value in types

    listed = client.get("/api/v1/conditions").json()
    assert any(item["id"] == body["id"] for item in listed)
    fetched = client.get(f"/api/v1/conditions/{body['id']}").json()
    assert fetched["id"] == body["id"]


def test_detect_stale_input_returns_conflict_without_current_event(client, db_session):
    component = _register(client, "T-301")
    _ingest(client, component["id"], [10.0, 10.1, 10.2], "feed-T-301")
    state = db_session.scalar(
        select(DataSourceState)
        .join(DataSource, DataSource.id == DataSourceState.source_id)
        .where(DataSource.key == "feed-T-301")
    )
    now = datetime.now(timezone.utc)
    state.last_valid_ts = now - timedelta(seconds=1000)
    db_session.commit()

    refresh_source_states(db_session, now)

    response = client.post(f"/api/v1/conditions/detect/{component['id']}")

    assert response.status_code == 409
    assert response.json()["detail"] == "input not current: STALE"
    current = db_session.scalars(
        select(ConditionEvent).where(ConditionEvent.data_quality == DataQualityState.CURRENT)
    ).all()
    assert current == []


def test_assessment_rules_cover_critical_and_monitor(client, db_session):
    high = _detect(client, "T-302", [10.0] * 19 + [500.0])
    high_response = client.post(
        "/api/v1/assessments", json={"condition_event_id": high["id"]}
    )
    assert high_response.status_code == 201
    high_body = high_response.json()
    assert high_body["recommendation"] == "MAINTAIN"
    assert high_body["priority"] == "CRITICAL"
    assert high_body["horizon_hours"] == 24
    assert high_body["rationale"]["context"] == "unavailable"

    evidence = client.get(f"/api/v1/assessments/{high_body['id']}/evidence").json()
    types = {item["type"] for item in evidence}
    assert EvidenceType.OBSERVATION.value in types
    assert EvidenceType.MODEL_INFERENCE.value in types

    low = _detect(client, "T-303", [10.0] * 20)
    low_body = client.post(
        "/api/v1/assessments", json={"condition_event_id": low["id"]}
    ).json()
    assert low_body["recommendation"] == "MONITOR"
    assert low_body["priority"] == "LOW"


def test_work_package_copies_priority_without_fabrication(client, db_session):
    high = _detect(client, "T-304", [10.0] * 19 + [500.0])
    assessment = client.post(
        "/api/v1/assessments", json={"condition_event_id": high["id"]}
    ).json()

    response = client.post("/api/v1/work-packages", json={"assessment_id": assessment["id"]})

    assert response.status_code == 201
    body = response.json()
    assert body["priority"] == assessment["priority"]
    assert body["state"] == "CREATED"
    assert body["title"]
    assert body["competency"] is None
    assert body["est_duration_min"] is None
    assert body["tools"] is None
    assert body["parts"] is None
