"""SLURM dry-run planning errors."""

from __future__ import annotations

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.executors.errors import ExecutorError


class SlurmPlanningError(ExecutorError, RuntimeResourceError):
    """Base error for malformed SLURM planning contracts."""


class SlurmOptionError(SlurmPlanningError):
    """Raised when SLURM options are malformed or conflicting."""


class SlurmResourceMappingError(SlurmPlanningError):
    """Raised when generic resources cannot be mapped to SBATCH directives."""


class SlurmManifestError(SlurmPlanningError):
    """Raised when a planned SLURM manifest is malformed."""


class SlurmPathError(SlurmPlanningError):
    """Raised when a planned SLURM artifact path is malformed."""


class SlurmLiveOperationError(SlurmPlanningError):
    """Base error for live SLURM command and manifest contracts."""


class SlurmCommandUnavailableError(SlurmLiveOperationError):
    """Raised when a required scheduler command is unavailable."""


class SlurmCommandExecutionError(SlurmLiveOperationError):
    """Raised when a scheduler command returns an unsuccessful result."""


class SlurmJobIdParseError(SlurmLiveOperationError):
    """Raised when ``sbatch --parsable`` output does not contain a job ID."""


class SlurmCapabilityUnavailableError(SlurmLiveOperationError):
    """Raised when a command runner cannot provide a requested capability."""


class SlurmManifestUpdateError(SlurmLiveOperationError):
    """Raised when a live SLURM manifest cannot be written or updated."""


__all__ = [
    "SlurmCapabilityUnavailableError",
    "SlurmCommandExecutionError",
    "SlurmCommandUnavailableError",
    "SlurmJobIdParseError",
    "SlurmLiveOperationError",
    "SlurmManifestError",
    "SlurmManifestUpdateError",
    "SlurmOptionError",
    "SlurmPathError",
    "SlurmPlanningError",
    "SlurmResourceMappingError",
]
