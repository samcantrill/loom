"""Schema-versioned SLURM planned-submission manifest contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from loom.pipeline.stores._paths import validate_stage_name
from loom.pipeline.stores.errors import UnsafeStorePathError
from loom.serialization import (
    PlainData,
    freeze_plain_data,
    load_versioned_document,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError, SchemaVersionError

from .errors import SlurmManifestError
from .options import SlurmCommandArgv, SlurmOptions
from .paths import slurm_manifest_relative_path
from .resources import SlurmSbatchDirective

SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION = 1

_DEPENDENCY_FIELDS = frozenset({"job_key", "type", "upstream_job_keys"})
_JOB_FIELDS = frozenset(
    {
        "logical_key",
        "mode",
        "command",
        "dependency_job_keys",
        "resources",
        "sbatch_directives",
        "script_relative_path",
        "stdout_relative_path",
        "stderr_relative_path",
        "manifest_relative_path",
        "scheduler_job_id",
    }
)
_MANIFEST_REQUIRED_FIELDS = frozenset(
    {
        "run_uri",
        "mode",
        "dry_run",
        "planning_id",
        "created_at",
        "plan_relative_path",
        "manifest_relative_path",
        "options",
        "jobs",
        "dependencies",
    }
)
_MANIFEST_OPTIONAL_FIELDS = frozenset({"generated_command_argv", "resources"})


class SlurmMode(StrEnum):
    SINGLE_JOB = "slurm-single-job"
    AFTEROK = "slurm-afterok"


class SlurmDependencyType(StrEnum):
    AFTEROK = "afterok"


@dataclass(frozen=True, slots=True)
class SlurmPlannedDependency:
    """Logical afterok dependency record."""

    job_key: str
    upstream_job_keys: Sequence[str]
    dependency_type: SlurmDependencyType | str = SlurmDependencyType.AFTEROK

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "job_key",
            validate_logical_job_key(
                self.job_key, path="SlurmPlannedDependency.job_key"
            ),
        )
        object.__setattr__(
            self,
            "upstream_job_keys",
            tuple(
                validate_logical_job_key(
                    key, path=f"SlurmPlannedDependency.upstream_job_keys[{index}]"
                )
                for index, key in enumerate(
                    _sequence(
                        self.upstream_job_keys,
                        path="SlurmPlannedDependency.upstream_job_keys",
                    )
                )
            ),
        )
        object.__setattr__(
            self,
            "dependency_type",
            _coerce_dependency_type(
                self.dependency_type,
                path="SlurmPlannedDependency.type",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        dependency_type = cast(SlurmDependencyType, self.dependency_type)
        return {
            "job_key": self.job_key,
            "type": dependency_type.value,
            "upstream_job_keys": list(self.upstream_job_keys),
        }

    @classmethod
    def from_dict(
        cls,
        data: object,
        *,
        path: str = "SlurmPlannedDependency",
    ) -> "SlurmPlannedDependency":
        mapping = _mapping(data, path=path)
        _reject_unknown(mapping, _DEPENDENCY_FIELDS, path=path)
        missing = {"job_key", "type", "upstream_job_keys"} - set(mapping)
        if missing:
            fields = ", ".join(sorted(missing))
            raise SlurmManifestError(f"{path} missing required field(s): {fields}")
        return cls(
            job_key=validate_logical_job_key(
                mapping["job_key"], path=f"{path}.job_key"
            ),
            dependency_type=_coerce_dependency_type(
                mapping["type"], path=f"{path}.type"
            ),
            upstream_job_keys=tuple(
                validate_logical_job_key(key, path=f"{path}.upstream_job_keys[{index}]")
                for index, key in enumerate(
                    _sequence(
                        mapping["upstream_job_keys"], path=f"{path}.upstream_job_keys"
                    )
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class SlurmPlannedJob:
    """Planned dry-run SLURM job record."""

    logical_key: str
    mode: SlurmMode | str
    command: SlurmCommandArgv | Mapping[str, object]
    dependency_job_keys: Sequence[str] = ()
    resources: Mapping[str, PlainData] = field(default_factory=dict)
    sbatch_directives: Sequence[SlurmSbatchDirective | Mapping[str, object]] = ()
    script_relative_path: str | None = None
    stdout_relative_path: str | None = None
    stderr_relative_path: str | None = None
    manifest_relative_path: str | None = None
    scheduler_job_id: None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "logical_key",
            validate_logical_job_key(
                self.logical_key, path="SlurmPlannedJob.logical_key"
            ),
        )
        object.__setattr__(
            self, "mode", _coerce_mode(self.mode, path="SlurmPlannedJob.mode")
        )
        object.__setattr__(
            self,
            "command",
            _coerce_command(self.command, path="SlurmPlannedJob.command"),
        )
        object.__setattr__(
            self,
            "dependency_job_keys",
            tuple(
                validate_logical_job_key(
                    key, path=f"SlurmPlannedJob.dependency_job_keys[{index}]"
                )
                for index, key in enumerate(
                    _sequence(
                        self.dependency_job_keys,
                        path="SlurmPlannedJob.dependency_job_keys",
                    )
                )
            ),
        )
        object.__setattr__(
            self,
            "resources",
            MappingProxyType(
                _plain_mapping(self.resources, path="SlurmPlannedJob.resources")
            ),
        )
        object.__setattr__(
            self,
            "sbatch_directives",
            tuple(
                item
                if isinstance(item, SlurmSbatchDirective)
                else SlurmSbatchDirective.from_dict(
                    item, path=f"SlurmPlannedJob.sbatch_directives[{index}]"
                )
                for index, item in enumerate(self.sbatch_directives)
            ),
        )
        for field_name in (
            "script_relative_path",
            "stdout_relative_path",
            "stderr_relative_path",
            "manifest_relative_path",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_relative_path(
                    getattr(self, field_name),
                    path=f"SlurmPlannedJob.{field_name}",
                ),
            )
        if self.scheduler_job_id is not None:
            raise SlurmManifestError(
                "SlurmPlannedJob.scheduler_job_id must be absent or null"
            )

    def to_dict(self) -> dict[str, PlainData]:
        mode = cast(SlurmMode, self.mode)
        command = cast(SlurmCommandArgv, self.command)
        directives = cast(tuple[SlurmSbatchDirective, ...], self.sbatch_directives)
        payload: dict[str, PlainData] = {
            "logical_key": self.logical_key,
            "mode": mode.value,
            "command": command.to_dict(),
            "dependency_job_keys": list(self.dependency_job_keys),
            "resources": thaw_plain_data(
                self.resources, path="SlurmPlannedJob.resources"
            ),
            "sbatch_directives": [directive.to_dict() for directive in directives],
        }
        for field_name in (
            "script_relative_path",
            "stdout_relative_path",
            "stderr_relative_path",
            "manifest_relative_path",
        ):
            value = getattr(self, field_name)
            if value is not None:
                payload[field_name] = value
        return payload

    @classmethod
    def from_dict(
        cls,
        data: object,
        *,
        path: str = "SlurmPlannedJob",
    ) -> "SlurmPlannedJob":
        mapping = _mapping(data, path=path)
        _reject_unknown(mapping, _JOB_FIELDS, path=path)
        missing = {"logical_key", "mode", "command"} - set(mapping)
        if missing:
            fields = ", ".join(sorted(missing))
            raise SlurmManifestError(f"{path} missing required field(s): {fields}")
        scheduler_job_id = mapping.get("scheduler_job_id")
        if scheduler_job_id is not None:
            raise SlurmManifestError(
                f"{path}.scheduler_job_id must be null when present"
            )
        return cls(
            logical_key=validate_logical_job_key(
                mapping["logical_key"], path=f"{path}.logical_key"
            ),
            mode=_coerce_mode(mapping["mode"], path=f"{path}.mode"),
            command=SlurmCommandArgv.from_dict(
                mapping["command"], path=f"{path}.command"
            ),
            dependency_job_keys=tuple(
                validate_logical_job_key(
                    key, path=f"{path}.dependency_job_keys[{index}]"
                )
                for index, key in enumerate(
                    _sequence(
                        mapping.get("dependency_job_keys", ()),
                        path=f"{path}.dependency_job_keys",
                    )
                )
            ),
            resources=_plain_mapping(
                mapping.get("resources", {}), path=f"{path}.resources"
            ),
            sbatch_directives=tuple(
                SlurmSbatchDirective.from_dict(
                    item, path=f"{path}.sbatch_directives[{index}]"
                )
                for index, item in enumerate(
                    _sequence(
                        mapping.get("sbatch_directives", ()),
                        path=f"{path}.sbatch_directives",
                    )
                )
            ),
            script_relative_path=_optional_relative_path(
                mapping.get("script_relative_path"),
                path=f"{path}.script_relative_path",
            ),
            stdout_relative_path=_optional_relative_path(
                mapping.get("stdout_relative_path"),
                path=f"{path}.stdout_relative_path",
            ),
            stderr_relative_path=_optional_relative_path(
                mapping.get("stderr_relative_path"),
                path=f"{path}.stderr_relative_path",
            ),
            manifest_relative_path=_optional_relative_path(
                mapping.get("manifest_relative_path"),
                path=f"{path}.manifest_relative_path",
            ),
        )


@dataclass(frozen=True, slots=True)
class SlurmPlannedSubmission:
    """Schema-versioned dry-run planned submission manifest."""

    run_uri: str
    mode: SlurmMode | str
    planning_id: str
    created_at: str
    plan_relative_path: str
    jobs: Sequence[SlurmPlannedJob | Mapping[str, object]]
    dependencies: Sequence[SlurmPlannedDependency | Mapping[str, object]] = ()
    options: SlurmOptions | Mapping[str, object] = field(default_factory=SlurmOptions)
    manifest_relative_path: str | None = None
    generated_command_argv: Sequence[SlurmCommandArgv | Mapping[str, object]] = ()
    resources: Mapping[str, PlainData] = field(default_factory=dict)
    dry_run: bool = True
    schema_version: int = SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(
                self.schema_version,
                path="SlurmPlannedSubmission.schema_version",
            ),
        )
        object.__setattr__(
            self,
            "run_uri",
            _required_string(self.run_uri, path="SlurmPlannedSubmission.run_uri"),
        )
        object.__setattr__(
            self,
            "mode",
            _coerce_mode(self.mode, path="SlurmPlannedSubmission.mode"),
        )
        object.__setattr__(
            self,
            "planning_id",
            _required_string(
                self.planning_id, path="SlurmPlannedSubmission.planning_id"
            ),
        )
        object.__setattr__(
            self,
            "created_at",
            _required_string(self.created_at, path="SlurmPlannedSubmission.created_at"),
        )
        object.__setattr__(
            self,
            "plan_relative_path",
            _relative_path(
                self.plan_relative_path,
                path="SlurmPlannedSubmission.plan_relative_path",
            ),
        )
        manifest_relative_path = (
            slurm_manifest_relative_path(self.planning_id)
            if self.manifest_relative_path is None
            else self.manifest_relative_path
        )
        object.__setattr__(
            self,
            "manifest_relative_path",
            _relative_path(
                manifest_relative_path,
                path="SlurmPlannedSubmission.manifest_relative_path",
            ),
        )
        object.__setattr__(
            self,
            "options",
            self.options
            if isinstance(self.options, SlurmOptions)
            else SlurmOptions.from_dict(self.options),
        )
        object.__setattr__(
            self,
            "jobs",
            tuple(
                item
                if isinstance(item, SlurmPlannedJob)
                else SlurmPlannedJob.from_dict(
                    item, path=f"SlurmPlannedSubmission.jobs[{index}]"
                )
                for index, item in enumerate(self.jobs)
            ),
        )
        object.__setattr__(
            self,
            "dependencies",
            tuple(
                item
                if isinstance(item, SlurmPlannedDependency)
                else SlurmPlannedDependency.from_dict(
                    item,
                    path=f"SlurmPlannedSubmission.dependencies[{index}]",
                )
                for index, item in enumerate(self.dependencies)
            ),
        )
        object.__setattr__(
            self,
            "generated_command_argv",
            tuple(
                item
                if isinstance(item, SlurmCommandArgv)
                else SlurmCommandArgv.from_dict(
                    item,
                    path=f"SlurmPlannedSubmission.generated_command_argv[{index}]",
                )
                for index, item in enumerate(self.generated_command_argv)
            ),
        )
        object.__setattr__(
            self,
            "resources",
            MappingProxyType(
                _plain_mapping(self.resources, path="SlurmPlannedSubmission.resources")
            ),
        )
        if self.dry_run is not True:
            raise SlurmManifestError("SlurmPlannedSubmission.dry_run must be true")

    def to_dict(self) -> dict[str, PlainData]:
        mode = cast(SlurmMode, self.mode)
        options = cast(SlurmOptions, self.options)
        jobs = cast(tuple[SlurmPlannedJob, ...], self.jobs)
        dependencies = cast(tuple[SlurmPlannedDependency, ...], self.dependencies)
        generated_command_argv = cast(
            tuple[SlurmCommandArgv, ...],
            self.generated_command_argv,
        )
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "mode": mode.value,
            "dry_run": True,
            "planning_id": self.planning_id,
            "created_at": self.created_at,
            "plan_relative_path": self.plan_relative_path,
            "manifest_relative_path": cast(str, self.manifest_relative_path),
            "options": options.to_dict(),
            "jobs": [job.to_dict() for job in jobs],
            "dependencies": [dependency.to_dict() for dependency in dependencies],
            "generated_command_argv": [
                command.to_dict() for command in generated_command_argv
            ],
            "resources": thaw_plain_data(
                self.resources,
                path="SlurmPlannedSubmission.resources",
            ),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SlurmPlannedSubmission":
        try:
            mapping = load_versioned_document(
                data,
                current_version=SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION,
                required=_MANIFEST_REQUIRED_FIELDS,
                optional=_MANIFEST_OPTIONAL_FIELDS,
                path="SlurmPlannedSubmission",
            )
        except SchemaVersionError as exc:
            raise SlurmManifestError(
                f"SlurmPlannedSubmission.from_dict: {exc}"
            ) from exc
        return cls(
            schema_version=_require_schema_version(
                mapping["schema_version"],
                path="SlurmPlannedSubmission.schema_version",
            ),
            run_uri=_required_string(
                mapping["run_uri"], path="SlurmPlannedSubmission.run_uri"
            ),
            mode=_coerce_mode(mapping["mode"], path="SlurmPlannedSubmission.mode"),
            dry_run=_require_true(
                mapping["dry_run"], path="SlurmPlannedSubmission.dry_run"
            ),
            planning_id=_required_string(
                mapping["planning_id"],
                path="SlurmPlannedSubmission.planning_id",
            ),
            created_at=_required_string(
                mapping["created_at"],
                path="SlurmPlannedSubmission.created_at",
            ),
            plan_relative_path=_relative_path(
                mapping["plan_relative_path"],
                path="SlurmPlannedSubmission.plan_relative_path",
            ),
            manifest_relative_path=_relative_path(
                mapping["manifest_relative_path"],
                path="SlurmPlannedSubmission.manifest_relative_path",
            ),
            options=SlurmOptions.from_dict(mapping["options"]),
            jobs=tuple(
                SlurmPlannedJob.from_dict(
                    item, path=f"SlurmPlannedSubmission.jobs[{index}]"
                )
                for index, item in enumerate(
                    _sequence(mapping["jobs"], path="SlurmPlannedSubmission.jobs")
                )
            ),
            dependencies=tuple(
                SlurmPlannedDependency.from_dict(
                    item,
                    path=f"SlurmPlannedSubmission.dependencies[{index}]",
                )
                for index, item in enumerate(
                    _sequence(
                        mapping["dependencies"],
                        path="SlurmPlannedSubmission.dependencies",
                    )
                )
            ),
            generated_command_argv=tuple(
                SlurmCommandArgv.from_dict(
                    item,
                    path=f"SlurmPlannedSubmission.generated_command_argv[{index}]",
                )
                for index, item in enumerate(
                    _sequence(
                        mapping.get("generated_command_argv", ()),
                        path="SlurmPlannedSubmission.generated_command_argv",
                    )
                )
            ),
            resources=_plain_mapping(
                mapping.get("resources", {}),
                path="SlurmPlannedSubmission.resources",
            ),
        )


def pipeline_job_key() -> str:
    return "pipeline"


def stage_job_key(stage_name: str) -> str:
    try:
        stage_text = validate_stage_name(stage_name, field="stage_name")
    except UnsafeStorePathError as exc:
        raise SlurmManifestError(f"stage_name is invalid: {exc}") from exc
    return f"stage:{stage_text}"


def validate_logical_job_key(value: object, *, path: str = "logical_job_key") -> str:
    if not isinstance(value, str) or not value:
        raise SlurmManifestError(f"{path} must be 'pipeline' or 'stage:<stage_name>'")
    if value == "pipeline":
        return value
    if value.startswith("stage:"):
        stage_name = value.removeprefix("stage:")
        try:
            validate_stage_name(stage_name, field=path)
        except UnsafeStorePathError as exc:
            raise SlurmManifestError(f"{path} is invalid: {exc}") from exc
        return value
    raise SlurmManifestError(f"{path} must be 'pipeline' or 'stage:<stage_name>'")


def _coerce_mode(value: object, *, path: str) -> SlurmMode:
    if isinstance(value, SlurmMode):
        return value
    if isinstance(value, str):
        try:
            return SlurmMode(value)
        except ValueError as exc:
            valid = ", ".join(mode.value for mode in SlurmMode)
            raise SlurmManifestError(f"{path} must be one of: {valid}") from exc
    raise SlurmManifestError(f"{path} must be a string")


def _coerce_dependency_type(value: object, *, path: str) -> SlurmDependencyType:
    if isinstance(value, SlurmDependencyType):
        return value
    if value == SlurmDependencyType.AFTEROK.value:
        return SlurmDependencyType.AFTEROK
    raise SlurmManifestError(f"{path} must be 'afterok'")


def _coerce_command(
    value: SlurmCommandArgv | Mapping[str, object], *, path: str
) -> SlurmCommandArgv:
    if isinstance(value, SlurmCommandArgv):
        return value
    return SlurmCommandArgv.from_dict(value, path=path)


def _require_schema_version(value: object, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SlurmManifestError(
            f"{path} must be {SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION}"
        )
    if value != SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION:
        raise SlurmManifestError(
            f"{path} must be {SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION}, got {value!r}"
        )
    return value


def _require_true(value: object, *, path: str) -> bool:
    if value is not True:
        raise SlurmManifestError(f"{path} must be true")
    return True


def _required_string(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise SlurmManifestError(f"{path} must be a non-empty string")
    if any(ord(ch) < 32 for ch in value):
        raise SlurmManifestError(f"{path} must not contain control characters")
    return value


def _optional_relative_path(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    return _relative_path(value, path=path)


def _relative_path(value: object, *, path: str) -> str:
    text = _required_string(value, path=path)
    if text.startswith("/") or "\\" in text:
        raise SlurmManifestError(f"{path} must be a relative path")
    if text.strip() != text:
        raise SlurmManifestError(
            f"{path} must not contain leading or trailing whitespace"
        )
    parts = text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SlurmManifestError(
            f"{path} must not contain empty, '.', or '..' components"
        )
    if any(ch.isspace() or ord(ch) < 32 for ch in text):
        raise SlurmManifestError(
            f"{path} must not contain whitespace or control characters"
        )
    return text


def _plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    try:
        normalized = thaw_plain_data(value, path=path)
    except PlainDataError as exc:
        raise SlurmManifestError(
            f"{path} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise SlurmManifestError(f"{path} must be a mapping")
    return cast(
        Mapping[str, PlainData],
        freeze_plain_data(normalized, path=path),
    )


def _mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SlurmManifestError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise SlurmManifestError(f"{path} must use string keys")
    return cast(Mapping[str, object], value)


def _sequence(value: object, *, path: str) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SlurmManifestError(f"{path} must be a sequence")
    return cast(Sequence[object], value)


def _reject_unknown(
    mapping: Mapping[str, object],
    allowed: frozenset[str],
    *,
    path: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise SlurmManifestError(f"{path} contains unknown field(s): {fields}")


__all__ = [
    "SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION",
    "SlurmDependencyType",
    "SlurmMode",
    "SlurmPlannedDependency",
    "SlurmPlannedJob",
    "SlurmPlannedSubmission",
    "pipeline_job_key",
    "stage_job_key",
    "validate_logical_job_key",
]
