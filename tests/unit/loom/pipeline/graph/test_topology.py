"""Unit tests for deterministic graph topology helpers."""

import pytest

from loom.pipeline import PipelineSpec
from loom.pipeline.errors import PipelineCycleError
from loom.pipeline.graph import build_stage_graph, detect_cycles, topological_sort


def _diamond_spec() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "stages": [
                {"name": "a", "_target_": "tests.support.config_samples:concat", "outputs": {"value": {"artifact_type": "text"}}},
                {"name": "b", "_target_": "tests.support.config_samples:concat", "depends_on": ["a"], "outputs": {"value": {"artifact_type": "text"}}},
                {"name": "c", "_target_": "tests.support.config_samples:concat", "depends_on": ["a"], "outputs": {"value": {"artifact_type": "text"}}},
                {"name": "d", "_target_": "tests.support.config_samples:concat", "depends_on": ["b", "c"], "outputs": {"value": {"artifact_type": "text"}}},
            ]
        }
    )


def test_topological_sort_is_deterministic_with_author_order_tiebreak() -> None:
    spec = _diamond_spec()
    graph = build_stage_graph(spec)
    order = topological_sort(graph)
    assert order == ["a", "b", "c", "d"]


def test_transitive_upstream_and_downstream() -> None:
    spec = _diamond_spec()
    graph = build_stage_graph(spec)
    from loom.pipeline.graph.dag import transitive_downstream, transitive_upstream

    assert transitive_upstream(graph, "d") == {"a", "b", "c"}
    assert transitive_downstream(graph, "a") == {"b", "c", "d"}


def test_detect_cycles_reports_cycle_examples() -> None:
    from loom.pipeline.graph.dag import StageNode, StageEdge, StageEdgeReason, StageGraph

    graph = StageGraph(
        nodes={"a": StageNode("a", 0), "b": StageNode("b", 1), "c": StageNode("c", 2)},
        edges=frozenset(
            {
                StageEdge("a", "b", StageEdgeReason.CONTROL),
                StageEdge("b", "c", StageEdgeReason.CONTROL),
                StageEdge("c", "a", StageEdgeReason.CONTROL),
            },
        ),
    )
    cycles = detect_cycles(graph)
    assert cycles
    with pytest.raises(PipelineCycleError, match="cycle"):
        topological_sort(graph)
