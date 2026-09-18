"""Shared validation context and derived indexes.

The fallback validator re-derives every fact from the canonical
:class:`PlanningInstance` and the parsed :class:`SubmissionBundle`. It never
reads ``SolverResult`` or any CP-SAT object, so a plan cannot pass merely because
it round-tripped through the solver.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.rail.compiled import CompiledInstance
from app.modules.compiler.policy import ScenarioPolicy
from app.modules.export.schemas import AccessRow, ResultRow
from app.modules.validator.report import Authority, HardViolation


@dataclass
class ValidationContext:
    """Mutable accumulator for one validation run."""

    compiled: CompiledInstance
    policy: ScenarioPolicy
    scenario: str
    authority: Authority = "fallback"
    violations: list[HardViolation] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    # Derived indexes, filled in by :meth:`index`.
    result_rows: tuple[ResultRow, ...] = ()
    access_by_activity: dict[str, list[AccessRow]] = field(default_factory=dict)
    access_row_at: dict[tuple[str, int], AccessRow] = field(default_factory=dict)
    occupancy_locations: dict[tuple[str, int], set[str]] = field(default_factory=dict)
    occupancy_groups: dict[tuple[str, int], set[str]] = field(default_factory=dict)
    group_activities: dict[tuple[str, int, str], set[str]] = field(default_factory=dict)
    groups_at_location_week: dict[tuple[str, int], set[str]] = field(default_factory=dict)
    capacity_excess: dict[tuple[str, int], int] = field(default_factory=dict)
    capacity_hotspots: list[dict[str, object]] = field(default_factory=list)
    excess_access_nights_total: int = 0

    @property
    def instance(self):
        return self.compiled.instance

    @property
    def known_activities(self) -> frozenset[str]:
        return frozenset(self.compiled.activities)

    def activity(self, activity_id: str):
        return self.compiled.activities[activity_id]

    def add(self, rule: str, detail: str) -> None:
        """Record one hard violation."""

        self.violations.append(HardViolation(rule=rule, severity="hard", detail=detail))

    def has_rule(self, rule: str) -> bool:
        return any(violation.rule == rule for violation in self.violations)

    def index(self, access: tuple[AccessRow, ...], occupancy: tuple = ()) -> None:
        """Populate every derived index from the parsed submission rows."""

        for row in access:
            self.access_by_activity.setdefault(row.activity_id, []).append(row)
        for rows in self.access_by_activity.values():
            rows.sort(key=lambda row: (row.week, row.access_night))

        for row in access:
            key = (row.activity_id, row.week)
            self.access_row_at.setdefault(key, row)

        for row in occupancy:
            key = (row.activity_id, row.week)
            self.occupancy_locations.setdefault(key, set()).add(row.location_id)
            self.occupancy_groups.setdefault(key, set()).add(row.co_share_group)
            self.group_activities.setdefault(
                (row.location_id, row.week, row.co_share_group), set()
            ).add(row.activity_id)
            self.groups_at_location_week.setdefault(
                (row.location_id, row.week), set()
            ).add(row.co_share_group)


__all__ = ["ValidationContext"]
