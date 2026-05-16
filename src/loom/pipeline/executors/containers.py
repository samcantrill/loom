"""Import-light shared container execution records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import cast

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.runtime.capabilities import (
    CapabilitySeverity,
    ResourceCapability,
    ResourceEnforcementExpectation,
    ResourceSupportLevel,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError


REDACTED_VALUE = "[redacted]"
_IMAGE_FIELDS = frozenset({"reference"})
_MOUNT_FIELDS = frozenset({"source", "target", "mode"})
_ENVIRONMENT_FIELDS = frozenset({"variables", "required_host_variables"})
_RESOURCE_INTENT_FIELDS = frozenset({"entries", "capabilities"})
_PATH_PARITY_FIELDS = frozenset(
    {
        "kind",
        "host_path",
        "container_path",
        "writable_required",
        "ok",
        "reason",
    }
)
_OPTIONS_FIELDS = frozenset(
    {"image", "workdir", "mounts", "environment", "resources"}
)
_DOCKER_RESERVED_GENERIC_FIELDS = frozenset(
    {"image", "workdir", "mounts", "environment", "resources"}
)


class ContainerOptionError(RuntimeResourceError):
    """Raised when container adapter options are invalid."""


class ContainerMountMode(StrEnum):
    """Portable mount intent for container backends."""

    READ_ONLY = "ro"
    READ_WRITE = "rw"


@dataclass(frozen=True, slots=True)
class ContainerImageReference:
    """Authored container image reference without daemon inspection."""

    reference: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reference",
            _non_empty_string(self.reference, path="ContainerImageReference.reference"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {"reference": self.reference}

    @classmethod
    def from_dict(cls, data: object) -> "ContainerImageReference":
        mapping = _mapping(data, path="ContainerImageReference")
        _reject_unknown(mapping, _IMAGE_FIELDS, path="ContainerImageReference")
        _require_fields(mapping, {"reference"}, path="ContainerImageReference")
        return cls(
            reference=_string(mapping["reference"], path="ContainerImageReference.reference")
        )


@dataclass(frozen=True, slots=True)
class ContainerMount:
    """One host path mounted at the same container-visible path contract."""

    source: str
    target: str
    mode: ContainerMountMode | str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source",
            _absolute_host_path(self.source, path="ContainerMount.source"),
        )
        object.__setattr__(
            self,
            "target",
            _absolute_container_path(self.target, path="ContainerMount.target"),
        )
        object.__setattr__(
            self,
            "mode",
            _mount_mode(self.mode, path="ContainerMount.mode"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "source": self.source,
            "target": self.target,
            "mode": cast(ContainerMountMode, self.mode).value,
        }

    @classmethod
    def from_dict(cls, data: object) -> "ContainerMount":
        mapping = _mapping(data, path="ContainerMount")
        _reject_unknown(mapping, _MOUNT_FIELDS, path="ContainerMount")
        _require_fields(mapping, _MOUNT_FIELDS, path="ContainerMount")
        return cls(
            source=_string(mapping["source"], path="ContainerMount.source"),
            target=_string(mapping["target"], path="ContainerMount.target"),
            mode=_string(mapping["mode"], path="ContainerMount.mode"),
        )

    def to_redacted_metadata(self) -> dict[str, PlainData]:
        return {
            "source": self.source,
            "target": self.target,
            "mode": cast(ContainerMountMode, self.mode).value,
        }


@dataclass(frozen=True, slots=True)
class ContainerEnvironment:
    """Explicit container environment handoff without host inheritance."""

    variables: Mapping[str, str] = field(default_factory=dict)
    required_host_variables: Sequence[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "variables",
            MappingProxyType(
                {
                    key: value
                    for key, value in sorted(
                        _str_mapping(
                            self.variables,
                            path="ContainerEnvironment.variables",
                        ).items()
                    )
                }
            ),
        )
        object.__setattr__(
            self,
            "required_host_variables",
            _str_tuple(
                self.required_host_variables,
                path="ContainerEnvironment.required_host_variables",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "variables": dict(self.variables),
            "required_host_variables": list(self.required_host_variables),
        }

    @classmethod
    def from_dict(cls, data: object | None) -> "ContainerEnvironment":
        if data is None:
            return cls()
        mapping = _mapping(data, path="ContainerEnvironment")
        _reject_unknown(mapping, _ENVIRONMENT_FIELDS, path="ContainerEnvironment")
        return cls(
            variables=_str_mapping(
                mapping.get("variables", {}),
                path="ContainerEnvironment.variables",
            ),
            required_host_variables=_str_tuple(
                mapping.get("required_host_variables", ()),
                path="ContainerEnvironment.required_host_variables",
            ),
        )

    def to_redacted_metadata(self) -> dict[str, PlainData]:
        return {
            "variable_names": list(self.variables),
            "variables": {key: REDACTED_VALUE for key in self.variables},
            "required_host_variables": list(self.required_host_variables),
        }


@dataclass(frozen=True, slots=True)
class ContainerResourceIntent:
    """Container-facing projection of canonical runtime resources."""

    entries: Mapping[str, ResourceEntry | Mapping[str, PlainData]] = field(
        default_factory=dict
    )
    capabilities: Mapping[str, ResourceCapability | Mapping[str, PlainData]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        entries = _resource_entries(self.entries, path="ContainerResourceIntent.entries")
        capabilities = _resource_capabilities(
            self.capabilities,
            path="ContainerResourceIntent.capabilities",
        )
        missing = sorted(set(entries) - set(capabilities))
        if missing:
            fields = ", ".join(missing)
            raise ContainerOptionError(
                "ContainerResourceIntent.capabilities missing resource kind(s): "
                f"{fields}"
            )
        object.__setattr__(
            self,
            "entries",
            MappingProxyType(dict(sorted(entries.items()))),
        )
        object.__setattr__(
            self,
            "capabilities",
            MappingProxyType(dict(sorted(capabilities.items()))),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "entries": {
                kind: entry.to_dict()
                for kind, entry in cast(
                    Mapping[str, ResourceEntry],
                    self.entries,
                ).items()
            },
            "capabilities": {
                kind: capability.to_dict()
                for kind, capability in cast(
                    Mapping[str, ResourceCapability],
                    self.capabilities,
                ).items()
            },
        }

    @classmethod
    def from_dict(cls, data: object | None) -> "ContainerResourceIntent | None":
        if data is None:
            return None
        mapping = _mapping(data, path="ContainerResourceIntent")
        _reject_unknown(mapping, _RESOURCE_INTENT_FIELDS, path="ContainerResourceIntent")
        return cls(
            entries=cast(
                Mapping[str, ResourceEntry | Mapping[str, PlainData]],
                _mapping(
                    mapping.get("entries", {}),
                    path="ContainerResourceIntent.entries",
                ),
            ),
            capabilities=cast(
                Mapping[str, ResourceCapability | Mapping[str, PlainData]],
                _mapping(
                    mapping.get("capabilities", {}),
                    path="ContainerResourceIntent.capabilities",
                ),
            ),
        )

    @classmethod
    def from_runtime(
        cls,
        resources: ResourceRequest,
        capabilities: Mapping[str, ResourceCapability],
    ) -> "ContainerResourceIntent":
        return cls(entries=resources.entries, capabilities=capabilities)

    def to_redacted_metadata(self) -> dict[str, PlainData]:
        return {
            "entries": {
                kind: {
                    "kind": entry.kind,
                    "amount": entry.amount,
                    "unit": entry.unit,
                    "attribute_count": len(entry.attributes),
                }
                for kind, entry in cast(
                    Mapping[str, ResourceEntry],
                    self.entries,
                ).items()
            },
            "capabilities": {
                kind: _resource_capability_metadata(capability)
                for kind, capability in cast(
                    Mapping[str, ResourceCapability],
                    self.capabilities,
                ).items()
            },
        }


@dataclass(frozen=True, slots=True)
class ContainerPathParitySummary:
    """Validation summary for a host path that must be visible unchanged."""

    kind: str
    host_path: str
    container_path: str
    writable_required: bool
    ok: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _non_empty_string(self.kind, path="ContainerPathParitySummary.kind"),
        )
        object.__setattr__(
            self,
            "host_path",
            _non_empty_string(
                self.host_path,
                path="ContainerPathParitySummary.host_path",
            ),
        )
        object.__setattr__(
            self,
            "container_path",
            _non_empty_string(
                self.container_path,
                path="ContainerPathParitySummary.container_path",
            ),
        )
        if not isinstance(self.writable_required, bool):
            raise ContainerOptionError(
                "ContainerPathParitySummary.writable_required must be a bool"
            )
        if not isinstance(self.ok, bool):
            raise ContainerOptionError("ContainerPathParitySummary.ok must be a bool")
        if self.reason is not None:
            object.__setattr__(
                self,
                "reason",
                _non_empty_string(
                    self.reason,
                    path="ContainerPathParitySummary.reason",
                ),
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind,
            "host_path": self.host_path,
            "container_path": self.container_path,
            "writable_required": self.writable_required,
            "ok": self.ok,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: object) -> "ContainerPathParitySummary":
        mapping = _mapping(data, path="ContainerPathParitySummary")
        _reject_unknown(mapping, _PATH_PARITY_FIELDS, path="ContainerPathParitySummary")
        _require_fields(
            mapping,
            _PATH_PARITY_FIELDS - {"reason"},
            path="ContainerPathParitySummary",
        )
        return cls(
            kind=_string(mapping["kind"], path="ContainerPathParitySummary.kind"),
            host_path=_string(
                mapping["host_path"],
                path="ContainerPathParitySummary.host_path",
            ),
            container_path=_string(
                mapping["container_path"],
                path="ContainerPathParitySummary.container_path",
            ),
            writable_required=_bool(
                mapping["writable_required"],
                path="ContainerPathParitySummary.writable_required",
            ),
            ok=_bool(mapping["ok"], path="ContainerPathParitySummary.ok"),
            reason=_optional_string(
                mapping.get("reason"),
                path="ContainerPathParitySummary.reason",
            ),
        )


@dataclass(frozen=True, slots=True)
class ContainerOptions:
    """Generic container adapter options shared across container executors."""

    image: ContainerImageReference | str | Mapping[str, object]
    workdir: str | None = None
    mounts: Sequence[ContainerMount | Mapping[str, object]] = ()
    environment: ContainerEnvironment | Mapping[str, object] | None = None
    resources: ContainerResourceIntent | Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        image = _coerce_image_reference(self.image)
        workdir = _optional_container_path(self.workdir, path="ContainerOptions.workdir")
        mounts = tuple(_container_mounts(self.mounts, path="ContainerOptions.mounts"))
        targets = [mount.target for mount in mounts]
        duplicates = sorted({target for target in targets if targets.count(target) > 1})
        if duplicates:
            fields = ", ".join(duplicates)
            raise ContainerOptionError(
                f"ContainerOptions.mounts contains duplicate target(s): {fields}"
            )
        environment = (
            self.environment
            if isinstance(self.environment, ContainerEnvironment)
            else ContainerEnvironment.from_dict(self.environment)
        )
        resources = (
            self.resources
            if isinstance(self.resources, ContainerResourceIntent)
            else ContainerResourceIntent.from_dict(self.resources)
        )
        object.__setattr__(self, "image", image)
        object.__setattr__(self, "workdir", workdir)
        object.__setattr__(self, "mounts", mounts)
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "resources", resources)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "image": cast(ContainerImageReference, self.image).to_dict(),
            "workdir": self.workdir,
            "mounts": [
                mount.to_dict()
                for mount in cast(tuple[ContainerMount, ...], self.mounts)
            ],
            "environment": cast(ContainerEnvironment, self.environment).to_dict(),
            "resources": (
                None
                if self.resources is None
                else cast(ContainerResourceIntent, self.resources).to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ContainerOptions":
        mapping = _mapping(data, path="ContainerOptions")
        _reject_unknown(mapping, _OPTIONS_FIELDS, path="ContainerOptions")
        _require_fields(mapping, {"image"}, path="ContainerOptions")
        return cls(
            image=ContainerImageReference.from_dict(mapping["image"]),
            workdir=_optional_string(mapping.get("workdir"), path="ContainerOptions.workdir"),
            mounts=tuple(
                cast(
                    Sequence[ContainerMount | Mapping[str, object]],
                    _sequence(mapping.get("mounts", ()), path="ContainerOptions.mounts"),
                )
            ),
            environment=cast(
                Mapping[str, object] | None,
                mapping.get("environment"),
            ),
            resources=cast(Mapping[str, object] | None, mapping.get("resources")),
        )

    def to_redacted_metadata(self) -> dict[str, PlainData]:
        environment = cast(ContainerEnvironment, self.environment)
        resources = cast(ContainerResourceIntent | None, self.resources)
        return {
            "image": cast(ContainerImageReference, self.image).reference,
            "workdir": self.workdir,
            "mounts": [
                mount.to_redacted_metadata()
                for mount in cast(tuple[ContainerMount, ...], self.mounts)
            ],
            "environment": environment.to_redacted_metadata(),
            "resources": None if resources is None else resources.to_redacted_metadata(),
        }

    def path_parity_summaries(self) -> tuple[ContainerPathParitySummary, ...]:
        summaries: list[ContainerPathParitySummary] = []
        if self.workdir is not None:
            summaries.append(
                summarize_path_parity(
                    kind="workdir",
                    host_path=self.workdir,
                    container_path=self.workdir,
                    writable_required=True,
                )
            )
        for mount in cast(tuple[ContainerMount, ...], self.mounts):
            summaries.append(
                summarize_path_parity(
                    kind="mount",
                    host_path=mount.source,
                    container_path=mount.target,
                    writable_required=mount.mode is ContainerMountMode.READ_WRITE,
                )
            )
        return tuple(summaries)


def parse_container_options(data: object) -> ContainerOptions:
    """Parse ``adapter_options.container`` into shared container records."""

    return ContainerOptions.from_dict(data)


def validate_reserved_docker_options(data: object | None) -> Mapping[str, PlainData]:
    """Validate Phase 1 Docker namespace payload without owning Docker flags."""

    if data is None:
        return MappingProxyType({})
    mapping = _plain_mapping(data, path="adapter_options.docker")
    generic = sorted(set(mapping) & _DOCKER_RESERVED_GENERIC_FIELDS)
    if generic:
        fields = ", ".join(generic)
        raise ContainerOptionError(
            "adapter_options.docker cannot contain generic container field(s): "
            f"{fields}; use adapter_options.container"
        )
    return MappingProxyType(dict(sorted(mapping.items())))


def summarize_path_parity(
    *,
    kind: str,
    host_path: str,
    container_path: str,
    writable_required: bool,
) -> ContainerPathParitySummary:
    """Return a fail-closed path-parity summary without filesystem probing."""

    normalized_kind = _non_empty_string(kind, path="kind")
    if not isinstance(writable_required, bool):
        raise ContainerOptionError("writable_required must be a bool")
    try:
        host = _absolute_host_path(host_path, path="host_path")
        container = _absolute_container_path(container_path, path="container_path")
    except ContainerOptionError as exc:
        return ContainerPathParitySummary(
            kind=normalized_kind,
            host_path=str(host_path),
            container_path=str(container_path),
            writable_required=writable_required,
            ok=False,
            reason=str(exc),
        )
    if host != container:
        return ContainerPathParitySummary(
            kind=normalized_kind,
            host_path=host,
            container_path=container,
            writable_required=writable_required,
            ok=False,
            reason="host_path and container_path must match in Stage 17",
        )
    return ContainerPathParitySummary(
        kind=normalized_kind,
        host_path=host,
        container_path=container,
        writable_required=writable_required,
        ok=True,
        reason=None,
    )


def _container_mounts(
    value: Sequence[ContainerMount | Mapping[str, object]],
    *,
    path: str,
) -> tuple[ContainerMount, ...]:
    items = _sequence(value, path=path)
    mounts: list[ContainerMount] = []
    for index, item in enumerate(items):
        mounts.append(
            item
            if isinstance(item, ContainerMount)
            else ContainerMount.from_dict(item)
        )
    return tuple(mounts)


def _coerce_image_reference(
    value: ContainerImageReference | str | Mapping[str, object],
) -> ContainerImageReference:
    if isinstance(value, ContainerImageReference):
        return value
    if isinstance(value, str):
        return ContainerImageReference(reference=value)
    return ContainerImageReference.from_dict(value)


def _resource_entries(
    value: Mapping[str, ResourceEntry | Mapping[str, PlainData]],
    *,
    path: str,
) -> dict[str, ResourceEntry]:
    mapping = _mapping(value, path=path)
    entries: dict[str, ResourceEntry] = {}
    for key, item in mapping.items():
        kind = _non_empty_string(key, path=f"{path} key")
        entry = (
            item
            if isinstance(item, ResourceEntry)
            else ResourceEntry.from_dict(item, path=f"{path}[{kind!r}]")
        )
        if entry.kind != kind:
            raise ContainerOptionError(f"{path}[{kind!r}].kind must match its key")
        entries[kind] = entry
    return entries


def _resource_capabilities(
    value: Mapping[str, ResourceCapability | Mapping[str, PlainData]],
    *,
    path: str,
) -> dict[str, ResourceCapability]:
    mapping = _mapping(value, path=path)
    capabilities: dict[str, ResourceCapability] = {}
    for key, item in mapping.items():
        kind = _non_empty_string(key, path=f"{path} key")
        capabilities[kind] = (
            item
            if isinstance(item, ResourceCapability)
            else ResourceCapability.from_dict(item)
        )
    return capabilities


def _resource_capability_metadata(
    capability: ResourceCapability,
) -> dict[str, PlainData]:
    support_level = cast(ResourceSupportLevel, capability.support_level)
    enforcement = cast(ResourceEnforcementExpectation, capability.enforcement)
    severity = cast(CapabilitySeverity, capability.severity)
    return {
        "support_level": support_level.value,
        "enforcement": enforcement.value,
        "severity": severity.value,
    }


def _mount_mode(value: ContainerMountMode | str, *, path: str) -> ContainerMountMode:
    if isinstance(value, ContainerMountMode):
        return value
    if not isinstance(value, str):
        raise ContainerOptionError(f"{path} must be a string")
    try:
        return ContainerMountMode(value)
    except ValueError as exc:
        raise ContainerOptionError(f"{path} must be one of: ro, rw") from exc


def _absolute_host_path(value: object, *, path: str) -> str:
    text = _non_empty_string(value, path=path)
    if "\x00" in text:
        raise ContainerOptionError(f"{path} cannot contain NUL")
    if not text.startswith("/"):
        raise ContainerOptionError(f"{path} must be an absolute path")
    if _has_unsafe_parts(text):
        raise ContainerOptionError(f"{path} cannot contain '.' or '..' path parts")
    return text


def _absolute_container_path(value: object, *, path: str) -> str:
    text = _non_empty_string(value, path=path)
    if "\\" in text:
        raise ContainerOptionError(f"{path} must use POSIX '/' separators")
    if "\x00" in text:
        raise ContainerOptionError(f"{path} cannot contain NUL")
    parsed = PurePosixPath(text)
    if not parsed.is_absolute():
        raise ContainerOptionError(f"{path} must be an absolute container path")
    if parsed == PurePosixPath("/"):
        raise ContainerOptionError(f"{path} must not be container root")
    if _has_unsafe_parts(text):
        raise ContainerOptionError(f"{path} cannot contain '.' or '..' path parts")
    return text


def _optional_container_path(value: object | None, *, path: str) -> str | None:
    if value is None:
        return None
    return _absolute_container_path(value, path=path)


def _has_unsafe_parts(value: str) -> bool:
    parts = value.split("/")
    return any(part in {".", ".."} for part in parts)


def _mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContainerOptionError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise ContainerOptionError(f"{path} must be a mapping with string keys")
    return cast(Mapping[str, object], value)


def _plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    try:
        normalized = freeze_plain_data(value, path=path)
    except PlainDataError as exc:
        raise ContainerOptionError(f"{path} must be plain data: {exc}") from exc
    thawed = thaw_plain_data(normalized, path=path)
    if not isinstance(thawed, Mapping):
        raise ContainerOptionError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in thawed):
        raise ContainerOptionError(f"{path} must be a mapping with string keys")
    return cast(Mapping[str, PlainData], thawed)


def _str_mapping(value: object, *, path: str) -> Mapping[str, str]:
    mapping = _mapping(value, path=path)
    normalized: dict[str, str] = {}
    for key, item in mapping.items():
        name = _non_empty_string(key, path=f"{path} key")
        if not isinstance(item, str):
            raise ContainerOptionError(f"{path}[{name!r}] must be a string")
        normalized[name] = item
    return MappingProxyType(dict(sorted(normalized.items())))


def _sequence(value: object, *, path: str) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ContainerOptionError(f"{path} must be a sequence")
    return cast(Sequence[object], value)


def _str_tuple(value: object, *, path: str) -> tuple[str, ...]:
    items = _sequence(value, path=path)
    normalized = [
        _non_empty_string(item, path=f"{path}[{index}]")
        for index, item in enumerate(items)
    ]
    if len(set(normalized)) != len(normalized):
        raise ContainerOptionError(f"{path} contains duplicate variable names")
    return tuple(sorted(normalized))


def _string(value: object, *, path: str) -> str:
    if not isinstance(value, str):
        raise ContainerOptionError(f"{path} must be a string")
    return value


def _non_empty_string(value: object, *, path: str) -> str:
    text = _string(value, path=path).strip()
    if not text:
        raise ContainerOptionError(f"{path} must be a non-empty string")
    return text


def _optional_string(value: object | None, *, path: str) -> str | None:
    if value is None:
        return None
    return _string(value, path=path)


def _bool(value: object, *, path: str) -> bool:
    if not isinstance(value, bool):
        raise ContainerOptionError(f"{path} must be a bool")
    return value


def _require_fields(
    mapping: Mapping[str, object],
    required: frozenset[str] | set[str],
    *,
    path: str,
) -> None:
    missing = set(required) - set(mapping)
    if missing:
        fields = ", ".join(sorted(missing))
        raise ContainerOptionError(f"{path} missing required field(s): {fields}")


def _reject_unknown(
    mapping: Mapping[str, object],
    allowed: frozenset[str],
    *,
    path: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise ContainerOptionError(f"{path} contains unknown field(s): {fields}")


__all__ = [
    "ContainerEnvironment",
    "ContainerImageReference",
    "ContainerMount",
    "ContainerMountMode",
    "ContainerOptionError",
    "ContainerOptions",
    "ContainerPathParitySummary",
    "ContainerResourceIntent",
    "REDACTED_VALUE",
    "parse_container_options",
    "summarize_path_parity",
    "validate_reserved_docker_options",
]
