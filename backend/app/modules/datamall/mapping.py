"""Presentation mapping from the solver's DTL/CCL demo network to LTA codes.

Provenance and honesty note
----------------------------
The solver keeps its own canonical identifiers (``ALP``, ``BET``, ``S01`` ..
``S18``, ``H01``, ``H02``). The real station names and LTA station codes below
are an unverified presentation mapping of the public LTA Downtown Line, Circle
Line and Circle Line Extension, consistent with ``data/mapped/README.md``. They
have not been checked against a live authoritative LTA dataset. The mapping is a
display and query-key label only and never reaches the canonical model.

Sources
-------
* LTA DataMall static dataset "Train Station Codes and Chinese Names" and the
  DataMall static datasets portal, Public Transport section:
  https://datamall.lta.gov.sg/content/datamall/en/static-data.html
* LTA DataMall API User Guide v6.9 (3 Aug 2026), sections 2.7 (PV/ODTrain),
  2.8 (PV/Train), 2.11 (TrainServiceAlerts), 2.24 (PCDRealTime) and 2.25
  (PCDForecast), which define the line and station code vocabularies:
  https://datamall.lta.gov.sg/content/dam/datamall/datasets/LTA_DataMall_API_User_Guide.pdf

Only these public reference codes are ever sent to LTA. No instance data, no
solver output and no upload ever leaves the process. Hidden instances whose
lines or stations are not in this table degrade to an explicit "context
unavailable for this network" state instead of guessing a code.
"""

from __future__ import annotations

from dataclasses import dataclass

DEMO_NETWORK_KEY = "dtl-ccl-demo"
DEMO_NETWORK_LABEL = "DTL/CCL demonstration network"

MAPPING_SOURCE = (
    "LTA DataMall static dataset 'Train Station Codes and Chinese Names' "
    "(datamall.lta.gov.sg static datasets, Public Transport) and the "
    "LTA DataMall API User Guide v6.9, sections 2.7, 2.8, 2.11, 2.24 and 2.25."
)
MAPPING_SOURCE_URL = "https://datamall.lta.gov.sg/content/datamall/en/static-data.html"
MAPPING_CAVEAT = (
    "Unverified presentation mapping of the public LTA Downtown and Circle "
    "lines, consistent with data/mapped/README.md. Solver identifiers stay "
    "canonical. Only public line and station codes are shared with LTA."
)


@dataclass(frozen=True)
class MappedStation:
    """One solver station and the public LTA station code it maps to."""

    solver_line: str
    solver_station: str
    name: str
    code: str
    datamall_line: str


@dataclass(frozen=True)
class NetworkMapping:
    """A solvable demo network and the public codes used to query LTA."""

    key: str
    label: str
    solver_lines: tuple[str, ...]
    crowd_lines: tuple[str, ...]
    alert_lines: tuple[str, ...]
    stations: tuple[MappedStation, ...]


# ALP is the DTL city segment. Station codes follow the LTA Downtown Line.
_ALP = (
    MappedStation("ALP", "S01", "Newton", "DT11", "DTL"),
    MappedStation("ALP", "S02", "Little India", "DT12", "DTL"),
    MappedStation("ALP", "S03", "Rochor", "DT13", "DTL"),
    MappedStation("ALP", "S04", "Bugis", "DT14", "DTL"),
    MappedStation("ALP", "H01", "Promenade", "DT15", "DTL"),
    MappedStation("ALP", "H02", "Bayfront", "DT16", "DTL"),
    MappedStation("ALP", "S05", "Downtown", "DT17", "DTL"),
    MappedStation("ALP", "S06", "Telok Ayer", "DT18", "DTL"),
    MappedStation("ALP", "S07", "Chinatown", "DT19", "DTL"),
    MappedStation("ALP", "S08", "Fort Canning", "DT20", "DTL"),
)

# BET is the CCL segment. Promenade is CC4 (CCL); Bayfront is CE1 and Marina
# Bay is CE2 on the Circle Line Extension, a separate crowd-density TrainLine.
_BET = (
    MappedStation("BET", "S11", "Dakota", "CC8", "CCL"),
    MappedStation("BET", "S12", "Mountbatten", "CC7", "CCL"),
    MappedStation("BET", "S13", "Stadium", "CC6", "CCL"),
    MappedStation("BET", "S14", "Nicoll Highway", "CC5", "CCL"),
    MappedStation("BET", "H01", "Promenade", "CC4", "CCL"),
    MappedStation("BET", "H02", "Bayfront", "CE1", "CEL"),
    MappedStation("BET", "S15", "Marina Bay", "CE2", "CEL"),
    MappedStation("BET", "S16", "Prince Edward Road", "CC32", "CCL"),
    MappedStation("BET", "S17", "Cantonment", "CC31", "CCL"),
    MappedStation("BET", "S18", "Keppel", "CC30", "CCL"),
)

_DEMO = NetworkMapping(
    key=DEMO_NETWORK_KEY,
    label=DEMO_NETWORK_LABEL,
    solver_lines=("ALP", "BET"),
    crowd_lines=("DTL", "CCL", "CEL"),
    alert_lines=("DTL", "CCL"),
    stations=_ALP + _BET,
)

NETWORKS: dict[str, NetworkMapping] = {_DEMO.key: _DEMO}

STATION_LOOKUP: dict[tuple[str, str], MappedStation] = {
    (station.solver_line, station.solver_station): station for station in _DEMO.stations
}

STATION_BY_CODE: dict[str, MappedStation] = {station.code: station for station in _DEMO.stations}

# Public vocabularies a caller may ever send to LTA.
ALLOWED_LINES: frozenset[str] = frozenset(
    line for network in NETWORKS.values() for line in network.crowd_lines
)
ALLOWED_ALERT_LINES: frozenset[str] = frozenset(
    line for network in NETWORKS.values() for line in network.alert_lines
)
ALLOWED_STATION_CODES: frozenset[str] = frozenset(STATION_BY_CODE)


def get_network(network_key: str) -> NetworkMapping | None:
    """Return a supported demo network mapping, or ``None`` when unmapped."""

    return NETWORKS.get(network_key)


def is_supported_network(network_key: str) -> bool:
    """Whether the network key is a known, mapped presentation network."""

    return network_key in NETWORKS


def mapped_station(solver_line: str, solver_station: str) -> MappedStation | None:
    """Map a solver station id to its public LTA station code, if known."""

    return STATION_LOOKUP.get((solver_line, solver_station))


def station_by_code(code: str) -> MappedStation | None:
    """Map a public LTA station code back to its solver station, if known."""

    return STATION_BY_CODE.get(code)


def all_networks() -> tuple[NetworkMapping, ...]:
    """Every supported presentation network."""

    return tuple(NETWORKS.values())


__all__ = [
    "ALLOWED_ALERT_LINES",
    "ALLOWED_LINES",
    "ALLOWED_STATION_CODES",
    "DEMO_NETWORK_KEY",
    "MAPPING_CAVEAT",
    "MAPPING_SOURCE",
    "MAPPING_SOURCE_URL",
    "MappedStation",
    "NETWORKS",
    "NetworkMapping",
    "all_networks",
    "get_network",
    "is_supported_network",
    "mapped_station",
    "station_by_code",
]
