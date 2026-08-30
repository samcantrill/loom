"""Deterministic SLURM script rendering helpers."""

from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from typing import cast

from .errors import SlurmPlanningError
from .manifest import SlurmDependencyType, SlurmMode, SlurmPlannedJob
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
    gpu_lines = _gpu_allocation_lines(job)
    if gpu_lines:
        lines.append("")
        lines.extend(gpu_lines)
    lines.extend(("", render_command_argv(command), ""))
    return "\n".join(lines)


def _gpu_allocation_lines(job: SlurmPlannedJob) -> tuple[str, ...]:
    if job.mode is not SlurmMode.AFTEROK:
        return ()
    raw = job.resources.get("gpu")
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise SlurmPlanningError("planned GPU resources must be a mapping")
    amount = raw.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise SlurmPlanningError("planned GPU resource amount must be non-negative")
    if amount == 0:
        return ()
    return (
        '_loom_cuda_visible_devices="${CUDA_VISIBLE_DEVICES-}"',
        'if [[ -z "${_loom_cuda_visible_devices}" || "${_loom_cuda_visible_devices}" == "-1" ]]; then',
        f"  echo 'loom GPU admission failed: requested {amount}, CUDA_VISIBLE_DEVICES is missing' >&2",
        "  exit 78",
        "fi",
        'if [[ "${_loom_cuda_visible_devices}" == ,* || "${_loom_cuda_visible_devices}" == *, || "${_loom_cuda_visible_devices}" == *,,* ]]; then',
        "  echo 'loom GPU admission failed: invalid visibility token' >&2",
        "  exit 78",
        "fi",
        "IFS=',' read -r -a _loom_cuda_devices <<< \"${_loom_cuda_visible_devices}\"",
        f'if [[ "${{#_loom_cuda_devices[@]}}" -ne {amount} ]]; then',
        f"  echo 'loom GPU admission failed: requested {amount}, visibility count differs' >&2",
        "  exit 78",
        "fi",
        'for _loom_cuda_device in "${_loom_cuda_devices[@]}"; do',
        '  case "${_loom_cuda_device}" in',
        "    ''|[!A-Za-z0-9]*|*[!A-Za-z0-9._:/-]*) echo 'loom GPU admission failed: invalid visibility token' >&2; exit 78 ;;",
        "  esac",
        "done",
        "for (( _loom_cuda_i=0; _loom_cuda_i<${#_loom_cuda_devices[@]}; _loom_cuda_i++ )); do",
        "  for (( _loom_cuda_j=_loom_cuda_i+1; _loom_cuda_j<${#_loom_cuda_devices[@]}; _loom_cuda_j++ )); do",
        '    if [[ "${_loom_cuda_devices[_loom_cuda_i]}" == "${_loom_cuda_devices[_loom_cuda_j]}" ]]; then',
        "      echo 'loom GPU admission failed: duplicate visibility token' >&2",
        "      exit 78",
        "    fi",
        "  done",
        "done",
        'export APPTAINERENV_CUDA_VISIBLE_DEVICES="${_loom_cuda_visible_devices}"',
        'export SINGULARITYENV_CUDA_VISIBLE_DEVICES="${_loom_cuda_visible_devices}"',
    )


__all__ = [
    "render_command_argv",
    "render_dependency_value",
    "render_sbatch_directive",
    "render_slurm_script",
]
