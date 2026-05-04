"""Minimal stage execution context for v0 static execution surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.ids import RunID, StageID
from loom.pipeline.errors import PipelineValidationError
from loom.pipeline.specs import OutputSpec
from loom.pipeline.stores._paths import validate_output_name
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.pipeline.stores.run_store import RunStore
from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError


@dataclass(frozen=True, slots=True)
class StageContext:
    run_id: RunID
    stage_name: StageID
    run_dir: Path
    stage_dir: Path
    resolved_config: Mapping[str, PlainData]
    stage_config: Mapping[str, PlainData]
    provenance: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    run_store: RunStore | None = None
    artifact_store: ArtifactStore | None = None
    output_specs: Mapping[str, OutputSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise PipelineValidationError("run_id must be a non-empty string")
        if not isinstance(self.stage_name, str) or not self.stage_name:
            raise PipelineValidationError("stage_name must be a non-empty string")
        object.__setattr__(self, "run_dir", Path(self.run_dir))
        object.__setattr__(self, "stage_dir", Path(self.stage_dir))
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
        if self.run_store is not None and not isinstance(self.run_store, RunStore):
            raise PipelineValidationError(
                "run_store must satisfy RunStore when supplied"
            )
        if self.artifact_store is not None and not isinstance(
            self.artifact_store, ArtifactStore
        ):
            raise PipelineValidationError(
                "artifact_store must satisfy ArtifactStore when supplied"
            )
        if not isinstance(self.output_specs, Mapping):
            raise PipelineValidationError("output_specs must be a mapping")
        output_specs: dict[str, OutputSpec] = {}
        for name, spec in self.output_specs.items():
            if not isinstance(name, str) or not isinstance(spec, OutputSpec):
                raise PipelineValidationError(
                    "output_specs must map output names to OutputSpec"
                )
            output_specs[name] = spec
        object.__setattr__(self, "output_specs", output_specs)

    def output_path(self, name: str, *, suffix: str = "") -> Path:
        self._validate_declared_output(name)
        output_name = validate_output_name(name, field="name")
        if not isinstance(suffix, str):
            raise PipelineValidationError("suffix must be a string")
        if any(part in suffix for part in ("/", "\\", "\x00")) or ".." in suffix:
            raise PipelineValidationError(
                "suffix must not contain path separators, NUL, or parent traversal"
            )
        if self.run_store is None:
            raise PipelineValidationError("StageContext.output_path requires run_store")
        path = (
            self.run_store.local_stage_artifact_dir(self.run_id, self.stage_name)
            / f"{output_name}{suffix}"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

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
        if self.artifact_store is None:
            raise PipelineValidationError(
                "StageContext.save_artifact requires artifact_store"
            )
        return self.artifact_store.save(
            obj,
            run_id=self.run_id,
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
        self._validate_declared_output_contract(
            name,
            artifact_type=artifact_type,
            codec_key=codec_key,
            schema_version=schema_version,
        )
        if self.artifact_store is None:
            raise PipelineValidationError(
                "StageContext.register_artifact requires artifact_store"
            )
        return self.artifact_store.register(
            path,
            run_id=self.run_id,
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

    def _validate_declared_output(self, name: str) -> OutputSpec | None:
        validate_output_name(name, field="name")
        if not self.output_specs:
            return None
        if name not in self.output_specs:
            raise PipelineValidationError(
                f"output {name!r} is not declared for stage {self.stage_name!r}"
            )
        return self.output_specs[name]
