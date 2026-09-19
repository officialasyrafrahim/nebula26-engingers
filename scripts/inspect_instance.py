#!/usr/bin/env python3
"""Read-only inspection report for an eight-file PS1 instance directory.

Parses and compiles the directory through the same code paths as the API, then
prints file presence, parse issues, entity counts, the planning horizon,
activity and contract counts and a compile summary. It never writes to the
instance and exits non-zero if any file is missing or fails to parse, validate
or compile.

Usage::

    python3 scripts/inspect_instance.py data/public-instance
    python3 scripts/inspect_instance.py /path/to/instance
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
SCRIPT_PATH = Path(__file__).resolve()


def _local_venv_python() -> Path | None:
    for candidate in (
        BACKEND_ROOT / ".venv" / "bin" / "python",
        BACKEND_ROOT / ".venv" / "Scripts" / "python.exe",
    ):
        if candidate.is_file():
            return candidate
    return None


def _bootstrap_interpreter() -> None:
    """Re-run under the backend virtualenv when the default interpreter lacks deps."""

    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    try:
        import pydantic  # noqa: F401
    except ModuleNotFoundError:
        interpreter = _local_venv_python()
        if interpreter is not None and sys.prefix == sys.base_prefix:
            print(
                f"[inspect] using {interpreter} (backend dependencies not on this interpreter)",
                file=sys.stderr,
            )
            os.execv(str(interpreter), [str(interpreter), str(SCRIPT_PATH), *sys.argv[1:]])


_bootstrap_interpreter()

from app.domain.rail.errors import RailDataError  # noqa: E402
from app.modules.compiler.rule_compiler import compile_instance  # noqa: E402
from app.modules.instance.schemas import INSTANCE_FILES  # noqa: E402
from app.modules.instance.service import load_instance  # noqa: E402


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _report_files(root: Path) -> None:
    print("Files")
    for name in INSTANCE_FILES:
        path = root / name
        if path.is_file():
            print(f"  ok       {name:<28} {_human_size(path.stat().st_size)}")
        else:
            print(f"  MISSING  {name}")


def _report_parse_failure(exc: RailDataError) -> int:
    print(f"Parse: FAILED ({len(exc.issues)} issue(s))")
    for issue in exc.issues:
        print(f"  {issue}")
    return 1


def _report_entities(instance) -> None:
    rows = (
        ("lines", len(instance.lines)),
        ("stations", len(instance.stations)),
        ("sectors", len(instance.sectors)),
        ("locations", len(instance.locations)),
        ("buffer rules", len(instance.buffer_rules)),
        ("contracts", len(instance.contracts)),
        ("activities", len(instance.activities)),
        ("predecessor edges", len(instance.predecessors)),
    )
    width = max(len(label) for label, _ in rows)
    print("Entities")
    for label, count in rows:
        print(f"  {label:<{width}}  {count}")


def _report_activity_counts(instance) -> None:
    per_contract = Counter(
        activity.contract_number for activity in instance.activities.values()
    )
    if not per_contract:
        return
    counts = list(per_contract.values())
    print(
        "Activity/contract: "
        f"{len(instance.contracts)} contract(s), "
        f"{sum(counts)} activit(ies), "
        f"{min(counts)}-{max(counts)} per contract"
    )


def _report_compile(compiled) -> None:
    possession = compiled.physical_possession
    allowed = sum(1 for value in compiled.co_share_allowed.values() if value)
    total = len(compiled.co_share_allowed)
    rows = (
        ("compiled activities", len(compiled.activities)),
        ("closure conflicts", len(possession.closure_conflicts)),
        ("occupied locations", len(possession.location_occupants)),
        ("access-night domains", len(possession.access_night_domains)),
        ("capacity locations", len(compiled.location_capacities)),
        ("co-share pairs allowed", f"{allowed}/{total}"),
    )
    width = max(len(label) for label, _ in rows)
    print("Compile: OK")
    for label, value in rows:
        print(f"  {label:<{width}}  {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory",
        nargs="?",
        default="data/public-instance",
        help="eight-file PS1 instance directory (default: data/public-instance)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.directory)
    if not root.is_absolute():
        root = (REPO_ROOT / root).resolve()

    print(f"Instance: {root}")
    print()
    _report_files(root)
    print()

    try:
        instance = load_instance(root)
    except RailDataError as exc:
        return _report_parse_failure(exc)

    _report_entities(instance)
    print(f"Horizon: {instance.horizon_start.isoformat()} for {instance.horizon_weeks} week(s)")
    _report_activity_counts(instance)
    print()

    try:
        compiled = compile_instance(instance)
    except Exception as exc:  # noqa: BLE001 - the CLI reports failures without a traceback
        print(f"Compile: FAILED ({type(exc).__name__})")
        print(f"  {exc}")
        return 1

    _report_compile(compiled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
