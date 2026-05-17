"""Apptainer exec command records and fakeable runners."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import os
import re
import shutil
from types import MappingProxyType
from typing import Protocol, cast

from loom.pipeline.executors.containers import (
    REDACTED_VALUE,
    ContainerEnvironment,
    ContainerImageReference,
    ContainerMount,
    ContainerMountMode,
    ContainerOptions,
    parse_container_options,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import utc_timestamp

from .build import (
    ApptainerCommandResult,
    ApptainerCommandUnavailableError,
    ApptainerOptionError,
)


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXEC_OPTIONS_FIELDS = frozenset(
    {"command", "cleanenv", "nv", "rocm", "fakeroot", "no_home"}
)


@dataclass(frozen=True, slots=True)
class ApptainerExecOptions:
    """Apptainer-owned options for deterministic ``exec`` commands."""

    command: str = "apptainer"
    cleanenv: bool = True
    nv: bool = False
    rocm: bool = False
    fakeroot: bool = False
    no_home: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "command",
            _text(self.command, path="ApptainerExecOptions.command"),
        )
        for field_name in ("cleanenv", "nv", "rocm", "fakeroot", "no_home"):
            if not isinstance(getattr(self, field_name), bool):
                raise ApptainerOptionError(
                    f"ApptainerExecOptions.{field_name} must be a bool"
                )
        if self.nv and self.rocm:
            raise ApptainerOptionError(
                "ApptainerExecOptions.nv and rocm cannot both be true"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "command": self.command,
            "cleanenv": self.cleanenv,
            "nv": self.nv,
            "rocm": self.rocm,
            "fakeroot": self.fakeroot,
            "no_home": self.no_home,
        }

    @classmethod
    def from_dict(cls, data: object | None) -> "ApptainerExecOptions":
        if data is None:
            return cls()
        mapping = _plain_mapping(data, path="ApptainerExecOptions")
        _reject_unknown(mapping, _EXEC_OPTIONS_FIELDS, path="ApptainerExecOptions")
        return cls(
            command=_text(
                mapping.get("command", "apptainer"),
                path="ApptainerExecOptions.command",
            ),
            cleanenv=_bool(
                mapping.get("cleanenv", True),
                path="ApptainerExecOptions.cleanenv",
            ),
            nv=_bool(mapping.get("nv", False), path="ApptainerExecOptions.nv"),
            rocm=_bool(mapping.get("rocm", False), path="ApptainerExecOptions.rocm"),
            fakeroot=_bool(
                mapping.get("fakeroot", False),
                path="ApptainerExecOptions.fakeroot",
            ),
            no_home=_bool(
                mapping.get("no_home", False),
                path="ApptainerExecOptions.no_home",
            ),
        )


@dataclass(frozen=True, slots=True)
class ApptainerExecCommand:
    """Shell-free Apptainer exec argv plus redacted persistence projection."""

    argv: Sequence[str]
    redacted_argv: Sequence[str] | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        argv = _argv_tuple(self.argv, path="ApptainerExecCommand.argv")
        redacted = (
            argv
            if self.redacted_argv is None
            else _argv_tuple(
                self.redacted_argv,
                path="ApptainerExecCommand.redacted_argv",
            )
        )
        if len(argv) != len(redacted):
            raise ApptainerOptionError(
                "ApptainerExecCommand.redacted_argv must match argv length"
            )
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "redacted_argv", redacted)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(
                dict(
                    _plain_mapping(self.metadata, path="ApptainerExecCommand.metadata")
                )
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "argv": list(self.argv),
            "redacted_argv": list(cast(tuple[str, ...], self.redacted_argv)),
            "metadata": _thaw_mapping(
                self.metadata,
                path="ApptainerExecCommand.metadata",
            ),
        }

    @classmethod
    def from_argv(
        cls,
        argv: Sequence[str],
        *,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> "ApptainerExecCommand":
        return cls(argv=argv, redacted_argv=argv, metadata=metadata or {})


class ApptainerExecRunner(Protocol):
    """Protocol for fakeable Apptainer exec command execution."""

    def require(self, command: str) -> None:
        """Raise when the Apptainer command is unavailable."""
        ...

    def run(
        self,
        command: ApptainerExecCommand,
        *,
        timeout_seconds: int | float | None = None,
    ) -> ApptainerCommandResult:
        """Run one Apptainer exec command."""
        ...

    def version(
        self,
        apptainer_options: ApptainerExecOptions | Mapping[str, object] | None = None,
        *,
        timeout_seconds: int | float | None = None,
    ) -> ApptainerCommandResult:
        """Return cheap Apptainer CLI version command evidence."""
        ...


class SubprocessApptainerExecRunner:
    """Apptainer exec runner backed by local subprocess calls."""

    def __init__(self, *, clock: object = utc_timestamp) -> None:
        if not callable(clock):
            raise ApptainerOptionError(
                "SubprocessApptainerExecRunner.clock must be callable"
            )
        self.clock = cast("Clock", clock)

    def require(self, command: str) -> None:
        command_text = _text(command, path="command")
        if shutil.which(command_text) is None:
            raise ApptainerCommandUnavailableError(
                f"required Apptainer command is not available on PATH: {command_text}"
            )

    def run(
        self,
        command: ApptainerExecCommand,
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

    def version(
        self,
        apptainer_options: ApptainerExecOptions | Mapping[str, object] | None = None,
        *,
        timeout_seconds: int | float | None = None,
    ) -> ApptainerCommandResult:
        return self.run(
            build_apptainer_version_command(apptainer_options=apptainer_options),
            timeout_seconds=timeout_seconds,
        )


class FakeApptainerExecRunner:
    """Deterministic Apptainer exec runner for tests."""

    def __init__(
        self,
        *,
        scripted_results: Sequence[ApptainerCommandResult | BaseException] = (),
        unavailable_commands: Sequence[str] = (),
        clock: object = utc_timestamp,
    ) -> None:
        if not callable(clock):
            raise ApptainerOptionError("FakeApptainerExecRunner.clock must be callable")
        self._scripted = list(scripted_results)
        self._unavailable = frozenset(
            _text(command, path="unavailable_commands[]")
            for command in unavailable_commands
        )
        self.clock = cast("Clock", clock)
        self.calls: list[ApptainerExecCommand] = []

    def require(self, command: str) -> None:
        command_text = _text(command, path="command")
        if command_text in self._unavailable:
            raise ApptainerCommandUnavailableError(
                "required Apptainer command is not available in fake runner: "
                f"{command_text}"
            )

    def run(
        self,
        command: ApptainerExecCommand,
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

    def version(
        self,
        apptainer_options: ApptainerExecOptions | Mapping[str, object] | None = None,
        *,
        timeout_seconds: int | float | None = None,
    ) -> ApptainerCommandResult:
        return self.run(
            build_apptainer_version_command(apptainer_options=apptainer_options),
            timeout_seconds=timeout_seconds,
        )


Clock = Callable[[], str]


def build_apptainer_exec_command(
    *,
    container_options: ContainerOptions | Mapping[str, object],
    worker_command: Sequence[str],
    apptainer_options: ApptainerExecOptions | Mapping[str, object] | None = None,
    host_environment: Mapping[str, str] | None = None,
) -> ApptainerExecCommand:
    """Return deterministic ``apptainer exec`` argv for one worker command."""

    container = _container_options(container_options)
    options = _exec_options(apptainer_options)
    worker = _argv_tuple(worker_command, path="worker_command")
    argv: list[str] = [options.command, "exec"]
    redacted: list[str] = [options.command, "exec"]
    if options.cleanenv:
        _append(argv, redacted, "--cleanenv")
    if options.nv:
        _append(argv, redacted, "--nv")
    if options.rocm:
        _append(argv, redacted, "--rocm")
    if options.fakeroot:
        _append(argv, redacted, "--fakeroot")
    if options.no_home:
        _append(argv, redacted, "--no-home")
    if container.workdir is not None:
        _append_option(argv, redacted, "--pwd", container.workdir)
    for mount in _sorted_mounts(container):
        _append_option(argv, redacted, "--bind", _bind_argument(mount))
    _append_environment(
        argv,
        redacted,
        cast(ContainerEnvironment, container.environment),
        host_environment=host_environment,
    )
    image = cast(ContainerImageReference, container.image).reference
    _append(argv, redacted, image)
    for item in worker:
        _append(argv, redacted, item)
    return ApptainerExecCommand(
        argv=argv,
        redacted_argv=redacted,
        metadata={
            "executor": "apptainer",
            "command": options.command,
            "argv": list(redacted),
            "apptainer_options": options.to_dict(),
            "container": container.to_redacted_metadata(),
            "worker_command": list(worker),
        },
    )


def build_apptainer_version_command(
    apptainer_options: ApptainerExecOptions | Mapping[str, object] | None = None,
) -> ApptainerExecCommand:
    """Return a cheap Apptainer CLI version command."""

    options = _exec_options(apptainer_options)
    return ApptainerExecCommand.from_argv(
        (options.command, "--version"),
        metadata={
            "executor": "apptainer",
            "operation": "version",
            "command": options.command,
        },
    )


def _append_environment(
    argv: list[str],
    redacted: list[str],
    environment: ContainerEnvironment,
    *,
    host_environment: Mapping[str, str] | None,
) -> None:
    for name, value in environment.variables.items():
        key = _env_name(name)
        _append(argv, redacted, "--env")
        argv.append(f"{key}={_env_value(value, key=key)}")
        redacted.append(f"{key}={REDACTED_VALUE}")
    host = os.environ if host_environment is None else host_environment
    for name in environment.required_host_variables:
        key = _env_name(name)
        if key not in host:
            raise ApptainerOptionError(
                f"required host environment variable {key!r} is not set"
            )
        _append(argv, redacted, "--env")
        argv.append(f"{key}={_env_value(host[key], key=key)}")
        redacted.append(f"{key}={REDACTED_VALUE}")


def _bind_argument(mount: ContainerMount) -> str:
    mode = cast(ContainerMountMode, mount.mode)
    return f"{mount.source}:{mount.target}:{mode.value}"


def _sorted_mounts(container: ContainerOptions) -> tuple[ContainerMount, ...]:
    return tuple(
        sorted(
            cast(tuple[ContainerMount, ...], container.mounts),
            key=lambda mount: (
                mount.target,
                mount.source,
                cast(ContainerMountMode, mount.mode).value,
            ),
        )
    )


def _container_options(
    value: ContainerOptions | Mapping[str, object],
) -> ContainerOptions:
    return (
        value if isinstance(value, ContainerOptions) else parse_container_options(value)
    )


def _exec_options(
    value: ApptainerExecOptions | Mapping[str, object] | None,
) -> ApptainerExecOptions:
    return (
        value
        if isinstance(value, ApptainerExecOptions)
        else ApptainerExecOptions.from_dict(value)
    )


def _run_command(command: ApptainerExecCommand) -> ApptainerExecCommand:
    if not isinstance(command, ApptainerExecCommand):
        raise ApptainerOptionError("command must be ApptainerExecCommand")
    return command


def _append(argv: list[str], redacted: list[str], value: str) -> None:
    text = _text(value, path="argv[]")
    argv.append(text)
    redacted.append(text)


def _append_option(
    argv: list[str],
    redacted: list[str],
    flag: str,
    value: str | None,
) -> None:
    if value is None:
        return
    _append(argv, redacted, flag)
    _append(argv, redacted, value)


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
    argv_tuple = _argv_tuple(argv, path="argv")
    redacted = _argv_tuple(redacted_argv, path="redacted_argv")
    return ApptainerCommandResult(
        command=command,
        argv=argv_tuple,
        redacted_argv=redacted,
        returncode=124 if timed_out else 127,
        stdout=_exception_stream(exc, "stdout"),
        stderr=_exception_stream(exc, "stderr"),
        started_at=started_at,
        finished_at=finished_at or utc_timestamp(),
        timed_out=timed_out,
        timeout_seconds=timeout_seconds,
        error=_exception_error(exc, argv=argv_tuple, redacted_argv=redacted),
    )


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
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ApptainerOptionError(f"{path} must be a sequence of strings")
    argv = tuple(_text(item, path=f"{path}[]") for item in value)
    if not argv:
        raise ApptainerOptionError(f"{path} must not be empty")
    return argv


def _text(value: object, *, path: str) -> str:
    if not isinstance(value, str):
        raise ApptainerOptionError(f"{path} must be a non-empty string")
    text = value.strip()
    if not text:
        raise ApptainerOptionError(f"{path} must be a non-empty string")
    if _has_control_chars(text):
        raise ApptainerOptionError(f"{path} must not contain control chars")
    return text


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


def _env_name(value: object) -> str:
    text = _text(value, path="environment variable name")
    if _ENV_NAME_RE.fullmatch(text) is None:
        raise ApptainerOptionError(f"invalid environment variable name: {text!r}")
    return text


def _env_value(value: object, *, key: str) -> str:
    if not isinstance(value, str):
        raise ApptainerOptionError(f"environment variable {key!r} must be a string")
    if _has_control_chars(value):
        raise ApptainerOptionError(
            f"environment variable {key!r} must not contain control chars"
        )
    return value


def _exception_stream(exc: BaseException, name: str) -> str:
    value = getattr(exc, name, "")
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _exception_error(
    exc: BaseException,
    *,
    argv: Sequence[str],
    redacted_argv: Sequence[str],
) -> str:
    if exc.__class__.__name__ == "TimeoutExpired":
        timeout = getattr(exc, "timeout", None)
        message = (
            "command timed out"
            if timeout is None
            else f"command timed out after {timeout} seconds"
        )
    else:
        message = str(exc) or type(exc).__name__
    for raw, redacted in zip(argv, redacted_argv, strict=True):
        if raw != redacted:
            message = message.replace(raw, redacted)
    return f"{type(exc).__module__}.{type(exc).__name__}: {message}"


def _has_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


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
    "ApptainerExecCommand",
    "ApptainerExecOptions",
    "ApptainerExecRunner",
    "FakeApptainerExecRunner",
    "SubprocessApptainerExecRunner",
    "build_apptainer_exec_command",
    "build_apptainer_version_command",
]
