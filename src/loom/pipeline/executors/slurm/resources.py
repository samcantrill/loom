"""Generic resource to SBATCH directive mapping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.serialization import PlainData

from .errors import SlurmResourceMappingError
from .options import SlurmOptions


@dataclass(frozen=True, slots=True)
class SlurmSbatchDirective:
    """Structured SBATCH directive summary without rendering syntax."""

    name: str
    value: str | bool
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "name", _required_string(self.name, path="SlurmSbatchDirective.name")
        )
        if not (self.value is True or isinstance(self.value, str)):
            raise SlurmResourceMappingError(
                "SlurmSbatchDirective.value must be a string or true"
            )
        if isinstance(self.value, str) and not self.value:
            raise SlurmResourceMappingError(
                "SlurmSbatchDirective.value must not be an empty string"
            )
        object.__setattr__(
            self,
            "source",
            _required_string(self.source, path="SlurmSbatchDirective.source"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {"name": self.name, "value": self.value, "source": self.source}

    @classmethod
    def from_dict(
        cls,
        data: object,
        *,
        path: str = "SlurmSbatchDirective",
    ) -> "SlurmSbatchDirective":
        mapping = _mapping(data, path=path)
        _reject_unknown(mapping, {"name", "value", "source"}, path=path)
        missing = {"name", "value", "source"} - set(mapping)
        if missing:
            fields = ", ".join(sorted(missing))
            raise SlurmResourceMappingError(
                f"{path} missing required field(s): {fields}"
            )
        value = mapping["value"]
        if not (value is True or isinstance(value, str)):
            raise SlurmResourceMappingError(f"{path}.value must be a string or true")
        return cls(
            name=_required_string(mapping["name"], path=f"{path}.name"),
            value=value,
            source=_required_string(mapping["source"], path=f"{path}.source"),
        )


def map_slurm_resources(
    resources: ResourceRequest | Mapping[str, ResourceEntry],
    *,
    options: SlurmOptions | None = None,
    path: str = "resources.entries",
) -> tuple[SlurmSbatchDirective, ...]:
    """Map canonical Loom resources to deterministic SBATCH directive records."""

    option_values = SlurmOptions() if options is None else options
    entries = resources.entries if isinstance(resources, ResourceRequest) else resources
    directives: list[SlurmSbatchDirective] = []
    for key, entry in sorted(entries.items()):
        if not isinstance(entry, ResourceEntry):
            raise SlurmResourceMappingError(f"{path}[{key!r}] must be a ResourceEntry")
        entry_path = f"{path}[{key!r}]"
        if key != entry.kind:
            raise SlurmResourceMappingError(
                f"{entry_path}.kind must match its mapping key"
            )
        if entry.kind == "cpu":
            directive = _map_cpu(entry, options=option_values, path=entry_path)
        elif entry.kind == "memory":
            directive = _map_memory(entry, options=option_values, path=entry_path)
        elif entry.kind == "gpu":
            directive = _map_gpu(entry, options=option_values, path=entry_path)
        else:
            raise SlurmResourceMappingError(
                f"{entry_path}: unsupported SLURM resource kind {entry.kind!r}"
            )
        if directive is not None:
            directives.append(directive)
    return tuple(directives)


def build_sbatch_directives(
    *,
    options: SlurmOptions | None = None,
    resources: ResourceRequest | Mapping[str, ResourceEntry] | None = None,
) -> tuple[SlurmSbatchDirective, ...]:
    """Combine modeled options, generic resources, and extra SBATCH directives."""

    option_values = SlurmOptions() if options is None else options
    directives: list[SlurmSbatchDirective] = [
        SlurmSbatchDirective(name=name, value=value, source="option")
        for name, value in sorted(option_values.modeled_sbatch_directives().items())
    ]
    if resources is not None:
        directives.extend(map_slurm_resources(resources, options=option_values))
    directives.extend(
        SlurmSbatchDirective(name=name, value=value, source="extra_sbatch")
        for name, value in sorted(option_values.extra_sbatch.items())
    )
    return tuple(directives)


def _map_cpu(
    entry: ResourceEntry,
    *,
    options: SlurmOptions,
    path: str,
) -> SlurmSbatchDirective:
    if options.cpus_per_task is not None:
        raise SlurmResourceMappingError(
            f"{path} conflicts with SlurmOptions.cpus_per_task"
        )
    if entry.unit not in {None, "count"}:
        raise SlurmResourceMappingError(f"{path}.unit must be omitted or 'count'")
    amount = _positive_int(entry.amount, path=f"{path}.amount")
    return SlurmSbatchDirective(
        name="cpus-per-task",
        value=str(amount),
        source="resource:cpu",
    )


def _map_memory(
    entry: ResourceEntry,
    *,
    options: SlurmOptions,
    path: str,
) -> SlurmSbatchDirective:
    if options.mem is not None:
        raise SlurmResourceMappingError(f"{path} conflicts with SlurmOptions.mem")
    if options.mem_per_cpu is not None:
        raise SlurmResourceMappingError(
            f"{path} conflicts with SlurmOptions.mem_per_cpu"
        )
    amount = _positive_int(entry.amount, path=f"{path}.amount")
    if entry.unit == "MiB":
        value = f"{amount}M"
    elif entry.unit == "GiB":
        value = f"{amount}G"
    elif entry.unit == "TiB":
        value = f"{amount}T"
    else:
        raise SlurmResourceMappingError(
            f"{path}.unit must be one of MiB, GiB, TiB for deterministic SLURM mapping"
        )
    return SlurmSbatchDirective(name="mem", value=value, source="resource:memory")


def _map_gpu(
    entry: ResourceEntry,
    *,
    options: SlurmOptions,
    path: str,
) -> SlurmSbatchDirective | None:
    if options.gres is not None:
        raise SlurmResourceMappingError(f"{path} conflicts with SlurmOptions.gres")
    if entry.unit not in {None, "count"}:
        raise SlurmResourceMappingError(f"{path}.unit must be omitted or 'count'")
    amount = _non_negative_int(entry.amount, path=f"{path}.amount")
    if amount == 0:
        return None
    return SlurmSbatchDirective(
        name="gres",
        value=f"gpu:{amount}",
        source="resource:gpu",
    )


def _positive_int(value: int | float, *, path: str) -> int:
    amount = _integer(value, path=path)
    if amount <= 0:
        raise SlurmResourceMappingError(f"{path} must be a positive integer")
    return amount


def _non_negative_int(value: int | float, *, path: str) -> int:
    amount = _integer(value, path=path)
    if amount < 0:
        raise SlurmResourceMappingError(f"{path} must be a non-negative integer")
    return amount


def _integer(value: int | float, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SlurmResourceMappingError(f"{path} must be an integer")
    return value


def _required_string(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise SlurmResourceMappingError(f"{path} must be a non-empty string")
    return value


def _mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SlurmResourceMappingError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise SlurmResourceMappingError(f"{path} must use string keys")
    return cast(Mapping[str, object], value)


def _reject_unknown(
    mapping: Mapping[str, object],
    allowed: set[str],
    *,
    path: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise SlurmResourceMappingError(f"{path} contains unknown field(s): {fields}")


__all__ = [
    "SlurmSbatchDirective",
    "build_sbatch_directives",
    "map_slurm_resources",
]
