"""Exact schema definitions for the eight published instance CSVs.

Column order is significant and every other column is forbidden. The row models
are the frozen domain records, so the parsed output and the canonical model
cannot drift apart.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.rail.instance_model import Activity, Contract, Parameters
from app.domain.rail.network import BufferRule, Line, LocationSupply, Sector, Station

PARAMETERS_FILE = "06_PARAMETERS.csv"

INSTANCE_FILES: tuple[str, ...] = (
    "01_LINES.csv",
    "02_STATIONS.csv",
    "03_SECTORS.csv",
    "04_LOCATION_SUPPLY.csv",
    "05_BUFFER_LOCATION.csv",
    PARAMETERS_FILE,
    "07_PROJECT_DETAILS.csv",
    "08_ACTIVITY_DETAILS.csv",
)

ROW_MODELS: dict[str, type[BaseModel]] = {
    "01_LINES.csv": Line,
    "02_STATIONS.csv": Station,
    "03_SECTORS.csv": Sector,
    "04_LOCATION_SUPPLY.csv": LocationSupply,
    "05_BUFFER_LOCATION.csv": BufferRule,
    "07_PROJECT_DETAILS.csv": Contract,
    "08_ACTIVITY_DETAILS.csv": Activity,
}

PARAMETER_HEADERS: tuple[str, ...] = ("key", "value")

FILE_HEADERS: dict[str, tuple[str, ...]] = {
    name: tuple(model.model_fields) for name, model in ROW_MODELS.items()
}
FILE_HEADERS[PARAMETERS_FILE] = PARAMETER_HEADERS

PARAMETER_KEYS: tuple[str, ...] = ("horizon_start", "horizon_weeks")


class ParsedInstance(BaseModel):
    """Typed, validated records read from the eight instance files."""

    model_config = ConfigDict(frozen=True)

    lines: tuple[Line, ...]
    stations: tuple[Station, ...]
    sectors: tuple[Sector, ...]
    locations: tuple[LocationSupply, ...]
    buffer_rules: tuple[BufferRule, ...]
    parameters: Parameters
    contracts: tuple[Contract, ...]
    activities: tuple[Activity, ...]
