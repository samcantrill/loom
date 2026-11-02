"""Fakeable SLURM command runner contracts for live operations."""

from __future__ import annotations

import math
import os
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    import subprocess

from loom.serialization import PlainData, load_versioned_document
from loom.serialization.errors import SchemaVersionError
from loom.timestamps import parse_timestamp, utc_timestamp

from .errors import (
    SlurmCommandOutputLimitError,
    SlurmCommandUnavailableError,
    SlurmJobIdParseError,
    SlurmPlanningError,
)
from .history import SlurmAccountingIdentity, accounting_batch_argv, accounting_query_argv

SLURM_COMMAND_RESULT_SCHEMA_VERSION = 1
MAX_PERSISTED_COMMAND_OUTPUT_CHARS = 4096

_CLIENT_ENVIRONMENT_KEYS = frozenset({
    "PATH", "TMPDIR", "TMP", "TEMP", "LC_ALL", "LANG", "TZ", "LD_LIBRARY_PATH",
})


def _client_environment(value: object) -> Mapping[str, str] | None:
    """Freeze explicit non-secret client settings without inspecting the host."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or "PATH" not in value:
        raise SlurmPlanningError("client_environment requires an explicit PATH mapping")
    selected: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or key not in _CLIENT_ENVIRONMENT_KEYS:
            raise SlurmPlanningError("client_environment contains an unsupported variable")
        if (
            not isinstance(item, str) or not item
            or any(ord(char) < 32 or ord(char) == 127 for char in item)
        ):
            raise SlurmPlanningError(f"client_environment {key} requires nonempty literal text")
        paths = item.split(os.pathsep) if key in {"PATH", "LD_LIBRARY_PATH"} else (
            [item] if key in {"TMPDIR", "TMP", "TEMP"} else []
        )
        if any(not Path(path).is_absolute() or ".." in Path(path).parts for path in paths):
            raise SlurmPlanningError(f"client_environment {key} requires absolute paths without '..'")
        selected[key] = item
    return MappingProxyType(selected)


def ready_stage_client_environment(runner: SlurmCommandRunner) -> Mapping[str, str] | None:
    """Read an optional client selection without changing legacy runner contracts."""
    return _client_environment(getattr(runner, "client_environment", None))


def _effective_client_environment(
    selected: Mapping[str, str] | None,
    requested: Mapping[str, str] | None,
    *,
    accounting: bool,
) -> dict[str, str] | None:
    if selected is None:
        return None if requested is None else dict(requested)
    if requested:
        raise SlurmPlanningError("per-call environment cannot override client_environment")
    environment = dict(selected)
    if accounting:
        environment.update(TZ="UTC", SLURM_TIME_FORMAT="%Y-%m-%dT%H:%M:%S")
    return environment

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
class SlurmCommandPolicy:
    """Explicit command deadlines and conservative ready-stage submission errors.

    Deadlines bound ordinary subprocess execution, not uninterruptible kernel
    IO. A selected policy never treats an unclassified nonzero sbatch exit as
    proof that the controller did not accept an allocation.
    """

    observation_timeout_seconds: float
    submission_timeout_seconds: float
    cancellation_timeout_seconds: float

    def __post_init__(self) -> None:
        for name in (
            "observation_timeout_seconds",
            "submission_timeout_seconds",
            "cancellation_timeout_seconds",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SlurmPlanningError(f"{name} must be finite and positive")
            try:
                normalized = float(value)
            except OverflowError as exc:
                raise SlurmPlanningError(f"{name} must be finite and positive") from exc
            if not math.isfinite(normalized) or not 0 < normalized <= 3600:
                raise SlurmPlanningError(f"{name} must be finite and in (0, 3600]")
            object.__setattr__(self, name, normalized)

    def timeout_for(self, command: str) -> float:
        if command == "sbatch":
            return self.submission_timeout_seconds
        if command == "scancel":
            return self.cancellation_timeout_seconds
        if command in {"squeue", "sacct"}:
            return self.observation_timeout_seconds
        raise SlurmPlanningError("unsupported bounded scheduler command")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": "bounded-command-v1",
            "observation_timeout_seconds": self.observation_timeout_seconds,
            "submission_timeout_seconds": self.submission_timeout_seconds,
            "cancellation_timeout_seconds": self.cancellation_timeout_seconds,
        }


def _command_policy(value: object) -> SlurmCommandPolicy | None:
    if value is None or isinstance(value, SlurmCommandPolicy):
        return value
    if not isinstance(value, Mapping) or set(value) != {
        "observation_timeout_seconds",
        "submission_timeout_seconds",
        "cancellation_timeout_seconds",
    }:
        raise SlurmPlanningError("command_policy requires all three scheduler deadlines")
    return SlurmCommandPolicy(
        observation_timeout_seconds=cast(float, value["observation_timeout_seconds"]),
        submission_timeout_seconds=cast(float, value["submission_timeout_seconds"]),
        cancellation_timeout_seconds=cast(float, value["cancellation_timeout_seconds"]),
    )


def ready_stage_command_policy(runner: SlurmCommandRunner) -> SlurmCommandPolicy | None:
    """Read the optional typed policy exposed by a selected command adapter."""
    value = getattr(runner, "command_policy", None)
    if value is not None and not isinstance(value, SlurmCommandPolicy):
        raise SlurmPlanningError("runner command_policy must be a SlurmCommandPolicy")
    return value


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
        environment: Mapping[str, str] | None = None,
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

    def discover_live_operations(self) -> SlurmCommandResult:
        """Return bounded live job/comment rows for exact local filtering."""
        ...

    def discover_accounted_operations(
        self, *, started_after: str
    ) -> SlurmCommandResult:
        """Return bounded retained allocation/comment rows for local filtering."""
        ...


class SubprocessSlurmCommandRunner:
    """SLURM commands with optional deadlines and explicit client environment.

    Selected client settings replace inheritance for every scheduler command and
    select executable lookup. Submission remains ``--export=NIL``; per-call
    environment may only be absent or empty in this mode. Values are non-secret,
    literal configuration bound into a ready-stage profile's identity.
    """

    def __init__(
        self, *, command_policy: SlurmCommandPolicy | Mapping[str, object] | None = None,
        client_environment: Mapping[str, str] | None = None,
    ) -> None:
        self._command_policy = _command_policy(command_policy)
        self._client_environment = _client_environment(client_environment)

    @property
    def command_policy(self) -> SlurmCommandPolicy | None:
        return self._command_policy

    @property
    def client_environment(self) -> Mapping[str, str] | None:
        return self._client_environment

    def _executable(self, command: str) -> str:
        command_text = _required_text(command, "command")
        executable = (
            shutil.which(command_text) if self.client_environment is None
            else shutil.which(command_text, path=self.client_environment["PATH"])
        )
        if executable is None:
            raise SlurmCommandUnavailableError(
                f"required SLURM command is not available on selected PATH: {command_text}"
            )
        return executable

    def require(self, command: str) -> None:
        self._executable(command)

    def sbatch(
        self,
        script_path: str | Path,
        *,
        dependency_job_ids: Sequence[str] = (),
        comment: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> SlurmCommandResult:
        argv = ["sbatch", "--parsable"]
        dependencies = _job_id_tuple(dependency_job_ids, field="dependency_job_ids")
        if dependencies:
            argv.append("--dependency=afterok:" + ":".join(dependencies))
        if comment is not None:
            argv.append("--comment=" + _operation_marker(comment))
        argv.append(str(script_path))
        return self._run("sbatch", argv, environment=environment)

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

    def discover_live_operations(self) -> SlurmCommandResult:
        return self._run(
            "squeue",
            ["squeue", "--noheader", "--format", "%i|%k"],
        )

    def discover_accounted_operations(
        self, *, started_after: str
    ) -> SlurmCommandResult:
        timestamp = _required_text(started_after, "started_after")
        return self._run(
            "sacct",
            [
                "sacct",
                "--noheader",
                "--parsable2",
                "--allocations",
                f"--starttime={timestamp}",
                "--format",
                "JobIDRaw,Comment,Cluster",
            ],
        )

    def _run(
        self,
        command: str,
        argv: Sequence[str],
        *,
        environment: Mapping[str, str] | None = None,
        _timeout_seconds: float | None = None,
    ) -> SlurmCommandResult:
        import subprocess

        process_environment = _effective_client_environment(
            self.client_environment, environment, accounting=command == "sacct",
        )
        timeout = (
            None if _timeout_seconds is None
            else _observation_timeout(self.command_policy, _timeout_seconds)
        )
        executable = self._executable(command)
        started_at = utc_timestamp()
        if command == "sbatch" and (environment is not None or self.client_environment is not None):
            argv = [*argv[:-1], "--export=NIL", argv[-1]]
        execution_argv = (
            list(argv) if self.client_environment is None else [executable, *argv[1:]]
        )
        if self.command_policy is None:
            completed = subprocess.run(  # noqa: S603
                execution_argv, check=False, capture_output=True, text=True,
                env=process_environment,
            )
        else:
            completed = _run_bounded_command(
                execution_argv, timeout=(self.command_policy.timeout_for(command) if timeout is None else timeout),
                environment=process_environment,
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

    def discover_named_operation(
        self, *, job_name: str, user_id: int, cluster: str,
        started_after: str, ended_before: str,
    ) -> SlurmCommandResult:
        """Query exact-name, duplicate-aware UTC accounting without comments."""
        argv = accounting_query_argv(
            job_name=job_name, user_id=user_id, cluster=cluster,
            started_after=started_after, ended_before=ended_before,
        )
        environment = None if self.client_environment is not None else {
            **os.environ, "TZ": "UTC", "SLURM_TIME_FORMAT": "%Y-%m-%dT%H:%M:%S",
        }
        return self._run("sacct", argv, environment=environment)

    def discover_named_operations(
        self, *, job_names: Sequence[str], user_id: int, cluster: str,
        started_after: str, ended_before: str, timeout_seconds: float,
    ) -> SlurmCommandResult:
        """Bound a complete exact-name batch by the caller's remaining budget."""
        argv = accounting_batch_argv(
            job_names=job_names, user_id=user_id, cluster=cluster,
            started_after=started_after, ended_before=ended_before,
        )
        environment = None if self.client_environment is not None else {
            **os.environ, "TZ": "UTC", "SLURM_TIME_FORMAT": "%Y-%m-%dT%H:%M:%S",
        }
        return self._run("sacct", argv, environment=environment, _timeout_seconds=timeout_seconds)

    def scancel_named_operation(self, identity: SlurmAccountingIdentity) -> SlurmCommandResult:
        """Constrain cancellation by the retained operation name, UID and cluster."""
        if not isinstance(identity, SlurmAccountingIdentity):
            raise SlurmPlanningError("named cancellation requires accounting identity")
        return self._run("scancel", [
            "scancel", f"--clusters={identity.cluster}",
            f"--user={identity.user_id}", f"--name={identity.job_name}", identity.job_id,
        ])


def _observation_timeout(policy: SlurmCommandPolicy | None, value: float) -> float:
    if policy is None:
        raise SlurmPlanningError("batched accounting requires a command policy")
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not 0 < value <= 3600:
        raise SlurmPlanningError("accounting timeout must be in (0, 3600]")
    return min(float(value), policy.observation_timeout_seconds)


def _run_bounded_command(
    argv: Sequence[str], *, timeout: float, environment: Mapping[str, str] | None,
) -> subprocess.CompletedProcess[str]:
    """Stop this command's process group before returning an uncertain timeout."""
    from loom._bounded_process import ProcessOutputLimitError, run_bounded_process

    if os.name != "posix":
        raise SlurmPlanningError("bounded scheduler commands require POSIX process groups")
    executable = shutil.which(argv[0])
    if executable is None:
        raise SlurmCommandUnavailableError("bounded scheduler executable is unavailable")
    try:
        return run_bounded_process(
            argv, executable=executable, timeout=timeout, environment=environment,
            output_limit=MAX_PERSISTED_COMMAND_OUTPUT_CHARS, text=True,
        )
    except ProcessOutputLimitError as exc:
        raise SlurmCommandOutputLimitError("bounded scheduler output exceeds the evidence limit") from exc


class FakeSlurmCommandRunner:
    """Deterministic command runner for local tests."""

    def __init__(
        self,
        *,
        scripted_results: Mapping[str, Sequence[SlurmCommandResult | BaseException]]
        | None = None,
        unavailable_commands: Sequence[str] = (),
        starting_job_id: int = 1000,
        command_policy: SlurmCommandPolicy | Mapping[str, object] | None = None,
        client_environment: Mapping[str, str] | None = None,
    ) -> None:
        self.command_policy = _command_policy(command_policy)
        self._client_environment = _client_environment(client_environment)
        self._scripted: dict[str, list[SlurmCommandResult | BaseException]] = {
            command: list(results)
            for command, results in dict(scripted_results or {}).items()
        }
        self._unavailable = frozenset(str(command) for command in unavailable_commands)
        self._next_job_id = starting_job_id
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.environments: list[Mapping[str, str] | None] = []
        # Effective explicit settings in calls order; legacy inheritance is None.
        self.client_environments: list[Mapping[str, str] | None] = []
        self.observation_timeouts: list[float] = []

    @property
    def client_environment(self) -> Mapping[str, str] | None:
        return self._client_environment

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
        environment: Mapping[str, str] | None = None,
    ) -> SlurmCommandResult:
        _effective_client_environment(self.client_environment, environment, accounting=False)
        argv = ["sbatch", "--parsable"]
        dependencies = _job_id_tuple(dependency_job_ids, field="dependency_job_ids")
        if dependencies:
            argv.append("--dependency=afterok:" + ":".join(dependencies))
        if comment is not None:
            argv.append("--comment=" + _operation_marker(comment))
        if environment is not None or self.client_environment is not None:
            argv.append("--export=NIL")
        argv.append(str(script_path))
        self.environments.append(None if environment is None else dict(environment))
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

    def discover_live_operations(self) -> SlurmCommandResult:
        argv = ("squeue", "--noheader", "--format", "%i|%k")
        return self._result(
            "squeue",
            argv,
            SlurmCommandResult(command="squeue", argv=argv, returncode=0),
        )

    def discover_accounted_operations(
        self, *, started_after: str
    ) -> SlurmCommandResult:
        timestamp = _required_text(started_after, "started_after")
        argv = (
            "sacct",
            "--noheader",
            "--parsable2",
            "--allocations",
            f"--starttime={timestamp}",
            "--format",
            "JobIDRaw,Comment,Cluster",
        )
        return self._result(
            "sacct",
            argv,
            SlurmCommandResult(command="sacct", argv=argv, returncode=0),
        )

    def discover_named_operation(
        self, *, job_name: str, user_id: int, cluster: str,
        started_after: str, ended_before: str,
    ) -> SlurmCommandResult:
        argv = accounting_query_argv(
            job_name=job_name, user_id=user_id, cluster=cluster,
            started_after=started_after, ended_before=ended_before,
        )
        return self._result("sacct", argv, SlurmCommandResult("sacct", argv, 0))

    def scancel_named_operation(self, identity: SlurmAccountingIdentity) -> SlurmCommandResult:
        if not isinstance(identity, SlurmAccountingIdentity):
            raise SlurmPlanningError("named cancellation requires accounting identity")
        argv = (
            "scancel", f"--clusters={identity.cluster}",
            f"--user={identity.user_id}", f"--name={identity.job_name}", identity.job_id,
        )
        return self._result("scancel", argv, SlurmCommandResult("scancel", argv, 0))

    def discover_named_operations(
        self, *, job_names: Sequence[str], user_id: int, cluster: str,
        started_after: str, ended_before: str, timeout_seconds: float,
    ) -> SlurmCommandResult:
        timeout = _observation_timeout(self.command_policy, timeout_seconds)
        argv = accounting_batch_argv(
            job_names=job_names, user_id=user_id, cluster=cluster,
            started_after=started_after, ended_before=ended_before,
        )
        self.observation_timeouts.append(timeout)
        return self._result("sacct", argv, SlurmCommandResult("sacct", argv, 0))

    def _result(
        self,
        command: str,
        argv: tuple[str, ...],
        fallback: SlurmCommandResult,
    ) -> SlurmCommandResult:
        self.require(command)
        self.calls.append((command, argv))
        self.client_environments.append(_effective_client_environment(
            self.client_environment, None, accounting=command == "sacct",
        ))
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
