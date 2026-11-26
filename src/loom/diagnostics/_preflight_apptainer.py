"""Apptainer runtime, resource and filesystem preflight checks."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from loom.serialization import PlainData

from ._preflight_common import (
    _SLURM_EXECUTORS,
    _adapter_options_include_container,
    _apptainer_container_from_adapter,
    _apptainer_options_from_adapter,
    _ApptainerPreflightRawTarget,
    _Context,
    _executor_descriptor,
    _fail,
    _is_slurm_executor,
    _is_slurm_executor_name,
    _local_reference_path,
    _missing_run_uri,
    _nearest_existing_directory,
    _preflight_container_command,
    _request_selects_slurm_container,
    _resolve_apptainer_preflight_target,
    _resource_amount,
    _resource_entries,
    _result,
    _selected_resource_controls,
    _selected_run_uri,
    _severity_for_status,
)
from .models import (
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightGroup,
    PreflightSeverity,
)

_APPTAINER_EXECUTORS = frozenset({"apptainer", "singularity"})


@dataclass(frozen=True)
class _ApptainerPreflightTarget:
    stage_id: str | None
    container: object
    apptainer_options: object
    resources: object | None
    executor_name: str
    selected_executor: str


def _check_apptainer_executor(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_apptainer(context):
        return ()
    return (
        _check_apptainer_command(context),
        _check_apptainer_container_options(context),
        _check_apptainer_image(context),
        _check_apptainer_environment(context),
    )


def _check_apptainer_command(context: _Context) -> PreflightCheckResult:
    try:
        targets = _apptainer_raw_targets(context)
        options = cast(Any, context.runtime_options())
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.apptainer.command",
            PreflightGroup.EXECUTOR,
            "Apptainer command availability probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    commands: list[PlainData] = []
    command_required = _apptainer_command_required(options)
    for target in targets:
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
        command = cast(Any, apptainer_options).command
        resolved = shutil.which(command)
        commands.append(
            {
                "stage_id": target.stage_id,
                "command": command,
                "available": resolved is not None,
                "path": resolved,
                "required": command_required,
            }
        )
        if resolved is None:
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_command_unavailable",
                    message=(
                        "Apptainer/Singularity command is not available on PATH: "
                        f"{command}"
                    ),
                    detail={"command": command, "required": command_required},
                )
            )

    if diagnostics:
        status = (
            PreflightCheckStatus.FAIL if command_required else PreflightCheckStatus.WARN
        )
    else:
        status = PreflightCheckStatus.PASS
    return _result(
        "executor.apptainer.command",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Apptainer/Singularity command is available"
            if status is PreflightCheckStatus.PASS
            else "Apptainer/Singularity command availability checks reported issues"
        ),
        {
            "target_count": len(targets),
            "commands": commands,
            "diagnostics": diagnostics,
            "expensive_probe": False,
        },
    )


def _check_apptainer_container_options(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _apptainer_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.apptainer.container_options",
            PreflightGroup.EXECUTOR,
            "Apptainer container adapter option parsing failed",
            exc,
        )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "executor.apptainer.container_options",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Apptainer container adapter options are valid"
            if status is PreflightCheckStatus.PASS
            else "Apptainer container adapter options are invalid"
        ),
        {
            "target_count": len(parsed) + len(diagnostics),
            "targets": [_apptainer_target_summary(target) for target in parsed],
            "diagnostics": list(diagnostics),
        },
    )


def _check_apptainer_image(context: _Context) -> PreflightCheckResult:
    try:
        targets = _apptainer_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.apptainer.image",
            PreflightGroup.EXECUTOR,
            "Apptainer image/SIF reference probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    images: list[PlainData] = []
    for target in targets:
        try:
            image = _apptainer_image_from_adapter(
                target.adapter_options,
                allow_target_resolution=_is_slurm_executor_name(
                    target.selected_executor
                ),
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_image_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        reference = cast(Any, image).reference
        local_path = _local_reference_path(reference, cwd=context.request.cwd)
        images.append(
            {
                "stage_id": target.stage_id,
                "image": reference,
                "local_path": None if local_path is None else str(local_path),
                "local_path_probe": local_path is not None,
                "exists": None if local_path is None else local_path.exists(),
            }
        )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "executor.apptainer.image",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Apptainer image/SIF references are present"
            if status is PreflightCheckStatus.PASS
            else "Apptainer image/SIF reference checks failed"
        ),
        {
            "target_count": len(targets),
            "images": images,
            "diagnostics": diagnostics,
            "expensive_probe": False,
        },
    )


def _check_apptainer_environment(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _apptainer_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.apptainer.environment",
            PreflightGroup.EXECUTOR,
            "Apptainer environment readiness probe failed",
            exc,
        )
    if diagnostics:
        return _result(
            "executor.apptainer.environment",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "Apptainer environment checks require valid container options",
            {"diagnostics": list(diagnostics)},
        )

    missing: list[PlainData] = []
    required: list[PlainData] = []
    explicit_names: list[PlainData] = []
    cleanenv: list[PlainData] = []
    for target in parsed:
        environment = cast(Any, target.container).environment
        target_required = list(cast(Any, environment).required_host_variables)
        target_explicit = list(cast(Any, environment).variables)
        required.append({"stage_id": target.stage_id, "names": target_required})
        explicit_names.append({"stage_id": target.stage_id, "names": target_explicit})
        cleanenv.append(
            {
                "stage_id": target.stage_id,
                "cleanenv": bool(getattr(target.apptainer_options, "cleanenv")),
                "command": str(getattr(target.apptainer_options, "command")),
            }
        )
        for name in target_required:
            if name not in os.environ:
                missing.append({"stage_id": target.stage_id, "name": name})

    status = PreflightCheckStatus.FAIL if missing else PreflightCheckStatus.PASS
    return _result(
        "executor.apptainer.environment",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Apptainer required host environment variables are available"
            if status is PreflightCheckStatus.PASS
            else "Apptainer required host environment variables are missing"
        ),
        {
            "required_host_variables": required,
            "explicit_variable_names": explicit_names,
            "clean_environment": cleanenv,
            "missing_required_host_variables": missing,
            "value_redaction": "values_not_reported",
        },
    )


def _check_apptainer_resource_mapping(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_apptainer(context):
        return ()
    return (
        _check_apptainer_cpu_memory_mapping(context),
        _check_apptainer_gpu_resource(context),
    )


def _check_apptainer_cpu_memory_mapping(context: _Context) -> PreflightCheckResult:
    try:
        targets = _apptainer_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "resources.apptainer.mapping",
            PreflightGroup.RESOURCES,
            "Apptainer resource mapping probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    mapped: list[PlainData] = []
    for target in targets:
        scheduler_owned = _is_slurm_executor_name(target.selected_executor)
        try:
            if scheduler_owned:
                resources = _resource_entries(target.resources)
                projected: Mapping[str, str] = {}
                apptainer_options = None
            else:
                resources = _apptainer_effective_resource_entries(target)
                apptainer_options = _apptainer_options_from_adapter(
                    target.adapter_options, executor_name=target.executor_name
                )
                projected = _projected_apptainer_cpu_memory_arguments(
                    entries=resources,
                    executor_name=target.executor_name,
                    apptainer_options=apptainer_options,
                    resource_policy=target.resource_policy,
                )
        except Exception as exc:  # noqa: BLE001 - command mapping owns conversion.
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_cpu_memory_projection_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        for kind, entry in sorted(resources.items()):
            if kind in {"cpu", "memory"}:
                capability = _apptainer_resource_capability(
                    kind, executor_name=target.selected_executor
                )
                detail: dict[str, PlainData] = {
                    "stage_id": target.stage_id,
                    "resource_kind": kind,
                    "amount": cast(Any, entry).amount,
                    "unit": cast(Any, entry).unit,
                    "support_level": cast(Any, capability).support_level.value,
                    "enforcement": (
                        "slurm_enforced"
                        if scheduler_owned
                        else (
                            cast(Any, capability).enforcement.value
                            if kind in projected
                            else "not_enforced"
                        )
                    ),
                }
                if not scheduler_owned:
                    detail["runtime_argument"] = projected.get(kind)
                mapped.append(detail)
                continue
            if kind == "gpu":
                continue
            if not scheduler_owned and kind not in _selected_resource_controls(
                target, resources
            ):
                continue
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_resource_unsupported",
                    message=f"Apptainer resource kind {kind!r} is unsupported",
                    detail={"resource_kind": kind},
                )
            )

    if diagnostics:
        status = PreflightCheckStatus.FAIL
        message = "Apptainer resource mapping checks failed"
    elif any(
        cast(dict[str, PlainData], item)["enforcement"] == "not_enforced"
        for item in mapped
    ):
        status = PreflightCheckStatus.WARN
        message = (
            "Apptainer CPU/memory requests are retained but not enforced by the "
            "direct runtime for scheduling-only stages"
        )
    else:
        status = PreflightCheckStatus.PASS
        message = "Apptainer CPU and memory resource mapping is valid"
    return _result(
        "resources.apptainer.mapping",
        PreflightGroup.RESOURCES,
        status,
        _severity_for_status(status),
        message,
        {
            "target_count": len(targets),
            "mapped_resources": mapped,
            "diagnostics": diagnostics,
            "supported_resources": ["cpu", "memory", "gpu"],
            "expensive_probe": False,
        },
    )


def _check_apptainer_gpu_resource(context: _Context) -> PreflightCheckResult:
    try:
        targets = _apptainer_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "resources.apptainer.gpu",
            PreflightGroup.RESOURCES,
            "Apptainer GPU resource probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    gpu_targets: list[PlainData] = []
    for target in targets:
        resources = _apptainer_effective_resource_entries(target)
        gpu = resources.get("gpu")
        if _resource_amount(gpu) <= 0:
            continue
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
        try:
            gpu_flag = _projected_apptainer_gpu_flag(apptainer_options, resources)
            selected = "gpu" in _selected_resource_controls(target, resources)
            if selected and not _is_slurm_executor_name(target.selected_executor):
                _preflight_container_command(target, resources)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_gpu_projection_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        gpu_targets.append(
            {
                "stage_id": target.stage_id,
                "amount": _resource_amount(gpu),
                "unit": getattr(gpu, "unit", None),
                "gpu_flag": gpu_flag,
                "binding": "requested" if selected else "not_requested",
            }
        )
        if gpu_flag is None:
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_gpu_flag_missing",
                    message=(
                        "GPU resources are requested but Apptainer NVIDIA "
                        "passthrough could not be projected"
                    ),
                    detail={"resource_kind": "gpu"},
                )
            )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "resources.apptainer.gpu",
        PreflightGroup.RESOURCES,
        status,
        _severity_for_status(status),
        (
            "Apptainer GPU resources are either not requested or project runtime flags"
            if status is PreflightCheckStatus.PASS
            else "Apptainer GPU resource mapping checks failed"
        ),
        {
            "target_count": len(targets),
            "gpu_targets": gpu_targets,
            "diagnostics": diagnostics,
            "expensive_probe": False,
        },
    )


def _check_apptainer_filesystem(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_apptainer(context):
        return ()
    return (
        _check_apptainer_bind_sources(context),
        _check_apptainer_bind_targets(context),
        _check_apptainer_run_dir_writable(context),
        _check_apptainer_artifact_root_visible(context),
    )


def _check_apptainer_bind_sources(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _apptainer_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.apptainer.bind_sources",
            PreflightGroup.FILESYSTEM,
            "Apptainer bind source probe failed",
            exc,
        )
    if diagnostics:
        return _result(
            "filesystem.apptainer.bind_sources",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "Apptainer bind source checks require valid container options",
            {"diagnostics": list(diagnostics)},
        )

    bind_sources: list[PlainData] = []
    missing: list[PlainData] = []
    for target in parsed:
        for mount in cast(tuple[Any, ...], cast(Any, target.container).mounts):
            source = Path(mount.source)
            exists = source.exists()
            detail = {
                "stage_id": target.stage_id,
                "source": mount.source,
                "target": mount.target,
                "exists": exists,
                "is_dir": source.is_dir() if exists else False,
                "is_file": source.is_file() if exists else False,
            }
            bind_sources.append(detail)
            if not exists:
                missing.append(detail)

    status = PreflightCheckStatus.FAIL if missing else PreflightCheckStatus.PASS
    return _result(
        "filesystem.apptainer.bind_sources",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "Apptainer bind sources exist"
            if status is PreflightCheckStatus.PASS
            else "Apptainer bind source checks failed"
        ),
        {"target_count": len(parsed), "bind_sources": bind_sources, "missing": missing},
    )


def _check_apptainer_bind_targets(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _apptainer_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.apptainer.bind_targets",
            PreflightGroup.FILESYSTEM,
            "Apptainer bind target probe failed",
            exc,
        )
    if diagnostics:
        return _result(
            "filesystem.apptainer.bind_targets",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "Apptainer bind target checks require valid container options",
            {"diagnostics": list(diagnostics)},
        )

    summaries: list[PlainData] = []
    invalid: list[PlainData] = []
    for target in parsed:
        for summary in cast(Any, target.container).path_parity_summaries():
            detail = {"stage_id": target.stage_id, **summary.to_dict()}
            summaries.append(detail)
            if not summary.ok:
                invalid.append(detail)

    status = PreflightCheckStatus.FAIL if invalid else PreflightCheckStatus.PASS
    return _result(
        "filesystem.apptainer.bind_targets",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "Apptainer bind targets satisfy path parity"
            if status is PreflightCheckStatus.PASS
            else "Apptainer bind target path-parity checks failed"
        ),
        {"target_count": len(parsed), "path_parity": summaries, "invalid": invalid},
    )


def _check_apptainer_run_dir_writable(context: _Context) -> PreflightCheckResult:
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.apptainer.run_dir_writable",
            PreflightGroup.FILESYSTEM,
            "Apptainer run-directory writability probe failed",
            exc,
        )
    if run_uri is None:
        return _missing_run_uri(
            "filesystem.apptainer.run_dir_writable", PreflightGroup.FILESYSTEM
        )
    try:
        resolved = cast(Any, context.run_uri())
        probe_parent = _nearest_existing_directory(resolved.path)
        with tempfile.TemporaryDirectory(
            prefix=".loom-preflight-apptainer-",
            dir=probe_parent,
        ) as probe_dir:
            probe_path = Path(probe_dir) / "run-dir-write-probe"
            probe_path.write_text("ok\n", encoding="utf-8")
            probe_path.unlink()
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.apptainer.run_dir_writable",
            PreflightGroup.FILESYSTEM,
            "Apptainer run-directory parent is not writable",
            exc,
        )

    return _result(
        "filesystem.apptainer.run_dir_writable",
        PreflightGroup.FILESYSTEM,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        "Apptainer run-directory parent is writable",
        {
            "run_uri": resolved.uri,
            "run_path": str(resolved.path),
            "probe_parent": str(probe_parent),
        },
    )


def _check_apptainer_artifact_root_visible(context: _Context) -> PreflightCheckResult:
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.apptainer.artifact_root_visible",
            PreflightGroup.FILESYSTEM,
            "Apptainer artifact-root visibility probe failed",
            exc,
        )
    if run_uri is None:
        return _missing_run_uri(
            "filesystem.apptainer.artifact_root_visible", PreflightGroup.FILESYSTEM
        )
    try:
        from loom.pipeline.executors.containers import ContainerMountMode
        from loom.pipeline.stores import LocalRunStore

        parsed, diagnostics = _apptainer_parsed_targets(context)
        if diagnostics:
            return _result(
                "filesystem.apptainer.artifact_root_visible",
                PreflightGroup.FILESYSTEM,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "Apptainer artifact-root checks require valid container options",
                {"diagnostics": list(diagnostics)},
            )
        resolved = cast(Any, context.run_uri())
        store = LocalRunStore(resolved.path.parent)
        run_dir = str(store.local_run_dir(resolved.uri))
        artifact_root = store.local_artifact_root(resolved.uri)
        required_paths = (run_dir, str(artifact_root))
        conflicts: list[PlainData] = []
        for target in parsed:
            mounts = cast(tuple[Any, ...], cast(Any, target.container).mounts)
            for required_path in required_paths:
                existing = next(
                    (mount for mount in mounts if mount.target == required_path),
                    None,
                )
                if existing is None:
                    continue
                mode = cast(Any, existing).mode
                if (
                    existing.source != required_path
                    or mode is not ContainerMountMode.READ_WRITE
                ):
                    conflicts.append(
                        {
                            "stage_id": target.stage_id,
                            "path": required_path,
                            "source": existing.source,
                            "target": existing.target,
                            "mode": mode.value,
                        }
                    )
        if artifact_root.exists() and not artifact_root.is_dir():
            conflicts.append(
                {
                    "stage_id": None,
                    "path": str(artifact_root),
                    "reason": "artifact_root_not_directory",
                }
            )
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.apptainer.artifact_root_visible",
            PreflightGroup.FILESYSTEM,
            "Apptainer artifact-root visibility probe failed",
            exc,
        )

    status = PreflightCheckStatus.FAIL if conflicts else PreflightCheckStatus.PASS
    return _result(
        "filesystem.apptainer.artifact_root_visible",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "Apptainer artifact root is path-parity bindable"
            if status is PreflightCheckStatus.PASS
            else "Apptainer artifact-root path-parity checks failed"
        ),
        {
            "run_uri": resolved.uri,
            "artifact_root": str(artifact_root),
            "artifact_root_exists": artifact_root.exists(),
            "required_binds": [
                {"path": path, "mode": "rw", "source_equals_target": True}
                for path in required_paths
            ],
            "conflicts": conflicts,
        },
    )


def _request_selects_apptainer(context: _Context) -> bool:
    try:
        options = cast(Any, context.runtime_options())
        return _is_apptainer_executor(options) or _request_selects_slurm_container(
            context
        )
    except Exception:  # noqa: BLE001 - caller-specific checks report request failures.
        runtime_options = context.request.runtime_options
        executor = None
        adapter_options: object = None
        stage_options: object = None
        if isinstance(runtime_options, Mapping):
            executor = runtime_options.get("executor")
            adapter_options = runtime_options.get("adapter_options")
            stage_options = runtime_options.get("stage_options")
        else:
            executor = getattr(runtime_options, "executor", None)
            adapter_options = getattr(runtime_options, "adapter_options", None)
            stage_options = getattr(runtime_options, "stage_options", None)
        return executor in _APPTAINER_EXECUTORS or (
            executor in _SLURM_EXECUTORS
            and _adapter_options_include_container(adapter_options, stage_options)
        )


def _is_apptainer_executor(options: object) -> bool:
    return (getattr(options, "executor", None) or "local") in _APPTAINER_EXECUTORS


def _apptainer_raw_targets(
    context: _Context,
) -> tuple[_ApptainerPreflightRawTarget, ...]:
    options = cast(Any, context.runtime_options())
    if not (
        _is_apptainer_executor(options) or _request_selects_slurm_container(context)
    ):
        return ()
    stage_ids = _apptainer_stage_ids(context, options)
    selected_executor = str(getattr(options, "executor", None) or "apptainer")
    if not stage_ids:
        adapter_options = cast(Mapping[str, object], options.adapter_options)
        return (
            _ApptainerPreflightRawTarget(
                stage_id=None,
                adapter_options=adapter_options,
                resources=None,
                resource_policy=getattr(options, "resource_policy", None),
                executor_name=_apptainer_executor_name_for_adapter(
                    adapter_options,
                    fallback=selected_executor,
                ),
                selected_executor=selected_executor,
            ),
        )
    from loom.pipeline.runtime import resolve_run_runtime

    resolved = resolve_run_runtime(options, stage_ids=stage_ids)
    return tuple(
        _ApptainerPreflightRawTarget(
            stage_id=stage_id,
            adapter_options=cast(
                Mapping[str, object],
                cast(Any, resolved[stage_id]).adapter_options,
            ),
            resources=cast(Any, resolved[stage_id]).resources,
            resource_policy=cast(Any, resolved[stage_id]).resource_policy,
            executor_name=_apptainer_executor_name_for_adapter(
                cast(
                    Mapping[str, object], cast(Any, resolved[stage_id]).adapter_options
                ),
                fallback=selected_executor,
            ),
            selected_executor=selected_executor,
        )
        for stage_id in stage_ids
        if _is_apptainer_executor(options)
        or "container" in cast(Any, resolved[stage_id]).adapter_options
    )


def _apptainer_stage_ids(context: _Context, options: object) -> tuple[str, ...]:
    try:
        validation = cast(Any, context.pipeline())
        stage_names = tuple(str(stage_id) for stage_id in validation.spec.stage_names)
        if stage_names:
            return stage_names
    except Exception:  # noqa: BLE001 - checks can still inspect explicit runtime input.
        pass
    return tuple(str(stage_id) for stage_id in cast(Any, options).stage_options)


def _apptainer_parsed_targets(
    context: _Context,
) -> tuple[tuple[_ApptainerPreflightTarget, ...], tuple[PlainData, ...]]:
    parsed: list[_ApptainerPreflightTarget] = []
    diagnostics: list[PlainData] = []
    for target in _apptainer_raw_targets(context):
        try:
            container = _apptainer_container_from_adapter(
                target.adapter_options,
                allow_target_resolution=_is_slurm_executor_name(
                    target.selected_executor
                ),
            )
            apptainer_options = _apptainer_options_from_adapter(
                target.adapter_options,
                executor_name=target.executor_name,
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_container_options_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        parsed.append(
            _ApptainerPreflightTarget(
                stage_id=target.stage_id,
                container=container,
                apptainer_options=apptainer_options,
                resources=target.resources,
                executor_name=target.executor_name,
                selected_executor=target.selected_executor,
            )
        )
    return tuple(parsed), tuple(diagnostics)


def _apptainer_executor_name_for_adapter(
    adapter_options: Mapping[str, object],
    *,
    fallback: str,
) -> str:
    if fallback in _APPTAINER_EXECUTORS:
        return fallback
    if "singularity" in adapter_options:
        return "singularity"
    return "apptainer"


def _apptainer_image_from_adapter(
    adapter_options: Mapping[str, object],
    *,
    allow_target_resolution: bool,
) -> object:
    from loom.pipeline.executors.containers import ContainerImageReference

    if "container" not in adapter_options:
        raise ValueError(
            "adapter_options.container is required for Apptainer preflight"
        )
    raw = adapter_options["container"]
    if (
        allow_target_resolution
        and isinstance(raw, Mapping)
        and "target" in raw
        and "image" not in raw
    ):
        raw = _resolve_apptainer_preflight_target(adapter_options, raw)
    if not isinstance(raw, Mapping):
        raise TypeError("adapter_options.container must be a mapping")
    if "image" not in raw:
        raise ValueError("adapter_options.container.image is required")
    image = raw["image"]
    return (
        ContainerImageReference(reference=image)
        if isinstance(image, str)
        else ContainerImageReference.from_dict(image)
    )


def _apptainer_target_summary(target: _ApptainerPreflightTarget) -> PlainData:
    apptainer_options = cast(Any, target.apptainer_options).to_dict()
    return {
        "stage_id": target.stage_id,
        "executor_name": target.executor_name,
        "selected_executor": target.selected_executor,
        "container": cast(Any, target.container).to_redacted_metadata(),
        "apptainer_option_keys": [
            key for key, value in sorted(apptainer_options.items()) if value is not None
        ],
    }


def _apptainer_diagnostic(
    stage_id: str | None,
    *,
    code: str,
    message: str,
    detail: Mapping[str, PlainData] | None = None,
) -> PlainData:
    payload: dict[str, PlainData] = {
        "stage_id": stage_id,
        "code": code,
        "message": message,
    }
    if detail:
        payload["detail"] = dict(detail)
    return payload


def _apptainer_command_required(options: object) -> bool:
    if _is_apptainer_executor(options):
        return True
    if _is_slurm_executor(options):
        return not bool(getattr(options, "dry_run", False))
    return False


def _apptainer_gpu_flag(apptainer_options: object) -> str | None:
    if bool(getattr(apptainer_options, "nv", False)):
        return "nv"
    if bool(getattr(apptainer_options, "rocm", False)):
        return "rocm"
    return None


def _projected_apptainer_gpu_flag(
    apptainer_options: object,
    resources: object | None,
) -> str | None:
    """Report the same resource-derived GPU option used at execution time."""

    from loom.pipeline.executors.apptainer import ApptainerExecOptions
    from loom.pipeline.executors.gpu_visibility import project_apptainer_gpu_options

    if not isinstance(apptainer_options, ApptainerExecOptions):
        raise TypeError("Apptainer options are not normalized")
    return _apptainer_gpu_flag(
        project_apptainer_gpu_options(apptainer_options, cast(Any, resources))
    )


def _projected_apptainer_cpu_memory_arguments(
    *,
    entries: Mapping[str, object],
    executor_name: str,
    apptainer_options: object | None = None,
    resource_policy: object | None = None,
) -> Mapping[str, str]:
    """Use the production command builder to inspect direct limit conversion."""

    from loom.pipeline.executors.apptainer import build_apptainer_exec_command
    from loom.pipeline.executors.containers import (
        ContainerOptions,
        ContainerResourceIntent,
    )
    from loom.pipeline.resources import ResourceEntry, ResourceRequest

    selected = {
        kind: entry for kind, entry in entries.items() if kind in {"cpu", "memory"}
    }
    if not selected:
        return {}
    descriptor = _executor_descriptor(executor_name)
    intent = ContainerResourceIntent.from_runtime(
        ResourceRequest(
            entries={
                kind: cast(ResourceEntry, entry) for kind, entry in selected.items()
            }
        ),
        {kind: descriptor.capability_for(kind) for kind in selected},
    )
    command = build_apptainer_exec_command(
        container_options=ContainerOptions(image="preflight.sif", resources=intent),
        apptainer_options=cast(Any, apptainer_options),
        worker_command=("loom-preflight",),
        resource_policy=cast(Any, resource_policy),
    )
    argv = command.argv
    projected: dict[str, str] = {}
    for kind, flag in (("cpu", "--cpus"), ("memory", "--memory")):
        if flag in argv:
            projected[kind] = argv[argv.index(flag) + 1]
    return projected


def _apptainer_effective_resource_entries(
    target: _ApptainerPreflightRawTarget,
) -> Mapping[str, object]:
    """Mirror direct execution's runtime-resource override and intent fallback."""

    runtime_entries = _resource_entries(target.resources)
    if runtime_entries:
        return runtime_entries
    container = _apptainer_container_from_adapter(
        target.adapter_options,
        allow_target_resolution=_is_slurm_executor_name(target.selected_executor),
    )
    intent = getattr(container, "resources", None)
    return _resource_entries(intent)


def _apptainer_resource_capability(kind: str, *, executor_name: str) -> Any:
    return _executor_descriptor(executor_name).capability_for(kind)
