"""Independent validation and reporting (F-VALIDATOR-001/002)."""

from app.modules.validator.adapter import (
    OfficialValidatorError,
    ValidationOutcome,
    report_from_official_payload,
    resolve_validator_command,
    run_official_validator,
    validate_with_adapter,
)
from app.modules.validator.calibration import (
    CalibrationResult,
    compare_reports,
    run_calibration,
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
from app.modules.validator.witness import (
    PhysicalCheck,
    PhysicalWitnessReport,
    check_physical_witness,
)

__all__ = [
    "FORMULA_VERSION",
    "Authority",
    "CalibrationResult",
    "HardViolation",
    "OfficialValidatorError",
    "PhysicalCheck",
    "PhysicalWitnessReport",
    "SoftScores",
    "ValidationContext",
    "ValidationOutcome",
    "ValidatorDetail",
    "ValidatorReport",
    "check_physical_witness",
    "compare_reports",
    "infer_scenario",
    "report_from_official_payload",
    "resolve_validator_command",
    "run_calibration",
    "run_checks",
    "run_official_validator",
    "validate_bundle",
    "validate_compiled",
    "validate_directories",
    "validate_with_adapter",
]
