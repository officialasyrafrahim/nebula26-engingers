"""Assets API router.

ERD requirements: DAT-01, ARC-02.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domain.models import Asset, Component
from app.domain.schemas import AssetCreate, AssetRead, ComponentCreate, ComponentRead
from app.modules.assets import service

router = APIRouter(prefix="/api/v1", tags=["assets"])


@router.post("/assets", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def create_asset(data: AssetCreate, db: Session = Depends(get_db)) -> Asset:
    """Register a canonical asset."""
    return service.register_asset(db, data)


@router.get("/assets", response_model=list[AssetRead])
def read_assets(fleet: str | None = None, db: Session = Depends(get_db)) -> list[Asset]:
    """List canonical assets, optionally filtered by fleet."""
    return service.list_assets(db, fleet)


@router.get("/assets/{asset_id}", response_model=AssetRead)
def read_asset(asset_id: uuid.UUID, db: Session = Depends(get_db)) -> Asset:
    """Return one canonical asset."""
    asset = service.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    return asset


@router.post(
    "/assets/{asset_id}/components",
    response_model=ComponentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_component(
    asset_id: uuid.UUID,
    data: ComponentCreate,
    db: Session = Depends(get_db),
) -> Component:
    """Attach a component to an asset."""
    component = service.add_component(db, asset_id, data)
    if component is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    return component


@router.get("/assets/{asset_id}/components", response_model=list[ComponentRead])
def read_components(asset_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Component]:
    """List components attached to an asset."""
    return service.list_components(db, asset_id)
