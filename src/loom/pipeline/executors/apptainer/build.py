"""Apptainer SIF build helpers over shared container build requests."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
import shutil
from types import MappingProxyType
from typing import Protocol, cast

from loom.pipeline.executors.containers import (
    ContainerBuildAction,
    ContainerBuildCommandProjection,
    ContainerBuildEvidence,
    ContainerBuildFailure,
    ContainerBuildOutputKind,
    ContainerBuildOutputRef,
    ContainerBuildRequest,
    ContainerBuildResult,
    ContainerBuildRuntime,
    ContainerBuildSource,
    ContainerBuildSourceKind,
    ContainerBuildStatus,
    ContainerBuildTarget,
    ContainerOptionError,
    evaluate_container_build_policy,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import utc_timestamp


APPTAINER_COMMAND_RESULT_SCHEMA_VERSION = 1
MAX_APPTAINER_OUTPUT_CHARS = 4096
TRUNCATED_OUTPUT_SUFFIX = "...[truncated]"

_BUILD_OPTIONS_FIELDS = frozenset(
    {"command", "fakeroot", "force", "notest", "sandbox"}
)


class ApptainerOptionError(ContainerOptionError):
    """Raised when Apptainer build options or results are invalid."""


class ApptainerCommandUnavailableError(ApptainerOptionError):
    """Raised when the configured Apptainer command is unavailable."""


@dataclass(frozen=True, slots=True)
class ApptainerBuildOptions:
    """Apptainer-owned options for local SIF build commands."""

    command: str = "apptainer"
    fakeroot: bool = False
    force: bool = False
    notest: bool = False
    sandbox: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "command",
            _text(self.command, path="ApptainerBuildOptions.command"),
        )
        for field_name in ("fakeroot", "force", "notest", "sandbox"):
            if not isinstance(getattr(self, field_name), bool):
                raise ApptainerOptionError(
                    f"ApptainerBuildOptions.{field_name} must be a bool"
                )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "command": self.command,
            "fakeroot": self.fakeroot,
            "force": self.force,
            "notest": self.notest,
            "sandbox": self.sandbox,
        }

    @classmethod
    def from_dict(cls, data: object | None) -> "ApptainerBuildOptions":
        if data is None:
            return cls()
        mapping = _plain_mapping(data, path="ApptainerBuildOptions")
        _reject_unknown(mapping, _BUILD_OPTIONS_FIELDS, path="ApptainerBuildOptions")
        return cls(
            command=_text(
                mapping.get("command", "apptainer"),
                path="ApptainerBuildOptions.command",
            ),
            fakeroot=_bool(
                mapping.get("fakeroot", False),
                path="ApptainerBuildOptions.fakeroot",
            ),
            force=_bool(
                mapping.get("force", False),
                path="ApptainerBuildOptions.force",
            ),
            notest=_bool(
                mapping.get("notest", False),
                path="ApptainerBuildOptions.notest",
            ),
            sandbox=_bool(
                mapping.get("sandbox", False),
                path="ApptainerBuildOptions.sandbox",
            ),
        )


@dataclass(frozen=True, slots=True)
class ApptainerBuildCommand:
    """Shell-free Apptainer build argv plus redacted projection."""

    argv: Sequence[str]
    redacted_argv: Sequence[str] | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        argv = _argv_tuple(self.argv, path="ApptainerBuildCommand.argv")
        redacted = (
            argv
            if self.redacted_argv is None
            else _argv_tuple(
                self.redacted_argv,
                path="ApptainerBuildCommand.redacted_argv",
            )
        )
        if len(argv) != len(redacted):
            raise ApptainerOptionError(
                "ApptainerBuildCommand.redacted_argv must match argv length"
            )
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "redacted_argv", redacted)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(
                dict(_plain_mapping(self.metadata, path="ApptainerBuildCommand.metadata"))
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "argv": list(self.argv),
            "redacted_argv": list(cast(tuple[str, ...], self.redacted_argv)),
            "metadata": _thaw_mapping(
                self.metadata,
                path="ApptainerBuildCommand.metadata",
            ),
        }


@dataclass(frozen=True, slots=True)
class ApptainerCommandResult:
    """Bounded Apptainer command result safe for build evidence."""

    command: str
    argv: Sequence[str]
    redacted_argv: Sequence[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    timed_out: bool = False
    timeout_seconds: int | float | None = None
    error: str | None = None
    schema_version: int = APPTAINER_COMMAND_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != APPTAINER_COMMAND_RESULT_SCHEMA_VERSION:
            raise ApptainerOptionError(
                "unsupported ApptainerCommandResult schema_version "
                f"{self.schema_version!r}"
            )
        object.__setattr__(
            self,
            "command",
            _text(self.command, path="ApptainerCommandResult.command"),
        )
        argv = _argv_tuple(self.argv, path="ApptainerCommandResult.argv")
        redacted = _argv_tuple(
            self.redacted_argv,
            path="ApptainerCommandResult.redacted_argv",
        )
        if len(argv) != len(redacted):
            raise ApptainerOptionError(
                "ApptainerCommandResult.redacted_argv must match argv length"
            )
        if not isinstance(self.returncode, int) or isinstance(self.returncode, bool):
            raise ApptainerOptionError(
                "ApptainerCommandResult.returncode must be an integer"
            )
        if not isinstance(self.timed_out, bool):
            raise ApptainerOptionError(
                "ApptainerCommandResult.timed_out must be a bool"
            )
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "redacted_argv", redacted)
        object.__setattr__(
            self,
            "stdout",
            _bound_output(self.stdout, field="ApptainerCommandResult.stdout"),
        )
        object.__setattr__(
            self,
            "stderr",
            _bound_output(self.stderr, field="ApptainerCommandResult.stderr"),
        )
        object.__setattr__(
            self,
            "timeout_seconds",
            _optional_positive_number(
                self.timeout_seconds,
                path="ApptainerCommandResult.timeout_seconds",
            ),
        )
        if self.error is not None:
            object.__setattr__(
                self,
                "error",
                _bound_output(self.error, field="ApptainerCommandResult.error"),
            )

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "command": self.command,
            "argv": list(self.argv),
            "redacted_argv": list(self.redacted_argv),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "timed_out": self.timed_out,
            "timeout_seconds": self.timeout_seconds,
            "error": self.error,
        }


class ApptainerCommandRunner(Protocol):
    """Protocol for fakeable Apptainer build command execution."""

    def require(self, command: str) -> None:
        """Raise when the Apptainer command is unavailable."""
        ...

    def run(
        self,
        command: ApptainerBuildCommand,
        *,
        timeout_seconds: int | float | None = None,
    ) -> ApptainerCommandResult:
        """Run one Apptainer build command."""
        ...


class SubprocessApptainerCommandRunner:
    """Apptainer command runner backed by local subprocess calls."""

    def __init__(self, *, clock: object = utc_timestamp) -> None:
        if not callable(clock):
            raise ApptainerOptionError(
                "SubprocessApptainerCommandRunner.clock must be callable"
            )
        self.clock = cast("Clock", clock)

    def require(self, command: str) -> None:
        command_text = _text(command, path="command")
        if shutil.which(command_text) is None:
            raise ApptainerCommandUnavailableError(
                "required Apptainer command is not available on PATH: "
                f"{command_text}"
            )

    def run(
        self,
        command: ApptainerBuildCommand,
        *,
        timeout_seconds: int | float | None = None,
    ) -> ApptainerCommandResult:
        run_command = _run_command(command)
        timeout = _optional_positive_number(timeout_seconds, path="timeout_seconds")
        self.require(run_command.argv[0])
        started_at = self.clock()
        try:
            import subprocess

            completed = subprocess.run(  # noqa: S603
                list(run_command.argv),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - command-launch facts are returned.
            return _result_from_exception(
                command=run_command.argv[0],
                argv=run_command.argv,
                redacted_argv=cast(tuple[str, ...], run_command.redacted_argv),
                exc=exc,
                started_at=started_at,
                finished_at=self.clock(),
                timeout_seconds=timeout,
            )
        return ApptainerCommandResult(
            command=run_command.argv[0],
            argv=run_command.argv,
            redacted_argv=cast(tuple[str, ...], run_command.redacted_argv),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            started_at=started_at,
            finished_at=self.clock(),
        )


class FakeApptainerCommandRunner:
    """Deterministic Apptainer command runner for tests."""

    def __init__(
        self,
        *,
        scripted_results: Sequence[ApptainerCommandResult | BaseException] = (),
        unavailable_commands: Sequence[str] = (),
        clock: object = utc_timestamp,
    ) -> None:
        if not callable(clock):
            raise ApptainerOptionError("FakeApptainerCommandRunner.clock must be callable")
        self._scripted = list(scripted_results)
        self._unavailable = frozenset(
            _text(command, path="unavailable_commands[]")
            for command in unavailable_commands
        )
        self.clock = cast("Clock", clock)
        self.calls: list[ApptainerBuildCommand] = []

    def require(self, command: str) -> None:
        command_text = _text(command, path="command")
        if command_text in self._unavailable:
            raise ApptainerCommandUnavailableError(
                "required Apptainer command is not available in fake runner: "
                f"{command_text}"
            )

    def run(
        self,
        command: ApptainerBuildCommand,
        *,
        timeout_seconds: int | float | None = None,
    ) -> ApptainerCommandResult:
        run_command = _run_command(command)
        timeout = _optional_positive_number(timeout_seconds, path="timeout_seconds")
        self.require(run_command.argv[0])
        self.calls.append(run_command)
        if self._scripted:
            result = self._scripted.pop(0)
            if isinstance(result, BaseException):
                return _result_from_exception(
                    command=run_command.argv[0],
                    argv=run_command.argv,
                    redacted_argv=cast(tuple[str, ...], run_command.redacted_argv),
                    exc=result,
                    started_at=self.clock(),
                    finished_at=self.clock(),
                    timeout_seconds=timeout,
                )
            return result
        return ApptainerCommandResult(
            command=run_command.argv[0],
            argv=run_command.argv,
            redacted_argv=cast(tuple[str, ...], run_command.redacted_argv),
            returncode=0,
            started_at=self.clock(),
            finished_at=self.clock(),
        )


class ApptainerContainerBuilder:
    """Foreground Apptainer SIF builder for shared build requests."""

    def __init__(
        self,
        *,
        runner: ApptainerCommandRunner | None = None,
        options: ApptainerBuildOptions | Mapping[str, object] | None = None,
        workspace_root: str | Path = ".",
        timeout_seconds: int | float | None = None,
    ) -> None:
        self.runner = runner or SubprocessApptainerCommandRunner()
        self.options = _build_options(options)
        self.workspace_root = Path(workspace_root)
        self.timeout_seconds = _optional_positive_number(
            timeout_seconds,
            path="ApptainerContainerBuilder.timeout_seconds",
        )

    def build(self, request: ContainerBuildRequest) -> ContainerBuildResult:
        parsed = _request(request)
        target = _apptainer_target(cast(ContainerBuildTarget, parsed.target))
        output = cast(ContainerBuildOutputRef, target.output)
        output_path = _workspace_path(self.workspace_root, cast(str, output.path))
        output_exists = output_path.exists()
        source_probe = _source_probe(self.workspace_root, target)
        decision = evaluate_container_build_policy(
            target,
            output_exists=output_exists,
            source_stale=source_probe.stale_when_output_exists(output_path),
        )
        evidence = _evidence(decision=decision.to_dict(), operation="probe")
        if decision.action is ContainerBuildAction.REUSE:
            return ContainerBuildResult(
                target_name=target.name,
                status=ContainerBuildStatus.REUSED,
                output=output,
                build_key=parsed.build_key,
                evidence=evidence,
            )
        if decision.action is ContainerBuildAction.FAIL:
            return _failure_result(
                request=parsed,
                code="container_build.policy_missing_output",
                message=decision.reason,
                details={"decision": decision.to_dict()},
                evidence=evidence,
            )
        if source_probe.missing:
            return _failure_result(
                request=parsed,
                code="container_build.source_missing",
                message=f"local Apptainer build source is missing: {source_probe.source}",
                details={"source": source_probe.source},
                evidence=evidence,
            )
        command = build_apptainer_build_command(parsed, options=self.options)
        projection = _projection(command)
        try:
            result = self.runner.run(command, timeout_seconds=self.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - command availability becomes evidence.
            return _failure_result(
                request=parsed,
                code="container_build.apptainer_launch_failed",
                message="apptainer build command could not be launched",
                details={"error": _exception_name(exc)},
                command=projection,
                evidence=_evidence(
                    decision=decision.to_dict(),
                    operation="build",
                ),
            )
        if not result.ok:
            return _failure_result(
                request=parsed,
                code="container_build.apptainer_failed",
                message="apptainer build command failed",
                details=_result_details(result),
                command=projection,
                evidence=_evidence(
                    decision=decision.to_dict(),
                    operation="build",
                    returncode=result.returncode,
                ),
            )
        return ContainerBuildResult(
            target_name=target.name,
            status=ContainerBuildStatus.BUILT,
            output=output,
            build_key=parsed.build_key,
            command=projection,
            evidence=_evidence(
                decision=decision.to_dict(),
                operation="build",
                returncode=result.returncode,
            ),
        )


@dataclass(frozen=True, slots=True)
class _SourceProbe:
    source: str
    mtime: float | None
    missing: bool

    def stale_when_output_exists(self, output_path: Path) -> bool | None:
        if not output_path.exists():
            return None
        if self.missing:
            return True
        if self.mtime is None:
            return None
        return self.mtime > output_path.stat().st_mtime


Clock = Callable[[], str]


def build_apptainer_build_command(
    request: ContainerBuildRequest | Mapping[str, object],
    *,
    options: ApptainerBuildOptions | Mapping[str, object] | None = None,
) -> ApptainerBuildCommand:
    """Return a deterministic ``apptainer build`` argv for one request."""

    parsed = _request(request)
    target = _apptainer_target(cast(ContainerBuildTarget, parsed.target))
    if target.build_args:
        raise ApptainerOptionError(
            "Apptainer build targets do not support build_args in Phase 2"
        )
    build_options = _build_options(options)
    source = cast(ContainerBuildSource, target.source)
    output = cast(ContainerBuildOutputRef, target.output)
    argv: list[str] = [build_options.command, "build"]
    redacted: list[str] = [build_options.command, "build"]
    if build_options.fakeroot:
        _append(argv, redacted, "--fakeroot")
    if build_options.force:
        _append(argv, redacted, "--force")
    if build_options.notest:
        _append(argv, redacted, "--notest")
    if build_options.sandbox:
        _append(argv, redacted, "--sandbox")
    _append(argv, redacted, cast(str, output.path))
    _append(argv, redacted, _source_argument(source))
    return ApptainerBuildCommand(
        argv=argv,
        redacted_argv=redacted,
        metadata={
            "builder": "apptainer",
            "operation": "build",
            "target": target.to_redacted_metadata(),
            "apptainer_build_options": build_options.to_dict(),
        },
    )


def _projection(command: ApptainerBuildCommand) -> ContainerBuildCommandProjection:
    return ContainerBuildCommandProjection(
        argv=cast(Sequence[str], command.redacted_argv),
        metadata={
            "builder": "apptainer",
            "operation": "build",
            "command": cast(Sequence[str], command.argv)[0],
        },
    )


def _evidence(
    *,
    decision: Mapping[str, PlainData],
    operation: str,
    returncode: int | None = None,
) -> ContainerBuildEvidence:
    metadata: dict[str, PlainData] = {
        "operation": operation,
        "decision": dict(decision),
    }
    if returncode is not None:
        metadata["returncode"] = returncode
    return ContainerBuildEvidence(builder="apptainer", metadata=metadata)


def _failure_result(
    *,
    request: ContainerBuildRequest,
    code: str,
    message: str,
    details: Mapping[str, PlainData],
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
        failure=ContainerBuildFailure(code=code, message=message, details=details),
    )


def _result_details(result: ApptainerCommandResult) -> dict[str, PlainData]:
    details: dict[str, PlainData] = {
        "returncode": result.returncode,
        "timed_out": result.timed_out,
    }
    if result.error:
        details["error"] = result.error
    return details


def _source_probe(root: Path, target: ContainerBuildTarget) -> _SourceProbe:
    source = cast(ContainerBuildSource, target.source)
    if source.kind is ContainerBuildSourceKind.URI:
        return _SourceProbe(source=cast(str, source.uri), mtime=None, missing=False)
    source_path = _workspace_path(root, _source_argument(source))
    if not source_path.exists():
        return _SourceProbe(source=str(source_path), mtime=None, missing=True)
    return _SourceProbe(
        source=str(source_path),
        mtime=_newest_mtime(source_path),
        missing=False,
    )


def _newest_mtime(path: Path) -> float:
    if path.is_file():
        return path.stat().st_mtime
    newest = path.stat().st_mtime
    for child in path.rglob("*"):
        try:
            newest = max(newest, child.stat().st_mtime)
        except OSError:
            continue
    return newest


def _source_argument(source: ContainerBuildSource) -> str:
    if source.kind is ContainerBuildSourceKind.DEFINITION_FILE:
        return cast(str, source.path)
    if source.kind is ContainerBuildSourceKind.LOCAL_PATH:
        return cast(str, source.path)
    if source.kind is ContainerBuildSourceKind.URI:
        return cast(str, source.uri)
    raise ApptainerOptionError("Apptainer builder does not support docker_context sources")


def _request(
    request: ContainerBuildRequest | Mapping[str, object],
) -> ContainerBuildRequest:
    return (
        request
        if isinstance(request, ContainerBuildRequest)
        else ContainerBuildRequest.from_dict(request)
    )


def _apptainer_target(target: ContainerBuildTarget) -> ContainerBuildTarget:
    if cast(ContainerBuildRuntime, target.runtime) is not ContainerBuildRuntime.APPTAINER:
        raise ApptainerOptionError("Apptainer builder requires an apptainer target")
    output = cast(ContainerBuildOutputRef, target.output)
    if output.kind is not ContainerBuildOutputKind.APPTAINER_SIF:
        raise ApptainerOptionError("Apptainer builder requires an apptainer_sif output")
    return target


def _build_options(
    value: ApptainerBuildOptions | Mapping[str, object] | None,
) -> ApptainerBuildOptions:
    return (
        value
        if isinstance(value, ApptainerBuildOptions)
        else ApptainerBuildOptions.from_dict(value)
    )


def _run_command(command: ApptainerBuildCommand) -> ApptainerBuildCommand:
    if not isinstance(command, ApptainerBuildCommand):
        raise ApptainerOptionError("command must be ApptainerBuildCommand")
    return command


def _append(argv: list[str], redacted: list[str], value: str) -> None:
    text = _text(value, path="argv[]")
    argv.append(text)
    redacted.append(text)


def _workspace_path(root: Path, path: str) -> Path:
    return root / path


def _result_from_exception(
    *,
    command: str,
    argv: Sequence[str],
    redacted_argv: Sequence[str],
    exc: BaseException,
    started_at: str | None = None,
    finished_at: str | None = None,
    timeout_seconds: int | float | None = None,
) -> ApptainerCommandResult:
    timed_out = exc.__class__.__name__ == "TimeoutExpired"
    return ApptainerCommandResult(
        command=command,
        argv=argv,
        redacted_argv=redacted_argv,
        returncode=124 if timed_out else 127,
        started_at=started_at,
        finished_at=finished_at or utc_timestamp(),
        timed_out=timed_out,
        timeout_seconds=timeout_seconds,
        error=exc.__class__.__name__,
    )


def _exception_name(exc: BaseException) -> str:
    return exc.__class__.__name__


def _plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    try:
        normalized = freeze_plain_data(value, path=path)
    except PlainDataError as exc:
        raise ApptainerOptionError(f"{path} must be plain data: {exc}") from exc
    thawed = thaw_plain_data(normalized, path=path)
    if not isinstance(thawed, Mapping):
        raise ApptainerOptionError(f"{path} must be a mapping")
    return MappingProxyType(dict(sorted(cast(Mapping[str, PlainData], thawed).items())))


def _thaw_mapping(value: Mapping[str, PlainData], *, path: str) -> dict[str, PlainData]:
    thawed = thaw_plain_data(value, path=path)
    if not isinstance(thawed, Mapping):
        raise ApptainerOptionError(f"{path} must be a mapping")
    return dict(sorted(cast(Mapping[str, PlainData], thawed).items()))


def _argv_tuple(value: Sequence[str], *, path: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise ApptainerOptionError(f"{path} must be a sequence of strings")
    return tuple(_text(item, path=f"{path}[]") for item in value)


def _text(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ApptainerOptionError(f"{path} must be a non-empty string")
    return value


def _bool(value: object, *, path: str) -> bool:
    if not isinstance(value, bool):
        raise ApptainerOptionError(f"{path} must be a bool")
    return value


def _optional_positive_number(value: object, *, path: str) -> int | float | None:
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        raise ApptainerOptionError(f"{path} must be a positive number")
    return value


def _bound_output(value: object, *, field: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode(errors="replace")
    elif isinstance(value, str):
        text = value
    else:
        raise ApptainerOptionError(f"{field} must be a string")
    sanitized = "".join(
        ch if ch in {"\n", "\t"} or (ord(ch) >= 32 and ord(ch) != 127) else "?"
        for ch in text
    )
    if len(sanitized) <= MAX_APPTAINER_OUTPUT_CHARS:
        return sanitized
    return (
        sanitized[: MAX_APPTAINER_OUTPUT_CHARS - len(TRUNCATED_OUTPUT_SUFFIX)]
        + TRUNCATED_OUTPUT_SUFFIX
    )


def _reject_unknown(
    mapping: Mapping[str, object],
    allowed: frozenset[str],
    *,
    path: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise ApptainerOptionError(f"{path} contains unknown field(s): {fields}")


__all__ = [
    "APPTAINER_COMMAND_RESULT_SCHEMA_VERSION",
    "ApptainerBuildCommand",
    "ApptainerBuildOptions",
    "ApptainerCommandResult",
    "ApptainerCommandRunner",
    "ApptainerContainerBuilder",
    "ApptainerOptionError",
    "FakeApptainerCommandRunner",
    "SubprocessApptainerCommandRunner",
    "build_apptainer_build_command",
]
