"""Strict scalar parsers for the published CSV boundary.

Pydantic's lax mode is deliberately permissive: it accepts ``01``, ``+1`` and
``1.0`` as integers, ``true``/``yes``/``on`` as booleans, and datetime strings
as dates. The published instance format promises exact spellings, so these
annotated types reject anything that is not the canonical form. They are applied
to the frozen network and instance records so a malformed hidden instance fails
with a structured issue instead of being coerced into a plausible value.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated

from pydantic import BeforeValidator

_INTEGER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def strict_int(value: object) -> int:
    """Accept only a canonical base-10 integer spelling."""

    if isinstance(value, bool):
        raise ValueError("expected an integer, got a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _INTEGER_RE.match(value):
        return int(value)
    raise ValueError(f"integer must be spelled as an exact decimal: {value!r}")


def strict_bool(value: object) -> bool:
    """Accept only ``0``/``1`` (or the Python bools they map to)."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if value == "0":
        return False
    if value == "1":
        return True
    raise ValueError(f"boolean must be exactly 0 or 1: {value!r}")


def strict_date(value: object) -> date:
    """Accept only an exact ``YYYY-MM-DD`` calendar date."""

    if isinstance(value, datetime):
        raise ValueError(f"date must be exactly YYYY-MM-DD: {value!r}")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _DATE_RE.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"date must be exactly YYYY-MM-DD: {value!r}") from exc
    raise ValueError(f"date must be exactly YYYY-MM-DD: {value!r}")


StrictInt = Annotated[int, BeforeValidator(strict_int)]
StrictBool = Annotated[bool, BeforeValidator(strict_bool)]
StrictDate = Annotated[date, BeforeValidator(strict_date)]
