"""Docker CLI command records and fakeable runner contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import re
import shutil
from types import MappingProxyType
from typing import Protocol, cast

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.executors.containers import (
    REDACTED_VALUE,
    ContainerEnvironment,
    ContainerImageReference,
    ContainerMount,
    ContainerMountMode,
    ContainerOptions,
    ContainerResourceIntent,
    parse_container_options,
)
from loom.pipeline.resources import ResourceEntry
from loom.pipeline.runtime.capabilities import ResourceCapability, ResourceSupportLevel
from loom.serialization import (
    PlainData,
    freeze_plain_data,
    load_versioned_document,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError, SchemaVersionError
from loom.timestamps import parse_timestamp, utc_timestamp


DOCKER_COMMAND_RESULT_SCHEMA_VERSION = 1
MAX_DOCKER_COMMAND_OUTPUT_CHARS = 4096
TRUNCATED_OUTPUT_SUFFIX = "...[truncated]"

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OPTIONS_FIELDS = frozenset(
    {"command", "remove", "network", "platform", "user", "hostname"}
)
_RUN_COMMAND_FIELDS = frozenset({"argv", "redacted_argv", "metadata"})
_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "command",
        "argv",
        "redacted_argv",
        "returncode",
        "stdout",
        "stderr",
        "started_at",
        "finished_at",
        "timed_out",
        "timeout_seconds",
        "error",
    }
)
_MEMORY_UNITS = {
    "B": "b",
    "KiB": "k",
    "MiB": "m",
    "GiB": "g",
    "TiB": "t",
}


class DockerOptionError(RuntimeResourceError):
    """Raised when Docker command options or results are invalid."""


class DockerCommandUnavailableError(DockerOptionError):
    """Raised when the configured Docker command is unavailable."""


@dataclass(frozen=True, slots=True)
class DockerOptions:
    """Docker-owned adapter options for deterministic command construction."""

    command: str = "docker"
    remove: bool = True
    network: str | None = None
    platform: str | None = None
    user: str | None = None
    hostname: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "command",
            _text(self.command, path="DockerOptions.command"),
        )
        if not isinstance(self.remove, bool):
            raise DockerOptionError("DockerOptions.remove must be a bool")
        for field_name in ("network", "platform", "user", "hostname"):
            object.__setattr__(
                self,
                field_name,
                _optional_text(
                    getattr(self, field_name),
                    path=f"DockerOptions.{field_name}",
                ),
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "command": self.command,
            "remove": self.remove,
            "network": self.network,
            "platform": self.platform,
            "user": self.user,
            "hostname": self.hostname,
        }

    @classmethod
    def from_dict(cls, data: object | None) -> "DockerOptions":
        if data is None:
            return cls()
        mapping = _plain_mapping(data, path="DockerOptions")
        _reject_unknown(mapping, _OPTIONS_FIELDS, path="DockerOptions")
        return cls(
            command=(
                "docker"
                if "command" not in mapping
                else _text(mapping["command"], path="DockerOptions.command")
            ),
            remove=_bool(mapping.get("remove", True), path="DockerOptions.remove"),
            network=_optional_text(
                mapping.get("network"),
                path="DockerOptions.network",
            ),
            platform=_optional_text(
                mapping.get("platform"),
                path="DockerOptions.platform",
            ),
            user=_optional_text(mapping.get("user"), path="DockerOptions.user"),
            hostname=_optional_text(
                mapping.get("hostname"),
                path="DockerOptions.hostname",
            ),
        )


@dataclass(frozen=True, slots=True)
class DockerRunCommand:
    """Shell-free Docker argv plus redacted persistence-facing projection."""

    argv: Sequence[str]
    redacted_argv: Sequence[str] | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        argv = _argv_tuple(self.argv, path="DockerRunCommand.argv")
        redacted_argv = (
            argv
            if self.redacted_argv is None
            else _argv_tuple(
                self.redacted_argv,
                path="DockerRunCommand.redacted_argv",
            )
        )
        if len(redacted_argv) != len(argv):
            raise DockerOptionError(
                "DockerRunCommand.redacted_argv must match argv length"
            )
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "redacted_argv", redacted_argv)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(
                dict(_freeze_mapping(self.metadata, path="DockerRunCommand.metadata"))
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "argv": list(self.argv),
            "redacted_argv": list(cast(tuple[str, ...], self.redacted_argv)),
            "metadata": _thaw_mapping(
                self.metadata,
                path="DockerRunCommand.metadata",
            ),
        }

    @classmethod
    def from_dict(cls, data: object) -> "DockerRunCommand":
        mapping = _plain_mapping(data, path="DockerRunCommand")
        _reject_unknown(mapping, _RUN_COMMAND_FIELDS, path="DockerRunCommand")
        _require_fields(mapping, {"argv"}, path="DockerRunCommand")
        return cls(
            argv=_sequence(mapping["argv"], path="DockerRunCommand.argv"),
            redacted_argv=(
                None
                if mapping.get("redacted_argv") is None
                else _sequence(
                    mapping["redacted_argv"],
                    path="DockerRunCommand.redacted_argv",
                )
            ),
            metadata=_plain_mapping(
                mapping.get("metadata", {}),
                path="DockerRunCommand.metadata",
            ),
        )

    @classmethod
    def from_argv(
        cls,
        argv: Sequence[str],
        *,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> "DockerRunCommand":
        return cls(argv=argv, redacted_argv=argv, metadata=metadata or {})


@dataclass(frozen=True, slots=True)
class DockerCommandResult:
    """Bounded Docker command result safe to include in metadata artifacts."""

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
    schema_version: int = DOCKER_COMMAND_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != DOCKER_COMMAND_RESULT_SCHEMA_VERSION:
            raise DockerOptionError(
                "unsupported DockerCommandResult schema_version "
                f"{self.schema_version!r}"
            )
        object.__setattr__(
            self,
            "command",
            _text(self.command, path="DockerCommandResult.command"),
        )
        argv = _argv_tuple(self.argv, path="DockerCommandResult.argv")
        redacted_argv = _argv_tuple(
            self.redacted_argv,
            path="DockerCommandResult.redacted_argv",
        )
        if len(argv) != len(redacted_argv):
            raise DockerOptionError(
                "DockerCommandResult.redacted_argv must match argv length"
            )
        if not isinstance(self.returncode, int) or isinstance(self.returncode, bool):
            raise DockerOptionError("DockerCommandResult.returncode must be an integer")
        if not isinstance(self.timed_out, bool):
            raise DockerOptionError("DockerCommandResult.timed_out must be a bool")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "redacted_argv", redacted_argv)
        object.__setattr__(
            self,
            "stdout",
            bound_docker_output(self.stdout, field="DockerCommandResult.stdout"),
        )
        object.__setattr__(
            self,
            "stderr",
            bound_docker_output(self.stderr, field="DockerCommandResult.stderr"),
        )
        _validate_optional_timestamp(self.started_at, field="started_at")
        _validate_optional_timestamp(self.finished_at, field="finished_at")
        object.__setattr__(
            self,
            "timeout_seconds",
            _optional_positive_number(
                self.timeout_seconds,
                path="DockerCommandResult.timeout_seconds",
            ),
        )
        if self.error is not None:
            object.__setattr__(
                self,
                "error",
                bound_docker_output(self.error, field="DockerCommandResult.error"),
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

    @classmethod
    def from_dict(cls, data: object) -> "DockerCommandResult":
        try:
            mapping = load_versioned_document(
                data,
                current_version=DOCKER_COMMAND_RESULT_SCHEMA_VERSION,
                required={
                    "command",
                    "argv",
                    "redacted_argv",
                    "returncode",
                    "stdout",
                    "stderr",
                    "timed_out",
                },
                optional={"started_at", "finished_at", "timeout_seconds", "error"},
                path="DockerCommandResult",
            )
        except SchemaVersionError as exc:
            raise DockerOptionError(f"DockerCommandResult.from_dict: {exc}") from exc
        _reject_unknown(mapping, _RESULT_FIELDS, path="DockerCommandResult")
        return cls(
            schema_version=DOCKER_COMMAND_RESULT_SCHEMA_VERSION,
            command=cast(str, mapping["command"]),
            argv=_sequence(mapping["argv"], path="DockerCommandResult.argv"),
            redacted_argv=_sequence(
                mapping["redacted_argv"],
                path="DockerCommandResult.redacted_argv",
            ),
            returncode=_int(mapping["returncode"], path="DockerCommandResult.returncode"),
            stdout=cast(str, mapping["stdout"]),
            stderr=cast(str, mapping["stderr"]),
            started_at=cast(str | None, mapping.get("started_at")),
            finished_at=cast(str | None, mapping.get("finished_at")),
            timed_out=_bool(
                mapping["timed_out"],
                path="DockerCommandResult.timed_out",
            ),
            timeout_seconds=cast(int | float | None, mapping.get("timeout_seconds")),
            error=cast(str | None, mapping.get("error")),
        )


class DockerCommandRunner(Protocol):
    """Protocol for fakeable Docker command execution."""

    def require(self, command: str) -> None:
        """Raise when a Docker CLI command is unavailable."""
        ...

    def run(
        self,
        command: DockerRunCommand,
        *,
        timeout_seconds: int | float | None = None,
    ) -> DockerCommandResult:
        """Run one Docker command."""
        ...

    def version(
        self,
        docker_options: DockerOptions | Mapping[str, object] | None = None,
        *,
        timeout_seconds: int | float | None = None,
    ) -> DockerCommandResult:
        """Return cheap Docker CLI version command evidence."""
        ...

    def image_digest(
        self,
        image: ContainerImageReference | str,
        docker_options: DockerOptions | Mapping[str, object] | None = None,
        *,
        timeout_seconds: int | float | None = None,
    ) -> DockerCommandResult:
        """Return local image digest command evidence without pulling images."""
        ...


class SubprocessDockerCommandRunner:
    """Docker command runner backed by local subprocess calls."""

    def __init__(self, *, clock: object = utc_timestamp) -> None:
        if not callable(clock):
            raise DockerOptionError("SubprocessDockerCommandRunner.clock must be callable")
        self.clock = cast("Clock", clock)

    def require(self, command: str) -> None:
        command_text = _text(command, path="command")
        if shutil.which(command_text) is None:
            raise DockerCommandUnavailableError(
                f"required Docker command is not available on PATH: {command_text}"
            )

    def run(
        self,
        command: DockerRunCommand,
        *,
        timeout_seconds: int | float | None = None,
    ) -> DockerCommandResult:
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
            return command_result_from_exception(
                command=run_command.argv[0],
                argv=run_command.argv,
                redacted_argv=cast(tuple[str, ...], run_command.redacted_argv),
                exc=exc,
                started_at=started_at,
                finished_at=self.clock(),
                timeout_seconds=timeout,
            )
        return DockerCommandResult(
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
        docker_options: DockerOptions | Mapping[str, object] | None = None,
        *,
        timeout_seconds: int | float | None = None,
    ) -> DockerCommandResult:
        return self.run(
            build_docker_version_command(docker_options=docker_options),
            timeout_seconds=timeout_seconds,
        )

    def image_digest(
        self,
        image: ContainerImageReference | str,
        docker_options: DockerOptions | Mapping[str, object] | None = None,
        *,
        timeout_seconds: int | float | None = None,
    ) -> DockerCommandResult:
        return self.run(
            build_docker_image_digest_command(
                image=image,
                docker_options=docker_options,
            ),
            timeout_seconds=timeout_seconds,
        )


class FakeDockerCommandRunner:
    """Deterministic Docker command runner for local tests."""

    def __init__(
        self,
        *,
        scripted_results: Sequence[DockerCommandResult | BaseException] = (),
        unavailable_commands: Sequence[str] = (),
        clock: object = utc_timestamp,
    ) -> None:
        if not callable(clock):
            raise DockerOptionError("FakeDockerCommandRunner.clock must be callable")
        self._scripted = list(scripted_results)
        self._unavailable = frozenset(
            _text(command, path="unavailable_commands[]")
            for command in unavailable_commands
        )
        self.clock = cast("Clock", clock)
        self.calls: list[DockerRunCommand] = []

    def require(self, command: str) -> None:
        command_text = _text(command, path="command")
        if command_text in self._unavailable:
            raise DockerCommandUnavailableError(
                f"required Docker command is not available in fake runner: {command_text}"
            )

    def run(
        self,
        command: DockerRunCommand,
        *,
        timeout_seconds: int | float | None = None,
    ) -> DockerCommandResult:
        run_command = _run_command(command)
        timeout = _optional_positive_number(timeout_seconds, path="timeout_seconds")
        self.require(run_command.argv[0])
        self.calls.append(run_command)
        if self._scripted:
            result = self._scripted.pop(0)
            if isinstance(result, BaseException):
                return command_result_from_exception(
                    command=run_command.argv[0],
                    argv=run_command.argv,
                    redacted_argv=cast(tuple[str, ...], run_command.redacted_argv),
                    exc=result,
                    started_at=self.clock(),
                    finished_at=self.clock(),
                    timeout_seconds=timeout,
                )
            return result
        return DockerCommandResult(
            command=run_command.argv[0],
            argv=run_command.argv,
            redacted_argv=cast(tuple[str, ...], run_command.redacted_argv),
            returncode=0,
            started_at=self.clock(),
            finished_at=self.clock(),
        )

    def version(
        self,
        docker_options: DockerOptions | Mapping[str, object] | None = None,
        *,
        timeout_seconds: int | float | None = None,
    ) -> DockerCommandResult:
        return self.run(
            build_docker_version_command(docker_options=docker_options),
            timeout_seconds=timeout_seconds,
        )

    def image_digest(
        self,
        image: ContainerImageReference | str,
        docker_options: DockerOptions | Mapping[str, object] | None = None,
        *,
        timeout_seconds: int | float | None = None,
    ) -> DockerCommandResult:
        return self.run(
            build_docker_image_digest_command(
                image=image,
                docker_options=docker_options,
            ),
            timeout_seconds=timeout_seconds,
        )


Clock = Callable[[], str]


def build_docker_run_command(
    *,
    container_options: ContainerOptions | Mapping[str, object],
    worker_command: Sequence[str],
    docker_options: DockerOptions | Mapping[str, object] | None = None,
) -> DockerRunCommand:
    """Return deterministic ``docker run`` argv for one prepared worker command."""

    container = _container_options(container_options)
    options = _docker_options(docker_options)
    worker = _argv_tuple(worker_command, path="worker_command")
    argv: list[str] = [options.command, "run"]
    redacted: list[str] = [options.command, "run"]
    if options.remove:
        _append(argv, redacted, "--rm")
    _append_option(argv, redacted, "--network", options.network)
    _append_option(argv, redacted, "--platform", options.platform)
    _append_option(argv, redacted, "--user", options.user)
    _append_option(argv, redacted, "--hostname", options.hostname)
    if container.workdir is not None:
        _append_option(argv, redacted, "--workdir", container.workdir)
    for mount in _sorted_mounts(container):
        _append_option(argv, redacted, "--mount", _mount_argument(mount))
    _append_environment(argv, redacted, cast(ContainerEnvironment, container.environment))
    for flag, value in _resource_flags(cast(ContainerResourceIntent | None, container.resources)):
        _append_option(argv, redacted, flag, value)
    image = cast(ContainerImageReference, container.image).reference
    _append(argv, redacted, image)
    for item in worker:
        _append(argv, redacted, item)
    metadata: dict[str, PlainData] = {
        "executor": "docker",
        "command": options.command,
        "argv": list(redacted),
        "docker_options": options.to_dict(),
        "container": container.to_redacted_metadata(),
        "worker_command": list(worker),
    }
    return DockerRunCommand(argv=argv, redacted_argv=redacted, metadata=metadata)


def build_docker_version_command(
    docker_options: DockerOptions | Mapping[str, object] | None = None,
) -> DockerRunCommand:
    """Return a cheap Docker CLI version command that does not pull images."""

    options = _docker_options(docker_options)
    return DockerRunCommand.from_argv(
        (options.command, "--version"),
        metadata={
            "executor": "docker",
            "operation": "version",
            "command": options.command,
        },
    )


def build_docker_image_digest_command(
    *,
    image: ContainerImageReference | str,
    docker_options: DockerOptions | Mapping[str, object] | None = None,
) -> DockerRunCommand:
    """Return a local image-inspection command without pulling from registries."""

    options = _docker_options(docker_options)
    reference = _image_reference(image).reference
    return DockerRunCommand.from_argv(
        (
            options.command,
            "image",
            "inspect",
            "--format",
            "{{index .RepoDigests 0}}",
            reference,
        ),
        metadata={
            "executor": "docker",
            "operation": "image_digest",
            "command": options.command,
            "image": reference,
            "pull": False,
        },
    )


def bound_docker_output(value: object, *, field: str = "output") -> str:
    """Return artifact-safe bounded Docker output text."""

    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode(errors="replace")
    elif isinstance(value, str):
        text = value
    else:
        raise DockerOptionError(f"{field} must be a string")
    sanitized = "".join(
        ch if ch in {"\n", "\t"} or (ord(ch) >= 32 and ord(ch) != 127) else "?"
        for ch in text
    )
    if len(sanitized) <= MAX_DOCKER_COMMAND_OUTPUT_CHARS:
        return sanitized
    return (
        sanitized[: MAX_DOCKER_COMMAND_OUTPUT_CHARS - len(TRUNCATED_OUTPUT_SUFFIX)]
        + TRUNCATED_OUTPUT_SUFFIX
    )


def command_result_from_exception(
    *,
    command: str,
    argv: Sequence[str],
    exc: BaseException,
    redacted_argv: Sequence[str] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    timeout_seconds: int | float | None = None,
) -> DockerCommandResult:
    """Represent a caught Docker command exception as a bounded result."""

    argv_tuple = _argv_tuple(argv, path="argv")
    redacted = argv_tuple if redacted_argv is None else _argv_tuple(redacted_argv, path="redacted_argv")
    timed_out = _is_timeout_exception(exc)
    stdout = _exception_stream(exc, "stdout")
    stderr = _exception_stream(exc, "stderr")
    return DockerCommandResult(
        command=command,
        argv=argv_tuple,
        redacted_argv=redacted,
        returncode=124 if timed_out else 127,
        stdout=stdout,
        stderr=stderr,
        started_at=started_at,
        finished_at=finished_at or utc_timestamp(),
        timed_out=timed_out,
        timeout_seconds=timeout_seconds,
        error=_exception_error(exc, argv=argv_tuple, redacted_argv=redacted),
    )


def _append(argv: list[str], redacted: list[str], value: str) -> None:
    text = _argv_text(value, path="argv[]")
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


def _append_environment(
    argv: list[str],
    redacted: list[str],
    environment: ContainerEnvironment,
) -> None:
    for name, value in environment.variables.items():
        key = _env_name(name)
        _append(argv, redacted, "--env")
        argv.append(f"{key}={_env_value(value, key=key)}")
        redacted.append(f"{key}={REDACTED_VALUE}")
    for name in environment.required_host_variables:
        _append_option(argv, redacted, "--env", _env_name(name))


def _resource_flags(
    resources: ContainerResourceIntent | None,
) -> tuple[tuple[str, str], ...]:
    if resources is None:
        return ()
    flags: list[tuple[str, str]] = []
    entries = cast(Mapping[str, ResourceEntry], resources.entries)
    capabilities = cast(Mapping[str, ResourceCapability], resources.capabilities)
    for kind, entry in sorted(entries.items()):
        capability = capabilities.get(kind)
        if capability is None:
            raise DockerOptionError(f"Docker resource {kind!r} is missing capability")
        _require_supported_resource(kind, capability)
        if kind == "cpu":
            flags.append(("--cpus", _format_amount(entry.amount)))
        elif kind == "memory":
            flags.append(("--memory", _docker_memory_amount(entry)))
        elif kind == "gpu":
            raise DockerOptionError("Docker GPU resource mapping is unsupported")
        else:
            raise DockerOptionError(f"Docker resource kind {kind!r} is unsupported")
    return tuple(flags)


def _require_supported_resource(kind: str, capability: ResourceCapability) -> None:
    if capability.support_level == ResourceSupportLevel.UNSUPPORTED:
        raise DockerOptionError(f"Docker resource kind {kind!r} is unsupported")


def _docker_memory_amount(entry: ResourceEntry) -> str:
    unit = _MEMORY_UNITS.get(entry.unit or "")
    if unit is None:
        raise DockerOptionError(
            "Docker memory resource unit must be one of: "
            + ", ".join(sorted(_MEMORY_UNITS))
        )
    return _format_amount(entry.amount) + unit


def _format_amount(value: int | float) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DockerOptionError("resource amount must be numeric")
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise DockerOptionError("resource amount must be finite")
        if value.is_integer():
            return str(int(value))
    return str(value)


def _mount_argument(mount: ContainerMount) -> str:
    mode = cast(ContainerMountMode, mount.mode)
    parts = [
        "type=bind",
        f"source={mount.source}",
        f"target={mount.target}",
    ]
    if mode is ContainerMountMode.READ_ONLY:
        parts.append("readonly")
    return ",".join(parts)


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


def _container_options(value: ContainerOptions | Mapping[str, object]) -> ContainerOptions:
    return value if isinstance(value, ContainerOptions) else parse_container_options(value)


def _docker_options(
    value: DockerOptions | Mapping[str, object] | None,
) -> DockerOptions:
    return value if isinstance(value, DockerOptions) else DockerOptions.from_dict(value)


def _run_command(value: DockerRunCommand) -> DockerRunCommand:
    if not isinstance(value, DockerRunCommand):
        raise DockerOptionError("DockerCommandRunner.run requires DockerRunCommand")
    return value


def _image_reference(value: ContainerImageReference | str) -> ContainerImageReference:
    return value if isinstance(value, ContainerImageReference) else ContainerImageReference(value)


def _is_timeout_exception(exc: BaseException) -> bool:
    return type(exc).__name__ == "TimeoutExpired"


def _exception_stream(exc: BaseException, name: str) -> str:
    value = getattr(exc, name, "")
    if value is None:
        return ""
    if isinstance(value, bytes | str):
        return bound_docker_output(value, field=name)
    return bound_docker_output(str(value), field=name)


def _exception_error(
    exc: BaseException,
    *,
    argv: Sequence[str],
    redacted_argv: Sequence[str],
) -> str:
    if _is_timeout_exception(exc):
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


def _env_name(value: object) -> str:
    name = _text(value, path="environment variable name")
    if _ENV_NAME_RE.fullmatch(name) is None:
        raise DockerOptionError(
            "environment variable name must be an uppercase/lowercase ASCII "
            "identifier"
        )
    return name


def _env_value(value: object, *, key: str) -> str:
    text = _string(value, path=f"environment[{key!r}]")
    if _has_control_chars(text):
        raise DockerOptionError(f"environment[{key!r}] must not contain control chars")
    return text


def _argv_tuple(value: Sequence[str], *, path: str) -> tuple[str, ...]:
    items = _sequence(value, path=path)
    argv = tuple(_argv_text(item, path=f"{path}[]") for item in items)
    if not argv:
        raise DockerOptionError(f"{path} must not be empty")
    return argv


def _argv_text(value: object, *, path: str) -> str:
    text = _text(value, path=path)
    if _has_control_chars(text):
        raise DockerOptionError(f"{path} must not contain control chars")
    return text


def _text(value: object, *, path: str) -> str:
    text = _string(value, path=path).strip()
    if not text:
        raise DockerOptionError(f"{path} must be a non-empty string")
    if _has_control_chars(text):
        raise DockerOptionError(f"{path} must not contain control chars")
    return text


def _optional_text(value: object | None, *, path: str) -> str | None:
    if value is None:
        return None
    return _text(value, path=path)


def _string(value: object, *, path: str) -> str:
    if not isinstance(value, str):
        raise DockerOptionError(f"{path} must be a string")
    return value


def _sequence(value: object, *, path: str) -> Sequence[str]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise DockerOptionError(f"{path} must be a sequence")
    return cast(Sequence[str], value)


def _plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    try:
        normalized = freeze_plain_data(value, path=path)
    except PlainDataError as exc:
        raise DockerOptionError(f"{path} must be plain data: {exc}") from exc
    thawed = thaw_plain_data(normalized, path=path)
    if not isinstance(thawed, Mapping):
        raise DockerOptionError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in thawed):
        raise DockerOptionError(f"{path} must be a mapping with string keys")
    return cast(Mapping[str, PlainData], thawed)


def _freeze_mapping(
    value: Mapping[str, PlainData],
    *,
    path: str,
) -> Mapping[str, PlainData]:
    try:
        normalized = freeze_plain_data(value, path=path)
    except PlainDataError as exc:
        raise DockerOptionError(f"{path} must be plain data: {exc}") from exc
    if not isinstance(normalized, Mapping):
        raise DockerOptionError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _thaw_mapping(value: Mapping[str, PlainData], *, path: str) -> dict[str, PlainData]:
    thawed = thaw_plain_data(value, path=path)
    if not isinstance(thawed, Mapping):
        raise DockerOptionError(f"{path} must be a mapping")
    return dict(cast(Mapping[str, PlainData], thawed))


def _bool(value: object, *, path: str) -> bool:
    if not isinstance(value, bool):
        raise DockerOptionError(f"{path} must be a bool")
    return value


def _int(value: object, *, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise DockerOptionError(f"{path} must be an integer")
    return value


def _optional_positive_number(
    value: object | None,
    *,
    path: str,
) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DockerOptionError(f"{path} must be a positive number")
    if isinstance(value, float) and (
        value != value or value in {float("inf"), float("-inf")}
    ):
        raise DockerOptionError(f"{path} must be finite")
    if value <= 0:
        raise DockerOptionError(f"{path} must be positive")
    return value


def _validate_optional_timestamp(value: object, *, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise DockerOptionError(f"{field} must be a string or null")
    try:
        parse_timestamp(value)
    except ValueError as exc:
        raise DockerOptionError(f"{field} must be a valid timestamp: {exc}") from exc


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
        raise DockerOptionError(f"{path} contains unknown field(s): {fields}")


def _require_fields(
    mapping: Mapping[str, object],
    fields: set[str],
    *,
    path: str,
) -> None:
    missing = fields - set(mapping)
    if missing:
        names = ", ".join(sorted(missing))
        raise DockerOptionError(f"{path} missing required field(s): {names}")


__all__ = [
    "DOCKER_COMMAND_RESULT_SCHEMA_VERSION",
    "MAX_DOCKER_COMMAND_OUTPUT_CHARS",
    "DockerCommandResult",
    "DockerCommandRunner",
    "DockerCommandUnavailableError",
    "DockerOptionError",
    "DockerOptions",
    "DockerRunCommand",
    "FakeDockerCommandRunner",
    "SubprocessDockerCommandRunner",
    "build_docker_image_digest_command",
    "build_docker_run_command",
    "build_docker_version_command",
    "bound_docker_output",
    "command_result_from_exception",
]
