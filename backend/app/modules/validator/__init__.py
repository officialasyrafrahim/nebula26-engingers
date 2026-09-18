"""Independent validation and reporting (F-VALIDATOR-001/002)."""

from app.modules.validator.adapter import (
    OfficialValidatorError,
    ValidationOutcome,
    report_from_official_payload,
    resolve_validator_command,
    run_official_validator,
    validate_with_adapter,
)
from app.modules.validator.checks import run_checks
from app.modules.validator.checks.context import ValidationContext
from app.modules.validator.fallback_validator import (
    infer_scenario,
    validate_bundle,
    validate_compiled,
    validate_directories,
)
from app.modules.validator.report import (
    FORMULA_VERSION,
    Authority,
    HardViolation,
    SoftScores,
    ValidatorDetail,
    ValidatorReport,
)

__all__ = [
    "FORMULA_VERSION",
    "Authority",
    "HardViolation",
    "OfficialValidatorError",
    "SoftScores",
    "ValidationContext",
    "ValidationOutcome",
    "ValidatorDetail",
    "ValidatorReport",
    "infer_scenario",
    "report_from_official_payload",
    "resolve_validator_command",
    "run_checks",
    "run_official_validator",
    "validate_bundle",
    "validate_compiled",
    "validate_directories",
    "validate_with_adapter",
]
