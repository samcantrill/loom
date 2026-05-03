"""Provenance capture helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Mapping, cast

from importlib.metadata import PackageNotFoundError, version as package_version

from loom.artifacts import ArtifactRef
from loom.serialization import PlainData, ensure_plain_data
from loom.timestamps import utc_timestamp

from .errors import ProvenanceCaptureError
from .git import capture_git_provenance
from .models import (
    ArtifactLineage,
    CommandProvenance,
    CodeProvenance,
    DependencyProvenance,
    EnvironmentProvenance,
    ProvenanceCaptureOptions,
    RunProvenance,
)


def capture_code_provenance(
    project_root: str | None = None,
    package_name: str | None = None,
    include_git_remote: bool = False,
    strict: bool = False,
) -> CodeProvenance:
    """Capture lightweight code provenance."""

    git = None
    if project_root is not None:
        git = capture_git_provenance(project_root, include_remote=include_git_remote, strict=strict)

    version_value: str | None = None
    if package_name is not None:
        try:
            version_value = package_version(package_name)
        except PackageNotFoundError as exc:
            if strict:
                raise ProvenanceCaptureError(f"Package {package_name!r} is not installed") from exc
            version_value = None

    return CodeProvenance(
        git=git,
        package_name=package_name,
        package_version=version_value,
        source_paths=(project_root,) if project_root else (),
    )


def capture_environment_provenance(
    env_keys: tuple[str, ...] = (),
    *,
    include_user: bool = False,
) -> EnvironmentProvenance:
    """Capture selected environment metadata."""

    from .environment import capture_environment_provenance as impl

    return impl(env_keys=env_keys, include_user=include_user)


def capture_dependency_provenance(
    packages: tuple[str, ...] = ("loom",),
    *,
    strict: bool = False,
) -> "DependencyProvenance":
    """Capture versions of explicitly requested packages."""

    from .packages import capture_dependency_provenance as impl

    return impl(packages=packages, strict=strict)


def capture_command_provenance(
    argv: tuple[str, ...] | None = None,
    cwd: str | None = None,
    launcher: str | None = None,
) -> CommandProvenance:
    if argv is None:
        argv = tuple(sys.argv)
    if cwd is None:
        cwd = str(Path.cwd())
    command_string = " ".join(argv)
    return CommandProvenance(argv=tuple(argv), cwd=cwd, launcher=launcher, command_string=command_string)


def capture_artifact_lineage(
    ref: ArtifactRef,
    *,
    metadata: Mapping[str, object] | None = None,
) -> ArtifactLineage:
    lineage_metadata = _plain_mapping(ref.metadata, "ref.metadata")
    if metadata:
        lineage_metadata = {
            **lineage_metadata,
            **_plain_mapping(metadata, "metadata"),
        }
    return ArtifactLineage(
        artifact_id=ref.artifact_id,
        artifact_type=ref.artifact_type,
        uri=ref.uri,
        artifact_schema_version=ref.schema_version,
        producer_stage=ref.producer_stage,
        producer_fingerprint=ref.fingerprint,
        checksum=ref.checksum,
        metadata=lineage_metadata,
    )


def capture_run_provenance(
    run_id: str,
    *,
    run_dir: str | None = None,
    options: ProvenanceCaptureOptions | None = None,
    command: CommandProvenance | None = None,
    config: Mapping[str, object] | None = None,
    metadata: Mapping[str, object] | None = None,
) -> RunProvenance:
    capture_options = options or ProvenanceCaptureOptions()

    provenance_command: CommandProvenance | None = command
    if command is None and capture_options.capture_command:
        provenance_command = capture_command_provenance()

    code = None
    environment = None
    dependencies = None
    if capture_options.capture_git and capture_options.git_root is not None:
        code = capture_code_provenance(
            project_root=capture_options.git_root,
            include_git_remote=capture_options.include_git_remote,
            strict=capture_options.strict,
        )
    if capture_options.capture_environment:
        from .environment import capture_environment_provenance as impl

        environment = impl(env_keys=capture_options.env_keys, include_user=capture_options.include_user)
    if capture_options.capture_dependencies:
        from .packages import capture_dependency_provenance as impl

        dependencies = impl(packages=capture_options.packages, strict=capture_options.strict)

    return RunProvenance(
        run_id=run_id,
        created_at=utc_timestamp(),
        run_dir=run_dir,
        command=provenance_command,
        code=code,
        environment=environment,
        dependencies=dependencies,
        config=_plain_mapping(config or {}, "config"),
        metadata=_plain_mapping(metadata or {}, "metadata"),
    )


def _plain_mapping(value: Mapping[str, object], path: str) -> dict[str, PlainData]:
    return cast(dict[str, PlainData], ensure_plain_data(dict(value), path=path))
