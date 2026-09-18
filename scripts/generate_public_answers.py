#!/usr/bin/env python3
"""Generate and validate the public Scenario A/B/C submission answer keys.

One command solves Scenarios A, B and C against an instance, writes each as a
separate exact-schema answer key (directory and/or zip), re-reads every file to
prove the schema round-trips, then validates each key with the fallback validator
(or the configured official validator). It exits non-zero on **any** solve,
workload, schema or validation failure, so CI can never silently skip a broken
solver.

Profiles
--------
``smoke``
    Bounded profile for CI. Solves A/B/C with a practical per-scenario time
    limit; a scenario that does not solve within the bound fails the run.
``full``
    Longer profile for the final public deliverables, with a larger per-scenario
    budget.

Usage
-----
    backend/.venv/bin/python scripts/generate_public_answers.py \
        --profile smoke --outdir dist/public-answers

    # official validator (never required, never faked)
    RAIL_VALIDATOR_COMMAND="/path/to/validator" \
        python scripts/generate_public_answers.py --profile full
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.rail.compiled import CompiledInstance  # noqa: E402
from app.domain.rail.errors import RailDataError  # noqa: E402
from app.modules.compiler.rule_compiler import compile_instance  # noqa: E402
from app.modules.export.archive import (  # noqa: E402
    export_scenario_zip,
    scenario_archive_name,
)
from app.modules.export.bundle import (  # noqa: E402
    SubmissionBundle,
    bundle_from_solver_result,
    load_bundle,
    write_bundle,
)
from app.modules.export.schemas import (  # noqa: E402
    SUBMISSION_FILES,
    SubmissionParseError,
)
from app.modules.instance.service import load_instance  # noqa: E402
from app.modules.solver import cp_sat_available, solve  # noqa: E402
from app.modules.validator import (  # noqa: E402
    OfficialValidatorError,
    ValidatorReport,
    validate_compiled,
    validate_with_adapter,
)

SCENARIOS: tuple[str, ...] = ("A", "B", "C")
PROFILES: dict[str, dict[str, float]] = {
    "smoke": {"time_limit": 60.0},
    "full": {"time_limit": 180.0},
}
DEFAULT_PROFILE = "smoke"
MANIFEST_NAME = "generation_manifest.json"

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_ENVIRONMENT = 2


class GenerationError(RuntimeError):
    """Configuration or environment failure that stops generation."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _validate_bundle(
    compiled: CompiledInstance,
    bundle: SubmissionBundle,
    scenario: str,
) -> ValidatorReport:
    return validate_compiled(compiled, bundle, scenario)


def generate_scenario(
    compiled: CompiledInstance,
    scenario: str,
    outdir: Path,
    *,
    time_limit_seconds: float,
    seed: int,
    horizon_extension_weeks: int,
    formats: tuple[str, ...],
    validator_command: str | None = None,
    instance_dir: str | Path | None = None,
) -> dict:
    """Solve, export, re-read and validate one scenario answer key."""

    outcome: dict = {
        "scenario": scenario,
        "solved": False,
        "status": "",
        "feasible": False,
        "workload_complete": False,
        "validation_ready": False,
        "authority": "fallback",
        "objective_score": None,
        "directory": None,
        "archive": None,
        "files": {},
        "errors": [],
    }

    result = solve(
        compiled,
        scenario,  # type: ignore[arg-type]
        time_limit_seconds=time_limit_seconds,
        seed=seed,
        horizon_extension_weeks=horizon_extension_weeks,
    )
    outcome["status"] = result.status
    if not result.feasible:
        reasons = list(result.infeasibility_reasons)[:5]
        outcome["errors"].append(
            f"scenario {scenario} did not solve ({result.status}): {reasons}"
        )
        return outcome
    outcome["solved"] = True

    bundle = bundle_from_solver_result(result)
    if bundle.scenario != scenario:
        outcome["errors"].append(
            f"scenario {scenario}: solver result declared {bundle.scenario!r}"
        )
        return outcome

    # Always write the directory so the exact schema can be re-read; zip is
    # layered on top when requested. Each scenario stays a distinct answer key.
    directory = outdir / f"scenario_{scenario}"
    write_bundle(directory, bundle)
    outcome["directory"] = str(directory)

    # Re-read what was written: proves the exact schema round-trips.
    try:
        reloaded = load_bundle(directory)
    except SubmissionParseError as exc:
        outcome["errors"].append(f"scenario {scenario} schema round-trip failed: {exc}")
        return outcome

    missing = [name for name in SUBMISSION_FILES if not (directory / name).is_file()]
    if missing:
        outcome["errors"].append(f"scenario {scenario} missing files {missing}")
        return outcome
    outcome["files"] = {
        name: _sha256(directory / name) for name in SUBMISSION_FILES
    }

    report = _validate_bundle(compiled, reloaded, scenario)
    outcome["feasible"] = report.feasible
    outcome["workload_complete"] = report.workload_complete
    outcome["validation_ready"] = report.ready_for_submission
    outcome["authority"] = report.authority
    outcome["objective_score"] = report.soft_scores.objective_score

    if not report.workload_complete:
        outcome["errors"].append(
            f"scenario {scenario} workload incomplete: "
            f"{[v.rule for v in report.hard_violations if v.rule == 'workload']}"
        )
    if not report.feasible:
        outcome["errors"].append(
            f"scenario {scenario} validation failed: {report.rules}"
        )

    if instance_dir is not None:
        try:
            adapter_outcome = validate_with_adapter(
                instance_dir, directory, scenario, command=validator_command
            )
        except OfficialValidatorError as exc:
            outcome["validation_ready"] = False
            outcome["errors"].append(
                f"scenario {scenario} official validator failed: {exc}"
            )
            adapter_outcome = None
        if adapter_outcome is not None:
            official = adapter_outcome.report
            outcome["authority"] = official.authority
            outcome["validation_ready"] = official.ready_for_submission
            if official.authority == "official" and not official.ready_for_submission:
                outcome["errors"].append(
                    f"scenario {scenario} official validator rejected: {official.rules}"
                )

    if "zip" in formats or "both" in formats:
        archive_path = outdir / scenario_archive_name(scenario)
        archive_path.write_bytes(export_scenario_zip(bundle))
        outcome["archive"] = str(archive_path)

    return outcome


def generate_answers(
    instance_dir: str | Path,
    outdir: str | Path,
    *,
    scenarios: tuple[str, ...] = SCENARIOS,
    time_limit_seconds: float,
    seed: int = 42,
    horizon_extension_weeks: int = 6,
    formats: tuple[str, ...] = ("dir",),
    validator_command: str | None = None,
) -> dict:
    """Load, compile, generate and validate the requested scenarios."""

    try:
        instance = load_instance(instance_dir)
    except RailDataError as exc:
        raise GenerationError(f"invalid instance {instance_dir}: {exc}") from exc
    compiled = compile_instance(instance)
    return generate_for_compiled(
        compiled,
        outdir,
        scenarios=scenarios,
        time_limit_seconds=time_limit_seconds,
        seed=seed,
        horizon_extension_weeks=horizon_extension_weeks,
        formats=formats,
        validator_command=validator_command,
        instance_dir=instance_dir,
    )


def generate_for_compiled(
    compiled: CompiledInstance,
    outdir: str | Path,
    *,
    scenarios: tuple[str, ...] = SCENARIOS,
    time_limit_seconds: float,
    seed: int = 42,
    horizon_extension_weeks: int = 6,
    formats: tuple[str, ...] = ("dir",),
    validator_command: str | None = None,
    instance_dir: str | Path | None = None,
) -> dict:
    """Generate and validate answer keys from an already compiled instance."""

    outdir_path = Path(outdir)
    outdir_path.mkdir(parents=True, exist_ok=True)

    outcomes = [
        generate_scenario(
            compiled,
            scenario,
            outdir_path,
            time_limit_seconds=time_limit_seconds,
            seed=seed,
            horizon_extension_weeks=horizon_extension_weeks,
            formats=formats,
            validator_command=validator_command,
            instance_dir=instance_dir,
        )
        for scenario in scenarios
    ]

    failures = [
        outcome["scenario"]
        for outcome in outcomes
        if outcome["errors"] or not outcome["validation_ready"]
    ]
    report = {
        "instance": str(instance_dir) if instance_dir is not None else None,
        "outdir": str(outdir_path),
        "scenarios": list(scenarios),
        "time_limit_seconds": time_limit_seconds,
        "seed": seed,
        "horizon_extension_weeks": horizon_extension_weeks,
        "formats": list(formats),
        "ok": not failures,
        "failures": failures,
        "outcomes": outcomes,
    }
    (outdir_path / MANIFEST_NAME).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance",
        default=str(REPO_ROOT / "data" / "public-instance"),
        help="instance directory with the eight published CSVs",
    )
    parser.add_argument(
        "--outdir",
        default=str(REPO_ROOT / "dist" / "public-answers"),
        help="output root; each scenario gets its own answer-key directory",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default=DEFAULT_PROFILE,
        help="bounded smoke profile or longer full generation",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        choices=SCENARIOS,
        default=list(SCENARIOS),
        help="scenarios to generate (default: all three)",
    )
    parser.add_argument(
        "--time-limit",
        type=float,
        default=None,
        help="per-scenario solve budget in seconds (overrides the profile)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--horizon-extension-weeks", type=int, default=6)
    parser.add_argument(
        "--format",
        dest="formats",
        nargs="+",
        choices=("dir", "zip", "both"),
        default=["dir"],
    )
    parser.add_argument(
        "--validator-command",
        default=None,
        help="official validator command; falls back to the bundled validator",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not cp_sat_available():
        print(
            "error: OR-Tools CP-SAT is unavailable; cannot generate answers "
            "(refusing to skip silently)",
            file=sys.stderr,
        )
        return EXIT_ENVIRONMENT

    time_limit = (
        args.time_limit
        if args.time_limit is not None
        else PROFILES[args.profile]["time_limit"]
    )
    formats = tuple(dict.fromkeys(args.formats))

    try:
        report = generate_answers(
            args.instance,
            args.outdir,
            scenarios=tuple(args.scenarios),
            time_limit_seconds=time_limit,
            seed=args.seed,
            horizon_extension_weeks=args.horizon_extension_weeks,
            formats=formats,
            validator_command=args.validator_command,
        )
    except GenerationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ENVIRONMENT

    if not args.quiet:
        for outcome in report["outcomes"]:
            print(
                "scenario {scenario}: solved={solved} status={status} "
                "feasible={feasible} workload={workload_complete} "
                "ready={validation_ready} authority={authority} score={objective_score}".format(
                    **outcome
                )
            )
            for error in outcome["errors"]:
                print(f"  error: {error}")
        print(f"manifest: {Path(args.outdir) / MANIFEST_NAME}")

    return EXIT_OK if report["ok"] else EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
