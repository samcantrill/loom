"""Docker image build helpers over shared container build requests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import cast

from loom.pipeline.executors.containers import (
    REDACTED_VALUE,
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
    container_build_output_identity,
    evaluate_container_build_policy,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError

from .commands import (
    DockerCommandResult,
    DockerCommandRunner,
    DockerOptions,
    DockerRunCommand,
    FakeDockerCommandRunner,
    SubprocessDockerCommandRunner,
)


_BUILD_OPTIONS_FIELDS = frozenset(
    {"command", "buildx", "builder", "pull", "no_cache", "platform", "progress"}
)
_ARG_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class DockerBuildOptions:
    """Docker-owned options for local image build commands."""

    command: str = "docker"
    buildx: bool = False
    builder: str | None = None
    pull: bool = False
    no_cache: bool = False
    platform: str | None = None
    progress: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "command",
            _text(self.command, path="DockerBuildOptions.command"),
        )
        for field_name in ("buildx", "pull", "no_cache"):
            if not isinstance(getattr(self, field_name), bool):
                raise ContainerOptionError(
                    f"DockerBuildOptions.{field_name} must be a bool"
                )
        for field_name in ("builder", "platform", "progress"):
            object.__setattr__(
                self,
                field_name,
                _optional_text(
                    getattr(self, field_name),
                    path=f"DockerBuildOptions.{field_name}",
                ),
            )
        if self.builder is not None and not self.buildx:
            raise ContainerOptionError(
                "DockerBuildOptions.builder requires DockerBuildOptions.buildx"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "command": self.command,
            "buildx": self.buildx,
            "builder": self.builder,
            "pull": self.pull,
            "no_cache": self.no_cache,
            "platform": self.platform,
            "progress": self.progress,
        }

    @classmethod
    def from_dict(cls, data: object | None) -> "DockerBuildOptions":
        if data is None:
            return cls()
        mapping = _plain_mapping(data, path="DockerBuildOptions")
        _reject_unknown(mapping, _BUILD_OPTIONS_FIELDS, path="DockerBuildOptions")
        return cls(
            command=_text(
                mapping.get("command", "docker"),
                path="DockerBuildOptions.command",
            ),
            buildx=_bool(
                mapping.get("buildx", False),
                path="DockerBuildOptions.buildx",
            ),
            builder=_optional_text(
                mapping.get("builder"),
                path="DockerBuildOptions.builder",
            ),
            pull=_bool(mapping.get("pull", False), path="DockerBuildOptions.pull"),
            no_cache=_bool(
                mapping.get("no_cache", False),
                path="DockerBuildOptions.no_cache",
            ),
            platform=_optional_text(
                mapping.get("platform"),
                path="DockerBuildOptions.platform",
            ),
            progress=_optional_text(
                mapping.get("progress"),
                path="DockerBuildOptions.progress",
            ),
        )


class DockerContainerBuilder:
    """Foreground Docker image builder for shared build requests."""

    def __init__(
        self,
        *,
        runner: DockerCommandRunner | None = None,
        options: DockerBuildOptions | Mapping[str, object] | None = None,
        timeout_seconds: int | float | None = None,
    ) -> None:
        self.runner = runner or SubprocessDockerCommandRunner()
        self.options = _docker_build_options(options)
        self.timeout_seconds = _optional_positive_number(
            timeout_seconds,
            path="DockerContainerBuilder.timeout_seconds",
        )

    def build(self, request: ContainerBuildRequest) -> ContainerBuildResult:
        parsed = _request(request)
        target = _docker_target(cast(ContainerBuildTarget, parsed.target))
        output = cast(ContainerBuildOutputRef, target.output)
        output_id = container_build_output_identity(output)
        try:
            exists_result = self.runner.image_digest(
                output_id,
                DockerOptions(command=self.options.command),
                timeout_seconds=self.timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - command availability becomes evidence.
            return _failure_result(
                request=parsed,
                code="container_build.docker_inspect_failed",
                message="docker image inspection failed before build",
                details={"error": _exception_name(exc)},
            )
        output_exists = exists_result.ok and bool(exists_result.stdout.strip())
        decision = evaluate_container_build_policy(
            target,
            output_exists=output_exists,
            source_stale=False if output_exists else None,
        )
        evidence = _docker_evidence(
            decision=decision.to_dict(),
            operation="inspect" if decision.action is ContainerBuildAction.REUSE else "build",
            inspect_returncode=exists_result.returncode,
        )
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
        command = build_docker_build_command(parsed, docker_build_options=self.options)
        projection = _docker_projection(command)
        try:
            result = self.runner.run(command, timeout_seconds=self.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - command availability becomes evidence.
            return _failure_result(
                request=parsed,
                code="container_build.docker_launch_failed",
                message="docker build command could not be launched",
                details={"error": _exception_name(exc)},
                command=projection,
                evidence=_docker_evidence(
                    decision=decision.to_dict(),
                    operation="build",
                ),
            )
        if not result.ok:
            return _failure_result(
                request=parsed,
                code="container_build.docker_failed",
                message="docker build command failed",
                details=_result_details(result),
                command=projection,
                evidence=_docker_evidence(
                    decision=decision.to_dict(),
                    operation="build",
                    build_returncode=result.returncode,
                ),
            )
        return ContainerBuildResult(
            target_name=target.name,
            status=ContainerBuildStatus.BUILT,
            output=output,
            build_key=parsed.build_key,
            command=projection,
            evidence=_docker_evidence(
                decision=decision.to_dict(),
                operation="build",
                build_returncode=result.returncode,
            ),
        )


def build_docker_build_command(
    request: ContainerBuildRequest | Mapping[str, object],
    *,
    docker_build_options: DockerBuildOptions | Mapping[str, object] | None = None,
) -> DockerRunCommand:
    """Return a deterministic Docker image build argv for one build request."""

    parsed = _request(request)
    target = _docker_target(cast(ContainerBuildTarget, parsed.target))
    source = cast(ContainerBuildSource, target.source)
    output = cast(ContainerBuildOutputRef, target.output)
    options = _docker_build_options(docker_build_options)
    argv: list[str] = [options.command]
    redacted: list[str] = [options.command]
    if options.buildx:
        _append(argv, redacted, "buildx")
    _append(argv, redacted, "build")
    if options.builder is not None:
        _append_option(argv, redacted, "--builder", options.builder)
    if options.pull:
        _append(argv, redacted, "--pull")
    if options.no_cache:
        _append(argv, redacted, "--no-cache")
    _append_option(argv, redacted, "--platform", options.platform)
    _append_option(argv, redacted, "--progress", options.progress)
    _append_option(argv, redacted, "--tag", cast(str, output.reference))
    if source.recipe_path is not None:
        _append_option(argv, redacted, "--file", source.recipe_path)
    for name, value in sorted(target.build_args.items()):
        _append(argv, redacted, "--build-arg")
        argv.append(f"{_arg_name(name)}={_build_arg_value(value, name=name)}")
        redacted.append(f"{_arg_name(name)}={REDACTED_VALUE}")
    _append(argv, redacted, cast(str, source.context_path))
    return DockerRunCommand(
        argv=argv,
        redacted_argv=redacted,
        metadata={
            "builder": "docker",
            "operation": "build",
            "target": target.to_redacted_metadata(),
            "docker_build_options": options.to_dict(),
            "build_arg_names": list(target.build_args),
        },
    )


def _docker_projection(command: DockerRunCommand) -> ContainerBuildCommandProjection:
    return ContainerBuildCommandProjection(
        argv=cast(Sequence[str], command.redacted_argv),
        build_arg_names=cast(Sequence[str], command.metadata.get("build_arg_names", ())),
        metadata={
            "builder": "docker",
            "operation": "build",
            "command": cast(Sequence[str], command.argv)[0],
        },
    )


def _docker_evidence(
    *,
    decision: Mapping[str, PlainData],
    operation: str,
    inspect_returncode: int | None = None,
    build_returncode: int | None = None,
) -> ContainerBuildEvidence:
    metadata: dict[str, PlainData] = {
        "operation": operation,
        "decision": dict(decision),
    }
    if inspect_returncode is not None:
        metadata["inspect_returncode"] = inspect_returncode
    if build_returncode is not None:
        metadata["build_returncode"] = build_returncode
    return ContainerBuildEvidence(builder="docker", metadata=metadata)


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


def _result_details(result: DockerCommandResult) -> dict[str, PlainData]:
    details: dict[str, PlainData] = {
        "returncode": result.returncode,
        "timed_out": result.timed_out,
    }
    if result.error:
        details["error"] = result.error
    return details


def _request(request: ContainerBuildRequest | Mapping[str, object]) -> ContainerBuildRequest:
    return (
        request
        if isinstance(request, ContainerBuildRequest)
        else ContainerBuildRequest.from_dict(request)
    )


def _docker_target(target: ContainerBuildTarget) -> ContainerBuildTarget:
    if cast(ContainerBuildRuntime, target.runtime) is not ContainerBuildRuntime.DOCKER:
        raise ContainerOptionError("Docker builder requires a docker build target")
    if cast(ContainerBuildOutputRef, target.output).kind is not ContainerBuildOutputKind.DOCKER_IMAGE:
        raise ContainerOptionError("Docker builder requires a docker_image output")
    if cast(ContainerBuildSource, target.source).kind is not ContainerBuildSourceKind.DOCKER_CONTEXT:
        raise ContainerOptionError("Docker builder requires a docker_context source")
    return target


def _docker_build_options(
    value: DockerBuildOptions | Mapping[str, object] | None,
) -> DockerBuildOptions:
    return value if isinstance(value, DockerBuildOptions) else DockerBuildOptions.from_dict(value)


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


def _arg_name(value: object) -> str:
    text = _text(value, path="build_args key")
    if not _ARG_NAME_RE.match(text):
        raise ContainerOptionError(f"build arg name is not portable: {text!r}")
    return text


def _build_arg_value(value: PlainData, *, name: str) -> str:
    if value is None or isinstance(value, bool | int | float | str):
        return "" if value is None else str(value)
    raise ContainerOptionError(f"Docker build arg {name!r} must be scalar plain data")


def _plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    try:
        normalized = freeze_plain_data(value, path=path)
    except PlainDataError as exc:
        raise ContainerOptionError(f"{path} must be plain data: {exc}") from exc
    thawed = thaw_plain_data(normalized, path=path)
    if not isinstance(thawed, Mapping):
        raise ContainerOptionError(f"{path} must be a mapping")
    return MappingProxyType(dict(sorted(cast(Mapping[str, PlainData], thawed).items())))


def _text(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContainerOptionError(f"{path} must be a non-empty string")
    return value


def _optional_text(value: object | None, *, path: str) -> str | None:
    if value is None:
        return None
    return _text(value, path=path)


def _bool(value: object, *, path: str) -> bool:
    if not isinstance(value, bool):
        raise ContainerOptionError(f"{path} must be a bool")
    return value


def _optional_positive_number(value: object, *, path: str) -> int | float | None:
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        raise ContainerOptionError(f"{path} must be a positive number")
    return value


def _exception_name(exc: BaseException) -> str:
    return exc.__class__.__name__


def _reject_unknown(
    mapping: Mapping[str, object],
    allowed: frozenset[str],
    *,
    path: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise ContainerOptionError(f"{path} contains unknown field(s): {fields}")


__all__ = [
    "DockerBuildOptions",
    "DockerContainerBuilder",
    "FakeDockerCommandRunner",
    "SubprocessDockerCommandRunner",
    "build_docker_build_command",
]
