"""Fakeable SLURM command runner contracts for live operations."""

from __future__ import annotations

import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from loom.serialization import PlainData, load_versioned_document
from loom.serialization.errors import SchemaVersionError
from loom.timestamps import parse_timestamp, utc_timestamp

from .errors import (
    SlurmCommandUnavailableError,
    SlurmJobIdParseError,
    SlurmPlanningError,
)

SLURM_COMMAND_RESULT_SCHEMA_VERSION = 1
MAX_PERSISTED_COMMAND_OUTPUT_CHARS = 4096

_SBATCH_PARSABLE_RE = re.compile(
    r"^(?P<job_id>[0-9]+)(?:;(?P<cluster>[A-Za-z0-9_.-]+))?$"
)
_COMMAND_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "command",
        "argv",
        "returncode",
        "stdout",
        "stderr",
        "started_at",
        "finished_at",
    }
)


@dataclass(frozen=True, slots=True)
class SlurmParsedJobId:
    """Parsed ``sbatch --parsable`` job identity."""

    job_id: str
    raw_output: str
    cluster: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.job_id, str) or not self.job_id.isdecimal():
            raise SlurmJobIdParseError("SLURM job ID must be decimal digits")
        object.__setattr__(
            self,
            "raw_output",
            bound_scheduler_output(self.raw_output, field="raw_output"),
        )
        if self.cluster is not None:
            if (
                not isinstance(self.cluster, str)
                or not self.cluster
                or any(ch.isspace() or ord(ch) < 32 for ch in self.cluster)
            ):
                raise SlurmJobIdParseError(
                    "SLURM cluster name must be non-empty artifact-safe text"
                )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "job_id": self.job_id,
            "cluster": self.cluster,
            "raw_output": self.raw_output,
        }


@dataclass(frozen=True, slots=True)
class SlurmCommandResult:
    """Normalized scheduler command result safe to persist in artifacts."""

    command: str
    argv: Sequence[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    schema_version: int = SLURM_COMMAND_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SLURM_COMMAND_RESULT_SCHEMA_VERSION:
            raise SlurmPlanningError(
                f"unsupported SLURM command result schema_version {self.schema_version!r}"
            )
        object.__setattr__(self, "command", _required_text(self.command, "command"))
        object.__setattr__(
            self,
            "argv",
            _argv_tuple(self.argv, path="SlurmCommandResult.argv"),
        )
        if not isinstance(self.returncode, int) or isinstance(self.returncode, bool):
            raise SlurmPlanningError("SlurmCommandResult.returncode must be an integer")
        object.__setattr__(
            self,
            "stdout",
            bound_scheduler_output(self.stdout, field="stdout"),
        )
        object.__setattr__(
            self,
            "stderr",
            bound_scheduler_output(self.stderr, field="stderr"),
        )
        _validate_optional_timestamp(self.started_at, field="started_at")
        _validate_optional_timestamp(self.finished_at, field="finished_at")

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "command": self.command,
            "argv": list(self.argv),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: object) -> "SlurmCommandResult":
        try:
            mapping = load_versioned_document(
                data,
                current_version=SLURM_COMMAND_RESULT_SCHEMA_VERSION,
                required={
                    "command",
                    "argv",
                    "returncode",
                    "stdout",
                    "stderr",
                },
                optional={"started_at", "finished_at"},
                path="SlurmCommandResult",
            )
        except SchemaVersionError as exc:
            raise SlurmPlanningError(f"SlurmCommandResult.from_dict: {exc}") from exc
        unknown = set(mapping) - _COMMAND_RESULT_FIELDS
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise SlurmPlanningError(
                f"SlurmCommandResult contains unknown field(s): {fields}"
            )
        return cls(
            schema_version=SLURM_COMMAND_RESULT_SCHEMA_VERSION,
            command=cast(str, mapping["command"]),
            argv=_sequence(mapping["argv"], path="SlurmCommandResult.argv"),
            returncode=cast(int, mapping["returncode"]),
            stdout=cast(str, mapping["stdout"]),
            stderr=cast(str, mapping["stderr"]),
            started_at=cast(str | None, mapping.get("started_at")),
            finished_at=cast(str | None, mapping.get("finished_at")),
        )


class SlurmCommandRunner(Protocol):
    """Protocol for fakeable SLURM command execution."""

    def require(self, command: str) -> None:
        """Raise when a scheduler command is unavailable."""
        ...

    def sbatch(
        self,
        script_path: str | Path,
        *,
        dependency_job_ids: Sequence[str] = (),
        comment: str | None = None,
    ) -> SlurmCommandResult:
        """Submit one script with ``sbatch --parsable``."""
        ...

    def squeue(self, *, job_ids: Sequence[str] = ()) -> SlurmCommandResult:
        """Query active queue data."""
        ...

    def sacct(self, *, job_ids: Sequence[str] = ()) -> SlurmCommandResult:
        """Query accounting data."""
        ...

    def scancel(self, *, job_ids: Sequence[str]) -> SlurmCommandResult:
        """Cancel submitted jobs."""
        ...

    def discover_operation(self, operation_marker: str) -> SlurmCommandResult:
        """Return bounded job/comment rows for one profile-owned marker."""
        ...


class SubprocessSlurmCommandRunner:
    """SLURM command runner backed by local subprocess calls."""

    def require(self, command: str) -> None:
        command_text = _required_text(command, "command")
        if shutil.which(command_text) is None:
            raise SlurmCommandUnavailableError(
                f"required SLURM command is not available on PATH: {command_text}"
            )

    def sbatch(
        self,
        script_path: str | Path,
        *,
        dependency_job_ids: Sequence[str] = (),
        comment: str | None = None,
    ) -> SlurmCommandResult:
        argv = ["sbatch", "--parsable"]
        dependencies = _job_id_tuple(dependency_job_ids, field="dependency_job_ids")
        if dependencies:
            argv.append("--dependency=afterok:" + ":".join(dependencies))
        if comment is not None:
            argv.append("--comment=" + _operation_marker(comment))
        argv.append(str(script_path))
        return self._run("sbatch", argv)

    def squeue(self, *, job_ids: Sequence[str] = ()) -> SlurmCommandResult:
        argv = ["squeue", "--noheader", "--format", "%i|%T|%r"]
        ids = _job_id_tuple(job_ids, field="job_ids")
        if ids:
            argv.extend(("--jobs", ",".join(ids)))
        return self._run("squeue", argv)

    def sacct(self, *, job_ids: Sequence[str] = ()) -> SlurmCommandResult:
        argv = [
            "sacct",
            "--noheader",
            "--parsable2",
            "--format",
            "JobIDRaw,State,ExitCode",
        ]
        ids = _job_id_tuple(job_ids, field="job_ids")
        if ids:
            argv.extend(("--jobs", ",".join(ids)))
        return self._run("sacct", argv)

    def scancel(self, *, job_ids: Sequence[str]) -> SlurmCommandResult:
        ids = _job_id_tuple(job_ids, field="job_ids")
        if not ids:
            raise SlurmPlanningError("scancel requires at least one job ID")
        return self._run("scancel", ["scancel", *ids])

    def discover_operation(self, operation_marker: str) -> SlurmCommandResult:
        _operation_marker(operation_marker)
        return self._run(
            "squeue",
            ["squeue", "--noheader", "--format", "%i|%k"],
        )

    def _run(self, command: str, argv: Sequence[str]) -> SlurmCommandResult:
        import subprocess

        self.require(command)
        started_at = utc_timestamp()
        completed = subprocess.run(  # noqa: S603
            list(argv),
            check=False,
            capture_output=True,
            text=True,
        )
        return SlurmCommandResult(
            command=command,
            argv=tuple(argv),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            started_at=started_at,
            finished_at=utc_timestamp(),
        )


class FakeSlurmCommandRunner:
    """Deterministic command runner for local tests."""

    def __init__(
        self,
        *,
        scripted_results: Mapping[str, Sequence[SlurmCommandResult | BaseException]]
        | None = None,
        unavailable_commands: Sequence[str] = (),
        starting_job_id: int = 1000,
    ) -> None:
        self._scripted: dict[str, list[SlurmCommandResult | BaseException]] = {
            command: list(results)
            for command, results in dict(scripted_results or {}).items()
        }
        self._unavailable = frozenset(str(command) for command in unavailable_commands)
        self._next_job_id = starting_job_id
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def require(self, command: str) -> None:
        command_text = _required_text(command, "command")
        if command_text in self._unavailable:
            raise SlurmCommandUnavailableError(
                f"required SLURM command is not available in fake runner: {command_text}"
            )

    def sbatch(
        self,
        script_path: str | Path,
        *,
        dependency_job_ids: Sequence[str] = (),
        comment: str | None = None,
    ) -> SlurmCommandResult:
        argv = ["sbatch", "--parsable"]
        dependencies = _job_id_tuple(dependency_job_ids, field="dependency_job_ids")
        if dependencies:
            argv.append("--dependency=afterok:" + ":".join(dependencies))
        if comment is not None:
            argv.append("--comment=" + _operation_marker(comment))
        argv.append(str(script_path))
        fallback = SlurmCommandResult(
            command="sbatch",
            argv=tuple(argv),
            returncode=0,
            stdout=f"{self._next_job_id}\n",
            started_at=utc_timestamp(),
            finished_at=utc_timestamp(),
        )
        self._next_job_id += 1
        return self._result("sbatch", tuple(argv), fallback)

    def squeue(self, *, job_ids: Sequence[str] = ()) -> SlurmCommandResult:
        ids = _job_id_tuple(job_ids, field="job_ids")
        argv = ("squeue", "--noheader", "--format", "%i|%T|%r")
        if ids:
            argv = (*argv, "--jobs", ",".join(ids))
        return self._result(
            "squeue",
            argv,
            SlurmCommandResult(command="squeue", argv=argv, returncode=0),
        )

    def sacct(self, *, job_ids: Sequence[str] = ()) -> SlurmCommandResult:
        ids = _job_id_tuple(job_ids, field="job_ids")
        argv = (
            "sacct",
            "--noheader",
            "--parsable2",
            "--format",
            "JobIDRaw,State,ExitCode",
        )
        if ids:
            argv = (*argv, "--jobs", ",".join(ids))
        return self._result(
            "sacct",
            argv,
            SlurmCommandResult(command="sacct", argv=argv, returncode=0),
        )

    def scancel(self, *, job_ids: Sequence[str]) -> SlurmCommandResult:
        ids = _job_id_tuple(job_ids, field="job_ids")
        if not ids:
            raise SlurmPlanningError("scancel requires at least one job ID")
        argv = ("scancel", *ids)
        return self._result(
            "scancel",
            argv,
            SlurmCommandResult(command="scancel", argv=argv, returncode=0),
        )

    def discover_operation(self, operation_marker: str) -> SlurmCommandResult:
        _operation_marker(operation_marker)
        argv = ("squeue", "--noheader", "--format", "%i|%k")
        return self._result(
            "squeue",
            argv,
            SlurmCommandResult(command="squeue", argv=argv, returncode=0),
        )

    def _result(
        self,
        command: str,
        argv: tuple[str, ...],
        fallback: SlurmCommandResult,
    ) -> SlurmCommandResult:
        self.require(command)
        self.calls.append((command, argv))
        scripted = self._scripted.get(command)
        if scripted:
            result = scripted.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return fallback


def parse_sbatch_parsable_output(output: object) -> SlurmParsedJobId:
    """Parse ``sbatch --parsable`` output while preserving bounded raw text."""

    raw = bound_scheduler_output(output, field="sbatch.stdout")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SlurmJobIdParseError(
            "sbatch --parsable output must contain exactly one non-empty line"
        )
    match = _SBATCH_PARSABLE_RE.fullmatch(lines[0])
    if match is None:
        raise SlurmJobIdParseError(
            "sbatch --parsable output must be '<job_id>' or '<job_id>;<cluster>'"
        )
    return SlurmParsedJobId(
        job_id=match.group("job_id"),
        cluster=match.group("cluster"),
        raw_output=raw,
    )


def bound_scheduler_output(value: object, *, field: str = "output") -> str:
    """Return artifact-safe, bounded scheduler output text."""

    if value is None:
        return ""
    if not isinstance(value, str):
        raise SlurmPlanningError(f"{field} must be a string")
    sanitized = "".join(
        ch if ch in {"\n", "\t"} or (ord(ch) >= 32 and ord(ch) != 127) else "?"
        for ch in value
    )
    if len(sanitized) <= MAX_PERSISTED_COMMAND_OUTPUT_CHARS:
        return sanitized
    suffix = "...[truncated]"
    return sanitized[: MAX_PERSISTED_COMMAND_OUTPUT_CHARS - len(suffix)] + suffix


def command_result_from_exception(
    *,
    command: str,
    argv: Sequence[str],
    exc: BaseException,
    started_at: str | None = None,
) -> SlurmCommandResult:
    """Represent a caught command exception as a persisted command record."""

    return SlurmCommandResult(
        command=command,
        argv=argv,
        returncode=127,
        stderr=str(exc) or type(exc).__name__,
        started_at=started_at,
        finished_at=utc_timestamp(),
    )


def _job_id_tuple(value: Sequence[str], *, field: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise SlurmPlanningError(f"{field} must be a sequence of job IDs")
    job_ids: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.isdecimal():
            raise SlurmPlanningError(f"{field}[{index}] must be decimal job ID text")
        job_ids.append(item)
    return tuple(job_ids)


def _argv_tuple(value: Sequence[str], *, path: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise SlurmPlanningError(f"{path} must be a sequence of strings")
    argv: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise SlurmPlanningError(f"{path}[{index}] must be a non-empty string")
        if any(ord(ch) < 32 for ch in item):
            raise SlurmPlanningError(f"{path}[{index}] must not contain control chars")
        argv.append(item)
    if not argv:
        raise SlurmPlanningError(f"{path} must not be empty")
    return tuple(argv)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SlurmPlanningError(f"{field} must be a non-empty string")
    if any(ord(ch) < 32 for ch in value):
        raise SlurmPlanningError(f"{field} must not contain control characters")
    return value


def _operation_marker(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 120
        or any(
            char
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:@+"
            for char in value
        )
    ):
        raise SlurmPlanningError("operation marker is invalid")
    return value


def _sequence(value: object, *, path: str) -> Sequence[str]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SlurmPlanningError(f"{path} must be a sequence")
    return cast(Sequence[str], value)


def _validate_optional_timestamp(value: object, *, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise SlurmPlanningError(f"{field} must be a string or null")
    try:
        parse_timestamp(value)
    except ValueError as exc:
        raise SlurmPlanningError(f"{field} must be a valid timestamp: {exc}") from exc


__all__ = [
    "FakeSlurmCommandRunner",
    "MAX_PERSISTED_COMMAND_OUTPUT_CHARS",
    "SLURM_COMMAND_RESULT_SCHEMA_VERSION",
    "SlurmCommandResult",
    "SlurmCommandRunner",
    "SlurmParsedJobId",
    "SubprocessSlurmCommandRunner",
    "bound_scheduler_output",
    "command_result_from_exception",
    "parse_sbatch_parsable_output",
]
