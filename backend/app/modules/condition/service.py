"""Condition service.

ERD requirements: DET-01, DET-02.
"""

from __future__ import annotations

import math
import statistics
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ConditionTrend, DataQualityState, EvidenceType
from app.domain.models import (
    Component,
    ConditionEvent,
    DataSourceState,
    Evidence,
    TelemetryReading,
)

_SEVERITY = {
    DataQualityState.CURRENT: 0,
    DataQualityState.DEGRADED: 1,
    DataQualityState.STALE: 2,
    DataQualityState.MISSING: 3,
    DataQualityState.INVALID: 4,
}

_DETECTOR = "zscore-placeholder-v0"
_SLOPE_THRESHOLD = 0.05


class ComponentNotFoundError(Exception):
    """Raised when a component does not exist."""


class InputNotCurrentError(Exception):
    """Raised when feeding source data is not current."""

    def __init__(self, state: DataQualityState) -> None:
        super().__init__(state.value)
        self.state = state


def _input_quality(db: Session, component_id: uuid.UUID) -> DataQualityState:
    source_ids = list(
        db.scalars(
            select(TelemetryReading.source_id)
            .where(
                TelemetryReading.component_id == component_id,
                TelemetryReading.source_id.is_not(None),
            )
            .distinct()
        ).all()
    )
    if not source_ids:
        return DataQualityState.MISSING
    latest: dict[uuid.UUID, DataSourceState] = {}
    for state in db.scalars(
        select(DataSourceState).where(DataSourceState.source_id.in_(source_ids))
    ).all():
        latest[state.source_id] = state
    if not latest:
        return DataQualityState.MISSING
    return max((state.state for state in latest.values()), key=lambda item: _SEVERITY[item])


def _channel_stats(db: Session, component_id: uuid.UUID) -> dict[str, dict]:
    readings = db.scalars(
        select(TelemetryReading)
        .where(TelemetryReading.component_id == component_id)
        .order_by(TelemetryReading.ts)
    ).all()
    by_channel: dict[str, list[TelemetryReading]] = {}
    for reading in readings:
        by_channel.setdefault(reading.channel, []).append(reading)
    stats: dict[str, dict] = {}
    for channel, items in by_channel.items():
        values = [item.value for item in items]
        latest = values[-1]
        mean = statistics.fmean(values)
        std = statistics.pstdev(values) if len(values) > 1 else 0.0
        if std > 0:
            zscore = (latest - mean) / std
        elif latest == mean:
            zscore = 0.0
        else:
            zscore = math.inf
        score = min(1.0, abs(zscore) / 4.0)
        stats[channel] = {
            "count": len(values),
            "mean": mean,
            "std": std,
            "latest": latest,
            "zscore": zscore if math.isfinite(zscore) else None,
            "score": score,
        }
    return stats


def _slope(values: list[float]) -> float:
    count = len(values)
    indices = list(range(count))
    mean_x = statistics.fmean(indices)
    mean_y = statistics.fmean(values)
    denominator = sum((index - mean_x) ** 2 for index in indices)
    if denominator == 0:
        return 0.0
    return sum(
        (index - mean_x) * (value - mean_y)
        for index, value in zip(indices, values, strict=True)
    ) / denominator


def _trend(db: Session, component_id: uuid.UUID, score: float) -> ConditionTrend:
    prior = db.scalars(
        select(ConditionEvent)
        .where(ConditionEvent.component_id == component_id)
        .order_by(ConditionEvent.detected_at.desc())
        .limit(4)
    ).all()
    series = [event.score for event in reversed(prior)] + [score]
    if len(series) < 3:
        return ConditionTrend.UNKNOWN
    slope = _slope(series)
    if slope > _SLOPE_THRESHOLD:
        return ConditionTrend.DETERIORATING
    if slope < -_SLOPE_THRESHOLD:
        return ConditionTrend.IMPROVING
    return ConditionTrend.STABLE


def detect_condition(db: Session, component_id: uuid.UUID) -> ConditionEvent:
    """Detect a condition for a component and persist an event."""
    # TODO(DET-01): replace the univariate z-score placeholder with a validated
    # multivariable model once training data and approval exist.
    component = db.get(Component, component_id)
    if component is None:
        raise ComponentNotFoundError
    quality = _input_quality(db, component_id)
    if quality != DataQualityState.CURRENT:
        raise InputNotCurrentError(quality)
    stats = _channel_stats(db, component_id)
    score = max((item["score"] for item in stats.values()), default=0.0)
    trend = _trend(db, component_id, score)
    event = ConditionEvent(
        component_id=component.id,
        score=score,
        trend=trend,
        data_quality=DataQualityState.CURRENT,
        evidence={"window": stats},
    )
    db.add(event)
    db.flush()
    db.add(
        Evidence(
            condition_event_id=event.id,
            type=EvidenceType.OBSERVATION,
            content={"window": stats},
        )
    )
    db.add(
        Evidence(
            condition_event_id=event.id,
            type=EvidenceType.MODEL_INFERENCE,
            content={"detector": _DETECTOR, "score": score, "trend": trend.value},
        )
    )
    db.commit()
    return event


def list_conditions(
    db: Session, component_id: uuid.UUID | None = None
) -> list[ConditionEvent]:
    """List detected condition events, optionally for a component."""
    statement = select(ConditionEvent).order_by(ConditionEvent.detected_at.desc())
    if component_id is not None:
        statement = statement.where(ConditionEvent.component_id == component_id)
    return list(db.scalars(statement).all())


def get_condition(db: Session, condition_id: uuid.UUID) -> ConditionEvent | None:
    """Return one condition event or None when absent."""
    return db.get(ConditionEvent, condition_id)


def list_evidence(db: Session, condition_id: uuid.UUID) -> list[Evidence]:
    """List evidence rows attached to a condition event."""
    return list(
        db.scalars(
            select(Evidence)
            .where(Evidence.condition_event_id == condition_id)
            .order_by(Evidence.created_at)
        ).all()
    )
