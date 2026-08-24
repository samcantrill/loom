"""Runtime resource foundation models."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import InitVar, dataclass, field
from types import MappingProxyType
from typing import cast

from loom.serialization import (
    PlainData,
    freeze_plain_data,
    load_versioned_document,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError, SchemaVersionError

from .errors import RuntimeResourceError

RESOURCE_SCHEMA_VERSION = 2

_RESOURCE_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_RESOURCE_FIELDS = frozenset({"entries"})
_RESOURCE_ENTRY_FIELDS = frozenset({"kind", "amount", "unit", "attributes"})
_OLD_RESOURCE_FIELDS = frozenset({"cpus", "memory_mb", "gpus", "custom"})


@dataclass(frozen=True, slots=True)
class ResourceEntry:
    kind: str
    amount: int | float
    unit: str | None = None
    attributes: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            validate_resource_kind(self.kind, path="ResourceEntry.kind"),
        )
        object.__setattr__(
            self,
            "amount",
            _numeric_amount(self.amount, path=f"ResourceEntry[{self.kind!r}].amount"),
        )
        object.__setattr__(
            self,
            "unit",
            _optional_unit(self.unit, path=f"ResourceEntry[{self.kind!r}].unit"),
        )
        object.__setattr__(
            self,
            "attributes",
            freeze_plain_data(
                _plain_mapping(
                    self.attributes,
                    path=f"ResourceEntry[{self.kind!r}].attributes",
                ),
                path=f"ResourceEntry[{self.kind!r}].attributes",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind,
            "amount": self.amount,
            "unit": self.unit,
            "attributes": thaw_plain_data(
                self.attributes,
                path=f"ResourceEntry[{self.kind!r}].attributes",
            ),
        }

    @classmethod
    def from_dict(cls, data: object, *, path: str = "ResourceEntry") -> "ResourceEntry":
        mapping = _plain_mapping(data, path=path)
        _reject_old_resource_fields(mapping, path=path)
        unknown = set(mapping) - _RESOURCE_ENTRY_FIELDS
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise RuntimeResourceError(f"{path} contains unknown field(s): {fields}")
        missing = {"kind", "amount"} - set(mapping)
        if missing:
            fields = ", ".join(sorted(missing))
            raise RuntimeResourceError(f"{path} missing required field(s): {fields}")
        return cls(
            kind=_string_value(mapping["kind"], path=f"{path}.kind"),
            amount=_numeric_amount(mapping["amount"], path=f"{path}.amount"),
            unit=_optional_unit(mapping.get("unit"), path=f"{path}.unit"),
            attributes=_plain_mapping(
                mapping.get("attributes", {}), path=f"{path}.attributes"
            ),
        )


ResourceValidator = Callable[[ResourceEntry, str], None]


@dataclass(frozen=True, slots=True)
class ResourceValidatorRegistry:
    """Immutable resource validator registry."""

    validators: Mapping[str, ResourceValidator] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[str, ResourceValidator] = {}
        for kind, validator in self.validators.items():
            validate_resource_kind(kind, path=f"ResourceValidatorRegistry[{kind!r}]")
            if not callable(validator):
                raise RuntimeResourceError(
                    f"ResourceValidatorRegistry[{kind!r}] must be callable"
                )
            normalized[kind] = validator
        object.__setattr__(self, "validators", MappingProxyType(normalized))

    def with_validator(
        self,
        kind: str,
        validator: ResourceValidator,
    ) -> "ResourceValidatorRegistry":
        normalized_kind = validate_resource_kind(kind, path="resource validator kind")
        if normalized_kind in self.validators:
            raise RuntimeResourceError(
                f"resource validator already registered for kind {normalized_kind!r}"
            )
        return ResourceValidatorRegistry(
            {**self.validators, normalized_kind: validator}
        )

    def compose(
        self,
        *registries: "ResourceValidatorRegistry",
    ) -> "ResourceValidatorRegistry":
        composed: ResourceValidatorRegistry = self
        for registry in registries:
            if not isinstance(registry, ResourceValidatorRegistry):
                raise RuntimeResourceError(
                    "ResourceValidatorRegistry.compose requires ResourceValidatorRegistry instances"
                )
            for kind, validator in registry.validators.items():
                composed = composed.with_validator(kind, validator)
        return composed

    def validate(self, entry: ResourceEntry, *, path: str) -> None:
        validator = self.validators.get(entry.kind)
        if validator is None:
            raise RuntimeResourceError(
                f"{path}: unregistered resource kind {entry.kind!r}"
            )
        validator(entry, path)


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    entries: Mapping[str, ResourceEntry] = field(default_factory=dict)
    schema_version: int = RESOURCE_SCHEMA_VERSION
    validator_registry: InitVar[ResourceValidatorRegistry | None] = None

    def __post_init__(
        self, validator_registry: ResourceValidatorRegistry | None
    ) -> None:
        _require_schema_version(self.schema_version)
        registry = (
            DEFAULT_RESOURCE_VALIDATOR_REGISTRY
            if validator_registry is None
            else validator_registry
        )
        if not isinstance(registry, ResourceValidatorRegistry):
            raise RuntimeResourceError(
                "ResourceRequest.validator_registry must be a ResourceValidatorRegistry"
            )
        entries = _coerce_entries(self.entries, path="ResourceRequest.entries")
        _validate_entries(entries, registry=registry, path="ResourceRequest.entries")
        object.__setattr__(
            self, "entries", MappingProxyType(dict(sorted(entries.items())))
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "entries": {
                kind: entry.to_dict() for kind, entry in sorted(self.entries.items())
            },
        }

    @classmethod
    def from_dict(
        cls,
        data: object,
        *,
        registry: ResourceValidatorRegistry | None = None,
    ) -> "ResourceRequest":
        try:
            mapping = load_versioned_document(
                data,
                current_version=RESOURCE_SCHEMA_VERSION,
                required={"entries"},
                optional=(),
                path="ResourceRequest",
            )
        except SchemaVersionError as exc:
            raise RuntimeResourceError(f"ResourceRequest.from_dict: {exc}") from exc
        _reject_old_resource_fields(mapping, path="ResourceRequest")
        return cls(
            schema_version=_require_schema_version(mapping["schema_version"]),
            entries=cast(
                Mapping[str, ResourceEntry],
                _entry_mapping(mapping["entries"], path="ResourceRequest.entries"),
            ),
            validator_registry=registry,
        )


def validate_resource_kind(value: object, *, path: str = "resource kind") -> str:
    if not isinstance(value, str):
        raise RuntimeResourceError(f"{path} must be a string")
    if not _RESOURCE_KIND_PATTERN.fullmatch(value):
        raise RuntimeResourceError(
            f"{path} must be lowercase ASCII identifier segment(s) separated by dots"
        )
    return value


def parse_resource_request(
    data: object | None,
    *,
    registry: ResourceValidatorRegistry | None = None,
) -> ResourceRequest:
    """Parse authored stage resources without requiring a schema wrapper."""

    if data is None:
        return ResourceRequest(validator_registry=registry)
    mapping = _plain_mapping(data, path="resources")
    _reject_old_resource_fields(mapping, path="resources")
    if not mapping:
        return ResourceRequest(validator_registry=registry)
    unknown = set(mapping) - _RESOURCE_FIELDS
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise RuntimeResourceError(f"resources contains unknown field(s): {fields}")
    if "entries" not in mapping:
        raise RuntimeResourceError("resources.entries is required")
    return ResourceRequest(
        entries=cast(
            Mapping[str, ResourceEntry],
            _entry_mapping(mapping["entries"], path="resources.entries"),
        ),
        validator_registry=registry,
    )


def _builtin_registry() -> ResourceValidatorRegistry:
    return (
        ResourceValidatorRegistry()
        .with_validator("cpu", _validate_cpu)
        .with_validator("memory", _validate_memory)
        .with_validator("gpu", _validate_gpu)
    )


def _validate_cpu(entry: ResourceEntry, path: str) -> None:
    _require_no_attributes(entry, path=path)
    _require_count_unit(entry, path=path)
    if not isinstance(entry.amount, int):
        raise RuntimeResourceError(f"{path}.amount must be a positive integer")
    if entry.amount <= 0:
        raise RuntimeResourceError(f"{path}.amount must be a positive integer")


def _validate_memory(entry: ResourceEntry, path: str) -> None:
    _require_no_attributes(entry, path=path)
    if entry.unit not in {"B", "KiB", "MiB", "GiB", "TiB"}:
        raise RuntimeResourceError(f"{path}.unit must be one of B, KiB, MiB, GiB, TiB")
    if entry.amount <= 0:
        raise RuntimeResourceError(f"{path}.amount must be positive")


def _validate_gpu(entry: ResourceEntry, path: str) -> None:
    mode = entry.attributes.get("allocation_mode", "exclusive")
    if mode == "exclusive":
        if entry.unit not in {None, "count"}:
            raise RuntimeResourceError(f"{path}.unit must be count")
        # The legacy codec remains readable; managed resolution rejects zero.
        if not entry.attributes and entry.amount == 0:
            return
        if (
            not isinstance(entry.amount, int)
            or isinstance(entry.amount, bool)
            or entry.amount <= 0
        ):
            raise RuntimeResourceError(
                f"{path}.amount must be a non-negative integer (positive for managed GPU requests)"
            )
        _validate_gpu_attributes(
            entry,
            path,
            {"allocation_mode", "minimum_vram", "models", "features", "fabric_group"},
        )
        _validate_gpu_minimum_vram(entry.attributes.get("minimum_vram"), path)
        _validate_gpu_strings(entry.attributes.get("models"), path, "models")
        _validate_gpu_strings(entry.attributes.get("features"), path, "features")
        fabric_group = entry.attributes.get("fabric_group")
        if fabric_group is not None and (
            not isinstance(fabric_group, str) or not fabric_group
        ):
            raise RuntimeResourceError(f"{path}.attributes.fabric_group is invalid")
        return
    if mode == "vram_share":
        if entry.unit not in {"B", "KiB", "MiB", "GiB", "TiB"}:
            raise RuntimeResourceError(f"{path}.unit must be a binary VRAM byte unit")
        if (
            not isinstance(entry.amount, int)
            or isinstance(entry.amount, bool)
            or entry.amount <= 0
        ):
            raise RuntimeResourceError(
                f"{path}.amount must be an exact positive integer"
            )
        _validate_gpu_attributes(
            entry, path, {"allocation_mode", "provider", "device_ids"}
        )
        _gpu_provider(entry, path)
        _validate_gpu_strings(entry.attributes.get("device_ids"), path, "device_ids")
        return
    if mode == "provider_fraction":
        if entry.unit != "share":
            raise RuntimeResourceError(f"{path}.unit must be share")
        denominator = entry.attributes.get("share_denominator")
        if (
            not isinstance(entry.amount, int)
            or isinstance(entry.amount, bool)
            or entry.amount <= 0
            or not isinstance(denominator, int)
            or isinstance(denominator, bool)
            or denominator <= 0
        ):
            raise RuntimeResourceError(
                f"{path} provider_fraction requires positive integer amount and share_denominator"
            )
        _validate_gpu_attributes(
            entry,
            path,
            {"allocation_mode", "provider", "share_denominator", "device_ids"},
        )
        _gpu_provider(entry, path)
        _validate_gpu_strings(entry.attributes.get("device_ids"), path, "device_ids")
        return
    raise RuntimeResourceError(f"{path}.attributes.allocation_mode is unsupported")


def _validate_gpu_attributes(
    entry: ResourceEntry, path: str, allowed: set[str]
) -> None:
    unknown = set(entry.attributes) - allowed
    if unknown:
        raise RuntimeResourceError(
            f"{path}.attributes contains unsupported GPU field(s): {', '.join(sorted(unknown))}"
        )


def _gpu_provider(entry: ResourceEntry, path: str) -> None:
    provider = entry.attributes.get("provider")
    if not isinstance(provider, str) or not provider:
        raise RuntimeResourceError(f"{path}.attributes.provider is required")


def _validate_gpu_minimum_vram(value: object, path: str) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping) or set(value) != {"amount", "unit"}:
        raise RuntimeResourceError(f"{path}.attributes.minimum_vram is invalid")
    amount, unit = value["amount"], value["unit"]
    if (
        not isinstance(amount, int)
        or isinstance(amount, bool)
        or amount <= 0
        or unit not in {"B", "KiB", "MiB", "GiB", "TiB"}
    ):
        raise RuntimeResourceError(f"{path}.attributes.minimum_vram is invalid")


def _validate_gpu_strings(value: object, path: str, field: str) -> None:
    if value is None:
        return
    if (
        not isinstance(value, (list, tuple))
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise RuntimeResourceError(f"{path}.attributes.{field} is invalid")


def _require_no_attributes(entry: ResourceEntry, *, path: str) -> None:
    if entry.attributes:
        raise RuntimeResourceError(f"{path}.attributes must be empty")


def _require_count_unit(entry: ResourceEntry, *, path: str) -> None:
    if entry.unit not in {None, "count"}:
        raise RuntimeResourceError(f"{path}.unit must be omitted or 'count'")


def _validate_entries(
    entries: Mapping[str, ResourceEntry],
    *,
    registry: ResourceValidatorRegistry,
    path: str,
) -> None:
    for key, entry in entries.items():
        normalized_key = validate_resource_kind(key, path=f"{path} key")
        if normalized_key != entry.kind:
            raise RuntimeResourceError(
                f"{path}[{key!r}].kind must match its mapping key"
            )
        registry.validate(entry, path=f"{path}[{key!r}]")


def _coerce_entries(
    value: Mapping[str, ResourceEntry | Mapping[str, PlainData]],
    *,
    path: str,
) -> Mapping[str, ResourceEntry]:
    mapping = _entry_mapping(value, path=path)
    return {
        key: entry
        if isinstance(entry, ResourceEntry)
        else ResourceEntry.from_dict(entry, path=f"{path}[{key!r}]")
        for key, entry in mapping.items()
    }


def _entry_mapping(
    value: object, *, path: str
) -> Mapping[str, ResourceEntry | Mapping[str, PlainData]]:
    if not isinstance(value, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise RuntimeResourceError(f"{path} must be a mapping with string keys")
    return cast(Mapping[str, ResourceEntry | Mapping[str, PlainData]], value)


def _require_schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeResourceError("schema_version must be a positive integer")
    if value != RESOURCE_SCHEMA_VERSION:
        raise RuntimeResourceError(
            f"unsupported schema_version {value!r}, expected {RESOURCE_SCHEMA_VERSION}"
        )
    return value


def _numeric_amount(value: object, *, path: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RuntimeResourceError(f"{path} must be a finite numeric amount")
    if isinstance(value, float) and (
        value != value or value == float("inf") or value == float("-inf")
    ):
        raise RuntimeResourceError(f"{path} must be finite")
    return value


def _optional_unit(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    return _string_value(value, path=path)


def _string_value(value: object, *, path: str) -> str:
    if not isinstance(value, str):
        raise RuntimeResourceError(f"{path} must be a string")
    return value


def _plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    try:
        normalized = thaw_plain_data(value, path=path)
    except PlainDataError as exc:
        raise RuntimeResourceError(
            f"{path} must be plain-data-compatible mapping: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _reject_old_resource_fields(mapping: Mapping[str, object], *, path: str) -> None:
    old_fields = set(mapping) & _OLD_RESOURCE_FIELDS
    if old_fields:
        fields = ", ".join(sorted(old_fields))
        raise RuntimeResourceError(f"{path} uses removed resource field(s): {fields}")


DEFAULT_RESOURCE_VALIDATOR_REGISTRY = _builtin_registry()

__all__ = [
    "DEFAULT_RESOURCE_VALIDATOR_REGISTRY",
    "RESOURCE_SCHEMA_VERSION",
    "ResourceEntry",
    "ResourceRequest",
    "ResourceValidator",
    "ResourceValidatorRegistry",
    "parse_resource_request",
    "validate_resource_kind",
]
