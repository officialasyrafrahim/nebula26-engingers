"""Shared helpers for the rail instance/compiler tests."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from pathlib import Path

from app.domain.rail.compiled import CompiledInstance
from app.domain.rail.instance_model import PlanningInstance
from app.modules.compiler.rule_compiler import compile_instance
from app.modules.instance.parser import parse_directory, parse_mapping
from app.modules.instance.schemas import INSTANCE_FILES, ParsedInstance
from app.modules.instance.service import build_planning_instance

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_INSTANCE_DIR = REPO_ROOT / "data" / "public-instance"
SUBMISSION_SAMPLE_DIR = REPO_ROOT / "data" / "submission-sample"


def read_instance_source() -> dict[str, str]:
    """Read the public instance files as raw text, keyed by filename."""

    return {
        name: (PUBLIC_INSTANCE_DIR / name).read_text(encoding="utf-8-sig")
        for name in INSTANCE_FILES
    }


def parse_public() -> ParsedInstance:
    return parse_directory(PUBLIC_INSTANCE_DIR)


def instance_from_source(source: Mapping[str, object]) -> PlanningInstance:
    return build_planning_instance(parse_mapping(source))


def load_public_instance() -> PlanningInstance:
    return build_planning_instance(parse_public())


def load_public_compiled() -> CompiledInstance:
    return compile_instance(load_public_instance())


def sample_occupancy_rows() -> list[dict[str, str]]:
    with (SUBMISSION_SAMPLE_DIR / "SCHEDULE_OCCUPANCY.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        return list(csv.DictReader(handle))


def sample_occupancy_locations() -> dict[str, frozenset[str]]:
    """Distinct location set per activity, ignoring week and co-share label."""

    grouped: dict[str, set[str]] = {}
    for row in sample_occupancy_rows():
        grouped.setdefault(row["activity_id"], set()).add(row["location_id"])
    return {activity_id: frozenset(locations) for activity_id, locations in grouped.items()}


def sample_access_rows() -> list[dict[str, str]]:
    with (SUBMISSION_SAMPLE_DIR / "SCHEDULE_ACCESS.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        return list(csv.DictReader(handle))
