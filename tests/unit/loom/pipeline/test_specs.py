"""Unit tests for pipeline spec parsing and validation."""

from typing import Any, cast

import pytest

from loom.pipeline import PipelineSpec, parse_pipeline_config, StageSpec
from loom.pipeline.errors import PipelineSpecError


def _base_stage(stage_name: str, *, outputs: dict[str, Any] | None = None, depends_on: list[str] | tuple[str, ...] = (), inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": stage_name,
        "_target_": "tests.support.config_samples:concat",
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


def test_stage_rejects_deferred_fields() -> None:
    stage = _base_stage("build")
    stage["runtime"] = "local"
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
            "_target_": "tests.support.config_samples:concat",
            "depends_on": ["build"],
            "inputs": {"x": "build.result"},
            "outputs": {"report": {"artifact_type": "text", "codec_key": "text.v1", "schema_version": 2}},
            "config": {"nested": {"enabled": True}},
            "resources": {"slot": "cpu"},
        },
        path="$.stages[0]",
    )

    assert stage.name == "report"
    assert stage.dependencies == ("build",)
    assert stage.inputs["x"] == "build.result"
    assert stage.outputs["report"].artifact_type == "text"
    assert stage.outputs["report"].schema_version == 2
    assert cast(dict[str, Any], stage.stage_config)["nested"]["enabled"] is True
