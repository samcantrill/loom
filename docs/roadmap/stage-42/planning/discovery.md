# Discovery: Queries, Native Facts, And Coverage

Card ID: `PC-42-discovery`.
Status: detailed implementation design independently reviewed and approved;
implementation pending.
Planning manifest: [Stage 42](../planning.md).
Evidence revision: `220358ed26392f30bb2f36bf09d547607a57d442`.
Dependencies: [run context](run-context.md).

Owned IDs: `FR-42-Q01`–`Q07`, `EX-42-Q01`–`Q04`, `VAL-42-Q01`–`Q06`,
`DQ-42-Q01`–`Q04`.

## Intent And Existing Owners

People and agents can find submitted work without guessing storage paths or
reading every configuration/artifact. Queries combine caller organization with
facts Loom already owns and identify the scope and limitations of the answer.

| Evidence | Existing behavior and extension point |
| --- | --- |
| `src/loom/runs/catalog.py::RunCatalog` | Refresh-on-read listing, scanning, rebuilding, and persisted-metadata comparison are existing surfaces |
| `src/loom/runs/models.py::RunFilterKind` | Exact-match status, tag, fingerprint, commit, stage status, artifact identity/checksum, executor, and backend filters exist |
| `src/loom/runs/_scan.py` and `_extract.py` | Authority-backed summaries, state-source evidence, freshness, and warnings already distinguish unavailable evidence |
| `src/loom/queue/_coordinator_client.py` and `src/loom/mcp/_server.py` | Native job/operation/run inspection supplies existing client and transport boundaries; MCP does not yet provide this full catalog query contract |
| `docs/features/run-catalog.md` | Time ranges, pagination, sorting, and a general query language are deferred at the evidence base; this stage accepts bounded structured query behavior |
| `tests/contracts/test_run_catalog_contract.py`, `tests/integration/pipeline/test_run_catalog_current_list.py` | Existing current-read and catalog-contract tests provide regression owners |

The catalog remains derived. Adding coordinator-backed discovery does not create
a new tracking authority or a separate hosted catalog server. Query indexes may
be rebuilt from owning facts; their shape is an implementation decision.

## Functional Requirements

| ID | Required behavior | Validation |
| --- | --- | --- |
| FR-42-Q01 | Search explicitly selected deployment/collection scope through native client behavior without client-side directory guessing, implicit service startup, or hidden cross-deployment search | VAL-42-Q01 |
| FR-42-Q02 | Filter runs and native job views using existing identifiers/associations, lifecycle fields, timestamps, and supported captured provenance; preserve each entity's meaning | VAL-42-Q02 |
| FR-42-Q03 | Combine caller tags/typed metadata with native facts using supported conjunction, alternatives, exclusion, equality, membership, existence, and type-appropriate comparisons | VAL-42-Q03 |
| FR-42-Q04 | Discover valid native query fields/operators and existing tag keys/values in scope; arbitrary application tag assignment needs no vocabulary registration | VAL-42-Q03 |
| FR-42-Q05 | Search original/current descriptions and later note text while identifying which context matched | VAL-42-Q04 |
| FR-42-Q06 | Return bounded projected records with deterministic ordering and pagination/continuation, plus explicit scope, observation context, coverage warnings, and truncation | VAL-42-Q05 |
| FR-42-Q07 | Keep metadata discovery separate from payload reads; incomplete/unavailable evidence must not be reported as an exhaustive empty result | VAL-42-Q06 |

## Search Scope And Results

The caller selects the native deployment or a supported run collection. Responses
identify that selection and the observed coordinator/authority context where
applicable. A query does not search unrelated deployments, start missing services,
scan arbitrary client directories, or discover credentials implicitly.

Run discovery returns run identities and requested summaries. A job view returns
native jobs/admissions and their related `run_uri`, stage, and operational
identities as applicable; it does not pretend all job IDs are interchangeable.
Use existing native entity names when selecting the actual public interface.

Responses provide a limit-bounded page, projected fields, deterministic ordering
with an identity tie-break, and a continuation when more results may exist. The
detailed design below selects stateless live keyset cursors. It does not promise
a global frozen snapshot or allocate a persistent query database.

Coverage and paging are different:

- More matches than the page limit: continuation is available; consume further
  pages before claiming to have processed all matching runs.
- Some authority/records cannot be inspected: response reports that coverage
  limitation even if no matches were returned.
- Search completed with no matches in the declared scope: a genuine empty result.
- Invalid/unsupported field/operator/query: a request error, not an empty result.

Warnings identify affected records or scope where known, following current safe
presentation rules. Result projections must not expose credentials or bypass
existing redaction/access policy. This requirement extends the existing trust
boundary; it does not introduce a new general authorization system.

## Field And Operator Semantics

The names below express concepts; exact field representation and initial inventory
are specified in the detailed design below.

| Field family | Examples | Semantics |
| --- | --- | --- |
| Identity | `run_uri`, stage name, native job/attempt/operation identifiers | Exact typed identity and recorded associations; avoid ambiguous unqualified `id` |
| Lifecycle | Run/stage status, native admission/job state | Keep independent state owners/axes visible |
| Time | Submission received/accepted, run/stage started/finished | Name the event; use explicit timezone-aware bounds; creation is not automatically submission |
| Provenance | Repository, commit, recorded dirty state, config/pipeline fingerprint, executor/backend | Query captured public facts only; absence stays explicit |
| Tags | `tags.study`, `tags.model`, `tags.customer` | Application strings; same valid operations for every application vocabulary |
| Structured metadata | `metadata.revision`, `metadata.temporal_kernel_size` | Retain JSON types; use comparisons compatible with actual values |
| Human context | Original submission reason, current description, note text | Search intended text and identify its source; no inferred motivation |
| Output metadata | Declared output name/type, artifact identity/checksum, producer metadata | Read references/projections without decoding domain payloads |

Supported boolean composition should express all/any/exclusion without forcing
clients to concatenate query-language strings. Surface shape may be typed
objects, inert mappings, or CLI translation over one native representation.
No caller expression evaluation, arbitrary SQL, config imports, or field-type
inference from application names is required.

For supported typed comparisons:

- Number `3`, string `"3"`, boolean `true`, missing, and explicit null remain
  distinguishable. Unsupported or ambiguous combinations cannot silently coerce.
- Missing/null and exclusion truth rules are fixed in the detailed design below.
  Positive equality cannot match a missing field. Callers need an explicit
  existence/missing operation.
- Semantic-version ordering requires an explicit comparator/type convention;
  a field named `version` is not automatically semantic version data. A numeric
  revision can use ordinary numeric comparison.
- Git commit equality is useful. Commit string ordering does not establish time
  or ancestry. Git graph traversal and fetching repositories are outside the
  accepted query baseline.
- Tag keys may contain punctuation; the field-selector design must distinguish
  a literal tag key from a nested structured-metadata path.

Supported native field/operator discovery and observed tag vocabulary serve
different purposes. A field schema describes valid Loom query capabilities;
tag discovery reports keys/values that callers have actually assigned. Optional
application metadata schemas are not a prerequisite for assigning tags.

## Examples

All snippets use proposed pseudocode. Helpers such as `all_of`, `eq`, and
`collect_pages` are illustrative, not existing imports. A helper which collects
pages must retain coverage warnings; it must not discard them to return a list.

### EX-42-Q01: What Did We Launch Yesterday, And Why?

```python
page = client.search_submissions(SubmissionQuery(
    scope=ManagedScope(),
    where=all_of(
        eq("submission.context.tags.study", "temporal-kernel-ablation"),
        gte("submission.submitted_at", "2026-09-23T00:00:00Z"),
        lt("submission.submitted_at", "2026-09-24T00:00:00Z"),
    ),
    select=[
        "operation_id", "run_uri", "run.status", "submission.submitted_at",
        "submission.submitted_by", "submission.description", "tags",
    ],
    order_by=["submission.submitted_at DESC", "operation_id ASC"],
    limit=50,
))
```

Sample human view, with shortened URIs used only for display:

| Run | Submitted UTC | Status | Original reason |
| --- | --- | --- | --- |
| run C | 15:20 | RUNNING | Check the longer kernel with another seed |
| run B | 12:10 | FAILED | Evaluate the longer kernel on the target dataset |
| run A | 09:05 | SUCCEEDED | Establish the baseline |

This is a behavioral sketch using the helper notation from the original intent
examples; the detailed field/tree encoding below is authoritative. Each row is a
submission, not necessarily a unique run: repeated submissions may share a run,
and unbound/failed preparations have an operation identity without a run URI.
The table shows the bound subset and its associated run lifecycle status.

Machine records retain full `run_uri` values and the search scope. An absent
reason is shown as absent. `finished_at` would answer a different question.
Relative language such as "yesterday" is resolved by the caller using a chosen
timezone; the request carries explicit instants. This example uses UTC and a
half-open interval; it does not silently assume the caller's local day.

### EX-42-Q02: Combine Application Labels And Typed Metadata

```python
query = all_of(
    eq("tags.dataset", "PURE"),
    eq("tags.model", "PhysNet"),
    gte("metadata.revision", 3),
    eq("status", "SUCCEEDED"),
)
matching = collect_pages(client.runs.search(where=query, limit=50))
```

Expected: numeric revision filtering and exact labels are both honored. A run
without revision metadata does not match the positive numeric predicate. A
string revision requires the explicitly supported string/version rule, not
automatic conversion. The completed collection retains nonfatal warnings and
does not claim full scope coverage if the native service could not inspect it.

### EX-42-Q03: Recorded Code Provenance

```python
page = client.runs.search(
    where=all_of(
        eq("provenance.git.repository", repository_identity),
        eq("provenance.git.commit", exact_commit),
    ),
    limit=50,
)
```

Expected: query recorded provenance in the declared repository context. A
user-supplied `metadata.commit` is a different field. No repository checkout or
network Git operation occurs to fill missing facts. If code from a dirty tree
was captured, inspection preserves that recorded qualification.

### EX-42-Q04: Discover Labels And Search Notes

```python
keys = client.runs.tag_keys()
studies = client.runs.tag_values("study")
fields = client.runs.query_fields()

page = client.runs.search(
    where=all_of(
        eq("tags.study", selected_study),
        contains_text("notes.text", "target-dataset evaluation"),
    ),
    limit=50,
)
```

Expected: label discovery uses current scoped data, field discovery explains
supported operators, and text results indicate the matching note rather than
misrepresenting it as original submission intent. The detailed design below
selects literal case-folded substring search and bounded vocabulary pages.

## Proposed Ownership And Complexity

Extend existing catalog/read-model extraction and native coordinator query routes.
Preserve authority/store ownership and distinguish local materialized evidence
from live authoritative state. Clients should not duplicate filesystem scanning
and query logic separately for Python, CLI, and MCP.

Time filters, typed metadata predicates, deterministic ordering, bounded pages,
and text/vocabulary discovery are justified by the accepted workflows. They do
not justify an arbitrary query language, remote global search service, semantic
index, or application metrics database. A field/operation schema serves current
client construction; it is not a registry of application concepts.

## Design Decision Disposition

| ID | Decision required before implementation readiness | Direction and constraint |
| --- | --- | --- |
| DQ-42-Q01 | Field inventory, scope, query serialization | Resolved proposal: explicit field segments and finite predicate tree; managed scope and configured run-store collection scope; reuse native identities |
| DQ-42-Q02 | Types, missing/null, text, versions | Resolved proposal: three-valued predicates, explicit presence tests, case-sensitive equality, case-folded literal text search, explicit strict SemVer operators |
| DQ-42-Q03 | Pages and derived projections | Resolved proposal: bounded live keyset pages with immutable ordering keys, explicit observation/coverage, no durable query snapshots |
| DQ-42-Q04 | Capture and older records | Resolved proposal: query recorded typed facts only; submission receipt time is distinct from creation; unavailable historical fields remain unknown |

## Detailed Implementation Contract

### One Native Query Representation

Add inert public query values and pure predicate evaluation in `loom.runs`, with
coordinator data acquisition in `loom.queue`. Keep CLI/MCP as translators to that
one representation. The existing `RunCatalog.list(RunFilter...)` remains valid;
adapt its supported exact filters to the same predicate semantics rather than
creating conflicting search rules.

Use explicit field segments rather than parsing arbitrary dotted strings:

```python
query = RunQuery(
    scope=ManagedScope(),
    where=AllOf((
        Compare(Field("tags", ("dataset",)), "eq", "PURE"),
        Compare(Field("tags", ("model",)), "eq", "PhysNet"),
        Compare(Field("metadata", ("revision",)), "gte", 3),
    )),
    order_by=(Order("submitted_at", descending=True), Order("run_uri")),
    limit=50,
)
page = client.search_runs(query)
```

For a tag literally named `dataset.version`, its path is one segment. For nested
metadata `{"dataset": {"version": 3}}`, its path has two segments. No `eval`, SQL
fragment, import target, or application config resolver can occur in a query.

Representative wire shape (`schema_version=1` is for this new request family):

```json
{
  "schema_version": 1,
  "scope": {"kind": "managed"},
  "where": {
    "kind": "all",
    "terms": [
      {"kind": "compare", "field": {"source": "tags", "path": ["study"]}, "op": "eq", "value": "kernel-study"},
      {"kind": "compare", "field": {"source": "native", "path": ["submitted_at"]}, "op": "gte", "value": "2026-09-23T00:00:00Z"}
    ]
  },
  "order_by": [{"field": "submitted_at", "descending": true}],
  "limit": 50,
  "cursor": null
}
```

The server appends an ascending identity tie-break when omitted. Validate the
request once at the public/wire boundary using owning query models. Internal
evaluators consume the checked tree; they do not repeatedly revalidate every
node. SQL pushdown is a later private optimization only if equivalent to the
authoritative evaluator and tested against it.

### Scopes, Entities, And Public Methods

| Method | Candidate owner and result identity |
| --- | --- |
| `search_runs(query)` | Authorized run snapshots; one result per `run_uri` |
| `search_submissions(query)` | Existing coordinator operation journal; one result per coordinator/operation ID, including requests not yet bound to a run |
| `search_jobs(query)` | Existing admission/job projections; preserve admission/queue/run/stage/assignment fields rather than inventing a universal job ID |
| `query_fields(entity)` | Finite native field/operator/sort schema plus available sources/limits |
| `tag_keys(scope, ...)`, `tag_values(scope, key, ...)` | Distinct current annotation vocabulary with bounded pages and normal coverage |

Native managed scope is the connected coordinator's accessible admissions and
associated runs/submission operations. Collection scope explicitly selects
`{"kind":"collection","name":"run_store"}`, the configured run-store root;
remote callers cannot submit arbitrary server filesystem paths. Expose only this
existing configured collection initially. `RunCatalog.search(query)` can reuse
the pure query/evaluation path for an explicitly opened local collection, with
the same existing authority requirements and state-source warnings. It does not
provide remote mutation or fabricate current lifecycle state when authority is
absent. New multi-root registration/federation is deferred.

Run submissions can be many-to-one under reconciliation. A recent-submission
query must include all launch descriptions and show their shared `run_uri` once
known. A run query's `submitted_at` and submission context refer to the initializing
submission; `created_at` remains the existing run creation fact. Job/submission
fields not meaningful for a collection-only record are unavailable, not invented.

Initial native field inventory: `run_uri`; run status; created/initially submitted/
started/finished timestamps; initializer operation/principal; config and pipeline
fingerprints; recorded Git repository/commit/dirty flag; executor/backend; and
explicit `any_stage` predicates over one stage's name/status/attempt and captured
timestamps. Submission/job queries add their actual native IDs/state/time fields.
Do not flatten several stages or submissions and accidentally satisfy two
conditions from different entities. `any_stage(AllOf(...))` evaluates all child
predicates against the same stage. Output predicates use the output query owner.

Caller sources are current `tags`, typed `metadata`, original `submission.context`,
current `description`, and `notes`. `notes` text search is existential and returns
bounded matching note IDs/excerpts. Stage/artifact metadata remains in that
entity's output/lineage views. Read field capabilities from the server, not from
an unrestricted schema introspection of its private database.

### Exact Predicate Rules

The expression nodes are `all`, `any`, `not`, `compare`, `exists`, `missing`,
`is_null`, `contains_text`, and the scoped `any_stage` form. Empty `all` is true;
empty `any` is false. Restrict comparisons to JSON scalars; collection membership
uses `in` with a scalar candidate and an explicit finite operand list.

Comparison results are true, false, or unknown. `not unknown` stays unknown;
`all(false, unknown)` is false; `any(true, unknown)` is true. Only true selects a
record. A known absent key is distinguishable from a source which could not be
observed. `missing` matches the former; the latter is unknown and contributes a
coverage warning. Explicit null is a present value and matches `is_null`.

Equality preserves JSON types: boolean is not a number; string `"3"` is not
number `3`. Finite integer/float numeric values share numeric ordering. Ordering
a string/null/bool against a numeric operand is unknown, with an aggregate
type-mismatch diagnostic, not coercion. Invalid query operand/operator combinations
are rejected before data acquisition. Known mixed application data can therefore
be searched without failing the entire collection or silently retyping values.

String equality is exact and case-sensitive. `contains_text` is a literal Unicode
case-folded substring operation; no regex or semantic search. It returns the
matching context source and bounded excerpts. Native timestamps normalize
timezone-aware RFC3339 strings to UTC; comparisons use instants. Naive dates are
invalid. A half-open range uses `gte(start)` and `lt(end)`.

Explicit `semver_eq/lt/lte/gt/gte` operators apply strict SemVer 2.0.0 ordering to
strings: numeric core components, release greater than prerelease, numeric
prerelease identifiers ordered numerically, build metadata ignored. An invalid
operand is an invalid request; a non-version stored string produces unknown.
Use a small pure tested comparator, not PEP 440 ordering or a heavyweight query
dependency. No field becomes version-typed because it is named `version`.

### Acquisition, Pages, And Coverage

Native dispatch obtains a bounded candidate page from coordinator admissions or
the existing derived run catalog, then reads owning facts outside coordinator
write transactions. Join context, state, safe provenance, and requested metadata
into detached query records. Avoid holding scheduling/SQLite write locks while
calling authority or reading files. Use the existing catalog/state-source and
freshness machinery; do not make the query index a new authority.

Initial sort keys are immutable `run_uri`, recorded `created_at`, initializing
`submitted_at`, or native submission/job identity/accepted time as applicable.
Missing time values sort last. Arbitrary mutable metadata/metric ranking is not
an initial sort option; clients can explicitly collect results and sort locally.
Use a stateless keyset continuation containing schema version, scope/coordinator
identity, canonical query digest, ordering, and last examined ordering tuple.
The token grants no access: reauthorize scope on every request and validate all
token fields. A different query/scope returns `invalid_cursor`.

Consistency is explicitly `live_keyset`: each page observes current facts. New
matches whose immutable sort key is behind the cursor are not retroactively
inserted; changed filter membership can differ across pages. Response observation
timestamps/state-source revisions qualify that result. No point-in-time snapshot
is promised. A client needing a reproducible analysis retains the returned exact
run/output selections; that list freezes the selection, not a claim of exhaustive
membership at an earlier instant.

Proposed defaults: 50 results per page, at most 200, at most 64 predicate nodes and
depth 8, 100 values per `in`, and at most 500 candidates examined per request.
The maintainer clarified on 2026-09-25 that this candidate budget limits detailed
run/authority acquisition and predicate evaluation. Collection metadata enumeration
needed to establish immutable ordering may scan more than 500 entries; it must
not read artifact payloads or refresh every run's authority as part of that scan.
The existing request deadline still applies. This is not a bound on total metadata
filesystem reads or total collection-scan cost, and does not require a new
incrementally maintained index. Tests distinguish metadata enumeration from
detailed candidate acquisition and verify the latter remains bounded.
Existing native deadline and 1 MiB response limits still apply. Cursor tracks the
last examined candidate, so a page can contain no matches and still have more
candidates. Bound projected text and explicitly mark excerpts/truncation; a
single oversize record yields a diagnostic/reference rather than dropping it.

```python
def search_page(request, candidates):
    items, warnings = [], []
    for candidate in candidates.after(request.cursor):
        record = acquire_owned_facts(candidate, request.select)
        warnings.extend(record.coverage_warnings)
        if evaluate(request.where, record) is TRUE:
            items.append(project(record, request.select))
        if page_or_scan_budget_reached(items):
            return page(items, warnings, cursor_after(candidate), consistency="live_keyset")
    return page(items, warnings, None, consistency="live_keyset")
```

This sketch omits byte limits and error plumbing. It shows why no-match and
end-of-search are different. A `collect_pages` iterator carries warnings and a
coverage summary through to its final result rather than returning a bare list.
When acquiring immutable ordering keys is itself unavailable, report incomplete
coverage; do not position unknown values as if their order were authoritative.

### Routes And Compatibility

Advertise `run-query-v1`. Add pure request/result codecs, native query handlers,
`CoordinatorClient` methods, `loom runs search/submissions/jobs/fields/tags`, and
thin MCP search/schema/vocabulary tools. Both Unix CLIENT access and authenticated
HTTPS CLIENT/QUERY read paths call the same service. QUERY must not gain annotation
or lifecycle mutation rights. Existing job/inspection commands remain supported.

The old local exact-filter catalog API retains its behavior and warning model.
Do not silently apply a new live-page contract to an old unpaginated return type.
New methods return a separate explicit page envelope. Queries on historical
records keep missing original times/authors/version associations visible.

## Validation Obligations

| ID | Reachable producer and consequence | Minimal discriminating check |
| --- | --- | --- |
| VAL-42-Q01 | A caller selects one coordinator/collection while another exists | Results stay in scope; disconnected service reports failure/coverage and never starts services or searches another deployment |
| VAL-42-Q02 | A retry/job association and a run with different submitted/finished times | Identity queries return correct entity links; time boundaries include/exclude the intended event; recorded Git facts are distinct from caller metadata |
| VAL-42-Q03 | Two applications supply different labels and mixed typed values | Vocabulary discovery is generic; boolean composition/type comparisons obey the declared rules; missing, null, numeric/string/bool, and unsupported query behavior are distinguishable |
| VAL-42-Q04 | Original reason differs from edited description and later note | Search returns the right matching text source and never rewrites launch motivation |
| VAL-42-Q05 | More results than a page and a run changes between requests | Stable ordering and continuation follow the selected consistency contract; all-page helper preserves coverage warnings |
| VAL-42-Q06 | Authority unavailable, a partial record, and an actually empty scope | Three states have different outcomes; catalog reads do not download payloads or invoke recorded application targets |

Extend existing run-catalog contracts/integration tests and native route/client
tests at the actual boundary. Selected fake/native local fixtures can establish
query behavior; physical GPUs, datasets, containers, and cloud services are not
prerequisites. New storage/cursor semantics or changes to shared native response
unions trigger the affected wider suites.
