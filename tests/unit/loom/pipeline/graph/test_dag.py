"""Unit tests for DAG construction."""

import pytest

from loom.pipeline import PipelineSpec
from loom.pipeline.errors import (
    PipelineCycleError,
    PipelineGraphError,
    PipelineSpecError,
)
from loom.pipeline.graph import (
    StageEdgeReason,
    StageEdge,
    StageGraph,
    StageNode,
    build_stage_graph,
)
from loom.pipeline.graph.dag import topological_sort


def _linear_spec() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "a",
                    "factory": {"_target_": "tests.support.config_samples:concat"},
                    "outputs": {"value": {"artifact_type": "text"}},
                },
                {
                    "name": "b",
                    "factory": {"_target_": "tests.support.config_samples:concat"},
                    "depends_on": ["a"],
                    "outputs": {"value": {"artifact_type": "text"}},
                },
                {
                    "name": "c",
                    "factory": {"_target_": "tests.support.config_samples:concat"},
                    "inputs": {"in": "b.value"},
                    "outputs": {"value": {"artifact_type": "text"}},
                },
            ]
        }
    )


def test_build_stage_graph_adds_data_and_control_edges() -> None:
    spec = _linear_spec()
    graph = build_stage_graph(spec)
    assert any(
        edge == StageEdge("a", "b", StageEdgeReason.CONTROL) for edge in graph.edges
    )
    assert any(
        edge
        == StageEdge(
            "b", "c", StageEdgeReason.DATA, input_name="in", output_name="value"
        )
        for edge in graph.edges
    )
    assert topological_sort(graph) == ["a", "b", "c"]


def test_stage_graph_nodes_are_copied_and_immutable() -> None:
    nodes = {"a": StageNode("a", 0)}
    graph = StageGraph(nodes=nodes, edges=frozenset())

    nodes["b"] = StageNode("b", 1)
    assert set(graph.nodes) == {"a"}
    with pytest.raises(TypeError):
        graph.nodes["b"] = StageNode("b", 1)  # type: ignore[index]


def test_build_stage_graph_unknown_dependency_rejected() -> None:
    spec = PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "a",
                    "factory": {"_target_": "tests.support.config_samples:concat"},
                    "depends_on": ["missing"],
                    "outputs": {"value": {"artifact_type": "text"}},
                },
            ]
        }
    )
    with pytest.raises(PipelineGraphError, match="unknown stage"):
        build_stage_graph(spec)


def test_build_stage_graph_self_dependency_rejected() -> None:
    with pytest.raises(PipelineSpecError, match="same stage"):
        PipelineSpec.from_config(
            {
                "stages": [
                    {
                        "name": "a",
                        "factory": {"_target_": "tests.support.config_samples:concat"},
                        "depends_on": ["a"],
                        "outputs": {"value": {"artifact_type": "text"}},
                    },
                ]
            }
        )


def test_build_stage_graph_detects_cycles() -> None:
    spec = PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "a",
                    "factory": {"_target_": "tests.support.config_samples:concat"},
                    "depends_on": ["b"],
                    "outputs": {"value": {"artifact_type": "text"}},
                },
                {
                    "name": "b",
                    "factory": {"_target_": "tests.support.config_samples:concat"},
                    "depends_on": ["a"],
                    "outputs": {"value": {"artifact_type": "text"}},
                },
            ]
        }
    )
    with pytest.raises(PipelineCycleError, match="cycle"):
        build_stage_graph(spec)
