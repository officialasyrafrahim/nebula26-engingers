"""Canonical, immutable planning instance keyed by published natural ids.

``PlanningInstance`` is the single source of truth that the compiler and (later)
the solver consume. It never reads CSV rows directly. Cross-record validation
is exposed as :func:`validate_planning_instance` so callers receive every issue
at once instead of the first exception.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.rail.errors import Issue
from app.domain.rail.keys import parse_location_id, parse_sector_id
from app.domain.rail.network import BufferRule, Line, LocationSupply, Sector, Station, StationKey
from app.domain.rail.routes import RouteError, RouteNetwork, expand_route
from app.domain.rail.strict_types import StrictDate, StrictInt


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_number: str
    contract_description: str
    contract_award_date: StrictDate
    activity_type: str
    nature_of_activity: str
    contract_priority: StrictInt = Field(ge=1, le=3)
    contract_completion_date: StrictDate
    planned_completion_date: StrictDate
    number_of_workfronts: StrictInt = Field(ge=1)
    access_type: Literal["PM", "PC", "C"]
    number_of_maximum_access_per_week: StrictInt = Field(ge=1)


class Activity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    activity_id: str
    contract_number: str
    activity_type: str
    start_location_id: str
    end_location_id: str
    total_accesses: StrictInt = Field(ge=1)
    planned_start_date: StrictDate
    predecessor_activity_id: str | None = None
    activity_priority: StrictInt = Field(ge=1, le=3)


class Parameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    horizon_start: StrictDate
    horizon_weeks: StrictInt = Field(ge=1)


class PlanningInstance(BaseModel):
    """Validated canonical instance. Build via ``modules.instance.service``."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    lines: Mapping[str, Line]
    stations: Mapping[StationKey, Station]
    sectors: Mapping[str, Sector]
    locations: Mapping[str, LocationSupply]
    buffer_rules: Mapping[str, BufferRule]
    parameters: Parameters
    contracts: Mapping[str, Contract]
    activities: Mapping[str, Activity]
    predecessors: Mapping[str, str] = Field(default_factory=dict)
    successors: Mapping[str, tuple[str, ...]] = Field(default_factory=dict)

    @property
    def horizon_start(self) -> date:
        return self.parameters.horizon_start

    @property
    def horizon_weeks(self) -> int:
        return self.parameters.horizon_weeks

    def route_network(self) -> RouteNetwork:
        return RouteNetwork(
            stations=self.stations,
            sectors=self.sectors,
            locations=self.locations,
        )

    def sectors_on_line(self, line_code: str) -> tuple[Sector, ...]:
        return tuple(
            sorted(
                (sector for sector in self.sectors.values() if sector.line_code == line_code),
                key=lambda sector: sector.seq,
            )
        )

    def stations_on_line(self, line_code: str) -> tuple[Station, ...]:
        return tuple(
            sorted(
                (
                    station
                    for (line, _), station in self.stations.items()
                    if line == line_code
                ),
                key=lambda station: station.seq,
            )
        )

    def planned_start_week(self, activity: Activity) -> int:
        return planned_start_week(self.parameters.horizon_start, activity.planned_start_date)


def planned_start_week(horizon_start: date, start_date: date) -> int:
    """Return the 1-based week index containing ``start_date`` (clamped to 1)."""

    offset = (start_date - horizon_start).days
    if offset < 0:
        return 1
    return offset // 7 + 1


def find_predecessor_cycles(predecessors: Mapping[str, str]) -> list[tuple[str, ...]]:
    """Return every predecessor cycle, each as an ordered tuple of activity ids.

    The walk is iterative so a deep hidden-instance chain cannot exhaust the
    Python call stack. Each node has at most one predecessor, so a path and an
    index map are enough to spot the back edge that closes a cycle.
    """

    cycles: list[tuple[str, ...]] = []
    seen_cycles: set[frozenset[str]] = set()
    state: dict[str, int] = {}

    for root in predecessors:
        if state.get(root, 0) != 0:
            continue
        path: list[str] = []
        path_index: dict[str, int] = {}
        node: str | None = root
        while node is not None and state.get(node, 0) == 0:
            state[node] = 1
            path_index[node] = len(path)
            path.append(node)
            node = predecessors.get(node)

        if node is not None and state.get(node) == 1:
            cycle = tuple(path[path_index[node] :])
            key = frozenset(cycle)
            if key not in seen_cycles:
                seen_cycles.add(key)
                cycles.append(cycle)

        for visited in path:
            state[visited] = 2
    return cycles


def validate_planning_instance(instance: PlanningInstance) -> list[Issue]:
    """Collect every reference, uniqueness, continuity and dependency issue."""

    issues: list[Issue] = []
    _validate_references(instance, issues)
    _validate_sectors(instance, issues)
    _validate_uniqueness(instance, issues)
    _validate_network_continuity(instance, issues)
    _validate_predecessors(instance, issues)
    _validate_routes(instance, issues)
    return issues


def _validate_references(instance: PlanningInstance, issues: list[Issue]) -> None:
    line_codes = set(instance.lines)

    for (line_code, station_id), station in instance.stations.items():
        if line_code != station.line_code:
            issues.append(
                Issue(f"station {station_id!r} keyed under {line_code!r} but declares "
                      f"{station.line_code!r}")
            )
        if station.line_code not in line_codes:
            issues.append(
                Issue(f"station {station_id!r} references unknown line {station.line_code!r}")
            )

    for sector_id, sector in instance.sectors.items():
        if sector_id != sector.sector_id:
            issues.append(
                Issue(f"sector key {sector_id!r} disagrees with sector_id {sector.sector_id!r}")
            )
        if sector.line_code not in line_codes:
            issues.append(
                Issue(f"sector {sector_id!r} references unknown line {sector.line_code!r}")
            )
        for role, station_id in (
            ("from_station_id", sector.from_station_id),
            ("to_station_id", sector.to_station_id),
        ):
            if (sector.line_code, station_id) not in instance.stations:
                issues.append(
                    Issue(f"sector {sector_id!r} {role} references unknown station "
                          f"{station_id!r} on {sector.line_code!r}")
                )

    for location_id, location in instance.locations.items():
        if location_id != location.location_id:
            issues.append(
                Issue(f"location key {location_id!r} disagrees with location_id "
                      f"{location.location_id!r}")
            )
        if location.line_code not in line_codes:
            issues.append(
                Issue(f"location {location_id!r} references unknown line "
                      f"{location.line_code!r}")
            )
        try:
            key = parse_location_id(location.location_id)
        except ValueError as exc:
            issues.append(Issue(f"location {location_id!r} is malformed: {exc}"))
            continue
        if key.line_code != location.line_code or key.bound != location.bound:
            issues.append(
                Issue(f"location {location_id!r} key disagrees with declared line/bound")
            )
        expected_kind = "tunnel sector" if key.is_tunnel else "platform sector"
        if location.location_kind != expected_kind:
            issues.append(
                Issue(
                    f"location {location_id!r} location_kind {location.location_kind!r} "
                    f"disagrees with id kind {key.kind!r}"
                )
            )
        if key.is_tunnel and key.sector_id not in instance.sectors:
            issues.append(
                Issue(f"location {location_id!r} references unknown tunnel sector "
                      f"{key.sector_id!r}")
            )
        if key.is_platform and (location.line_code, key.station_id) not in instance.stations:
            issues.append(
                Issue(f"location {location_id!r} references unknown station "
                      f"{key.station_id!r} on {location.line_code!r}")
            )

    for contract_number, contract in instance.contracts.items():
        if contract_number != contract.contract_number:
            issues.append(
                Issue(f"contract key {contract_number!r} disagrees with contract_number "
                      f"{contract.contract_number!r}")
            )
        if contract.nature_of_activity not in instance.buffer_rules:
            issues.append(
                Issue(f"contract {contract_number!r} references unknown "
                      f"nature_of_activity {contract.nature_of_activity!r}")
            )
        if contract.planned_completion_date > contract.contract_completion_date:
            issues.append(
                Issue(f"contract {contract_number!r} planned_completion_date "
                      f"{contract.planned_completion_date} is after contract_completion_date "
                      f"{contract.contract_completion_date}")
            )

    for activity_id, activity in instance.activities.items():
        contract = instance.contracts.get(activity.contract_number)
        if contract is None:
            issues.append(
                Issue(f"activity {activity_id!r} references unknown contract "
                      f"{activity.contract_number!r}")
            )
        else:
            if activity.activity_type != contract.activity_type:
                issues.append(
                    Issue(f"activity {activity_id!r} activity_type "
                          f"{activity.activity_type!r} does not match contract "
                          f"{contract.contract_number!r} activity_type "
                          f"{contract.activity_type!r}")
                )
            if activity.planned_start_date < contract.contract_award_date:
                issues.append(
                    Issue(f"activity {activity_id!r} planned_start_date "
                          f"{activity.planned_start_date} is before contract "
                          f"{contract.contract_number!r} award date "
                          f"{contract.contract_award_date}")
                )
        for role, location_id in (
            ("start_location_id", activity.start_location_id),
            ("end_location_id", activity.end_location_id),
        ):
            if location_id not in instance.locations:
                issues.append(
                    Issue(f"activity {activity_id!r} {role} references unknown location "
                          f"{location_id!r}")
                )


def _validate_sectors(instance: PlanningInstance, issues: list[Issue]) -> None:
    """Check every sector id against its declared endpoints and station order."""

    for sector_id, sector in instance.sectors.items():
        try:
            key = parse_sector_id(sector.sector_id)
        except ValueError as exc:
            issues.append(Issue(f"sector {sector_id!r} is malformed: {exc}"))
            continue
        if (
            key.line_code != sector.line_code
            or key.from_station_id != sector.from_station_id
            or key.to_station_id != sector.to_station_id
        ):
            issues.append(
                Issue(
                    f"sector {sector_id!r} key disagrees with its declared line and "
                    f"endpoints ({sector.from_station_id!r} -> {sector.to_station_id!r})"
                )
            )
            continue

        from_station = instance.stations.get((sector.line_code, sector.from_station_id))
        to_station = instance.stations.get((sector.line_code, sector.to_station_id))
        if from_station is None or to_station is None:
            continue
        if abs(from_station.seq - to_station.seq) != 1:
            issues.append(
                Issue(
                    f"sector {sector_id!r} endpoints {sector.from_station_id!r} (seq "
                    f"{from_station.seq}) and {sector.to_station_id!r} (seq "
                    f"{to_station.seq}) are not adjacent stations on {sector.line_code!r}"
                )
            )


def _validate_uniqueness(instance: PlanningInstance, issues: list[Issue]) -> None:
    station_by_line_seq: dict[tuple[str, int], str] = {}
    for (line_code, station_id), station in instance.stations.items():
        key = (line_code, station.seq)
        if key in station_by_line_seq:
            issues.append(
                Issue(f"duplicate station seq {station.seq} on {line_code}: "
                      f"{station_by_line_seq[key]!r} and {station_id!r}")
            )
        station_by_line_seq[key] = station_id

    sector_by_line_seq: dict[tuple[str, int], str] = {}
    for sector in instance.sectors.values():
        key = (sector.line_code, sector.seq)
        if key in sector_by_line_seq:
            issues.append(
                Issue(f"duplicate sector seq {sector.seq} on {sector.line_code}: "
                      f"{sector_by_line_seq[key]!r} and {sector.sector_id!r}")
            )
        sector_by_line_seq[key] = sector.sector_id


def _validate_network_continuity(instance: PlanningInstance, issues: list[Issue]) -> None:
    for line_code in instance.lines:
        stations = instance.stations_on_line(line_code)
        if stations:
            sequences = [station.seq for station in stations]
            if sequences != list(range(sequences[0], sequences[-1] + 1)):
                issues.append(
                    Issue(f"station sequence on {line_code} is not continuous: {sequences}")
                )
        sectors = instance.sectors_on_line(line_code)
        if sectors:
            sequences = [sector.seq for sector in sectors]
            if sequences != list(range(sequences[0], sequences[-1] + 1)):
                issues.append(
                    Issue(f"sector sequence on {line_code} is not continuous: {sequences}")
                )
            for previous, current in pairwise(sectors):
                if previous.to_station_id != current.from_station_id:
                    issues.append(
                        Issue(f"sector chain break on {line_code}: "
                              f"{previous.sector_id!r} ends at "
                              f"{previous.to_station_id!r} but {current.sector_id!r} "
                              f"starts at {current.from_station_id!r}")
                    )


def _validate_predecessors(instance: PlanningInstance, issues: list[Issue]) -> None:
    for activity_id, predecessor_id in instance.predecessors.items():
        if activity_id not in instance.activities:
            issues.append(
                Issue(f"predecessor map references unknown activity {activity_id!r}")
            )
        if predecessor_id not in instance.activities:
            issues.append(
                Issue(f"activity {activity_id!r} predecessor {predecessor_id!r} does not exist")
            )
    for cycle in find_predecessor_cycles(instance.predecessors):
        issues.append(Issue(f"predecessor cycle detected: {' -> '.join(cycle)}"))


def _validate_routes(instance: PlanningInstance, issues: list[Issue]) -> None:
    network = instance.route_network()
    for activity_id, activity in instance.activities.items():
        try:
            expand_route(
                activity_id,
                activity.start_location_id,
                activity.end_location_id,
                network,
            )
        except RouteError as exc:
            issues.append(Issue(str(exc)))


def build_successor_index(predecessors: Mapping[str, str]) -> dict[str, tuple[str, ...]]:
    """Invert a predecessor map into deterministic successor tuples."""

    successors: dict[str, list[str]] = {activity_id: [] for activity_id in predecessors}
    for activity_id, predecessor_id in predecessors.items():
        successors.setdefault(predecessor_id, []).append(activity_id)
    return {
        activity_id: tuple(sorted(children))
        for activity_id, children in sorted(successors.items())
    }


def ordered_activities(activities: Mapping[str, Activity]) -> Sequence[Activity]:
    """Deterministic activity order (id ascending) used by the compiler."""

    return tuple(activities[activity_id] for activity_id in sorted(activities))
