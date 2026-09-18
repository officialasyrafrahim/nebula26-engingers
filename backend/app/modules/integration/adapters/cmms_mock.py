"""In-memory CMMS adapter for dev and tests.

ERD requirements: INT-01.
"""

from typing import Any

from app.modules.integration.adapters.base import CmmsAdapter


class MockCmmsAdapter(CmmsAdapter):
    """Sample CMMS adapter that records write-back calls in memory."""

    def __init__(self) -> None:
        self.write_back_calls: list[dict[str, Any]] = []

    def fetch_assets(self) -> list[dict[str, Any]]:
        """Return sample source assets."""
        return [
            {
                "source_id": "A-1001",
                "label": "Unit 1001",
                "fleet": "Fleet-A",
                "asset_type": "EMU",
            }
        ]

    def fetch_work_orders(self) -> list[dict[str, Any]]:
        """Return sample source work orders."""
        return [
            {
                "source_id": "WO-1",
                "asset_source_id": "A-1001",
                "description": "Inspect door system",
                "state": "OPEN",
            }
        ]

    # TODO(INT-01): explicit approved write-back only.
    def write_back_work_package(self, work_package: dict[str, Any]) -> dict[str, Any]:
        """Record a work-package write-back."""
        self.write_back_calls.append({"kind": "work_package", "payload": work_package})
        return {"status": "recorded", "kind": "work_package"}

    def write_back_schedule(self, schedule: dict[str, Any]) -> dict[str, Any]:
        """Record a schedule write-back."""
        self.write_back_calls.append({"kind": "schedule", "payload": schedule})
        return {"status": "recorded", "kind": "schedule"}
