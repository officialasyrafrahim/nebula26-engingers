"""Read/write contract for CMMS/EAM adapters.

ERD requirements: INT-01, ARC-02.
"""

from abc import ABC, abstractmethod
from typing import Any


class CmmsAdapter(ABC):
    """Adapter contract for an existing CMMS/EAM system."""

    @abstractmethod
    def fetch_assets(self) -> list[dict[str, Any]]:
        """Return source assets available for canonical mapping."""

    @abstractmethod
    def fetch_work_orders(self) -> list[dict[str, Any]]:
        """Return source work orders available for canonical mapping."""

    @abstractmethod
    def write_back_work_package(self, work_package: dict[str, Any]) -> dict[str, Any]:
        """Write an approved work package back to the source system."""

    @abstractmethod
    def write_back_schedule(self, schedule: dict[str, Any]) -> dict[str, Any]:
        """Write an approved schedule back to the source system."""
