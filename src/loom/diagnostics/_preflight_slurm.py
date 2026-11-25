"""Slurm submission, resource and filesystem preflight checks."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loom.serialization import PlainData
from loom.state_sources import (
    local_materialization_source,
)

from .models import (
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightGroup,
    PreflightSeverity,
)

if TYPE_CHECKING:
    from loom.pipeline.executors.slurm import SlurmOptions

from ._preflight_apptainer import (
    _apptainer_diagnostic,
    _apptainer_raw_targets,
    _projected_apptainer_gpu_flag,
)
from ._preflight_common import (
    _SLURM_EXECUTORS,
    _active_submission_source,
    _apptainer_options_from_adapter,
    _authority_policy_details,
    _Context,
    _fail,
    _is_slurm_executor,
    _missing_run_uri,
    _nearest_existing_directory,
    _request_selects_slurm_container,
    _resource_amount,
    _resource_entries,
    _result,
    _selected_run_uri,
    _severity_for_status,
)


def _check_runtime_slurm_options(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        options = cast(Any, context.runtime_options())
    except Exception:  # noqa: BLE001 - runtime.options reports normalization failures.
        return ()

    if not _is_slurm_executor(options):
        return ()

    try:
        run_options = _slurm_options_from_adapter(
            options.adapter_options,
            path="RunOptions.adapter_options['slurm']",
        )
        stage_options = {
            stage_id: _slurm_options_from_adapter(
                stage_runtime.adapter_options,
                path=f"RunOptions.stage_options[{stage_id!r}].adapter_options['slurm']",
            )
            for stage_id, stage_runtime in cast(
                Mapping[str, Any], options.stage_options
            ).items()
            if "slurm" in stage_runtime.adapter_options
        }
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "runtime.slurm.options",
                PreflightGroup.RUNTIME,
                "SLURM adapter options are invalid",
                exc,
            ),
        )

    return (
        _result(
            "runtime.slurm.options",
            PreflightGroup.RUNTIME,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "SLURM adapter options are valid",
            cast(
                Mapping[str, PlainData],
                {
                    "executor": options.executor,
                    "run_option_keys": _slurm_option_keys(run_options),
                    "stage_option_count": len(stage_options),
                    "stage_options": sorted(stage_options),
                },
            ),
        ),
    )


def _check_slurm_active_submission(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_slurm(context):
        return ()
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "run_uri.slurm.active_submission",
                PreflightGroup.RUN,
                "SLURM submitted-operation probe failed",
                exc,
            ),
        )
    if run_uri is None:
        return (
            _missing_run_uri("run_uri.slurm.active_submission", PreflightGroup.RUN),
        )
    try:
        from loom.pipeline.execution import create_authority_backed_serial_run_store

        resolved = cast(Any, context.run_uri())
        if not resolved.path.exists():
            return (
                _result(
                    "run_uri.slurm.active_submission",
                    PreflightGroup.RUN,
                    PreflightCheckStatus.PASS,
                    PreflightSeverity.INFO,
                    "no existing run directory has active submitted SLURM work",
                    {
                        "run_uri": resolved.uri,
                        "run_exists": False,
                        "state_source": local_materialization_source(
                            path=str(resolved.path)
                        ),
                        **_authority_policy_details(context),
                    },
                ),
            )
        store = create_authority_backed_serial_run_store(
            resolved.path.parent,
            authority_config=cast(Any, context.authority_config()),
            owner_id="preflight",
        )
        store.open_run(resolved.uri)
        active = store.latest_active_submitted_operation(resolved.uri)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "run_uri.slurm.active_submission",
                PreflightGroup.RUN,
                "SLURM submitted-operation probe failed",
                exc,
            ),
        )
    if active is None:
        return (
            _result(
                "run_uri.slurm.active_submission",
                PreflightGroup.RUN,
                PreflightCheckStatus.PASS,
                PreflightSeverity.INFO,
                "existing run has no active submitted SLURM work",
                {
                    "run_uri": resolved.uri,
                    "active": False,
                    "state_source": _active_submission_source(context),
                    **_authority_policy_details(context),
                },
            ),
        )
    return (
        _result(
            "run_uri.slurm.active_submission",
            PreflightGroup.RUN,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "run already has active submitted scheduler work",
            {
                "run_uri": resolved.uri,
                "active": True,
                "submission_id": active.submission_id,
                "backend": active.backend,
                "mode": active.mode,
                "state": active.state.value,
                "state_source": _active_submission_source(context),
                "guidance": "cancel or inspect active scheduler work before resubmitting",
                **_authority_policy_details(context),
            },
        ),
    )


def _check_slurm_run_uri_local(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_slurm(context):
        return ()
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "run_uri.slurm.local",
                PreflightGroup.RUN,
                "SLURM run URI probe failed",
                exc,
            ),
        )
    if run_uri is None:
        return (_missing_run_uri("run_uri.slurm.local", PreflightGroup.RUN),)
    try:
        resolved = cast(Any, context.run_uri())
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "run_uri.slurm.local",
                PreflightGroup.RUN,
                "SLURM dry-run requires a local run URI",
                exc,
            ),
        )
    return (
        _result(
            "run_uri.slurm.local",
            PreflightGroup.RUN,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "SLURM dry-run run URI resolves locally",
            {
                "run_uri": resolved.uri,
                "path": str(resolved.path),
                "state_source": local_materialization_source(path=str(resolved.path)),
            },
        ),
    )


def _check_slurm_executor(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        options = cast(Any, context.runtime_options())
    except Exception:  # noqa: BLE001 - runtime checks already report this.
        return ()
    if not _is_slurm_executor(options):
        return ()
    dry_run = bool(getattr(options, "dry_run", False))
    checks = [
        _check_slurm_mode(options),
        _check_slurm_launcher(options),
        _check_slurm_sbatch(live_submission=not dry_run),
    ]
    if not dry_run:
        checks.extend(
            (
                _check_optional_slurm_command(
                    check_id="executor.slurm.squeue",
                    command="squeue",
                    purpose="scheduler-aware status for active jobs",
                ),
                _check_optional_slurm_command(
                    check_id="executor.slurm.sacct",
                    command="sacct",
                    purpose="scheduler accounting status for completed jobs",
                ),
                _check_optional_slurm_command(
                    check_id="executor.slurm.scancel",
                    command="scancel",
                    purpose="submitted-job cancellation",
                ),
            )
        )
    return tuple(checks)


def _check_slurm_mode(options: object) -> PreflightCheckResult:
    executor = str(getattr(options, "executor", ""))
    dry_run = bool(getattr(options, "dry_run", False))
    if executor not in _SLURM_EXECUTORS:
        return _result(
            "executor.slurm.mode",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "selected SLURM executor mode is unsupported",
            cast(
                Mapping[str, PlainData],
                {"executor": executor, "supported": sorted(_SLURM_EXECUTORS)},
            ),
        )
    if not dry_run:
        return _result(
            "executor.slurm.mode",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "SLURM live executor mode is supported",
            {"executor": executor, "dry_run": False, "live_submission": True},
        )
    return _result(
        "executor.slurm.mode",
        PreflightGroup.EXECUTOR,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        "SLURM dry-run executor mode is supported",
        {
            "executor": executor,
            "dry_run": True,
            "live_submission": True,
        },
    )


def _check_slurm_launcher(options: object) -> PreflightCheckResult:
    try:
        slurm_options = _slurm_options_from_adapter(
            cast(Any, options).adapter_options,
            path="RunOptions.adapter_options['slurm']",
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.slurm.launcher",
            PreflightGroup.EXECUTOR,
            "SLURM launcher argv is invalid",
            exc,
        )
    return _result(
        "executor.slurm.launcher",
        PreflightGroup.EXECUTOR,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        "SLURM launcher argv is valid",
        {
            "launcher_argv": list(slurm_options.launcher_argv),
            "argc": len(slurm_options.launcher_argv),
        },
    )


def _check_slurm_sbatch(*, live_submission: bool) -> PreflightCheckResult:
    resolved = shutil.which("sbatch")
    if resolved is None:
        if live_submission:
            return _result(
                "executor.slurm.sbatch",
                PreflightGroup.EXECUTOR,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "sbatch is required for SLURM live submission",
                {"command": "sbatch", "available": False, "required": True},
            )
        return _result(
            "executor.slurm.sbatch",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.WARN,
            PreflightSeverity.WARNING,
            "sbatch is not available; SLURM dry-run artifact generation can continue",
            {"command": "sbatch", "available": False},
        )
    return _result(
        "executor.slurm.sbatch",
        PreflightGroup.EXECUTOR,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        "sbatch is available",
        {"command": "sbatch", "available": True, "path": resolved},
    )


def _check_optional_slurm_command(
    *,
    check_id: str,
    command: str,
    purpose: str,
) -> PreflightCheckResult:
    resolved = shutil.which(command)
    if resolved is None:
        return _result(
            check_id,
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.WARN,
            PreflightSeverity.WARNING,
            f"{command} is not available; {purpose} may be unavailable",
            {
                "command": command,
                "available": False,
                "required": False,
                "purpose": purpose,
            },
        )
    return _result(
        check_id,
        PreflightGroup.EXECUTOR,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        f"{command} is available",
        {"command": command, "available": True, "path": resolved, "purpose": purpose},
    )


def _check_slurm_resource_mapping(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    try:
        options = cast(Any, context.runtime_options())
    except Exception:  # noqa: BLE001 - runtime checks already report this.
        return ()
    if not _is_slurm_executor(options):
        return ()
    try:
        from loom.pipeline.executors.slurm.resources import build_sbatch_directives

        run_slurm_options = _slurm_options_from_adapter(
            options.adapter_options,
            path="RunOptions.adapter_options['slurm']",
        )
        mapped: dict[str, int] = {}
        for stage_id, stage_runtime in cast(
            Mapping[str, Any], options.stage_options
        ).items():
            directives = build_sbatch_directives(
                options=_slurm_stage_options(options, stage_id, run_slurm_options),
                resources=stage_runtime.resources,
            )
            mapped[stage_id] = len(directives)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "resources.slurm.mapping",
                PreflightGroup.RESOURCES,
                "SLURM resource mapping failed",
                exc,
            ),
        )

    return (
        _result(
            "resources.slurm.mapping",
            PreflightGroup.RESOURCES,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "SLURM resource mapping is valid",
            cast(
                Mapping[str, PlainData],
                {
                    "stage_count": len(mapped),
                    "directive_counts_by_stage": mapped,
                    "supported_resources": ["cpu", "gpu", "memory"],
                },
            ),
        ),
    )


def _check_slurm_container_compatibility(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    try:
        options = cast(Any, context.runtime_options())
    except Exception:  # noqa: BLE001 - runtime checks already report this.
        return ()
    if not _is_slurm_executor(options) or not _request_selects_slurm_container(context):
        return ()

    diagnostics: list[PlainData] = []
    compatibility: list[PlainData] = []
    try:
        targets = _apptainer_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "resources.slurm.container_compatibility",
                PreflightGroup.RESOURCES,
                "SLURM container compatibility probe failed",
                exc,
            ),
        )
    for target in targets:
        resources = _resource_entries(target.resources)
        try:
            apptainer_options = _apptainer_options_from_adapter(
                target.adapter_options,
                executor_name=target.executor_name,
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_options_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        gpu_requested = _resource_amount(resources.get("gpu")) > 0
        try:
            gpu_flag = _projected_apptainer_gpu_flag(apptainer_options, resources)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_gpu_projection_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        detail: dict[str, PlainData] = {
            "stage_id": target.stage_id,
            "scheduler_authority": "slurm",
            "container_runtime": target.executor_name,
            "selected_executor": target.selected_executor,
            "resource_kinds": cast(list[PlainData], sorted(resources)),
            "gpu_requested": gpu_requested,
            "gpu_flag": gpu_flag,
            "cpu_memory_owner": "slurm",
            "runtime_device_owner": "apptainer",
        }
        compatibility.append(detail)
        if gpu_requested and gpu_flag is None:
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="slurm_container_gpu_flag_missing",
                    message=(
                        "SLURM GPU allocation is selected but GPU passthrough "
                        "could not be projected"
                    ),
                    detail={"resource_kind": "gpu"},
                )
            )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return (
        _result(
            "resources.slurm.container_compatibility",
            PreflightGroup.RESOURCES,
            status,
            _severity_for_status(status),
            (
                "SLURM and Apptainer resource ownership is compatible"
                if status is PreflightCheckStatus.PASS
                else "SLURM and Apptainer resource compatibility checks failed"
            ),
            {
                "target_count": len(targets),
                "compatibility": compatibility,
                "diagnostics": diagnostics,
                "expensive_probe": False,
            },
        ),
    )


def _check_slurm_generated_paths(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_slurm(context):
        return ()
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "filesystem.slurm.generated_paths",
                PreflightGroup.FILESYSTEM,
                "SLURM generated path probe failed",
                exc,
            ),
        )
    if run_uri is None:
        return (
            _missing_run_uri(
                "filesystem.slurm.generated_paths", PreflightGroup.FILESYSTEM
            ),
        )
    try:
        from loom.pipeline.executors.slurm.paths import (
            resolve_slurm_generated_artifact_path,
            slurm_job_log_relative_path,
            slurm_job_script_relative_path,
            slurm_manifest_relative_path,
            slurm_plan_relative_path,
        )
        from loom.pipeline.stores import LocalRunStore

        resolved = cast(Any, context.run_uri())
        store = LocalRunStore(resolved.path.parent)
        relative_paths = (
            slurm_plan_relative_path("preflight"),
            slurm_manifest_relative_path("preflight"),
            slurm_job_script_relative_path("preflight", "pipeline"),
            slurm_job_log_relative_path("preflight", "pipeline", "stdout"),
            slurm_job_log_relative_path("preflight", "pipeline", "stderr"),
        )
        artifacts = [
            resolve_slurm_generated_artifact_path(store, resolved.uri, relative)
            for relative in relative_paths
        ]
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "filesystem.slurm.generated_paths",
                PreflightGroup.FILESYSTEM,
                "SLURM generated paths are unsafe",
                exc,
            ),
        )
    return (
        _result(
            "filesystem.slurm.generated_paths",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "SLURM generated paths resolve under the local run directory",
            cast(
                Mapping[str, PlainData],
                {
                    "run_uri": cast(Any, context.run_uri()).uri,
                    "path_count": len(artifacts),
                    "relative_paths": [
                        artifact.relative_path for artifact in artifacts
                    ],
                },
            ),
        ),
    )


def _check_slurm_generated_paths_writable(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_slurm(context):
        return ()
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "filesystem.slurm.generated_writable",
                PreflightGroup.FILESYSTEM,
                "SLURM generated path writability probe failed",
                exc,
            ),
        )
    if run_uri is None:
        return (
            _missing_run_uri(
                "filesystem.slurm.generated_writable", PreflightGroup.FILESYSTEM
            ),
        )
    try:
        resolved = cast(Any, context.run_uri())
        probe_parent = _nearest_existing_directory(resolved.path)
        with tempfile.TemporaryDirectory(
            prefix=".loom-preflight-slurm-",
            dir=probe_parent,
        ) as probe_dir:
            probe_path = Path(probe_dir) / "generated-path-write-probe"
            probe_path.write_text("ok\n", encoding="utf-8")
            probe_path.unlink()
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "filesystem.slurm.generated_writable",
                PreflightGroup.FILESYSTEM,
                "SLURM generated paths are not writable",
                exc,
            ),
        )
    return (
        _result(
            "filesystem.slurm.generated_writable",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "SLURM generated path parent is writable",
            {
                "run_uri": resolved.uri,
                "run_path": str(resolved.path),
                "probe_parent": str(probe_parent),
            },
        ),
    )


def _request_selects_slurm(context: _Context) -> bool:
    try:
        return _is_slurm_executor(cast(Any, context.runtime_options()))
    except Exception:  # noqa: BLE001 - caller-specific checks report request failures.
        runtime_options = context.request.runtime_options
        executor = None
        if isinstance(runtime_options, Mapping):
            executor = runtime_options.get("executor")
        else:
            executor = getattr(runtime_options, "executor", None)
        return executor in _SLURM_EXECUTORS


def _slurm_options_from_adapter(
    adapter_options: Mapping[str, object],
    *,
    path: str,
) -> "SlurmOptions":
    from loom.pipeline.executors.slurm.options import SlurmOptions

    raw = adapter_options.get("slurm", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise TypeError(f"{path} must be a mapping")
    if not raw:
        return SlurmOptions()
    try:
        return SlurmOptions.from_dict(raw)
    except Exception as exc:  # noqa: BLE001
        raise type(exc)(f"{path}: {exc}") from exc


def _slurm_stage_options(
    options: object,
    stage_id: str,
    fallback: "SlurmOptions",
) -> "SlurmOptions":
    stage_runtime = cast(Mapping[str, Any], getattr(options, "stage_options"))[stage_id]
    if "slurm" not in stage_runtime.adapter_options:
        return fallback
    raw = stage_runtime.adapter_options.get("slurm", {})
    if not isinstance(raw, Mapping):
        raise TypeError(
            f"RunOptions.stage_options[{stage_id!r}].adapter_options['slurm'] "
            "must be a mapping"
        )
    merged = dict(fallback.to_dict())
    merged.update(raw)
    try:
        from loom.pipeline.executors.slurm.options import SlurmOptions

        return SlurmOptions.from_dict(merged)
    except Exception as exc:  # noqa: BLE001
        raise type(exc)(
            f"RunOptions.stage_options[{stage_id!r}].adapter_options['slurm']: {exc}"
        ) from exc


def _slurm_option_keys(options: object) -> list[str]:
    data = cast(Any, options).to_dict()
    return [
        key
        for key, value in sorted(data.items())
        if key != "schema_version" and value not in (None, [], {})
    ]
