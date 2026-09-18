"""Per-scenario zip export.

Each scenario is a distinct answer key. The archive for a scenario contains
exactly the three published files at the archive root, so it can be uploaded or
inspected without a directory walk. ``trackaccess``-style expander tooling is a
later convenience; the XML-free zip layout is the contract the judges consume.
"""

from __future__ import annotations

import io
import os
import zipfile
from collections.abc import Iterable
from pathlib import Path

from app.modules.export.bundle import SubmissionBundle
from app.modules.export.schemas import SUBMISSION_FILES

DEFAULT_ARCHIVE_SUFFIX = "submission"


def scenario_archive_name(scenario: str, suffix: str = DEFAULT_ARCHIVE_SUFFIX) -> str:
    """Return the conventional archive filename for a scenario."""

    return f"scenario_{scenario}_{suffix}.zip"


def export_scenario_zip(bundle: SubmissionBundle) -> bytes:
    """Return the in-memory zip archive for one scenario bundle."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, text in bundle.render_files().items():
            archive.writestr(filename, text)
    return buffer.getvalue()


def write_scenario_zip(
    path: str | os.PathLike[str], bundle: SubmissionBundle
) -> Path:
    """Write one scenario's zip archive to ``path`` and return the path."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(export_scenario_zip(bundle))
    return target


def export_scenarios_zip(bundles: Iterable[SubmissionBundle]) -> bytes:
    """Return a single archive with one ``scenario_X/`` directory per bundle."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for bundle in bundles:
            for filename, text in bundle.render_files().items():
                archive.writestr(f"scenario_{bundle.scenario}/{filename}", text)
    return buffer.getvalue()


def archive_members(payload: bytes) -> tuple[str, ...]:
    """Return the member names of an in-memory archive, for tests and callers."""

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return tuple(archive.namelist())


__all__ = [
    "DEFAULT_ARCHIVE_SUFFIX",
    "SUBMISSION_FILES",
    "archive_members",
    "export_scenario_zip",
    "export_scenarios_zip",
    "scenario_archive_name",
    "write_scenario_zip",
]
