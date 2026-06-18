"""Artifact-store protocol contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from loom.artifacts import ArtifactRef
from loom.serialization import PlainData


@runtime_checkable
class ArtifactStore(Protocol):
    def save(
        self,
        obj: object,
        *,
        stage_name: str,
        name: str,
        artifact_type: str,
        codec_key: str,
        schema_version: int = 1,
        metadata: Mapping[str, PlainData] | None = None,
        fingerprint: str | None = None,
    ) -> ArtifactRef: ...

    def register(
        self,
        uri: str,
        *,
        stage_name: str,
        name: str,
        artifact_type: str,
        codec_key: str | None = None,
        schema_version: int = 1,
        metadata: Mapping[str, PlainData] | None = None,
        fingerprint: str | None = None,
        checksum: str | None = None,
        allow_external: bool = False,
    ) -> ArtifactRef: ...

    def load(
        self,
        ref: ArtifactRef,
        *,
        expected_type: str | None = None,
        codec_key: str | None = None,
    ) -> object: ...

    def exists(self, ref: ArtifactRef) -> bool: ...

    def verify_checksum(self, ref: ArtifactRef) -> bool: ...

    def validate(
        self,
        ref: ArtifactRef,
        *,
        expected_type: str | None = None,
    ) -> None: ...


@runtime_checkable
class RunArtifactStore(Protocol):
    """Run-scoped artifact and materialization surface.

    This protocol intentionally excludes lifecycle facts such as statuses,
    attempts, leases, submitted operations, commits, snapshots, and recovery.
    """

    def artifact_store_kind(self) -> Literal["run_artifacts"]: ...

    def resolve_run_uri(self, run_uri: str) -> str: ...

    def allocate_run_uri(self) -> str: ...

    def local_run_dir(self, run_uri: str) -> Path: ...

    def local_artifact_root(self, run_uri: str) -> Path: ...

    def local_config_path(self, run_uri: str, name: str) -> Path: ...

    def local_provenance_path(self, run_uri: str, name: str) -> Path: ...

    def local_generated_artifact_path(
        self, run_uri: str, relative_path: str
    ) -> Path: ...

    def read_config_snapshot(self, run_uri: str, name: str) -> str | None: ...

    def write_config_snapshot(self, run_uri: str, name: str, content: str) -> None: ...

    def read_composition_manifest(
        self, run_uri: str
    ) -> dict[str, PlainData] | None: ...

    def write_composition_manifest(
        self, run_uri: str, manifest: Mapping[str, PlainData]
    ) -> None: ...

    def read_recipe_manifest(
        self, run_uri: str
    ) -> tuple[dict[str, PlainData], ...] | None: ...

    def write_recipe_manifest(
        self, run_uri: str, records: Sequence[Mapping[str, PlainData]]
    ) -> None: ...

    def read_runtime_metadata(self, run_uri: str) -> dict[str, PlainData] | None: ...

    def write_runtime_metadata(
        self, run_uri: str, metadata: Mapping[str, PlainData]
    ) -> None: ...

    def read_provenance_document(
        self, run_uri: str, name: str
    ) -> dict[str, PlainData] | None: ...

    def write_provenance_document(
        self, run_uri: str, name: str, document: Mapping[str, PlainData]
    ) -> None: ...

    def stage_artifacts(
        self, run_uri: str, stage_name: str
    ) -> "StageArtifactStore": ...


@runtime_checkable
class StageArtifactStore(Protocol):
    """Stage-scoped artifact and materialization surface."""

    @property
    def run_uri(self) -> str: ...

    @property
    def stage_name(self) -> str: ...

    def artifact_store_kind(self) -> Literal["stage_artifacts"]: ...

    def local_stage_dir(self) -> Path: ...

    def local_stage_artifact_dir(self) -> Path: ...

    def local_stage_log_path(self, stream: str) -> Path: ...

    def local_stage_worker_request_path(self) -> Path: ...

    def local_stage_worker_result_path(self) -> Path: ...

    def local_stage_workspace_dir(self) -> Path: ...

    def prepare_stage_workspace(self) -> None: ...

    def read_stage_log(self, stream: str) -> str | None: ...

    def write_stage_log(self, stream: str, content: str) -> None: ...

    def read_stage_worker_request(
        self, *, attempt: int
    ) -> dict[str, PlainData] | None: ...

    def write_stage_worker_request(
        self, request: Mapping[str, PlainData], *, attempt: int
    ) -> None: ...

    def read_stage_worker_result(
        self, *, attempt: int
    ) -> dict[str, PlainData] | None: ...

    def write_stage_worker_result(
        self, result: Mapping[str, PlainData], *, attempt: int
    ) -> None: ...

    def read_stage_provenance(self) -> dict[str, PlainData] | None: ...

    def write_stage_provenance(
        self, provenance: Mapping[str, PlainData], *, attempt: int
    ) -> None: ...


__all__ = ["ArtifactStore", "RunArtifactStore", "StageArtifactStore"]
