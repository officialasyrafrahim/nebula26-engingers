"""Rail access optimisation solver (DEV-2).

Public entry point is :func:`solve`; everything else is an implementation
detail. The solver consumes the scenario-independent
:class:`~app.domain.rail.compiled.CompiledInstance` and returns a
:class:`~app.modules.solver.results.SolverResult`.
"""

from app.modules.solver.engine import (
    RailPlanRequest,
    Scenario,
    resolve_total_weeks,
    solve,
    solve_request,
)
from app.modules.solver.model import (
    DEFAULT_HORIZON_EXTENSION_WEEKS,
    DEFAULT_SEED,
    DEFAULT_TIME_LIMIT_SECONDS,
    OrToolsUnavailableError,
    cp_sat_available,
    load_cp_model,
)
from app.modules.solver.results import (
    AccessPlacement,
    ContractResult,
    OccupancyPlacement,
    SolverResult,
    week_end,
    week_start,
)

__all__ = [
    "AccessPlacement",
    "ContractResult",
    "DEFAULT_HORIZON_EXTENSION_WEEKS",
    "DEFAULT_SEED",
    "DEFAULT_TIME_LIMIT_SECONDS",
    "OccupancyPlacement",
    "OrToolsUnavailableError",
    "RailPlanRequest",
    "Scenario",
    "SolverResult",
    "cp_sat_available",
    "load_cp_model",
    "resolve_total_weeks",
    "solve",
    "solve_request",
    "week_end",
    "week_start",
]
