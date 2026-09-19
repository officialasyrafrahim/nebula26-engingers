"""Submission bundle: the three per-scenario answer keys as one object.

A :class:`SubmissionBundle` is the unit of validation and export. Builders turn
solver output into a bundle, parsers turn the published CSVs into a bundle, and
the renderer turns the three files back into exact text. Every path sorts rows
deterministically, so the same logical plan always exports identically.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from app.domain.rail.errors import Issue
from app.modules.export.schemas import (
    ACCESS_FILE,
    OCCUPANCY_FILE,
    RESULTS_FILE,
    AccessRow,
    OccupancyRow,
    ResultRow,
    SubmissionParseError,
    parse_submission_files,
    render_access,
    render_occupancy,
    render_results,
)

# Import only for type checking. A runtime import here creates a cycle:
# export.bundle -> solver package -> solver.engine -> validator package ->
# validator.fallback_validator -> export.bundle. The annotation below is lazy
# because this module uses ``from __future__ import annotations``.
if TYPE_CHECKING:
    from app.modules.solver.results import SolverResult


class SubmissionBundle(BaseModel):
    """The three published submission files for exactly one scenario."""

    model_config = ConfigDict(frozen=True)

    scenario: str
    access: tuple[AccessRow, ...] = ()
    occupancy: tuple[OccupancyRow, ...] = ()
    results: tuple[ResultRow, ...] = ()

    @property
    def access_by_activity(self) -> dict[str, tuple[AccessRow, ...]]:
        grouped: dict[str, list[AccessRow]] = {}
        for row in self.access:
            grouped.setdefault(row.activity_id, []).append(row)
        return {
            activity_id: tuple(sorted(rows, key=lambda row: row.access_seq))
            for activity_id, rows in grouped.items()
        }

    @property
    def occupancy_by_activity_week(self) -> dict[tuple[str, int], frozenset[str]]:
        grouped: dict[tuple[str, int], set[str]] = {}
        for row in self.occupancy:
            grouped.setdefault((row.activity_id, row.week), set()).add(row.location_id)
        return {key: frozenset(locations) for key, locations in grouped.items()}

    def render_files(self) -> dict[str, str]:
        """Render the three files as text, keyed by published filename."""

        return {
            ACCESS_FILE: render_access(self.access),
            OCCUPANCY_FILE: render_occupancy(self.occupancy),
            RESULTS_FILE: render_results(self.results),
        }


def build_bundle(
    scenario: str,
    access: Iterable[AccessRow],
    occupancy: Iterable[OccupancyRow],
    results: Iterable[ResultRow],
) -> SubmissionBundle:
    """Build a bundle from row iterables, validating every row model."""

    return SubmissionBundle(
        scenario=scenario,
        access=tuple(access),
        occupancy=tuple(occupancy),
        results=tuple(results),
    )


def bundle_from_solver_result(result: SolverResult) -> SubmissionBundle:
    """Convert a :class:`~app.modules.solver.results.SolverResult` into a bundle.

    This is the only bridge between the solver lane and the export/validator
    lane. It reads the published result contract and does not import CP-SAT, so
    the resulting bundle can be validated exactly as a file-based submission.
    """

    scenario = result.scenario
    access = tuple(
        AccessRow(
            activity_id=row.activity_id,
            access_seq=row.access_seq,
            week=row.week,
            eclo=1 if row.eclo else 0,
            access_night=row.access_night,
        )
        for row in result.access
    )
    occupancy = tuple(
        OccupancyRow(
            activity_id=row.activity_id,
            week=row.week,
            location_id=row.location_id,
            co_share_group=row.co_share_group,
        )
        for row in result.occupancy
    )
    results = tuple(
        ResultRow(
            scenario=scenario,
            contract_number=item.contract_number,
            simulated_completion_date=item.simulated_completion_date,
            overrun_days=max(0, int(item.overrun_days)),
        )
        for item in result.contract_results
    )
    return SubmissionBundle(
        scenario=scenario, access=access, occupancy=occupancy, results=results
    )


def parse_bundle(sources: Mapping[str, str]) -> SubmissionBundle:
    """Parse a filename -> text mapping into a bundle, inferring the scenario."""

    access, occupancy, results = parse_submission_files(sources)
    scenarios = sorted({row.scenario for row in results})
    scenario = scenarios[0] if len(scenarios) == 1 else ""
    return SubmissionBundle(
        scenario=scenario, access=access, occupancy=occupancy, results=results
    )


def load_bundle(directory: str | os.PathLike[str]) -> SubmissionBundle:
    """Read the three submission files from a directory into a bundle."""

    root = Path(directory)
    sources: dict[str, str] = {}
    missing = []
    for name in (ACCESS_FILE, OCCUPANCY_FILE, RESULTS_FILE):
        path = root / name
        if not path.is_file():
            missing.append(name)
        else:
            sources[name] = path.read_text(encoding="utf-8-sig")
    if missing:
        raise SubmissionParseError(
            [Issue("missing required submission file", file=name) for name in missing]
        )
    return parse_bundle(sources)


def write_bundle(directory: str | os.PathLike[str], bundle: SubmissionBundle) -> dict[str, Path]:
    """Write the three files into ``directory`` and return their paths."""

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for filename, text in bundle.render_files().items():
        path = root / filename
        path.write_text(text, encoding="utf-8")
        written[filename] = path
    return written


__all__ = [
    "SubmissionBundle",
    "build_bundle",
    "bundle_from_solver_result",
    "load_bundle",
    "parse_bundle",
    "write_bundle",
]
