"""Structured, actionable issues for rail instance parsing and validation.

Issues are plain data so they can be collected across files and rows and then
surfaced through the API or CLI without leaking implementation detail. The
``file``/``row``/``column`` fields are populated by the CSV parser; domain
validation issues name the offending natural keys in ``message`` instead.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    """One actionable problem found in an instance file or the domain model."""

    message: str
    file: str | None = None
    row: int | None = None
    column: str | None = None
    value: str | None = None

    def __str__(self) -> str:
        location = self.file or "<instance>"
        if self.row is not None:
            location = f"{location}:{self.row}"
        if self.column:
            location = f"{location}:{self.column}"
        suffix = f" (value={self.value!r})" if self.value is not None else ""
        return f"{location}: {self.message}{suffix}"


class RailDataError(ValueError):
    """Raised when an instance cannot be parsed or validated.

    Carries the full list of :class:`Issue` objects so callers can present
    every problem at once rather than failing on the first one.
    """

    def __init__(self, issues: Iterable[Issue], summary: str = "invalid rail instance") -> None:
        self.issues: tuple[Issue, ...] = tuple(issues)
        rendered = "\n".join(str(issue) for issue in self.issues)
        super().__init__(rendered or summary)


class InstanceParseError(RailDataError):
    """Raised when the eight instance CSVs fail schema-level parsing."""


class InstanceValidationError(RailDataError):
    """Raised when parsed records fail canonical domain validation."""


def render_issues(issues: Sequence[Issue]) -> str:
    """Render issues for human-readable logging."""

    return "\n".join(str(issue) for issue in issues)
