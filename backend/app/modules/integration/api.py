"""Integration API router.

ERD requirements: INT-01, ARC-02.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_role
from app.domain.enums import UserRole
from app.modules.integration import service
from app.modules.integration.adapters.cmms_mock import MockCmmsAdapter

router = APIRouter(prefix="/api/v1", tags=["integration"])

ADAPTERS = [
    {
        "name": "cmms-mock",
        "kind": "cmms",
        "mode": "simulated",
        "write_back": "explicit-approved-only",
    }
]


@router.get("/integration/adapters")
def list_adapters() -> list[dict[str, str]]:
    """List configured integration adapters."""
    return ADAPTERS


@router.post("/integration/sync")
def sync_integration(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Read assets and work orders from the demo CMMS adapter."""
    return service.sync_from_cmms(db, MockCmmsAdapter())


@router.post("/integration/writeback/{work_package_id}")
def write_back(
    work_package_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(UserRole.PLANNER, UserRole.ADMIN)),
) -> dict[str, Any]:
    """Write an approved work package back to the CMMS."""
    return service.write_back_work_package(db, work_package_id)
