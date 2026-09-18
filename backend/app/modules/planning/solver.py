"""Constraint-valid maintenance planning with optional CP-SAT optimization.

ERD requirements: PLN-01, PLN-02, PLN-03.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from itertools import combinations

from app.domain.enums import InterventionPriority

Choice = tuple[str, str | None, str | None, str]

_PRIORITY_ORDER = {
    InterventionPriority.CRITICAL.value: 0,
    InterventionPriority.HIGH.value: 1,
    InterventionPriority.MEDIUM.value: 2,
    InterventionPriority.LOW.value: 3,
}
_PRIORITY_DELAY_WEIGHT = {
    InterventionPriority.CRITICAL.value: 8,
    InterventionPriority.HIGH.value: 4,
    InterventionPriority.MEDIUM.value: 2,
    InterventionPriority.LOW.value: 1,
}


@dataclass(frozen=True)
class ObjectiveWeights:
    """Integer weights used by CP-SAT and fallback scoring."""

    makespan: int
    asset_downtime: int
    priority_delay: int
    overtime: int
    travel: int
    workload: int
    bundling: int


_OBJECTIVE_PROFILES = {
    "balanced": ObjectiveWeights(2, 5, 4, 3, 2, 2, 4),
    "speed": ObjectiveWeights(6, 8, 8, 1, 1, 1, 3),
    "cost": ObjectiveWeights(1, 2, 2, 8, 8, 2, 3),
    "workload": ObjectiveWeights(1, 2, 2, 3, 2, 8, 2),
}


@dataclass
class PlanRequest:
    """Canonical inputs to a planning solve."""

    work_packages: list[dict]
    horizon_start: datetime
    horizon_end: datetime
    time_limit_seconds: int
    crews: list[dict] = field(default_factory=list)
    windows: list[dict] = field(default_factory=list)
    depots: list[dict] = field(default_factory=list)
    crew_unavailability: dict[str, list[dict]] = field(default_factory=dict)
    asset_unavailability: dict[str, list[dict]] = field(default_factory=dict)
    depot_parts: dict[str, dict[str, int]] = field(default_factory=dict)
    depot_tools: dict[str, dict[str, int]] = field(default_factory=dict)
    crew_regular_minutes: dict[str, int] = field(default_factory=dict)


@dataclass
class SolverResult:
    """Structured outcome of one planning solve."""

    feasible: bool
    assignments: list[dict] = field(default_factory=list)
    objective_breakdown: dict = field(default_factory=dict)
    infeasibility_reasons: list[str] = field(default_factory=list)
    objective_profile: str = "balanced"


def solve_plan(
    request: PlanRequest,
    objective_profile: str = "balanced",
    *,
    prefer_cp_sat: bool = True,
    forbidden_signatures: tuple[frozenset[Choice], ...] = (),
) -> SolverResult:
    """Solve one feasible option with all supplied mandatory constraints."""
    profile = _profile(objective_profile)
    if prefer_cp_sat:
        try:
            from ortools.sat.python import cp_model
        except ImportError:
            pass
        else:
            return _solve_with_cp_sat(
                request,
                objective_profile,
                profile,
                forbidden_signatures,
                cp_model,
            )
    return _greedy(request, objective_profile, profile, forbidden_signatures)


def solve_alternatives(
    request: PlanRequest,
    alternatives: int = 1,
    objective_profile: str = "balanced",
    *,
    prefer_cp_sat: bool = True,
) -> list[SolverResult]:
    """Generate up to three unique feasible options with explicit trade-offs."""
    target = max(1, min(3, alternatives))
    profile_order = [
        objective_profile,
        *[name for name in ("balanced", "speed", "cost", "workload") if name != objective_profile],
    ]
    results: list[SolverResult] = []
    signatures: list[frozenset[Choice]] = []
    attempts = 0
    max_attempts = max(target * 2, len(profile_order)) if target > 1 else 1
    bounded_request = replace(
        request,
        time_limit_seconds=max(1, int(request.time_limit_seconds) // max_attempts),
    )
    while len(results) < target and attempts < max_attempts:
        profile_name = profile_order[attempts % len(profile_order)]
        try:
            result = solve_plan(
                bounded_request,
                profile_name,
                prefer_cp_sat=prefer_cp_sat,
                forbidden_signatures=tuple(signatures),
            )
        except TimeoutError:
            if results:
                break
            raise
        attempts += 1
        if not result.feasible:
            if not results:
                return [result]
            continue
        signature = assignment_signature(result.assignments)
        if signature in signatures:
            break
        signatures.append(signature)
        results.append(result)
    return results


def assignment_signature(assignments: list[dict]) -> frozenset[Choice]:
    """Return the material crew/depot/window choices for an option."""
    return frozenset(
        (
            str(assignment["work_package_id"]),
            _optional_string(assignment.get("crew_id")),
            _optional_string(assignment.get("depot_id")),
            str(assignment.get("window_id")),
        )
        for assignment in assignments
    )


def _profile(name: str) -> ObjectiveWeights:
    return _OBJECTIVE_PROFILES.get(name, _OBJECTIVE_PROFILES["balanced"])


def _as_datetime(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _minutes(value: datetime, origin: datetime) -> int:
    return int((_as_datetime(value) - _as_datetime(origin)).total_seconds() // 60)


def _priority_rank(priority: str | None) -> int:
    return _PRIORITY_ORDER.get(priority or "", len(_PRIORITY_ORDER))


def _priority_delay_weight(priority: str | None) -> int:
    return _PRIORITY_DELAY_WEIGHT.get(priority or "", 1)


def _order_work_packages(work_packages: list[dict]) -> list[dict]:
    return sorted(
        work_packages,
        key=lambda item: (
            _priority_rank(item.get("priority")),
            -(int(item.get("est_duration_min") or 0)),
            str(item.get("id")),
        ),
    )


def _order_windows(windows: list[dict]) -> list[dict]:
    return sorted(
        windows,
        key=lambda item: (_as_datetime(item["starts_at"]), str(item.get("id") or "")),
    )


def _crew_eligible(work_package: dict, crew: dict) -> bool:
    competency = work_package.get("competency")
    if not competency:
        return True
    return competency in (crew.get("competencies") or [])


def _eligible_crews(request: PlanRequest, work_package: dict) -> list[dict]:
    eligible = [crew for crew in request.crews if _crew_eligible(work_package, crew)]
    if eligible:
        return eligible
    if not request.crews and not work_package.get("competency"):
        return [{"id": None, "depot_id": None, "competencies": []}]
    return []


def _normalize_requirements(items: object) -> dict[str, int]:
    requirements: dict[str, int] = {}
    if not items:
        return requirements
    values = items if isinstance(items, list) else [items]
    for item in values:
        if isinstance(item, str):
            name, quantity = item, 1
        elif isinstance(item, dict):
            name = item.get("id") or item.get("name") or item.get("part") or item.get("tool")
            quantity = int(item.get("quantity", 1))
        else:
            continue
        if name and quantity > 0:
            requirements[str(name)] = requirements.get(str(name), 0) + quantity
    return requirements


def _window_bounds(
    request: PlanRequest, window: dict, duration: int
) -> tuple[datetime, datetime] | None:
    start = max(_as_datetime(window["starts_at"]), _as_datetime(request.horizon_start))
    end = min(_as_datetime(window["ends_at"]), _as_datetime(request.horizon_end))
    if end - start < timedelta(minutes=duration):
        return None
    return start, end


def _resources_available(request: PlanRequest, work_package: dict, depot_id: str | None) -> bool:
    parts = _normalize_requirements(work_package.get("parts"))
    tools = _normalize_requirements(work_package.get("tools"))
    if (parts or tools) and depot_id is None:
        return False
    part_inventory = request.depot_parts.get(depot_id or "", {})
    tool_inventory = request.depot_tools.get(depot_id or "", {})
    return all(part_inventory.get(name, 0) >= quantity for name, quantity in parts.items()) and all(
        tool_inventory.get(name, 0) >= quantity for name, quantity in tools.items()
    )


def _travel_minutes(crew: dict, depot_id: str | None) -> int:
    crew_depot = _optional_string(crew.get("depot_id"))
    return 0 if crew_depot is None or depot_id is None or crew_depot == depot_id else 30


def _solve_with_cp_sat(
    request: PlanRequest,
    profile_name: str,
    weights: ObjectiveWeights,
    forbidden_signatures: tuple[frozenset[Choice], ...],
    cp_model,
) -> SolverResult:
    horizon_start = _as_datetime(request.horizon_start)
    horizon_end = _as_datetime(request.horizon_end)
    horizon_minutes = max(1, _minutes(horizon_end, horizon_start))
    model = cp_model.CpModel()
    candidates: list[dict] = []
    candidates_by_work_package: dict[str, list[dict]] = {}
    crew_intervals: dict[str, list] = {}
    asset_intervals: dict[str, list] = {}
    depot_intervals: dict[str, list] = {}
    tool_intervals: dict[tuple[str, str], list[tuple[object, int]]] = {}
    part_usage: dict[tuple[str, str], list[tuple[object, int]]] = {}

    for work_package in _order_work_packages(request.work_packages):
        work_package_id = str(work_package["id"])
        duration = int(work_package.get("est_duration_min") or 0)
        if duration <= 0:
            return _infeasible(profile_name, f"work package {work_package_id} has no duration")
        asset_id = _optional_string(work_package.get("asset_id")) or work_package_id
        eligible_crews = _eligible_crews(request, work_package)
        for window in _order_windows(request.windows):
            bounds = _window_bounds(request, window, duration)
            depot_id = _optional_string(window.get("depot_id"))
            if bounds is None or not _resources_available(request, work_package, depot_id):
                continue
            lower = _minutes(bounds[0], horizon_start)
            upper = _minutes(bounds[1], horizon_start) - duration
            window_id = str(window.get("id"))
            for crew in eligible_crews:
                crew_id = _optional_string(crew.get("id"))
                owner = crew_id or "unassigned"
                suffix = f"{work_package_id}_{owner}_{window_id}"
                present = model.NewBoolVar(f"present_{suffix}")
                start = model.NewIntVar(lower, upper, f"start_{suffix}")
                end = model.NewIntVar(lower + duration, upper + duration, f"end_{suffix}")
                interval = model.NewOptionalIntervalVar(
                    start, duration, end, present, f"interval_{suffix}"
                )
                candidate = {
                    "work_package": work_package,
                    "work_package_id": work_package_id,
                    "asset_id": asset_id,
                    "crew": crew,
                    "crew_id": crew_id,
                    "depot_id": depot_id,
                    "window_id": window_id,
                    "duration": duration,
                    "present": present,
                    "start": start,
                    "end": end,
                    "interval": interval,
                    "travel_minutes": _travel_minutes(crew, depot_id),
                }
                candidates.append(candidate)
                candidates_by_work_package.setdefault(work_package_id, []).append(candidate)
                crew_intervals.setdefault(owner, []).append(interval)
                asset_intervals.setdefault(asset_id, []).append(interval)
                if depot_id:
                    depot_intervals.setdefault(depot_id, []).append(interval)
                    for name, quantity in _normalize_requirements(
                        work_package.get("parts")
                    ).items():
                        part_usage.setdefault((depot_id, name), []).append((present, quantity))
                    for name, quantity in _normalize_requirements(
                        work_package.get("tools")
                    ).items():
                        tool_intervals.setdefault((depot_id, name), []).append(
                            (interval, quantity)
                        )

        work_package_candidates = candidates_by_work_package.get(work_package_id, [])
        if not work_package_candidates:
            return _infeasible(
                profile_name,
                "no feasible crew, resource and maintenance-window combination "
                f"for {work_package_id}",
            )
        model.AddExactlyOne([item["present"] for item in work_package_candidates])

    _add_fixed_unavailability(
        model,
        crew_intervals,
        request.crew_unavailability,
        horizon_start,
        horizon_end,
        "crew",
    )
    _add_fixed_unavailability(
        model,
        asset_intervals,
        request.asset_unavailability,
        horizon_start,
        horizon_end,
        "asset",
    )
    for intervals in crew_intervals.values():
        model.AddNoOverlap(intervals)
    for intervals in asset_intervals.values():
        model.AddNoOverlap(intervals)

    depots = {str(depot["id"]): depot for depot in request.depots}
    default_capacity = max(1, len(request.work_packages))
    for depot_id, intervals in depot_intervals.items():
        capacity = int(depots.get(depot_id, {}).get("capacity") or default_capacity)
        model.AddCumulative(intervals, [1] * len(intervals), max(0, capacity))
    for (depot_id, name), usage in part_usage.items():
        capacity = int(request.depot_parts.get(depot_id, {}).get(name, 0))
        model.Add(sum(present * quantity for present, quantity in usage) <= capacity)
    for (depot_id, name), usage in tool_intervals.items():
        capacity = int(request.depot_tools.get(depot_id, {}).get(name, 0))
        model.AddCumulative(
            [interval for interval, _ in usage],
            [quantity for _, quantity in usage],
            capacity,
        )

    for signature in forbidden_signatures:
        selected = [
            candidate["present"]
            for candidate in candidates
            if _candidate_choice(candidate) in signature
        ]
        if len(selected) == len(request.work_packages):
            model.Add(sum(selected) <= len(selected) - 1)

    work_package_starts = {}
    work_package_ends = {}
    for work_package_id, work_package_candidates in candidates_by_work_package.items():
        start = model.NewIntVar(0, horizon_minutes, f"selected_start_{work_package_id}")
        end = model.NewIntVar(0, horizon_minutes, f"selected_end_{work_package_id}")
        for candidate in work_package_candidates:
            model.Add(start == candidate["start"]).OnlyEnforceIf(candidate["present"])
            model.Add(end == candidate["end"]).OnlyEnforceIf(candidate["present"])
        work_package_starts[work_package_id] = start
        work_package_ends[work_package_id] = end

    first_start = model.NewIntVar(0, horizon_minutes, "first_start")
    last_end = model.NewIntVar(0, horizon_minutes, "last_end")
    model.AddMinEquality(first_start, list(work_package_starts.values()))
    model.AddMaxEquality(last_end, list(work_package_ends.values()))
    makespan = model.NewIntVar(0, horizon_minutes, "makespan")
    model.Add(makespan == last_end - first_start)

    asset_spans = []
    for asset_id in {str(item.get("asset_id") or item["id"]) for item in request.work_packages}:
        ids = [
            str(item["id"])
            for item in request.work_packages
            if str(item.get("asset_id") or item["id"]) == asset_id
        ]
        asset_start = model.NewIntVar(0, horizon_minutes, f"asset_start_{asset_id}")
        asset_end = model.NewIntVar(0, horizon_minutes, f"asset_end_{asset_id}")
        model.AddMinEquality(asset_start, [work_package_starts[item] for item in ids])
        model.AddMaxEquality(asset_end, [work_package_ends[item] for item in ids])
        span = model.NewIntVar(0, horizon_minutes, f"asset_span_{asset_id}")
        model.Add(span == asset_end - asset_start)
        asset_spans.append(span)

    priority_delay = sum(
        _priority_delay_weight(item.get("priority")) * work_package_starts[str(item["id"])]
        for item in request.work_packages
    )
    travel_cost = sum(
        candidate["travel_minutes"] * candidate["present"] for candidate in candidates
    )
    crew_loads = []
    overtime = []
    for crew_key in crew_intervals:
        load = model.NewIntVar(0, sum(item["duration"] for item in candidates), f"load_{crew_key}")
        model.Add(
            load
            == sum(
                candidate["duration"] * candidate["present"]
                for candidate in candidates
                if (candidate["crew_id"] or "unassigned") == crew_key
            )
        )
        crew_loads.append(load)
        regular = int(request.crew_regular_minutes.get(crew_key, horizon_minutes))
        extra = model.NewIntVar(0, sum(item["duration"] for item in candidates), f"ot_{crew_key}")
        model.Add(extra >= load - regular)
        overtime.append(extra)
    if len(crew_loads) > 1:
        max_load = model.NewIntVar(0, horizon_minutes, "max_load")
        min_load = model.NewIntVar(0, horizon_minutes, "min_load")
        model.AddMaxEquality(max_load, crew_loads)
        model.AddMinEquality(min_load, crew_loads)
        workload_spread = max_load - min_load
    else:
        workload_spread = 0

    bundles = _add_bundle_variables(model, request, candidates)
    model.Minimize(
        weights.makespan * makespan
        + weights.asset_downtime * sum(asset_spans)
        + weights.priority_delay * priority_delay
        + weights.overtime * sum(overtime)
        + weights.travel * travel_cost
        + weights.workload * workload_spread
        - weights.bundling * 30 * sum(bundles)
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1, int(request.time_limit_seconds))
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 42
    status = solver.Solve(model)
    if status == cp_model.UNKNOWN:
        raise TimeoutError("solver time limit reached before a feasible plan was found")
    if status == cp_model.INFEASIBLE:
        return _infeasible(profile_name, "mandatory planning constraints are infeasible")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("CP-SAT returned an invalid model status")

    assignments = []
    for candidate in candidates:
        if not solver.Value(candidate["present"]):
            continue
        start = horizon_start + timedelta(minutes=solver.Value(candidate["start"]))
        assignments.append(_assignment(candidate, start, profile_name))
    assignments.sort(key=lambda item: (item["window_start"], item["work_package_id"]))
    return SolverResult(
        feasible=True,
        assignments=assignments,
        objective_breakdown=_objective_breakdown(request, assignments, profile_name, weights),
        objective_profile=profile_name,
    )


def _add_fixed_unavailability(
    model,
    intervals_by_owner: dict[str, list],
    unavailability: dict[str, list[dict]],
    horizon_start: datetime,
    horizon_end: datetime,
    prefix: str,
) -> None:
    for owner, ranges in unavailability.items():
        if owner not in intervals_by_owner:
            continue
        for index, blocked in enumerate(ranges):
            start = max(_as_datetime(blocked["starts_at"]), horizon_start)
            end = min(_as_datetime(blocked["ends_at"]), horizon_end)
            duration = _minutes(end, start)
            if duration <= 0:
                continue
            offset = _minutes(start, horizon_start)
            intervals_by_owner[owner].append(
                model.NewIntervalVar(
                    offset,
                    duration,
                    offset + duration,
                    f"{prefix}_blocked_{owner}_{index}",
                )
            )


def _add_bundle_variables(model, request: PlanRequest, candidates: list[dict]) -> list:
    assigned: dict[tuple[str, tuple[str | None, str | None, str]], object] = {}
    for work_package in request.work_packages:
        work_package_id = str(work_package["id"])
        keys = {
            (candidate["crew_id"], candidate["depot_id"], candidate["window_id"])
            for candidate in candidates
            if candidate["work_package_id"] == work_package_id
        }
        for key in keys:
            variables = [
                candidate["present"]
                for candidate in candidates
                if candidate["work_package_id"] == work_package_id
                and (candidate["crew_id"], candidate["depot_id"], candidate["window_id"])
                == key
            ]
            choice = model.NewBoolVar(f"bundle_choice_{work_package_id}_{key}")
            model.Add(choice == sum(variables))
            assigned[(work_package_id, key)] = choice

    bundles = []
    for left, right in combinations(request.work_packages, 2):
        if left.get("asset_id") != right.get("asset_id"):
            continue
        left_id, right_id = str(left["id"]), str(right["id"])
        left_keys = {key for work_package_id, key in assigned if work_package_id == left_id}
        right_keys = {key for work_package_id, key in assigned if work_package_id == right_id}
        for key in left_keys.intersection(right_keys):
            bundled = model.NewBoolVar(f"bundled_{left_id}_{right_id}_{key}")
            model.Add(bundled <= assigned[(left_id, key)])
            model.Add(bundled <= assigned[(right_id, key)])
            model.Add(
                bundled
                >= assigned[(left_id, key)] + assigned[(right_id, key)] - 1
            )
            bundles.append(bundled)
    return bundles


def _candidate_choice(candidate: dict) -> Choice:
    return (
        candidate["work_package_id"],
        candidate["crew_id"],
        candidate["depot_id"],
        candidate["window_id"],
    )


def _assignment(candidate: dict, start: datetime, profile_name: str) -> dict:
    return {
        "work_package_id": candidate["work_package_id"],
        "asset_id": candidate["asset_id"],
        "priority": candidate["work_package"].get("priority"),
        "crew_id": candidate["crew_id"],
        "depot_id": candidate["depot_id"],
        "window_id": candidate["window_id"],
        "window_start": start,
        "window_end": start + timedelta(minutes=candidate["duration"]),
        "duration_min": candidate["duration"],
        "travel_minutes": candidate["travel_minutes"],
        "objective_profile": profile_name,
    }


def _greedy(
    request: PlanRequest,
    profile_name: str,
    weights: ObjectiveWeights,
    forbidden_signatures: tuple[frozenset[Choice], ...],
) -> SolverResult:
    crew_busy = _initial_busy(request.crew_unavailability)
    asset_busy = _initial_busy(request.asset_unavailability)
    depot_busy: dict[str, list[tuple[datetime, datetime, int]]] = {}
    tool_busy: dict[tuple[str, str], list[tuple[datetime, datetime, int]]] = {}
    crew_load: dict[str, int] = {}
    parts_remaining = {
        depot: dict(inventory) for depot, inventory in request.depot_parts.items()
    }
    depots = {str(depot["id"]): depot for depot in request.depots}
    prior_choices = set().union(*forbidden_signatures) if forbidden_signatures else set()
    assignments: list[dict] = []

    for work_package in _order_work_packages(request.work_packages):
        work_package_id = str(work_package["id"])
        duration = int(work_package.get("est_duration_min") or 0)
        if duration <= 0:
            return _infeasible(profile_name, f"work package {work_package_id} has no duration")
        asset_id = _optional_string(work_package.get("asset_id")) or work_package_id
        parts = _normalize_requirements(work_package.get("parts"))
        tools = _normalize_requirements(work_package.get("tools"))
        options = []
        for window in _order_windows(request.windows):
            bounds = _window_bounds(request, window, duration)
            depot_id = _optional_string(window.get("depot_id"))
            if bounds is None or not _resources_available(request, work_package, depot_id):
                continue
            if any(
                parts_remaining.get(depot_id or "", {}).get(name, 0) < quantity
                for name, quantity in parts.items()
            ):
                continue
            for crew in _eligible_crews(request, work_package):
                crew_id = _optional_string(crew.get("id"))
                owner = crew_id or "unassigned"
                start = _greedy_slot(
                    bounds[0],
                    bounds[1],
                    duration,
                    crew_busy.get(owner, []),
                    asset_busy.get(asset_id, []),
                    depot_busy.get(depot_id or "", []),
                    int(
                        depots.get(depot_id or "", {}).get("capacity")
                        or max(1, len(request.work_packages))
                    ),
                    tools,
                    request.depot_tools.get(depot_id or "", {}),
                    tool_busy,
                    depot_id,
                )
                if start is None:
                    continue
                choice: Choice = (work_package_id, crew_id, depot_id, str(window.get("id")))
                score = _greedy_score(
                    request,
                    work_package,
                    crew,
                    depot_id,
                    start,
                    duration,
                    crew_load.get(owner, 0),
                    assignments,
                    weights,
                )
                if choice in prior_choices:
                    score += 1_000_000
                options.append((score, start, str(crew_id), str(window.get("id")), crew, window))

        if not options:
            return _infeasible(
                profile_name,
                "no feasible crew, resource and maintenance-window combination "
                f"for {work_package_id}",
            )
        _, start, _, _, crew, window = min(options)
        crew_id = _optional_string(crew.get("id"))
        owner = crew_id or "unassigned"
        depot_id = _optional_string(window.get("depot_id"))
        end = start + timedelta(minutes=duration)
        crew_busy.setdefault(owner, []).append((start, end, 1))
        asset_busy.setdefault(asset_id, []).append((start, end, 1))
        if depot_id:
            depot_busy.setdefault(depot_id, []).append((start, end, 1))
            for name, quantity in parts.items():
                parts_remaining[depot_id][name] -= quantity
            for name, quantity in tools.items():
                tool_busy.setdefault((depot_id, name), []).append((start, end, quantity))
        crew_load[owner] = crew_load.get(owner, 0) + duration
        candidate = {
            "work_package": work_package,
            "work_package_id": work_package_id,
            "asset_id": asset_id,
            "crew_id": crew_id,
            "depot_id": depot_id,
            "window_id": str(window.get("id")),
            "duration": duration,
            "travel_minutes": _travel_minutes(crew, depot_id),
        }
        assignments.append(_assignment(candidate, start, profile_name))

    assignments.sort(key=lambda item: (item["window_start"], item["work_package_id"]))
    signature = assignment_signature(assignments)
    if signature in forbidden_signatures:
        return _infeasible(profile_name, "no materially different feasible alternative exists")
    return SolverResult(
        feasible=True,
        assignments=assignments,
        objective_breakdown=_objective_breakdown(request, assignments, profile_name, weights),
        objective_profile=profile_name,
    )


def _initial_busy(source: dict[str, list[dict]]) -> dict[str, list[tuple[datetime, datetime, int]]]:
    return {
        owner: [
            (_as_datetime(item["starts_at"]), _as_datetime(item["ends_at"]), 1)
            for item in ranges
        ]
        for owner, ranges in source.items()
    }


def _greedy_slot(
    window_start: datetime,
    window_end: datetime,
    duration: int,
    crew_busy: list[tuple[datetime, datetime, int]],
    asset_busy: list[tuple[datetime, datetime, int]],
    depot_busy: list[tuple[datetime, datetime, int]],
    depot_capacity: int,
    tools: dict[str, int],
    tool_inventory: dict[str, int],
    tool_busy: dict[tuple[str, str], list[tuple[datetime, datetime, int]]],
    depot_id: str | None,
) -> datetime | None:
    candidate = window_start
    while candidate + timedelta(minutes=duration) <= window_end:
        end = candidate + timedelta(minutes=duration)
        blockers = [
            value
            for value in (
                _capacity_conflict_end(candidate, end, crew_busy, 1, 1),
                _capacity_conflict_end(candidate, end, asset_busy, 1, 1),
                _capacity_conflict_end(candidate, end, depot_busy, depot_capacity, 1),
            )
            if value is not None
        ]
        for name, quantity in tools.items():
            blockers.extend(
                value
                for value in [
                    _capacity_conflict_end(
                        candidate,
                        end,
                        tool_busy.get((depot_id or "", name), []),
                        int(tool_inventory.get(name, 0)),
                        quantity,
                    )
                ]
                if value is not None
            )
        if not blockers:
            return candidate
        candidate = min(blockers)
    return None


def _capacity_conflict_end(
    start: datetime,
    end: datetime,
    intervals: list[tuple[datetime, datetime, int]],
    capacity: int,
    demand: int,
) -> datetime | None:
    if demand > capacity:
        return end
    overlapping = [item for item in intervals if item[0] < end and item[1] > start]
    points = sorted(
        {
            start,
            end,
            *[item[0] for item in overlapping],
            *[item[1] for item in overlapping],
        }
    )
    for left, right in zip(points, points[1:], strict=False):
        segment_start = max(left, start)
        segment_end = min(right, end)
        if segment_start >= segment_end:
            continue
        active = [item for item in overlapping if item[0] < segment_end and item[1] > segment_start]
        if demand + sum(item[2] for item in active) > capacity:
            return min(item[1] for item in active)
    return None


def _greedy_score(
    request: PlanRequest,
    work_package: dict,
    crew: dict,
    depot_id: str | None,
    start: datetime,
    duration: int,
    current_load: int,
    assignments: list[dict],
    weights: ObjectiveWeights,
) -> int:
    delay = max(0, _minutes(start, _as_datetime(request.horizon_start)))
    travel = _travel_minutes(crew, depot_id)
    end_offset = delay + duration
    bundled = any(
        item.get("asset_id") == _optional_string(work_package.get("asset_id"))
        and item.get("depot_id") == depot_id
        and abs(_minutes(start, item["window_end"])) <= 60
        for item in assignments
    )
    return (
        weights.makespan * end_offset
        + weights.priority_delay * _priority_delay_weight(work_package.get("priority")) * delay
        + weights.travel * travel
        + weights.workload * (current_load + duration)
        - weights.bundling * 30 * int(bundled)
    )


def _objective_breakdown(
    request: PlanRequest,
    assignments: list[dict],
    profile_name: str,
    weights: ObjectiveWeights,
) -> dict:
    if not assignments:
        return {
            "profile": profile_name,
            "makespan_hours": 0.0,
            "asset_downtime_min": 0,
            "priority_delay_min": 0,
            "overtime_min": 0,
            "travel_min": 0,
            "workload_spread_min": 0,
            "bundled_pairs": 0,
            "total_work_min": 0,
            "objective_score": 0,
        }
    first = min(item["window_start"] for item in assignments)
    last = max(item["window_end"] for item in assignments)
    by_asset: dict[str, list[dict]] = {}
    by_crew: dict[str, int] = {}
    for assignment in assignments:
        by_asset.setdefault(str(assignment.get("asset_id")), []).append(assignment)
        crew = str(assignment.get("crew_id") or "unassigned")
        by_crew[crew] = by_crew.get(crew, 0) + int(assignment["duration_min"])
    asset_downtime = sum(
        _minutes(
            max(item["window_end"] for item in values),
            min(item["window_start"] for item in values),
        )
        for values in by_asset.values()
    )
    priority_by_id = {
        str(item["id"]): item.get("priority") for item in request.work_packages
    }
    priority_delay = sum(
        max(0, _minutes(item["window_start"], _as_datetime(request.horizon_start)))
        * _priority_delay_weight(priority_by_id.get(str(item["work_package_id"])))
        for item in assignments
    )
    horizon_minutes = max(
        0,
        _minutes(
            _as_datetime(request.horizon_end),
            _as_datetime(request.horizon_start),
        ),
    )
    overtime = sum(
        max(0, load - int(request.crew_regular_minutes.get(crew, horizon_minutes)))
        for crew, load in by_crew.items()
    )
    loads = list(by_crew.values())
    workload_spread = max(loads) - min(loads) if len(loads) > 1 else 0
    bundled_pairs = _count_bundled_pairs(assignments)
    makespan = _minutes(last, first)
    travel = sum(int(item.get("travel_minutes") or 0) for item in assignments)
    score = (
        weights.makespan * makespan
        + weights.asset_downtime * asset_downtime
        + weights.priority_delay * priority_delay
        + weights.overtime * overtime
        + weights.travel * travel
        + weights.workload * workload_spread
        - weights.bundling * 30 * bundled_pairs
    )
    return {
        "profile": profile_name,
        "makespan_hours": round(makespan / 60.0, 3),
        "asset_downtime_min": asset_downtime,
        "priority_delay_min": priority_delay,
        "overtime_min": overtime,
        "travel_min": travel,
        "workload_spread_min": workload_spread,
        "bundled_pairs": bundled_pairs,
        "total_work_min": sum(int(item["duration_min"]) for item in assignments),
        "objective_score": score,
    }


def _count_bundled_pairs(assignments: list[dict]) -> int:
    count = 0
    for left, right in combinations(assignments, 2):
        if left.get("asset_id") != right.get("asset_id"):
            continue
        if left.get("depot_id") != right.get("depot_id"):
            continue
        gap = min(
            abs(_minutes(left["window_start"], right["window_end"])),
            abs(_minutes(right["window_start"], left["window_end"])),
        )
        if gap <= 60:
            count += 1
    return count


def _infeasible(profile_name: str, reason: str) -> SolverResult:
    return SolverResult(
        feasible=False,
        infeasibility_reasons=[reason],
        objective_profile=profile_name,
    )
