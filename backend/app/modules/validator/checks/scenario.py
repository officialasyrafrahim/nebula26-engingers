"""Scenario A/B/C hard semantics and RESULTS consistency.

Scenario A forbids ECLO outright (rule ``eclo``). Scenario B makes planned
completion dates hard (rule ``planned_date``). Scenario C bounds all ECLO nights
affecting a line to one continuous two-week window (rule ``eclo_window``).
``RESULTS.csv`` must carry exactly one scenario and one completion row per
contract, with completion dates and overrun matching the published week-end
mapping.
"""

from __future__ import annotations

from collections import defaultdict

from app.domain.rail.keys import parse_location_id
from app.modules.compiler.policy import SCENARIOS
from app.modules.solver.results import week_end
from app.modules.validator.checks.context import ValidationContext


def check(ctx: ValidationContext) -> None:
    _check_eclo(ctx)
    _check_eclo_window(ctx)
    _check_planned_dates(ctx)
    _check_results(ctx)


def _check_eclo(ctx: ValidationContext) -> None:
    if ctx.policy.eclo_allowed:
        return
    for activity_id, rows in sorted(ctx.access_by_activity.items()):
        if activity_id not in ctx.known_activities:
            continue
        for row in rows:
            if row.eclo:
                ctx.add(
                    "eclo",
                    f"activity {activity_id} week {row.week} uses ECLO but Scenario "
                    f"{ctx.scenario} forbids it",
                )


def _affected_lines(ctx: ValidationContext, activity_id: str) -> set[str]:
    lines: set[str] = set()
    for location_id in ctx.activity(activity_id).closed_locations:
        try:
            lines.add(parse_location_id(location_id).line_code)
        except ValueError:
            continue
    return lines


def _check_eclo_window(ctx: ValidationContext) -> None:
    if ctx.policy.eclo_window != "two_week_per_line":
        return
    weeks_by_line: dict[str, set[int]] = defaultdict(set)
    for activity_id, rows in ctx.access_by_activity.items():
        if activity_id not in ctx.known_activities:
            continue
        if not any(row.eclo for row in rows):
            continue
        lines = _affected_lines(ctx, activity_id)
        if not lines:
            ctx.add(
                "eclo_window",
                f"activity {activity_id} uses ECLO but affects no known line",
            )
            continue
        for row in rows:
            if row.eclo:
                for line_code in lines:
                    weeks_by_line[line_code].add(row.week)
    for line_code, weeks in sorted(weeks_by_line.items()):
        if not weeks:
            continue
        span = max(weeks) - min(weeks) + 1
        if span > 2:
            ctx.add(
                "eclo_window",
                f"line {line_code} ECLO weeks {sorted(weeks)} span {span} calendar "
                "weeks but Scenario C allows at most 2",
            )


def _check_planned_dates(ctx: ValidationContext) -> None:
    if not ctx.policy.planned_completion_hard:
        return
    for row in ctx.result_rows:
        contract = ctx.instance.contracts.get(row.contract_number)
        if contract is None:
            continue
        if row.simulated_completion_date > contract.planned_completion_date:
            overrun = (row.simulated_completion_date - contract.planned_completion_date).days
            ctx.add(
                "planned_date",
                f"contract {row.contract_number} completes "
                f"{row.simulated_completion_date} which is {overrun} days past its "
                "planned completion date (Scenario B is hard)",
            )


def _check_results(ctx: ValidationContext) -> None:
    results = ctx.result_rows
    if not results:
        ctx.add("results", "RESULTS.csv is empty")
        return

    unknown = sorted({row.scenario for row in results if row.scenario not in SCENARIOS})
    for scenario in unknown:
        ctx.add(
            "results",
            f"RESULTS.csv declares unknown scenario {scenario!r}; expected one of "
            f"{list(SCENARIOS)}",
        )

    scenarios = sorted({row.scenario for row in results})
    if len(scenarios) != 1:
        ctx.add(
            "results",
            f"RESULTS.csv mixes scenarios {scenarios}; exactly one is required",
        )

    contracts_with_activities = {
        contract_number
        for contract_number, contract in ctx.instance.contracts.items()
        if any(
            activity.contract_number == contract_number
            for activity in ctx.instance.activities.values()
        )
    }
    seen: dict[str, int] = defaultdict(int)
    for row in results:
        seen[row.contract_number] += 1
        if row.contract_number not in ctx.instance.contracts:
            ctx.add("results", f"RESULTS.csv names unknown contract {row.contract_number}")
    for contract_number in sorted(contracts_with_activities - set(seen)):
        ctx.add("results", f"RESULTS.csv is missing contract {contract_number}")
    for contract_number, count in sorted(seen.items()):
        if count > 1:
            ctx.add(
                "results",
                f"RESULTS.csv lists contract {contract_number} {count} times",
            )

    _check_completion_dates(ctx)


def _check_completion_dates(ctx: ValidationContext) -> None:
    horizon_start = ctx.instance.horizon_start
    for row in ctx.result_rows:
        contract = ctx.instance.contracts.get(row.contract_number)
        if contract is None:
            continue
        weeks = [
            access.week
            for activity_id, accesses in ctx.access_by_activity.items()
            if activity_id in ctx.known_activities
            and ctx.activity(activity_id).contract_number == row.contract_number
            for access in accesses
        ]
        if not weeks:
            ctx.add(
                "results",
                f"contract {row.contract_number} has no scheduled access but a "
                "completion row",
            )
            continue
        expected = week_end(horizon_start, max(weeks))
        if expected != row.simulated_completion_date:
            ctx.add(
                "results",
                f"contract {row.contract_number} simulated completion "
                f"{row.simulated_completion_date} does not match week "
                f"{max(weeks)} end {expected}",
            )
            continue
        expected_overrun = max(0, (expected - contract.planned_completion_date).days)
        if expected_overrun != row.overrun_days:
            ctx.add(
                "results",
                f"contract {row.contract_number} overrun {row.overrun_days} does not "
                f"match computed {expected_overrun}",
            )


__all__ = ["check"]
