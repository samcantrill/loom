"""Provenance models and schema helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from loom.fingerprints import validate_digest
from loom.ids import ArtifactID, ArtifactType, Checksum, Fingerprint, RunID, StageID
from loom.serialization import PlainData, check_supported_schema, ensure_plain_data
from loom.timestamps import parse_timestamp

from .errors import ProvenanceValidationError

KIND_GIT = "loom.git_provenance"
KIND_CODE = "loom.code_provenance"
KIND_ENV = "loom.environment_provenance"
KIND_DEP = "loom.dependency_provenance"
KIND_COMMAND = "loom.command_provenance"
KIND_LINEAGE = "loom.artifact_lineage"
KIND_STAGE = "loom.stage_provenance"
KIND_RUN = "loom.run_provenance"


def _require_schema_version(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProvenanceValidationError(f"{field} must be a positive integer")
    if value != 1:
        raise ProvenanceValidationError(f"{field} must be 1")
    return value


def _check_fields(data: Mapping[str, object], kind: str, allowed: set[str], *, field: str = "kind") -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ProvenanceValidationError(f"{kind} received unknown fields: {', '.join(sorted(unknown))}")
    if data.get(field) != kind:
        raise ProvenanceValidationError(f"Invalid kind: expected {kind!r}, got {data.get(field)!r}")


def _require_str(value: object, field: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ProvenanceValidationError(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise ProvenanceValidationError(f"{field} must be a string")
    if required and not value:
        raise ProvenanceValidationError(f"{field} must be a non-empty string")
    return value


def _require_non_empty_str(value: object, field: str) -> str:
    text = _require_str(value, field, required=True)
    assert text is not None
    return text


def _require_bool_or_none(value: object, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ProvenanceValidationError(f"{field} must be a boolean")
    return value


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProvenanceValidationError(f"{field} must be a mapping")
    return value


def _require_plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    mapping = _require_mapping(value, field)
    return ensure_plain_data(dict(mapping), path=field)


def _normalize_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProvenanceValidationError(f"{field} must be a non-negative int")
    return value


def _normalize_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ProvenanceValidationError(f"{field} must be a tuple of strings")
    normalized = tuple(_require_non_empty_str(item, field) for item in value)
    return normalized


def _normalize_digest(value: object, field: str) -> str | None:
    if value is None:
        return None
    try:
        return validate_digest(value)
    except Exception as exc:
        raise ProvenanceValidationError(f"{field} must be a valid digest") from exc


def _normalize_timestamp(value: object, field: str) -> str | None:
    if value is None:
        return None
    text = _require_str(value, field, required=True)
    parse_timestamp(text)
    return text


def _normalize_mapping_optional_str(value: object, field: str) -> Mapping[str, str]:
    mapping = _require_mapping(value, field)
    normalized: dict[str, str] = {}
    for key, item in mapping.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ProvenanceValidationError(f"{field} must map strings to strings")
        normalized[key] = item
    return normalized


@dataclass(frozen=True, slots=True)
class GitProvenance:
    repository_root: str | None = None
    commit: str | None = None
    branch: str | None = None
    is_dirty: bool | None = None
    has_untracked: bool | None = None
    remote_url: str | None = None
    capture_error: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.repository_root is not None and not isinstance(self.repository_root, str):
            raise ProvenanceValidationError("repository_root must be a string")
        if self.commit is not None and not isinstance(self.commit, str):
            raise ProvenanceValidationError("commit must be a string")
        if self.branch is not None and not isinstance(self.branch, str):
            raise ProvenanceValidationError("branch must be a string")
        if self.remote_url is not None and not isinstance(self.remote_url, str):
            raise ProvenanceValidationError("remote_url must be a string")
        if self.capture_error is not None and not isinstance(self.capture_error, str):
            raise ProvenanceValidationError("capture_error must be a string")
        _require_bool_or_none(self.is_dirty, "is_dirty")
        _require_bool_or_none(self.has_untracked, "has_untracked")
        object.__setattr__(self, "metadata", _require_plain_mapping(self.metadata, "metadata"))
        _require_schema_version(self.schema_version, "schema_version")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": KIND_GIT,
            "schema_version": self.schema_version,
            "repository_root": self.repository_root,
            "commit": self.commit,
            "branch": self.branch,
            "is_dirty": self.is_dirty,
            "has_untracked": self.has_untracked,
            "remote_url": self.remote_url,
            "capture_error": self.capture_error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "GitProvenance":
        if not isinstance(data, Mapping):
            raise ProvenanceValidationError("GitProvenance.from_dict expects mapping")
        allowed = {
            "kind",
            "schema_version",
            "repository_root",
            "commit",
            "branch",
            "is_dirty",
            "has_untracked",
            "remote_url",
            "capture_error",
            "metadata",
        }
        _check_fields(data, KIND_GIT, allowed)
        check_supported_schema(data, supported=(1,))
        return cls(
            repository_root=_require_str(data.get("repository_root"), "repository_root"),
            commit=_require_str(data.get("commit"), "commit"),
            branch=_require_str(data.get("branch"), "branch"),
            is_dirty=_require_bool_or_none(data.get("is_dirty"), "is_dirty"),
            has_untracked=_require_bool_or_none(data.get("has_untracked"), "has_untracked"),
            remote_url=_require_str(data.get("remote_url"), "remote_url"),
            capture_error=_require_str(data.get("capture_error"), "capture_error"),
            metadata=_require_plain_mapping(data.get("metadata", {}), "metadata"),
            schema_version=_require_schema_version(data.get("schema_version", 1), "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class CodeProvenance:
    git: GitProvenance | None = None
    package_name: str | None = None
    package_version: str | None = None
    source_paths: tuple[str, ...] = ()
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.git is not None and not isinstance(self.git, GitProvenance):
            raise ProvenanceValidationError("git must be GitProvenance")
        if self.package_name is not None and not isinstance(self.package_name, str):
            raise ProvenanceValidationError("package_name must be a string")
        if self.package_version is not None and not isinstance(self.package_version, str):
            raise ProvenanceValidationError("package_version must be a string")
        object.__setattr__(self, "source_paths", _normalize_tuple(self.source_paths, "source_paths"))
        object.__setattr__(self, "metadata", _require_plain_mapping(self.metadata, "metadata"))
        _require_schema_version(self.schema_version, "schema_version")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": KIND_CODE,
            "schema_version": self.schema_version,
            "git": self.git.to_dict() if self.git else None,
            "package_name": self.package_name,
            "package_version": self.package_version,
            "source_paths": tuple(self.source_paths),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CodeProvenance":
        if not isinstance(data, Mapping):
            raise ProvenanceValidationError("CodeProvenance.from_dict expects mapping")
        allowed = {
            "kind",
            "schema_version",
            "git",
            "package_name",
            "package_version",
            "source_paths",
            "metadata",
        }
        _check_fields(data, KIND_CODE, allowed)
        check_supported_schema(data, supported=(1,))
        git_data = data.get("git")
        return cls(
            git=GitProvenance.from_dict(git_data) if isinstance(git_data, Mapping) else None,
            package_name=_require_str(data.get("package_name"), "package_name"),
            package_version=_require_str(data.get("package_version"), "package_version"),
            source_paths=_normalize_tuple(data.get("source_paths", ()), "source_paths"),
            metadata=_require_plain_mapping(data.get("metadata", {}), "metadata"),
            schema_version=_require_schema_version(data.get("schema_version", 1), "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class EnvironmentProvenance:
    python_version: str
    python_executable: str | None = None
    platform: str | None = None
    machine: str | None = None
    processor: str | None = None
    hostname: str | None = None
    user: str | None = None
    selected_env: Mapping[str, str] = field(default_factory=dict)
    container: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not _require_str(self.python_version, "python_version", required=True):
            raise ProvenanceValidationError("python_version must be set")
        if self.python_executable is not None and not isinstance(self.python_executable, str):
            raise ProvenanceValidationError("python_executable must be a string")
        if self.platform is not None and not isinstance(self.platform, str):
            raise ProvenanceValidationError("platform must be a string")
        if self.machine is not None and not isinstance(self.machine, str):
            raise ProvenanceValidationError("machine must be a string")
        if self.processor is not None and not isinstance(self.processor, str):
            raise ProvenanceValidationError("processor must be a string")
        if self.hostname is not None and not isinstance(self.hostname, str):
            raise ProvenanceValidationError("hostname must be a string")
        if self.user is not None and not isinstance(self.user, str):
            raise ProvenanceValidationError("user must be a string")
        object.__setattr__(self, "selected_env", _normalize_mapping_optional_str(self.selected_env, "selected_env"))
        object.__setattr__(self, "container", _require_plain_mapping(self.container, "container"))
        object.__setattr__(self, "metadata", _require_plain_mapping(self.metadata, "metadata"))
        _require_schema_version(self.schema_version, "schema_version")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": KIND_ENV,
            "schema_version": self.schema_version,
            "python_version": self.python_version,
            "python_executable": self.python_executable,
            "platform": self.platform,
            "machine": self.machine,
            "processor": self.processor,
            "hostname": self.hostname,
            "user": self.user,
            "selected_env": dict(self.selected_env),
            "container": dict(self.container),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "EnvironmentProvenance":
        if not isinstance(data, Mapping):
            raise ProvenanceValidationError("EnvironmentProvenance.from_dict expects mapping")
        allowed = {
            "kind",
            "schema_version",
            "python_version",
            "python_executable",
            "platform",
            "machine",
            "processor",
            "hostname",
            "user",
            "selected_env",
            "container",
            "metadata",
        }
        _check_fields(data, KIND_ENV, allowed)
        check_supported_schema(data, supported=(1,))
        return cls(
            python_version=_require_non_empty_str(data.get("python_version"), "python_version"),
            python_executable=_require_str(data.get("python_executable"), "python_executable"),
            platform=_require_str(data.get("platform"), "platform"),
            machine=_require_str(data.get("machine"), "machine"),
            processor=_require_str(data.get("processor"), "processor"),
            hostname=_require_str(data.get("hostname"), "hostname"),
            user=_require_str(data.get("user"), "user"),
            selected_env=_normalize_mapping_optional_str(data.get("selected_env", {}), "selected_env"),
            container=_require_plain_mapping(data.get("container", {}), "container"),
            metadata=_require_plain_mapping(data.get("metadata", {}), "metadata"),
            schema_version=_require_schema_version(data.get("schema_version", 1), "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class DependencyProvenance:
    packages: Mapping[str, str] = field(default_factory=dict)
    missing_packages: tuple[str, ...] = ()
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        normalized: dict[str, str] = {}
        for name, version in self.packages.items():
            if not isinstance(name, str) or not name:
                raise ProvenanceValidationError("packages keys must be strings")
            if not isinstance(version, str):
                raise ProvenanceValidationError("packages values must be strings")
            normalized[name] = version
        object.__setattr__(self, "packages", normalized)
        object.__setattr__(self, "missing_packages", _normalize_tuple(self.missing_packages, "missing_packages"))
        object.__setattr__(self, "metadata", _require_plain_mapping(self.metadata, "metadata"))
        _require_schema_version(self.schema_version, "schema_version")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": KIND_DEP,
            "schema_version": self.schema_version,
            "packages": dict(self.packages),
            "missing_packages": tuple(self.missing_packages),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "DependencyProvenance":
        if not isinstance(data, Mapping):
            raise ProvenanceValidationError("DependencyProvenance.from_dict expects mapping")
        allowed = {"kind", "schema_version", "packages", "missing_packages", "metadata"}
        _check_fields(data, KIND_DEP, allowed)
        check_supported_schema(data, supported=(1,))
        return cls(
            packages=_require_mapping(data.get("packages", {}), "packages"),
            missing_packages=_normalize_tuple(data.get("missing_packages", ()), "missing_packages"),
            metadata=_require_plain_mapping(data.get("metadata", {}), "metadata"),
            schema_version=_require_schema_version(data.get("schema_version", 1), "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class CommandProvenance:
    argv: tuple[str, ...] = ()
    cwd: str | None = None
    launcher: str | None = None
    command_string: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", _normalize_tuple(self.argv, "argv"))
        if self.cwd is not None and not isinstance(self.cwd, str):
            raise ProvenanceValidationError("cwd must be a string")
        if self.launcher is not None and not isinstance(self.launcher, str):
            raise ProvenanceValidationError("launcher must be a string")
        if self.command_string is not None and not isinstance(self.command_string, str):
            raise ProvenanceValidationError("command_string must be a string")
        object.__setattr__(self, "metadata", _require_plain_mapping(self.metadata, "metadata"))
        _require_schema_version(self.schema_version, "schema_version")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": KIND_COMMAND,
            "schema_version": self.schema_version,
            "argv": tuple(self.argv),
            "cwd": self.cwd,
            "launcher": self.launcher,
            "command_string": self.command_string,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CommandProvenance":
        if not isinstance(data, Mapping):
            raise ProvenanceValidationError("CommandProvenance.from_dict expects mapping")
        allowed = {"kind", "schema_version", "argv", "cwd", "launcher", "command_string", "metadata"}
        _check_fields(data, KIND_COMMAND, allowed)
        check_supported_schema(data, supported=(1,))
        return cls(
            argv=_normalize_tuple(data.get("argv", ()), "argv"),
            cwd=_require_str(data.get("cwd"), "cwd"),
            launcher=_require_str(data.get("launcher"), "launcher"),
            command_string=_require_str(data.get("command_string"), "command_string"),
            metadata=_require_plain_mapping(data.get("metadata", {}), "metadata"),
            schema_version=_require_schema_version(data.get("schema_version", 1), "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactLineage:
    artifact_id: ArtifactID
    artifact_type: ArtifactType | None = None
    uri: str | None = None
    artifact_schema_version: int | None = None
    producer_stage: StageID | None = None
    producer_fingerprint: Fingerprint | None = None
    checksum: Checksum | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, str) or not self.artifact_id:
            raise ProvenanceValidationError("artifact_id must be a non-empty string")
        if self.artifact_type is not None and not isinstance(self.artifact_type, str):
            raise ProvenanceValidationError("artifact_type must be a string")
        if self.uri is not None and not isinstance(self.uri, str):
            raise ProvenanceValidationError("uri must be a string")
        if self.artifact_schema_version is not None:
            _require_schema_version(self.artifact_schema_version, "artifact_schema_version")
        if self.producer_stage is not None and not isinstance(self.producer_stage, str):
            raise ProvenanceValidationError("producer_stage must be a string")
        object.__setattr__(self, "producer_fingerprint", _normalize_digest(self.producer_fingerprint, "producer_fingerprint"))
        object.__setattr__(self, "checksum", _normalize_digest(self.checksum, "checksum"))
        object.__setattr__(self, "metadata", _require_plain_mapping(self.metadata, "metadata"))
        _require_schema_version(self.schema_version, "schema_version")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": KIND_LINEAGE,
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "uri": self.uri,
            "artifact_schema_version": self.artifact_schema_version,
            "producer_stage": self.producer_stage,
            "producer_fingerprint": self.producer_fingerprint,
            "checksum": self.checksum,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ArtifactLineage":
        if not isinstance(data, Mapping):
            raise ProvenanceValidationError("ArtifactLineage.from_dict expects mapping")
        allowed = {
            "kind",
            "schema_version",
            "artifact_id",
            "artifact_type",
            "uri",
            "artifact_schema_version",
            "producer_stage",
            "producer_fingerprint",
            "checksum",
            "metadata",
        }
        _check_fields(data, KIND_LINEAGE, allowed)
        check_supported_schema(data, supported=(1,))
        return cls(
            artifact_id=_require_non_empty_str(data.get("artifact_id"), "artifact_id"),
            artifact_type=_require_str(data.get("artifact_type"), "artifact_type"),
            uri=_require_str(data.get("uri"), "uri"),
            artifact_schema_version=_normalize_int(data.get("artifact_schema_version"), "artifact_schema_version")
            if data.get("artifact_schema_version") is not None
            else None,
            producer_stage=_require_str(data.get("producer_stage"), "producer_stage"),
            producer_fingerprint=_normalize_digest(data.get("producer_fingerprint"), "producer_fingerprint"),
            checksum=_normalize_digest(data.get("checksum"), "checksum"),
            metadata=_require_plain_mapping(data.get("metadata", {}), "metadata"),
            schema_version=_require_schema_version(data.get("schema_version", 1), "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class StageProvenance:
    run_id: RunID
    stage_name: StageID
    status: str
    attempt: int
    target: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    fingerprint: Mapping[str, PlainData] | None = None
    input_artifacts: Mapping[str, PlainData] = field(default_factory=dict)
    output_artifacts: Mapping[str, PlainData] = field(default_factory=dict)
    executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    code: CodeProvenance | None = None
    environment: EnvironmentProvenance | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise ProvenanceValidationError("run_id must be a non-empty string")
        if not isinstance(self.stage_name, str) or not self.stage_name:
            raise ProvenanceValidationError("stage_name must be a non-empty string")
        if not isinstance(self.status, str) or not self.status:
            raise ProvenanceValidationError("status must be a non-empty string")
        if not isinstance(self.attempt, int) or isinstance(self.attempt, bool) or self.attempt <= 0:
            raise ProvenanceValidationError("attempt must be a positive int")
        if self.target is not None and not isinstance(self.target, str):
            raise ProvenanceValidationError("target must be a string")
        if self.started_at is not None:
            _normalize_timestamp(self.started_at, "started_at")
        if self.finished_at is not None:
            _normalize_timestamp(self.finished_at, "finished_at")
        if self.duration_seconds is not None and not isinstance(self.duration_seconds, (int, float)):
            raise ProvenanceValidationError("duration_seconds must be a number")
        if self.fingerprint is not None:
            _require_mapping(self.fingerprint, "fingerprint")
            object.__setattr__(self, "fingerprint", _require_plain_mapping(self.fingerprint, "fingerprint"))
        object.__setattr__(self, "input_artifacts", _require_plain_mapping(self.input_artifacts, "input_artifacts"))
        object.__setattr__(self, "output_artifacts", _require_plain_mapping(self.output_artifacts, "output_artifacts"))
        object.__setattr__(self, "executor_metadata", _require_plain_mapping(self.executor_metadata, "executor_metadata"))
        if self.code is not None and not isinstance(self.code, CodeProvenance):
            raise ProvenanceValidationError("code must be CodeProvenance")
        if self.environment is not None and not isinstance(self.environment, EnvironmentProvenance):
            raise ProvenanceValidationError("environment must be EnvironmentProvenance")
        object.__setattr__(self, "metadata", _require_plain_mapping(self.metadata, "metadata"))
        _require_schema_version(self.schema_version, "schema_version")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": KIND_STAGE,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "stage_name": self.stage_name,
            "status": self.status,
            "attempt": self.attempt,
            "target": self.target,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "fingerprint": dict(self.fingerprint or {}),
            "input_artifacts": dict(self.input_artifacts),
            "output_artifacts": dict(self.output_artifacts),
            "executor_metadata": dict(self.executor_metadata),
            "code": self.code.to_dict() if self.code else None,
            "environment": self.environment.to_dict() if self.environment else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StageProvenance":
        if not isinstance(data, Mapping):
            raise ProvenanceValidationError("StageProvenance.from_dict expects mapping")
        allowed = {
            "kind",
            "schema_version",
            "run_id",
            "stage_name",
            "status",
            "attempt",
            "target",
            "started_at",
            "finished_at",
            "duration_seconds",
            "fingerprint",
            "input_artifacts",
            "output_artifacts",
            "executor_metadata",
            "code",
            "environment",
            "metadata",
        }
        _check_fields(data, KIND_STAGE, allowed)
        check_supported_schema(data, supported=(1,))

        code_data = data.get("code")
        environment_data = data.get("environment")
        return cls(
            run_id=_require_non_empty_str(data.get("run_id"), "run_id"),
            stage_name=_require_non_empty_str(data.get("stage_name"), "stage_name"),
            status=_require_non_empty_str(data.get("status"), "status"),
            attempt=_normalize_int(data.get("attempt"), "attempt"),
            target=_require_str(data.get("target"), "target"),
            started_at=_normalize_timestamp(data.get("started_at"), "started_at"),
            finished_at=_normalize_timestamp(data.get("finished_at"), "finished_at"),
            duration_seconds=_require_non_negative_duration(data.get("duration_seconds"), "duration_seconds"),
            fingerprint=_require_mapping(data.get("fingerprint", {}), "fingerprint") if data.get("fingerprint") is not None else None,
            input_artifacts=_require_plain_mapping(data.get("input_artifacts", {}), "input_artifacts"),
            output_artifacts=_require_plain_mapping(data.get("output_artifacts", {}), "output_artifacts"),
            executor_metadata=_require_plain_mapping(data.get("executor_metadata", {}), "executor_metadata"),
            code=CodeProvenance.from_dict(code_data) if isinstance(code_data, Mapping) else None,
            environment=EnvironmentProvenance.from_dict(environment_data) if isinstance(environment_data, Mapping) else None,
            metadata=_require_plain_mapping(data.get("metadata", {}), "metadata"),
            schema_version=_require_schema_version(data.get("schema_version", 1), "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class RunProvenance:
    run_id: RunID
    created_at: str
    run_dir: str | None = None
    command: CommandProvenance | None = None
    code: CodeProvenance | None = None
    environment: EnvironmentProvenance | None = None
    dependencies: DependencyProvenance | None = None
    config: Mapping[str, PlainData] = field(default_factory=dict)
    stages: Mapping[str, PlainData] = field(default_factory=dict)
    artifacts: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise ProvenanceValidationError("run_id must be a non-empty string")
        object.__setattr__(self, "created_at", _normalize_timestamp(self.created_at, "created_at") or "")
        if self.run_dir is not None and not isinstance(self.run_dir, str):
            raise ProvenanceValidationError("run_dir must be a string")
        if self.command is not None and not isinstance(self.command, CommandProvenance):
            raise ProvenanceValidationError("command must be CommandProvenance")
        if self.code is not None and not isinstance(self.code, CodeProvenance):
            raise ProvenanceValidationError("code must be CodeProvenance")
        if self.environment is not None and not isinstance(self.environment, EnvironmentProvenance):
            raise ProvenanceValidationError("environment must be EnvironmentProvenance")
        if self.dependencies is not None and not isinstance(self.dependencies, DependencyProvenance):
            raise ProvenanceValidationError("dependencies must be DependencyProvenance")
        object.__setattr__(self, "config", _require_plain_mapping(self.config, "config"))
        object.__setattr__(self, "stages", _require_plain_mapping(self.stages, "stages"))
        object.__setattr__(self, "artifacts", _require_plain_mapping(self.artifacts, "artifacts"))
        object.__setattr__(self, "metadata", _require_plain_mapping(self.metadata, "metadata"))
        _require_schema_version(self.schema_version, "schema_version")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": KIND_RUN,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "run_dir": self.run_dir,
            "command": self.command.to_dict() if self.command else None,
            "code": self.code.to_dict() if self.code else None,
            "environment": self.environment.to_dict() if self.environment else None,
            "dependencies": self.dependencies.to_dict() if self.dependencies else None,
            "config": dict(self.config),
            "stages": dict(self.stages),
            "artifacts": dict(self.artifacts),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunProvenance":
        if not isinstance(data, Mapping):
            raise ProvenanceValidationError("RunProvenance.from_dict expects mapping")
        allowed = {
            "kind",
            "schema_version",
            "run_id",
            "created_at",
            "run_dir",
            "command",
            "code",
            "environment",
            "dependencies",
            "config",
            "stages",
            "artifacts",
            "metadata",
        }
        _check_fields(data, KIND_RUN, allowed)
        check_supported_schema(data, supported=(1,))

        command_data = data.get("command")
        code_data = data.get("code")
        environment_data = data.get("environment")
        dependencies_data = data.get("dependencies")

        return cls(
            run_id=_require_non_empty_str(data.get("run_id"), "run_id"),
            created_at=_require_non_empty_str(data.get("created_at"), "created_at"),
            run_dir=_require_str(data.get("run_dir"), "run_dir"),
            command=CommandProvenance.from_dict(command_data) if isinstance(command_data, Mapping) else None,
            code=CodeProvenance.from_dict(code_data) if isinstance(code_data, Mapping) else None,
            environment=EnvironmentProvenance.from_dict(environment_data) if isinstance(environment_data, Mapping) else None,
            dependencies=DependencyProvenance.from_dict(dependencies_data) if isinstance(dependencies_data, Mapping) else None,
            config=_require_plain_mapping(data.get("config", {}), "config"),
            stages=_require_plain_mapping(data.get("stages", {}), "stages"),
            artifacts=_require_plain_mapping(data.get("artifacts", {}), "artifacts"),
            metadata=_require_plain_mapping(data.get("metadata", {}), "metadata"),
            schema_version=_require_schema_version(data.get("schema_version", 1), "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class ProvenanceCaptureOptions:
    capture_git: bool = True
    git_root: str | None = None
    include_git_remote: bool = False
    capture_environment: bool = True
    env_keys: tuple[str, ...] = ()
    include_user: bool = False
    capture_dependencies: bool = True
    packages: tuple[str, ...] = ("loom",)
    capture_command: bool = True
    strict: bool = False


def _require_non_negative_duration(value: object, field: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise ProvenanceValidationError(f"{field} must be a number")
    return float(value)
