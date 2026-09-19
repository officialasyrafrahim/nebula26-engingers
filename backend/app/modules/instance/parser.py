"""Directory and mapping parser for the eight published instance CSVs.

Only the eight named files are accepted. Every file is header-checked in order,
then each data row is validated into a frozen typed record. All problems are
collected and raised together so an operator sees every bad file and row at once.
"""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.rail.errors import InstanceParseError, Issue
from app.domain.rail.instance_model import Parameters
from app.modules.instance.schemas import (
    FILE_HEADERS,
    INSTANCE_FILES,
    PARAMETER_HEADERS,
    PARAMETER_KEYS,
    PARAMETERS_FILE,
    ROW_MODELS,
    ParsedInstance,
)


def parse_directory(directory: str | os.PathLike[str]) -> ParsedInstance:
    """Parse the eight instance files from a directory."""

    root = Path(directory)
    if not root.is_dir():
        raise InstanceParseError(
            [Issue("instance directory does not exist", file=str(root))]
        )

    issues: list[Issue] = []
    sources: dict[str, str] = {}
    for name in INSTANCE_FILES:
        path = root / name
        if not path.is_file():
            issues.append(Issue("missing required instance file", file=name))
            continue
        try:
            sources[name] = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            issues.append(Issue(f"invalid UTF-8 encoding: {exc.reason}", file=name))
    if issues:
        raise InstanceParseError(issues)
    return _parse_sources(sources)


def parse_mapping(mapping: Mapping[str, object]) -> ParsedInstance:
    """Parse the eight instance files from a name -> content mapping.

    Accepted values are ``str``, ``bytes``, filesystem paths or file-like
    objects. Unknown or missing names are reported as per-file issues.
    """

    issues: list[Issue] = []
    sources: dict[str, str] = {}
    for key, value in mapping.items():
        name = Path(str(key)).name
        if name not in FILE_HEADERS:
            issues.append(Issue("unexpected instance file", file=name))
            continue
        if name in sources:
            issues.append(Issue("duplicate instance file", file=name))
            continue
        try:
            sources[name] = _as_text(value, name)
        except InstanceParseError as exc:
            issues.extend(exc.issues)

    for name in INSTANCE_FILES:
        if name not in sources:
            issues.append(Issue("missing required instance file", file=name))
    if issues:
        raise InstanceParseError(issues)
    return _parse_sources(sources)


def _as_text(value: object, name: str) -> str:
    if isinstance(value, bytes):
        return _decode(value, name)
    if isinstance(value, str):
        return value
    if isinstance(value, os.PathLike):
        return _decode(Path(value).read_bytes(), name)
    read = getattr(value, "read", None)
    if callable(read):
        data = read()
        if isinstance(data, bytes):
            return _decode(data, name)
        return str(data)
    raise InstanceParseError(
        [Issue(f"unsupported source type {type(value).__name__}", file=name)]
    )


def _decode(data: bytes, name: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InstanceParseError(
            [Issue(f"invalid UTF-8 encoding: {exc.reason}", file=name)]
        ) from None


def _parse_sources(sources: Mapping[str, str]) -> ParsedInstance:
    issues: list[Issue] = []
    rows: dict[str, tuple[Any, ...]] = {}
    parameters: Parameters | None = None

    for name in INSTANCE_FILES:
        try:
            if name == PARAMETERS_FILE:
                parameters = _parse_parameters(name, sources[name])
            else:
                rows[name] = _parse_rows(
                    name, ROW_MODELS[name], FILE_HEADERS[name], sources[name]
                )
        except InstanceParseError as exc:
            issues.extend(exc.issues)

    if issues or parameters is None:
        raise InstanceParseError(issues)

    return ParsedInstance(
        lines=rows["01_LINES.csv"],
        stations=rows["02_STATIONS.csv"],
        sectors=rows["03_SECTORS.csv"],
        locations=rows["04_LOCATION_SUPPLY.csv"],
        buffer_rules=rows["05_BUFFER_LOCATION.csv"],
        parameters=parameters,
        contracts=rows["07_PROJECT_DETAILS.csv"],
        activities=rows["08_ACTIVITY_DETAILS.csv"],
    )


def _reader(text: str) -> csv.reader:
    return csv.reader(io.StringIO(text.lstrip("\ufeff")), strict=True)


def _header_issues(name: str, header: list[str], expected: tuple[str, ...]) -> list[Issue]:
    issues: list[Issue] = []
    duplicates = sorted({column for column in header if header.count(column) > 1})
    if duplicates:
        issues.append(
            Issue(f"duplicate column(s): {', '.join(duplicates)}", file=name)
        )
    missing = [column for column in expected if column not in header]
    unexpected = [column for column in header if column not in expected]
    if missing:
        issues.append(Issue(f"missing required column(s): {', '.join(missing)}", file=name))
    if unexpected:
        issues.append(Issue(f"unexpected column(s): {', '.join(unexpected)}", file=name))
    if not missing and not unexpected and header != list(expected):
        issues.append(
            Issue(
                "column order mismatch: expected "
                f"{', '.join(expected)} but found {', '.join(header)}",
                file=name,
            )
        )
    return issues


def _parse_rows(
    name: str,
    model: type[BaseModel],
    expected: tuple[str, ...],
    text: str,
) -> tuple[Any, ...]:
    reader = _reader(text)
    try:
        header = next(reader)
    except StopIteration:
        raise InstanceParseError([Issue("file is empty", file=name)]) from None
    except csv.Error as exc:
        raise InstanceParseError(
            [Issue(f"malformed CSV: {exc}", file=name, row=reader.line_num)]
        ) from None

    header_issues = _header_issues(name, header, expected)
    if header_issues:
        raise InstanceParseError(header_issues)

    records: list[Any] = []
    issues: list[Issue] = []
    try:
        for raw in reader:
            if not raw or all(cell.strip() == "" for cell in raw):
                continue
            line_number = reader.line_num
            if len(raw) != len(expected):
                issues.append(
                    Issue(
                        f"expected {len(expected)} columns but found {len(raw)}",
                        file=name,
                        row=line_number,
                    )
                )
                continue
            data = _normalise(dict(zip(expected, raw, strict=True)))
            try:
                records.append(model.model_validate(data))
            except ValidationError as exc:
                for error in exc.errors():
                    location = error.get("loc") or ()
                    column = str(location[0]) if location else None
                    value = data.get(column) if column else None
                    issues.append(
                        Issue(
                            error.get("msg", "invalid value"),
                            file=name,
                            row=line_number,
                            column=column,
                            value=None if value is None else str(value),
                        )
                    )
    except csv.Error as exc:
        issues.append(Issue(f"malformed CSV: {exc}", file=name, row=reader.line_num))

    if issues:
        raise InstanceParseError(issues)
    return tuple(records)


def _normalise(data: dict[str, Any]) -> dict[str, Any]:
    normalised: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip()
        normalised[key] = value
    if normalised.get("predecessor_activity_id") == "":
        normalised["predecessor_activity_id"] = None
    return normalised


def _parse_parameters(name: str, text: str) -> Parameters:
    reader = _reader(text)
    try:
        header = next(reader)
    except StopIteration:
        raise InstanceParseError([Issue("file is empty", file=name)]) from None
    except csv.Error as exc:
        raise InstanceParseError(
            [Issue(f"malformed CSV: {exc}", file=name, row=reader.line_num)]
        ) from None

    header_issues = _header_issues(name, header, PARAMETER_HEADERS)
    if header_issues:
        raise InstanceParseError(header_issues)

    values: dict[str, str] = {}
    issues: list[Issue] = []
    try:
        for raw in reader:
            if not raw or all(cell.strip() == "" for cell in raw):
                continue
            line_number = reader.line_num
            if len(raw) != len(PARAMETER_HEADERS):
                issues.append(
                    Issue(
                        f"expected {len(PARAMETER_HEADERS)} columns but found {len(raw)}",
                        file=name,
                        row=line_number,
                    )
                )
                continue
            key, value = raw[0].strip(), raw[1].strip()
            if key in values:
                issues.append(
                    Issue(f"duplicate parameter key {key!r}", file=name, row=line_number)
                )
                continue
            values[key] = value
    except csv.Error as exc:
        issues.append(Issue(f"malformed CSV: {exc}", file=name, row=reader.line_num))

    for required in PARAMETER_KEYS:
        if required not in values:
            issues.append(Issue(f"missing required parameter {required!r}", file=name))
    if issues:
        raise InstanceParseError(issues)

    try:
        return Parameters.model_validate(
            {key: values[key] for key in PARAMETER_KEYS}
        )
    except ValidationError as exc:
        issues = []
        for error in exc.errors():
            location = error.get("loc") or ()
            column = str(location[0]) if location else None
            issues.append(
                Issue(
                    error.get("msg", "invalid value"),
                    file=name,
                    column=column,
                    value=values.get(column) if column else None,
                )
            )
        raise InstanceParseError(issues) from None
