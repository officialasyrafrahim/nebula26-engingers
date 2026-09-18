"""Ingestion service.

ERD requirements: DAT-01, DAT-02, PERF-01.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import DataQualityState
from app.domain.models import (
    Component,
    DataSource,
    DataSourceState,
    TelemetryReading,
    utcnow,
)
from app.domain.schemas import TelemetryReadingIn


@dataclass
class RejectedRow:
    """One rejected reading with its batch index and reason."""

    index: int
    reason: str


@dataclass
class IngestBatchResult:
    """Outcome of a telemetry batch."""

    accepted: int
    rejected: list[RejectedRow] = field(default_factory=list)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve_component(
    db: Session,
    component_id: uuid.UUID | None,
    component_serial: str | None,
) -> Component | None:
    if component_id is not None:
        return db.get(Component, component_id)
    if component_serial:
        return db.scalar(select(Component).where(Component.serial == component_serial))
    return None


def _upsert_source(db: Session, key: str) -> DataSource:
    source = db.scalar(select(DataSource).where(DataSource.key == key))
    if source is None:
        source = DataSource(key=key)
        db.add(source)
        db.flush()
    return source


def _state_for(db: Session, source: DataSource) -> DataSourceState:
    state = db.scalar(select(DataSourceState).where(DataSourceState.source_id == source.id))
    if state is None:
        state = DataSourceState(source_id=source.id)
        db.add(state)
        db.flush()
    return state


def _apply_source_state(
    db: Session,
    source: DataSource,
    valid: list[tuple[datetime, Component]],
    invalid: int,
    now: datetime,
) -> DataSourceState:
    state = _state_for(db, source)
    existing = _as_utc(state.last_valid_ts) if state.last_valid_ts is not None else None
    latest_valid = max((ts for ts, _ in valid), default=None)
    newest = max((value for value in (existing, latest_valid) if value is not None), default=None)
    total = len(valid) + invalid
    invalid_ratio = invalid / total if total else 0.0
    state.last_valid_ts = newest
    if newest is None:
        state.state = DataQualityState.INVALID
    else:
        state.state = evaluate_source_state(
            newest, now, get_settings().stale_after_seconds, invalid_ratio
        )
    state.updated_at = now
    return state


def ingest_telemetry_batch(db: Session, readings: list[Any]) -> IngestBatchResult:
    """Validate and persist a batch of telemetry readings."""
    # TODO(DAT-01): add bounded buffering/backpressure policy.
    now = utcnow()
    result = IngestBatchResult(accepted=0)
    valid_by_source: dict[str, list[tuple[datetime, Component]]] = {}
    invalid_by_source: dict[str, int] = {}
    for index, raw in enumerate(readings):
        raw_key = raw.get("source_key") if isinstance(raw, dict) else None
        try:
            row = TelemetryReadingIn.model_validate(raw)
        except ValidationError as exc:
            reason = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
            result.rejected.append(RejectedRow(index=index, reason=reason or "invalid reading"))
            if isinstance(raw_key, str) and raw_key:
                invalid_by_source[raw_key] = invalid_by_source.get(raw_key, 0) + 1
                _upsert_source(db, raw_key)
            continue
        component = _resolve_component(db, row.component_id, row.component_serial)
        if component is None:
            reason = (
                "unknown component identity"
                if row.component_id is None and not row.component_serial
                else "unknown component"
            )
            result.rejected.append(RejectedRow(index=index, reason=reason))
            invalid_by_source[row.source_key] = invalid_by_source.get(row.source_key, 0) + 1
            _upsert_source(db, row.source_key)
            continue
        source = _upsert_source(db, row.source_key)
        ts = _as_utc(row.ts)
        db.add(
            TelemetryReading(
                component_id=component.id,
                source_id=source.id,
                ts=ts,
                channel=row.channel,
                value=row.value,
                quality=DataQualityState.CURRENT,
            )
        )
        valid_by_source.setdefault(row.source_key, []).append((ts, component))
        result.accepted += 1

    for key in set(valid_by_source) | set(invalid_by_source):
        source = _upsert_source(db, key)
        _apply_source_state(
            db,
            source,
            valid_by_source.get(key, []),
            invalid_by_source.get(key, 0),
            now,
        )
    db.commit()
    return result


def evaluate_source_state(
    last_valid_ts: datetime | None,
    now: datetime,
    stale_after_seconds: int,
    invalid_ratio: float,
) -> DataQualityState:
    """Derive the data-quality state for a source."""
    if last_valid_ts is None:
        return DataQualityState.MISSING
    if (now - last_valid_ts).total_seconds() > stale_after_seconds:
        return DataQualityState.STALE
    if invalid_ratio > 0.25:
        return DataQualityState.DEGRADED
    return DataQualityState.CURRENT


def _invalid_ratio(db: Session, source_id: uuid.UUID) -> float:
    qualities = list(
        db.scalars(select(TelemetryReading.quality).where(TelemetryReading.source_id == source_id))
    )
    if not qualities:
        return 0.0
    invalid = sum(1 for quality in qualities if quality == DataQualityState.INVALID)
    return invalid / len(qualities)


def refresh_source_states(db: Session, now: datetime | None = None) -> list[DataSourceState]:
    """Recompute and persist data-source quality states."""
    # TODO(DAT-02): recompute freshness without carrying healthy state forward.
    moment = _as_utc(now) if now is not None else utcnow()
    states: list[DataSourceState] = []
    for source in db.scalars(select(DataSource).order_by(DataSource.key)).all():
        state = _state_for(db, source)
        last_valid = _as_utc(state.last_valid_ts) if state.last_valid_ts is not None else None
        state.last_valid_ts = last_valid
        state.state = evaluate_source_state(
            last_valid,
            moment,
            get_settings().stale_after_seconds,
            _invalid_ratio(db, source.id),
        )
        state.updated_at = moment
        states.append(state)
    db.commit()
    return states


def list_source_states(db: Session) -> list[tuple[DataSource, DataSourceState | None]]:
    """List every registered source alongside its current state."""
    pairs: list[tuple[DataSource, DataSourceState | None]] = []
    for source in db.scalars(select(DataSource).order_by(DataSource.key)).all():
        state = db.scalar(select(DataSourceState).where(DataSourceState.source_id == source.id))
        pairs.append((source, state))
    return pairs


def get_source_state(db: Session, source_id: uuid.UUID) -> DataSourceState | None:
    """Return the current state for a source, creating MISSING when absent."""
    source = db.get(DataSource, source_id)
    if source is None:
        return None
    state = _state_for(db, source)
    db.commit()
    return state
