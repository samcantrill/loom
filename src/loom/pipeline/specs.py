"""Pipeline specification parsing and validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from loom.ids import ArtifactType, CodecKey, StageID
from loom.serialization import PlainData, ensure_plain_data, freeze_plain_data
from loom.serialization.errors import PlainDataError

from .errors import PipelineSpecError


def _require_mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PipelineSpecError(f"{path} must be a mapping")
    return cast(Mapping[str, object], value)


def _reject_unknown_fields(
    data: Mapping[str, object],
    *,
    allowed: set[str],
    deferred: set[str],
    path: str,
) -> None:
    deferred_fields = set(data) & deferred
    if deferred_fields:
        fields = ", ".join(sorted(deferred_fields))
        raise PipelineSpecError(f"{path} uses deferred field(s) not supported in v0: {fields}")

    unknown = set(data) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise PipelineSpecError(f"{path} contains unknown field(s): {fields}")


def _require_non_empty_string(value: object, *, path: str) -> str:
    if not isinstance(value, str):
        raise PipelineSpecError(f"{path} must be a non-empty string")
    if not value:
        raise PipelineSpecError(f"{path} must be a non-empty string")
    return value


def _optional_string(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, path=path)


def _optional_schema_version(value: object, *, path: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PipelineSpecError(f"{path} must be a positive integer or null")
    if value <= 0:
        raise PipelineSpecError(f"{path} must be a positive integer")
    return value


def _validate_identifier(value: str, *, kind: str, path: str) -> str:
    if not value:
        raise PipelineSpecError(f"{path} must be a non-empty {kind}")
    if value in {".", ".."}:
        raise PipelineSpecError(f"{path} cannot be '.' or '..'")
    if "." in value:
        raise PipelineSpecError(f"{path} cannot contain '.'")
    if "/" in value or "\\" in value:
        raise PipelineSpecError(f"{path} cannot contain path separators")
    if any(ch <= " " for ch in value):
        raise PipelineSpecError(f"{path} cannot contain control or whitespace characters")
    return value


def _plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=path)
    except PlainDataError as exc:
        raise PipelineSpecError(f"{path} must be plain-data-compatible mapping: {exc}") from exc
    if not isinstance(normalized, Mapping):
        raise PipelineSpecError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _parse_dependencies(
    value: object,
    *,
    stage_name: StageID,
    path: str,
) -> tuple[StageID, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise PipelineSpecError(f"{path} must be a sequence of stage identifiers")
    deps: list[StageID] = []
    for index, item in enumerate(value):
        identifier = _require_non_empty_string(item, path=f"{path}[{index}]")
        deps.append(_validate_identifier(identifier, kind="stage identifier", path=f"{path}[{index}]"))
    for identifier in deps:
        if identifier == stage_name:
            raise PipelineSpecError(f"{path} may not depend on the same stage '{stage_name}'")
    return tuple(deps)


def _parse_inputs(
    value: object,
    *,
    stage_name: StageID,
    path: str,
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PipelineSpecError(f"{path} must be a mapping")
    for key in value:
        _validate_identifier(_require_non_empty_string(key, path=f"{path} key"), kind="input name", path=f"{path}.{key}")
    inputs: dict[str, str] = {}
    for input_name, reference in value.items():
        if not isinstance(reference, str) or not reference:
            raise PipelineSpecError(f"{path}.{input_name} must be a non-empty stage.output reference")
        if reference.count(".") != 1:
            raise PipelineSpecError(f"{path}.{input_name} must be a strict stage.output reference")
        source_stage, source_output = reference.split(".", 1)
        if not source_stage or not source_output:
            raise PipelineSpecError(f"{path}.{input_name} must be a strict stage.output reference")
        _validate_identifier(
            _require_non_empty_string(source_stage, path=f"{path}.{input_name}.stage"),
            kind="stage identifier",
            path=f"{path}.{input_name}.stage",
        )
        _validate_identifier(
            _require_non_empty_string(source_output, path=f"{path}.{input_name}.output"),
            kind="output name",
            path=f"{path}.{input_name}.output",
        )
        if source_stage == stage_name:
            raise PipelineSpecError(f"{path}.{input_name} may not reference its own stage")
        inputs[input_name] = reference
    return inputs


def _parse_outputs(
    value: object,
    *,
    stage_name: StageID,
    path: str,
) -> dict[str, "OutputSpec"]:
    if value is None:
        raise PipelineSpecError(f"{path} requires at least one output")
    if not isinstance(value, Mapping):
        raise PipelineSpecError(f"{path} must be a mapping")
    output_specs: dict[str, OutputSpec] = {}
    for output_name, output_data in value.items():
        _validate_identifier(
            _require_non_empty_string(output_name, path=f"{path} key"),
            kind="output name",
            path=f"{path}['{output_name}']",
        )
        output_specs[output_name] = OutputSpec.from_config(
            output_data,
            path=f"{path}['{output_name}']",
        )
    if not output_specs:
        raise PipelineSpecError(f"{path} requires at least one output")
    _ = stage_name  # preserve parameter for compatibility with call-site helpers
    return output_specs


@dataclass(frozen=True, slots=True)
class StageFactorySpec:
    target_path: str
    init: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_path",
            _require_non_empty_string(self.target_path, path="StageFactorySpec.target_path"),
        )
        object.__setattr__(
            self,
            "init",
            _plain_mapping(self.init, path="StageFactorySpec.init"),
        )

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        path: str,
    ) -> "StageFactorySpec":
        mapping = _require_mapping(config, path=path)
        _reject_unknown_fields(
            mapping,
            allowed={"_target_", "init"},
            deferred={"_args_", "_partial_", "_inject_"},
            path=path,
        )
        target_path = _require_non_empty_string(
            mapping.get("_target_"),
            path=f"{path}._target_",
        )
        init = _plain_mapping(mapping.get("init", {}), path=f"{path}.init")
        return cls(target_path=target_path, init=init)


@dataclass(frozen=True, slots=True)
class OutputSpec:
    artifact_type: ArtifactType
    codec_key: CodecKey | None = None
    schema_version: int | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifact_type",
            _require_non_empty_string(self.artifact_type, path="OutputSpec.artifact_type"),
        )
        object.__setattr__(
            self,
            "codec_key",
            _optional_string(self.codec_key, path="OutputSpec.codec_key"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _optional_schema_version(self.schema_version, path="OutputSpec.schema_version"),
        )
        object.__setattr__(
            self,
            "metadata",
            freeze_plain_data(self.metadata, path="OutputSpec.metadata"),
        )

    @classmethod
    def from_config(cls, config: object, *, path: str = "$.output") -> "OutputSpec":
        mapping = _require_mapping(config, path=path)
        _reject_unknown_fields(
            mapping,
            allowed={"artifact_type", "codec_key", "schema_version", "metadata"},
            deferred={"path", "required"},
            path=path,
        )

        artifact_type = _require_non_empty_string(mapping.get("artifact_type"), path=f"{path}.artifact_type")
        codec_key = _optional_string(mapping.get("codec_key"), path=f"{path}.codec_key")
        schema_version = _optional_schema_version(mapping.get("schema_version"), path=f"{path}.schema_version")
        metadata = _plain_mapping(mapping.get("metadata", {}), path=f"{path}.metadata")
        return cls(
            artifact_type=artifact_type,
            codec_key=codec_key,
            schema_version=schema_version,
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class StageSpec:
    name: StageID
    factory: StageFactorySpec
    outputs: Mapping[str, OutputSpec]
    stage_config: Mapping[str, PlainData] = field(default_factory=dict)
    dependencies: tuple[StageID, ...] = field(default_factory=tuple)
    inputs: Mapping[str, str] = field(default_factory=dict)
    resources: Mapping[str, PlainData] = field(default_factory=dict)
    fingerprint_fields: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = _validate_identifier(
            _require_non_empty_string(self.name, path="StageSpec.name"),
            kind="stage name",
            path="StageSpec.name",
        )
        object.__setattr__(self, "name", name)

        outputs: dict[str, OutputSpec] = {}
        if not isinstance(self.outputs, Mapping):
            raise PipelineSpecError("StageSpec.outputs must be a mapping")
        for output_name, output_spec in self.outputs.items():
            normalized_name = _validate_identifier(
                _require_non_empty_string(output_name, path="StageSpec.outputs key"),
                kind="output name",
                path=f"StageSpec.outputs['{output_name}']",
            )
            if not isinstance(output_spec, OutputSpec):
                raise PipelineSpecError(f"StageSpec.outputs['{output_name}'] must be an OutputSpec")
            outputs[normalized_name] = output_spec
        if not outputs:
            raise PipelineSpecError("StageSpec.outputs requires at least one output")
        object.__setattr__(self, "outputs", MappingProxyType(outputs))

        object.__setattr__(
            self,
            "stage_config",
            freeze_plain_data(self.stage_config, path="StageSpec.stage_config"),
        )
        object.__setattr__(
            self,
            "dependencies",
            _parse_dependencies(self.dependencies, stage_name=name, path="StageSpec.dependencies"),
        )
        object.__setattr__(
            self,
            "inputs",
            freeze_plain_data(_parse_inputs(self.inputs, stage_name=name, path="StageSpec.inputs"), path="StageSpec.inputs"),
        )
        object.__setattr__(
            self,
            "resources",
            freeze_plain_data(_plain_mapping(self.resources, path="StageSpec.resources"), path="StageSpec.resources"),
        )
        object.__setattr__(
            self,
            "fingerprint_fields",
            freeze_plain_data(
                _plain_mapping(self.fingerprint_fields, path="StageSpec.fingerprint_fields"),
                path="StageSpec.fingerprint_fields",
            ),
        )

    @property
    def target_path(self) -> str:
        return self.factory.target_path

    @classmethod
    def from_config(cls, config: object, *, path: str = "$.stage") -> "StageSpec":
        mapping = _require_mapping(config, path=path)
        if "_target_" in mapping:
            raise PipelineSpecError(
                f"{path} uses legacy top-level _target_; use factory._target_ and factory.init"
            )
        _reject_unknown_fields(
            mapping,
            allowed={"name", "factory", "config", "depends_on", "inputs", "outputs", "resources", "fingerprint"},
            deferred={"runtime", "retry", "when", "metadata"},
            path=path,
        )
        if "factory" not in mapping:
            raise PipelineSpecError(f"{path}.factory is required")

        name = _validate_identifier(
            _require_non_empty_string(mapping.get("name"), path=f"{path}.name"),
            kind="stage name",
            path=f"{path}.name",
        )
        factory = StageFactorySpec.from_config(mapping["factory"], path=f"{path}.factory")
        stage_config = _plain_mapping(mapping.get("config", {}), path=f"{path}.config")
        dependencies = _parse_dependencies(
            mapping.get("depends_on"),
            stage_name=name,
            path=f"{path}.depends_on",
        )
        inputs = _parse_inputs(mapping.get("inputs"), stage_name=name, path=f"{path}.inputs")
        outputs = _parse_outputs(mapping.get("outputs"), stage_name=name, path=f"{path}.outputs")
        resources = _plain_mapping(mapping.get("resources", {}), path=f"{path}.resources")
        fingerprint_fields = _plain_mapping(mapping.get("fingerprint", {}), path=f"{path}.fingerprint")
        return cls(
            name=name,
            factory=factory,
            outputs=outputs,
            stage_config=stage_config,
            dependencies=dependencies,
            inputs=inputs,
            resources=resources,
            fingerprint_fields=fingerprint_fields,
        )


@dataclass(frozen=True, slots=True)
class PipelineSpec:
    stages: tuple[StageSpec, ...]
    name: str | None = None
    description: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stages, Sequence) or isinstance(self.stages, (bytes, str)):
            raise PipelineSpecError("PipelineSpec.stages must be a non-empty sequence")

        stages: list[StageSpec] = []
        stage_names: set[str] = set()
        for index, stage in enumerate(self.stages):
            if not isinstance(stage, StageSpec):
                raise PipelineSpecError(f"PipelineSpec.stages[{index}] must be a StageSpec")
            if stage.name in stage_names:
                raise PipelineSpecError(f"PipelineSpec.stages[{index}] has duplicate stage name '{stage.name}'")
            stage_names.add(stage.name)
            stages.append(stage)

        if not stages:
            raise PipelineSpecError("PipelineSpec.stages must be a non-empty sequence")
        object.__setattr__(self, "stages", tuple(stages))
        object.__setattr__(self, "name", _optional_string(self.name, path="PipelineSpec.name"))
        object.__setattr__(
            self,
            "description",
            _optional_string(self.description, path="PipelineSpec.description"),
        )
        object.__setattr__(
            self,
            "metadata",
            freeze_plain_data(self.metadata, path="PipelineSpec.metadata"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _optional_schema_version(self.schema_version, path="PipelineSpec.schema_version"),
        )

    @classmethod
    def from_config(cls, config: object, *, path: str = "$.pipeline") -> "PipelineSpec":
        mapping = _require_mapping(config, path=path)
        _reject_unknown_fields(
            mapping,
            allowed={"stages", "name", "description", "metadata", "schema_version"},
            deferred={"defaults"},
            path=path,
        )
        name = _optional_string(mapping.get("name"), path=f"{path}.name")
        description = _optional_string(mapping.get("description"), path=f"{path}.description")
        metadata = _plain_mapping(mapping.get("metadata", {}), path=f"{path}.metadata")
        schema_version = _optional_schema_version(mapping.get("schema_version"), path=f"{path}.schema_version")

        stages_raw = mapping.get("stages")
        if stages_raw is None:
            raise PipelineSpecError(f"{path}.stages is required")
        if not isinstance(stages_raw, Sequence) or isinstance(stages_raw, (bytes, str, dict)):
            raise PipelineSpecError(f"{path}.stages must be a non-empty sequence")
        stages: list[StageSpec] = []
        stage_names: set[str] = set()
        for index, item in enumerate(stages_raw):
            stage = StageSpec.from_config(item, path=f"{path}.stages[{index}]")
            if stage.name in stage_names:
                raise PipelineSpecError(f"{path}.stages[{index}] has duplicate stage name '{stage.name}'")
            stage_names.add(stage.name)
            stages.append(stage)

        if not stages:
            raise PipelineSpecError(f"{path}.stages must be a non-empty sequence")
        return cls(
            stages=tuple(stages),
            name=name,
            description=description,
            metadata=metadata,
            schema_version=schema_version,
        )

    @property
    def stage_names(self) -> tuple[StageID, ...]:
        return tuple(stage.name for stage in self.stages)

    def get_stage(self, stage_id: StageID) -> StageSpec:
        for stage in self.stages:
            if stage.name == stage_id:
                return stage
        raise PipelineSpecError(f"pipeline has no stage named '{stage_id}'")


def parse_pipeline_config(config: object) -> PipelineSpec:
    return PipelineSpec.from_config(config)


__all__ = [
    "OutputSpec",
    "StageFactorySpec",
    "StageSpec",
    "PipelineSpec",
    "parse_pipeline_config",
    "_require_mapping",
    "_reject_unknown_fields",
    "_require_non_empty_string",
    "_optional_string",
    "_optional_schema_version",
    "_validate_identifier",
    "_plain_mapping",
    "_parse_dependencies",
    "_parse_inputs",
    "_parse_outputs",
]
