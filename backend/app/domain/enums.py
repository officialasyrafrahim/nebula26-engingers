"""Canonical domain enumerations for Rail Access Optimisation."""

from enum import Enum


class Scenario(str, Enum):
    """The three published answer keys."""

    A = "A"
    B = "B"
    C = "C"


class JobState(str, Enum):
    """Lifecycle of an asynchronous scenario solve job."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    INFEASIBLE = "INFEASIBLE"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


# A scenario solve job is a "run" of a scenario; the two names are aliases.
RunState = JobState


class UserRole(str, Enum):
    """Actor roles recognised by the development auth stub."""

    PLANNER = "PLANNER"
    ADMIN = "ADMIN"
    VIEWER = "VIEWER"


__all__ = ["JobState", "RunState", "Scenario", "UserRole"]
