"""Shared preflight context, selection and result construction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from loom.serialization import PlainData
from loom.state_sources import (
    authoritative_service_source,
    deferred_finalization_source,
    offline_evidence_source,
    redacted_authority_summary,
    unavailable_authority_source,
)

from .models import (
    STABLE_CHECK_IDS,
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightGroup,
    PreflightRequest,
    PreflightSeverity,
)

_SLURM_EXECUTORS = frozenset({"slurm-single-job", "slurm-afterok"})


@dataclass(frozen=True)
class _DockerPreflightRawTarget:
    stage_id: str | None
    adapter_options: Mapping[str, object]
    resources: object | None
    resource_policy: object | None


@dataclass(frozen=True)
class _ApptainerPreflightRawTarget:
    stage_id: str | None
    adapter_options: Mapping[str, object]
    resources: object | None
    resource_policy: object | None
    executor_name: str
    selected_executor: str


@dataclass
class _Context:
    request: PreflightRequest
    composed: object | None = None
    _config: object | None = None
    _config_error: BaseException | None = None
    _pipeline: object | None = None
    _pipeline_error: BaseException | None = None
    _runtime_options: object | None = None
    _runtime_options_error: BaseException | None = None
    _capability_validation: object | None = None
    _capability_validation_error: BaseException | None = None
    _run_uri: object | None = None
    _run_uri_error: BaseException | None = None

    def authority_config(self) -> object | None:
        return self.request.authority_config

    def authority_mode(self) -> object | None:
        return self.request.authority_mode

    def config(self) -> object:
        if self.composed is not None:
            return self.composed
        if self._config is not None:
            return self._config
        if self._config_error is not None:
            raise self._config_error
        try:
            from weave.api import compose_config

            self._config = compose_config(
                _resolve_path(self.request.config_path, cwd=self.request.cwd),
                overlays=tuple(
                    _resolve_path(path, cwd=self.request.cwd)
                    for path in self.request.overlays
                ),
                overrides=self.request.overrides,
            )
        except Exception as exc:  # noqa: BLE001
            self._config_error = exc
            raise
        return self._config

    def pipeline(self) -> object:
        if self._pipeline is not None:
            return self._pipeline
        if self._pipeline_error is not None:
            raise self._pipeline_error
        try:
            from loom.pipeline import validate_pipeline_config

            composed = self.config()
            resolved = cast(Any, composed).resolved
            self._pipeline = (
                validate_pipeline_config(
                    resolved,
                    registry=cast(Any, self.request.resource_validator_registry),
                )
                if self.request.resource_validator_registry is not None
                else validate_pipeline_config(resolved)
            )
        except Exception as exc:  # noqa: BLE001
            self._pipeline_error = exc
            raise
        return self._pipeline

    def runtime_options(self) -> object:
        if self._runtime_options is not None:
            return self._runtime_options
        if self._runtime_options_error is not None:
            raise self._runtime_options_error
        try:
            from loom.pipeline.runtime import merge_config_run_options

            composed = self.config()
            self._runtime_options = merge_config_run_options(
                cast(Any, composed).resolved,
                explicit=cast(Any, _request_runtime_source(self.request)),
                registry=cast(Any, self.request.resource_validator_registry),
            )
        except Exception as exc:  # noqa: BLE001
            self._runtime_options_error = exc
            raise
        return self._runtime_options

    def capability_validation(self) -> object:
        if self._capability_validation is not None:
            return self._capability_validation
        if self._capability_validation_error is not None:
            raise self._capability_validation_error
        try:
            from loom.pipeline.runtime import validate_executor_capabilities

            self._capability_validation = validate_executor_capabilities(
                cast(Any, self.runtime_options()),
                registry=cast(Any, self.request.executor_descriptor_registry),
                resource_validator_registry=cast(
                    Any,
                    self.request.resource_validator_registry,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self._capability_validation_error = exc
            raise
        return self._capability_validation

    def run_uri(self) -> object:
        if self._run_uri is not None:
            return self._run_uri
        if self._run_uri_error is not None:
            raise self._run_uri_error
        try:
            from loom.pipeline.stores import resolve_local_run_uri

            self._run_uri = resolve_local_run_uri(
                _selected_run_uri(self), cwd=self.request.cwd
            )
        except Exception as exc:  # noqa: BLE001
            self._run_uri_error = exc
            raise
        return self._run_uri


def _authority_policy_details(context: _Context) -> dict[str, PlainData]:
    config = context.authority_config()
    authority = redacted_authority_summary(config)
    backend_kind = _enum_value(getattr(config, "backend_kind", None))
    deployment_profile = _enum_value(getattr(config, "deployment_profile", None))
    authority_mode = _enum_value(context.authority_mode())
    policy: dict[str, PlainData] = {
        "backend_kind": backend_kind,
        "deployment_profile": deployment_profile,
    }
    if authority_mode is not None:
        policy["authority_mode"] = authority_mode
    details: dict[str, PlainData] = {"authority_policy": policy}
    if authority is not None:
        details["authority"] = authority
    if authority_mode == "offline_first":
        policy["source"] = offline_evidence_source()
        details["guidance"] = (
            "offline-first mode records local evidence and does not create "
            "authority truth until import"
        )
    elif (
        backend_kind == "deferred_finalization"
        or deployment_profile == "deferred_finalization"
    ):
        policy["source"] = deferred_finalization_source()
        details["guidance"] = (
            "deferred finalization is non-authoritative until a service imports it"
        )
    elif backend_kind in {"direct_database", "transitional_sqlite"}:
        policy["source"] = unavailable_authority_source(
            reason=f"unsupported_{backend_kind}",
            authority=authority,
        )
        details["guidance"] = (
            "select a service authority endpoint or explicit offline mode"
        )
    else:
        policy["source"] = authoritative_service_source(
            authority=authority,
        )
    return details


def _active_submission_source(context: _Context) -> dict[str, PlainData]:
    return authoritative_service_source(
        authority=redacted_authority_summary(context.authority_config())
    )


def _enum_value(value: object) -> str | None:
    raw = getattr(value, "value", value)
    if raw is None:
        return None
    return str(raw)


def _nearest_existing_directory(path: Path) -> Path:
    current = path if path.exists() else path.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    if not current.is_dir():
        raise NotADirectoryError(str(current))
    return current


def _request_selects_slurm_container(context: _Context) -> bool:
    try:
        options = cast(Any, context.runtime_options())
    except Exception:  # noqa: BLE001 - caller-specific checks report request failures.
        return False
    return _is_slurm_executor(options) and _runtime_options_include_container(options)


def _is_slurm_executor(options: object) -> bool:
    return getattr(options, "executor", None) in _SLURM_EXECUTORS


def _is_slurm_executor_name(executor: object) -> bool:
    return executor in _SLURM_EXECUTORS


def _runtime_options_include_container(options: object) -> bool:
    return _adapter_options_include_container(
        getattr(options, "adapter_options", None),
        getattr(options, "stage_options", None),
    )


def _adapter_options_include_container(
    adapter_options: object,
    stage_options: object,
) -> bool:
    if isinstance(adapter_options, Mapping) and "container" in adapter_options:
        return True
    if isinstance(stage_options, Mapping):
        for value in stage_options.values():
            raw_adapter_options = (
                value.get("adapter_options")
                if isinstance(value, Mapping)
                else getattr(value, "adapter_options", None)
            )
            if (
                isinstance(raw_adapter_options, Mapping)
                and "container" in raw_adapter_options
            ):
                return True
    return False


def _container_build_options_from_adapter(
    adapter_options: Mapping[str, object],
) -> object:
    from loom.pipeline.executors.containers import parse_container_build_options

    return parse_container_build_options(adapter_options.get("container_build"))


def _container_build_output_identity(output: object) -> str | None:
    if output is None:
        return None
    try:
        from loom.pipeline.executors.containers import container_build_output_identity

        return container_build_output_identity(cast(Any, output))
    except Exception:  # noqa: BLE001 - identity is best-effort diagnostic metadata.
        return None


def _apptainer_container_from_adapter(
    adapter_options: Mapping[str, object],
    *,
    allow_target_resolution: bool,
) -> object:
    from loom.pipeline.executors.containers import parse_container_options

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
    return parse_container_options(raw)


def _resolve_apptainer_preflight_target(
    adapter_options: Mapping[str, object],
    container: Mapping[str, object],
) -> Mapping[str, object]:
    from loom.pipeline.executors.containers import (
        ContainerBuildOutputKind,
        ContainerBuildRuntime,
    )

    target_name = container.get("target")
    if not isinstance(target_name, str) or not target_name:
        raise ValueError("adapter_options.container.target must be non-empty")
    build_options = _container_build_options_from_adapter(adapter_options)
    target = cast(Mapping[str, object], cast(Any, build_options).targets).get(
        target_name
    )
    if target is None:
        raise ValueError(f"container build target {target_name!r} is not defined")
    runtime = getattr(target, "runtime", None)
    output = getattr(target, "output", None)
    output_kind = getattr(output, "kind", None)
    if runtime is not ContainerBuildRuntime.APPTAINER:
        raise ValueError("Apptainer execution requires an apptainer build target")
    if output_kind is not ContainerBuildOutputKind.APPTAINER_SIF:
        raise ValueError("Apptainer execution requires an apptainer_sif output")
    identity = _container_build_output_identity(output)
    if identity is None:
        raise ValueError("Apptainer build target output has no image identity")
    resolved = dict(container)
    resolved.pop("target", None)
    resolved["image"] = {"reference": identity}
    return cast(Mapping[str, object], resolved)


def _apptainer_options_from_adapter(
    adapter_options: Mapping[str, object],
    *,
    executor_name: str,
) -> object:
    from loom.pipeline.executors.apptainer import ApptainerExecOptions

    raw_options: object | None
    if executor_name == "singularity":
        raw_options = adapter_options.get(
            "singularity",
            adapter_options.get("apptainer"),
        )
    else:
        raw_options = adapter_options.get("apptainer")
    options = ApptainerExecOptions.from_dict(raw_options)
    if executor_name == "singularity" and not _adapter_options_set_command(raw_options):
        return replace(options, command="singularity")
    return options


def _adapter_options_set_command(raw_options: object | None) -> bool:
    return isinstance(raw_options, Mapping) and "command" in raw_options


def _selected_resource_controls(
    target: _ApptainerPreflightRawTarget | _DockerPreflightRawTarget,
    entries: Mapping[str, object],
) -> tuple[str, ...]:
    from loom.pipeline.runtime.resource_policy import (
        ResourcePolicy,
        coerce_resource_policy,
    )

    policy = (
        ResourcePolicy()
        if target.resource_policy is None
        else coerce_resource_policy(target.resource_policy, path="resource_policy")
    )
    return policy.select(entries)["enforce"]


def _preflight_container_command(
    target: _ApptainerPreflightRawTarget | _DockerPreflightRawTarget,
    entries: Mapping[str, object],
) -> Any:
    """Inspect the same full-intent mapping as launch without running a command."""

    from dataclasses import replace

    from loom.pipeline.executors.apptainer import build_apptainer_exec_command
    from loom.pipeline.executors.containers import ContainerResourceIntent
    from loom.pipeline.executors.docker import build_docker_run_command

    apptainer = isinstance(target, _ApptainerPreflightRawTarget)
    executor = target.executor_name if apptainer else "docker"
    descriptor = _executor_descriptor(executor)
    intent = ContainerResourceIntent(
        entries=cast(Any, entries),
        capabilities={kind: descriptor.capability_for(kind) for kind in entries},
    )
    container = (
        _apptainer_container_from_adapter(
            target.adapter_options, allow_target_resolution=False
        )
        if apptainer
        else _docker_container_from_adapter(target.adapter_options)
    )
    container = replace(cast(Any, container), resources=intent)
    if apptainer:
        return build_apptainer_exec_command(
            container_options=container,
            apptainer_options=cast(
                Any,
                _apptainer_options_from_adapter(
                    target.adapter_options,
                    executor_name=executor,
                ),
            ),
            worker_command=("loom-preflight",),
            resource_policy=cast(Any, target.resource_policy),
        )
    return build_docker_run_command(
        container_options=container,
        docker_options=cast(Any, _docker_options_from_adapter(target.adapter_options)),
        worker_command=("loom-preflight",),
        resource_policy=cast(Any, target.resource_policy),
    )


def _executor_descriptor(executor_name: str) -> Any:
    from loom.pipeline.runtime.capabilities import DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY

    return DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.resolve(executor_name)


def _resource_amount(resource: object | None) -> float:
    if resource is None:
        return 0.0
    amount = getattr(resource, "amount", 0)
    if isinstance(amount, int | float) and not isinstance(amount, bool):
        return float(amount)
    return 0.0


def _local_reference_path(reference: str, *, cwd: str | Path | None) -> Path | None:
    if "://" in reference or reference.startswith(("docker:", "oras:", "library:")):
        return None
    if not (
        reference.startswith(("/", "."))
        or "/" in reference
        or reference.endswith((".sif", ".simg"))
    ):
        return None
    return _resolve_path(reference, cwd=cwd)


def _docker_container_from_adapter(adapter_options: Mapping[str, object]) -> object:
    from loom.pipeline.executors.containers import parse_container_options

    if "container" not in adapter_options:
        raise ValueError("adapter_options.container is required for Docker preflight")
    return parse_container_options(adapter_options["container"])


def _docker_options_from_adapter(adapter_options: Mapping[str, object]) -> object:
    from loom.pipeline.executors.docker.commands import DockerOptions

    return DockerOptions.from_dict(adapter_options.get("docker"))


def _resource_entries(resources: object | None) -> Mapping[str, object]:
    if resources is None:
        return {}
    entries = getattr(resources, "entries", None)
    if isinstance(entries, Mapping):
        return cast(Mapping[str, object], entries)
    return {}


def _selected_run_uri(context: _Context) -> str | None:
    explicit_run_uri = _explicit_runtime_run_uri(context.request.runtime_options)
    if explicit_run_uri is not None:
        return explicit_run_uri
    if context.request.run_uri is not None:
        return context.request.run_uri
    if context._runtime_options is not None:
        options = cast(Any, context.runtime_options())
        if options.run_uri is not None:
            return cast(str, options.run_uri)
    return None


def _explicit_runtime_run_uri(runtime_options: object | None) -> str | None:
    if isinstance(runtime_options, Mapping):
        value = runtime_options.get("run_uri")
        if value is None:
            return None
        return cast(str, value)
    value = getattr(runtime_options, "run_uri", None)
    if value is None:
        return None
    return cast(str, value)


def _request_runtime_source(request: PreflightRequest) -> object | None:
    if request.runtime_options is not None and not isinstance(
        request.runtime_options, Mapping
    ):
        return request.runtime_options
    source = dict(cast(Mapping[str, object], request.runtime_options or {}))
    if request.run_uri is not None and "run_uri" not in source:
        source["run_uri"] = request.run_uri
    if request.selectors is not None and "selectors" not in source:
        source["selectors"] = request.selectors
    return source or None


def _severity_for_status(status: PreflightCheckStatus) -> PreflightSeverity:
    if status is PreflightCheckStatus.FAIL:
        return PreflightSeverity.ERROR
    if status is PreflightCheckStatus.WARN:
        return PreflightSeverity.WARNING
    return PreflightSeverity.INFO


def _missing_run_uri(check_id: str, group: PreflightGroup) -> PreflightCheckResult:
    return _skip(
        check_id,
        group,
        "check skipped because RUN_URI was not provided",
        {"reason": "missing_run_uri", "requires": "RUN_URI"},
    )


def _skip(
    check_id: str,
    group: PreflightGroup,
    message: str,
    details: Mapping[str, PlainData],
) -> PreflightCheckResult:
    return _result(
        check_id,
        group,
        PreflightCheckStatus.SKIP,
        PreflightSeverity.INFO,
        message,
        details,
    )


def _fail(
    check_id: str, group: PreflightGroup, message: str, exc: BaseException
) -> PreflightCheckResult:
    return _result(
        check_id,
        group,
        PreflightCheckStatus.FAIL,
        PreflightSeverity.ERROR,
        message,
        {"error_type": type(exc).__name__, "error": str(exc)},
    )


def _result(
    check_id: str,
    group: PreflightGroup,
    status: PreflightCheckStatus,
    severity: PreflightSeverity,
    message: str,
    details: Mapping[str, PlainData],
) -> PreflightCheckResult:
    expected_ids = STABLE_CHECK_IDS[group]
    if check_id not in expected_ids:
        raise AssertionError(
            f"unexpected check ID {check_id!r} for group {group.value!r}"
        )
    return PreflightCheckResult(
        check_id=check_id,
        group=group,
        status=status,
        severity=severity,
        message=message,
        details=details,
    )


def _resolve_path(value: str | Path, *, cwd: str | Path | None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve(strict=False)
    root = Path.cwd() if cwd is None else Path(cwd)
    return (root / path).resolve(strict=False)
