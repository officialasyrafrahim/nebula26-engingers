"""Canonical domain enumerations."""

from enum import Enum


class DataQualityState(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    DEGRADED = "DEGRADED"
    MISSING = "MISSING"
    INVALID = "INVALID"


class ConditionTrend(str, Enum):
    STABLE = "STABLE"
    IMPROVING = "IMPROVING"
    DETERIORATING = "DETERIORATING"
    UNKNOWN = "UNKNOWN"


class RecommendationClass(str, Enum):
    MONITOR = "MONITOR"
    INSPECT = "INSPECT"
    MAINTAIN = "MAINTAIN"


class InterventionPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EvidenceType(str, Enum):
    OBSERVATION = "OBSERVATION"
    MODEL_INFERENCE = "MODEL_INFERENCE"
    CONFIRMED_FINDING = "CONFIRMED_FINDING"


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INFEASIBLE = "INFEASIBLE"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


class ApprovalDecision(str, Enum):
    APPROVED = "APPROVED"
    MODIFIED = "MODIFIED"
    REJECTED = "REJECTED"


class ProposalState(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    INVALIDATED = "INVALIDATED"


class WorkPackageState(str, Enum):
    CREATED = "CREATED"
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FindingType(str, Enum):
    CONFIRMED = "CONFIRMED"
    FAULT_NOT_FOUND = "FAULT_NOT_FOUND"
    OTHER = "OTHER"


class UserRole(str, Enum):
    TECHNICIAN = "TECHNICIAN"
    PLANNER = "PLANNER"
    ENGINEER = "ENGINEER"
    ADMIN = "ADMIN"
    MODEL_APPROVER = "MODEL_APPROVER"


class ModelApprovalState(str, Enum):
    CANDIDATE = "CANDIDATE"
    STAGED = "STAGED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class ComponentType(str, Enum):
    DOOR_SYSTEM = "DOOR_SYSTEM"
    BOGIE = "BOGIE"
    TRACTION = "TRACTION"
    BRAKE = "BRAKE"
    HVAC = "HVAC"
    OTHER = "OTHER"
