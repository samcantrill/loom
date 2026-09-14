"""Deterministic SLURM script rendering helpers."""

from __future__ import annotations

import shlex

from .errors import SlurmPlanningError
from .options import SlurmCommandArgv
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


def render_gpu_allocation_environment(requested_count: int) -> tuple[str, ...]:
    """Render the outer-Slurm GPU admission check and cleanenv projection.

    The scheduler owns the allocation.  This shell boundary validates its
    opaque visibility tokens before forwarding them to either supported
    Singularity-family runtime; it does not record those tokens as a realized
    binding.
    """

    if isinstance(requested_count, bool) or not isinstance(requested_count, int):
        raise SlurmPlanningError("planned GPU resource amount must be an integer")
    if requested_count < 0:
        raise SlurmPlanningError("planned GPU resource amount must be non-negative")
    if requested_count == 0:
        return ()
    return (
        '_loom_cuda_visible_devices="${CUDA_VISIBLE_DEVICES-}"',
        'if [[ -z "${_loom_cuda_visible_devices}" || "${_loom_cuda_visible_devices}" == "-1" ]]; then',
        f"  echo 'loom GPU admission failed: requested {requested_count}, CUDA_VISIBLE_DEVICES is missing' >&2",
        "  exit 78",
        "fi",
        "if [[ \"${_loom_cuda_visible_devices}\" == *$'\\n'* ]]; then",
        "  echo 'loom GPU admission failed: invalid visibility token' >&2",
        "  exit 78",
        "fi",
        'if [[ "${_loom_cuda_visible_devices}" == ,* || "${_loom_cuda_visible_devices}" == *, || "${_loom_cuda_visible_devices}" == *,,* ]]; then',
        "  echo 'loom GPU admission failed: invalid visibility token' >&2",
        "  exit 78",
        "fi",
        "IFS=',' read -r -a _loom_cuda_devices <<< \"${_loom_cuda_visible_devices}\"",
        f'if [[ "${{#_loom_cuda_devices[@]}}" -ne {requested_count} ]]; then',
        f"  echo 'loom GPU admission failed: requested {requested_count}, visibility count differs' >&2",
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
    "render_gpu_allocation_environment",
    "render_sbatch_directive",
]
