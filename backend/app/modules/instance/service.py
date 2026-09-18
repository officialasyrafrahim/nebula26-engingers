"""Instance ingestion service: typed records -> validated PlanningInstance."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from app.domain.rail.errors import InstanceValidationError, Issue
from app.domain.rail.instance_model import (
    PlanningInstance,
    build_successor_index,
    validate_planning_instance,
)
from app.modules.instance.parser import parse_directory, parse_mapping
from app.modules.instance.schemas import ParsedInstance


def _index[Record](
    records: Iterable[Record],
    key: Callable[[Record], Any],
    label: str,
    file: str,
    issues: list[Issue],
) -> dict[Any, Record]:
    indexed: dict[Any, Record] = {}
    for record in records:
        natural_key = key(record)
        if natural_key in indexed:
            issues.append(Issue(f"duplicate {label} {natural_key!r}", file=file))
            continue
        indexed[natural_key] = record
    return indexed


def build_planning_instance(parsed: ParsedInstance) -> PlanningInstance:
    """Fold parsed records into the canonical model and validate every link."""

    issues: list[Issue] = []
    lines = _index(parsed.lines, lambda row: row.line_code, "line", "01_LINES.csv", issues)
    stations = _index(
        parsed.stations,
        lambda row: (row.line_code, row.station_id),
        "station",
        "02_STATIONS.csv",
        issues,
    )
    sectors = _index(parsed.sectors, lambda row: row.sector_id, "sector", "03_SECTORS.csv", issues)
    locations = _index(
        parsed.locations,
        lambda row: row.location_id,
        "location",
        "04_LOCATION_SUPPLY.csv",
        issues,
    )
    buffer_rules = _index(
        parsed.buffer_rules,
        lambda row: row.nature_of_works,
        "buffer rule",
        "05_BUFFER_LOCATION.csv",
        issues,
    )
    contracts = _index(
        parsed.contracts,
        lambda row: row.contract_number,
        "contract",
        "07_PROJECT_DETAILS.csv",
        issues,
    )
    activities = _index(
        parsed.activities,
        lambda row: row.activity_id,
        "activity",
        "08_ACTIVITY_DETAILS.csv",
        issues,
    )

    predecessors: dict[str, str] = {
        activity.activity_id: activity.predecessor_activity_id
        for activity in parsed.activities
        if activity.predecessor_activity_id is not None
    }
    successors = build_successor_index(predecessors)

    instance = PlanningInstance(
        lines=lines,
        stations=stations,
        sectors=sectors,
        locations=locations,
        buffer_rules=buffer_rules,
        parameters=parsed.parameters,
        contracts=contracts,
        activities=activities,
        predecessors=predecessors,
        successors=successors,
    )

    issues.extend(validate_planning_instance(instance))
    if issues:
        raise InstanceValidationError(issues)
    return instance


def load_instance(directory: str | os.PathLike[str]) -> PlanningInstance:
    """Parse a directory and build the canonical instance in one step."""

    return build_planning_instance(parse_directory(directory))


def load_instance_from_mapping(mapping: Mapping[str, object]) -> PlanningInstance:
    """Parse an in-memory file mapping and build the canonical instance."""

    return build_planning_instance(parse_mapping(mapping))
