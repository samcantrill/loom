# Output Access: Dependencies, Published Results, And Client Workflows

Card ID: `PC-42-output-access`.
Status: detailed implementation design independently reviewed and approved;
implementation pending.
Planning manifest: [Stage 42](../planning.md).
Evidence revision: `220358ed26392f30bb2f36bf09d547607a57d442`.
Dependencies: [run context](run-context.md) for identity and annotations;
[discovery](discovery.md) for scope, query, and coverage.

Owned IDs: `FR-42-A01`–`A09`, `EX-42-A01`–`A06`, `VAL-42-A01`–`A08`,
`DQ-42-A01`–`A05`.

## Intent And Existing Owners

A caller can find outputs associated with specified executions, explain those
associations, and access the selected bytes without guessing directories. The
same mechanism serves scientific summaries, invoice reports, compiled packages,
or any other application-declared artifact.

| Evidence | Current contract and reuse implication |
| --- | --- |
| `docs/features/artifacts.md` and `src/loom/artifacts.py` | `ArtifactRef` carries generic identity/location/type/codec/checksum/producer/metadata; stores and explicit codecs own access, applications own meaning |
| `docs/features/provenance.md` and `src/loom/provenance` | Generic recorded inputs/outputs and producer facts are adjacent to application interpretation |
| `src/loom/diagnostics/run_inspection.py` | Native inspection presents committed artifact locations from stage artifact facts |
| `src/loom/pipeline/stores/run_store.py` and authority stores | Stage inputs/outputs and artifact indexes have existing owners |
| `docs/features/artifacts.md`, authority output-commit interfaces | Current committed outputs and explicit earlier commit history already have distinct semantics |
| `src/loom/pipeline/stores/artifact_materialization.py`, `immutable_artifacts.py`, and backend interfaces | Extend explicit supported materialization/lookup contracts; a URI alone does not transfer bytes to a remote caller |
| `tests/contracts/test_artifact_materialization_contract.py` and `test_immutable_artifact_semantics_contract.py` | Existing identity/integrity/capability obligations constrain result access |
| `tests/contracts/test_mcp_tools.py` and `tests/integration/mcp/test_stdio.py` | MCP is an existing optional native client adapter, not a new execution authority |

Existing primitives are not evidence that the complete traversal and batch-fetch
API below exists. Check producer/consumption coverage and supported backend paths
before finalizing the implementation design.

## Functional Requirements

| ID | Required behavior | Validation |
| --- | --- | --- |
| FR-42-A01 | Traverse upstream/downstream within explicit scope/depth using existing run, stage, and artifact identities | VAL-42-A01 |
| FR-42-A02 | Distinguish declared execution ordering from actual recorded artifact consumption; return the relationships justifying each association | VAL-42-A01 |
| FR-42-A03 | Resolve recorded cross-run dependencies and preserve original producers for reused outputs; do not infer provenance from tags, names, or equal checksums | VAL-42-A02 |
| FR-42-A04 | Select outputs by producer, declared name/type/metadata, or exact address; default to current committed outputs and permit explicit historical selection | VAL-42-A03 |
| FR-42-A05 | Bind retrieval to selected output versions and existing identity/integrity evidence; do not silently replace selected bytes with a newer commit | VAL-42-A03 |
| FR-42-A06 | Retrieve/materialize supported artifacts and complete producer-declared file collections, preserving relative layout and references; expose unsupported/unavailable access | VAL-42-A04 |
| FR-42-A07 | Provide explicit bounded text/JSON/byte access as supported and batch per-item outcomes with source/reuse associations; domain decoding stays with applications | VAL-42-A05, VAL-42-A06 |
| FR-42-A08 | Distinguish run success, committed output existence, selected historical/current state, and current access/verification evidence | VAL-42-A06 |
| FR-42-A09 | Share native behavior across Python, CLI, and MCP; keep metadata reads inert and mutating/access requests explicit, with bounded machine-readable responses | VAL-42-A07, VAL-42-A08 |

## Dependency Graph Behavior

The query graph follows persisted relationships, not application names. A
traversal identifies its starting entity, direction, relation kinds, depth,
scope, and limits. A response provides matching entities, connecting edges, and
whether depth/page/scope/evidence limits prevented a complete traversal.

At least these two relationship meanings must remain distinguishable:

| Relation | Evidence | Meaning |
| --- | --- | --- |
| Declared dependency | Captured pipeline dependency/binding contract | An authored/planned ordering or input relationship |
| Artifact consumption | Recorded binding of a selected artifact to an actual execution/attempt | This execution used that published result |

An unexecuted downstream node may appear in a declared graph without having
consumed anything. A later repaired/retried producer can have newer outputs than
the artifact previously consumed. Actual lineage must preserve the selected
version at the consuming execution, rather than relinking every consumer to the
producer's current head.

Traversal from a run or stage defaults to its current committed outputs for a
result-oriented query. A caller can explicitly select historical outputs or a
particular artifact/commit. Starting from a specific artifact follows that exact
version. The detailed design below specifies native locators and history selectors.

Traverse through intermediate nodes before filtering terminal result types. A
`summary_manifest` filter must not prune a required checkpoint/prediction/metric
edge and falsely report no summaries. Support fan-out/fan-in without treating
multiple paths to one artifact as independent producer executions.

Across runs, use recorded artifact addresses, producer/reuse facts, and consumed
inputs where those facts exist. A matching tag, stage name, or content checksum
does not by itself establish lineage. Unknown external provenance is an explicit
boundary. This stage does not retroactively fabricate missing historical edges.

## Output Selection And History

Output discovery is metadata-only. Select by run/stage producer, declared output
name, application-provided artifact type/metadata, or existing exact address.
No hard-coded `train`, `predict`, `score`, or `summary` dispatch belongs here.

A selected output should convey, using existing native representations where
possible:

- Run/stage/output association used to find it.
- Exact artifact identity/reference and commit/version selection.
- Original producer/reuse relationships when different from the consuming run.
- Declared type/schema/codec and checksum/fingerprint evidence when available.
- Known locations and the scope/freshness of availability evidence.

Existing authority output commits are the owner of published success. Default
selection uses current committed output facts; historical access is explicit.
Uncommitted workspace files do not become successful results merely because they
exist. Their existing diagnostic access, if any, remains separate.

Selection fixes the reference/version used by subsequent reads. A concurrent
new output commit does not silently redirect a prior selection. If old bytes
are no longer accessible, return that outcome rather than substituting current
bytes. This is not a promise to pin retention or prevent explicit garbage
collection indefinitely.

## Payload Access And Batch Behavior

Metadata search, lineage discovery, and content access are separate operations.
Selecting a file URI does not guarantee that the client has that filesystem.
Use configured backend/access/materialization capabilities to obtain the
selected result or explain why it is unsupported/unavailable.

For multi-file artifacts, fetch the complete file collection declared by the
producer and preserve relative layout. Loom handles generic declarations and
existing containment/integrity rules. It does not parse an arbitrary rphys,
invoice, or model manifest to discover implicit dependencies. The producing
application must publish the declaration through supported contracts.

Bounded generic text or JSON reading can return contents directly when supported;
byte/binary/large outputs can use explicit materialization or streaming handles.
Do not import/execute recorded application targets or arbitrary serialized Python
objects for an agent preview. Applications may explicitly apply their own codecs
or readers after retrieval. Existing codec APIs need no domain special cases.

Limits and truncation must be explicit. Truncated text can be a labelled preview;
truncated JSON is not a successfully decoded JSON value, and a partial download
is not a complete verified artifact. The detailed design below fixes byte/page
limits and chunk retries; cross-restart download resume is deferred.

Batch selection/retrieval retains each selected run/output association and an
outcome per item. Selection also accounts for explicitly requested runs with no
matching output; an empty list must not hide those omissions.

| Situation | Required meaning in the response |
| --- | --- |
| Selected run has no matching committed output | No matching output for that run; do not report a transfer failure |
| Selected artifact metadata exists but bytes cannot be obtained | Unavailable/unsupported access with the selected reference retained |
| Bytes fail recorded integrity checks | Failed verification, not a usable completed fetch |
| Current run failed after publishing earlier outputs | Those committed outputs remain discoverable independently of terminal failure |
| Several selected runs reuse one artifact | Fetch may deduplicate bytes; every matching association and original producer stays visible |
| Some items succeed and others fail | Return per-item outcomes and truthful batch completeness; do not silently drop failures |
| A page, byte, depth, or scope limit is reached | Report the applicable limit/continuation and avoid an exhaustive-result claim |

Deduplicating transfer does not deduplicate scientific evidence on behalf of the
application. Preserve enough provenance for the caller to decide which results
represent independent observations.

## Examples

All snippets are proposed Python-shaped pseudocode. Full `run_uri` and artifact
references are supplied by native responses. Display names in diagrams are not
new identity formats. `collect_pages` stands for exhausting a bounded query while
retaining coverage warnings; production callers may instead stream pages.

### EX-42-A01: Summaries Associated With A Particular Producer

An application declares these names and publishes the corresponding artifacts:

```text
run A / fit
    -> checkpoint A1
    -> run B / predict
    -> predictions B1
    -> run B / score
    -> metrics B2
    -> run B / summarize
    -> summary B3
```

```python
downstream = collect_pages(client.lineage.traverse(
    start={"run_uri": training_run_uri, "stage": "fit"},
    direction="downstream",
    relation="artifact_consumption",
    max_depth=10,
))
summaries = collect_pages(client.outputs.search(
    producers=downstream.executions,
    artifact_type="summary_manifest",
))
```

Expected: summary B3 is returned with the path through A1, B1, and B2. A similarly
tagged summary from run C with no recorded dependency is not included. Intermediate
non-summary nodes are traversed. A depth/coverage limit is visible to the caller.

### EX-42-A02: Explain A Result's Inputs

```python
upstream = collect_pages(client.lineage.traverse(
    start={"artifact_ref": selected_summary_ref},
    direction="upstream",
    relation="artifact_consumption",
    max_depth=10,
))
```

Expected: exact consumed versions and original producers are returned. An input
with unknown external production history is shown as an external boundary. A
later checkpoint repair does not rewrite the summary's actual consumed lineage.

### EX-42-A03: Retrieve All Matching Summary Artifacts

```python
run_matches = collect_pages(client.runs.search(
    where=all_of(
        eq("tags.study", "temporal-kernel-ablation"),
        eq("status", "SUCCEEDED"),
    ),
    limit=50,
))
outputs = collect_pages(client.outputs.search(
    run_uris=run_matches.run_uris,
    artifact_type="summary_manifest",
))
retrieved = client.artifacts.fetch(
    refs=outputs.refs,
    destination="./retrieved-summaries",
)
```

Expected: selection records identify exact committed outputs and source runs.
The caller consumes all query pages and accounts for query warnings/no-output
matches before describing the result as "all summaries". Retrieval obtains each
declared file collection and returns per-item outcomes and usable local paths or
supported handles. A remote URI is not blindly converted to a local path.

Representative metadata, not a frozen wire schema:

```json
{
  "run_uri": "<native run URI>",
  "stage": "summarize",
  "output_name": "summary_manifest",
  "artifact_ref": "<serialized native reference>",
  "output_commit_id": "<native committed output identity>",
  "artifact_type": "summary_manifest",
  "availability": "<known access evidence, or not checked>"
}
```

Application interpretation is a separate call:

```python
for item in retrieved.items:
    if item.status == "available":
        summary = application.read_summary(item.local_path)
```

The application may decode rphys formatted manifests and compare units,
populations, splits, and aggregation. Loom does not select a metric or conclude
that two results are scientifically comparable.

### EX-42-A04: Reuse And Historical Selection

Run A published artifact P1, later superseded by P2. Run B actually consumed P1
and produced S1; run C consumed P2 and produced S2.

Expected observations:

- Current output selection on A returns P2.
- Explicit history exposes P1 and P2 with their commit identities.
- Traversal from P1 reaches B/S1; it does not relink B to P2.
- A fetch already selecting P1 either retrieves/verifies P1 or reports that P1
  is unavailable; it never returns P2 as if it were P1.
- If another run adopts S1, access preserves both the adoption association and
  S1's original producer. Its bytes can be transferred once for a batch.

### EX-42-A05: A Non-Scientific Application Uses The Same Mechanism

```text
run D / normalize -> normalized document
    -> run E / extract -> extracted fields
    -> run E / publish -> invoice_report
```

Search `tags.customer=example-company`, traverse recorded dependencies, and select
`artifact_type=invoice_report`. Retrieve the declared JSON/PDF/files using the
same Loom calls. A downstream invoice reader interprets their contents. There is
no model/dataset field requirement or branch in Loom for this application.

### EX-42-A06: Agent Workflow And Transport Parity

Request:

> Find work launched this week for the kernel study, explain why it was launched,
> retrieve summaries downstream of its training outputs, and tag runs with
> successfully retrieved summaries as ready for review.

Expected tool sequence:

1. Discover relevant tag values if needed; resolve an explicit time range.
2. Search scope, time, and study; preserve full identities and coverage.
3. Read original submission descriptions and current execution/output state.
4. Traverse recorded artifact dependencies from the caller-selected producers.
5. Select exact summary references, obtain their complete declared files, and
   report missing/unavailable/failed items.
6. Apply the explicitly requested run tag to the identified runs, using the
   chosen association (source runs in this request) and report which were changed.

The interface must keep source runs and downstream producer runs explicit so an
agent does not annotate the wrong entity. If a request leaves that target
ambiguous, the client/agent resolves it before mutation. Read-only requests do
not trigger step 6.

Equivalent behavioral surfaces; concrete methods are specified in the detailed
design below:

| Capability | Python | CLI | MCP |
| --- | --- | --- | --- |
| Search/inspect | Typed native request/result | Flags/query input and JSON or human projection | Bounded structured tools with continuation |
| Vocabulary/field discovery | Native schema and value views | List/inspect presentation | Discoverable query fields and label values |
| Annotate | Explicit native patches/note append | Explicit mutation commands | Explicit write tools using identical ownership/replay rules |
| Traverse/select outputs | Native entity/edge/reference results | Machine-readable graph/output selections | Structured selections retaining exact identities |
| Read/fetch | Supported native read/materialization handles | Explicit destination/content requests | Bounded content or references/handles, no implicit large prompt dump |

MCP is an optional client of native capabilities. It does not own another index,
scheduler, artifact format, or metadata store. Reuse the existing adapter and
safe result/error presentation. The CLI should not require parsing human tables
to pass results between operations.

## Proposed Ownership And Complexity

Use existing persisted stage input/output bindings, authority output commits,
artifact addresses/provenance, materialization capabilities, native query routes,
and client adapters. New derived edge/output projections are justified only for
the accepted traversal/discovery consumer and must identify their fact source.

Do not create a durable "result" object which duplicates `ArtifactRef`, a global
content-addressed cache, a new producer identity, or a remote backend SDK merely
to implement convenient access. If recorded facts cannot establish a required
cross-run edge, identify the exact producer/consumer capture change in design
instead of guessing a relationship at query time.

## Design Decision Disposition

| ID | Decision required before implementation readiness | Direction and constraint |
| --- | --- | --- |
| DQ-42-A01 | Consumption evidence and graph | Resolved proposal: retain per-input exact producer selection on prepared attempts, expose started-attempt input relations and reuse edges; bounded deterministic graph traversal |
| DQ-42-A02 | Selection/history representation | Resolved proposal: `OutputLocator` selects existing run/stage/commit/output tuple; `SelectedOutput` carries native facts and matched associations; current/history modes explicit |
| DQ-42-A03 | Access matrix and files | Resolved proposal: committed coordinator-local regular files and native shared-publication closures over Unix/HTTPS; client-local copy after resolution; no arbitrary backend promise |
| DQ-42-A04 | Content and limits | Resolved proposal: explicit text/JSON/bytes previews, bounded chunk reads and atomic client materialization, per-item batch outcomes; no server transfer-job lifecycle |
| DQ-42-A05 | Public interface and adapters | Resolved proposal: flat native client methods and capability-versioned routes below; CLI/MCP are thin consumers with identical reference/coverage semantics |

## Detailed Implementation Contract

### Existing Version And Binding Evidence

Source investigation at the evidence revision established:

- `OutputCommitRecord` and `ArtifactFactRecord` in
  `src/loom/pipeline/stores/read_models.py` already retain producer run/stage,
  attempt, output names, exact commit, full refs, and supersession history.
- `ActionResultBinding` retains an original producer commit across run/node reuse.
  Reuse creates no new consuming attempt or output commit. Preserve this behavior.
- `PreparedAttemptRequest` in `src/loom/pipeline/stores/authority.py` retains
  `bound_inputs` and `upstream_commits`, but those maps are not uniform per-input
  lineage. Pending inputs can be absent and prerequisites include control edges.
- `src/loom/queue/_action_result_resolution.py` resolves stronger per-port original
  commit evidence for qualified installed actions, retained in coordinator action
  claims. General stage lineage cannot depend only on that specialized path.
- `StageWorkerRequest.inputs`, stage provenance, and local `inputs.json` retain
  refs without required original run/commit associations. Stage-level files can
  be replaced by a later attempt; they are not an authoritative history.
- `StageAttempt` retains current status/creation time, not a monotonic start
  witness. Both authorities replace granted/running bindings with terminal state;
  deferred lifecycle observations may be lost on crash. Terminal status or audit
  observations cannot establish the required before/after-start distinction.

Consequently, querying current refs is insufficient. Extend the existing attempt
preparation boundary and authority read models; do not reconstruct old inputs from
an upstream stage's current `latest_commit`.

### Exact Output Selectors

Export an inert selector/value pair from `loom.runs`, keeping `ArtifactRef` as the
existing artifact value. These are selectors/views over native identity, not new
allocated artifact IDs:

```python
@dataclass(frozen=True)
class OutputLocator:
    run_uri: str                 # original producer
    stage_name: str
    commit_id: str
    output_name: str

@dataclass(frozen=True)
class SelectedOutput:
    locator: OutputLocator
    artifact: ArtifactRef
    matched_run_uri: str         # may be a reuse consumer
    matched_stage_name: str
```

`select_outputs` accepts explicit run/stage selectors or a bounded query,
declared name/type/metadata filters, and `history="current" | "all"` or an exact
locator. Default current selection reads authority heads and result bindings.
History enumerates `list_output_commits`; it does not scrape artifact directories.
For a reused output, `locator` remains the original producer and the match fields
retain the adopted run/node. A query may return multiple associations for one
locator; unique byte transfer is a separate convenience.

Selections include the authority revision/state source and known verification
evidence. `availability="not_checked"` is the default for metadata-only discovery;
do not probe payloads just to call an artifact available. Explicit selectors with
no matching output produce per-selector `no_matching_output` results, distinct
from `run_not_found`, unavailable authority, and a filtered query with zero matches.

When access is requested, resolve the exact locator again through authorized
authority reads. The caller cannot replace its returned URI and cause arbitrary
filesystem access. Use the committed ref and allowed publication mapping, not
the client-supplied ref contents. An unavailable original producer is reported;
the service does not silently fall back to a newer or same-checksum artifact.

### Retaining Input Version Facts

Extend the prepared-attempt request/receipt and owning stores with an optional
sequence of per-port bindings. `None` means historical evidence absent; an empty
sequence explicitly means zero declared data inputs. Each entry contains the
consumer input name, declared source stage/output, actual original `ArtifactRef`,
and either the exact `OutputLocator` or an explicit external/unresolved source.
Consumers are identified by `(run_uri, stage_name, attempt_id)`; attempt IDs alone
are not globally unique. Input metadata does not enter `ArtifactRef.metadata` or
change semantic fingerprint payloads merely to support this feature.

```python
@dataclass(frozen=True)
class AttemptInputBinding:
    input_name: str
    source_stage_name: str | None
    source_output_name: str | None
    artifact: ArtifactRef
    producer: OutputLocator | None
    source_kind: str             # produced, external, or legacy_unresolved
```

At readiness/preparation, resolve every declared data port, including previously
pending inputs. When an upstream node is an `ActionResultBinding`, take its
unchanged original producer commit. Preserve a separate declared dependency
set; do not turn every `upstream_commits` entry into data consumption.

Persist these bindings with the existing prepared-attempt receipt before grants
or worker handoff. Revalidate selected upstream heads/fences at existing
preparation and assignment boundaries. The binding must correspond to the exact
refs delivered to the worker, even if materialization changes local URI spelling.
Carry origin identity separately from the worker-local path projection.
`stage_attempts.prepare_stage_attempt`, orchestration/readiness preparation,
qualified action binding, remote/shared/container and connected Slurm handoff
must consume the same retained binding contract. Keep existing readiness
generation, admission ownership, retry, and replay checks intact.

Attempt input binding is evidence of assignment, not proof application code opened
every file. The public data edge means "bound to an attempt whose start the
authority acknowledged". A prepared/cancelled-before-start attempt is `bound`,
not `consumed`; declared graph inspection can still show its planned inputs.
A successful output's upstream lineage joins the bindings of that output commit's
producing attempt. Failed started attempts can be inspected explicitly without
inventing produced outputs.

Retain that start evidence on the existing authority attempt record in both
SQLite owners, expose it through `StageAttempt`/historical reads, and preserve it
in versioned protocol and bundle serializers. Logical fields are
`start_confirmed: bool | None` and `start_confirmed_at: str | None`:

- New managed prepared attempts start with `false` and a null time: the upgraded
  owner knows it has not acknowledged start. Creating a grant does not change it.
- In the existing `confirm_execution_started` transaction, after fence/cancel
  validation, the actual granted → running transition sets `true` and the owner's
  UTC acknowledgement time atomically with lifecycle state. The existing supported
  `allocate_stage_attempt` path that directly establishes RUNNING records the same
  evidence in its allocation transaction. This extends existing producers; it
  does not restore a removed execution mode or claim a physical process timestamp.
- Repeated confirmation retains the first timestamp. Terminal success/failure,
  cancellation, recovery closure and restart never erase or reverse a witnessed
  `true`. A delayed confirmation which merely returns after terminalization must
  not convert a known unstarted attempt to started. Existing fence/replay behavior
  still decides whether that request is accepted, rejected or a no-op.
- Historical rows/bundles without the witness decode to `None` and null time,
  including terminal rows. Do not derive a negative from absence or backfill a
  start time from creation/finish time, current heads, or best-effort audit events.

The graph projects `consumed_input` only for confirmed-true attempts. Confirmed
false inputs remain bound; unknown start evidence remains an explicit bound edge
with `start_evidence=unknown` and incomplete-consumption coverage, not an invented
consumed edge or a claim that execution never started. A missing historical input
binding is independently unknown even when start evidence is known. The witness
is retained evidence, not a new execution lifecycle state or event journal.

Store bindings with existing prepared-attempt durable records and expose them
through authority reads for historical attempts. Schema changes cover embedded
SQLite, repository backend, authority protocol/service client/adapters, and
read-model serialization. Legacy exact-key records decode through versioned
migration with `input_bindings=None`; never assign a current head as their old
producer. Bundle/export/import serializers must either preserve the new records
and source identity mappings or explicitly report absent lineage on older bundles.
Do not silently drop version associations while claiming a complete import.

#### Imported Historical Evidence Policy

The maintainer approved historical evidence preservation (Option 1) on
2026-09-25 after investigation found that portable imports create a new
historical-only run and offline authority imports synthesize local commits.
An import is not a new execution of the source attempt.

- Preserve exported input bindings, original run/stage/attempt/commit identities,
  and nullable start witnesses as explicitly source-owned historical evidence.
  The importing run's local identity and any rebased payload locations remain
  separate. Never rewrite an original producer locator into an imported commit
  or infer a mapping from equal bytes, names, paths, or a shared source run URI.
- Retain that evidence through supported bundle export/import in the existing
  bundle/import metadata ownership, and make it inspectable through the existing
  historical metadata/provenance surface. Version serializers as needed; older
  bundles expose absent evidence as unknown, not a known empty input set.
- A source start witness means the exporting authority recorded start; the
  importing coordinator did not itself acknowledge that execution. Synthesized
  offline-import attempts/commits must not acquire original native provenance
  or a local start witness merely because source evidence exists.
- Native authority-backed lineage and imported historical evidence remain
  visibly distinct. Preserving history does not make a historical-only import
  a current authority-backed run. Original references resolve only through
  independently authorized existing scope; unresolved/out-of-scope references
  remain explicit unavailable/restricted boundaries, without credential following
  or hidden-provenance disclosure. Importing another copy never automatically
  substitutes it for the referenced source.
- No source-to-imported attempt/commit registry, automatic graph stitching,
  imported execution authority, or new resume capability is required. A future
  explicit remapping feature is outside this stage.

Validation must round-trip nonempty bindings and known/unknown start evidence,
retain exact original identities alongside a different target run URI and copied
payload paths, distinguish absent older evidence, and show that unavailable
sources or duplicate imports do not invent local execution or remapped edges.

Cross-run inputs declared using native selectors are retained exactly. A project
that opens an arbitrary file internally without a declared input has no Loom
data edge. External inputs remain external unless the caller supplies a native
source selection that the owner verifies; matching a URI/checksum cannot promote
an external reference to trusted production evidence.

### Graph Query

`trace_lineage` accepts a run, stage, attempt, or output locator, direction,
relation kind, history selector, depth and result budget. Edge kinds are
`declared_dependency`, `bound_input`, `consumed_input`, and `reused_output`.
The default result-oriented relation is `consumed_input` plus reuse resolution;
requesting declared relations is explicit. Response nodes/edges use native
identities and references, with observation/coverage information.

Build forward/reverse adjacency from retained bindings and output commits. An
optional derived adjacency index must be rebuildable; authority facts stay the
owner. Breadth-first traversal is a small pure operation over those facts:

```python
frontier = deque([(start, 0)])
visited = set()
while frontier:
    node, depth = frontier.popleft()
    if node.identity in visited:
        continue
    visited.add(node.identity)
    emit_node_if_selected(node)          # filters do not prune traversal
    edges = neighbors(node, direction)
    if depth == max_depth:
        mark_depth_limited_if(edges)
        continue
    for edge in sorted(edges, key=stable_edge_key):
        emit_edge(edge)                  # preserve fan-in/fan-out evidence
        frontier.append((edge.next_node, depth + 1))
```

Use commit and consumer-attempt identity in visited keys, not only stage names.
Do not collapse independent producer commits because their bytes match. Bound
defaults at depth 10, 200 returned nodes/edges per page, and 2,000 visited entities
per request; advertise limits. A deterministic continuation may rewalk from the
same start and skip already emitted stable keys within that bounded graph, rather
than creating a durable traversal job. Above the visit bound return
`traversal_limit` and narrower-query guidance; do not advertise a continuation
that cannot advance. Actual graph changes between pages use the same explicit
live-read qualification as discovery.

### Complete Artifact Access Without A New Transfer Service

Add `describe_artifact(locator)`, `read_artifact_chunk(locator, member, offset,
length)`, `read_artifact(locator, format, limit)`, and a client-side
`fetch_artifacts(selections, destination)` convenience. The first three are native
requests. Fetch orchestrates those bounded reads and local filesystem writes; it
does not create a coordinator job, workflow, or durable query/transfer lifecycle.

Real supported matrix for this stage:

| Artifact/access path | Resolution and declaration | Required verification |
| --- | --- | --- |
| Committed regular file retained below the configured run artifact store | Authority locator -> committed ref -> existing contained local artifact path; one-member declaration | Record size and existing checksum evidence; verify supplied checksum; explicitly label absent original checksum |
| Native shared publication | `SHARED_PUBLICATION` binding -> protected coordinator `shared_roots` mapping -> verified publication receipt | Use receipt's complete `members`, size/digests, primary/output mapping, and receipt digest |
| Client without producer mounts | Same coordinator-resolved artifacts read in bounded chunks over Unix or authenticated HTTPS | Full client-side member verification and preserved relative layout |
| Client has an admitted local mapping | Same exact locator/declaration, optional existing copy materializer | Same selection/integrity outcome as streamed access; no arbitrary URI shortcut |
| External/cloud URI with no installed supported reader | Metadata can be selected | Explicit `unsupported_backend`; no invented S3/HTTP/W&B adapter |
| Multi-file artifact without a native complete-file declaration | No schema inference from application manifest | Explicit `unsupported_closure`; producer must declare/publish supported files |

For shared publications reuse `shared_artifacts.binding`, receipt, containment,
and inventory semantics. The current receipt declares a publication tree, which
may contain several output primaries. Fetch the entire declared tree when that is
the existing closure granularity and identify its chosen primary. Do not invent a
smaller file subset by parsing a domain manifest. Per-output closure minimization
is deferred unless a supported declaration already supplies it.

`describe_artifact` returns the selected locator, declaration identity/digest,
primary relative member, total bytes, and paged members (path, size, known digest).
Use the original shared receipt digest; a single-file declaration is derived from
the selected ref and checked file evidence. A request includes that declaration
identity on subsequent chunk reads to detect changes. Unchecksummed legacy files
must carry `verification=unverified_original`; a transfer-time digest can prove
consistent transfer but cannot prove original publication content.

Server chunk reads reauthorize the exact selected run/producer and allowed
publication on each call. Member paths must belong to the declaration and obey
existing containment/regular-file rules; a caller cannot supply a source path,
URI, codec import, or arbitrary symlink target. Share generic byte-range/file
helpers with existing regular-file transfer only when semantics match. Do not
reuse an agent assignment authorization or session for a human client fetch.

Use chunks of at most 256 KiB raw bytes, base64-encoded in the existing plain JSON
control envelope (below its 1 MiB response limit). Requests remain below 64 KiB.
Repeated `(locator, declaration, member, offset, length)` reads are side-effect
free and can retry after an uncertain reply. Full-member integrity is checked
before marking completion. Concurrent mutation/deletion can yield mismatch or
unavailable; no attempt to substitute a new current output is allowed.

### Client Materialization And Content Preview

For each unique selected declaration, create a caller-owned temporary directory
under the explicit destination, download declared members, verify their sizes and
available digests, preserve relative layout, then rename into a nonexisting final
directory. Default existing-target behavior is `destination_exists`; no overwrite
or recursive removal is authorized implicitly. Clean only temporary files created
by that fetch on failure, or return their exact partial location if cleanup fails.
Durable resume of partial directories across client restart is deferred; retrying
individual chunk calls is supported.

```python
declaration = client.describe_artifact(selection.locator)
with temporary_output(destination) as pending:
    for member in declaration.iter_members():
        with pending.open_member(member.path) as sink:
            for chunk in client.iter_artifact_chunks(selection.locator, declaration, member):
                sink.write(chunk.data)
        verify_member(pending.path(member.path), member)
    local_result = pending.publish_if_absent()
```

The batch helper streams outcomes in input order and retains every association,
including reused outputs whose bytes were fetched once. Native selection returns
no-output outcomes; fetch returns `available`, `unavailable`, `unsupported_backend`,
`unsupported_closure`, `integrity_failed`, `destination_exists`, or `failed` as
appropriate. Include verification scope and exact locator in every result. A
batch-level `complete` means every selected item was processed, not that every
fetch succeeded; report success/failure counts separately.

Generic preview uses caller-selected `format="text" | "json" | "bytes"` and a
maximum raw content limit of 256 KiB. Text is strict UTF-8; a bounded prefix is
labelled truncated and does not split a UTF-8 character. JSON requires the whole
selected member within the limit and valid JSON; oversize returns `too_large`,
never a partly parsed JSON object. Bytes are base64. Default preview is the
declared primary member. No automatic `codec_key` execution, pickle loading,
application `_target_`, HTML execution, or metric interpretation occurs.

MCP fetch destinations refer to the MCP client process's filesystem, not the
assistant user's laptop. Return that location context explicitly. MCP can return
bounded content instead when the assistant cannot access the materialized path.

### Client, CLI, And MCP Integration

Advertise `output-query-v1`, `lineage-query-v1`, and `artifact-read-v1` only after
their native routes exist. Use `CoordinatorClient` flat methods; earlier
`client.outputs`/`client.lineage` sketches are behavioral examples, not required
facade classes. Add `loom runs outputs`, `loom runs lineage`, and
`loom artifacts describe/read/fetch` over the same request objects, with JSON
input/output modes. Existing commands keep their contracts.

MCP adds `loom_select_outputs`, `loom_trace_lineage`, `loom_describe_artifact`,
`loom_read_artifact`, and `loom_fetch_artifacts`. The fetch tool has a write hint
because it writes its local destination; server query/read routes remain read-only.
CLIENT and QUERY roles share the authorized read paths; QUERY cannot annotate or
control lifecycle. Metadata queries never fetch bytes, and file access never
implicitly starts/stops workers or services. Preserve expected-coordinator
identity checks, native error unions, and response budgets across both transports.

## Validation Obligations

| ID | Reachable producer and consequence | Minimal discriminating check |
| --- | --- | --- |
| VAL-42-A01 | Pipeline has declared/unstarted, prepared, and start-confirmed paths which later fail or cancel | Correct relation kinds and multi-hop paths; distinguish depth-limit from no match; both authorities retain before/after-start evidence after terminalization/restart even without audit observations; legacy absence is unknown |
| VAL-42-A02 | Another run consumes a published output while an unrelated run has the same tags or bytes | Include the recorded consumer only, retain original producer/reuse association, and expose unknown external provenance |
| VAL-42-A03 | Producer publishes a successor after a consumer used/selected the older commit | Default current selection and explicit history differ; downstream/read results remain bound to the actual selected version |
| VAL-42-A04 | Application publishes a manifest plus payload files; client lacks the producer's mount | Fetch complete declared files with preserved layout/integrity through supported access, or return precise unsupported/unavailable outcomes |
| VAL-42-A05 | Text/JSON/binary output exceeds presentation limits or has an application-specific type | Bound content without falsely decoding truncation; return appropriate handles; never execute recorded targets to preview data |
| VAL-42-A06 | Mixed batch includes missing output, inaccessible/corrupt bytes, successful earlier output of a failed run, and reused artifact | Distinct per-item outcomes, truthful completeness, preserved associations, and no substitution or silent drops |
| VAL-42-A07 | Python, CLI, and MCP consume the same native fixture | Equivalent filters, identities, relations, selections, write effects, and error/coverage meanings; transport formatting may differ |
| VAL-42-A08 | Agent performs the accepted multi-step workflow with pages and partial results | Preserve identities/warnings across calls, fetch only explicit selections, and annotate only explicitly selected source runs with successful retrieval |

Reuse artifact identity/materialization/output-commit tests and native client/MCP
integration fixtures. Add a small generic multi-run synthetic artifact graph and
a second application vocabulary. No actual physiological data or invoice data is
needed. A fake backend demonstrates failure semantics but is not proof of an
unimplemented real transfer path. The chosen supported transport/access matrix
must have executable acceptance evidence; optional unqualified physical/cloud
paths stay explicitly outside its claim.
