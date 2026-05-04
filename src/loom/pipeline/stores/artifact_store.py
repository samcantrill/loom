"""Artifact-store protocol contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

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
