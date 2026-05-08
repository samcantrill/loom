"""Pure SLURM dry-run planning contracts."""

from __future__ import annotations

from .errors import (
    SlurmManifestError,
    SlurmOptionError,
    SlurmPathError,
    SlurmPlanningError,
    SlurmResourceMappingError,
)
from .manifest import (
    SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION,
    SlurmDependencyType,
    SlurmMode,
    SlurmPlannedDependency,
    SlurmPlannedJob,
    SlurmPlannedSubmission,
    pipeline_job_key,
    stage_job_key,
    validate_logical_job_key,
)
from .options import (
    DEFAULT_SLURM_LAUNCHER_ARGV,
    GENERATED_SBATCH_DIRECTIVES,
    MODELED_SBATCH_DIRECTIVES,
    RESERVED_SBATCH_DIRECTIVES,
    SLURM_OPTIONS_SCHEMA_VERSION,
    SlurmCommandArgv,
    SlurmOptions,
    build_single_job_command_argv,
    build_stage_job_command_argv,
    normalize_extra_sbatch,
)
from .paths import (
    SLURM_SUBMISSION_ROOT,
    SlurmGeneratedArtifactPath,
    resolve_slurm_generated_artifact_path,
    resolve_slurm_manifest_path,
    slurm_job_log_relative_path,
    slurm_job_script_relative_path,
    slurm_manifest_relative_path,
    slurm_plan_relative_path,
    slurm_submission_relative_path,
)
from .resources import (
    SlurmSbatchDirective,
    build_sbatch_directives,
    map_slurm_resources,
)

__all__ = [
    "DEFAULT_SLURM_LAUNCHER_ARGV",
    "GENERATED_SBATCH_DIRECTIVES",
    "MODELED_SBATCH_DIRECTIVES",
    "RESERVED_SBATCH_DIRECTIVES",
    "SLURM_OPTIONS_SCHEMA_VERSION",
    "SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION",
    "SLURM_SUBMISSION_ROOT",
    "SlurmCommandArgv",
    "SlurmDependencyType",
    "SlurmGeneratedArtifactPath",
    "SlurmManifestError",
    "SlurmMode",
    "SlurmOptionError",
    "SlurmOptions",
    "SlurmPathError",
    "SlurmPlannedDependency",
    "SlurmPlannedJob",
    "SlurmPlannedSubmission",
    "SlurmPlanningError",
    "SlurmResourceMappingError",
    "SlurmSbatchDirective",
    "build_sbatch_directives",
    "build_single_job_command_argv",
    "build_stage_job_command_argv",
    "map_slurm_resources",
    "normalize_extra_sbatch",
    "pipeline_job_key",
    "resolve_slurm_generated_artifact_path",
    "resolve_slurm_manifest_path",
    "slurm_job_log_relative_path",
    "slurm_job_script_relative_path",
    "slurm_manifest_relative_path",
    "slurm_plan_relative_path",
    "slurm_submission_relative_path",
    "stage_job_key",
    "validate_logical_job_key",
]
