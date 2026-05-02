# loom.pipeline.graph Specification

## Purpose

`loom.pipeline.graph` owns the pure graph mechanics for pipeline specifications.

It converts a validated pipeline definition into an explicit directed acyclic
graph, resolves stage-to-stage artifact references, detects invalid dependency
shapes, and provides traversal helpers used by execution, resume planning,
preflight checks, and inspection tooling.

The graph layer is intentionally independent from execution. It decides what
depends on what; it does not decide whether a stage should run, how a stage is
submitted, or where artifacts are stored.

## Scope

This component owns:

```text
building a stage dependency graph
detecting cycles
topological ordering
direct upstream and downstream queries
transitive upstream and downstream queries
parsing artifact references such as train.model
binding stage inputs to upstream artifact outputs
producing graph diagnostics for invalid pipeline specs
```

This component does not own:

```text
stage execution
resume policy
artifact serialization
artifact loading
executor selection
resource scheduling
run state mutation
visual rendering
```

## Package Layout

Recommended source layout:

```text
src/loom/pipeline/graph/
  __init__.py
  dag.py
  topology.py
  bindings.py
```

Responsibilities:

```text
dag.py        graph construction and graph query helpers
topology.py   topological sort and cycle detection
bindings.py   artifact reference parsing and input binding resolution
```

The graph package should not import executor, artifact store, run store, or CLI
modules.

## Inputs

The primary input is the validated core pipeline model.

Conceptually:

```text
PipelineSpec
  stages:
    stage_id:
      callable
      inputs
      outputs
      resources
      metadata
```

The graph layer may depend on the shape of `PipelineSpec`, `StageSpec`,
`InputSpec`, and `OutputSpec`, but it should avoid depending on project runtime
objects.

## Outputs

The main output is a graph representation that can answer deterministic queries.

Recommended dataclasses:

```python
@dataclass(frozen=True)
class StageGraph:
    nodes: Mapping[str, StageNode]
    edges: frozenset[StageEdge]

@dataclass(frozen=True)
class StageNode:
    stage_id: str

@dataclass(frozen=True)
class StageEdge:
    upstream_stage_id: str
    downstream_stage_id: str
    reason: str
```

The exact implementation can be lighter than this if existing project models
already provide a natural graph shape. The important contract is that graph
queries are deterministic and do not mutate pipeline specs.

## Stage IDs

Stage IDs are the graph node identity.

Rules:

```text
stage IDs are unique within a pipeline
stage IDs are stable across validation, planning, and execution
stage IDs are used in artifact references
stage IDs are used in state and provenance records
```

The graph layer should not rewrite stage IDs. Name normalization belongs in
pipeline construction or config loading before graph construction.

## Edges

An edge means:

```text
the downstream stage cannot run until the upstream stage has produced the required output
```

Edges are derived from input bindings, not from the order in which stages appear
in a config file.

Example:

```yaml
stages:
  extract:
    outputs:
      table: ...
  train:
    inputs:
      data: extract.table
```

This creates:

```text
extract -> train
```

## Artifact References

Artifact references use a small, domain-neutral syntax.

Recommended canonical form:

```text
{stage_id}.{output_name}
```

Examples:

```text
extract.table
train.model
evaluate.metrics
```

The graph layer should parse this syntax into a structured value.

Recommended dataclass:

```python
@dataclass(frozen=True)
class ArtifactReference:
    stage_id: str
    output_name: str
```

## Reference Parsing

Recommended function:

```python
def parse_artifact_reference(value: str) -> ArtifactReference: ...
```

Expected behavior:

```text
exactly one separator between stage ID and output name
empty stage ID is invalid
empty output name is invalid
unknown stage IDs are not checked by the parser
unknown output names are not checked by the parser
```

Parsing should stay syntactic. Semantic validation belongs in binding
resolution because it needs the full pipeline spec.

## Input Binding Resolution

Recommended functions:

```python
def resolve_input_bindings(spec: PipelineSpec) -> Mapping[str, Mapping[str, ResolvedInputBinding]]: ...

def bind_stage_inputs(stage_id: str, spec: PipelineSpec) -> Mapping[str, ResolvedInputBinding]: ...
```

Recommended resolved value:

```python
@dataclass(frozen=True)
class ResolvedInputBinding:
    input_name: str
    source_stage_id: str | None
    source_output_name: str | None
    literal_value: object | None
```

The exact shape should follow the existing input model. The contract is that
stage inputs are resolved before execution planning needs them.

## Binding Sources

Inputs may be:

```text
upstream artifact references
literal config values
external source references
runtime-provided values
```

Only upstream artifact references create graph edges.

Literal values and external sources may still be validated by preflight, but
they do not create stage-to-stage dependencies.

## Graph Construction

Recommended function:

```python
def build_stage_graph(spec: PipelineSpec) -> StageGraph: ...
```

Expected behavior:

```text
include every stage as a node
derive edges from resolved artifact references
raise a validation error for unknown upstream stages
raise a validation error for unknown upstream outputs
raise CycleError or a pipeline validation error when cycles are found
return a deterministic graph
```

Graph construction should be pure. It should not touch the filesystem, import
stage callables, load artifacts, or mutate run state.

## Topological Ordering

Recommended function:

```python
def topological_sort(graph: StageGraph) -> list[str]: ...
```

Expected behavior:

```text
return every stage ID exactly once
place upstream stages before downstream stages
use deterministic tie-breaking for independent stages
raise CycleError if the graph contains a cycle
```

Tie-breaking should use stable stage order from the pipeline spec if available,
otherwise lexical stage ID order.

## Cycle Detection

Recommended function:

```python
def detect_cycles(graph: StageGraph) -> list[list[str]]: ...
```

Recommended exception:

```python
class CycleError(ValueError):
    cycles: Sequence[Sequence[str]]
```

Diagnostics should include the stage path where practical:

```text
cycle detected: prepare -> train -> prepare
```

The graph layer should not attempt to break cycles automatically.

## Graph Queries

Recommended helpers:

```python
def upstream_of(graph: StageGraph, stage_id: str) -> set[str]: ...
def downstream_of(graph: StageGraph, stage_id: str) -> set[str]: ...
def transitive_upstream(graph: StageGraph, stage_id: str) -> set[str]: ...
def transitive_downstream(graph: StageGraph, stage_id: str) -> set[str]: ...
```

These helpers support:

```text
resume planning
force-rerun planning
impact analysis
CLI inspection
preflight explanations
future graph visualization
```

Unknown stage IDs should raise a clear validation error.

## Execution Integration

Execution uses graph output to decide legal scheduling order.

The graph layer provides:

```text
topological order
ready-stage dependency relationships
resolved input bindings
```

Execution owns:

```text
whether a stage is skipped
whether a stage is resumed
whether a stage is submitted locally or remotely
how input artifacts are loaded
how output artifacts are recorded
```

## Resume Integration

Resume planning should use graph traversal helpers for:

```text
finding descendants of forced stages
finding ancestors needed by selected stages
checking whether skipped stages have valid upstream artifacts
explaining why a downstream stage must rerun
```

The graph package should not inspect run history directly. It should be passed
the pipeline spec and let resume logic combine graph facts with run-store facts.

## Preflight Integration

Preflight uses graph construction to catch:

```text
missing upstream stages
missing upstream outputs
cycles
invalid artifact reference syntax
unreachable or unused outputs when warning rules are enabled
```

Preflight may also render a graph summary, but the underlying graph component
should remain presentation-neutral.

## Error Model

Graph errors should carry enough context for user-facing messages.

Useful fields:

```text
stage_id
input_name
reference
source_stage_id
source_output_name
cycle_path
```

The core exception type can be a pipeline validation error if such a type
already exists. Avoid introducing a parallel error hierarchy unless the existing
errors cannot express graph-specific diagnostics.

## Determinism

Graph construction and traversal must be deterministic.

Rules:

```text
do not rely on unordered set iteration for output order
preserve authored stage order where available
sort independent items when authored order is unavailable
produce stable diagnostic ordering
```

This matters because graph output feeds fingerprints, planning explanations,
tests, and user-facing diffs.

## Serialization

The graph does not need to be a canonical persisted object in v0.

If graph summaries are persisted later, they should include only stable data:

```json
{
  "nodes": ["extract", "train", "evaluate"],
  "edges": [
    {
      "upstream": "extract",
      "downstream": "train",
      "reason": "input:data"
    }
  ]
}
```

Do not persist Python object reprs.

## Testing

Unit tests should cover:

```text
single-stage graph
linear graph
branching graph
diamond graph
independent stages
unknown upstream stage
unknown upstream output
invalid artifact reference syntax
cycle detection
deterministic topological ordering
direct upstream and downstream queries
transitive upstream and downstream queries
literal inputs do not create edges
external inputs do not create edges
```

Tests should use small in-memory pipeline specs and should not require artifact
stores or executors.

## Implementation Plan

1. Add syntactic artifact reference parsing.
2. Add binding resolution against the validated pipeline spec.
3. Build a deterministic `StageGraph`.
4. Add cycle detection and topological sorting.
5. Replace any ad hoc execution dependency logic with graph helpers.
6. Add preflight diagnostics on top of graph construction failures.

## Deferred Work

Deferred graph features:

```text
graph visualization output
partial graph materialization for selected stages
graph diffing between pipeline versions
conditional execution branches
dynamic graph expansion at runtime
fan-out and fan-in shorthand syntax
```

These should be designed only after the static DAG model is stable.

