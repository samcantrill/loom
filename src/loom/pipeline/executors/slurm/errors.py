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


__all__ = [
    "SlurmManifestError",
    "SlurmOptionError",
    "SlurmPathError",
    "SlurmPlanningError",
    "SlurmResourceMappingError",
]
