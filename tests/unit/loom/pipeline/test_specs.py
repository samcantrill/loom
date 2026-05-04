"""Unit tests for pipeline spec parsing and validation."""

from typing import Any, cast

import pytest

from loom.pipeline import (
    OutputSpec,
    PipelineSpec,
    StageFactorySpec,
    StageSpec,
    parse_pipeline_config,
)
from loom.pipeline.errors import PipelineSpecError
from loom.serialization import PlainData


def _base_stage(stage_name: str, *, outputs: dict[str, Any] | None = None, depends_on: list[str] | tuple[str, ...] = (), inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": stage_name,
        "factory": {
            "_target_": "tests.support.config_samples:concat",
        },
        "outputs": outputs
        or {
            "result": {"artifact_type": "text", "codec_key": "text.v1"},
        },
        "depends_on": list(depends_on),
        "inputs": inputs or {},
        "config": {"alpha": 1},
        "resources": {},
    }


def _sample_pipeline() -> dict[str, Any]:
    return {
        "name": "example",
        "description": "example pipeline",
        "stages": [
            _base_stage("build", outputs={"artifact": {"artifact_type": "text"}}),
        _base_stage(
            "report",
            depends_on=["build"],
            inputs={"artifact": "build.artifact"},
            outputs={"report": {"artifact_type": "json", "metadata": {"format": "summary"}}},
        ),
        ],
    }


def test_parse_pipeline_config_and_parse_pipeline_api_are_consistent() -> None:
    config = _sample_pipeline()
    from_fn = PipelineSpec.from_config(config)
    fn = parse_pipeline_config(config)
    assert from_fn == fn


def test_pipeline_requires_stages() -> None:
    with pytest.raises(PipelineSpecError, match="\\.pipeline\\.stages must be a non-empty sequence"):
        PipelineSpec.from_config({"stages": []})


def test_pipeline_rejects_unknown_field() -> None:
    pipeline = _sample_pipeline()
    pipeline["defaults"] = "forbidden"
    with pytest.raises(PipelineSpecError, match="deferred"):
        PipelineSpec.from_config(pipeline)


def test_stage_required_keys() -> None:
    stage = _base_stage("build")
    del stage["name"]
    with pytest.raises(PipelineSpecError, match="name"):
        PipelineSpec.from_config({"stages": [stage]})


def test_stage_rejects_top_level_target_legacy_shape() -> None:
    stage = {
        "name": "build",
        "_target_": "tests.support.config_samples:concat",
        "outputs": {"result": {"artifact_type": "text", "codec_key": "text.v1"}},
        "config": {"alpha": 1},
    }
    with pytest.raises(PipelineSpecError, match="legacy top-level _target_"):
        PipelineSpec.from_config({"stages": [stage]})


def test_stage_factory_is_required() -> None:
    stage = _base_stage("build")
    del stage["factory"]
    with pytest.raises(PipelineSpecError, match="factory is required"):
        PipelineSpec.from_config({"stages": [stage]})


def test_stage_rejects_deferred_fields() -> None:
    stage = _base_stage("build")
    stage["runtime"] = "local"
    with pytest.raises(PipelineSpecError, match="deferred"):
        PipelineSpec.from_config({"stages": [stage]})


def test_stage_factory_rejects_unknown_factory_fields() -> None:
    stage = _base_stage("build")
    stage["factory"]["_args_"] = {"skip": True}
    with pytest.raises(PipelineSpecError, match="deferred"):
        PipelineSpec.from_config({"stages": [stage]})


def test_stage_inputs_need_stage_dot_output() -> None:
    stage = _base_stage("build")
    stage["inputs"] = {"bad": "build"}
    with pytest.raises(PipelineSpecError, match="stage\\.output"):
        PipelineSpec.from_config({"stages": [stage]})


def test_stage_output_requires_artifact_type() -> None:
    stage = _base_stage("build")
    stage["outputs"] = {"artifact": {"codec_key": "text.v1"}}
    with pytest.raises(PipelineSpecError, match="artifact_type"):
        PipelineSpec.from_config({"stages": [stage]})


def test_output_rejects_deferred_fields() -> None:
    stage = _base_stage("build")
    stage["outputs"] = {"artifact": {"artifact_type": "text", "required": True}}
    with pytest.raises(PipelineSpecError, match="deferred"):
        PipelineSpec.from_config({"stages": [stage]})


def test_output_rejects_unknown_fields() -> None:
    stage = _base_stage("build")
    stage["outputs"] = {"artifact": {"artifact_type": "text", "unsupported": 1}}
    with pytest.raises(PipelineSpecError, match="unknown"):
        PipelineSpec.from_config({"stages": [stage]})


def test_parse_schema_version_validation() -> None:
    pipeline = _sample_pipeline()
    pipeline["schema_version"] = "1"
    with pytest.raises(PipelineSpecError, match="schema_version"):
        PipelineSpec.from_config(pipeline)


def test_duplicate_stage_names_fail() -> None:
    stage = _base_stage("build")
    with pytest.raises(PipelineSpecError, match="duplicate"):
        PipelineSpec.from_config({"stages": [stage, stage]})


def test_identifier_rules_reject_dots_and_slashes() -> None:
    invalid = _sample_pipeline()
    invalid["stages"][0]["name"] = "bad.stage"
    with pytest.raises(PipelineSpecError, match="cannot contain"):
        PipelineSpec.from_config(invalid)

    invalid["stages"][0]["name"] = "bad/stage"
    with pytest.raises(PipelineSpecError, match="path"):
        PipelineSpec.from_config(invalid)


def test_get_stage_raises_for_unknown() -> None:
    spec = PipelineSpec.from_config(_sample_pipeline())
    with pytest.raises(PipelineSpecError, match="has no stage"):
        spec.get_stage("unknown")


def test_stage_spec_parsing_preserves_declared_dependencies_and_bindings() -> None:
    stage = StageSpec.from_config(
        {
            "name": "report",
            "factory": {"_target_": "tests.support.config_samples:concat", "init": {"prefix": "p"}},
            "depends_on": ["build"],
            "inputs": {"x": "build.result"},
            "outputs": {"report": {"artifact_type": "text", "codec_key": "text.v1", "schema_version": 2}},
            "config": {"nested": {"enabled": True}},
            "fingerprint": {"label": "v1"},
            "resources": {"slot": "cpu"},
        },
        path="$.stages[0]",
    )

    assert stage.stage_config["nested"] == {"enabled": True}
    assert stage.name == "report"
    assert stage.factory.init == {"prefix": "p"}
    assert stage.dependencies == ("build",)
    assert stage.inputs["x"] == "build.result"
    assert stage.outputs["report"].artifact_type == "text"
    assert stage.outputs["report"].schema_version == 2
    assert stage.fingerprint_fields == {"label": "v1"}
    assert cast(dict[str, Any], stage.stage_config)["nested"]["enabled"] is True


def test_direct_spec_constructors_normalize_sequences_and_plain_mappings() -> None:
    output_metadata = cast(dict[str, PlainData], {"labels": ("raw",)})
    output = OutputSpec(artifact_type="text", metadata=output_metadata)
    output_metadata["changed"] = True

    assert output.metadata == {"labels": ("raw",)}

    stage_config: dict[str, PlainData] = {"threshold": 1}
    outputs = {"result": output}
    stage = StageSpec(
        name="report",
        factory=StageFactorySpec("tests.support.config_samples:concat"),
        outputs=outputs,
        stage_config=stage_config,
        dependencies=cast(tuple[str, ...], ["build"]),
        inputs={"artifact": "build.result"},
        resources={"slots": 1},
    )
    outputs["extra"] = OutputSpec(artifact_type="json")
    stage_config["changed"] = True

    assert stage.outputs == {"result": output}
    assert stage.stage_config == {"threshold": 1}
    assert stage.dependencies == ("build",)
    assert stage.inputs == {"artifact": "build.result"}
    assert stage.resources == {"slots": 1}

    pipeline_metadata = cast(dict[str, PlainData], {"tags": ("static",)})
    stages = [stage]
    pipeline = PipelineSpec(
        stages=cast(tuple[StageSpec, ...], stages),
        metadata=pipeline_metadata,
    )
    stages.append(
        StageSpec(
            name="extra",
            factory=StageFactorySpec("tests.support.config_samples:concat"),
            outputs={"extra": OutputSpec(artifact_type="json")},
        ),
    )
    pipeline_metadata["changed"] = True

    assert pipeline.stages == (stage,)
    assert pipeline.metadata == {"tags": ("static",)}


def test_stage_and_pipeline_spec_normalization_freezes_constructor_inputs() -> None:
    output = OutputSpec(artifact_type="text", metadata={"labels": ["raw", "final"]})
    outputs_input: dict[str, OutputSpec] = {"result": output}
    factory_init: dict[str, Any] = {"labels": ["constructor"]}
    stage_config: dict[str, Any] = {"retry": {"max": 3}}
    inputs = {"artifact": "build.result"}
    resources: dict[str, Any] = {"slots": ["cpu"]}

    stage = StageSpec(
        name="report",
        factory=StageFactorySpec("tests.support.config_samples:concat", factory_init),
        fingerprint_fields={"mode": "test"},
        outputs=outputs_input,
        stage_config=stage_config,
        dependencies=("build",),
        inputs=inputs,
        resources=resources,
    )
    pipeline_metadata = {"owner": {"team": "analysis", "labels": ["primary"]}}
    pipeline = PipelineSpec(stages=(stage,), metadata=pipeline_metadata)

    outputs_input["extra"] = OutputSpec(artifact_type="json")
    factory_init["labels"].append("mutated")
    stage_config["retry"]["max"] = 4
    stage_config["retry"]["active"] = True
    inputs["artifact"] = "other.result"
    resources["slots"].append("gpu")
    pipeline_metadata["owner"]["labels"].append("secondary")

    assert stage.outputs == {"result": output}
    assert stage.factory.init == {"labels": ("constructor",)}
    assert stage.stage_config == {"retry": {"max": 3}}
    assert stage.inputs == {"artifact": "build.result"}
    assert stage.resources == {"slots": ("cpu",)}
    pipeline_owner = cast(dict[str, Any], pipeline.metadata["owner"])
    assert pipeline_owner["team"] == "analysis"
    assert pipeline_owner["labels"] == ("primary",)

    with pytest.raises(TypeError):
        cast(Any, stage.outputs)["result"] = OutputSpec(artifact_type="json")
    with pytest.raises(TypeError):
        cast(Any, stage.factory.init)["labels"][0] = "mutated"
    with pytest.raises(TypeError):
        cast(Any, stage.stage_config)["retry"]["active"] = False
    with pytest.raises(TypeError):
        cast(Any, stage.inputs)["artifact"] = "new.result"
    with pytest.raises(TypeError):
        cast(Any, stage.resources)["slots"] = ("gpu",)
    with pytest.raises(TypeError):
        cast(Any, pipeline.metadata)["owner"]["labels"][0] = "mutated"


def test_stage_factory_defaults_and_parses_when_init_is_omitted() -> None:
    stage = StageSpec.from_config(
        {
            "name": "report",
            "factory": {"_target_": "tests.support.config_samples:concat"},
            "outputs": {"result": {"artifact_type": "text", "codec_key": "text.v1"}},
        },
        path="$.stages[0]",
    )
    assert stage.factory.init == {}
