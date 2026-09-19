"""Static DTL/CCL topology tables and ALP/BET mapping helpers (F-DATA-001).

Provenance: the station names and their order are an unverified presentation
mapping of the public LTA Downtown Line and Circle Line. They have not been
checked against a retrieved authoritative LTA dataset, so they must be treated
as a presentation label rather than an operational reference. The generator
maps the problem-statement identifiers onto them without changing the solver's
own identifiers:

    ALP -> DTL city segment (Newton .. Fort Canning)
    BET -> CCL segment      (Dakota .. Keppel)

The interchange is physically two adjacent tunnels, one per line, each with
independent capacity. Both H01_H02 sectors therefore carry ``is_shared=0``, to
match the published public instance. Every capacity, programme, workfront and
access allocation produced by ``generate_mapped_instance.py`` is synthetic and
follows PS1 rules only. This module holds no demand data; it is a presentation
mapping plus mapping helpers.
"""

from __future__ import annotations

from typing import NamedTuple


class StationSpec(NamedTuple):
    """One published station id and the real interchange name it maps to."""

    station_id: str
    name: str
    is_interchange: bool


LINE_CODES: tuple[str, ...] = ("ALP", "BET")
LINE_NAMES: dict[str, str] = {"ALP": "Line Alpha", "BET": "Line Beta"}
LINE_TO_REAL_CODE: dict[str, str] = {"ALP": "DTL", "BET": "CCL"}
REAL_LINE_NAMES: dict[str, str] = {"DTL": "Downtown Line", "CCL": "Circle Line"}

ALP_STATIONS: tuple[StationSpec, ...] = (
    StationSpec("S01", "Newton", False),
    StationSpec("S02", "Little India", False),
    StationSpec("S03", "Rochor", False),
    StationSpec("S04", "Bugis", False),
    StationSpec("H01", "Promenade", True),
    StationSpec("H02", "Bayfront", True),
    StationSpec("S05", "Downtown", False),
    StationSpec("S06", "Telok Ayer", False),
    StationSpec("S07", "Chinatown", False),
    StationSpec("S08", "Fort Canning", False),
)

BET_STATIONS: tuple[StationSpec, ...] = (
    StationSpec("S11", "Dakota", False),
    StationSpec("S12", "Mountbatten", False),
    StationSpec("S13", "Stadium", False),
    StationSpec("S14", "Nicoll Highway", False),
    StationSpec("H01", "Promenade", True),
    StationSpec("H02", "Bayfront", True),
    StationSpec("S15", "Marina Bay", False),
    StationSpec("S16", "Prince Edward Road", False),
    StationSpec("S17", "Cantonment", False),
    StationSpec("S18", "Keppel", False),
)

STATIONS_BY_LINE: dict[str, tuple[StationSpec, ...]] = {
    "ALP": ALP_STATIONS,
    "BET": BET_STATIONS,
}

# The public instance carries ALP sector seq 1..9 and BET sector seq 10..18.
SECTOR_SEQ_BASE: dict[str, int] = {"ALP": 1, "BET": 10}

INTERCHANGE_SECTOR: tuple[str, str] = ("H01", "H02")
INTERCHANGE_STATIONS: tuple[str, ...] = ("H01", "H02")

# Tunnel sectors immediately either side of the shared interchange tunnel.
APPROACH_SECTOR_PAIRS: dict[str, frozenset[tuple[str, str]]] = {
    "ALP": frozenset({("S04", "H01"), ("H02", "S05")}),
    "BET": frozenset({("S14", "H01"), ("H02", "S15")}),
}

# Bugis to Marina Bay: the synthetic CBD bottleneck used by the congestion profile.
CBD_SECTOR_PAIRS: dict[str, frozenset[tuple[str, str]]] = {
    "ALP": frozenset(
        {("S03", "S04"), ("S04", "H01"), ("H01", "H02"), ("H02", "S05")}
    ),
    "BET": frozenset(
        {("S13", "S14"), ("S14", "H01"), ("H01", "H02"), ("H02", "S15")}
    ),
}


def stations(line_code: str) -> tuple[StationSpec, ...]:
    """Return the ordered station table for a line, seq ascending."""

    return STATIONS_BY_LINE[line_code]


def station_spec(line_code: str, station_id: str) -> StationSpec:
    """Return the station spec for a published station id on a line."""

    for spec in STATIONS_BY_LINE[line_code]:
        if spec.station_id == station_id:
            return spec
    raise KeyError(f"unknown station {station_id!r} on {line_code!r}")


def real_station_name(line_code: str, station_id: str) -> str:
    """Map a published station id to its real DTL/CCL station name."""

    return station_spec(line_code, station_id).name


def sector_pairs(line_code: str) -> tuple[tuple[str, str], ...]:
    """Return adjacent station pairs in sector seq order for a line."""

    specs = STATIONS_BY_LINE[line_code]
    return tuple(
        (specs[index].station_id, specs[index + 1].station_id)
        for index in range(len(specs) - 1)
    )


def sector_id(line_code: str, from_station: str, to_station: str) -> str:
    return f"SEC:{line_code}:{from_station}_{to_station}"


def tunnel_location(line_code: str, from_station: str, to_station: str, bound: str) -> str:
    return f"{sector_id(line_code, from_station, to_station)}:{bound}"


def platform_location(line_code: str, station_id: str, bound: str) -> str:
    return f"PLAT:{line_code}:{station_id}:{bound}"


def sector_seq(line_code: str, pair: tuple[str, str]) -> int:
    """Return the seq of a tunnel sector pair, raising when it is unknown."""

    for index, candidate in enumerate(sector_pairs(line_code)):
        if candidate == pair:
            return SECTOR_SEQ_BASE[line_code] + index
    raise KeyError(f"unknown sector {pair!r} on {line_code!r}")


def spans_cbd(line_code: str, start: tuple[str, str], end: tuple[str, str]) -> bool:
    """Whether the sector span between two endpoints touches the synthetic CBD."""

    pairs = sector_pairs(line_code)
    start_index = pairs.index(start)
    end_index = pairs.index(end)
    low, high = sorted((start_index, end_index))
    cbd = CBD_SECTOR_PAIRS[line_code]
    return any(pair in cbd for pair in pairs[low : high + 1])


def station_rows() -> tuple[tuple[str, str, int, int], ...]:
    """Rows for ``02_STATIONS.csv`` in published order."""

    rows: list[tuple[str, str, int, int]] = []
    for line_code in LINE_CODES:
        for seq, spec in enumerate(STATIONS_BY_LINE[line_code], start=1):
            rows.append((spec.station_id, line_code, seq, int(spec.is_interchange)))
    return tuple(rows)


def sector_rows() -> tuple[tuple[str, str, str, str, int, int], ...]:
    """Rows for ``03_SECTORS.csv``; H01_H02 stays per line, never shared.

    ``PS1_README`` describes the interchange as two physically separate tunnels
    with independent line capacity, and the published public instance sets
    ``is_shared=0`` for both H01_H02 sectors. The mapped topology matches that
    semantics, so ``is_shared`` is always 0 here.
    """

    rows: list[tuple[str, str, str, str, int, int]] = []
    for line_code in LINE_CODES:
        base = SECTOR_SEQ_BASE[line_code]
        for index, (from_station, to_station) in enumerate(sector_pairs(line_code)):
            shared = 0
            rows.append(
                (
                    sector_id(line_code, from_station, to_station),
                    line_code,
                    from_station,
                    to_station,
                    base + index,
                    shared,
                )
            )
    return tuple(rows)
