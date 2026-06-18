"""Graph representation and helpers for pipeline DAGs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from loom.ids import StageID

from loom.pipeline.errors import PipelineCycleError, PipelineGraphError
from loom.pipeline.graph.bindings import resolve_input_bindings
from loom.pipeline.specs import PipelineSpec


class StageEdgeReason(StrEnum):
    DATA = "data"
    CONTROL = "control"


@dataclass(frozen=True, slots=True)
class StageNode:
    stage_id: StageID
    order: int


@dataclass(frozen=True, slots=True)
class StageEdge:
    upstream_stage_id: StageID
    downstream_stage_id: StageID
    reason: StageEdgeReason
    input_name: str | None = None
    output_name: str | None = None


@dataclass(frozen=True, slots=True)
class StageGraph:
    nodes: dict[StageID, StageNode]
    edges: frozenset[StageEdge]


def build_stage_graph(spec: PipelineSpec) -> StageGraph:
    nodes = {stage.name: StageNode(stage_id=stage.name, order=index) for index, stage in enumerate(spec.stages)}
    edges: set[StageEdge] = set()
    input_bindings = resolve_input_bindings(spec)
    for stage in spec.stages:
        for binding in input_bindings[stage.name].values():
            edges.add(
                StageEdge(
                    upstream_stage_id=binding.source_stage_id,
                    downstream_stage_id=binding.consumer_stage_id,
                    reason=StageEdgeReason.DATA,
                    input_name=binding.input_name,
                    output_name=binding.source_output_name,
                ),
            )

        for dependency in stage.dependencies:
            if dependency == stage.name:
                raise PipelineGraphError(f"stage '{stage.name}' has a self dependency")
            if dependency not in nodes:
                raise PipelineGraphError(f"stage '{stage.name}' depends on unknown stage '{dependency}'")
            edges.add(
                StageEdge(
                    upstream_stage_id=dependency,
                    downstream_stage_id=stage.name,
                    reason=StageEdgeReason.CONTROL,
                ),
            )

    graph = StageGraph(nodes=nodes, edges=frozenset(edges))
    cycles = detect_cycles(graph)
    if cycles:
        raise PipelineCycleError(cycles)
    return graph


def upstream_of(graph: StageGraph, stage_id: StageID) -> set[StageID]:
    upstream: set[StageID] = set()
    for edge in graph.edges:
        if edge.downstream_stage_id == stage_id:
            upstream.add(edge.upstream_stage_id)
    return upstream


def downstream_of(graph: StageGraph, stage_id: StageID) -> set[StageID]:
    downstream: set[StageID] = set()
    for edge in graph.edges:
        if edge.upstream_stage_id == stage_id:
            downstream.add(edge.downstream_stage_id)
    return downstream


def _transitive_helper(graph: StageGraph, start: StageID, *, upstream: bool) -> set[StageID]:
    neighbor_fn = upstream_of if upstream else downstream_of
    result: set[StageID] = set()
    stack = list(neighbor_fn(graph, start))
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        for next_stage in neighbor_fn(graph, current):
            if next_stage not in result:
                stack.append(next_stage)
    return result


def transitive_upstream(graph: StageGraph, stage_id: StageID) -> set[StageID]:
    return _transitive_helper(graph, stage_id, upstream=True)


def transitive_downstream(graph: StageGraph, stage_id: StageID) -> set[StageID]:
    return _transitive_helper(graph, stage_id, upstream=False)


def detect_cycles(graph: StageGraph) -> list[list[StageID]]:
    if not graph.nodes:
        return []

    adjacency: dict[StageID, set[StageID]] = {stage_id: set() for stage_id in graph.nodes}
    for edge in graph.edges:
        if edge.upstream_stage_id not in adjacency or edge.downstream_stage_id not in adjacency:
            continue
        adjacency[edge.upstream_stage_id].add(edge.downstream_stage_id)

    visited: set[StageID] = set()
    visiting: set[StageID] = set()
    stack: list[StageID] = []
    cycles: list[list[StageID]] = []

    ordered_nodes = sorted(graph.nodes.items(), key=lambda pair: pair[1].order)

    def visit(stage_id: StageID) -> None:
        if stage_id in visiting:
            cycle_start = stack.index(stage_id)
            cycle = stack[cycle_start:] + [stage_id]
            cycles.append(cycle)
            return
        if stage_id in visited:
            return
        visited.add(stage_id)
        visiting.add(stage_id)
        stack.append(stage_id)
        for next_id in sorted(adjacency[stage_id], key=lambda value: (graph.nodes[value].order, value)):
            visit(next_id)
        stack.pop()
        visiting.remove(stage_id)
        visited.add(stage_id)

    for stage_id, _ in ordered_nodes:
        visit(stage_id)
    return cycles


def topological_sort(graph: StageGraph) -> list[StageID]:
    cycles = detect_cycles(graph)
    if cycles:
        raise PipelineCycleError(cycles)

    indegree = {stage_id: 0 for stage_id in graph.nodes}
    downstream: dict[StageID, set[StageID]] = {stage_id: set() for stage_id in graph.nodes}
    seen_edges: set[tuple[StageID, StageID]] = set()
    for edge in graph.edges:
        if edge.upstream_stage_id not in indegree or edge.downstream_stage_id not in indegree:
            continue
        pair = (edge.upstream_stage_id, edge.downstream_stage_id)
        if pair in seen_edges:
            continue
        seen_edges.add(pair)
        indegree[edge.downstream_stage_id] += 1
        downstream[edge.upstream_stage_id].add(edge.downstream_stage_id)

    ready: list[StageID] = [stage_id for stage_id, degree in indegree.items() if degree == 0]
    result: list[StageID] = []

    while ready:
        ready.sort(key=lambda stage_id: (graph.nodes[stage_id].order, stage_id))
        current = ready.pop(0)
        result.append(current)
        for downstream_id in sorted(downstream[current], key=lambda stage_id: (graph.nodes[stage_id].order, stage_id)):
            indegree[downstream_id] -= 1
            if indegree[downstream_id] == 0:
                ready.append(downstream_id)

    if len(result) != len(graph.nodes):
        raise PipelineGraphError("topological sort failed: graph is incomplete or cyclic")
    return result


__all__ = [
    "StageEdgeReason",
    "StageNode",
    "StageEdge",
    "StageGraph",
    "build_stage_graph",
    "upstream_of",
    "downstream_of",
    "transitive_upstream",
    "transitive_downstream",
    "detect_cycles",
    "topological_sort",
]
