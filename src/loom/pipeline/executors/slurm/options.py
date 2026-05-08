"""SLURM dry-run option and command argv contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from loom.serialization import PlainData, load_versioned_document
from loom.serialization.errors import SchemaVersionError

from .errors import SlurmOptionError

SLURM_OPTIONS_SCHEMA_VERSION = 1
DEFAULT_SLURM_LAUNCHER_ARGV = ("loom",)

GENERATED_SBATCH_DIRECTIVES = frozenset({"job-name", "output", "error", "dependency"})
MODELED_SBATCH_DIRECTIVES = frozenset(
    {
        "partition",
        "account",
        "qos",
        "constraint",
        "nodes",
        "ntasks",
        "cpus-per-task",
        "mem",
        "mem-per-cpu",
        "gres",
        "time",
    }
)
RESERVED_SBATCH_DIRECTIVES = GENERATED_SBATCH_DIRECTIVES | MODELED_SBATCH_DIRECTIVES

_OPTIONS_FIELDS = frozenset(
    {
        "schema_version",
        "partition",
        "account",
        "qos",
        "constraint",
        "nodes",
        "ntasks",
        "cpus_per_task",
        "mem",
        "mem_per_cpu",
        "gres",
        "time",
        "prelude",
        "extra_sbatch",
        "launcher_argv",
    }
)
_DIRECTIVE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True, slots=True)
class SlurmCommandArgv:
    """Structured generated command argv record."""

    launcher_argv: Sequence[str] = DEFAULT_SLURM_LAUNCHER_ARGV
    command_args: Sequence[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "launcher_argv",
            _argv_tuple(self.launcher_argv, path="SlurmCommandArgv.launcher_argv"),
        )
        object.__setattr__(
            self,
            "command_args",
            _argv_tuple(
                self.command_args,
                path="SlurmCommandArgv.command_args",
                allow_empty=True,
            ),
        )

    @property
    def argv(self) -> tuple[str, ...]:
        return (*self.launcher_argv, *self.command_args)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "launcher_argv": list(self.launcher_argv),
            "command_args": list(self.command_args),
            "argv": list(self.argv),
        }

    @classmethod
    def from_dict(
        cls, data: object, *, path: str = "SlurmCommandArgv"
    ) -> "SlurmCommandArgv":
        mapping = _mapping(data, path=path)
        _reject_unknown(mapping, {"launcher_argv", "command_args", "argv"}, path=path)
        missing = {"launcher_argv", "command_args"} - set(mapping)
        if missing:
            fields = ", ".join(sorted(missing))
            raise SlurmOptionError(f"{path} missing required field(s): {fields}")
        record = cls(
            launcher_argv=_sequence(
                mapping["launcher_argv"], path=f"{path}.launcher_argv"
            ),
            command_args=_sequence(
                mapping["command_args"], path=f"{path}.command_args"
            ),
        )
        if "argv" in mapping:
            argv = _argv_tuple(
                _sequence(mapping["argv"], path=f"{path}.argv"), path=f"{path}.argv"
            )
            if argv != record.argv:
                raise SlurmOptionError(
                    f"{path}.argv must match launcher_argv + command_args"
                )
        return record


@dataclass(frozen=True, slots=True)
class SlurmOptions:
    """Structured, schema-versioned SLURM dry-run options."""

    partition: str | None = None
    account: str | None = None
    qos: str | None = None
    constraint: str | None = None
    nodes: int | None = None
    ntasks: int | None = None
    cpus_per_task: int | None = None
    mem: str | None = None
    mem_per_cpu: str | None = None
    gres: str | None = None
    time: str | None = None
    prelude: Sequence[str] = ()
    extra_sbatch: Mapping[str, str | bool] = field(default_factory=dict)
    launcher_argv: Sequence[str] = DEFAULT_SLURM_LAUNCHER_ARGV
    schema_version: int = SLURM_OPTIONS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(
                self.schema_version, path="SlurmOptions.schema_version"
            ),
        )
        for field_name in (
            "partition",
            "account",
            "qos",
            "constraint",
            "mem",
            "mem_per_cpu",
            "gres",
            "time",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_string(
                    getattr(self, field_name),
                    path=f"SlurmOptions.{field_name}",
                ),
            )
        for field_name in ("nodes", "ntasks", "cpus_per_task"):
            object.__setattr__(
                self,
                field_name,
                _optional_positive_int(
                    getattr(self, field_name),
                    path=f"SlurmOptions.{field_name}",
                ),
            )
        object.__setattr__(
            self,
            "prelude",
            _string_tuple(self.prelude, path="SlurmOptions.prelude", allow_empty=True),
        )
        object.__setattr__(
            self,
            "launcher_argv",
            _argv_tuple(self.launcher_argv, path="SlurmOptions.launcher_argv"),
        )
        object.__setattr__(
            self,
            "extra_sbatch",
            MappingProxyType(
                _normalize_extra_sbatch(
                    self.extra_sbatch,
                    path="SlurmOptions.extra_sbatch",
                )
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "partition": self.partition,
            "account": self.account,
            "qos": self.qos,
            "constraint": self.constraint,
            "nodes": self.nodes,
            "ntasks": self.ntasks,
            "cpus_per_task": self.cpus_per_task,
            "mem": self.mem,
            "mem_per_cpu": self.mem_per_cpu,
            "gres": self.gres,
            "time": self.time,
            "prelude": list(self.prelude),
            "extra_sbatch": dict(self.extra_sbatch),
            "launcher_argv": list(self.launcher_argv),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SlurmOptions":
        try:
            mapping = load_versioned_document(
                data,
                current_version=SLURM_OPTIONS_SCHEMA_VERSION,
                required=(),
                optional=_OPTIONS_FIELDS - {"schema_version"},
                path="SlurmOptions",
            )
        except SchemaVersionError as exc:
            raise SlurmOptionError(f"SlurmOptions.from_dict: {exc}") from exc
        return cls(
            schema_version=_require_schema_version(
                mapping["schema_version"],
                path="SlurmOptions.schema_version",
            ),
            partition=_optional_string(
                mapping.get("partition"), path="SlurmOptions.partition"
            ),
            account=_optional_string(
                mapping.get("account"), path="SlurmOptions.account"
            ),
            qos=_optional_string(mapping.get("qos"), path="SlurmOptions.qos"),
            constraint=_optional_string(
                mapping.get("constraint"),
                path="SlurmOptions.constraint",
            ),
            nodes=_optional_positive_int(
                mapping.get("nodes"), path="SlurmOptions.nodes"
            ),
            ntasks=_optional_positive_int(
                mapping.get("ntasks"), path="SlurmOptions.ntasks"
            ),
            cpus_per_task=_optional_positive_int(
                mapping.get("cpus_per_task"),
                path="SlurmOptions.cpus_per_task",
            ),
            mem=_optional_string(mapping.get("mem"), path="SlurmOptions.mem"),
            mem_per_cpu=_optional_string(
                mapping.get("mem_per_cpu"),
                path="SlurmOptions.mem_per_cpu",
            ),
            gres=_optional_string(mapping.get("gres"), path="SlurmOptions.gres"),
            time=_optional_string(mapping.get("time"), path="SlurmOptions.time"),
            prelude=_sequence(mapping.get("prelude", ()), path="SlurmOptions.prelude"),
            extra_sbatch=cast(
                Mapping[str, str | bool],
                _mapping(
                    mapping.get("extra_sbatch", {}), path="SlurmOptions.extra_sbatch"
                ),
            ),
            launcher_argv=_sequence(
                mapping.get("launcher_argv", DEFAULT_SLURM_LAUNCHER_ARGV),
                path="SlurmOptions.launcher_argv",
            ),
        )

    def modeled_sbatch_directives(self) -> dict[str, str]:
        directives: dict[str, str] = {}
        for field_name, directive_name in (
            ("partition", "partition"),
            ("account", "account"),
            ("qos", "qos"),
            ("constraint", "constraint"),
            ("nodes", "nodes"),
            ("ntasks", "ntasks"),
            ("cpus_per_task", "cpus-per-task"),
            ("mem", "mem"),
            ("mem_per_cpu", "mem-per-cpu"),
            ("gres", "gres"),
            ("time", "time"),
        ):
            value = getattr(self, field_name)
            if value is not None:
                directives[directive_name] = str(value)
        return directives


def build_single_job_command_argv(
    run_uri: str,
    *,
    launcher_argv: Sequence[str] = DEFAULT_SLURM_LAUNCHER_ARGV,
) -> SlurmCommandArgv:
    run_uri_text = _required_string(run_uri, path="run_uri")
    return SlurmCommandArgv(
        launcher_argv=launcher_argv,
        command_args=(
            "prepared-run",
            "continue",
            "--run-uri",
            run_uri_text,
            "--executor",
            "local",
        ),
    )


def build_stage_job_command_argv(
    run_uri: str,
    stage_name: str,
    *,
    launcher_argv: Sequence[str] = DEFAULT_SLURM_LAUNCHER_ARGV,
) -> SlurmCommandArgv:
    run_uri_text = _required_string(run_uri, path="run_uri")
    stage_text = _required_string(stage_name, path="stage_name")
    return SlurmCommandArgv(
        launcher_argv=launcher_argv,
        command_args=(
            "stage-job",
            "run",
            "--run-uri",
            run_uri_text,
            "--stage",
            stage_text,
            "--executor",
            "local",
        ),
    )


def normalize_extra_sbatch(
    extra_sbatch: Mapping[str, str | bool],
    *,
    path: str = "extra_sbatch",
) -> dict[str, str | bool]:
    return _normalize_extra_sbatch(extra_sbatch, path=path)


def _normalize_extra_sbatch(
    extra_sbatch: Mapping[str, str | bool],
    *,
    path: str,
) -> dict[str, str | bool]:
    if not isinstance(extra_sbatch, Mapping):
        raise SlurmOptionError(f"{path} must be a mapping")
    normalized: dict[str, str | bool] = {}
    for raw_name, raw_value in extra_sbatch.items():
        if not isinstance(raw_name, str):
            raise SlurmOptionError(f"{path} must use string directive names")
        name = _normalize_directive_name(raw_name, path=f"{path}[{raw_name!r}]")
        if name in normalized:
            raise SlurmOptionError(
                f"{path}[{raw_name!r}] duplicates directive {name!r}"
            )
        if name in RESERVED_SBATCH_DIRECTIVES:
            raise SlurmOptionError(
                f"{path}[{raw_name!r}] conflicts with generated or modeled directive {name!r}"
            )
        normalized[name] = _extra_value(raw_value, path=f"{path}[{raw_name!r}]")
    return dict(sorted(normalized.items()))


def _normalize_directive_name(value: str, *, path: str) -> str:
    if value.startswith("-") and not value.startswith("--"):
        raise SlurmOptionError(f"{path} must use long SBATCH directive names")
    normalized = value[2:] if value.startswith("--") else value
    if not normalized:
        raise SlurmOptionError(f"{path} must not be empty")
    if normalized.strip() != normalized:
        raise SlurmOptionError(
            f"{path} must not contain leading or trailing whitespace"
        )
    if "/" in normalized or "\\" in normalized:
        raise SlurmOptionError(f"{path} must not contain path separators")
    if any(ch.isspace() or ord(ch) < 32 for ch in normalized):
        raise SlurmOptionError(
            f"{path} must not contain whitespace or control characters"
        )
    if not _DIRECTIVE_NAME_PATTERN.fullmatch(normalized):
        raise SlurmOptionError(f"{path} must be an SBATCH directive name")
    return normalized


def _extra_value(value: object, *, path: str) -> str | bool:
    if value is True:
        return True
    if value is False:
        raise SlurmOptionError(f"{path} must be true for valueless flags, not false")
    if isinstance(value, str):
        if not value:
            raise SlurmOptionError(f"{path} must not be empty")
        if any(ord(ch) < 32 for ch in value):
            raise SlurmOptionError(f"{path} must not contain control characters")
        return value
    raise SlurmOptionError(f"{path} must be a string value or true")


def _require_schema_version(value: object, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SlurmOptionError(f"{path} must be {SLURM_OPTIONS_SCHEMA_VERSION}")
    if value != SLURM_OPTIONS_SCHEMA_VERSION:
        raise SlurmOptionError(
            f"{path} must be {SLURM_OPTIONS_SCHEMA_VERSION}, got {value!r}"
        )
    return value


def _optional_string(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, path=path)


def _required_string(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise SlurmOptionError(f"{path} must be a non-empty string")
    if any(ord(ch) < 32 for ch in value):
        raise SlurmOptionError(f"{path} must not contain control characters")
    return value


def _optional_positive_int(value: object, *, path: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SlurmOptionError(f"{path} must be a positive integer")
    if value <= 0:
        raise SlurmOptionError(f"{path} must be a positive integer")
    return value


def _argv_tuple(
    value: Sequence[str],
    *,
    path: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    entries = _string_tuple(value, path=path, allow_empty=allow_empty)
    if not allow_empty and not entries:
        raise SlurmOptionError(f"{path} must not be empty")
    return entries


def _string_tuple(
    value: Sequence[str],
    *,
    path: str,
    allow_empty: bool,
) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SlurmOptionError(f"{path} must be a sequence of strings")
    entries: list[str] = []
    for index, item in enumerate(value):
        entries.append(_required_string(item, path=f"{path}[{index}]"))
    if not allow_empty and not entries:
        raise SlurmOptionError(f"{path} must not be empty")
    return tuple(entries)


def _sequence(value: object, *, path: str) -> Sequence[str]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SlurmOptionError(f"{path} must be a sequence")
    return cast(Sequence[str], value)


def _mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SlurmOptionError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise SlurmOptionError(f"{path} must use string keys")
    return cast(Mapping[str, object], value)


def _reject_unknown(
    mapping: Mapping[str, object],
    allowed: frozenset[str] | set[str],
    *,
    path: str,
) -> None:
    unknown = set(mapping) - set(allowed)
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise SlurmOptionError(f"{path} contains unknown field(s): {fields}")


__all__ = [
    "DEFAULT_SLURM_LAUNCHER_ARGV",
    "GENERATED_SBATCH_DIRECTIVES",
    "MODELED_SBATCH_DIRECTIVES",
    "RESERVED_SBATCH_DIRECTIVES",
    "SLURM_OPTIONS_SCHEMA_VERSION",
    "SlurmCommandArgv",
    "SlurmOptions",
    "build_single_job_command_argv",
    "build_stage_job_command_argv",
    "normalize_extra_sbatch",
]
