"""Seed helpers shared by detection-side tests."""

import uuid

from sqlalchemy.orm import Session

from app.domain.enums import ComponentType
from app.domain.models import Asset, Component


def make_asset(db: Session, label: str = "T-100", fleet: str = "FLT-1") -> Asset:
    """Create and flush a canonical asset."""
    asset = Asset(fleet=fleet, label=label, asset_type="EMU")
    db.add(asset)
    db.flush()
    return asset


def make_component(
    db: Session, asset: Asset, component_type: ComponentType = ComponentType.BOGIE
) -> Component:
    """Create and flush a component on an asset."""
    component = Component(
        asset_id=asset.id,
        component_type=component_type,
        serial=uuid.uuid4().hex,
    )
    db.add(component)
    db.flush()
    return component
