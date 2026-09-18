"""Model registry service.

ERD requirements: ML-02, ML-03.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.security import CurrentUser
from app.domain.enums import ModelApprovalState
from app.domain.models import ModelVersion, utcnow
from app.domain.schemas import ModelVersionCreate


def register_model(db: Session, data: ModelVersionCreate) -> ModelVersion:
    """Register model version metadata as a candidate."""
    model = ModelVersion(
        name=data.name,
        version=data.version,
        fleet=data.fleet,
        training_data_ref=data.training_data_ref,
        metrics=data.metrics,
        approval_state=ModelApprovalState.CANDIDATE,
        registered_at=data.registered_at or utcnow(),
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


def approve_model(db: Session, model_id: uuid.UUID, user: CurrentUser) -> ModelVersion:
    """Approve a candidate or staged model version for production use."""
    model = db.get(ModelVersion, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="model version not found")
    allowed = (ModelApprovalState.CANDIDATE, ModelApprovalState.STAGED)
    if model.approval_state not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"cannot approve model in state {model.approval_state.value}",
        )
    before = model.approval_state.value
    model.approval_state = ModelApprovalState.APPROVED
    record_audit(
        db,
        actor=user.id,
        action="model_approval",
        entity_type="model_version",
        entity_id=model.id,
        before={"approval_state": before},
        after={"approval_state": model.approval_state.value},
    )
    db.commit()
    db.refresh(model)
    return model


def list_models(db: Session) -> list[ModelVersion]:
    """List registered model versions."""
    return list(
        db.scalars(select(ModelVersion).order_by(ModelVersion.registered_at.desc())).all()
    )
