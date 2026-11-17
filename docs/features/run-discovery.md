# Native run discovery

Native configuration identity uses the retained composition manifest's
`artifact_safe_config` fingerprint record. Git identity uses its current `commit`
member; old flat aliases do not supply missing facts. Whole-pipeline fingerprint
fields are unsupported because native execution does not produce that identity.
Run times come from authority, with unknown start evidence distinct from a known
run that has never started. Stage start requires a confirmed execution witness;
stage finish requires its own successful current-attempt commit. Preparation,
revision and reused-output timestamps do not stand in for execution times.

Tag vocabulary pages report distinct observations within each page, not a global
registry or snapshot. Keys or values can repeat across pages. Each page acquires
at most 500 detailed run records, including when no requested values occur.
Large per-run vocabularies continue by re-reading current annotations; cursor
contents never replace owning annotation facts. Union observations while
retaining every page's coverage and warnings with:

```python
from loom.runs import collect_vocabulary

observations = collect_vocabulary(lambda cursor: client.tag_keys(cursor=cursor))
print(observations.values, observations.complete, observations.warnings)
```

`CoordinatorClient` queries an existing coordinator without starting services or
loading application targets. `search_runs`, `search_submissions` and `search_jobs`
return `QueryPage` values. Run rows retain `run_uri`; submission rows retain
`operation_id`, including failed and unbound requests; job rows retain
`admission_id` and the admission's queue, run and structured owner associations.
Several submissions can refer to one run. Assignment collections preserve their
native identities and do not select an arbitrary latest assignment.
Admission/queue IDs are scalar predicates; historical assignment arrays are
returned as associations and are not implicitly scalar-searchable. `AnyStage`
correlates current stage name, status, attempt and captured time predicates.

```python
from loom.runs import AllOf, Compare, Field, RunQuery, collect_pages

query = RunQuery(where=AllOf((
    Compare(Field("tags", ("dataset.version",)), "eq", "v3"),
    Compare(Field("metadata", ("revision",)), "gte", 3),
)))
selected = collect_pages(client.search_runs, query)
# Retain selected.warnings and selected.complete with the selected items.
```

The literal tag `dataset.version` has one path segment. Nested structured
metadata uses separate segments, such as `Field("metadata", ("dataset", "version"))`.
Another application can use `customer`, `region` or any other vocabulary with
the same operators; no registration or domain schema is needed.

`query_fields("runs")` returns supported fields, operators, immutable sort keys
and limits. `tags` and `metadata` refer to current authority annotations.
`submission.context` refers to the initializing original context for run rows
and that exact original request for submission rows. Editing current
`description` never edits original motivation.

```python
from loom.runs import ContainsText, Order, SubmissionQuery

launches = client.search_submissions(SubmissionQuery(
    where=AllOf((
        Compare(Field("native", ("submitted_at",)), "gte", "2026-09-23T00:00:00Z"),
        Compare(Field("native", ("submitted_at",)), "lt", "2026-09-24T00:00:00Z"),
    )),
    order_by=(Order("submitted_at", descending=True),),
    select=(Field("submission.context", ("description",)),),
))
observations = client.search_runs(RunQuery(
    where=ContainsText(Field("notes", ("text",)), "follow-up"),
))
```

Notes are searched existentially, returning bounded matching IDs and excerpts.
Text search uses literal Unicode case folding, without regex or semantic search.
Native `git_repository`, `git_commit` and `git_dirty` query captured provenance.
For example, `Compare(Field("native", ("git_commit",)), "eq", exact_commit)`
does not query caller `metadata.commit`. No Git network requests, application
imports, artifact downloads or payload decoding occur.

Equality preserves JSON types: `true`, `1` and `"1"` differ; finite integers and
floats share numeric ordering. Ordinary ordering requires numeric operands;
timestamp fields require timezone-aware RFC3339 instants and compare in UTC.
Explicit `semver_eq/lt/lte/gt/gte` use SemVer 2.0.0 precedence, including numeric
prerelease ordering and ignoring build metadata. Invalid operands fail before
acquisition; incompatible stored values yield unknown and aggregate diagnostics.

Predicates include `AllOf`, `AnyOf`, `Not`, `Compare`, `Exists`, `Missing`,
`IsNull`, `ContainsText` and `AnyStage`. Same-stage conjunctions stay correlated.
Unknown remains unknown under negation; only true selects a record. `Missing`
matches a known absent key, while unavailable sources stay unknown. Explicit
null is present. Historical uncaptured fields stay unavailable; preparation or
revision timestamps never substitute for start or finish events.

Managed scope contains this coordinator's admissions and associated runs and
operations. `CollectionScope()` selects only its configured `run_store`; remote
requests cannot name paths. `RunCatalog.open(path).search` accepts that collection
scope for a locally opened collection. Missing authority remains a warning and
never promotes stale lifecycle state to current truth. Existing unpaginated
catalog `list` behavior and envelopes are unchanged.

An in-process viewer with an already selected protected deployment can pass
`RunCatalog.open(path).search(query, authority_factory=selected_factory)` to use
that deployment's per-run authority. Candidate membership remains restricted to
the opened collection. Omitting the factory preserves local authority discovery;
neither path promotes persisted lifecycle summaries into current status.

Pages use `live_keyset`, not snapshot consistency. New or newly matching records
behind a cursor are not inserted retroactively. Default limit is 50, maximum
200; at most 500 detailed candidates are acquired/evaluated per page. Collection
membership and creation-time ordering use the registered discovery index, with
at most 501 candidate rows fetched before detailed acquisition. Limits are
64 predicate nodes, depth 8 and 100 `in` operands. Missing sort times are last
with incomplete coverage. Cursors bind query, order, scope and coordinator;
they do not authorize access.

Managed job and submission queries select at most 501 journal candidates in
SQLite using the public keyset (500 candidates plus one continuation witness).
Default run-identity ordering also pages distinct run URIs before authority
acquisition; submission-time ordering pages submission facts with its private
operation-ID continuation key, retaining initializer selection at acquisition. Supported journal string equality/`in` predicates narrow candidates;
full typed evaluation still owns matching. Mixed predicates never discard an
unsupported OR branch. Original submission context is read by exact operation
identity for the selected run rather than loading the entire submission history.
These bounds limit transferred rows and detailed acquisition, not all SQLite
sorting/filtering work. Creation-time ordering joins registered immutable facts
before paging; collection queries do not enumerate directories or read every
run document. Exact admission observations use `CoordinatorClient.admission(admission_id)`
and need no discovery query.

### Registering and refreshing collection membership

Loom run-document publication automatically registers run identity and creation
time in `.loom_catalog/discovery.sqlite`. This derived index does not store live
execution status or replace run authority. A registration intent is committed
before publishing `run.json`, then acknowledged afterward; an interrupted write
can leave an indexed but unavailable run, which must not be treated as successful
execution. Ordinary creation and metadata updates need no manual registration.

After upgrading an existing collection, or copying/deleting run directories
outside Loom, refresh explicitly:

```sh
loom runs index /path/to/runs --discovery-only
```

The Python equivalent is `RunCatalog.open(path).rebuild(discovery_only=True)`.
This explicit operation scans run documents, preserves concurrent registrations,
and removes missing completed registrations. Missing pending publications remain
visible rather than racing a writer that may still finish. Unreadable documents
produce warnings and incomplete index coverage. Newly copied documents must use
the correct destination run identity, as required by the run-store format.
Unregistered directories without `run.json` are auxiliary storage and are
ignored, including colocated work and artifact directories. A registered run
whose directory remains but whose document is missing still reports incomplete
coverage, as does an unregistered directory containing an unreadable run document.

Search never rebuilds a missing index implicitly. It reports
`discovery_index_unavailable`; an index that has not had a successful refresh
reports `discovery_refresh_required`. Refresh after an upgrade establishes the
initial collection coverage. Later external changes become discoverable only
after another explicit refresh. Known indexed runs still obtain current status
and missing-storage diagnostics from their authoritative readers.

Discovery uses rollback-journal SQLite and memory-only temporary sorting, not
WAL or implicit host temporary directories. The ordinary `runs index` command
also rebuilds the legacy summary catalog; use `--discovery-only` when only search
registration is needed, particularly on qualified shared storage. If the derived
discovery database is corrupt, stop its writers, retain the damaged sidecar for
diagnosis, remove only that derived database, and run the explicit refresh before
resuming writers. Never remove run authority or execution journals for this repair.

Empty pages may have `next_cursor` after exhausting the scan budget.
`coverage.complete` qualifies the page independently of continuation;
`collect_pages` retains warnings and observations, including incomplete empty
pages. Oversized projections retain identity/reference and explicit truncation.
Save returned exact identities for a stable selection; discovery does not freeze
scope membership.

CLI `loom runs search/submissions/jobs/fields/tags` uses the same native service.
`--query` accepts schema-1 JSON; `--tag KEY=VALUE`, `--scope`, `--limit` and
`--cursor` translate to it. Existing `--endpoint` or `--connection` selects the
coordinator; `--format json` retains the envelope. MCP exposes
`loom_search_runs`, `loom_search_submissions`, `loom_search_jobs`,
`loom_query_fields`, `loom_tag_keys` and `loom_tag_values`. Unix CLIENT and HTTPS
CLIENT/QUERY reads share semantics; QUERY gains no mutation rights.
Handshakes advertise `run-query-v1`.
