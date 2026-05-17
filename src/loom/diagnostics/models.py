"""Preflight diagnostics result models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import cast

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError


class PreflightError(ValueError):
    """Raised when a preflight request is invalid."""


class PreflightCheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


class PreflightStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


class PreflightSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class PreflightGroup(StrEnum):
    CONFIG = "config"
    PIPELINE = "pipeline"
    SELECTORS = "selectors"
    RUNTIME = "runtime"
    RUN = "run"
    ARTIFACTS = "artifacts"
    CODECS = "codecs"
    EXECUTOR = "executor"
    RESOURCES = "resources"
    FILESYSTEM = "filesystem"
    PLUGINS = "plugins"


DEFAULT_PREFLIGHT_GROUPS: tuple[PreflightGroup, ...] = (
    PreflightGroup.CONFIG,
    PreflightGroup.PIPELINE,
    PreflightGroup.SELECTORS,
    PreflightGroup.RUNTIME,
    PreflightGroup.RUN,
    PreflightGroup.ARTIFACTS,
    PreflightGroup.CODECS,
    PreflightGroup.EXECUTOR,
    PreflightGroup.RESOURCES,
    PreflightGroup.FILESYSTEM,
)

OPTIONAL_PREFLIGHT_GROUPS: tuple[PreflightGroup, ...] = (
    PreflightGroup.PLUGINS,
)

ALL_PREFLIGHT_GROUPS: tuple[PreflightGroup, ...] = (
    *DEFAULT_PREFLIGHT_GROUPS,
    *OPTIONAL_PREFLIGHT_GROUPS,
)

STABLE_CHECK_IDS: Mapping[PreflightGroup, tuple[str, ...]] = {
    PreflightGroup.CONFIG: ("config.load",),
    PreflightGroup.PIPELINE: ("pipeline.graph",),
    PreflightGroup.SELECTORS: ("selectors.validate",),
    PreflightGroup.RUNTIME: (
        "runtime.options",
        "runtime.profile",
        "runtime.container_build.options",
        "runtime.slurm.options",
        "runtime.stage_options",
    ),
    PreflightGroup.RUN: (
        "run_uri.resolve",
        "run_uri.slurm.local",
        "run_uri.slurm.active_submission",
    ),
    PreflightGroup.ARTIFACTS: (
        "artifact_store.available",
        "artifact_backends.registry",
        "artifact_backends.handlers",
        "artifact_backends.capabilities",
        "artifact_backends.materialization",
    ),
    PreflightGroup.CODECS: ("codec_registry.available",),
    PreflightGroup.EXECUTOR: (
        "executor.local",
        "executor.resolve",
        "executor.capabilities",
        "executor.container_build.targets",
        "executor.apptainer.command",
        "executor.apptainer.container_options",
        "executor.apptainer.image",
        "executor.apptainer.environment",
        "executor.docker.command",
        "executor.docker.container_options",
        "executor.docker.image",
        "executor.docker.environment",
        "executor.slurm.mode",
        "executor.slurm.launcher",
        "executor.slurm.sbatch",
        "executor.slurm.squeue",
        "executor.slurm.sacct",
        "executor.slurm.scancel",
        "executor.subprocess.python",
        "executor.subprocess.worker",
    ),
    PreflightGroup.RESOURCES: (
        "resources.capabilities",
        "resources.slurm.mapping",
        "resources.slurm.container_compatibility",
        "resources.apptainer.mapping",
        "resources.apptainer.gpu",
        "resources.docker.mapping",
        "resources.docker.gpu",
    ),
    PreflightGroup.FILESYSTEM: (
        "filesystem.input_exists",
        "filesystem.container_build.sources",
        "filesystem.container_build.outputs",
        "filesystem.slurm.generated_paths",
        "filesystem.slurm.generated_writable",
        "filesystem.apptainer.bind_sources",
        "filesystem.apptainer.bind_targets",
        "filesystem.apptainer.run_dir_writable",
        "filesystem.apptainer.artifact_root_visible",
        "filesystem.docker.mount_sources",
        "filesystem.docker.mount_targets",
        "filesystem.docker.run_dir_writable",
        "filesystem.docker.artifact_root_visible",
    ),
    PreflightGroup.PLUGINS: ("plugins.metadata", "plugins.load"),
}


@dataclass(frozen=True, slots=True)
class PreflightCheckResult:
    check_id: str
    group: PreflightGroup
    status: PreflightCheckStatus
    severity: PreflightSeverity
    message: str
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        check_id = _non_empty_str(self.check_id, field="check_id")
        message = _non_empty_str(self.message, field="message")
        group = _coerce_group(self.group)
        status = _coerce_check_status(self.status)
        severity = _coerce_severity(self.severity)
        details = _plain_mapping(self.details, field="details")
        object.__setattr__(self, "check_id", check_id)
        object.__setattr__(self, "group", group)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "details", details)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "check_id": self.check_id,
            "group": self.group.value,
            "status": self.status.value,
            "severity": self.severity.value,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class PreflightResult:
    checks: tuple[PreflightCheckResult, ...]
    groups: tuple[PreflightGroup, ...]
    status: PreflightStatus = field(init=False)

    def __post_init__(self) -> None:
        checks = tuple(self.checks)
        groups = tuple(_coerce_group(group) for group in self.groups)
        for index, check in enumerate(checks):
            if not isinstance(check, PreflightCheckResult):
                raise PreflightError(
                    f"checks[{index}] must be a PreflightCheckResult"
                )
        object.__setattr__(self, "checks", checks)
        object.__setattr__(self, "groups", groups)
        object.__setattr__(self, "status", aggregate_status(checks))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "status": self.status.value,
            "groups": [group.value for group in self.groups],
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True, slots=True)
class ArtifactBackendPreflightTarget:
    """Explicit metadata-only artifact-backend preflight target."""

    target_id: str
    store: object
    required_operations: Iterable[str] = ()
    config: Mapping[str, PlainData] = field(default_factory=dict)
    run_context: Mapping[str, PlainData] = field(default_factory=dict)
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "target_id", _non_empty_str(self.target_id, field="target_id")
        )
        if self.store is None:
            raise PreflightError("store must not be None")
        object.__setattr__(
            self,
            "required_operations",
            _str_tuple(tuple(self.required_operations), "required_operations"),
        )
        object.__setattr__(self, "config", _plain_mapping(self.config, field="config"))
        object.__setattr__(
            self,
            "run_context",
            _plain_mapping(self.run_context, field="run_context"),
        )
        object.__setattr__(
            self, "details", _plain_mapping(self.details, field="details")
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "target_id": self.target_id,
            "store": _object_summary(self.store),
            "required_operations": list(self.required_operations),
            "config": dict(self.config),
            "run_context": dict(self.run_context),
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class PreflightRequest:
    config_path: str | Path
    groups: Iterable[str | PreflightGroup] | None = None
    run_uri: str | None = None
    cwd: str | Path | None = None
    overlays: tuple[str | Path, ...] = ()
    overrides: tuple[str, ...] = ()
    selectors: object | None = None
    runtime_options: object | None = None
    authority_config: object | None = None
    authority_mode: object | None = None
    plugin_groups: tuple[str, ...] = ()
    plugin_names: tuple[str, ...] = ()
    plugin_packages: tuple[str, ...] = ()
    artifact_backend_targets: tuple[ArtifactBackendPreflightTarget, ...] = ()
    artifact_backend_registry: object | None = None
    artifact_backend_handlers: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "config_path", _path_like(self.config_path, "config_path"))
        object.__setattr__(self, "cwd", None if self.cwd is None else _path_like(self.cwd, "cwd"))
        object.__setattr__(self, "overlays", _path_tuple(self.overlays, "overlays"))
        object.__setattr__(self, "overrides", _str_tuple(self.overrides, "overrides"))
        if self.run_uri is not None:
            object.__setattr__(self, "run_uri", _non_empty_str(self.run_uri, field="run_uri"))
        if self.groups is not None:
            object.__setattr__(self, "groups", tuple(self.groups))
        object.__setattr__(self, "plugin_groups", _str_tuple(self.plugin_groups, "plugin_groups"))
        object.__setattr__(self, "plugin_names", _str_tuple(self.plugin_names, "plugin_names"))
        object.__setattr__(
            self,
            "plugin_packages",
            _str_tuple(self.plugin_packages, "plugin_packages"),
        )
        object.__setattr__(
            self,
            "artifact_backend_targets",
            _artifact_backend_targets(self.artifact_backend_targets),
        )
        object.__setattr__(
            self,
            "artifact_backend_handlers",
            _object_mapping(self.artifact_backend_handlers, "artifact_backend_handlers"),
        )


def normalize_groups(
    groups: Iterable[str | PreflightGroup] | None,
) -> tuple[PreflightGroup, ...]:
    if groups is None:
        return DEFAULT_PREFLIGHT_GROUPS
    selected = tuple(groups)
    if not selected:
        raise PreflightError("preflight groups may not be empty")

    normalized: set[PreflightGroup] = set()
    unknown: list[str] = []
    for raw in selected:
        try:
            normalized.add(_coerce_group(raw))
        except PreflightError:
            unknown.append(str(raw))
    if unknown:
        names = ", ".join(sorted(unknown))
        allowed = ", ".join(group.value for group in ALL_PREFLIGHT_GROUPS)
        raise PreflightError(f"unknown preflight group(s): {names}; expected one of: {allowed}")

    return tuple(group for group in ALL_PREFLIGHT_GROUPS if group in normalized)


def aggregate_status(checks: Iterable[PreflightCheckResult]) -> PreflightStatus:
    statuses = tuple(check.status for check in checks)
    if any(status is PreflightCheckStatus.FAIL for status in statuses):
        return PreflightStatus.FAIL
    if any(status is PreflightCheckStatus.WARN for status in statuses):
        return PreflightStatus.WARN
    if any(status is PreflightCheckStatus.PASS for status in statuses):
        return PreflightStatus.PASS
    return PreflightStatus.SKIP


def _coerce_group(value: str | PreflightGroup) -> PreflightGroup:
    if isinstance(value, PreflightGroup):
        return value
    if isinstance(value, str):
        try:
            return PreflightGroup(value)
        except ValueError as exc:
            raise PreflightError(f"unknown preflight group: {value!r}") from exc
    raise PreflightError(f"preflight group must be a string or PreflightGroup, got {type(value)!r}")


def _coerce_check_status(value: str | PreflightCheckStatus) -> PreflightCheckStatus:
    if isinstance(value, PreflightCheckStatus):
        return value
    try:
        return PreflightCheckStatus(value)
    except ValueError as exc:
        raise PreflightError(f"unknown preflight check status: {value!r}") from exc


def _coerce_severity(value: str | PreflightSeverity) -> PreflightSeverity:
    if isinstance(value, PreflightSeverity):
        return value
    try:
        return PreflightSeverity(value)
    except ValueError as exc:
        raise PreflightError(f"unknown preflight severity: {value!r}") from exc


def _non_empty_str(value: object, *, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise PreflightError(f"{field} must be a non-empty string")
    return value


def _artifact_backend_targets(
    values: Iterable[ArtifactBackendPreflightTarget],
) -> tuple[ArtifactBackendPreflightTarget, ...]:
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise PreflightError("artifact_backend_targets must be a sequence")
    output: list[ArtifactBackendPreflightTarget] = []
    for index, value in enumerate(values):
        if not isinstance(value, ArtifactBackendPreflightTarget):
            raise PreflightError(
                "artifact_backend_targets"
                f"[{index}] must be ArtifactBackendPreflightTarget"
            )
        output.append(value)
    return tuple(output)


def _object_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PreflightError(f"{field} must be a mapping")
    output: dict[str, object] = {}
    for key, item in value.items():
        output[_non_empty_str(key, field=f"{field} key")] = item
    return MappingProxyType(output)


def _object_summary(value: object) -> PlainData:
    if isinstance(value, Mapping):
        summary = dict(value)
    elif hasattr(value, "to_summary"):
        summary = getattr(value, "to_summary")()
    elif hasattr(value, "to_dict"):
        summary = getattr(value, "to_dict")()
    else:
        summary = {"type": type(value).__name__}
    try:
        return ensure_plain_data(summary, path="store")
    except PlainDataError as exc:
        raise PreflightError(f"store summary must be plain data: {exc}") from exc


def _plain_mapping(value: Mapping[str, PlainData], *, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(dict(value), path=field)
    except PlainDataError as exc:
        raise PreflightError(f"{field} must be a plain-data mapping: {exc}") from exc
    if not isinstance(normalized, dict):
        raise PreflightError(f"{field} must be a plain-data mapping")
    return cast(Mapping[str, PlainData], normalized)


def _path_like(value: object, field: str) -> str | Path:
    if not isinstance(value, (str, Path)):
        raise PreflightError(f"{field} must be a string or Path")
    if isinstance(value, str) and value == "":
        raise PreflightError(f"{field} must be non-empty")
    return value


def _path_tuple(values: tuple[str | Path, ...], field: str) -> tuple[str | Path, ...]:
    if values is None:
        raise PreflightError(f"{field} may not be None")
    return tuple(_path_like(value, f"{field}[{index}]") for index, value in enumerate(values))


def _str_tuple(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if values is None:
        raise PreflightError(f"{field} may not be None")
    return tuple(_non_empty_str(value, field=f"{field}[{index}]") for index, value in enumerate(values))


__all__ = [
    "ArtifactBackendPreflightTarget",
    "DEFAULT_PREFLIGHT_GROUPS",
    "ALL_PREFLIGHT_GROUPS",
    "OPTIONAL_PREFLIGHT_GROUPS",
    "STABLE_CHECK_IDS",
    "PreflightCheckResult",
    "PreflightCheckStatus",
    "PreflightError",
    "PreflightGroup",
    "PreflightRequest",
    "PreflightResult",
    "PreflightSeverity",
    "PreflightStatus",
    "aggregate_status",
    "normalize_groups",
]
