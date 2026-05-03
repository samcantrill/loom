"""Unit tests for artifact bindings."""

import pytest

from loom.pipeline import PipelineSpec
from loom.pipeline.errors import InputBindingError
from loom.pipeline.graph import ArtifactReference, ResolvedInputBinding
from loom.pipeline.graph import bind_stage_inputs, parse_artifact_reference, resolve_input_bindings


def test_parse_artifact_reference_strict_shape() -> None:
    reference = parse_artifact_reference("build.output")
    assert reference == ArtifactReference(stage_id="build", output_name="output")

    with pytest.raises(InputBindingError, match="exactly one"):
        parse_artifact_reference("build.output.extra")
    with pytest.raises(InputBindingError, match="non-empty"):
        parse_artifact_reference("")
    with pytest.raises(InputBindingError, match="stage.output"):
        parse_artifact_reference("build")


def _pipeline() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "build",
                    "_target_": "tests.support.config_samples:concat",
                    "outputs": {"result": {"artifact_type": "text"}},
                },
                {
                    "name": "report",
                    "_target_": "tests.support.config_samples:concat",
                    "depends_on": ["build"],
                    "inputs": {"first": "build.result"},
                    "outputs": {"report": {"artifact_type": "text"}},
                },
                {
                    "name": "final",
                    "_target_": "tests.support.config_samples:concat",
                    "inputs": {"r": "report.report"},
                    "outputs": {"value": {"artifact_type": "text"}},
                },
            ]
        }
    )


def test_bind_stage_inputs_maps_and_validates_semantics() -> None:
    spec = _pipeline()
    bindings = bind_stage_inputs("report", spec)
    assert set(bindings) == {"first"}
    binding = bindings["first"]
    assert isinstance(binding, ResolvedInputBinding)
    assert binding.source_stage_id == "build"
    assert binding.source_output_name == "result"


def test_bind_stage_inputs_unknown_source_output() -> None:
    spec = PipelineSpec.from_config(
        {
            "stages": [
                {"name": "build", "_target_": "tests.support.config_samples:concat", "outputs": {"result": {"artifact_type": "text"}}},
                {
                    "name": "report",
                    "_target_": "tests.support.config_samples:concat",
                    "inputs": {"first": "build.missing"},
                    "outputs": {"value": {"artifact_type": "text"}},
                },
            ]
        }
    )
    with pytest.raises(InputBindingError, match="unknown output"):
        bind_stage_inputs("report", spec)


def test_resolve_input_bindings_includes_empty_stage_inputs() -> None:
    spec = _pipeline()
    all_bindings = resolve_input_bindings(spec)
    assert set(all_bindings) == {"build", "report", "final"}
    assert all_bindings["build"] == {}
