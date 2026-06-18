"""Minimal stage execution context for v0 static execution surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field
from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.ids import RunURI, StageID
from loom.pipeline.errors import PipelineValidationError
from loom.pipeline.specs import OutputSpec
from loom.pipeline.stores._paths import validate_output_name
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.pipeline.stores.run_store import LegacyRunStore
from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError


@dataclass(frozen=True, slots=True)
class StageContext:
    run_uri: RunURI
    stage_name: StageID
    resolved_config: Mapping[str, PlainData]
    stage_config: Mapping[str, PlainData]
    inputs: Mapping[str, ArtifactRef] = field(default_factory=dict)
    provenance: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    run_store: InitVar[LegacyRunStore | None] = None
    artifact_store: InitVar[ArtifactStore | None] = None
    output_specs: InitVar[Mapping[str, OutputSpec] | None] = None
    local_output_dir: InitVar[str | Path | None] = None
    local_workspace_dir: InitVar[str | Path | None] = None

    _run_store: LegacyRunStore | None = field(default=None, init=False, repr=False)
    _artifact_store: ArtifactStore | None = field(default=None, init=False, repr=False)
    _output_specs: dict[str, OutputSpec] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _local_output_dir: Path | None = field(default=None, init=False, repr=False)
    _local_workspace_dir: Path | None = field(default=None, init=False, repr=False)

    def __post_init__(
        self,
        run_store: LegacyRunStore | None,
        artifact_store: ArtifactStore | None,
        output_specs: Mapping[str, OutputSpec] | None,
        local_output_dir: str | Path | None,
        local_workspace_dir: str | Path | None,
    ) -> None:
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise PipelineValidationError("run_uri must be a non-empty string")
        if not isinstance(self.stage_name, str) or not self.stage_name:
            raise PipelineValidationError("stage_name must be a non-empty string")
        try:
            object.__setattr__(
                self,
                "resolved_config",
                ensure_plain_data(dict(self.resolved_config), path="resolved_config"),
            )
            object.__setattr__(
                self,
                "stage_config",
                ensure_plain_data(dict(self.stage_config), path="stage_config"),
            )
            object.__setattr__(
                self,
                "provenance",
                ensure_plain_data(dict(self.provenance), path="provenance"),
            )
            object.__setattr__(
                self,
                "metadata",
                ensure_plain_data(dict(self.metadata), path="metadata"),
            )
        except PlainDataError as exc:
            raise PipelineValidationError(
                f"StageContext mappings must be plain-data-compatible: {exc}"
            ) from exc
        if not isinstance(self.inputs, Mapping):
            raise PipelineValidationError("inputs must be a mapping")
        normalized_inputs: dict[str, ArtifactRef] = {}
        for name, ref in self.inputs.items():
            if not isinstance(name, str):
                raise PipelineValidationError("inputs keys must be non-empty strings")
            if not isinstance(ref, ArtifactRef):
                raise PipelineValidationError("inputs values must be ArtifactRef")
            normalized_inputs[name] = ref
        object.__setattr__(self, "inputs", normalized_inputs)

        if run_store is not None and not isinstance(run_store, LegacyRunStore):
            raise PipelineValidationError(
                "run_store must satisfy LegacyRunStore when supplied"
            )
        if artifact_store is not None and not isinstance(artifact_store, ArtifactStore):
            raise PipelineValidationError(
                "artifact_store must satisfy ArtifactStore when supplied"
            )
        object.__setattr__(self, "_run_store", run_store)
        object.__setattr__(self, "_artifact_store", artifact_store)

        specs = {} if output_specs is None else dict(output_specs)
        if not isinstance(specs, Mapping):
            raise PipelineValidationError("output_specs must be a mapping")
        normalized_specs: dict[str, OutputSpec] = {}
        for name, spec in specs.items():
            if not isinstance(name, str):
                raise PipelineValidationError(
                    "output_specs must map output names to OutputSpec"
                )
            validate_output_name(name, field="name")
            if not isinstance(spec, OutputSpec):
                raise PipelineValidationError(
                    "output_specs must map output names to OutputSpec"
                )
            normalized_specs[name] = spec
        object.__setattr__(self, "_output_specs", normalized_specs)

        if local_output_dir is not None:
            object.__setattr__(self, "_local_output_dir", Path(local_output_dir))
        if local_workspace_dir is not None:
            object.__setattr__(
                self,
                "_local_workspace_dir",
                Path(local_workspace_dir),
            )

    def input_artifact(self, name: str) -> ArtifactRef:
        if not isinstance(name, str) or not name:
            raise PipelineValidationError("name must be a non-empty string")
        if name not in self.inputs:
            raise PipelineValidationError(
                f"input {name!r} is not available for stage {self.stage_name!r}"
            )
        return self.inputs[name]

    def stop_early(
        self,
        message: str,
        *,
        detail: Mapping[str, PlainData] | None = None,
    ) -> None:
        """Request controlled cancellation of the current run."""

        from loom.pipeline.early_stopping import stop_early

        stop_early(message, detail=detail)

    def load_input(
        self,
        name: str,
        *,
        expected_type: str | None = None,
        codec_key: str | None = None,
    ) -> object:
        ref = self.input_artifact(name)
        return self.load_artifact(ref, expected_type=expected_type, codec_key=codec_key)

    def load_artifact(
        self,
        ref: ArtifactRef,
        *,
        expected_type: str | None = None,
        codec_key: str | None = None,
    ) -> object:
        artifact_store = self._artifact_store
        if artifact_store is None:
            raise PipelineValidationError(
                "StageContext.load_artifact requires artifact_store"
            )
        return artifact_store.load(
            ref,
            expected_type=expected_type,
            codec_key=codec_key,
        )

    def local_output_path(self, name: str, *, suffix: str = "") -> Path:
        self._validate_declared_output(name)
        output_name = validate_output_name(name, field="name")
        if not isinstance(suffix, str):
            raise PipelineValidationError("suffix must be a string")
        if any(part in suffix for part in ("/", "\\", "\x00")) or ".." in suffix:
            raise PipelineValidationError(
                "suffix must not contain path separators, NUL, or parent traversal"
            )
        output_dir = self._local_output_dir
        if output_dir is None:
            raise PipelineValidationError(
                "StageContext.local_output_path requires local_output_dir"
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{output_name}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def local_workspace_path(self, *parts: str) -> Path:
        workspace_dir = self._local_workspace_dir
        if workspace_dir is None:
            raise PipelineValidationError(
                "StageContext.local_workspace_path requires local_workspace_dir"
            )
        for part in parts:
            if not isinstance(part, str):
                raise PipelineValidationError(
                    "local_workspace_path path parts must be strings"
                )
            if not part:
                raise PipelineValidationError(
                    "local_workspace_path path parts must be non-empty"
                )
            if (
                part in {".", ".."}
                or ".." in part
                or any(ch in part for ch in ("/", "\\", "\x00"))
            ):
                raise PipelineValidationError(
                    "local_workspace_path path parts must not contain separators, NUL, parent traversal, '.', or '..'"
                )
        workspace_dir.mkdir(parents=True, exist_ok=True)
        if not parts:
            return workspace_dir
        target = workspace_dir.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def save_artifact(
        self,
        name: str,
        obj: object,
        *,
        artifact_type: str,
        codec_key: str,
        schema_version: int = 1,
        metadata: Mapping[str, PlainData] | None = None,
        fingerprint: str | None = None,
    ) -> ArtifactRef:
        self._validate_declared_output_contract(
            name,
            artifact_type=artifact_type,
            codec_key=codec_key,
            schema_version=schema_version,
        )
        artifact_store = self._artifact_store
        if artifact_store is None:
            raise PipelineValidationError(
                "StageContext.save_artifact requires artifact_store"
            )
        return artifact_store.save(
            obj,
            stage_name=self.stage_name,
            name=name,
            artifact_type=artifact_type,
            codec_key=codec_key,
            schema_version=schema_version,
            metadata=metadata,
            fingerprint=fingerprint,
        )

    def register_artifact(
        self,
        name: str,
        uri: str,
        *,
        artifact_type: str,
        codec_key: str | None = None,
        schema_version: int = 1,
        metadata: Mapping[str, PlainData] | None = None,
        fingerprint: str | None = None,
        checksum: str | None = None,
        allow_external: bool = False,
    ) -> ArtifactRef:
        self._validate_declared_output_contract(
            name,
            artifact_type=artifact_type,
            codec_key=codec_key,
            schema_version=schema_version,
        )
        artifact_store = self._artifact_store
        if artifact_store is None:
            raise PipelineValidationError(
                "StageContext.register_artifact requires artifact_store"
            )
        return artifact_store.register(
            uri,
            stage_name=self.stage_name,
            name=name,
            artifact_type=artifact_type,
            codec_key=codec_key,
            schema_version=schema_version,
            metadata=metadata,
            fingerprint=fingerprint,
            checksum=checksum,
            allow_external=allow_external,
        )

    def register_local_artifact(
        self,
        name: str,
        path: str | Path,
        *,
        artifact_type: str,
        codec_key: str | None = None,
        schema_version: int = 1,
        metadata: Mapping[str, PlainData] | None = None,
        fingerprint: str | None = None,
        checksum: str | None = None,
        allow_external: bool = False,
    ) -> ArtifactRef:
        uri = path if isinstance(path, str) else str(path)
        return self.register_artifact(
            name,
            uri=uri,
            artifact_type=artifact_type,
            codec_key=codec_key,
            schema_version=schema_version,
            metadata=metadata,
            fingerprint=fingerprint,
            checksum=checksum,
            allow_external=allow_external,
        )

    def _validate_declared_output(self, name: str) -> OutputSpec | None:
        validate_output_name(name, field="name")
        if not self._output_specs:
            return None
        if name not in self._output_specs:
            raise PipelineValidationError(
                f"output {name!r} is not declared for stage {self.stage_name!r}"
            )
        return self._output_specs[name]

    def _validate_declared_output_contract(
        self,
        name: str,
        *,
        artifact_type: str,
        codec_key: str | None,
        schema_version: int,
    ) -> None:
        spec = self._validate_declared_output(name)
        if spec is None:
            return
        if artifact_type != spec.artifact_type:
            raise PipelineValidationError(
                f"output {name!r} artifact_type must be {spec.artifact_type!r}, got {artifact_type!r}"
            )
        if spec.codec_key is not None and codec_key != spec.codec_key:
            raise PipelineValidationError(
                f"output {name!r} codec_key must be {spec.codec_key!r}"
            )
        if spec.schema_version is not None and schema_version != spec.schema_version:
            raise PipelineValidationError(
                f"output {name!r} schema_version must be {spec.schema_version}"
            )


__all__ = ["StageContext"]
