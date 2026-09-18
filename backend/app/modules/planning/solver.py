"""Solver contract and implementation entry point.

ERD requirements: PLN-01, PLN-02, PLN-03.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.domain.enums import InterventionPriority

_PRIORITY_ORDER = {
    InterventionPriority.CRITICAL.value: 0,
    InterventionPriority.HIGH.value: 1,
    InterventionPriority.MEDIUM.value: 2,
    InterventionPriority.LOW.value: 3,
}


@dataclass
class PlanRequest:
    """Inputs to a planning solve."""

    work_packages: list[dict]
    horizon_start: datetime
    horizon_end: datetime
    time_limit_seconds: int
    crews: list[dict] = field(default_factory=list)
    windows: list[dict] = field(default_factory=list)
    depots: list[dict] = field(default_factory=list)


@dataclass
class SolverResult:
    """Structured outcome of a planning solve."""

    feasible: bool
    assignments: list[dict] = field(default_factory=list)
    objective_breakdown: dict = field(default_factory=dict)
    infeasibility_reasons: list[str] = field(default_factory=list)


def solve_plan(request: PlanRequest) -> SolverResult:
    """Solve a maintenance plan, preferring CP-SAT and falling back to greedy."""
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return _greedy(request)
    try:
        result = _solve_with_cp_sat(request, cp_model)
    except Exception:
        result = None
    if result is None:
        return _greedy(request)
    return result


def _as_datetime(value: datetime | str) -> datetime:
    """Coerce a window boundary to a datetime."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _priority_rank(priority: str | None) -> int:
    """Rank a priority for deterministic ordering."""
    return _PRIORITY_ORDER.get(priority or "", len(_PRIORITY_ORDER))


def _crew_eligible(work_package: dict, crew: dict) -> bool:
    """Return whether a crew satisfies a required competency."""
    competency = work_package.get("competency")
    competencies = crew.get("competencies") or []
    if not competency or not competencies:
        return True
    return competency in competencies


def _earliest_slot(
    window_start: datetime,
    window_end: datetime,
    duration_min: int,
    busy: list[tuple[datetime, datetime]],
) -> datetime | None:
    """Find the earliest start inside a window that avoids busy intervals."""
    duration = timedelta(minutes=duration_min)
    candidate = window_start
    for busy_start, busy_end in sorted(busy):
        if candidate + duration <= busy_start:
            return candidate
        if busy_end > candidate:
            candidate = busy_end
    if candidate + duration <= window_end:
        return candidate
    return None


def _order_windows(windows: list[dict]) -> list[dict]:
    """Sort windows by start time then identifier."""
    return sorted(windows, key=lambda w: (_as_datetime(w["starts_at"]), str(w.get("id") or "")))


def _order_work_packages(work_packages: list[dict]) -> list[dict]:
    """Sort work packages by priority then estimated duration."""
    return sorted(
        work_packages,
        key=lambda wp: (_priority_rank(wp.get("priority")), wp.get("est_duration_min") or 0),
    )


# TODO(PLN-03): real bundling + alternative plans.
def _count_bundled_pairs(assignments: list[dict]) -> int:
    """Count same-crew assignments on overlapping or adjacent windows."""
    pairs = 0
    for i, left in enumerate(assignments):
        for right in assignments[i + 1 :]:
            if left.get("crew_id") is None or left.get("crew_id") != right.get("crew_id"):
                continue
            overlaps = (
                left["window_start"] <= right["window_end"]
                and right["window_start"] <= left["window_end"]
            )
            if overlaps:
                pairs += 1
    return pairs


def _objective_breakdown(work_packages: list[dict], assignments: list[dict]) -> dict:
    """Compute the objective breakdown shared by both solver paths."""
    total_work_min = sum(int(a.get("duration_min") or 0) for a in assignments)
    if not assignments:
        makespan_hours = 0.0
    else:
        starts = [a["window_start"] for a in assignments]
        ends = [a["window_end"] for a in assignments]
        makespan_hours = round((max(ends) - min(starts)).total_seconds() / 3600.0, 3)
    return {
        "makespan_hours": makespan_hours,
        "total_work_min": total_work_min,
        "bundled_pairs": _count_bundled_pairs(assignments),
    }


def _greedy(request: PlanRequest) -> SolverResult:
    """Place work packages greedily into the earliest fitting window and crew."""
    ordered = _order_work_packages(request.work_packages)
    windows = _order_windows(request.windows)
    crews = list(request.crews)
    busy: dict[str | None, list[tuple[datetime, datetime]]] = {}
    assignments: list[dict] = []
    reasons: list[str] = []

    for work_package in ordered:
        duration_min = int(work_package.get("est_duration_min") or 0)
        placed = False
        for window in windows:
            window_start = _as_datetime(window["starts_at"])
            window_end = _as_datetime(window["ends_at"])
            span_min = (window_end - window_start).total_seconds() / 60.0
            if duration_min > span_min:
                continue
            depot_id = window.get("depot_id")
            eligible = [crew for crew in crews if _crew_eligible(work_package, crew)]
            eligible.sort(
                key=lambda crew: (
                    0 if crew.get("depot_id") == depot_id else 1,
                    str(crew.get("id") or ""),
                )
            )
            chosen: dict | None = None
            start: datetime | None = None
            for crew in eligible:
                candidate = _earliest_slot(
                    window_start, window_end, duration_min, busy.get(crew.get("id"), [])
                )
                if candidate is not None:
                    chosen = crew
                    start = candidate
                    break
            if chosen is None and not crews:
                start = _earliest_slot(window_start, window_end, duration_min, busy.get(None, []))
            if start is None:
                continue
            end = start + timedelta(minutes=duration_min)
            key = chosen.get("id") if chosen is not None else None
            busy.setdefault(key, []).append((start, end))
            busy[key].sort()
            assignments.append(
                {
                    "work_package_id": str(work_package.get("id")),
                    "priority": work_package.get("priority"),
                    "crew_id": str(chosen.get("id")) if chosen is not None else None,
                    "depot_id": str(depot_id) if depot_id is not None else None,
                    "window_start": start,
                    "window_end": end,
                    "duration_min": duration_min,
                }
            )
            placed = True
            break
        if not placed:
            reasons.append(f"no window fits work package {work_package.get('id')}")

    if reasons:
        return SolverResult(feasible=False, infeasibility_reasons=reasons)
    if not request.work_packages:
        return SolverResult(
            feasible=True,
            assignments=[],
            objective_breakdown=_objective_breakdown(request.work_packages, []),
        )
    return SolverResult(
        feasible=True,
        assignments=assignments,
        objective_breakdown=_objective_breakdown(request.work_packages, assignments),
    )


def _solve_with_cp_sat(request: PlanRequest, cp_model) -> SolverResult | None:
    """Build and solve an equivalent CP-SAT model, or return None."""
    windows = _order_windows(request.windows)
    if not windows:
        return None
    work_packages = _order_work_packages(request.work_packages)
    horizon_start = request.horizon_start
    model = cp_model.CpModel()
    handles: list[tuple[dict, dict, dict | None, object, object]] = []
    by_crew: dict[str | None, list] = {}

    for work_package in work_packages:
        duration_min = int(work_package.get("est_duration_min") or 0)
        presences = []
        candidates = list(request.crews) if request.crews else [None]
        for crew in candidates:
            if crew is not None and not _crew_eligible(work_package, crew):
                continue
            for window in windows:
                window_start = _as_datetime(window["starts_at"])
                window_end = _as_datetime(window["ends_at"])
                span_min = int((window_end - window_start).total_seconds() / 60.0)
                if duration_min > span_min:
                    continue
                base = int((window_start - horizon_start).total_seconds())
                owner = crew["id"] if crew else "pool"
                present = model.NewBoolVar(
                    f"present_{work_package['id']}_{owner}_{window['id']}"
                )
                start = model.NewIntVar(base, base + span_min - duration_min, f"start_{present}")
                interval = model.NewOptionalIntervalVar(
                    start, duration_min, start + duration_min, present, f"iv_{present}"
                )
                presences.append(present)
                handles.append((work_package, window, crew, present, start))
                by_crew.setdefault(crew.get("id") if crew else None, []).append(interval)
        if not presences:
            return None
        model.AddExactlyOne(presences)

    for intervals in by_crew.values():
        if intervals:
            model.AddNoOverlap(intervals)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1, int(request.time_limit_seconds))
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    assignments: list[dict] = []
    for work_package, window, crew, present, start in handles:
        if not solver.Value(present):
            continue
        duration_min = int(work_package.get("est_duration_min") or 0)
        window_start = horizon_start + timedelta(seconds=solver.Value(start))
        assignments.append(
            {
                "work_package_id": str(work_package.get("id")),
                "priority": work_package.get("priority"),
                "crew_id": str(crew.get("id")) if crew else None,
                "depot_id": str(window.get("depot_id")) if window.get("depot_id") else None,
                "window_start": window_start,
                "window_end": window_start + timedelta(minutes=duration_min),
                "duration_min": duration_min,
            }
        )
    return SolverResult(
        feasible=True,
        assignments=assignments,
        objective_breakdown=_objective_breakdown(request.work_packages, assignments),
    )
