"""Local artifact-store implementation backed by filesystem files."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Mapping, Sequence

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_bytes, validate_digest
from loom.io.codecs import CodecError, CodecRegistry, create_default_codec_registry
from loom.io.uris import (
    UnsupportedURIError,
    get_uri_scheme,
    path_to_file_uri,
    uri_to_path,
)
from loom.serialization import PlainData, ensure_plain_data
from loom.timestamps import utc_timestamp

from ._paths import validate_output_name, validate_stage_name
from .atomic import atomic_write_bytes
from .errors import (
    ArtifactChecksumMismatchError,
    ArtifactChecksumUnsupportedError,
    ArtifactNotFoundError,
    ArtifactStoreError,
    ArtifactTypeMismatchError,
    MissingArtifactCodecError,
    UnsupportedArtifactURIError,
)
from .local_runs import LocalRunStore


class LocalArtifactStore:
    """Filesystem-backed local artifact store."""

    _SUFFIX_BY_CODEC: dict[str, str] = {
        "json.v1": ".json",
        "text.v1": ".txt",
        "bytes.v1": ".bin",
    }

    def __init__(
        self,
        root: str | Path,
        *,
        codec_registry: CodecRegistry | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        if codec_registry is None:
            codec_registry = create_default_codec_registry()
        self._registry = codec_registry

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
    ) -> ArtifactRef:
        validate_stage_name(stage_name, field="stage_name")
        validate_output_name(name, field="name")

        normalized_metadata = self._normalize_metadata(metadata)
        data = self._encode(obj, codec_key=codec_key, metadata=normalized_metadata)
        path = self.local_artifact_path(
            stage_name=stage_name,
            name=name,
            codec_key=codec_key,
        )
        atomic_write_bytes(path, data)
        checksum = hash_bytes(data)

        return ArtifactRef(
            artifact_id=f"{stage_name}/{name}",
            uri=path_to_file_uri(path.resolve()),
            artifact_type=artifact_type,
            codec_key=codec_key,
            schema_version=schema_version,
            checksum=checksum,
            fingerprint=fingerprint,
            producer_stage=stage_name,
            created_at=utc_timestamp(),
            metadata=normalized_metadata,
        )

    def register(
        self,
        uri: str | Path,
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
    ) -> ArtifactRef:
        validate_stage_name(stage_name, field="stage_name")
        validate_output_name(name, field="name")

        normalized_metadata = self._normalize_metadata(metadata)
        if not self._is_supported_uri(uri):
            raise UnsupportedArtifactURIError(
                f"Unsupported URI scheme for artifact registration: {uri!r}"
            )
        try:
            path = uri_to_path(uri)
        except UnsupportedURIError as exc:
            raise UnsupportedArtifactURIError(
                f"Unsupported URI for artifact registration: {uri!r}"
            ) from exc

        if not path.is_absolute():
            path = self.root / path

        path = path.resolve(strict=False)
        if not allow_external:
            stage_dir = self.local_stage_dir(stage_name=stage_name)
            self._ensure_within(stage_dir, path)

        if not path.exists():
            raise ArtifactNotFoundError(
                f"Cannot register missing artifact path: {path}"
            )

        computed_checksum: str | None
        if path.is_dir():
            if checksum is not None:
                raise ArtifactChecksumUnsupportedError(
                    f"Cannot verify checksum for directory artifact {path}; register directory without checksum",
                )
            computed_checksum = None
        elif path.is_file():
            content = path.read_bytes()
            computed_checksum = hash_bytes(content)
            if checksum is not None:
                expected = self._validate_checksum(checksum)
                if expected != computed_checksum:
                    raise ArtifactChecksumMismatchError(
                        f"Checksum mismatch for {path}: expected {expected}, got {computed_checksum}",
                    )
        else:
            raise ArtifactTypeMismatchError(
                f"Unsupported artifact source type at {path}; expected file or directory"
            )

        return ArtifactRef(
            artifact_id=f"{stage_name}/{name}",
            uri=path_to_file_uri(path),
            artifact_type=artifact_type,
            codec_key=codec_key,
            schema_version=schema_version,
            checksum=checksum or computed_checksum,
            fingerprint=fingerprint,
            producer_stage=stage_name,
            created_at=utc_timestamp(),
            metadata=normalized_metadata,
        )

    def load(
        self,
        ref: ArtifactRef,
        *,
        expected_type: str | None = None,
        codec_key: str | None = None,
    ) -> object:
        self.validate(ref, expected_type=expected_type)
        selected_codec = codec_key or ref.codec_key
        if selected_codec is None:
            raise MissingArtifactCodecError(
                f"No codec available for artifact {ref.uri!r}; pass codec_key=... to load()",
            )

        path = self.local_path(ref)
        if not path.is_file():
            raise ArtifactTypeMismatchError(
                f"Cannot load non-file artifact path {path}"
            )
        data = path.read_bytes()
        metadata = self._normalize_metadata(ref.metadata)
        try:
            return self._registry.decode(selected_codec, data, metadata=metadata)
        except Exception as exc:
            if isinstance(exc, CodecError):
                raise ArtifactStoreError(
                    f"Could not decode artifact {ref.uri!r} with codec {selected_codec!r}: {exc}",
                ) from exc
            raise ArtifactStoreError(
                f"Could not decode artifact {ref.uri!r} with codec {selected_codec!r}: {exc}",
            ) from exc

    def exists(self, ref: ArtifactRef) -> bool:
        path = self._require_local_path(ref.uri)
        return path.exists()

    def verify_checksum(self, ref: ArtifactRef) -> bool:
        if ref.checksum is None:
            return False

        path = self.local_path(ref)
        if not path.exists():
            raise ArtifactNotFoundError(f"Artifact file does not exist: {path}")
        if not path.is_file():
            raise ArtifactChecksumUnsupportedError(
                f"Cannot verify checksum for non-regular artifact path {path}"
            )

        current = hash_bytes(path.read_bytes())
        if current != ref.checksum:
            raise ArtifactChecksumMismatchError(
                f"Checksum mismatch for artifact {ref.uri}: expected {ref.checksum}, got {current}",
            )
        return True

    def validate(
        self,
        ref: ArtifactRef,
        *,
        expected_type: str | None = None,
    ) -> None:
        if expected_type is not None and ref.artifact_type != expected_type:
            raise ArtifactTypeMismatchError(
                f"artifact type mismatch for {ref.uri}: expected {expected_type!r}, got {ref.artifact_type!r}",
            )

        path = self.local_path(ref)
        if not path.exists():
            raise ArtifactNotFoundError(f"Artifact file does not exist: {path}")

        if path.is_dir() and ref.checksum is not None:
            raise ArtifactChecksumUnsupportedError(
                f"Cannot checksum-verify directory artifact {path}",
            )

        if not path.is_file() and ref.checksum is not None:
            raise ArtifactTypeMismatchError(
                f"Cannot load checksumed artifact from non-file path {path}"
            )

        if ref.checksum is not None:
            self.verify_checksum(ref)

    def local_stage_dir(self, stage_name: str) -> Path:
        validate_stage_name(stage_name, field="stage_name")
        return self.root / stage_name

    def local_artifact_path(
        self,
        stage_name: str,
        name: str,
        codec_key: str,
    ) -> Path:
        validate_stage_name(stage_name, field="stage_name")
        validate_output_name(name, field="name")
        suffix = self._SUFFIX_BY_CODEC.get(codec_key, "")
        return self.local_stage_dir(stage_name=stage_name) / f"{name}{suffix}"

    def local_path(self, ref: ArtifactRef) -> Path:
        return self._require_local_path(ref.uri)

    def _is_supported_uri(self, uri: str | Path) -> bool:
        scheme = get_uri_scheme(uri)
        if scheme is None:
            return True
        return scheme == "file"

    def _require_local_path(self, uri: str) -> Path:
        if not self._is_supported_uri(uri):
            raise UnsupportedArtifactURIError(
                f"Unsupported artifact URI scheme for local artifact: {uri!r}"
            )
        try:
            path = uri_to_path(uri)
        except UnsupportedURIError as exc:
            raise UnsupportedArtifactURIError(
                f"Unsupported artifact URI scheme for local artifact: {uri!r}"
            ) from exc
        try:
            return path.resolve()
        except RuntimeError as exc:
            raise ArtifactStoreError(
                f"Unable to resolve artifact URI {uri!r}: {exc}"
            ) from exc

    def _ensure_within(self, base: Path, candidate: Path) -> None:
        try:
            candidate.resolve(strict=False).relative_to(base.resolve(strict=False))
        except ValueError as exc:
            raise ArtifactStoreError(
                f"artifact path {candidate} is outside stage artifact root {base}",
            ) from exc

    def _validate_checksum(self, checksum: str) -> str:
        try:
            return validate_digest(checksum)
        except Exception as exc:
            raise ArtifactChecksumMismatchError(
                f"Invalid checksum syntax {checksum!r}: {exc}"
            ) from exc

    def _normalize_metadata(
        self, metadata: Mapping[str, PlainData] | None
    ) -> dict[str, PlainData]:
        normalized = ensure_plain_data(dict(metadata or {}), path="metadata")
        if not isinstance(normalized, dict):
            raise ArtifactStoreError(
                f"artifact metadata must be a mapping, got {type(normalized)!r}"
            )
        return normalized

    def _encode(
        self, obj: object, *, codec_key: str, metadata: Mapping[str, PlainData]
    ) -> bytes:
        try:
            return self._registry.encode(codec_key, obj, metadata=metadata)
        except Exception as exc:
            raise ArtifactStoreError(
                f"Could not encode artifact with codec {codec_key!r}: {exc}",
            ) from exc


class LocalRunArtifactStore:
    """Artifact/materialization-only wrapper for a local run layout."""

    def __init__(
        self,
        root: str | Path = "runs",
        *,
        local_store: LocalRunStore | None = None,
    ) -> None:
        self._local_store = local_store or LocalRunStore(root=root)

    @property
    def root(self) -> Path:
        return self._local_store.root

    def artifact_store_kind(self) -> Literal["run_artifacts"]:
        return "run_artifacts"

    def resolve_run_uri(self, run_uri: str) -> str:
        return self._local_store.resolve_run_uri(run_uri)

    def allocate_run_uri(self) -> str:
        return self._local_store.allocate_run_uri()

    def local_run_dir(self, run_uri: str) -> Path:
        return self._local_store.local_run_dir(run_uri)

    def local_artifact_root(self, run_uri: str) -> Path:
        return self._local_store.local_artifact_root(run_uri)

    def local_config_path(self, run_uri: str, name: str) -> Path:
        return self._local_store.local_config_path(run_uri, name)

    def local_provenance_path(self, run_uri: str, name: str) -> Path:
        return self._local_store.local_provenance_path(run_uri, name)

    def local_generated_artifact_path(self, run_uri: str, relative_path: str) -> Path:
        return self._local_store.local_generated_artifact_path(run_uri, relative_path)

    def read_config_snapshot(self, run_uri: str, name: str) -> str | None:
        return self._local_store.read_config_snapshot(run_uri, name)

    def write_config_snapshot(self, run_uri: str, name: str, content: str) -> None:
        self._local_store.write_config_snapshot(run_uri, name, content)

    def read_composition_manifest(self, run_uri: str) -> dict[str, PlainData] | None:
        return self._local_store.read_composition_manifest(run_uri)

    def write_composition_manifest(
        self, run_uri: str, manifest: Mapping[str, PlainData]
    ) -> None:
        self._local_store.write_composition_manifest(run_uri, manifest)

    def read_recipe_manifest(
        self, run_uri: str
    ) -> tuple[dict[str, PlainData], ...] | None:
        return self._local_store.read_recipe_manifest(run_uri)

    def write_recipe_manifest(
        self, run_uri: str, records: Sequence[Mapping[str, PlainData]]
    ) -> None:
        self._local_store.write_recipe_manifest(run_uri, records)

    def read_runtime_metadata(self, run_uri: str) -> dict[str, PlainData] | None:
        return self._local_store.read_runtime_metadata(run_uri)

    def write_runtime_metadata(
        self, run_uri: str, metadata: Mapping[str, PlainData]
    ) -> None:
        self._local_store.write_runtime_metadata(run_uri, metadata)

    def read_provenance_document(
        self, run_uri: str, name: str
    ) -> dict[str, PlainData] | None:
        return self._local_store.read_provenance_document(run_uri, name)

    def write_provenance_document(
        self, run_uri: str, name: str, document: Mapping[str, PlainData]
    ) -> None:
        self._local_store.write_provenance_document(run_uri, name, document)

    def stage_artifacts(
        self, run_uri: str, stage_name: str
    ) -> "LocalStageArtifactStore":
        return LocalStageArtifactStore(self._local_store, run_uri, stage_name)


class LocalStageArtifactStore:
    """Stage-scoped artifact/materialization wrapper for a local run layout."""

    def __init__(
        self,
        local_store: LocalRunStore,
        run_uri: str,
        stage_name: str,
    ) -> None:
        self._local_store = local_store
        self._run_uri = local_store.resolve_run_uri(run_uri)
        self._stage_name = validate_stage_name(stage_name, field="stage_name")

    @property
    def run_uri(self) -> str:
        return self._run_uri

    @property
    def stage_name(self) -> str:
        return self._stage_name

    def artifact_store_kind(self) -> Literal["stage_artifacts"]:
        return "stage_artifacts"

    def local_stage_dir(self) -> Path:
        return self._local_store.local_stage_dir(self._run_uri, self._stage_name)

    def local_stage_artifact_dir(self) -> Path:
        return self._local_store.local_stage_artifact_dir(
            self._run_uri,
            self._stage_name,
        )

    def local_stage_log_path(self, stream: str) -> Path:
        return self._local_store.local_stage_log_path(
            self._run_uri,
            self._stage_name,
            stream,
        )

    def local_stage_worker_request_path(self) -> Path:
        return self._local_store.local_stage_worker_request_path(
            self._run_uri,
            self._stage_name,
        )

    def local_stage_worker_result_path(self) -> Path:
        return self._local_store.local_stage_worker_result_path(
            self._run_uri,
            self._stage_name,
        )

    def local_stage_workspace_dir(self) -> Path:
        return self._local_store.local_stage_workspace_dir(
            self._run_uri,
            self._stage_name,
        )

    def prepare_stage_workspace(self) -> None:
        self._local_store.prepare_stage_workspace(self._run_uri, self._stage_name)

    def read_stage_log(self, stream: str) -> str | None:
        return self._local_store.read_stage_log(
            self._run_uri,
            self._stage_name,
            stream,
        )

    def write_stage_log(self, stream: str, content: str) -> None:
        self._local_store.write_stage_log(
            self._run_uri,
            self._stage_name,
            stream,
            content,
        )

    def read_stage_worker_request(self, *, attempt: int) -> dict[str, PlainData] | None:
        return self._local_store.read_stage_worker_request(
            self._run_uri,
            self._stage_name,
            attempt=attempt,
        )

    def write_stage_worker_request(
        self, request: Mapping[str, PlainData], *, attempt: int
    ) -> None:
        self._local_store.write_stage_worker_request(
            self._run_uri,
            self._stage_name,
            request,
            attempt=attempt,
        )

    def read_stage_worker_result(self, *, attempt: int) -> dict[str, PlainData] | None:
        return self._local_store.read_stage_worker_result(
            self._run_uri,
            self._stage_name,
            attempt=attempt,
        )

    def write_stage_worker_result(
        self, result: Mapping[str, PlainData], *, attempt: int
    ) -> None:
        self._local_store.write_stage_worker_result(
            self._run_uri,
            self._stage_name,
            result,
            attempt=attempt,
        )

    def read_stage_provenance(self) -> dict[str, PlainData] | None:
        return self._local_store.read_stage_provenance(
            self._run_uri,
            self._stage_name,
        )

    def write_stage_provenance(
        self, provenance: Mapping[str, PlainData], *, attempt: int
    ) -> None:
        self._local_store.write_stage_provenance(
            self._run_uri,
            self._stage_name,
            provenance,
            attempt=attempt,
        )


__all__ = ["LocalArtifactStore", "LocalRunArtifactStore", "LocalStageArtifactStore"]
