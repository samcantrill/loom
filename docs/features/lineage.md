# Dependency lineage

`CoordinatorClient.trace_lineage(LineageQuery(...))` reads retained relationships
without opening artifact bytes or running application code. `LineageQuery` is
available from `loom.runs`; `AttemptInputBinding` from `loom.pipeline.stores`.

```python
from loom.runs import LineageQuery

query = LineageQuery(
    start=selected_output.locator.to_dict(),
    direction="downstream",
    artifact_type="summary_manifest",
)
page = client.trace_lineage(query)
```

Start with a `run_uri`, optionally `stage_name`, an exact scoped `attempt_id`, or
all four `OutputLocator` fields. Run/stage queries default to current outputs;
`history="all"` includes historical outputs. Exact locators never follow a newer
producer commit. The same graph serves a checkpoint → prediction → summary
pipeline and a document → extracted fields → invoice report pipeline.

Relations are `declared_dependency`, `bound_input`, `consumed_input`, and
`reused_output`. The default includes consumed inputs and reuse associations.
Consumption means the authority acknowledged that the assigned attempt started;
it does not prove application code opened every input. Prepared or unstarted
terminal attempts retain bound edges. Unknown historical start evidence remains
bound and produces incomplete-coverage warnings. Each output node names its
producing attempt; these ownership joins do not count as another data dependency.

Bindings retain the exact original artifact and producer, independently of worker
materialized paths. Reuse retains the original producer and a separate adopted
stage association. Equal tags, filenames or checksums do not create edges.
Path-free resident handoffs carry a digest referencing those retained bindings,
scoped by the existing assignment/attempt identity. Original coordinator paths
stay at the authority; this evidence digest does not enter action fingerprints.
Missing historical bindings and external inputs are explicit evidence boundaries.
Declared ordering requires `relations=("declared_dependency",)` and may include
unexecuted nodes. Input, output and intermediate node identities remain visible
when `artifact_type` marks only matching output nodes with `selected=true`.

Pages are live observations. Follow `next_cursor` with the same query and retain
all warnings. Defaults are depth 10 and at most 200 returned nodes/edges per page;
requests cap acquired/visited entities at 2,000 and scoped run acquisitions at 500.
Depth or traversal limits indicate incomplete coverage. A traversal-limit result
has no advancing cursor: narrow scope before trying again. Node and edge entries
may span pages; assemble them by their full identities. Metadata-only access does
not promise payload availability or retention.

`loom runs lineage --query '{"start":{"run_uri":"file:///runs/example"}}'
--format json` uses the same native request as Python. MCP exposes the read-only
`loom_trace_lineage` tool. Native `lineage-query-v1` is available to both CLIENT
and QUERY roles over their existing transports. Scope independently authorizes
each producer; a retained reference never grants access to another run.

Embedded authority schema 10 and repository schema 11 retain nullable start
acknowledgements with their first authority UTC timestamp. Terminalization,
replay and restart preserve a witnessed start. Historical rows have unknown
witnesses; creation/finish times and audit observations are not substitutes.

Bundle exports preserve source attempts, bindings, witnesses and commit history
in versioned `lineage_evidence`. Portable imports retain this under
`historical_lineage` in existing run/runtime metadata, inspectable with
`LocalRunStore.read_runtime_metadata`. Original identities remain distinct from
the target run URI and copied payload paths. Older bundles expose `None`.
Historical imports do not become native executions or grant source access;
duplicate imports never substitute for unavailable source identities. Offline
authority import also keeps source evidence separate from synthesized commits
and leaves its local attempt start witness unknown.
Snapshot-only bundle metadata preserves the attempts and commits present in that
snapshot; `read_completed_run_bundle_metadata` includes the store's full commit history.
