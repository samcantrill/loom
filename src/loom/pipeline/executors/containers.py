"""Import-light shared container execution records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Protocol, cast

from loom.fingerprints import hash_mapping
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


CONTAINER_BUILD_SCHEMA_VERSION = 1
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
_OPTIONS_FIELDS = frozenset({"image", "workdir", "mounts", "environment", "resources"})
_DOCKER_RESERVED_GENERIC_FIELDS = frozenset(
    {"image", "workdir", "mounts", "environment", "resources"}
)
_BUILD_SOURCE_FIELDS = frozenset(
    {"schema_version", "kind", "path", "uri", "context_path", "recipe_path", "metadata"}
)
_BUILD_OUTPUT_FIELDS = frozenset(
    {"schema_version", "kind", "reference", "path", "metadata"}
)
_BUILD_POLICY_FIELDS = frozenset({"schema_version", "mode"})
_BUILD_POLICY_DECISION_FIELDS = frozenset(
    {
        "schema_version",
        "target_name",
        "action",
        "expected_status",
        "reason",
        "output_exists",
        "source_stale",
    }
)
_BUILD_TARGET_FIELDS = frozenset(
    {
        "schema_version",
        "name",
        "runtime",
        "source",
        "output",
        "policy",
        "build_args",
        "metadata",
    }
)
_BUILD_OPTIONS_FIELDS = frozenset({"schema_version", "targets", "service"})
_BUILD_KEY_FIELDS = frozenset(
    {"schema_version", "target_name", "digest", "algorithm", "fields"}
)
_BUILD_COMMAND_FIELDS = frozenset(
    {
        "schema_version",
        "argv",
        "environment_keys",
        "build_arg_names",
        "metadata",
    }
)
_BUILD_EVIDENCE_FIELDS = frozenset(
    {"schema_version", "builder", "log_paths", "metadata"}
)
_BUILD_FAILURE_FIELDS = frozenset({"schema_version", "code", "message", "details"})
_BUILD_REQUEST_FIELDS = frozenset(
    {"schema_version", "target", "requested_by", "build_key"}
)
_BUILD_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "target_name",
        "status",
        "output",
        "build_key",
        "command",
        "evidence",
        "failure",
    }
)


class ContainerOptionError(RuntimeResourceError):
    """Raised when container adapter options are invalid."""


class ContainerMountMode(StrEnum):
    """Portable mount intent for container backends."""

    READ_ONLY = "ro"
    READ_WRITE = "rw"


class ContainerBuildRuntime(StrEnum):
    """Container runtime family for a shared build target."""

    DOCKER = "docker"
    APPTAINER = "apptainer"


class ContainerBuildSourceKind(StrEnum):
    """Supported authored build source descriptions."""

    DEFINITION_FILE = "definition_file"
    DOCKER_CONTEXT = "docker_context"
    LOCAL_PATH = "local_path"
    URI = "uri"


class ContainerBuildOutputKind(StrEnum):
    """Portable output reference kinds produced by builders."""

    DOCKER_IMAGE = "docker_image"
    APPTAINER_SIF = "apptainer_sif"


class ContainerBuildPolicyMode(StrEnum):
    """Foreground build/reuse policy names."""

    IF_STALE = "if_stale"
    ALWAYS = "always"
    NEVER = "never"


class ContainerBuildStatus(StrEnum):
    """Build result status values shared by local/fake builders."""

    BUILT = "built"
    REUSED = "reused"
    FAILED = "failed"
    SKIPPED = "skipped"


class ContainerBuildAction(StrEnum):
    """Policy decision actions for foreground local builders."""

    BUILD = "build"
    REUSE = "reuse"
    FAIL = "fail"


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
            reference=_string(
                mapping["reference"], path="ContainerImageReference.reference"
            )
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
        entries = _resource_entries(
            self.entries, path="ContainerResourceIntent.entries"
        )
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
        _reject_unknown(
            mapping, _RESOURCE_INTENT_FIELDS, path="ContainerResourceIntent"
        )
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
        workdir = _optional_container_path(
            self.workdir, path="ContainerOptions.workdir"
        )
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
            workdir=_optional_string(
                mapping.get("workdir"), path="ContainerOptions.workdir"
            ),
            mounts=tuple(
                cast(
                    Sequence[ContainerMount | Mapping[str, object]],
                    _sequence(
                        mapping.get("mounts", ()), path="ContainerOptions.mounts"
                    ),
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
            "resources": None
            if resources is None
            else resources.to_redacted_metadata(),
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


@dataclass(frozen=True, slots=True)
class ContainerBuildSource:
    """Authored container build source without fetching or inspection."""

    kind: ContainerBuildSourceKind | str
    path: str | None = None
    uri: str | None = None
    context_path: str | None = None
    recipe_path: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = CONTAINER_BUILD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        version = _schema_version(
            self.schema_version,
            path="ContainerBuildSource.schema_version",
        )
        kind = _build_source_kind(self.kind, path="ContainerBuildSource.kind")
        path = _optional_portable_path(self.path, path="ContainerBuildSource.path")
        uri = _optional_uri(self.uri, path="ContainerBuildSource.uri")
        context_path = _optional_portable_path(
            self.context_path,
            path="ContainerBuildSource.context_path",
        )
        recipe_path = _optional_portable_path(
            self.recipe_path,
            path="ContainerBuildSource.recipe_path",
        )
        _validate_build_source_shape(
            kind=kind,
            path=path,
            uri=uri,
            context_path=context_path,
            recipe_path=recipe_path,
        )
        object.__setattr__(self, "schema_version", version)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "uri", uri)
        object.__setattr__(self, "context_path", context_path)
        object.__setattr__(self, "recipe_path", recipe_path)
        object.__setattr__(
            self,
            "metadata",
            _frozen_plain_mapping(
                self.metadata,
                path="ContainerBuildSource.metadata",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        data: dict[str, PlainData] = {
            "schema_version": self.schema_version,
            "kind": cast(ContainerBuildSourceKind, self.kind).value,
            "metadata": _thaw_plain_mapping(
                self.metadata,
                path="ContainerBuildSource.metadata",
            ),
        }
        if self.path is not None:
            data["path"] = self.path
        if self.uri is not None:
            data["uri"] = self.uri
        if self.context_path is not None:
            data["context_path"] = self.context_path
        if self.recipe_path is not None:
            data["recipe_path"] = self.recipe_path
        return data

    @classmethod
    def from_dict(cls, data: object) -> "ContainerBuildSource":
        mapping = _mapping(data, path="ContainerBuildSource")
        _reject_unknown(mapping, _BUILD_SOURCE_FIELDS, path="ContainerBuildSource")
        _require_fields(mapping, {"kind"}, path="ContainerBuildSource")
        kind = _build_source_kind(
            _string(mapping["kind"], path="ContainerBuildSource.kind"),
            path="ContainerBuildSource.kind",
        )
        _reject_build_source_fields(kind=kind, mapping=mapping)
        return cls(
            schema_version=_schema_version(
                mapping.get("schema_version", CONTAINER_BUILD_SCHEMA_VERSION),
                path="ContainerBuildSource.schema_version",
            ),
            kind=kind,
            path=_optional_string(
                mapping.get("path"), path="ContainerBuildSource.path"
            ),
            uri=_optional_string(mapping.get("uri"), path="ContainerBuildSource.uri"),
            context_path=_optional_string(
                mapping.get("context_path"),
                path="ContainerBuildSource.context_path",
            ),
            recipe_path=_optional_string(
                mapping.get("recipe_path"),
                path="ContainerBuildSource.recipe_path",
            ),
            metadata=_plain_mapping(
                mapping.get("metadata", {}),
                path="ContainerBuildSource.metadata",
            ),
        )

    def to_redacted_metadata(self) -> dict[str, PlainData]:
        data = self.to_dict()
        metadata = cast(dict[str, PlainData], data.pop("metadata"))
        data["metadata_keys"] = _plain_string_list(sorted(metadata))
        return data


@dataclass(frozen=True, slots=True)
class ContainerBuildOutputRef:
    """Reusable output reference produced by a container build target."""

    kind: ContainerBuildOutputKind | str
    reference: str | None = None
    path: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = CONTAINER_BUILD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        version = _schema_version(
            self.schema_version,
            path="ContainerBuildOutputRef.schema_version",
        )
        kind = _build_output_kind(self.kind, path="ContainerBuildOutputRef.kind")
        reference = _optional_non_empty_string(
            self.reference,
            path="ContainerBuildOutputRef.reference",
        )
        path = _optional_portable_path(self.path, path="ContainerBuildOutputRef.path")
        _validate_build_output_shape(kind=kind, reference=reference, path=path)
        object.__setattr__(self, "schema_version", version)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "path", path)
        object.__setattr__(
            self,
            "metadata",
            _frozen_plain_mapping(
                self.metadata,
                path="ContainerBuildOutputRef.metadata",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        data: dict[str, PlainData] = {
            "schema_version": self.schema_version,
            "kind": cast(ContainerBuildOutputKind, self.kind).value,
            "metadata": _thaw_plain_mapping(
                self.metadata,
                path="ContainerBuildOutputRef.metadata",
            ),
        }
        if self.reference is not None:
            data["reference"] = self.reference
        if self.path is not None:
            data["path"] = self.path
        return data

    @classmethod
    def from_dict(cls, data: object) -> "ContainerBuildOutputRef":
        mapping = _mapping(data, path="ContainerBuildOutputRef")
        _reject_unknown(mapping, _BUILD_OUTPUT_FIELDS, path="ContainerBuildOutputRef")
        _require_fields(mapping, {"kind"}, path="ContainerBuildOutputRef")
        kind = _build_output_kind(
            _string(mapping["kind"], path="ContainerBuildOutputRef.kind"),
            path="ContainerBuildOutputRef.kind",
        )
        _reject_build_output_fields(kind=kind, mapping=mapping)
        return cls(
            schema_version=_schema_version(
                mapping.get("schema_version", CONTAINER_BUILD_SCHEMA_VERSION),
                path="ContainerBuildOutputRef.schema_version",
            ),
            kind=kind,
            reference=_optional_string(
                mapping.get("reference"),
                path="ContainerBuildOutputRef.reference",
            ),
            path=_optional_string(
                mapping.get("path"),
                path="ContainerBuildOutputRef.path",
            ),
            metadata=_plain_mapping(
                mapping.get("metadata", {}),
                path="ContainerBuildOutputRef.metadata",
            ),
        )

    def to_redacted_metadata(self) -> dict[str, PlainData]:
        data = self.to_dict()
        metadata = cast(dict[str, PlainData], data.pop("metadata"))
        data["metadata_keys"] = _plain_string_list(sorted(metadata))
        return data


@dataclass(frozen=True, slots=True)
class ContainerBuildPolicy:
    """Build policy for local foreground builders."""

    mode: ContainerBuildPolicyMode | str = ContainerBuildPolicyMode.IF_STALE
    schema_version: int = CONTAINER_BUILD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_version(
                self.schema_version,
                path="ContainerBuildPolicy.schema_version",
            ),
        )
        object.__setattr__(
            self,
            "mode",
            _build_policy_mode(self.mode, path="ContainerBuildPolicy.mode"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "mode": cast(ContainerBuildPolicyMode, self.mode).value,
        }

    @classmethod
    def from_dict(cls, data: object | None) -> "ContainerBuildPolicy":
        if data is None:
            return cls()
        mapping = _mapping(data, path="ContainerBuildPolicy")
        _reject_unknown(mapping, _BUILD_POLICY_FIELDS, path="ContainerBuildPolicy")
        return cls(
            schema_version=_schema_version(
                mapping.get("schema_version", CONTAINER_BUILD_SCHEMA_VERSION),
                path="ContainerBuildPolicy.schema_version",
            ),
            mode=_string(
                mapping.get("mode", ContainerBuildPolicyMode.IF_STALE.value),
                path="ContainerBuildPolicy.mode",
            ),
        )


@dataclass(frozen=True, slots=True)
class ContainerBuildPolicyDecision:
    """Deterministic policy decision before a local builder runs."""

    target_name: str
    action: ContainerBuildAction | str
    expected_status: ContainerBuildStatus | str
    reason: str
    output_exists: bool
    source_stale: bool | None = None
    schema_version: int = CONTAINER_BUILD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_version(
                self.schema_version,
                path="ContainerBuildPolicyDecision.schema_version",
            ),
        )
        object.__setattr__(
            self,
            "target_name",
            _build_target_name(
                self.target_name,
                path="ContainerBuildPolicyDecision.target_name",
            ),
        )
        action = _build_action(
            self.action,
            path="ContainerBuildPolicyDecision.action",
        )
        status = _build_status(
            self.expected_status,
            path="ContainerBuildPolicyDecision.expected_status",
        )
        _validate_policy_decision_status(action=action, status=status)
        if not isinstance(self.output_exists, bool):
            raise ContainerOptionError(
                "ContainerBuildPolicyDecision.output_exists must be a bool"
            )
        if self.source_stale is not None and not isinstance(self.source_stale, bool):
            raise ContainerOptionError(
                "ContainerBuildPolicyDecision.source_stale must be a bool or None"
            )
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "expected_status", status)
        object.__setattr__(
            self,
            "reason",
            _non_empty_string(
                self.reason,
                path="ContainerBuildPolicyDecision.reason",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "target_name": self.target_name,
            "action": cast(ContainerBuildAction, self.action).value,
            "expected_status": cast(ContainerBuildStatus, self.expected_status).value,
            "reason": self.reason,
            "output_exists": self.output_exists,
            "source_stale": self.source_stale,
        }

    @classmethod
    def from_dict(cls, data: object) -> "ContainerBuildPolicyDecision":
        mapping = _mapping(data, path="ContainerBuildPolicyDecision")
        _reject_unknown(
            mapping,
            _BUILD_POLICY_DECISION_FIELDS,
            path="ContainerBuildPolicyDecision",
        )
        _require_fields(
            mapping,
            {
                "target_name",
                "action",
                "expected_status",
                "reason",
                "output_exists",
            },
            path="ContainerBuildPolicyDecision",
        )
        return cls(
            schema_version=_schema_version(
                mapping.get("schema_version", CONTAINER_BUILD_SCHEMA_VERSION),
                path="ContainerBuildPolicyDecision.schema_version",
            ),
            target_name=_string(
                mapping["target_name"],
                path="ContainerBuildPolicyDecision.target_name",
            ),
            action=_string(
                mapping["action"],
                path="ContainerBuildPolicyDecision.action",
            ),
            expected_status=_string(
                mapping["expected_status"],
                path="ContainerBuildPolicyDecision.expected_status",
            ),
            reason=_string(
                mapping["reason"],
                path="ContainerBuildPolicyDecision.reason",
            ),
            output_exists=_bool(
                mapping["output_exists"],
                path="ContainerBuildPolicyDecision.output_exists",
            ),
            source_stale=(
                None
                if mapping.get("source_stale") is None
                else _bool(
                    mapping["source_stale"],
                    path="ContainerBuildPolicyDecision.source_stale",
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class ContainerBuildTarget:
    """Named reusable build target for Docker or Apptainer builders."""

    name: str
    runtime: ContainerBuildRuntime | str
    source: ContainerBuildSource | Mapping[str, object]
    output: ContainerBuildOutputRef | Mapping[str, object]
    policy: ContainerBuildPolicy | Mapping[str, object] | None = None
    build_args: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = CONTAINER_BUILD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        version = _schema_version(
            self.schema_version,
            path="ContainerBuildTarget.schema_version",
        )
        name = _build_target_name(self.name, path="ContainerBuildTarget.name")
        runtime = _build_runtime(self.runtime, path="ContainerBuildTarget.runtime")
        source = (
            self.source
            if isinstance(self.source, ContainerBuildSource)
            else ContainerBuildSource.from_dict(self.source)
        )
        output = (
            self.output
            if isinstance(self.output, ContainerBuildOutputRef)
            else ContainerBuildOutputRef.from_dict(self.output)
        )
        policy = (
            self.policy
            if isinstance(self.policy, ContainerBuildPolicy)
            else ContainerBuildPolicy.from_dict(self.policy)
        )
        _validate_runtime_output_compatibility(
            runtime=runtime,
            output=cast(ContainerBuildOutputRef, output),
        )
        object.__setattr__(self, "schema_version", version)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "runtime", runtime)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "output", output)
        object.__setattr__(self, "policy", policy)
        object.__setattr__(
            self,
            "build_args",
            _frozen_plain_mapping(
                self.build_args,
                path="ContainerBuildTarget.build_args",
            ),
        )
        object.__setattr__(
            self,
            "metadata",
            _frozen_plain_mapping(
                self.metadata,
                path="ContainerBuildTarget.metadata",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "runtime": cast(ContainerBuildRuntime, self.runtime).value,
            "source": cast(ContainerBuildSource, self.source).to_dict(),
            "output": cast(ContainerBuildOutputRef, self.output).to_dict(),
            "policy": cast(ContainerBuildPolicy, self.policy).to_dict(),
            "build_args": _thaw_plain_mapping(
                self.build_args,
                path="ContainerBuildTarget.build_args",
            ),
            "metadata": _thaw_plain_mapping(
                self.metadata,
                path="ContainerBuildTarget.metadata",
            ),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ContainerBuildTarget":
        mapping = _mapping(data, path="ContainerBuildTarget")
        _reject_unknown(mapping, _BUILD_TARGET_FIELDS, path="ContainerBuildTarget")
        _require_fields(
            mapping,
            {"name", "runtime", "source", "output"},
            path="ContainerBuildTarget",
        )
        return cls(
            schema_version=_schema_version(
                mapping.get("schema_version", CONTAINER_BUILD_SCHEMA_VERSION),
                path="ContainerBuildTarget.schema_version",
            ),
            name=_string(mapping["name"], path="ContainerBuildTarget.name"),
            runtime=_string(mapping["runtime"], path="ContainerBuildTarget.runtime"),
            source=ContainerBuildSource.from_dict(mapping["source"]),
            output=ContainerBuildOutputRef.from_dict(mapping["output"]),
            policy=cast(Mapping[str, object] | None, mapping.get("policy")),
            build_args=_plain_mapping(
                mapping.get("build_args", {}),
                path="ContainerBuildTarget.build_args",
            ),
            metadata=_plain_mapping(
                mapping.get("metadata", {}),
                path="ContainerBuildTarget.metadata",
            ),
        )

    def build_key(self) -> "ContainerBuildKeySummary":
        return build_container_build_key(self)

    def to_redacted_metadata(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "runtime": cast(ContainerBuildRuntime, self.runtime).value,
            "source": cast(ContainerBuildSource, self.source).to_redacted_metadata(),
            "output": cast(ContainerBuildOutputRef, self.output).to_redacted_metadata(),
            "policy": cast(ContainerBuildPolicy, self.policy).to_dict(),
            "build_arg_names": _plain_string_list(list(self.build_args)),
            "metadata_keys": _plain_string_list(list(self.metadata)),
        }


@dataclass(frozen=True, slots=True)
class ContainerBuildOptions:
    """Parsed ``adapter_options.container_build`` namespace payload."""

    targets: Mapping[str, ContainerBuildTarget | Mapping[str, object]] = field(
        default_factory=dict
    )
    service: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = CONTAINER_BUILD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        version = _schema_version(
            self.schema_version,
            path="ContainerBuildOptions.schema_version",
        )
        targets = _build_targets(self.targets, path="ContainerBuildOptions.targets")
        object.__setattr__(self, "schema_version", version)
        object.__setattr__(
            self,
            "targets",
            MappingProxyType(dict(sorted(targets.items()))),
        )
        object.__setattr__(
            self,
            "service",
            _frozen_plain_mapping(
                self.service,
                path="ContainerBuildOptions.service",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "targets": {
                name: target.to_dict()
                for name, target in cast(
                    Mapping[str, ContainerBuildTarget],
                    self.targets,
                ).items()
            },
            "service": _thaw_plain_mapping(
                self.service,
                path="ContainerBuildOptions.service",
            ),
        }

    @classmethod
    def from_dict(cls, data: object | None) -> "ContainerBuildOptions":
        if data is None:
            return cls()
        mapping = _mapping(data, path="ContainerBuildOptions")
        _reject_unknown(mapping, _BUILD_OPTIONS_FIELDS, path="ContainerBuildOptions")
        return cls(
            schema_version=_schema_version(
                mapping.get("schema_version", CONTAINER_BUILD_SCHEMA_VERSION),
                path="ContainerBuildOptions.schema_version",
            ),
            targets=cast(
                Mapping[str, ContainerBuildTarget | Mapping[str, object]],
                _mapping(
                    mapping.get("targets", {}),
                    path="ContainerBuildOptions.targets",
                ),
            ),
            service=_plain_mapping(
                mapping.get("service", {}),
                path="ContainerBuildOptions.service",
            ),
        )

    def to_redacted_metadata(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "targets": {
                name: target.to_redacted_metadata()
                for name, target in cast(
                    Mapping[str, ContainerBuildTarget],
                    self.targets,
                ).items()
            },
            "service_keys": _plain_string_list(list(self.service)),
        }


@dataclass(frozen=True, slots=True)
class ContainerBuildKeySummary:
    """Deterministic local build-key summary without source fetching."""

    target_name: str
    digest: str
    fields: Mapping[str, PlainData]
    algorithm: str = "sha256"
    schema_version: int = CONTAINER_BUILD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_version(
                self.schema_version,
                path="ContainerBuildKeySummary.schema_version",
            ),
        )
        object.__setattr__(
            self,
            "target_name",
            _build_target_name(
                self.target_name,
                path="ContainerBuildKeySummary.target_name",
            ),
        )
        object.__setattr__(
            self,
            "digest",
            _non_empty_string(self.digest, path="ContainerBuildKeySummary.digest"),
        )
        object.__setattr__(
            self,
            "algorithm",
            _non_empty_string(
                self.algorithm,
                path="ContainerBuildKeySummary.algorithm",
            ),
        )
        object.__setattr__(
            self,
            "fields",
            _frozen_plain_mapping(
                self.fields,
                path="ContainerBuildKeySummary.fields",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "target_name": self.target_name,
            "digest": self.digest,
            "algorithm": self.algorithm,
            "fields": _thaw_plain_mapping(
                self.fields,
                path="ContainerBuildKeySummary.fields",
            ),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ContainerBuildKeySummary":
        mapping = _mapping(data, path="ContainerBuildKeySummary")
        _reject_unknown(mapping, _BUILD_KEY_FIELDS, path="ContainerBuildKeySummary")
        _require_fields(
            mapping,
            {"target_name", "digest", "fields"},
            path="ContainerBuildKeySummary",
        )
        return cls(
            schema_version=_schema_version(
                mapping.get("schema_version", CONTAINER_BUILD_SCHEMA_VERSION),
                path="ContainerBuildKeySummary.schema_version",
            ),
            target_name=_string(
                mapping["target_name"],
                path="ContainerBuildKeySummary.target_name",
            ),
            digest=_string(mapping["digest"], path="ContainerBuildKeySummary.digest"),
            algorithm=_string(
                mapping.get("algorithm", "sha256"),
                path="ContainerBuildKeySummary.algorithm",
            ),
            fields=_plain_mapping(
                mapping["fields"],
                path="ContainerBuildKeySummary.fields",
            ),
        )


@dataclass(frozen=True, slots=True)
class ContainerBuildCommandProjection:
    """Redacted command projection recorded as build evidence."""

    argv: Sequence[str]
    environment_keys: Sequence[str] = ()
    build_arg_names: Sequence[str] = ()
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = CONTAINER_BUILD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_version(
                self.schema_version,
                path="ContainerBuildCommandProjection.schema_version",
            ),
        )
        object.__setattr__(
            self,
            "argv",
            _str_sequence_tuple(
                self.argv,
                path="ContainerBuildCommandProjection.argv",
            ),
        )
        object.__setattr__(
            self,
            "environment_keys",
            _str_tuple(
                self.environment_keys,
                path="ContainerBuildCommandProjection.environment_keys",
            ),
        )
        object.__setattr__(
            self,
            "build_arg_names",
            _str_tuple(
                self.build_arg_names,
                path="ContainerBuildCommandProjection.build_arg_names",
            ),
        )
        object.__setattr__(
            self,
            "metadata",
            _frozen_plain_mapping(
                self.metadata,
                path="ContainerBuildCommandProjection.metadata",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "argv": list(self.argv),
            "environment_keys": list(self.environment_keys),
            "build_arg_names": list(self.build_arg_names),
            "metadata": _thaw_plain_mapping(
                self.metadata,
                path="ContainerBuildCommandProjection.metadata",
            ),
        }

    @classmethod
    def from_dict(cls, data: object | None) -> "ContainerBuildCommandProjection | None":
        if data is None:
            return None
        mapping = _mapping(data, path="ContainerBuildCommandProjection")
        _reject_unknown(
            mapping,
            _BUILD_COMMAND_FIELDS,
            path="ContainerBuildCommandProjection",
        )
        _require_fields(mapping, {"argv"}, path="ContainerBuildCommandProjection")
        return cls(
            schema_version=_schema_version(
                mapping.get("schema_version", CONTAINER_BUILD_SCHEMA_VERSION),
                path="ContainerBuildCommandProjection.schema_version",
            ),
            argv=_str_sequence_tuple(
                mapping["argv"],
                path="ContainerBuildCommandProjection.argv",
            ),
            environment_keys=_str_tuple(
                mapping.get("environment_keys", ()),
                path="ContainerBuildCommandProjection.environment_keys",
            ),
            build_arg_names=_str_tuple(
                mapping.get("build_arg_names", ()),
                path="ContainerBuildCommandProjection.build_arg_names",
            ),
            metadata=_plain_mapping(
                mapping.get("metadata", {}),
                path="ContainerBuildCommandProjection.metadata",
            ),
        )


@dataclass(frozen=True, slots=True)
class ContainerBuildEvidence:
    """Run-local build evidence summary."""

    builder: str
    log_paths: Sequence[str] = ()
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = CONTAINER_BUILD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_version(
                self.schema_version,
                path="ContainerBuildEvidence.schema_version",
            ),
        )
        object.__setattr__(
            self,
            "builder",
            _non_empty_string(self.builder, path="ContainerBuildEvidence.builder"),
        )
        object.__setattr__(
            self,
            "log_paths",
            tuple(
                _portable_path(path, path=f"ContainerBuildEvidence.log_paths[{index}]")
                for index, path in enumerate(
                    _sequence(
                        self.log_paths,
                        path="ContainerBuildEvidence.log_paths",
                    )
                )
            ),
        )
        object.__setattr__(
            self,
            "metadata",
            _frozen_plain_mapping(
                self.metadata,
                path="ContainerBuildEvidence.metadata",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "builder": self.builder,
            "log_paths": list(self.log_paths),
            "metadata": _thaw_plain_mapping(
                self.metadata,
                path="ContainerBuildEvidence.metadata",
            ),
        }

    @classmethod
    def from_dict(cls, data: object | None) -> "ContainerBuildEvidence | None":
        if data is None:
            return None
        mapping = _mapping(data, path="ContainerBuildEvidence")
        _reject_unknown(mapping, _BUILD_EVIDENCE_FIELDS, path="ContainerBuildEvidence")
        _require_fields(mapping, {"builder"}, path="ContainerBuildEvidence")
        return cls(
            schema_version=_schema_version(
                mapping.get("schema_version", CONTAINER_BUILD_SCHEMA_VERSION),
                path="ContainerBuildEvidence.schema_version",
            ),
            builder=_string(
                mapping["builder"],
                path="ContainerBuildEvidence.builder",
            ),
            log_paths=_str_sequence_tuple(
                mapping.get("log_paths", ()),
                path="ContainerBuildEvidence.log_paths",
            ),
            metadata=_plain_mapping(
                mapping.get("metadata", {}),
                path="ContainerBuildEvidence.metadata",
            ),
        )


@dataclass(frozen=True, slots=True)
class ContainerBuildFailure:
    """Redacted build failure summary."""

    code: str
    message: str
    details: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = CONTAINER_BUILD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_version(
                self.schema_version,
                path="ContainerBuildFailure.schema_version",
            ),
        )
        object.__setattr__(
            self,
            "code",
            _non_empty_string(self.code, path="ContainerBuildFailure.code"),
        )
        object.__setattr__(
            self,
            "message",
            _non_empty_string(self.message, path="ContainerBuildFailure.message"),
        )
        object.__setattr__(
            self,
            "details",
            _frozen_plain_mapping(
                self.details,
                path="ContainerBuildFailure.details",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "code": self.code,
            "message": self.message,
            "details": _thaw_plain_mapping(
                self.details,
                path="ContainerBuildFailure.details",
            ),
        }

    @classmethod
    def from_dict(cls, data: object | None) -> "ContainerBuildFailure | None":
        if data is None:
            return None
        mapping = _mapping(data, path="ContainerBuildFailure")
        _reject_unknown(mapping, _BUILD_FAILURE_FIELDS, path="ContainerBuildFailure")
        _require_fields(mapping, {"code", "message"}, path="ContainerBuildFailure")
        return cls(
            schema_version=_schema_version(
                mapping.get("schema_version", CONTAINER_BUILD_SCHEMA_VERSION),
                path="ContainerBuildFailure.schema_version",
            ),
            code=_string(mapping["code"], path="ContainerBuildFailure.code"),
            message=_string(
                mapping["message"],
                path="ContainerBuildFailure.message",
            ),
            details=_plain_mapping(
                mapping.get("details", {}),
                path="ContainerBuildFailure.details",
            ),
        )


@dataclass(frozen=True, slots=True)
class ContainerBuildRequest:
    """One local build request for a named target."""

    target: ContainerBuildTarget | Mapping[str, object]
    requested_by: str
    build_key: ContainerBuildKeySummary | Mapping[str, object] | None = None
    schema_version: int = CONTAINER_BUILD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        target = (
            self.target
            if isinstance(self.target, ContainerBuildTarget)
            else ContainerBuildTarget.from_dict(self.target)
        )
        build_key = (
            self.build_key
            if isinstance(self.build_key, ContainerBuildKeySummary)
            else (
                None
                if self.build_key is None
                else ContainerBuildKeySummary.from_dict(self.build_key)
            )
        )
        if build_key is None:
            build_key = cast(ContainerBuildTarget, target).build_key()
        if cast(ContainerBuildKeySummary, build_key).target_name != target.name:
            raise ContainerOptionError(
                "ContainerBuildRequest.build_key target_name must match target.name"
            )
        object.__setattr__(
            self,
            "schema_version",
            _schema_version(
                self.schema_version,
                path="ContainerBuildRequest.schema_version",
            ),
        )
        object.__setattr__(self, "target", target)
        object.__setattr__(
            self,
            "requested_by",
            _non_empty_string(
                self.requested_by,
                path="ContainerBuildRequest.requested_by",
            ),
        )
        object.__setattr__(self, "build_key", build_key)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "target": cast(ContainerBuildTarget, self.target).to_dict(),
            "requested_by": self.requested_by,
            "build_key": cast(ContainerBuildKeySummary, self.build_key).to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ContainerBuildRequest":
        mapping = _mapping(data, path="ContainerBuildRequest")
        _reject_unknown(mapping, _BUILD_REQUEST_FIELDS, path="ContainerBuildRequest")
        _require_fields(
            mapping,
            {"target", "requested_by"},
            path="ContainerBuildRequest",
        )
        return cls(
            schema_version=_schema_version(
                mapping.get("schema_version", CONTAINER_BUILD_SCHEMA_VERSION),
                path="ContainerBuildRequest.schema_version",
            ),
            target=ContainerBuildTarget.from_dict(mapping["target"]),
            requested_by=_string(
                mapping["requested_by"],
                path="ContainerBuildRequest.requested_by",
            ),
            build_key=cast(Mapping[str, object] | None, mapping.get("build_key")),
        )


@dataclass(frozen=True, slots=True)
class ContainerBuildResult:
    """Build, reuse, skip, or failure result for one target."""

    target_name: str
    status: ContainerBuildStatus | str
    output: ContainerBuildOutputRef | Mapping[str, object] | None = None
    build_key: ContainerBuildKeySummary | Mapping[str, object] | None = None
    command: ContainerBuildCommandProjection | Mapping[str, object] | None = None
    evidence: ContainerBuildEvidence | Mapping[str, object] | None = None
    failure: ContainerBuildFailure | Mapping[str, object] | None = None
    schema_version: int = CONTAINER_BUILD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        target_name = _build_target_name(
            self.target_name,
            path="ContainerBuildResult.target_name",
        )
        status = _build_status(self.status, path="ContainerBuildResult.status")
        output = (
            self.output
            if isinstance(self.output, ContainerBuildOutputRef) or self.output is None
            else ContainerBuildOutputRef.from_dict(self.output)
        )
        build_key = (
            self.build_key
            if isinstance(self.build_key, ContainerBuildKeySummary)
            or self.build_key is None
            else ContainerBuildKeySummary.from_dict(self.build_key)
        )
        command = (
            self.command
            if isinstance(self.command, ContainerBuildCommandProjection)
            or self.command is None
            else ContainerBuildCommandProjection.from_dict(self.command)
        )
        evidence = (
            self.evidence
            if isinstance(self.evidence, ContainerBuildEvidence)
            or self.evidence is None
            else ContainerBuildEvidence.from_dict(self.evidence)
        )
        failure = (
            self.failure
            if isinstance(self.failure, ContainerBuildFailure) or self.failure is None
            else ContainerBuildFailure.from_dict(self.failure)
        )
        if status is ContainerBuildStatus.FAILED and failure is None:
            raise ContainerOptionError(
                "ContainerBuildResult.failure is required when status is failed"
            )
        if status is not ContainerBuildStatus.FAILED and failure is not None:
            raise ContainerOptionError(
                "ContainerBuildResult.failure is only allowed when status is failed"
            )
        if (
            status in {ContainerBuildStatus.BUILT, ContainerBuildStatus.REUSED}
            and output is None
        ):
            raise ContainerOptionError(
                "ContainerBuildResult.output is required when status is built or reused"
            )
        if build_key is not None and build_key.target_name != target_name:
            raise ContainerOptionError(
                "ContainerBuildResult.build_key target_name must match target_name"
            )
        object.__setattr__(
            self,
            "schema_version",
            _schema_version(
                self.schema_version,
                path="ContainerBuildResult.schema_version",
            ),
        )
        object.__setattr__(self, "target_name", target_name)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "output", output)
        object.__setattr__(self, "build_key", build_key)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "failure", failure)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "target_name": self.target_name,
            "status": cast(ContainerBuildStatus, self.status).value,
            "output": (
                None
                if self.output is None
                else cast(ContainerBuildOutputRef, self.output).to_dict()
            ),
            "build_key": (
                None
                if self.build_key is None
                else cast(ContainerBuildKeySummary, self.build_key).to_dict()
            ),
            "command": (
                None
                if self.command is None
                else cast(ContainerBuildCommandProjection, self.command).to_dict()
            ),
            "evidence": (
                None
                if self.evidence is None
                else cast(ContainerBuildEvidence, self.evidence).to_dict()
            ),
            "failure": (
                None
                if self.failure is None
                else cast(ContainerBuildFailure, self.failure).to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ContainerBuildResult":
        mapping = _mapping(data, path="ContainerBuildResult")
        _reject_unknown(mapping, _BUILD_RESULT_FIELDS, path="ContainerBuildResult")
        _require_fields(
            mapping,
            {"target_name", "status"},
            path="ContainerBuildResult",
        )
        return cls(
            schema_version=_schema_version(
                mapping.get("schema_version", CONTAINER_BUILD_SCHEMA_VERSION),
                path="ContainerBuildResult.schema_version",
            ),
            target_name=_string(
                mapping["target_name"],
                path="ContainerBuildResult.target_name",
            ),
            status=_string(mapping["status"], path="ContainerBuildResult.status"),
            output=cast(Mapping[str, object] | None, mapping.get("output")),
            build_key=cast(Mapping[str, object] | None, mapping.get("build_key")),
            command=cast(Mapping[str, object] | None, mapping.get("command")),
            evidence=cast(Mapping[str, object] | None, mapping.get("evidence")),
            failure=cast(Mapping[str, object] | None, mapping.get("failure")),
        )


def parse_container_options(data: object) -> ContainerOptions:
    """Parse ``adapter_options.container`` into shared container records."""

    return ContainerOptions.from_dict(data)


def parse_container_build_options(data: object | None) -> ContainerBuildOptions:
    """Parse ``adapter_options.container_build`` into shared build records."""

    return ContainerBuildOptions.from_dict(data)


def build_container_build_key(
    target: ContainerBuildTarget | Mapping[str, object],
) -> ContainerBuildKeySummary:
    """Build a deterministic local key summary without probing external sources."""

    parsed = (
        target
        if isinstance(target, ContainerBuildTarget)
        else ContainerBuildTarget.from_dict(target)
    )
    digest_fields = {
        "schema_version": CONTAINER_BUILD_SCHEMA_VERSION,
        "target": parsed.to_dict(),
    }
    fields = {
        "schema_version": CONTAINER_BUILD_SCHEMA_VERSION,
        "target": parsed.to_redacted_metadata(),
    }
    digest = hash_mapping(digest_fields)
    return ContainerBuildKeySummary(
        target_name=parsed.name,
        digest=digest,
        fields=fields,
    )


class ContainerBuilder(Protocol):
    """Protocol implemented by local Docker, Apptainer, or fake builders."""

    def build(self, request: ContainerBuildRequest) -> ContainerBuildResult:
        """Build or reuse one target request."""
        ...


class LocalContainerBuildService:
    """Foreground local build dispatcher over runtime-specific builders."""

    def __init__(
        self,
        builders: Mapping[str | ContainerBuildRuntime, ContainerBuilder],
    ) -> None:
        normalized: dict[str, ContainerBuilder] = {}
        for runtime, builder in builders.items():
            runtime_value = _build_runtime(runtime, path="builders key").value
            if not callable(getattr(builder, "build", None)):
                raise ContainerOptionError(
                    f"builder for runtime {runtime_value!r} must provide build()"
                )
            normalized[runtime_value] = builder
        self.builders = MappingProxyType(normalized)

    def build(self, request: ContainerBuildRequest | Mapping[str, object]) -> ContainerBuildResult:
        parsed = (
            request
            if isinstance(request, ContainerBuildRequest)
            else ContainerBuildRequest.from_dict(request)
        )
        target = cast(ContainerBuildTarget, parsed.target)
        runtime = cast(ContainerBuildRuntime, target.runtime).value
        builder = self.builders.get(runtime)
        if builder is None:
            return ContainerBuildResult(
                target_name=target.name,
                status=ContainerBuildStatus.FAILED,
                build_key=parsed.build_key,
                failure=ContainerBuildFailure(
                    code="container_build.builder_unavailable",
                    message=f"no local container builder is registered for {runtime}",
                    details={"runtime": runtime},
                ),
            )
        return builder.build(parsed)

    def build_target(
        self,
        target: ContainerBuildTarget | Mapping[str, object],
        *,
        requested_by: str = "controller",
    ) -> ContainerBuildResult:
        return self.build(
            ContainerBuildRequest(target=target, requested_by=requested_by)
        )

    def build_options(
        self,
        options: ContainerBuildOptions | Mapping[str, object] | None,
        *,
        requested_by: str = "controller",
    ) -> tuple[ContainerBuildResult, ...]:
        parsed = (
            options
            if isinstance(options, ContainerBuildOptions)
            else ContainerBuildOptions.from_dict(options)
        )
        return tuple(
            self.build_target(target, requested_by=requested_by)
            for target in cast(Mapping[str, ContainerBuildTarget], parsed.targets).values()
        )


class FakeContainerBuilder:
    """Deterministic fake builder for policy, service, and integration tests."""

    def __init__(
        self,
        runtime: str | ContainerBuildRuntime,
        *,
        existing_outputs: Sequence[str] = (),
        stale_outputs: Sequence[str] = (),
        failed_targets: Mapping[str, str] | None = None,
    ) -> None:
        self.runtime = _build_runtime(runtime, path="FakeContainerBuilder.runtime")
        self.existing_outputs = {
            _non_empty_string(output, path="FakeContainerBuilder.existing_outputs[]")
            for output in existing_outputs
        }
        self.stale_outputs = {
            _non_empty_string(output, path="FakeContainerBuilder.stale_outputs[]")
            for output in stale_outputs
        }
        self.failed_targets = MappingProxyType(
            dict(
                sorted(
                    _str_mapping(
                        failed_targets or {},
                        path="FakeContainerBuilder.failed_targets",
                    ).items()
                )
            )
        )
        self.calls: list[ContainerBuildRequest] = []

    def build(self, request: ContainerBuildRequest) -> ContainerBuildResult:
        if not isinstance(request, ContainerBuildRequest):
            raise ContainerOptionError("FakeContainerBuilder.build requires request")
        target = cast(ContainerBuildTarget, request.target)
        runtime = cast(ContainerBuildRuntime, target.runtime)
        if runtime is not self.runtime:
            return ContainerBuildResult(
                target_name=target.name,
                status=ContainerBuildStatus.FAILED,
                build_key=request.build_key,
                failure=ContainerBuildFailure(
                    code="container_build.runtime_mismatch",
                    message=(
                        "fake builder runtime does not match target runtime: "
                        f"{self.runtime.value} != {runtime.value}"
                    ),
                    details={"builder_runtime": self.runtime.value, "runtime": runtime.value},
                ),
            )
        self.calls.append(request)
        output = cast(ContainerBuildOutputRef, target.output)
        output_id = container_build_output_identity(output)
        decision = evaluate_container_build_policy(
            target,
            output_exists=output_id in self.existing_outputs,
            source_stale=output_id in self.stale_outputs,
        )
        evidence = ContainerBuildEvidence(
            builder=f"fake-{runtime.value}",
            metadata={
                "decision": decision.to_dict(),
                "output": output.to_redacted_metadata(),
            },
        )
        if decision.action is ContainerBuildAction.REUSE:
            return ContainerBuildResult(
                target_name=target.name,
                status=ContainerBuildStatus.REUSED,
                output=output,
                build_key=request.build_key,
                evidence=evidence,
            )
        if decision.action is ContainerBuildAction.FAIL:
            return _build_failure_result(
                request=request,
                code="container_build.policy_missing_output",
                message=decision.reason,
                details={"decision": decision.to_dict()},
                evidence=evidence,
            )
        failure_message = self.failed_targets.get(target.name)
        command = ContainerBuildCommandProjection(
            argv=(f"fake-{runtime.value}-build", REDACTED_VALUE),
            build_arg_names=tuple(target.build_args),
            metadata={"target": target.name, "runtime": runtime.value},
        )
        if failure_message is not None:
            return _build_failure_result(
                request=request,
                code="container_build.fake_failed",
                message=failure_message,
                details={"target": target.name, "runtime": runtime.value},
                command=command,
                evidence=evidence,
            )
        self.existing_outputs.add(output_id)
        self.stale_outputs.discard(output_id)
        return ContainerBuildResult(
            target_name=target.name,
            status=ContainerBuildStatus.BUILT,
            output=output,
            build_key=request.build_key,
            command=command,
            evidence=evidence,
        )


def evaluate_container_build_policy(
    target: ContainerBuildTarget | Mapping[str, object],
    *,
    output_exists: bool,
    source_stale: bool | None = None,
) -> ContainerBuildPolicyDecision:
    """Return the local build/reuse/fail action for one target."""

    parsed = (
        target
        if isinstance(target, ContainerBuildTarget)
        else ContainerBuildTarget.from_dict(target)
    )
    if not isinstance(output_exists, bool):
        raise ContainerOptionError("output_exists must be a bool")
    if source_stale is not None and not isinstance(source_stale, bool):
        raise ContainerOptionError("source_stale must be a bool or None")
    mode = cast(ContainerBuildPolicy, parsed.policy).mode
    if mode is ContainerBuildPolicyMode.ALWAYS:
        return ContainerBuildPolicyDecision(
            target_name=parsed.name,
            action=ContainerBuildAction.BUILD,
            expected_status=ContainerBuildStatus.BUILT,
            reason="policy always requires a local build",
            output_exists=output_exists,
            source_stale=source_stale,
        )
    if mode is ContainerBuildPolicyMode.NEVER:
        if output_exists:
            return ContainerBuildPolicyDecision(
                target_name=parsed.name,
                action=ContainerBuildAction.REUSE,
                expected_status=ContainerBuildStatus.REUSED,
                reason="policy never reuses the existing local output",
                output_exists=output_exists,
                source_stale=source_stale,
            )
        return ContainerBuildPolicyDecision(
            target_name=parsed.name,
            action=ContainerBuildAction.FAIL,
            expected_status=ContainerBuildStatus.FAILED,
            reason="policy never forbids building a missing local output",
            output_exists=output_exists,
            source_stale=source_stale,
        )
    if not output_exists:
        return ContainerBuildPolicyDecision(
            target_name=parsed.name,
            action=ContainerBuildAction.BUILD,
            expected_status=ContainerBuildStatus.BUILT,
            reason="local output is missing",
            output_exists=output_exists,
            source_stale=source_stale,
        )
    if source_stale is True:
        return ContainerBuildPolicyDecision(
            target_name=parsed.name,
            action=ContainerBuildAction.BUILD,
            expected_status=ContainerBuildStatus.BUILT,
            reason="local output is older than the local source",
            output_exists=output_exists,
            source_stale=source_stale,
        )
    return ContainerBuildPolicyDecision(
        target_name=parsed.name,
        action=ContainerBuildAction.REUSE,
        expected_status=ContainerBuildStatus.REUSED,
        reason="local output exists and no local staleness was detected",
        output_exists=output_exists,
        source_stale=source_stale,
    )


def container_build_output_identity(
    output: ContainerBuildOutputRef | Mapping[str, object],
) -> str:
    """Return the local identity string used by policy probes."""

    parsed = (
        output
        if isinstance(output, ContainerBuildOutputRef)
        else ContainerBuildOutputRef.from_dict(output)
    )
    if parsed.reference is not None:
        return parsed.reference
    if parsed.path is not None:
        return parsed.path
    raise ContainerOptionError("ContainerBuildOutputRef has no identity")


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
            item if isinstance(item, ContainerMount) else ContainerMount.from_dict(item)
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


def _str_sequence_tuple(value: object, *, path: str) -> tuple[str, ...]:
    items = _sequence(value, path=path)
    return tuple(
        _non_empty_string(item, path=f"{path}[{index}]")
        for index, item in enumerate(items)
    )


def _plain_string_list(values: Sequence[str]) -> list[PlainData]:
    return [value for value in values]


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


def _schema_version(value: object, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContainerOptionError(f"{path} must be an integer")
    if value != CONTAINER_BUILD_SCHEMA_VERSION:
        raise ContainerOptionError(f"{path} must be {CONTAINER_BUILD_SCHEMA_VERSION}")
    return value


def _build_runtime(
    value: ContainerBuildRuntime | str, *, path: str
) -> ContainerBuildRuntime:
    if isinstance(value, ContainerBuildRuntime):
        return value
    if not isinstance(value, str):
        raise ContainerOptionError(f"{path} must be a string")
    try:
        return ContainerBuildRuntime(value)
    except ValueError as exc:
        valid = ", ".join(runtime.value for runtime in ContainerBuildRuntime)
        raise ContainerOptionError(f"{path} must be one of: {valid}") from exc


def _build_source_kind(
    value: ContainerBuildSourceKind | str,
    *,
    path: str,
) -> ContainerBuildSourceKind:
    if isinstance(value, ContainerBuildSourceKind):
        return value
    if not isinstance(value, str):
        raise ContainerOptionError(f"{path} must be a string")
    try:
        return ContainerBuildSourceKind(value)
    except ValueError as exc:
        valid = ", ".join(kind.value for kind in ContainerBuildSourceKind)
        raise ContainerOptionError(f"{path} must be one of: {valid}") from exc


def _build_output_kind(
    value: ContainerBuildOutputKind | str,
    *,
    path: str,
) -> ContainerBuildOutputKind:
    if isinstance(value, ContainerBuildOutputKind):
        return value
    if not isinstance(value, str):
        raise ContainerOptionError(f"{path} must be a string")
    try:
        return ContainerBuildOutputKind(value)
    except ValueError as exc:
        valid = ", ".join(kind.value for kind in ContainerBuildOutputKind)
        raise ContainerOptionError(f"{path} must be one of: {valid}") from exc


def _build_policy_mode(
    value: ContainerBuildPolicyMode | str,
    *,
    path: str,
) -> ContainerBuildPolicyMode:
    if isinstance(value, ContainerBuildPolicyMode):
        return value
    if not isinstance(value, str):
        raise ContainerOptionError(f"{path} must be a string")
    try:
        return ContainerBuildPolicyMode(value)
    except ValueError as exc:
        valid = ", ".join(mode.value for mode in ContainerBuildPolicyMode)
        raise ContainerOptionError(f"{path} must be one of: {valid}") from exc


def _build_status(
    value: ContainerBuildStatus | str, *, path: str
) -> ContainerBuildStatus:
    if isinstance(value, ContainerBuildStatus):
        return value
    if not isinstance(value, str):
        raise ContainerOptionError(f"{path} must be a string")
    try:
        return ContainerBuildStatus(value)
    except ValueError as exc:
        valid = ", ".join(status.value for status in ContainerBuildStatus)
        raise ContainerOptionError(f"{path} must be one of: {valid}") from exc


def _build_action(
    value: ContainerBuildAction | str,
    *,
    path: str,
) -> ContainerBuildAction:
    if isinstance(value, ContainerBuildAction):
        return value
    if not isinstance(value, str):
        raise ContainerOptionError(f"{path} must be a string")
    try:
        return ContainerBuildAction(value)
    except ValueError as exc:
        valid = ", ".join(action.value for action in ContainerBuildAction)
        raise ContainerOptionError(f"{path} must be one of: {valid}") from exc


def _validate_policy_decision_status(
    *,
    action: ContainerBuildAction,
    status: ContainerBuildStatus,
) -> None:
    expected = {
        ContainerBuildAction.BUILD: ContainerBuildStatus.BUILT,
        ContainerBuildAction.REUSE: ContainerBuildStatus.REUSED,
        ContainerBuildAction.FAIL: ContainerBuildStatus.FAILED,
    }[action]
    if status is not expected:
        raise ContainerOptionError(
            "ContainerBuildPolicyDecision.expected_status must be "
            f"{expected.value!r} for action {action.value!r}"
        )


def _build_failure_result(
    *,
    request: ContainerBuildRequest,
    code: str,
    message: str,
    details: Mapping[str, PlainData] | None = None,
    command: ContainerBuildCommandProjection | None = None,
    evidence: ContainerBuildEvidence | None = None,
) -> ContainerBuildResult:
    target = cast(ContainerBuildTarget, request.target)
    return ContainerBuildResult(
        target_name=target.name,
        status=ContainerBuildStatus.FAILED,
        build_key=request.build_key,
        command=command,
        evidence=evidence,
        failure=ContainerBuildFailure(
            code=code,
            message=message,
            details=details or {},
        ),
    )


def _validate_build_source_shape(
    *,
    kind: ContainerBuildSourceKind,
    path: str | None,
    uri: str | None,
    context_path: str | None,
    recipe_path: str | None,
) -> None:
    if kind is ContainerBuildSourceKind.DEFINITION_FILE:
        if path is None:
            raise ContainerOptionError(
                "ContainerBuildSource.path is required for definition_file sources"
            )
        if uri is not None or context_path is not None or recipe_path is not None:
            raise ContainerOptionError(
                "definition_file sources only allow path and metadata"
            )
        return
    if kind is ContainerBuildSourceKind.DOCKER_CONTEXT:
        if context_path is None:
            raise ContainerOptionError(
                "ContainerBuildSource.context_path is required for docker_context sources"
            )
        if path is not None or uri is not None:
            raise ContainerOptionError(
                "docker_context sources only allow context_path, recipe_path, and metadata"
            )
        return
    if kind is ContainerBuildSourceKind.LOCAL_PATH:
        if path is None:
            raise ContainerOptionError(
                "ContainerBuildSource.path is required for local_path sources"
            )
        if uri is not None or context_path is not None or recipe_path is not None:
            raise ContainerOptionError(
                "local_path sources only allow path and metadata"
            )
        return
    if uri is None:
        raise ContainerOptionError(
            "ContainerBuildSource.uri is required for uri sources"
        )
    if path is not None or context_path is not None or recipe_path is not None:
        raise ContainerOptionError("uri sources only allow uri and metadata")


def _reject_build_source_fields(
    *,
    kind: ContainerBuildSourceKind,
    mapping: Mapping[str, object],
) -> None:
    allowed = {"schema_version", "kind", "metadata"}
    if kind in {
        ContainerBuildSourceKind.DEFINITION_FILE,
        ContainerBuildSourceKind.LOCAL_PATH,
    }:
        allowed.add("path")
    elif kind is ContainerBuildSourceKind.DOCKER_CONTEXT:
        allowed.update({"context_path", "recipe_path"})
    else:
        allowed.add("uri")
    extra = set(mapping) - allowed
    if extra:
        fields = ", ".join(sorted(extra))
        raise ContainerOptionError(
            f"ContainerBuildSource contains field(s) not allowed for {kind.value}: {fields}"
        )


def _validate_build_output_shape(
    *,
    kind: ContainerBuildOutputKind,
    reference: str | None,
    path: str | None,
) -> None:
    if kind is ContainerBuildOutputKind.DOCKER_IMAGE:
        if reference is None:
            raise ContainerOptionError(
                "ContainerBuildOutputRef.reference is required for docker_image outputs"
            )
        if path is not None:
            raise ContainerOptionError("docker_image outputs only allow reference")
        return
    if path is None:
        raise ContainerOptionError(
            "ContainerBuildOutputRef.path is required for apptainer_sif outputs"
        )
    if reference is not None:
        raise ContainerOptionError("apptainer_sif outputs only allow path")


def _reject_build_output_fields(
    *,
    kind: ContainerBuildOutputKind,
    mapping: Mapping[str, object],
) -> None:
    allowed = {"schema_version", "kind", "metadata"}
    if kind is ContainerBuildOutputKind.DOCKER_IMAGE:
        allowed.add("reference")
    else:
        allowed.add("path")
    extra = set(mapping) - allowed
    if extra:
        fields = ", ".join(sorted(extra))
        raise ContainerOptionError(
            f"ContainerBuildOutputRef contains field(s) not allowed for {kind.value}: {fields}"
        )


def _validate_runtime_output_compatibility(
    *,
    runtime: ContainerBuildRuntime,
    output: ContainerBuildOutputRef,
) -> None:
    output_kind = cast(ContainerBuildOutputKind, output.kind)
    if runtime is ContainerBuildRuntime.DOCKER:
        expected = ContainerBuildOutputKind.DOCKER_IMAGE
    else:
        expected = ContainerBuildOutputKind.APPTAINER_SIF
    if output_kind is not expected:
        raise ContainerOptionError(
            f"ContainerBuildTarget.output kind {output_kind.value!r} is not compatible "
            f"with runtime {runtime.value!r}"
        )


def _build_targets(
    value: Mapping[str, ContainerBuildTarget | Mapping[str, object]],
    *,
    path: str,
) -> dict[str, ContainerBuildTarget]:
    mapping = _mapping(value, path=path)
    targets: dict[str, ContainerBuildTarget] = {}
    for key, item in mapping.items():
        target_name = _build_target_name(key, path=f"{path} key")
        if isinstance(item, ContainerBuildTarget):
            target = item
        else:
            target_mapping = _mapping(item, path=f"{path}[{target_name!r}]")
            target = ContainerBuildTarget.from_dict(
                {**target_mapping, "name": target_mapping.get("name", key)}
            )
        if target.name != target_name:
            raise ContainerOptionError(
                f"{path}[{target_name!r}].name must match its key"
            )
        targets[target_name] = target
    return targets


def _build_target_name(value: object, *, path: str) -> str:
    text = _non_empty_string(value, path=path)
    if text in {".", ".."}:
        raise ContainerOptionError(f"{path} cannot be '.' or '..'")
    if "/" in text or "\\" in text:
        raise ContainerOptionError(f"{path} cannot contain path separators")
    if any(ch.isspace() for ch in text):
        raise ContainerOptionError(f"{path} cannot contain whitespace")
    if not all(ch.isalnum() or ch in {"_", "-", "."} for ch in text):
        raise ContainerOptionError(
            f"{path} may only contain letters, numbers, '.', '_', or '-'"
        )
    return text


def _portable_path(value: object, *, path: str) -> str:
    text = _non_empty_string(value, path=path)
    if "\\" in text:
        raise ContainerOptionError(f"{path} must use POSIX '/' separators")
    if "\x00" in text:
        raise ContainerOptionError(f"{path} cannot contain NUL")
    if text == ".":
        return text
    if _has_unsafe_parts(text):
        raise ContainerOptionError(f"{path} cannot contain '.' or '..' path parts")
    if text in {".", ".."}:
        raise ContainerOptionError(f"{path} cannot be '.' or '..'")
    return text


def _optional_portable_path(value: object | None, *, path: str) -> str | None:
    if value is None:
        return None
    return _portable_path(value, path=path)


def _optional_uri(value: object | None, *, path: str) -> str | None:
    if value is None:
        return None
    text = _non_empty_string(value, path=path)
    if "\x00" in text:
        raise ContainerOptionError(f"{path} cannot contain NUL")
    if "://" not in text:
        raise ContainerOptionError(f"{path} must include a URI scheme")
    return text


def _optional_non_empty_string(value: object | None, *, path: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, path=path)


def _frozen_plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    mapping = _plain_mapping(value, path=path)
    return cast(
        Mapping[str, PlainData],
        freeze_plain_data(_sorted_plain_mapping(mapping), path=path),
    )


def _thaw_plain_mapping(
    value: Mapping[str, PlainData], *, path: str
) -> dict[str, PlainData]:
    thawed = thaw_plain_data(value, path=path)
    if not isinstance(thawed, Mapping):
        raise ContainerOptionError(f"{path} must be a mapping")
    return _sorted_plain_mapping(cast(Mapping[str, PlainData], thawed))


def _sorted_plain_mapping(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return {key: _sort_plain_value(value[key]) for key in sorted(value)}


def _sort_plain_value(value: PlainData) -> PlainData:
    if isinstance(value, dict):
        return _sorted_plain_mapping(value)
    if isinstance(value, list):
        return [_sort_plain_value(item) for item in value]
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
    "CONTAINER_BUILD_SCHEMA_VERSION",
    "ContainerBuildAction",
    "ContainerBuildCommandProjection",
    "ContainerBuildEvidence",
    "ContainerBuildFailure",
    "ContainerBuildKeySummary",
    "ContainerBuildOptions",
    "ContainerBuildOutputKind",
    "ContainerBuildOutputRef",
    "ContainerBuildPolicy",
    "ContainerBuildPolicyDecision",
    "ContainerBuildPolicyMode",
    "ContainerBuildRequest",
    "ContainerBuildResult",
    "ContainerBuildRuntime",
    "ContainerBuildSource",
    "ContainerBuildSourceKind",
    "ContainerBuildStatus",
    "ContainerBuildTarget",
    "ContainerBuilder",
    "ContainerEnvironment",
    "ContainerImageReference",
    "FakeContainerBuilder",
    "LocalContainerBuildService",
    "ContainerMount",
    "ContainerMountMode",
    "ContainerOptionError",
    "ContainerOptions",
    "ContainerPathParitySummary",
    "ContainerResourceIntent",
    "REDACTED_VALUE",
    "build_container_build_key",
    "container_build_output_identity",
    "evaluate_container_build_policy",
    "parse_container_build_options",
    "parse_container_options",
    "summarize_path_parity",
    "validate_reserved_docker_options",
]
