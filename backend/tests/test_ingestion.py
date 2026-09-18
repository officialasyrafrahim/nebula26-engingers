"""Detection-side ingestion tests (DAT-01, DAT-02)."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.domain.enums import DataQualityState
from app.domain.models import DataSource, DataSourceState
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_ingest_batch_accepts_valid_and_reports_invalid(client, db_session):
    component = _register(client, "T-200")
    now = _now()
    rows = [
        {
            "source_key": "feed-a",
            "component_id": component["id"],
            "ts": now.isoformat(),
            "channel": "temp",
            "value": 10.0,
        },
        {
            "source_key": "feed-a",
            "component_id": component["id"],
            "ts": (now + timedelta(seconds=1)).isoformat(),
            "channel": "temp",
            "value": 11.0,
        },
        {
            "source_key": "feed-b",
            "component_id": str(uuid.uuid4()),
            "ts": now.isoformat(),
            "channel": "temp",
            "value": 12.0,
        },
    ]

    response = client.post("/api/v1/ingest/telemetry", json=rows)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 2
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["index"] == 2
    assert body["rejected"][0]["reason"]

    state = db_session.scalar(
        select(DataSourceState)
        .join(DataSource, DataSource.id == DataSourceState.source_id)
        .where(DataSource.key == "feed-a")
    )
    assert state is not None
    assert state.state == DataQualityState.CURRENT
    assert state.last_valid_ts is not None


def test_refresh_flips_current_source_to_stale(client, db_session):
    component = _register(client, "T-201")
    now = _now()
    response = client.post(
        "/api/v1/ingest/telemetry",
        json=[
            {
                "source_key": "feed-stale",
                "component_id": component["id"],
                "ts": now.isoformat(),
                "channel": "temp",
                "value": 10.0,
            }
        ],
    )
    assert response.json()["accepted"] == 1

    state = db_session.scalar(
        select(DataSourceState)
        .join(DataSource, DataSource.id == DataSourceState.source_id)
        .where(DataSource.key == "feed-stale")
    )
    assert state.state == DataQualityState.CURRENT

    state.last_valid_ts = now - timedelta(seconds=1000)
    db_session.commit()

    refresh_source_states(db_session, now)

    assert state.state == DataQualityState.STALE


def test_ingest_reports_missing_required_fields_per_row(client, db_session):
    component = _register(client, "T-202")
    now = _now()
    rows = [
        {
            "source_key": "feed-fields",
            "component_id": component["id"],
            "ts": now.isoformat(),
            "channel": "temp",
            "value": 1.0,
        },
        {
            "source_key": "feed-fields",
            "component_id": component["id"],
            "channel": "temp",
            "value": 2.0,
        },
        {
            "source_key": "feed-fields",
            "component_id": component["id"],
            "ts": now.isoformat(),
            "value": 3.0,
        },
        {
            "source_key": "feed-fields",
            "component_id": component["id"],
            "ts": now.isoformat(),
            "channel": "temp",
        },
    ]

    response = client.post("/api/v1/ingest/telemetry", json=rows)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert {row["index"] for row in body["rejected"]} == {1, 2, 3}
    assert all(row["reason"] for row in body["rejected"])


def test_list_sources_reports_state(client, db_session):
    component = _register(client, "T-203")
    now = _now()
    client.post(
        "/api/v1/ingest/telemetry",
        json=[
            {
                "source_key": "feed-list",
                "component_id": component["id"],
                "ts": now.isoformat(),
                "channel": "temp",
                "value": 1.0,
            }
        ],
    )

    sources = client.get("/api/v1/ingest/sources").json()
    entry = next(item for item in sources if item["key"] == "feed-list")
    assert entry["state"] == "CURRENT"
    assert entry["last_valid_ts"] is not None

    state = client.get(f"/api/v1/ingest/sources/{entry['id']}/state").json()
    assert state["state"] == "CURRENT"
    assert state["source_id"] == entry["id"]


def test_refresh_marks_source_without_readings_missing(client, db_session):
    source = DataSource(key="feed-empty")
    db_session.add(source)
    db_session.commit()

    refresh_source_states(db_session, _now())

    state = db_session.scalar(
        select(DataSourceState).where(DataSourceState.source_id == source.id)
    )
    assert state is not None
    assert state.state == DataQualityState.MISSING
    assert state.last_valid_ts is None
