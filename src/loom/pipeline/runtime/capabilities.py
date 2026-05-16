"""Executor descriptor and runtime capability validation contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from loom.serialization import (
    PlainData,
    ensure_plain_data,
    freeze_plain_data,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import ResourceRequest, validate_resource_kind
from loom.pipeline.runtime.options import (
    RunOptions,
    StageRuntimeOptions,
    parse_run_options,
)
from loom.pipeline.reliability import (
    ReliabilityPolicy,
    TimeoutPolicy,
    TimeoutSupportLevel,
)


class ResourceSupportLevel(StrEnum):
    SUPPORTED = "supported"
    ADVISORY = "advisory"
    IGNORED = "ignored"
    UNSUPPORTED = "unsupported"


class ResourceEnforcementExpectation(StrEnum):
    ENFORCED = "enforced"
    BEST_EFFORT = "best_effort"
    NOT_ENFORCED = "not_enforced"
    NOT_APPLICABLE = "not_applicable"


class CapabilitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ResourceCapability:
    """Per-resource-kind support policy for an executor descriptor."""

    support_level: ResourceSupportLevel | str
    enforcement: ResourceEnforcementExpectation | str | None = None
    severity: CapabilitySeverity | str | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        support_level = _coerce_support_level(
            self.support_level,
            path="ResourceCapability.support_level",
        )
        object.__setattr__(self, "support_level", support_level)
        object.__setattr__(
            self,
            "enforcement",
            _coerce_enforcement(
                self.enforcement,
                path="ResourceCapability.enforcement",
                support_level=support_level,
            ),
        )
        object.__setattr__(
            self,
            "severity",
            _coerce_severity(
                self.severity,
                path="ResourceCapability.severity",
                support_level=support_level,
            ),
        )
        object.__setattr__(
            self,
            "details",
            _freeze_plain_mapping(self.details, path="ResourceCapability.details"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "support_level": cast(ResourceSupportLevel, self.support_level).value,
            "enforcement": cast(ResourceEnforcementExpectation, self.enforcement).value,
            "severity": cast(CapabilitySeverity, self.severity).value,
            "details": _thaw_mapping(
                self.details,
                path="ResourceCapability.details",
            ),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ResourceCapability":
        mapping = _object_mapping(data, path="ResourceCapability")
        _reject_unknown(
            mapping,
            allowed=frozenset({"support_level", "enforcement", "severity", "details"}),
            path="ResourceCapability",
        )
        if "support_level" not in mapping:
            raise RuntimeResourceError(
                "ResourceCapability missing required field(s): support_level"
            )
        return cls(
            support_level=cast(str, mapping["support_level"]),
            enforcement=cast(str | None, mapping.get("enforcement")),
            severity=cast(str | None, mapping.get("severity")),
            details=_plain_mapping(
                mapping.get("details", {}),
                path="ResourceCapability.details",
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutorDescriptor:
    """Import-light metadata for one executor name."""

    name: str
    resource_capabilities: Mapping[str, ResourceCapability | Mapping[str, object]] = (
        field(default_factory=dict)
    )
    adapter_namespaces: Iterable[str] | Mapping[str, object] = ()
    timeout_support: TimeoutSupportLevel | str = TimeoutSupportLevel.UNSUPPORTED
    details: Mapping[str, PlainData] = field(default_factory=dict)
    unknown_resource_capability: ResourceCapability | Mapping[str, object] = field(
        default_factory=lambda: ResourceCapability(
            support_level=ResourceSupportLevel.UNSUPPORTED,
            enforcement=ResourceEnforcementExpectation.NOT_APPLICABLE,
            severity=CapabilitySeverity.ERROR,
        )
    )

    def __post_init__(self) -> None:
        name = _normalize_executor_name(self.name, path="ExecutorDescriptor.name")
        object.__setattr__(self, "name", name)
        object.__setattr__(
            self,
            "resource_capabilities",
            _coerce_resource_capabilities(
                self.resource_capabilities,
                path=f"ExecutorDescriptor[{name!r}].resource_capabilities",
            ),
        )
        object.__setattr__(
            self,
            "adapter_namespaces",
            _adapter_namespace_tuple(
                self.adapter_namespaces,
                path=f"ExecutorDescriptor[{name!r}].adapter_namespaces",
            ),
        )
        object.__setattr__(
            self,
            "timeout_support",
            _coerce_timeout_support(
                self.timeout_support,
                path=f"ExecutorDescriptor[{name!r}].timeout_support",
            ),
        )
        object.__setattr__(
            self,
            "details",
            _freeze_plain_mapping(
                self.details, path=f"ExecutorDescriptor[{name!r}].details"
            ),
        )
        object.__setattr__(
            self,
            "unknown_resource_capability",
            _coerce_resource_capability(
                self.unknown_resource_capability,
                path=f"ExecutorDescriptor[{name!r}].unknown_resource_capability",
            ),
        )

    def capability_for(self, resource_kind: str) -> ResourceCapability:
        kind = validate_resource_kind(resource_kind, path="resource capability kind")
        return cast(
            ResourceCapability,
            self.resource_capabilities.get(kind, self.unknown_resource_capability),
        )

    def claims_adapter_namespace(self, namespace: str) -> bool:
        return namespace in cast(tuple[str, ...], self.adapter_namespaces)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "name": self.name,
            "resource_capabilities": {
                kind: capability.to_dict()
                for kind, capability in cast(
                    Mapping[str, ResourceCapability],
                    self.resource_capabilities,
                ).items()
            },
            "adapter_namespaces": list(cast(tuple[str, ...], self.adapter_namespaces)),
            "timeout_support": cast(TimeoutSupportLevel, self.timeout_support).value,
            "details": _thaw_mapping(
                self.details,
                path=f"ExecutorDescriptor[{self.name!r}].details",
            ),
            "unknown_resource_capability": cast(
                ResourceCapability,
                self.unknown_resource_capability,
            ).to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ExecutorDescriptor":
        mapping = _object_mapping(data, path="ExecutorDescriptor")
        _reject_unknown(
            mapping,
            allowed=frozenset(
                {
                    "name",
                    "resource_capabilities",
                    "adapter_namespaces",
                    "timeout_support",
                    "details",
                    "unknown_resource_capability",
                }
            ),
            path="ExecutorDescriptor",
        )
        if "name" not in mapping:
            raise RuntimeResourceError(
                "ExecutorDescriptor missing required field(s): name"
            )
        return cls(
            name=_string_value(mapping["name"], path="ExecutorDescriptor.name"),
            resource_capabilities=cast(
                Mapping[str, ResourceCapability | Mapping[str, object]],
                _object_mapping(
                    mapping.get("resource_capabilities", {}),
                    path="ExecutorDescriptor.resource_capabilities",
                ),
            ),
            adapter_namespaces=cast(
                Sequence[str],
                mapping.get("adapter_namespaces", ()),
            ),
            timeout_support=_coerce_timeout_support(
                mapping.get("timeout_support", TimeoutSupportLevel.UNSUPPORTED.value),
                path="ExecutorDescriptor.timeout_support",
            ),
            details=_plain_mapping(
                mapping.get("details", {}),
                path="ExecutorDescriptor.details",
            ),
            unknown_resource_capability=cast(
                ResourceCapability | Mapping[str, object],
                mapping.get(
                    "unknown_resource_capability",
                    ResourceCapability(
                        support_level=ResourceSupportLevel.UNSUPPORTED,
                        enforcement=ResourceEnforcementExpectation.NOT_APPLICABLE,
                        severity=CapabilitySeverity.ERROR,
                    ),
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class CapabilityDiagnostic:
    """One runtime capability validation finding."""

    path: str
    severity: CapabilitySeverity | str
    code: str
    message: str
    executor: str | None = None
    stage_id: str | None = None
    resource_kind: str | None = None
    adapter_namespace: str | None = None
    support_level: ResourceSupportLevel | str | None = None
    enforcement: ResourceEnforcementExpectation | str | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "path", _string_value(self.path, path="CapabilityDiagnostic.path")
        )
        object.__setattr__(
            self,
            "severity",
            _coerce_diagnostic_severity(
                self.severity,
                path="CapabilityDiagnostic.severity",
            ),
        )
        object.__setattr__(
            self, "code", _string_value(self.code, path="CapabilityDiagnostic.code")
        )
        object.__setattr__(
            self,
            "message",
            _string_value(self.message, path="CapabilityDiagnostic.message"),
        )
        object.__setattr__(
            self,
            "executor",
            _optional_string(self.executor, path="CapabilityDiagnostic.executor"),
        )
        object.__setattr__(
            self,
            "stage_id",
            _optional_string(self.stage_id, path="CapabilityDiagnostic.stage_id"),
        )
        object.__setattr__(
            self,
            "resource_kind",
            _optional_resource_kind(
                self.resource_kind,
                path="CapabilityDiagnostic.resource_kind",
            ),
        )
        object.__setattr__(
            self,
            "adapter_namespace",
            _optional_string(
                self.adapter_namespace,
                path="CapabilityDiagnostic.adapter_namespace",
            ),
        )
        object.__setattr__(
            self,
            "support_level",
            _optional_support_level(
                self.support_level,
                path="CapabilityDiagnostic.support_level",
            ),
        )
        object.__setattr__(
            self,
            "enforcement",
            _optional_enforcement(
                self.enforcement,
                path="CapabilityDiagnostic.enforcement",
            ),
        )
        object.__setattr__(
            self,
            "details",
            _freeze_plain_mapping(self.details, path="CapabilityDiagnostic.details"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        support_level = cast(ResourceSupportLevel | None, self.support_level)
        enforcement = cast(ResourceEnforcementExpectation | None, self.enforcement)
        return {
            "path": self.path,
            "severity": cast(CapabilitySeverity, self.severity).value,
            "code": self.code,
            "message": self.message,
            "executor": self.executor,
            "stage_id": self.stage_id,
            "resource_kind": self.resource_kind,
            "adapter_namespace": self.adapter_namespace,
            "support_level": None if support_level is None else support_level.value,
            "enforcement": None if enforcement is None else enforcement.value,
            "details": _thaw_mapping(self.details, path="CapabilityDiagnostic.details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CapabilityDiagnostic":
        mapping = _object_mapping(data, path="CapabilityDiagnostic")
        _reject_unknown(
            mapping,
            allowed=frozenset(
                {
                    "path",
                    "severity",
                    "code",
                    "message",
                    "executor",
                    "stage_id",
                    "resource_kind",
                    "adapter_namespace",
                    "support_level",
                    "enforcement",
                    "details",
                }
            ),
            path="CapabilityDiagnostic",
        )
        required = {"path", "severity", "code", "message"}
        missing = required - set(mapping)
        if missing:
            fields = ", ".join(sorted(missing))
            raise RuntimeResourceError(
                f"CapabilityDiagnostic missing required field(s): {fields}"
            )
        return cls(
            path=_string_value(mapping["path"], path="CapabilityDiagnostic.path"),
            severity=cast(str, mapping["severity"]),
            code=_string_value(mapping["code"], path="CapabilityDiagnostic.code"),
            message=_string_value(
                mapping["message"], path="CapabilityDiagnostic.message"
            ),
            executor=cast(str | None, mapping.get("executor")),
            stage_id=cast(str | None, mapping.get("stage_id")),
            resource_kind=cast(str | None, mapping.get("resource_kind")),
            adapter_namespace=cast(str | None, mapping.get("adapter_namespace")),
            support_level=cast(str | None, mapping.get("support_level")),
            enforcement=cast(str | None, mapping.get("enforcement")),
            details=_plain_mapping(
                mapping.get("details", {}),
                path="CapabilityDiagnostic.details",
            ),
        )


@dataclass(frozen=True, slots=True)
class CapabilityValidationResult:
    """Deterministic runtime capability validation result."""

    diagnostics: Sequence[CapabilityDiagnostic | Mapping[str, object]] = ()

    def __post_init__(self) -> None:
        diagnostics = tuple(
            diagnostic
            if isinstance(diagnostic, CapabilityDiagnostic)
            else CapabilityDiagnostic.from_dict(diagnostic)
            for diagnostic in self.diagnostics
        )
        object.__setattr__(
            self, "diagnostics", tuple(sorted(diagnostics, key=_diagnostic_sort_key))
        )

    @property
    def has_errors(self) -> bool:
        return any(
            diagnostic.severity is CapabilitySeverity.ERROR
            for diagnostic in cast(tuple[CapabilityDiagnostic, ...], self.diagnostics)
        )

    @property
    def ok(self) -> bool:
        return not self.has_errors

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "ok": self.ok,
            "has_errors": self.has_errors,
            "diagnostics": [
                diagnostic.to_dict()
                for diagnostic in cast(
                    tuple[CapabilityDiagnostic, ...], self.diagnostics
                )
            ],
        }

    def raise_for_errors(self) -> None:
        errors = [
            diagnostic
            for diagnostic in cast(tuple[CapabilityDiagnostic, ...], self.diagnostics)
            if diagnostic.severity is CapabilitySeverity.ERROR
        ]
        if not errors:
            return
        summary = "; ".join(
            f"{diagnostic.code} at {diagnostic.path}: {diagnostic.message}"
            for diagnostic in errors
        )
        raise RuntimeResourceError(f"capability validation failed: {summary}")


@dataclass(frozen=True, slots=True)
class ExecutorDescriptorRegistry:
    """Immutable explicit executor descriptor registry."""

    descriptors: Mapping[str, ExecutorDescriptor | Mapping[str, object]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        normalized: dict[str, ExecutorDescriptor] = {}
        for key, value in self.descriptors.items():
            lookup_name = _normalize_executor_name(
                key,
                path=f"ExecutorDescriptorRegistry[{key!r}]",
            )
            descriptor = (
                value
                if isinstance(value, ExecutorDescriptor)
                else ExecutorDescriptor.from_dict(value)
            )
            if descriptor.name != lookup_name:
                raise RuntimeResourceError(
                    f"ExecutorDescriptorRegistry[{key!r}] key must match descriptor name"
                )
            if lookup_name in normalized:
                raise RuntimeResourceError(
                    f"executor descriptor already registered for name {lookup_name!r}"
                )
            normalized[lookup_name] = descriptor
        object.__setattr__(
            self,
            "descriptors",
            MappingProxyType(dict(sorted(normalized.items()))),
        )

    def get(self, name: str | None) -> ExecutorDescriptor | None:
        lookup_name = _selected_executor_name(name)
        return cast(Mapping[str, ExecutorDescriptor], self.descriptors).get(lookup_name)

    def resolve(self, name: str | None) -> ExecutorDescriptor:
        lookup_name = _selected_executor_name(name)
        descriptor = cast(Mapping[str, ExecutorDescriptor], self.descriptors).get(
            lookup_name
        )
        if descriptor is None:
            raise RuntimeResourceError(f"unknown executor {lookup_name!r}")
        return descriptor

    def with_descriptor(
        self, descriptor: ExecutorDescriptor
    ) -> "ExecutorDescriptorRegistry":
        if not isinstance(descriptor, ExecutorDescriptor):
            raise RuntimeResourceError(
                "ExecutorDescriptorRegistry.with_descriptor requires an ExecutorDescriptor"
            )
        if descriptor.name in self.descriptors:
            raise RuntimeResourceError(
                f"executor descriptor already registered for name {descriptor.name!r}"
            )
        return ExecutorDescriptorRegistry(
            {**self.descriptors, descriptor.name: descriptor}
        )

    def compose(
        self,
        *registries: "ExecutorDescriptorRegistry",
    ) -> "ExecutorDescriptorRegistry":
        composed = self
        for registry in registries:
            if not isinstance(registry, ExecutorDescriptorRegistry):
                raise RuntimeResourceError(
                    "ExecutorDescriptorRegistry.compose requires ExecutorDescriptorRegistry instances"
                )
            for descriptor in cast(
                Mapping[str, ExecutorDescriptor], registry.descriptors
            ).values():
                composed = composed.with_descriptor(descriptor)
        return composed

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "descriptors": {
                name: descriptor.to_dict()
                for name, descriptor in cast(
                    Mapping[str, ExecutorDescriptor],
                    self.descriptors,
                ).items()
            }
        }

    @classmethod
    def from_dict(cls, data: object) -> "ExecutorDescriptorRegistry":
        mapping = _object_mapping(data, path="ExecutorDescriptorRegistry")
        _reject_unknown(
            mapping,
            allowed=frozenset({"descriptors"}),
            path="ExecutorDescriptorRegistry",
        )
        return cls(
            descriptors=cast(
                Mapping[str, ExecutorDescriptor | Mapping[str, object]],
                _object_mapping(
                    mapping.get("descriptors", {}),
                    path="ExecutorDescriptorRegistry.descriptors",
                ),
            )
        )


def resolve_executor_descriptor(
    executor: RunOptions | str | None = None,
    *,
    registry: ExecutorDescriptorRegistry | None = None,
) -> ExecutorDescriptor:
    descriptor_registry = _coerce_registry(registry)
    return descriptor_registry.resolve(
        executor.executor if isinstance(executor, RunOptions) else executor
    )


def validate_executor_capabilities(
    options: RunOptions | Mapping[str, object] | None = None,
    *,
    registry: ExecutorDescriptorRegistry | None = None,
) -> CapabilityValidationResult:
    run_options = (
        options if isinstance(options, RunOptions) else parse_run_options(options)
    )
    descriptor_registry = _coerce_registry(registry)
    try:
        executor_name = _selected_executor_name(run_options.executor)
    except RuntimeResourceError:
        return _unknown_executor_result(
            executor_name=run_options.executor,
            message="selected executor name must be a non-empty string after stripping",
        )
    descriptor = descriptor_registry.get(executor_name)
    if descriptor is None:
        return _unknown_executor_result(
            executor_name=executor_name,
            message=f"executor {executor_name!r} is not registered",
        )

    diagnostics: list[CapabilityDiagnostic] = []
    diagnostics.extend(_adapter_namespace_diagnostics(run_options, descriptor))
    diagnostics.extend(_reliability_capability_diagnostics(run_options, descriptor))
    diagnostics.extend(_resource_capability_diagnostics(run_options, descriptor))
    return CapabilityValidationResult(diagnostics)


def _unknown_executor_result(
    *,
    executor_name: str | None,
    message: str,
) -> CapabilityValidationResult:
    normalized_name = None if executor_name is None else executor_name.strip() or None
    return CapabilityValidationResult(
        [
            CapabilityDiagnostic(
                path="RunOptions.executor",
                severity=CapabilitySeverity.ERROR,
                code="executor.unknown",
                message=message,
                executor=normalized_name,
            )
        ]
    )


def _local_descriptor() -> ExecutorDescriptor:
    ignored = ResourceCapability(
        support_level=ResourceSupportLevel.IGNORED,
        enforcement=ResourceEnforcementExpectation.NOT_ENFORCED,
        severity=CapabilitySeverity.WARNING,
        details={
            "reason": "local executor records resource requests but does not enforce them"
        },
    )
    return ExecutorDescriptor(
        name="local",
        resource_capabilities={
            "cpu": ignored,
            "memory": ignored,
            "gpu": ignored,
        },
        adapter_namespaces=(),
        timeout_support=TimeoutSupportLevel.UNSUPPORTED,
        details={"built_in": True},
    )


def _subprocess_descriptor() -> ExecutorDescriptor:
    ignored = ResourceCapability(
        support_level=ResourceSupportLevel.IGNORED,
        enforcement=ResourceEnforcementExpectation.NOT_ENFORCED,
        severity=CapabilitySeverity.WARNING,
        details={
            "reason": "subprocess executor records resource requests but does not enforce them"
        },
    )
    return ExecutorDescriptor(
        name="subprocess",
        resource_capabilities={
            "cpu": ignored,
            "memory": ignored,
            "gpu": ignored,
        },
        adapter_namespaces=(),
        timeout_support=TimeoutSupportLevel.ENFORCED,
        details={"built_in": True, "process_isolating": True, "serial": True},
    )


def _slurm_descriptor(name: str) -> ExecutorDescriptor:
    supported = ResourceCapability(
        support_level=ResourceSupportLevel.SUPPORTED,
        enforcement=ResourceEnforcementExpectation.ENFORCED,
        severity=CapabilitySeverity.INFO,
        details={"reason": "SLURM planning maps this resource to SBATCH directives"},
    )
    return ExecutorDescriptor(
        name=name,
        resource_capabilities={
            "cpu": supported,
            "memory": supported,
            "gpu": supported,
        },
        adapter_namespaces=("slurm",),
        timeout_support=TimeoutSupportLevel.DELEGATED,
        details={
            "built_in": True,
            "dry_run_only": False,
            "live_submission": True,
            "scheduler_commands": True,
        },
    )


def _docker_descriptor() -> ExecutorDescriptor:
    mapped = ResourceCapability(
        support_level=ResourceSupportLevel.SUPPORTED,
        enforcement=ResourceEnforcementExpectation.BEST_EFFORT,
        severity=CapabilitySeverity.INFO,
        details={
            "reason": (
                "Docker command construction maps this resource to Docker CLI flags; "
                "daemon and platform enforcement can vary"
            )
        },
    )
    gpu = ResourceCapability(
        support_level=ResourceSupportLevel.UNSUPPORTED,
        enforcement=ResourceEnforcementExpectation.NOT_APPLICABLE,
        severity=CapabilitySeverity.ERROR,
        details={"reason": "GPU mapping is deferred beyond Stage 17"},
    )
    return ExecutorDescriptor(
        name="docker",
        resource_capabilities={
            "cpu": mapped,
            "memory": mapped,
            "gpu": gpu,
        },
        adapter_namespaces=("container", "docker"),
        timeout_support=TimeoutSupportLevel.UNSUPPORTED,
        details={
            "built_in": True,
            "containerized": True,
            "docker_cli": True,
            "docker_sdk_dependency": False,
            "security_sandbox": False,
            "requires_prepared_worker_request": True,
        },
    )


def _reliability_capability_diagnostics(
    options: RunOptions,
    descriptor: ExecutorDescriptor,
) -> list[CapabilityDiagnostic]:
    diagnostics: list[CapabilityDiagnostic] = []
    diagnostics.extend(
        _reliability_policy_diagnostics(
            path="RunOptions.reliability",
            executor=descriptor.name,
            stage_id=None,
            policy=cast(ReliabilityPolicy | None, options.reliability),
            timeout_support=cast(TimeoutSupportLevel, descriptor.timeout_support),
        )
    )
    for stage_id, stage_options in cast(
        Mapping[str, StageRuntimeOptions],
        options.stage_options,
    ).items():
        diagnostics.extend(
            _reliability_policy_diagnostics(
                path=f"RunOptions.stage_options[{stage_id!r}].reliability",
                executor=descriptor.name,
                stage_id=stage_id,
                policy=cast(ReliabilityPolicy | None, stage_options.reliability),
                timeout_support=cast(TimeoutSupportLevel, descriptor.timeout_support),
            )
        )
    return diagnostics


def _reliability_policy_diagnostics(
    *,
    path: str,
    executor: str,
    stage_id: str | None,
    policy: ReliabilityPolicy | None,
    timeout_support: TimeoutSupportLevel,
) -> list[CapabilityDiagnostic]:
    if policy is None:
        return []
    diagnostics: list[CapabilityDiagnostic] = []
    retry = policy.retry
    if retry is not None and retry.enabled:
        diagnostics.append(
            CapabilityDiagnostic(
                path=f"{path}.retry",
                severity=CapabilitySeverity.INFO,
                code="reliability.retry.runner_owned",
                message=(
                    "runner-owned retry policy will persist decisions before "
                    "scheduling another attempt"
                ),
                executor=executor,
                stage_id=stage_id,
                details={
                    "max_attempts": retry.max_attempts,
                    "retry_domain": "reliability",
                },
            )
        )
    timeout = policy.timeout
    if timeout is not None and timeout.enabled:
        diagnostics.append(
            _timeout_capability_diagnostic(
                path=f"{path}.timeout",
                executor=executor,
                stage_id=stage_id,
                policy=timeout,
                timeout_support=timeout_support,
            )
        )
    return diagnostics


def _timeout_capability_diagnostic(
    *,
    path: str,
    executor: str,
    stage_id: str | None,
    policy: TimeoutPolicy,
    timeout_support: TimeoutSupportLevel,
) -> CapabilityDiagnostic:
    severity = (
        CapabilitySeverity.WARNING
        if timeout_support is TimeoutSupportLevel.UNSUPPORTED
        else CapabilitySeverity.INFO
    )
    return CapabilityDiagnostic(
        path=path,
        severity=severity,
        code=f"reliability.timeout.{timeout_support.value}",
        message=_timeout_capability_message(
            executor=executor,
            timeout_support=timeout_support,
        ),
        executor=executor,
        stage_id=stage_id,
        details={
            "duration_seconds": policy.duration_seconds,
            "timeout_support": timeout_support.value,
            "timeout_domain": "reliability",
        },
    )


def _timeout_capability_message(
    *,
    executor: str,
    timeout_support: TimeoutSupportLevel,
) -> str:
    if timeout_support is TimeoutSupportLevel.ENFORCED:
        return f"executor {executor!r} can enforce reliability timeout policy"
    if timeout_support is TimeoutSupportLevel.DELEGATED:
        return f"executor {executor!r} delegates reliability timeout policy"
    if timeout_support is TimeoutSupportLevel.OBSERVED:
        return f"executor {executor!r} can observe reliability timeout outcomes"
    return f"executor {executor!r} does not support reliability timeout policy"


def _adapter_namespace_diagnostics(
    options: RunOptions,
    descriptor: ExecutorDescriptor,
) -> list[CapabilityDiagnostic]:
    diagnostics: list[CapabilityDiagnostic] = []
    for namespace in sorted(options.adapter_options):
        if descriptor.claims_adapter_namespace(namespace):
            continue
        diagnostics.append(
            _adapter_namespace_diagnostic(
                path=f"RunOptions.adapter_options[{namespace!r}]",
                namespace=namespace,
                executor=descriptor.name,
                stage_id=None,
            )
        )
    for stage_id, stage_options in cast(
        Mapping[str, StageRuntimeOptions],
        options.stage_options,
    ).items():
        for namespace in sorted(stage_options.adapter_options):
            if descriptor.claims_adapter_namespace(namespace):
                continue
            diagnostics.append(
                _adapter_namespace_diagnostic(
                    path=f"RunOptions.stage_options[{stage_id!r}].adapter_options[{namespace!r}]",
                    namespace=namespace,
                    executor=descriptor.name,
                    stage_id=stage_id,
                )
            )
    return diagnostics


def _adapter_namespace_diagnostic(
    *,
    path: str,
    namespace: str,
    executor: str,
    stage_id: str | None,
) -> CapabilityDiagnostic:
    return CapabilityDiagnostic(
        path=path,
        severity=CapabilitySeverity.WARNING,
        code="adapter_namespace.unclaimed",
        message=f"executor {executor!r} does not claim adapter namespace {namespace!r}",
        executor=executor,
        stage_id=stage_id,
        adapter_namespace=namespace,
    )


def _resource_capability_diagnostics(
    options: RunOptions,
    descriptor: ExecutorDescriptor,
) -> list[CapabilityDiagnostic]:
    diagnostics: list[CapabilityDiagnostic] = []
    for stage_id, stage_options in cast(
        Mapping[str, StageRuntimeOptions],
        options.stage_options,
    ).items():
        resources = cast(ResourceRequest, stage_options.resources)
        for kind in resources.entries:
            capability = descriptor.capability_for(kind)
            diagnostics.append(
                CapabilityDiagnostic(
                    path=f"RunOptions.stage_options[{stage_id!r}].resources.entries[{kind!r}]",
                    severity=cast(CapabilitySeverity, capability.severity),
                    code=_resource_diagnostic_code(
                        cast(ResourceSupportLevel, capability.support_level)
                    ),
                    message=_resource_diagnostic_message(
                        executor=descriptor.name,
                        kind=kind,
                        capability=capability,
                    ),
                    executor=descriptor.name,
                    stage_id=stage_id,
                    resource_kind=kind,
                    support_level=cast(ResourceSupportLevel, capability.support_level),
                    enforcement=cast(
                        ResourceEnforcementExpectation, capability.enforcement
                    ),
                    details=capability.details,
                )
            )
    return diagnostics


def _resource_diagnostic_code(support_level: ResourceSupportLevel) -> str:
    return f"resource.{support_level.value}"


def _resource_diagnostic_message(
    *,
    executor: str,
    kind: str,
    capability: ResourceCapability,
) -> str:
    support_level = cast(ResourceSupportLevel, capability.support_level)
    if support_level is ResourceSupportLevel.SUPPORTED:
        return f"executor {executor!r} supports resource kind {kind!r}"
    if support_level is ResourceSupportLevel.ADVISORY:
        return f"executor {executor!r} treats resource kind {kind!r} as advisory"
    if support_level is ResourceSupportLevel.IGNORED:
        return f"executor {executor!r} ignores resource kind {kind!r}"
    return f"executor {executor!r} does not support resource kind {kind!r}"


def _coerce_registry(
    registry: ExecutorDescriptorRegistry | None,
) -> ExecutorDescriptorRegistry:
    if registry is None:
        return DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY
    if not isinstance(registry, ExecutorDescriptorRegistry):
        raise RuntimeResourceError("registry must be an ExecutorDescriptorRegistry")
    return registry


def _coerce_resource_capabilities(
    value: Mapping[str, ResourceCapability | Mapping[str, object]],
    *,
    path: str,
) -> Mapping[str, ResourceCapability]:
    mapping = _object_mapping(value, path=path)
    normalized: dict[str, ResourceCapability] = {}
    for key, capability in mapping.items():
        kind = validate_resource_kind(key, path=f"{path} key")
        normalized[kind] = _coerce_resource_capability(
            cast(ResourceCapability | Mapping[str, object], capability),
            path=f"{path}[{kind!r}]",
        )
    return MappingProxyType(dict(sorted(normalized.items())))


def _coerce_resource_capability(
    value: ResourceCapability | Mapping[str, object],
    *,
    path: str,
) -> ResourceCapability:
    if isinstance(value, ResourceCapability):
        return value
    try:
        return ResourceCapability.from_dict(value)
    except RuntimeResourceError as exc:
        raise RuntimeResourceError(f"{path}: {exc}") from exc


def _adapter_namespace_tuple(
    value: Iterable[str] | Mapping[str, object],
    *,
    path: str,
) -> tuple[str, ...]:
    if isinstance(value, str):
        raise RuntimeResourceError(
            f"{path} must be a sequence or mapping of namespace names"
        )
    names = value.keys() if isinstance(value, Mapping) else value
    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(names):
        namespace = _string_value(item, path=f"{path}[{index}]").strip()
        if not namespace:
            raise RuntimeResourceError(f"{path}[{index}] must be a non-empty string")
        if namespace in seen:
            raise RuntimeResourceError(
                f"{path} contains duplicate namespace {namespace!r}"
            )
        seen.add(namespace)
        normalized.append(namespace)
    return tuple(sorted(normalized))


def _selected_executor_name(value: str | None) -> str:
    if value is None:
        return "local"
    return _normalize_executor_name(value, path="RunOptions.executor")


def _normalize_executor_name(value: object, *, path: str) -> str:
    text = _string_value(value, path=path).strip()
    if not text:
        raise RuntimeResourceError(f"{path} must be a non-empty string")
    return text


def _coerce_timeout_support(
    value: TimeoutSupportLevel | str | object,
    *,
    path: str,
) -> TimeoutSupportLevel:
    if isinstance(value, TimeoutSupportLevel):
        return value
    if not isinstance(value, str):
        raise RuntimeResourceError(f"{path} must be a string")
    try:
        return TimeoutSupportLevel(value)
    except ValueError as exc:
        valid = ", ".join(level.value for level in TimeoutSupportLevel)
        raise RuntimeResourceError(f"{path} must be one of: {valid}") from exc


def _diagnostic_sort_key(diagnostic: CapabilityDiagnostic) -> tuple[str, str, str, str]:
    identity = diagnostic.resource_kind or diagnostic.adapter_namespace or ""
    return (diagnostic.path, diagnostic.code, identity, diagnostic.message)


def _coerce_support_level(
    value: ResourceSupportLevel | str, *, path: str
) -> ResourceSupportLevel:
    if isinstance(value, ResourceSupportLevel):
        return value
    if not isinstance(value, str):
        raise RuntimeResourceError(f"{path} must be a string")
    try:
        return ResourceSupportLevel(value)
    except ValueError as exc:
        raise RuntimeResourceError(f"{path} has unsupported value {value!r}") from exc


def _optional_support_level(
    value: ResourceSupportLevel | str | None,
    *,
    path: str,
) -> ResourceSupportLevel | None:
    if value is None:
        return None
    return _coerce_support_level(value, path=path)


def _coerce_enforcement(
    value: ResourceEnforcementExpectation | str | None,
    *,
    path: str,
    support_level: ResourceSupportLevel,
) -> ResourceEnforcementExpectation:
    if value is None:
        return _default_enforcement(support_level)
    if isinstance(value, ResourceEnforcementExpectation):
        return value
    if not isinstance(value, str):
        raise RuntimeResourceError(f"{path} must be a string")
    try:
        return ResourceEnforcementExpectation(value)
    except ValueError as exc:
        raise RuntimeResourceError(f"{path} has unsupported value {value!r}") from exc


def _optional_enforcement(
    value: ResourceEnforcementExpectation | str | None,
    *,
    path: str,
) -> ResourceEnforcementExpectation | None:
    if value is None:
        return None
    if isinstance(value, ResourceEnforcementExpectation):
        return value
    if not isinstance(value, str):
        raise RuntimeResourceError(f"{path} must be a string")
    try:
        return ResourceEnforcementExpectation(value)
    except ValueError as exc:
        raise RuntimeResourceError(f"{path} has unsupported value {value!r}") from exc


def _coerce_severity(
    value: CapabilitySeverity | str | None,
    *,
    path: str,
    support_level: ResourceSupportLevel,
) -> CapabilitySeverity:
    if value is None:
        return _default_severity(support_level)
    return _coerce_diagnostic_severity(value, path=path)


def _coerce_diagnostic_severity(
    value: CapabilitySeverity | str,
    *,
    path: str,
) -> CapabilitySeverity:
    if isinstance(value, CapabilitySeverity):
        return value
    if not isinstance(value, str):
        raise RuntimeResourceError(f"{path} must be a string")
    try:
        return CapabilitySeverity(value)
    except ValueError as exc:
        raise RuntimeResourceError(f"{path} has unsupported value {value!r}") from exc


def _default_enforcement(
    support_level: ResourceSupportLevel,
) -> ResourceEnforcementExpectation:
    if support_level is ResourceSupportLevel.SUPPORTED:
        return ResourceEnforcementExpectation.ENFORCED
    if support_level is ResourceSupportLevel.ADVISORY:
        return ResourceEnforcementExpectation.BEST_EFFORT
    if support_level is ResourceSupportLevel.IGNORED:
        return ResourceEnforcementExpectation.NOT_ENFORCED
    return ResourceEnforcementExpectation.NOT_APPLICABLE


def _default_severity(support_level: ResourceSupportLevel) -> CapabilitySeverity:
    if support_level is ResourceSupportLevel.SUPPORTED:
        return CapabilitySeverity.INFO
    if support_level is ResourceSupportLevel.UNSUPPORTED:
        return CapabilitySeverity.ERROR
    return CapabilitySeverity.WARNING


def _optional_resource_kind(value: str | None, *, path: str) -> str | None:
    if value is None:
        return None
    return validate_resource_kind(value, path=path)


def _optional_string(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    return _string_value(value, path=path)


def _string_value(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeResourceError(f"{path} must be a non-empty string")
    return value


def _object_mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise RuntimeResourceError(f"{path} must be a mapping with string keys")
    return cast(Mapping[str, object], value)


def _plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=path)
    except PlainDataError as exc:
        raise RuntimeResourceError(
            f"{path} must be plain-data-compatible mapping: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _freeze_plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    return cast(
        Mapping[str, PlainData],
        freeze_plain_data(
            _sorted_plain_mapping(_plain_mapping(value, path=path)), path=path
        ),
    )


def _thaw_mapping(value: Mapping[str, PlainData], *, path: str) -> dict[str, PlainData]:
    thawed = thaw_plain_data(value, path=path)
    if not isinstance(thawed, dict):
        raise RuntimeResourceError(f"{path} must be a mapping")
    return _sorted_plain_mapping(thawed)


def _sorted_plain_mapping(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return {key: _sort_plain_value(value[key]) for key in sorted(value)}


def _sort_plain_value(value: PlainData) -> PlainData:
    if isinstance(value, dict):
        return _sorted_plain_mapping(value)
    if isinstance(value, list):
        return [_sort_plain_value(item) for item in value]
    return value


def _reject_unknown(
    mapping: Mapping[str, object],
    *,
    allowed: frozenset[str],
    path: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise RuntimeResourceError(f"{path} contains unknown field(s): {fields}")


DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY = ExecutorDescriptorRegistry(
    {
        "docker": _docker_descriptor(),
        "local": _local_descriptor(),
        "slurm-afterok": _slurm_descriptor("slurm-afterok"),
        "slurm-single-job": _slurm_descriptor("slurm-single-job"),
        "subprocess": _subprocess_descriptor(),
    }
)


__all__ = [
    "DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY",
    "CapabilityDiagnostic",
    "CapabilitySeverity",
    "CapabilityValidationResult",
    "ExecutorDescriptor",
    "ExecutorDescriptorRegistry",
    "ResourceCapability",
    "ResourceEnforcementExpectation",
    "ResourceSupportLevel",
    "resolve_executor_descriptor",
    "validate_executor_capabilities",
]
