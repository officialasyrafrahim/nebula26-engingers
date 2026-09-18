"""Assets service.

ERD requirements: DAT-01, ARC-02.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Asset, Component
from app.domain.schemas import AssetCreate, ComponentCreate


def register_asset(db: Session, data: AssetCreate) -> Asset:
    """Register a canonical asset from source data."""
    # TODO(DAT-01): map provider-specific source schemas through adapters.
    asset = Asset(
        fleet=data.fleet,
        label=data.label,
        asset_type=data.asset_type,
        source_system=data.source_system,
        source_id=data.source_id,
    )
    db.add(asset)
    db.commit()
    return asset


def list_assets(db: Session, fleet: str | None = None) -> list[Asset]:
    """List canonical assets, optionally filtered by fleet."""
    statement = select(Asset).order_by(Asset.created_at)
    if fleet is not None:
        statement = statement.where(Asset.fleet == fleet)
    return list(db.scalars(statement).all())


def get_asset(db: Session, asset_id: uuid.UUID) -> Asset | None:
    """Return one canonical asset or None when absent."""
    return db.get(Asset, asset_id)


def add_component(db: Session, asset_id: uuid.UUID, data: ComponentCreate) -> Component | None:
    """Attach a component to an existing asset."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        return None
    component = Component(
        asset_id=asset.id,
        component_type=data.component_type,
        serial=data.serial,
    )
    db.add(component)
    db.commit()
    return component


def list_components(db: Session, asset_id: uuid.UUID) -> list[Component]:
    """List components attached to an asset."""
    statement = (
        select(Component).where(Component.asset_id == asset_id).order_by(Component.created_at)
    )
    return list(db.scalars(statement).all())
