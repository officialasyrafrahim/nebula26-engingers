#!/usr/bin/env python3
"""Generate reproducible mapped DTL/CCL PS1 demonstration instances.

The generator writes exactly the eight published PS1 instance CSVs for a chosen
profile. The network is the public LTA Downtown Line and Circle Line topology
(``scripts/mapped_network.py``); every capacity, programme, workfront, planned
date and access allocation is synthetic and follows PS1 rules only. The solver
keeps using the problem-statement identifiers (ALP/BET, S01.., H01/H02); the
real station names live in ``contract_description`` and in ``data/mapped/README.md``.

Profiles
--------
``baseline``
    Normal A/B/C workload spread across both lines and bounds with generous
    outer supply.
``congestion``
    Baseline structure with heavier synthetic demand across Bugis to Marina Bay
    and tighter supply at the H01/H02 CBD bottleneck.
``disruption``
    Byte-identical baseline demand with the H01/H02 interchange supply reduced,
    to exercise replanning.

Determinism: the same ``(profile, seed)`` pair always writes identical bytes.

Usage::

    python3 scripts/generate_mapped_instance.py \
        --profile baseline --outdir data/mapped/baseline --seed 42
"""

from __future__ import annotations

import argparse
import csv
import io
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
_SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, _SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import mapped_network as net  # noqa: E402

from app.modules.instance.schemas import (  # noqa: E402
    FILE_HEADERS,
    INSTANCE_FILES,
    PARAMETER_HEADERS,
)

HORIZON_START = date(2027, 1, 4)
HORIZON_WEEKS = 30
BOUNDS: tuple[str, ...] = ("EB", "WB")
LIVE_NATURE = "Live"

# Fixed PS1 buffer policy (05_BUFFER_LOCATION.csv).
BUFFER_RULES: tuple[tuple[str, int, int], ...] = (
    ("Live", 2, 1),
    ("Non-live (Consist)", 1, 0),
    ("Non-live (Others)", 0, 0),
)

# Synthetic supply ladders per profile. Outer sectors are generous, supply drops
# approaching the interchange, and H01_H02 is the bottleneck.
SUPPLY_PROFILES: dict[str, dict[str, int]] = {
    "baseline": {
        "outer": 4,
        "approach": 3,
        "interchange": 2,
        "platform_normal": 3,
        "platform_interchange": 2,
    },
    "congestion": {
        "outer": 4,
        "approach": 2,
        "interchange": 1,
        "platform_normal": 3,
        "platform_interchange": 1,
    },
    "disruption": {
        "outer": 4,
        "approach": 3,
        "interchange": 1,
        "platform_normal": 3,
        "platform_interchange": 1,
    },
}

PROFILES: tuple[str, ...] = ("baseline", "congestion", "disruption")


class ContractTemplate(NamedTuple):
    number: str
    activity_type: str
    nature: str
    priority: int
    access_type: str
    workfronts: int


class ActivityTemplate(NamedTuple):
    line: str
    bound: str
    start: tuple[str, str]
    end: tuple[str, str]
    accesses: int
    priority: int
    predecessor: int | None


class BuiltActivity(NamedTuple):
    activity_id: str
    contract: ContractTemplate
    template: ActivityTemplate
    total_accesses: int
    start_week: int
    predecessor_id: str


CONTRACTS: tuple[ContractTemplate, ...] = (
    ContractTemplate("C001", "Renewal", "Non-live (Consist)", 3, "C", 2),
    ContractTemplate("C002", "Renewal", "Non-live (Consist)", 2, "C", 1),
    ContractTemplate("C003", "Construction", "Non-live (Others)", 1, "C", 1),
    ContractTemplate("C004", "Renewal", "Non-live (Consist)", 1, "PC", 1),
    ContractTemplate("C005", "Renewal", "Non-live (Consist)", 3, "PC", 2),
    ContractTemplate("C006", "Construction", "Non-live (Others)", 3, "C", 1),
    ContractTemplate("C007", "Renewal", "Non-live (Consist)", 1, "C", 1),
    ContractTemplate("C008", "Renewal", "Non-live (Consist)", 3, "C", 1),
    ContractTemplate("C009", "Construction", "Non-live (Others)", 3, "PC", 1),
    ContractTemplate("C010", "Construction", "Non-live (Others)", 3, "C", 2),
    ContractTemplate("C011", "Renewal", "Non-live (Consist)", 2, "C", 1),
    ContractTemplate("C012", "Construction", "Non-live (Others)", 1, "C", 1),
    ContractTemplate("C013", "Renewal", "Live", 2, "PC", 1),
    ContractTemplate("C014", "Construction", "Live", 3, "PM", 1),
)

# Dependency edges are indices into the same contract's activity list, always
# pointing backwards, so the graph is acyclic by construction.
ACTIVITY_TEMPLATES: dict[str, tuple[ActivityTemplate, ...]] = {
    "C001": (
        ActivityTemplate("ALP", "WB", ("S01", "S02"), ("S03", "S04"), 3, 2, None),
        ActivityTemplate("BET", "EB", ("H02", "S15"), ("S17", "S18"), 3, 1, None),
        ActivityTemplate("ALP", "EB", ("S06", "S07"), ("S07", "S08"), 2, 3, 0),
        ActivityTemplate("BET", "WB", ("S11", "S12"), ("S12", "S13"), 2, 3, 1),
    ),
    "C002": (
        ActivityTemplate("ALP", "WB", ("S02", "S03"), ("H01", "H02"), 4, 1, None),
        ActivityTemplate("BET", "EB", ("S12", "S13"), ("H01", "H02"), 4, 2, None),
        ActivityTemplate("BET", "WB", ("H01", "H02"), ("S15", "S16"), 3, 2, 1),
    ),
    "C003": (
        ActivityTemplate("BET", "EB", ("S11", "S12"), ("S12", "S13"), 3, 3, None),
        ActivityTemplate("ALP", "EB", ("S01", "S02"), ("S02", "S03"), 2, 3, None),
        ActivityTemplate("ALP", "WB", ("S07", "S08"), ("S07", "S08"), 2, 2, 1),
    ),
    "C004": (
        ActivityTemplate("ALP", "WB", ("S03", "S04"), ("H01", "H02"), 4, 1, None),
        ActivityTemplate("BET", "EB", ("S13", "S14"), ("H01", "H02"), 4, 1, None),
        ActivityTemplate("ALP", "EB", ("S02", "S03"), ("S03", "S04"), 3, 2, 0),
    ),
    "C005": (
        ActivityTemplate("ALP", "EB", ("S01", "S02"), ("S02", "S03"), 3, 2, None),
        ActivityTemplate("BET", "WB", ("S15", "S16"), ("S17", "S18"), 3, 3, None),
        ActivityTemplate("BET", "EB", ("S12", "S13"), ("S13", "S14"), 4, 2, 1),
    ),
    "C006": (
        ActivityTemplate("ALP", "WB", ("S01", "S02"), ("S01", "S02"), 2, 3, None),
        ActivityTemplate("BET", "EB", ("S16", "S17"), ("S17", "S18"), 2, 2, None),
        ActivityTemplate("ALP", "EB", ("S05", "S06"), ("S06", "S07"), 3, 3, 0),
    ),
    "C007": (
        ActivityTemplate("BET", "EB", ("S12", "S13"), ("H01", "H02"), 5, 1, None),
        ActivityTemplate("ALP", "WB", ("S04", "H01"), ("H02", "S05"), 4, 1, None),
        ActivityTemplate("BET", "WB", ("H01", "H02"), ("H02", "S15"), 3, 2, 0),
    ),
    "C008": (
        ActivityTemplate("ALP", "EB", ("S01", "S02"), ("S03", "S04"), 3, 3, None),
        ActivityTemplate("BET", "WB", ("S11", "S12"), ("S12", "S13"), 2, 2, None),
        ActivityTemplate("ALP", "WB", ("S06", "S07"), ("S07", "S08"), 2, 2, 0),
    ),
    "C009": (
        ActivityTemplate("BET", "EB", ("S13", "S14"), ("S14", "H01"), 4, 2, None),
        ActivityTemplate("ALP", "EB", ("H01", "H02"), ("H02", "S05"), 3, 1, None),
        ActivityTemplate("BET", "WB", ("H02", "S15"), ("S15", "S16"), 2, 3, 1),
    ),
    "C010": (
        ActivityTemplate("ALP", "EB", ("S07", "S08"), ("S07", "S08"), 3, 3, None),
        ActivityTemplate("BET", "WB", ("S12", "S13"), ("S13", "S14"), 4, 3, None),
        ActivityTemplate("ALP", "WB", ("S02", "S03"), ("S03", "S04"), 3, 2, 0),
    ),
    "C011": (
        ActivityTemplate("BET", "EB", ("H01", "H02"), ("S16", "S17"), 3, 2, None),
        ActivityTemplate("ALP", "WB", ("H01", "H02"), ("H02", "S05"), 3, 2, None),
        ActivityTemplate("BET", "WB", ("S12", "S13"), ("S13", "S14"), 2, 3, 0),
    ),
    "C012": (
        ActivityTemplate("ALP", "EB", ("S03", "S04"), ("S03", "S04"), 2, 2, None),
        ActivityTemplate("BET", "EB", ("S11", "S12"), ("S11", "S12"), 2, 3, None),
        ActivityTemplate("ALP", "WB", ("H02", "S05"), ("H02", "S05"), 1, 3, 0),
    ),
    "C013": (
        ActivityTemplate("ALP", "EB", ("H01", "H02"), ("H01", "H02"), 3, 2, None),
        ActivityTemplate("ALP", "WB", ("H01", "H02"), ("H01", "H02"), 2, 3, None),
    ),
    "C014": (
        ActivityTemplate("BET", "EB", ("H01", "H02"), ("H01", "H02"), 2, 2, None),
        ActivityTemplate("BET", "WB", ("H01", "H02"), ("H01", "H02"), 2, 3, None),
    ),
}

CONTRACT_AWARD_BASE = date(2026, 1, 5)


def _csv_text(header: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    """Render rows with LF terminators, no BOM and plain commas."""

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def _week_end(start: date, week: int) -> date:
    return start + timedelta(days=(week - 1) * 7 + 6)


def _week_start(start: date, week: int) -> date:
    return start + timedelta(days=(week - 1) * 7)


def _validate_templates() -> None:
    for templates in ACTIVITY_TEMPLATES.values():
        for template in templates:
            pairs = net.sector_pairs(template.line)
            for pair in (template.start, template.end):
                if pair not in pairs:
                    raise ValueError(
                        f"activity template references unknown sector {pair!r} "
                        f"on {template.line!r}"
                    )


def _is_live(contract: ContractTemplate) -> bool:
    return contract.nature == LIVE_NATURE


def _access_count(
    template: ActivityTemplate,
    rng: random.Random,
    *,
    scale_cbd: bool,
) -> int:
    value = template.accesses
    if value >= 2:
        value += rng.choice((-1, 0, 1))
    value = max(1, min(6, value))
    if scale_cbd and net.spans_cbd(template.line, template.start, template.end):
        value = min(7, value + 3)
    return value


def _start_week(
    template: ActivityTemplate,
    rng: random.Random,
    start_weeks: list[int],
) -> int:
    week = rng.randint(1, 12)
    if template.predecessor is not None:
        week = max(week, start_weeks[template.predecessor] + 1)
    return min(week, 22)


def build_activities(*, scale_cbd: bool, seed: int) -> list[BuiltActivity]:
    """Deterministically build the synthetic activity list for a profile."""

    rng = random.Random(seed)
    built: list[BuiltActivity] = []
    next_index = 1
    for contract in CONTRACTS:
        templates = ACTIVITY_TEMPLATES[contract.number]
        start_weeks: list[int] = []
        activity_ids: list[str] = []
        for template in templates:
            activity_id = f"A{next_index:03d}"
            next_index += 1
            week = _start_week(template, rng, start_weeks)
            accesses = _access_count(template, rng, scale_cbd=scale_cbd)
            predecessor_id = (
                activity_ids[template.predecessor]
                if template.predecessor is not None
                else ""
            )
            built.append(
                BuiltActivity(
                    activity_id=activity_id,
                    contract=contract,
                    template=template,
                    total_accesses=accesses,
                    start_week=week,
                    predecessor_id=predecessor_id,
                )
            )
            start_weeks.append(week)
            activity_ids.append(activity_id)
    return built


def _describe_contract(contract: ContractTemplate, first: BuiltActivity) -> str:
    template = first.template
    real_code = net.LINE_TO_REAL_CODE[template.line]
    start_name = net.real_station_name(template.line, template.start[0])
    end_name = net.real_station_name(template.line, template.end[1])
    return (
        f"{contract.activity_type} programme {contract.number}: "
        f"{real_code} {start_name} to {end_name}"
    )


def _contract_rows(built: list[BuiltActivity]) -> list[tuple[object, ...]]:
    by_contract: dict[str, list[BuiltActivity]] = {}
    for activity in built:
        by_contract.setdefault(activity.contract.number, []).append(activity)

    rows: list[tuple[object, ...]] = []
    for index, contract in enumerate(CONTRACTS):
        activities = by_contract[contract.number]
        planned_week = HORIZON_WEEKS - (index % 3)
        planned = _week_end(HORIZON_START, planned_week)
        completion = planned + timedelta(days=28)
        award = CONTRACT_AWARD_BASE + timedelta(days=index * 11)
        weekly_cap = 2 if _is_live(contract) else 3
        rows.append(
            (
                contract.number,
                _describe_contract(contract, activities[0]),
                award.isoformat(),
                contract.activity_type,
                contract.nature,
                contract.priority,
                completion.isoformat(),
                planned.isoformat(),
                contract.workfronts,
                contract.access_type,
                weekly_cap,
            )
        )
    return rows


def _activity_rows(built: list[BuiltActivity]) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for activity in built:
        template = activity.template
        start_location = net.tunnel_location(
            template.line, template.start[0], template.start[1], template.bound
        )
        end_location = net.tunnel_location(
            template.line, template.end[0], template.end[1], template.bound
        )
        rows.append(
            (
                activity.activity_id,
                activity.contract.number,
                activity.contract.activity_type,
                start_location,
                end_location,
                activity.total_accesses,
                _week_start(HORIZON_START, activity.start_week).isoformat(),
                activity.predecessor_id,
                template.priority,
            )
        )
    return rows


def _location_rows(profile: str) -> list[tuple[object, ...]]:
    table = SUPPLY_PROFILES[profile]
    rows: list[tuple[object, ...]] = []

    for line_code in net.LINE_CODES:
        for pair in net.sector_pairs(line_code):
            for bound in BOUNDS:
                if pair == net.INTERCHANGE_SECTOR:
                    capacity = table["interchange"]
                elif pair in net.APPROACH_SECTOR_PAIRS[line_code]:
                    capacity = table["approach"]
                else:
                    capacity = table["outer"]
                rows.append(
                    (
                        net.tunnel_location(line_code, pair[0], pair[1], bound),
                        "tunnel sector",
                        line_code,
                        bound,
                        capacity,
                    )
                )

    for line_code in net.LINE_CODES:
        for spec in net.stations(line_code):
            capacity = (
                table["platform_interchange"]
                if spec.is_interchange
                else table["platform_normal"]
            )
            for bound in BOUNDS:
                rows.append(
                    (
                        net.platform_location(line_code, spec.station_id, bound),
                        "platform sector",
                        line_code,
                        bound,
                        capacity,
                    )
                )
    return rows


def build_files(profile: str, seed: int) -> dict[str, str]:
    """Return the eight CSV texts for ``(profile, seed)`` without writing."""

    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; choose from {PROFILES}")

    _validate_templates()
    scale_cbd = profile == "congestion"
    built = build_activities(scale_cbd=scale_cbd, seed=seed)

    line_rows = [(code, net.LINE_NAMES[code]) for code in net.LINE_CODES]
    parameter_rows: list[tuple[object, ...]] = [
        ("horizon_start", HORIZON_START.isoformat()),
        ("horizon_weeks", HORIZON_WEEKS),
    ]
    buffer_rows: list[tuple[object, ...]] = [
        (nature, buffer, int(opposite)) for nature, buffer, opposite in BUFFER_RULES
    ]

    content: dict[str, str] = {
        "01_LINES.csv": _csv_text(FILE_HEADERS["01_LINES.csv"], line_rows),
        "02_STATIONS.csv": _csv_text(FILE_HEADERS["02_STATIONS.csv"], list(net.station_rows())),
        "03_SECTORS.csv": _csv_text(FILE_HEADERS["03_SECTORS.csv"], list(net.sector_rows())),
        "04_LOCATION_SUPPLY.csv": _csv_text(
            FILE_HEADERS["04_LOCATION_SUPPLY.csv"], _location_rows(profile)
        ),
        "05_BUFFER_LOCATION.csv": _csv_text(
            FILE_HEADERS["05_BUFFER_LOCATION.csv"], buffer_rows
        ),
        "06_PARAMETERS.csv": _csv_text(PARAMETER_HEADERS, parameter_rows),
        "07_PROJECT_DETAILS.csv": _csv_text(
            FILE_HEADERS["07_PROJECT_DETAILS.csv"], _contract_rows(built)
        ),
        "08_ACTIVITY_DETAILS.csv": _csv_text(
            FILE_HEADERS["08_ACTIVITY_DETAILS.csv"], _activity_rows(built)
        ),
    }
    return content


def write_files(outdir: str | Path, files: dict[str, str]) -> None:
    """Write the eight files as UTF-8 without BOM and with LF terminators."""

    root = Path(outdir)
    root.mkdir(parents=True, exist_ok=True)
    for name in INSTANCE_FILES:
        (root / name).write_bytes(files[name].encode("utf-8"))


def generate(profile: str, outdir: str | Path, seed: int = 42) -> dict[str, str]:
    """Build and write one mapped instance; return the CSV texts."""

    files = build_files(profile, seed)
    write_files(outdir, files)
    return files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default="baseline")
    parser.add_argument(
        "--outdir",
        default=None,
        help="output directory (default: data/mapped/<profile>)",
    )
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    outdir = Path(args.outdir) if args.outdir else REPO_ROOT / "data" / "mapped" / args.profile
    files = generate(args.profile, outdir, args.seed)
    print(
        f"profile={args.profile} seed={args.seed} outdir={outdir} "
        f"files={len(files)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
