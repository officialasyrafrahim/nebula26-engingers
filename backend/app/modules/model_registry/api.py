"""Model registry API router.

ERD requirements: ML-02, ML-03.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_role
from app.domain.enums import UserRole
from app.domain.schemas import ModelVersionCreate, ModelVersionRead
from app.modules.model_registry import service

router = APIRouter(prefix="/api/v1", tags=["model_registry"])


@router.post(
    "/model-registry",
    response_model=ModelVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def register_model(
    data: ModelVersionCreate, db: Session = Depends(get_db)
) -> ModelVersionRead:
    """Register a candidate model version."""
    return service.register_model(db, data)


@router.post("/model-registry/{model_id}/approve", response_model=ModelVersionRead)
def approve_model(
    model_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.MODEL_APPROVER)),
) -> ModelVersionRead:
    """Approve a candidate or staged model version."""
    return service.approve_model(db, model_id, user)


@router.get("/model-registry", response_model=list[ModelVersionRead])
def list_models(db: Session = Depends(get_db)) -> list[ModelVersionRead]:
    """List registered model versions."""
    return service.list_models(db)
