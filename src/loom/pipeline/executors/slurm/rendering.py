"""Deterministic SLURM script rendering helpers."""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from typing import cast

from .errors import SlurmPlanningError
from .manifest import SlurmDependencyType, SlurmPlannedJob
from .options import SlurmCommandArgv, SlurmOptions
from .resources import SlurmSbatchDirective


def render_command_argv(command: SlurmCommandArgv) -> str:
    """Render structured argv as shell-safe command text."""

    if not isinstance(command, SlurmCommandArgv):
        raise SlurmPlanningError("command must be a SlurmCommandArgv")
    return " ".join(shlex.quote(part) for part in command.argv)


def render_sbatch_directive(directive: SlurmSbatchDirective) -> str:
    """Render one structured SBATCH directive."""

    if not isinstance(directive, SlurmSbatchDirective):
        raise SlurmPlanningError("directive must be a SlurmSbatchDirective")
    if directive.value is True:
        return f"#SBATCH --{directive.name}"
    return f"#SBATCH --{directive.name}={directive.value}"


def render_dependency_value(
    dependency_job_keys: Sequence[str],
    *,
    dependency_type: SlurmDependencyType = SlurmDependencyType.AFTEROK,
) -> str:
    """Render a dry-run dependency value from logical upstream job keys."""

    if dependency_type is not SlurmDependencyType.AFTEROK:
        raise SlurmPlanningError("only afterok SLURM dependencies are supported")
    if not dependency_job_keys:
        raise SlurmPlanningError("dependency_job_keys must not be empty")
    return "afterok:" + ":".join(dependency_job_keys)


def render_slurm_script(
    job: SlurmPlannedJob,
    *,
    options: SlurmOptions,
) -> str:
    """Render a deterministic dry-run SBATCH script for a planned job."""

    if not isinstance(job, SlurmPlannedJob):
        raise SlurmPlanningError("job must be a SlurmPlannedJob")
    if not isinstance(options, SlurmOptions):
        raise SlurmPlanningError("options must be a SlurmOptions")
    command = cast(SlurmCommandArgv, job.command)
    directives = cast(tuple[SlurmSbatchDirective, ...], job.sbatch_directives)

    lines = ["#!/usr/bin/env bash"]
    lines.extend(render_sbatch_directive(directive) for directive in directives)
    lines.extend(("", "set -euo pipefail"))
    if options.prelude:
        lines.append("")
        lines.extend(options.prelude)
    lines.extend(("", render_command_argv(command), ""))
    return "\n".join(lines)


__all__ = [
    "render_command_argv",
    "render_dependency_value",
    "render_sbatch_directive",
    "render_slurm_script",
]
