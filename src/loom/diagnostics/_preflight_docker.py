"""Docker runtime, resource and filesystem preflight checks."""

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
    _Context,
    _docker_container_from_adapter,
    _docker_options_from_adapter,
    _DockerPreflightRawTarget,
    _fail,
    _missing_run_uri,
    _nearest_existing_directory,
    _preflight_container_command,
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


@dataclass(frozen=True)
class _DockerPreflightTarget:
    stage_id: str | None
    container: object
    docker_options: object
    resources: object | None


def _check_docker_executor(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_docker(context):
        return ()
    return (
        _check_docker_command(context),
        _check_docker_container_options(context),
        _check_docker_image(context),
        _check_docker_environment(context),
    )


def _check_docker_command(context: _Context) -> PreflightCheckResult:
    try:
        targets = _docker_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.docker.command",
            PreflightGroup.EXECUTOR,
            "Docker command availability probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    commands: list[PlainData] = []
    for target in targets:
        try:
            docker_options = _docker_options_from_adapter(target.adapter_options)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _docker_diagnostic(
                    target.stage_id,
                    code="docker_options_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        command = cast(Any, docker_options).command
        resolved = shutil.which(command)
        commands.append(
            {
                "stage_id": target.stage_id,
                "command": command,
                "available": resolved is not None,
                "path": resolved,
            }
        )
        if resolved is None:
            diagnostics.append(
                _docker_diagnostic(
                    target.stage_id,
                    code="docker_command_unavailable",
                    message=f"Docker command is not available on PATH: {command}",
                    detail={"command": command},
                )
            )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "executor.docker.command",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Docker command is available"
            if status is PreflightCheckStatus.PASS
            else "Docker command availability checks failed"
        ),
        {
            "target_count": len(targets),
            "commands": commands,
            "diagnostics": diagnostics,
            "expensive_probe": False,
        },
    )


def _check_docker_container_options(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _docker_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.docker.container_options",
            PreflightGroup.EXECUTOR,
            "Docker adapter option parsing failed",
            exc,
        )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "executor.docker.container_options",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Docker container adapter options are valid"
            if status is PreflightCheckStatus.PASS
            else "Docker container adapter options are invalid"
        ),
        {
            "target_count": len(parsed) + len(diagnostics),
            "targets": [_docker_target_summary(target) for target in parsed],
            "diagnostics": list(diagnostics),
        },
    )


def _check_docker_image(context: _Context) -> PreflightCheckResult:
    try:
        targets = _docker_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.docker.image",
            PreflightGroup.EXECUTOR,
            "Docker image reference probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    images: list[PlainData] = []
    for target in targets:
        try:
            image = _docker_image_from_adapter(target.adapter_options)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _docker_diagnostic(
                    target.stage_id,
                    code="docker_image_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        reference = cast(Any, image).reference
        images.append({"stage_id": target.stage_id, "image": reference})

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "executor.docker.image",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Docker image references are present"
            if status is PreflightCheckStatus.PASS
            else "Docker image reference checks failed"
        ),
        {
            "target_count": len(targets),
            "images": images,
            "diagnostics": diagnostics,
            "expensive_probe": False,
        },
    )


def _check_docker_environment(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _docker_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.docker.environment",
            PreflightGroup.EXECUTOR,
            "Docker environment readiness probe failed",
            exc,
        )
    if diagnostics:
        return _result(
            "executor.docker.environment",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "Docker environment checks require valid container options",
            {"diagnostics": list(diagnostics)},
        )

    missing: list[PlainData] = []
    required: list[PlainData] = []
    explicit_names: list[PlainData] = []
    for target in parsed:
        environment = cast(Any, target.container).environment
        target_required = list(cast(Any, environment).required_host_variables)
        target_explicit = list(cast(Any, environment).variables)
        required.append({"stage_id": target.stage_id, "names": target_required})
        explicit_names.append({"stage_id": target.stage_id, "names": target_explicit})
        for name in target_required:
            if name not in os.environ:
                missing.append({"stage_id": target.stage_id, "name": name})

    status = PreflightCheckStatus.FAIL if missing else PreflightCheckStatus.PASS
    return _result(
        "executor.docker.environment",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Docker required host environment variables are available"
            if status is PreflightCheckStatus.PASS
            else "Docker required host environment variables are missing"
        ),
        {
            "required_host_variables": required,
            "explicit_variable_names": explicit_names,
            "missing_required_host_variables": missing,
            "value_redaction": "values_not_reported",
        },
    )


def _check_docker_resource_mapping(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_docker(context):
        return ()
    return (
        _check_docker_cpu_memory_mapping(context),
        _check_docker_gpu_resource(context),
    )


def _check_docker_cpu_memory_mapping(context: _Context) -> PreflightCheckResult:
    try:
        targets = _docker_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "resources.docker.mapping",
            PreflightGroup.RESOURCES,
            "Docker resource mapping probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    mapped: list[PlainData] = []
    for target in targets:
        try:
            resources = _docker_effective_resource_entries(target)
            command = _preflight_container_command(target, resources)
            selected = _selected_resource_controls(target, resources)
        except Exception as exc:  # noqa: BLE001 - production mapper owns validity.
            diagnostics.append(
                _docker_diagnostic(
                    target.stage_id,
                    code="docker_resource_projection_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        for kind, entry in sorted(resources.items()):
            capability = _docker_resource_capability(kind)
            support_level = cast(Any, capability).support_level.value
            enforcement = (
                cast(Any, capability).enforcement.value
                if kind in selected
                else "not_enforced"
            )
            if kind in {"cpu", "memory"}:
                mapped.append(
                    {
                        "stage_id": target.stage_id,
                        "resource_kind": kind,
                        "amount": cast(Any, entry).amount,
                        "unit": cast(Any, entry).unit,
                        "support_level": support_level,
                        "enforcement": enforcement,
                        "resource_controls": cast(Any, command).metadata[
                            "resource_controls"
                        ],
                    }
                )
                continue
            if kind not in selected:
                continue
            diagnostics.append(
                _docker_diagnostic(
                    target.stage_id,
                    code="docker_resource_unsupported",
                    message=f"Docker resource kind {kind!r} is unsupported",
                    detail={
                        "resource_kind": kind,
                        "support_level": support_level,
                        "enforcement": enforcement,
                    },
                )
            )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "resources.docker.mapping",
        PreflightGroup.RESOURCES,
        status,
        _severity_for_status(status),
        (
            "Docker CPU and memory resource mapping is valid"
            if status is PreflightCheckStatus.PASS
            else "Docker resource mapping checks failed"
        ),
        {
            "target_count": len(targets),
            "mapped_resources": mapped,
            "diagnostics": diagnostics,
            "supported_resources": ["cpu", "memory"],
            "expensive_probe": False,
        },
    )


def _check_docker_gpu_resource(context: _Context) -> PreflightCheckResult:
    try:
        targets = _docker_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "resources.docker.gpu",
            PreflightGroup.RESOURCES,
            "Docker GPU resource probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    for target in targets:
        resources = _docker_effective_resource_entries(target)
        if "gpu" not in _selected_resource_controls(target, resources):
            continue
        capability = _docker_resource_capability("gpu")
        diagnostics.append(
            _docker_diagnostic(
                target.stage_id,
                code="docker_gpu_unsupported",
                message=(
                    "Docker GPU enforcement is unsupported; omit gpu from "
                    "resource_policy.enforce or use a supporting executor"
                ),
                detail={
                    "resource_kind": "gpu",
                    "amount": cast(Any, resources["gpu"]).amount,
                    "unit": cast(Any, resources["gpu"]).unit,
                    "support_level": cast(Any, capability).support_level.value,
                    "enforcement": cast(Any, capability).enforcement.value,
                },
            )
        )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "resources.docker.gpu",
        PreflightGroup.RESOURCES,
        status,
        _severity_for_status(status),
        (
            "Docker GPU enforcement is not requested"
            if status is PreflightCheckStatus.PASS
            else "Docker GPU resource mapping is unsupported"
        ),
        {
            "target_count": len(targets),
            "diagnostics": diagnostics,
            "supported": False,
            "expensive_probe": False,
        },
    )


def _check_docker_filesystem(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_docker(context):
        return ()
    return (
        _check_docker_mount_sources(context),
        _check_docker_mount_targets(context),
        _check_docker_run_dir_writable(context),
        _check_docker_artifact_root_visible(context),
    )


def _check_docker_mount_sources(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _docker_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.docker.mount_sources",
            PreflightGroup.FILESYSTEM,
            "Docker mount source probe failed",
            exc,
        )
    if diagnostics:
        return _result(
            "filesystem.docker.mount_sources",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "Docker mount source checks require valid container options",
            {"diagnostics": list(diagnostics)},
        )

    mount_sources: list[PlainData] = []
    missing: list[PlainData] = []
    for target in parsed:
        for mount in cast(tuple[Any, ...], cast(Any, target.container).mounts):
            source = Path(mount.source)
            exists = source.exists()
            is_dir = source.is_dir() if exists else False
            is_file = source.is_file() if exists else False
            detail = {
                "stage_id": target.stage_id,
                "source": mount.source,
                "target": mount.target,
                "exists": exists,
                "is_dir": is_dir,
                "is_file": is_file,
            }
            mount_sources.append(detail)
            if not exists:
                missing.append(detail)

    status = PreflightCheckStatus.FAIL if missing else PreflightCheckStatus.PASS
    return _result(
        "filesystem.docker.mount_sources",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "Docker mount sources exist"
            if status is PreflightCheckStatus.PASS
            else "Docker mount source checks failed"
        ),
        {
            "target_count": len(parsed),
            "mount_sources": mount_sources,
            "missing": missing,
        },
    )


def _check_docker_mount_targets(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _docker_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.docker.mount_targets",
            PreflightGroup.FILESYSTEM,
            "Docker mount target probe failed",
            exc,
        )
    if diagnostics:
        return _result(
            "filesystem.docker.mount_targets",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "Docker mount target checks require valid container options",
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
        "filesystem.docker.mount_targets",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "Docker mount targets satisfy Stage 17 path parity"
            if status is PreflightCheckStatus.PASS
            else "Docker mount target path-parity checks failed"
        ),
        {
            "target_count": len(parsed),
            "path_parity": summaries,
            "invalid": invalid,
        },
    )


def _check_docker_run_dir_writable(context: _Context) -> PreflightCheckResult:
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.docker.run_dir_writable",
            PreflightGroup.FILESYSTEM,
            "Docker run-directory writability probe failed",
            exc,
        )
    if run_uri is None:
        return _missing_run_uri(
            "filesystem.docker.run_dir_writable", PreflightGroup.FILESYSTEM
        )
    try:
        resolved = cast(Any, context.run_uri())
        probe_parent = _nearest_existing_directory(resolved.path)
        with tempfile.TemporaryDirectory(
            prefix=".loom-preflight-docker-",
            dir=probe_parent,
        ) as probe_dir:
            probe_path = Path(probe_dir) / "run-dir-write-probe"
            probe_path.write_text("ok\n", encoding="utf-8")
            probe_path.unlink()
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.docker.run_dir_writable",
            PreflightGroup.FILESYSTEM,
            "Docker run-directory parent is not writable",
            exc,
        )

    return _result(
        "filesystem.docker.run_dir_writable",
        PreflightGroup.FILESYSTEM,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        "Docker run-directory parent is writable",
        {
            "run_uri": resolved.uri,
            "run_path": str(resolved.path),
            "probe_parent": str(probe_parent),
        },
    )


def _check_docker_artifact_root_visible(context: _Context) -> PreflightCheckResult:
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.docker.artifact_root_visible",
            PreflightGroup.FILESYSTEM,
            "Docker artifact-root visibility probe failed",
            exc,
        )
    if run_uri is None:
        return _missing_run_uri(
            "filesystem.docker.artifact_root_visible", PreflightGroup.FILESYSTEM
        )
    try:
        from loom.pipeline.executors.containers import ContainerMountMode
        from loom.pipeline.stores import LocalRunStore

        parsed, diagnostics = _docker_parsed_targets(context)
        if diagnostics:
            return _result(
                "filesystem.docker.artifact_root_visible",
                PreflightGroup.FILESYSTEM,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "Docker artifact-root checks require valid container options",
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
            "filesystem.docker.artifact_root_visible",
            PreflightGroup.FILESYSTEM,
            "Docker artifact-root visibility probe failed",
            exc,
        )

    status = PreflightCheckStatus.FAIL if conflicts else PreflightCheckStatus.PASS
    return _result(
        "filesystem.docker.artifact_root_visible",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "Docker artifact root is path-parity mountable"
            if status is PreflightCheckStatus.PASS
            else "Docker artifact-root path-parity checks failed"
        ),
        {
            "run_uri": resolved.uri,
            "artifact_root": str(artifact_root),
            "artifact_root_exists": artifact_root.exists(),
            "required_mounts": [
                {"path": path, "mode": "rw", "source_equals_target": True}
                for path in required_paths
            ],
            "conflicts": conflicts,
        },
    )


def _request_selects_docker(context: _Context) -> bool:
    try:
        return _is_docker_executor(cast(Any, context.runtime_options()))
    except Exception:  # noqa: BLE001 - caller-specific checks report request failures.
        runtime_options = context.request.runtime_options
        executor = None
        if isinstance(runtime_options, Mapping):
            executor = runtime_options.get("executor")
        else:
            executor = getattr(runtime_options, "executor", None)
        return executor == "docker"


def _is_docker_executor(options: object) -> bool:
    return (getattr(options, "executor", None) or "local") == "docker"


def _docker_raw_targets(context: _Context) -> tuple[_DockerPreflightRawTarget, ...]:
    options = cast(Any, context.runtime_options())
    if not _is_docker_executor(options):
        return ()
    stage_ids = _docker_stage_ids(context, options)
    if not stage_ids:
        return (
            _DockerPreflightRawTarget(
                stage_id=None,
                adapter_options=cast(Mapping[str, object], options.adapter_options),
                resources=None,
                resource_policy=getattr(options, "resource_policy", None),
            ),
        )
    from loom.pipeline.runtime import resolve_run_runtime

    resolved = resolve_run_runtime(options, stage_ids=stage_ids)
    return tuple(
        _DockerPreflightRawTarget(
            stage_id=stage_id,
            adapter_options=cast(
                Mapping[str, object],
                cast(Any, resolved[stage_id]).adapter_options,
            ),
            resources=cast(Any, resolved[stage_id]).resources,
            resource_policy=cast(Any, resolved[stage_id]).resource_policy,
        )
        for stage_id in stage_ids
    )


def _docker_stage_ids(context: _Context, options: object) -> tuple[str, ...]:
    try:
        validation = cast(Any, context.pipeline())
        stage_names = tuple(str(stage_id) for stage_id in validation.spec.stage_names)
        if stage_names:
            return stage_names
    except Exception:  # noqa: BLE001 - Docker option checks can still inspect explicit runtime input.
        pass
    return tuple(str(stage_id) for stage_id in cast(Any, options).stage_options)


def _docker_parsed_targets(
    context: _Context,
) -> tuple[tuple[_DockerPreflightTarget, ...], tuple[PlainData, ...]]:
    parsed: list[_DockerPreflightTarget] = []
    diagnostics: list[PlainData] = []
    for target in _docker_raw_targets(context):
        try:
            container = _docker_container_from_adapter(target.adapter_options)
            docker_options = _docker_options_from_adapter(target.adapter_options)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _docker_diagnostic(
                    target.stage_id,
                    code="docker_container_options_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        parsed.append(
            _DockerPreflightTarget(
                stage_id=target.stage_id,
                container=container,
                docker_options=docker_options,
                resources=target.resources,
            )
        )
    return tuple(parsed), tuple(diagnostics)


def _docker_effective_resource_entries(
    target: _DockerPreflightRawTarget,
) -> Mapping[str, object]:
    runtime_entries = _resource_entries(target.resources)
    if runtime_entries:
        return runtime_entries
    container = _docker_container_from_adapter(target.adapter_options)
    return _resource_entries(getattr(container, "resources", None))


def _docker_image_from_adapter(adapter_options: Mapping[str, object]) -> object:
    from loom.pipeline.executors.containers import ContainerImageReference

    if "container" not in adapter_options:
        raise ValueError("adapter_options.container is required for Docker preflight")
    raw = adapter_options["container"]
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


def _docker_target_summary(target: _DockerPreflightTarget) -> PlainData:
    docker_options = cast(Any, target.docker_options).to_dict()
    return {
        "stage_id": target.stage_id,
        "container": cast(Any, target.container).to_redacted_metadata(),
        "docker_option_keys": [
            key for key, value in sorted(docker_options.items()) if value is not None
        ],
    }


def _docker_diagnostic(
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


def _docker_resource_capability(kind: str) -> object:
    from loom.pipeline.runtime.capabilities import DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY

    descriptor = DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.resolve("docker")
    return descriptor.capability_for(kind)
