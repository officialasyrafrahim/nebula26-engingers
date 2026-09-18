"""Integration service.

ERD requirements: INT-01, ARC-02.
"""

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.domain.enums import WorkPackageState
from app.domain.models import Asset, WorkPackage
from app.modules.integration.adapters.base import CmmsAdapter
from app.modules.integration.adapters.cmms_mock import MockCmmsAdapter

SOURCE_SYSTEM = "cmms-mock"


def sync_from_cmms(db: Session, adapter: CmmsAdapter) -> dict[str, Any]:
    """Read assets and work orders from a CMMS/EAM adapter."""
    assets_synced = 0
    for record in adapter.fetch_assets():
        source_id = record.get("source_id")
        if source_id is None:
            continue
        asset = db.scalars(
            select(Asset).where(
                Asset.source_system == SOURCE_SYSTEM,
                Asset.source_id == str(source_id),
            )
        ).first()
        if asset is None:
            asset = Asset(
                source_system=SOURCE_SYSTEM,
                source_id=str(source_id),
                fleet=record.get("fleet") or "",
                label=record.get("label") or "",
                asset_type=record.get("asset_type") or "",
            )
            db.add(asset)
        else:
            asset.fleet = record.get("fleet") or asset.fleet
            asset.label = record.get("label") or asset.label
            asset.asset_type = record.get("asset_type") or asset.asset_type
        assets_synced += 1

    work_orders = adapter.fetch_work_orders()
    db.commit()
    return {"assets_synced": assets_synced, "work_orders_fetched": len(work_orders)}


def write_back_work_package(
    db: Session, work_package_id: uuid.UUID, adapter: CmmsAdapter | None = None
) -> dict[str, Any]:
    """Write an approved work package back to the CMMS/EAM."""
    work_package = db.get(WorkPackage, work_package_id)
    if work_package is None:
        raise HTTPException(status_code=404, detail="work package not found")
    if work_package.state != WorkPackageState.APPROVED:
        raise HTTPException(
            status_code=409, detail="only approved work packages can be written back"
        )

    active_adapter = adapter or MockCmmsAdapter()
    payload = {
        "id": str(work_package.id),
        "title": work_package.title,
        "description": work_package.description,
        "priority": work_package.priority.value,
        "state": work_package.state.value,
    }
    result = active_adapter.write_back_work_package(payload)
    record_audit(
        db,
        actor=SOURCE_SYSTEM,
        action="cmms_writeback",
        entity_type="work_package",
        entity_id=work_package.id,
        after={"external_ref": result.get("external_ref"), "kind": result.get("kind")},
    )
    db.commit()
    return {
        "written_back": True,
        "external_ref": result.get("external_ref") or f"{SOURCE_SYSTEM}:{work_package.id}",
    }
