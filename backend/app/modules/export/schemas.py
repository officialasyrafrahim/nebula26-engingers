"""Exact, stable schemas for the three published submission files.

The submission contract is deliberately strict: column names and their order are
significant, values are unquoted integers or natural-key strings, and rows are
emitted in a deterministic order so two runs over the same plan produce
byte-identical files.

These models are intentionally independent of the solver so they can be reused
by the validator, the API and the CLI. ``eclo`` is kept as an ``int`` in
``0``/``1`` because that is exactly what the published files contain.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.rail.errors import Issue

ACCESS_FILE = "SCHEDULE_ACCESS.csv"
OCCUPANCY_FILE = "SCHEDULE_OCCUPANCY.csv"
RESULTS_FILE = "RESULTS.csv"

SUBMISSION_FILES: tuple[str, ...] = (ACCESS_FILE, OCCUPANCY_FILE, RESULTS_FILE)

ACCESS_HEADER: tuple[str, ...] = (
    "activity_id",
    "access_seq",
    "week",
    "eclo",
    "access_night",
)
OCCUPANCY_HEADER: tuple[str, ...] = (
    "activity_id",
    "week",
    "location_id",
    "co_share_group",
)
RESULTS_HEADER: tuple[str, ...] = (
    "scenario",
    "contract_number",
    "simulated_completion_date",
    "overrun_days",
)


class SubmissionParseError(ValueError):
    """Raised when a submission file is empty, malformed or has wrong headers."""

    def __init__(self, issues: Iterable[Issue], summary: str = "invalid submission"):
        self.issues: tuple[Issue, ...] = tuple(issues)
        rendered = "\n".join(str(issue) for issue in self.issues)
        super().__init__(rendered or summary)


class AccessRow(BaseModel):
    """One ``SCHEDULE_ACCESS.csv`` data row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    activity_id: str
    access_seq: int = Field(ge=1)
    week: int = Field(ge=1)
    eclo: int = Field(ge=0, le=1)
    access_night: int = Field(ge=1)

    @property
    def eclo_flag(self) -> bool:
        return self.eclo == 1


class OccupancyRow(BaseModel):
    """One ``SCHEDULE_OCCUPANCY.csv`` data row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    activity_id: str
    week: int = Field(ge=1)
    location_id: str
    co_share_group: str


class ResultRow(BaseModel):
    """One ``RESULTS.csv`` data row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario: str
    contract_number: str
    simulated_completion_date: date
    overrun_days: int = Field(ge=0)


_ROW_MODELS: dict[str, type[BaseModel]] = {
    ACCESS_FILE: AccessRow,
    OCCUPANCY_FILE: OccupancyRow,
    RESULTS_FILE: ResultRow,
}
_HEADERS: dict[str, tuple[str, ...]] = {
    ACCESS_FILE: ACCESS_HEADER,
    OCCUPANCY_FILE: OCCUPANCY_HEADER,
    RESULTS_FILE: RESULTS_HEADER,
}


def _new_reader(text: str) -> csv.reader:
    return csv.reader(io.StringIO(text.lstrip("\ufeff")))


def _parse_rows(
    file: str,
    text: str,
    model: type[BaseModel],
    header: tuple[str, ...],
) -> tuple[BaseModel, ...]:
    reader = _new_reader(text)
    try:
        actual = tuple(next(reader))
    except StopIteration:
        raise SubmissionParseError([Issue("file is empty", file=file)]) from None

    if actual != header:
        raise SubmissionParseError(
            [
                Issue(
                    "column mismatch: expected "
                    f"{','.join(header)} but found {','.join(actual)}",
                    file=file,
                )
            ]
        )

    records: list[BaseModel] = []
    issues: list[Issue] = []
    for raw in reader:
        if not raw or all(cell.strip() == "" for cell in raw):
            continue
        line_number = reader.line_num
        if len(raw) != len(header):
            issues.append(
                Issue(
                    f"expected {len(header)} columns but found {len(raw)}",
                    file=file,
                    row=line_number,
                )
            )
            continue
        data = {key: value.strip() for key, value in zip(header, raw, strict=True)}
        try:
            records.append(model.model_validate(data))
        except ValidationError as exc:
            for error in exc.errors():
                location = error.get("loc") or ()
                column = str(location[0]) if location else None
                issues.append(
                    Issue(
                        error.get("msg", "invalid value"),
                        file=file,
                        row=line_number,
                        column=column,
                        value=data.get(column) if column else None,
                    )
                )
    if issues:
        raise SubmissionParseError(issues)
    return tuple(records)


def parse_access(text: str) -> tuple[AccessRow, ...]:
    """Parse ``SCHEDULE_ACCESS.csv`` text, enforcing the exact header."""

    records = _parse_rows(ACCESS_FILE, text, AccessRow, ACCESS_HEADER)
    return tuple(record for record in records if isinstance(record, AccessRow))


def parse_occupancy(text: str) -> tuple[OccupancyRow, ...]:
    """Parse ``SCHEDULE_OCCUPANCY.csv`` text, enforcing the exact header."""

    records = _parse_rows(OCCUPANCY_FILE, text, OccupancyRow, OCCUPANCY_HEADER)
    return tuple(record for record in records if isinstance(record, OccupancyRow))


def parse_results(text: str) -> tuple[ResultRow, ...]:
    """Parse ``RESULTS.csv`` text, enforcing the exact header."""

    records = _parse_rows(RESULTS_FILE, text, ResultRow, RESULTS_HEADER)
    return tuple(record for record in records if isinstance(record, ResultRow))


def parse_submission_files(sources: Mapping[str, str]) -> tuple[
    tuple[AccessRow, ...], tuple[OccupancyRow, ...], tuple[ResultRow, ...]
]:
    """Parse a filename -> text mapping into the three typed row tuples."""

    missing = [name for name in SUBMISSION_FILES if name not in sources]
    if missing:
        raise SubmissionParseError(
            [Issue("missing required submission file", file=name) for name in missing]
        )
    unknown = [name for name in sources if name not in SUBMISSION_FILES]
    if unknown:
        raise SubmissionParseError(
            [Issue("unexpected submission file", file=name) for name in unknown]
        )
    return (
        parse_access(sources[ACCESS_FILE]),
        parse_occupancy(sources[OCCUPANCY_FILE]),
        parse_results(sources[RESULTS_FILE]),
    )


def _render(header: tuple[str, ...], rows: Iterable[tuple[object, ...]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def render_access(rows: Iterable[AccessRow]) -> str:
    """Render access rows in stable ``(activity_id, access_seq)`` order."""

    ordered = sorted(rows, key=lambda row: (row.activity_id, row.access_seq))
    return _render(
        ACCESS_HEADER,
        (
            (row.activity_id, row.access_seq, row.week, row.eclo, row.access_night)
            for row in ordered
        ),
    )


def render_occupancy(rows: Iterable[OccupancyRow]) -> str:
    """Render occupancy rows in stable ``(activity_id, week, location_id)`` order."""

    ordered = sorted(
        rows, key=lambda row: (row.activity_id, row.week, row.location_id)
    )
    return _render(
        OCCUPANCY_HEADER,
        (
            (row.activity_id, row.week, row.location_id, row.co_share_group)
            for row in ordered
        ),
    )


def render_results(rows: Iterable[ResultRow]) -> str:
    """Render result rows in stable ``(scenario, contract_number)`` order."""

    ordered = sorted(rows, key=lambda row: (row.scenario, row.contract_number))
    return _render(
        RESULTS_HEADER,
        (
            (
                row.scenario,
                row.contract_number,
                row.simulated_completion_date.isoformat(),
                row.overrun_days,
            )
            for row in ordered
        ),
    )


__all__ = [
    "ACCESS_FILE",
    "ACCESS_HEADER",
    "OCCUPANCY_FILE",
    "OCCUPANCY_HEADER",
    "RESULTS_FILE",
    "RESULTS_HEADER",
    "SUBMISSION_FILES",
    "AccessRow",
    "OccupancyRow",
    "ResultRow",
    "SubmissionParseError",
    "parse_access",
    "parse_occupancy",
    "parse_results",
    "parse_submission_files",
    "render_access",
    "render_occupancy",
    "render_results",
]
