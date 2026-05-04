"""Planning-specific errors for dry-run planning and resume decisions."""

from __future__ import annotations

from loom.errors import PipelineError, ValidationError


class PlanningError(PipelineError):
    """Raised for planning- and planner-level failures."""


class PlanningValidationError(PlanningError, ValidationError):
    """Raised when a planning input or serialized planning payload is invalid."""


class SelectorValidationError(PlanningValidationError):
    """Raised when selector combinations or stage references are invalid."""


class PlanSerializationError(PlanningValidationError):
    """Raised when planning payloads cannot be parsed or serialized safely."""


class StageFingerprintError(PlanningValidationError):
    """Raised when a stage fingerprint cannot be computed."""


class ResumeStateError(PlanningError):
    """Raised when prior run-state is corrupt or unsafe to interpret."""


class PlanPersistenceError(PlanningError):
    """Raised when planning persistence fails."""


__all__ = [
    "PlanningError",
    "PlanningValidationError",
    "SelectorValidationError",
    "PlanSerializationError",
    "StageFingerprintError",
    "ResumeStateError",
    "PlanPersistenceError",
]
