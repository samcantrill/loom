# Stage 42 Implementation Walkthrough

Status: proposed implementation, not currently available Loom APIs.

This guide explains the [implementation plan](implementation-plan.md) in ordinary
language. The three [planning cards](planning.md#planning-card-index) own exact
contracts; phase cards own implementation and tests. Snippets illustrate the
proposed public usage or internal algorithm, not copy-paste code for today's
release. Private helper names deliberately remain flexible.

## The Big Picture

The goal is to let a person or agent ask Loom useful questions without knowing
where a project puts files or how its pipeline names scientific operations.

```text
Application supplies context
          │
          ▼
Existing coordinator accepts a submission ── original reason + operation ID
          │
          ▼
Existing run authority ── run URI + lifecycle + editable annotations
          │
          ├── query: find runs, submissions, jobs and labels
          ├── select: resolve an exact committed output
          ├── trace: follow recorded input/output relationships
          └── access: describe, preview or fetch declared files
                    ▲
              Python / CLI / MCP
              share the same contract
```

We would extend the owners Loom already has. The coordinator knows requests and
their eventual runs. The run authority knows lifecycle and committed output
facts. Artifact stores/publication receipts know file locations and declared
contents. A client asks those owners; it does not guess paths or create a second
experiment database.

## 1. Describe Work When Submitting It

The application decides what its labels mean. Loom only stores plain data.

```python
context = SubmissionContext(
    description="Increase temporal kernel size to test cross-dataset transfer.",
    tags={"dataset": "PURE", "model": "PhysNet", "study": "kernel-study"},
    metadata={"temporal_kernel_size": 5, "revision": 3},
)

request = RunRequest(
    preparation=PrepareRunRequest(
        operation_id="kernel-study-submit-17",
        run_name="kernel-five",
        source=source,
        config_path="pipeline.yaml",
        preparation_profile="research",
        context=context,
    ),
    queue_item_id="kernel-study-job-17",
)
operation = client.start_run(request)
```

An invoice-processing application could supply `customer` and `document_type`
instead. Neither requires a Loom plugin or registered label vocabulary. If rphys
wants to derive labels from its config, ordinary rphys submission code constructs
this object. Loom does not inspect a configuration and decide what “model” means.

Implementation: add an optional field to existing `PrepareRunRequest`, retain it
in the existing operation journal, and initialize an authority-owned annotation
record when the run is first bound. Keep the original request unchanged after
that. The operation handle is useful before the eventual `run_uri` exists; an
accepted request is not a completed run.

There can be several submissions that reconcile to the same run. Therefore:

- “Why was this run originally created?” reads its initializing submission.
- “What did we submit yesterday?” searches submission records, including later
  requests that reused a run or failed before a run was created.
- “How do we describe this run now?” reads editable run annotations.

These are different questions; one mutable description cannot answer all three.
Old clients that omit context keep their existing request encoding and replay
digest. New nonempty context requires explicit server capability support.

See [P1](phases/submission-context.md) for storage, crash/replay and compatibility.

## 2. Edit Labels Without Losing Another Agent's Changes

Tags are a string-to-string map. Metadata preserves JSON types: a numeric revision
is different from the label `"3"`. Notes are timestamped observations, separate
from both the original reason and editable description.

```python
current = client.get_run_context(run_uri).annotations
client.patch_run_annotations(
    run_uri,
    mutation_id="review-17-labels",
    expected_revision=current.revision,
    set_tags={"review_status": "ready"},
    remove_tags=("needs_review",),
)
client.append_run_note(
    run_uri,
    mutation_id="review-17-note",
    text="Reviewed the declared summary; investigate the second cohort next.",
)
```

The revision means “apply my edit only if nobody has changed these annotations
since I read them.” A conflict asks the caller to read again and decide whether
to reapply. It does not silently erase someone else's work. The mutation ID means
“if the reply is lost, repeating this exact request must not apply it twice.”

Inside the owning database, the important ordering is:

```python
def apply_annotation_request(store, request, principal):
    with store.transaction():
        replay = store.find_mutation(request.run_uri, principal, request.mutation_id)
        if replay is not None:
            return verify_same_request_and_return(replay, request)
        current = store.read_annotations(request.run_uri)
        require_revision(current.revision, request.expected_revision)
        updated = patch_requested_fields_only(current, request)
        store.write_annotations(updated)
        store.record_mutation(request.run_uri, principal, request, updated)
        return updated
```

Checking replay before revision matters: a successful old request should still
replay successfully after later edits. The effect and receipt must commit in the
same transaction. Append-only notes use the same retry discipline; two independent
note appends need not compete over an annotation revision.

These changes never rewrite configuration/action fingerprints or artifact
identity. They organize an execution; they do not change what ran. See
[P2](phases/run-annotations.md).

## 3. Search With Explicit, Typed Filters

Use small data objects instead of executing a query string:

```python
query = RunQuery(
    scope=ManagedScope(),
    where=AllOf((
        Compare(Field("tags", ("dataset",)), "eq", "PURE"),
        Compare(Field("tags", ("model",)), "eq", "PhysNet"),
        Compare(Field("metadata", ("revision",)), "gte", 3),
        Compare(Field("native", ("submitted_at",)),
                "gte", "2026-09-23T00:00:00Z"),
        Compare(Field("native", ("submitted_at",)),
                "lt", "2026-09-24T00:00:00Z"),
    )),
    order_by=(Order("submitted_at", descending=True), Order("run_uri")),
    limit=50,
)
page = client.search_runs(query)
```

The application chooses `dataset`, `model` and `revision`. Loom understands
equality, numbers, timestamps, presence, boolean combinations and explicitly
requested version comparison. Native Git commit equality uses recorded provenance;
a metadata field called `commit` remains only a caller claim.

For a semantic-version tag, request `semver_gte` explicitly. Loom should never
guess that a key named `version` is SemVer, or that a Git hash has a meaningful
greater-than order. A literal tag `dataset.version` has one path segment;
nested metadata `dataset → version` has two.

Implementation has three small parts:

```python
def execute_query(request, source):
    checked = parse_and_validate_query(request)
    candidates = source.iter_authorized_candidates(checked.scope)
    return bounded_page(
        candidates,
        predicate=lambda row: evaluate(checked.where, row),
        ordering=checked.order_by,
        cursor=checked.cursor,
        limit=checked.limit,
    )
```

First validate the request. Then read candidate facts from existing owners. Then
evaluate and page. Keep this evaluator shared between native queries and the
local catalog surface. The CLI and MCP only translate to the same request.

An unavailable field is not the same as a known absent field. “Not model X” must
not quietly include a run whose metadata could not be read. Results carry
coverage warnings. Pagination is live, not a frozen database snapshot: callers
must preserve warnings and follow continuation, including empty pages that still
have a continuation because the scan budget ran out.

`query_fields`, `tag_keys` and `tag_values` make the interface discoverable.
`search_submissions` answers recent launch questions; `search_jobs` preserves
native job/run associations. See [P3](phases/run-discovery.md).

## 4. Select A Result Before Reading Its Bytes

“The current output” can change after a retry. Selecting it should return the
particular committed version observed, not just a mutable path:

```python
@dataclass(frozen=True)
class OutputLocator:
    run_uri: str
    stage_name: str
    commit_id: str
    output_name: str
```

This groups existing identity fields; it is not a new allocated result ID.
`select_outputs` produces this locator, the native `ArtifactRef`, its verification
evidence, and the run/stage through which it matched. Default selection uses
current commits; explicit history lists previous commits.

If a consumer reused another run's output, retain both associations: “found through
run B” and “actually produced by run A, commit C.” There may be no new commit or
attempt in B. P6 later reads the exact A/C output; it cannot substitute A's newer
commit. Failed runs may still have useful earlier committed outputs.

Selection is cheap metadata access. `availability=not_checked` says that Loom
has not yet tested whether the bytes are accessible. See
[P4](phases/output-selection.md).

## 5. Record Dependencies When Inputs Are Bound

For “summaries associated with training run X,” Loom must understand relationships,
not the words `train` or `summary`. The caller identifies X's run/stage/output and
asks for downstream outputs of a caller-defined type.

The critical implementation work happens before the query: retain each attempt's
actual input version when preparing it.

```python
binding = AttemptInputBinding(
    input_name="checkpoint",
    source_stage_name="fit",
    source_output_name="weights",
    artifact=resolved_input.artifact,
    producer=resolved_input.locator,
    source_kind="produced",
)
```

Store this alongside the existing prepared-attempt record, before worker handoff.
It must describe the same artifact the worker receives, even if materialization
changes its local path. Existing readiness/fencing checks still decide whether
the input is valid; lineage must not change scheduling.

Now a later producer retry cannot change the story of an earlier consumer. A
query follows producer commit → consuming attempt → that attempt's committed
outputs. Upstream traversal reverses those relationships. Declared dependencies,
prepared-but-unstarted bindings, started attempts and output reuse remain
different relation kinds.

We also need to retain the fact that a start was acknowledged. Today's terminal
status alone cannot tell us whether cancellation happened before or after start.
The authority would record `start_confirmed` and its acknowledgement time in the
same transaction that confirms execution start, and never erase it when the
attempt finishes. Older records without that evidence remain unknown. This is a
small addition to the existing attempt record, not a new event-tracking service.

The graph algorithm is ordinary bounded traversal, with one easy-to-miss rule:

```python
for node in walk_recorded_graph(start, direction="downstream", max_depth=10):
    # Walk through checkpoints/predictions even when only summaries are wanted.
    if matches_requested_output_type(node, "summary_manifest"):
        selected_results.append(node)
```

Filter what you return, not which intermediate nodes you traverse. Otherwise the
query misses summaries behind prediction/metric nodes. Deduplicate by native
identity, retain connecting edges, and report limits/unknown evidence. A recorded
input on a started attempt means “bound to this execution,” not proof that the
application opened every file. Legacy runs with insufficient evidence remain
explicitly unknown. See [P5](phases/dependency-lineage.md).

## 6. Retrieve Complete Files And Give Agents Bounded Content

A file URI on a worker is not necessarily readable on an agent's machine. Native
access needs to resolve an authorized selected output and transfer its declared
bytes. It must not accept an arbitrary server path supplied by the caller.

The proposed native operations are:

- `describe_artifact`: primary file, full declared file inventory, sizes and
  available checksums, all tied to the exact output locator.
- `read_artifact_chunk`: bounded byte ranges from authorized declared members.
- `read_artifact`: explicit bounded text, JSON or byte preview.
- `fetch_artifacts`: client-side download helper using those native reads.

For multi-file results, existing publication receipts are the generic inventory.
Fetch the complete declared tree and preserve relative paths. Loom does not open
an rphys manifest and try to guess its dependencies. If a producer never declared
the file collection, report that limitation instead of claiming a complete fetch.

```python
def fetch_one(client, selected, destination):
    declaration = client.describe_artifact(selected.locator)
    with owned_temporary_directory(destination) as pending:
        for member in declaration.iter_members():
            copy_chunks(client, selected.locator, declaration, member, pending)
            verify_size_and_available_digest(pending, member)
        return publish_if_destination_absent(pending, destination)
```

Download to a temporary directory, verify, and then publish a completed result.
An existing destination is a conflict, not permission to overwrite user data.
Large transfers use bounded chunks, not one large MCP response. Initial supported
paths are configured local artifact files and shared-publication trees served
through Unix or authenticated HTTPS—not every possible cloud URI.

Batch results retain an outcome for every selection: available, unavailable,
unsupported, corrupt or destination conflict. Reused bytes may be downloaded
once while retaining every run association. “Batch complete” means every item
was processed; it does not mean every fetch succeeded.

For previews, text may return a labelled truncated prefix; JSON must be complete
within the limit or return `too_large`. No Python unpickling, automatic codec
execution or domain metric extraction. If an agent asks for the contents of all
matching summaries, it pages the search, traces/selects exact outputs, then
reads/fetches those selections while preserving per-item errors and coverage.
Large summaries can be retrieved as files for application-owned analysis.

See [P6](phases/artifact-access.md), including a real HTTPS test where the client
cannot directly read the producer's source directory.

## What Makes This Generic And Useful

Loom supplies identities, facts, labels, relationships and safe access. rphys
supplies naming conventions and scientific interpretation. Another application
can use the same machinery unchanged.

The most consequential engineering work is not adding tool names: it is preserving
original submissions across retries, making edits atomic, recording exact input
versions, and carrying honest coverage/integrity evidence through every client.
The six phases make those contracts testable independently, with no promise that
historically missing evidence or inaccessible bytes can be reconstructed.
