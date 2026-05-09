# Implementation Plan v8: Run Catalog And Comparison

## Metadata

- Status: draft implementation plan; plan quality gate passed
- Related planning notes:
  `docs/implementation-plans/roadmap-v8-planning-notes.md`
- Related source docs:
  - `docs/implementation-plans/implementation-roadmap.md`
  - `docs/implementation-plans/implementation-plan-v7.md`
  - `docs/features/run-catalog.md`
  - `docs/features/run-store.md`
  - `docs/features/artifacts.md`
  - `docs/features/provenance.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
  - `docs/loom.md`
  - `docs/structure.md`
- Draft pass: complete on 2026-05-09 from confirmed roadmap v8 planning notes
- Refine pass: complete on 2026-05-09 from non-blocking
  `loom_plan_reviewer` notes
- Plan quality gate: passed on 2026-05-09 after initial review,
  non-blocking refinement, and confirmation review
- Blockers: none known for plan drafting. Phase implementation must verify the
  actual v7 run-store, diagnostics, CLI, status, submitted-operation,
  artifact-index, and provenance contracts on the implementation base before
  phase work begins.

## Goal

Implement the v8 local run catalog and metadata comparison layer for `loom`.

After v8, users can point Loom at a local run collection, maintain a
transactional rebuildable SQLite sidecar catalog, list and filter current run
summaries efficiently enough for thousands of local runs, receive
machine-readable warnings for invalid or uncertain runs, and compare two runs
using persisted metadata only. The Python API is the center of gravity; CLI
commands are thin wrappers over the public API.

## Context

V7 is treated as complete for this plan. It provides live SLURM submission,
submitted-operation records, scheduler-aware status and cancellation, and
cluster-free fake-command coverage. V8 does not add new execution behavior. It
derives many-run summaries from authoritative run-store metadata, including
status, stage state, artifact records, provenance records, runtime metadata, and
submitted-operation records where available.

The roadmap originally described a lightweight rebuildable sidecar index and
deferred SQLite-backed local catalogs. The confirmed v8 planning discussion
reopened that decision because concurrent catalog writers are expected. V8 now
uses standard-library SQLite as the default local derived catalog backend while
preserving the run store as the source of truth. Deleting the catalog database
must leave the collection rebuildable from run directories.

The current run-store design is intentionally inspectable one run at a time.
That remains the authoritative persistence layer. V8 adds a public
`loom.runs` package centered on a `RunCatalog` facade so notebooks, scripts,
project tooling, future bundle support, and future sweep aggregation can reuse
one typed API instead of shelling out to the CLI or path-walking run stores.

## Desired Outcome

When all phases are complete:

- `loom.runs` exposes a small public API centered on `RunCatalog` and immutable,
  JSON-serializable value models for run summaries, artifact summaries, filters,
  list/index results, warnings, and comparisons.
- Run identity in public models uses `run_uri` as canonical identity. Display
  names or paths may be exposed as secondary presentation fields only.
- The run store exposes run-local freshness metadata or inventory data that
  changes when catalog-relevant run metadata changes.
- `PipelineRunner` and executors do not write the collection catalog database.
- `RunCatalog.open(path)` or an equivalent constructor can open a local run
  collection without requiring a preexisting index.
- Direct scan can discover local run directories, extract current summaries
  through run-store inspection/public APIs, and report invalid, unreadable,
  partial, actively-changing, disappeared, or unsupported-schema runs as
  warnings by default.
- The minimum public warning taxonomy covers invalid, unreadable, partial,
  actively-changing, disappeared, unsupported-schema, stale/corrupt catalog, and
  unrecoverable catalog errors before CLI JSON exposes those warnings.
- A private SQLite sidecar under the run collection, likely
  `.loom_catalog/catalog.sqlite`, stores derived summaries and filterable
  metadata with schema-versioned internal tables.
- `RunCatalog.rebuild()` can create, replace, or repair the derived catalog from
  authoritative run directories.
- Default catalog reads support only one freshness mode: current. A list/filter
  call refreshes changed, missing, new, and deleted runs before querying the
  SQLite catalog and returning results. Current means validated/refreshed
  against run-store freshness during the read operation, not continuously
  synchronized after the result is returned.
- Exact-match filters are available for run status, tag key/value, config
  fingerprint, pipeline fingerprint, git commit, stage status, artifact
  identity/checksum, and executor/backend identity.
- Catalog reads return result models plus machine-readable warnings rather than
  failing the whole query for ordinary invalid-run conditions.
- Catalog DB corruption or incompatibility triggers rebuild from authoritative
  run directories when possible. Unrecoverable catalog errors do not mutate
  run-store truth.
- `RunCatalog.compare(left, right)` returns metadata-only comparison sections
  for run status/timestamps, config and pipeline fingerprints, stage status and
  fingerprints, artifact identities/checksums, executor/backend identity, and
  selected provenance facts.
- Comparison entries use `same`, `different`, `left_only`, `right_only`, and
  `unknown`.
- `loom runs index`, `loom runs list`, and `loom runs diff` or equivalent
  commands expose the API through text and JSON output without duplicating
  catalog logic.
- Default validation remains local, deterministic, synthetic, and filesystem
  only. No network service, real cluster, hosted tracker, or project-code import
  is required.

## Non-Goals

- No non-SQLite catalog backend in v8.
- No external database service, tracking server, dashboard, daemon, filesystem
  watcher, or remote catalog.
- No bundle export/import. That is v9, though v8 should keep catalog state
  rebuildable and compatible with future import refresh.
- No sweep orchestration or trial semantics. That is v10, though v8 summaries
  should be reusable by future sweep aggregation.
- No hidden project-code imports while scanning, listing, filtering, or
  comparing runs.
- No artifact payload loading during list or comparison.
- No domain-specific metric interpretation, report diff, binary diff, notebook
  rendering, or artifact-payload comparison.
- No fast stale-tolerant read mode in v8.
- No strict fail-on-uncertainty read mode in v8.
- No public SQLite schema or supported external SQL query contract.
- No direct `PipelineRunner` or executor writes to the collection catalog DB.

## Constraints

- Keep `loom` domain-neutral. Project code owns metric meaning, model semantics,
  domain artifact payloads, reports, and any domain-specific comparison plugins
  added later.
- Preserve source-tree boundaries from `docs/structure.md`.
- Keep run-store modules authoritative for persisted run state, stage state,
  attempts, artifact records, provenance records, submitted-operation records,
  and run-local freshness metadata.
- Keep catalog/comparison code under the new `loom.runs` public namespace with
  private internal storage and extraction modules.
- Keep the CLI as an outer presentation layer: parse arguments, call public
  APIs, format text/JSON, and select exit codes.
- Use `run_uri` as the public, protocol, and persisted run identity.
- Treat authored configs as trusted project code, but do not import project
  stage code for catalog listing or comparison.
- Use only standard-library SQLite. Do not add a heavyweight runtime dependency
  for v8 catalog storage.
- Do not rely on periodic full reindexing or stale-index warnings as the
  correctness model for default reads.
- Use short SQLite transactions and avoid holding catalog write transactions
  while reading run directories.
- Keep default tests local, deterministic, synthetic, and filesystem-only.
- Use `make validate-pr` before phase PR review and `make test-summary` before
  PR preparation.

## Design Principles

- The run store is authoritative; the catalog database is derived and
  rebuildable.
- Python APIs are primary; CLI commands are wrappers over those APIs.
- Current reads prioritize correctness and up-to-dateness over stale-fast
  performance.
- Current reads have a bounded consistency claim: they validate and refresh
  against run-store freshness during the read operation, retry or warn for
  actively changing runs, and do not claim returned summaries remain fresh after
  concurrent writers mutate run-store state.
- The public API is small and typed. Internal SQLite schema details stay
  private.
- Direct scan is the correctness fallback and rebuild source, even if the normal
  large-collection path uses SQLite.
- Warning-returning results are part of the API contract, not CLI-only
  presentation details.
- Comparison is metadata-only and domain-neutral by default.
- Concurrency is handled at the catalog layer with SQLite transactions and
  run-store freshness checks, not by coupling execution to the catalog DB.
- Future v9 bundles, v10 sweeps, remote catalogs, and optional read modes should
  extend through the facade and value models without changing runner semantics.

## Key Design Choices

- Add a public `loom.runs` package centered on `RunCatalog`.
- Expose immutable, JSON-serializable models for summaries, artifact summaries,
  filters, warnings, list/index results, and comparison sections/entries.
- Keep SQLite storage, query compilation, and extraction internals private. The
  public compatibility promise is the facade and result models, not DB tables.
- Add run-store-owned freshness metadata or inventory data that catalog code can
  read cheaply before and after summary extraction.
- Ensure run-store writes update freshness metadata through run-store code. The
  runner and executors remain unaware of the collection catalog DB.
- Use optimistic extraction: read freshness before extraction, extract summary
  through store APIs, read freshness again, and retry or warn if the run changed.
- Use SQLite as the local sidecar backend for thousands-of-runs listing and
  expected concurrent catalog readers/writers.
- Prefer WAL mode where available, per-process connections, and short write
  transactions. Do not hold a DB write transaction during filesystem scans.
- Treat corrupt or incompatible catalog DBs as derived-index problems: rebuild
  when possible and report unrecoverable catalog errors without mutating
  run-store truth.
- Support current refresh-on-read only in v8. Fast stale-tolerant and strict
  fail-on-uncertainty modes are deferred.
- Include freshness evidence such as checked timestamps or freshness tokens in
  result or diagnostic models where useful for JSON consumers, without making
  callers depend on SQLite internals.
- Implement exact-match filters first and avoid a general query language.
- Group v8 CLI commands under `loom runs`, with likely commands `index`, `list`,
  and `diff`.

## Conflicts And Tradeoffs

- Correctness vs read latency: v8 accepts refresh overhead on default reads
  because the user explicitly prioritized correct and up-to-date results over a
  stale-fast mode.
- Derived SQLite index vs simple local files: SQLite adds schema and transaction
  complexity, but concurrent writers and thousands-of-runs listing make a
  JSON-only sidecar too weak as the normal path.
- Public facade vs flat functions: `RunCatalog` adds a small object surface, but
  it cleanly encapsulates collection path, connection policy, refresh behavior,
  warnings, and future backend options.
- Rebuildability vs stable SQL access: v8 chooses rebuildability and stable
  Python models over supporting external SQL queries against internal tables.
- Warning-returning reads vs fail-fast behavior: v8 reports ordinary invalid-run
  uncertainty in results so users can still list healthy runs. Strict
  fail-on-uncertainty behavior is deferred.
- CLI discoverability vs API ownership: grouping commands under `loom runs`
  keeps the CLI understandable, but command modules must not become a second
  implementation of scan/filter/diff behavior.
- Metadata comparison vs domain insight: v8 comparison is stable and
  domain-neutral, but it will not answer project-specific metric or artifact
  payload questions until plugin or project-owned comparison hooks exist.

## Maintainability Assessment

The main maintainability risk is mixing authoritative run-store state with
derived catalog state. This plan avoids that by keeping the run store
authoritative, adding only run-store-owned freshness metadata to the store
boundary, and isolating SQLite persistence inside private catalog modules.

The second risk is making the runner responsible for catalog correctness. The
plan explicitly rejects runner-to-DB writes. Execution continues to write run
state through run-store APIs; catalog reads reconcile the derived DB with
run-store freshness data at query time.

The third risk is public API sprawl. `loom.runs.RunCatalog` and a small set of
value models form the public surface. Storage backends, SQL schemas, extraction
helpers, and refresh mechanics remain private so future plan phases can change
internals without breaking callers.

The fourth risk is API/CLI drift. The phase order keeps CLI work last and
requires CLI commands to format public API results rather than duplicate
catalog logic.

The fifth risk is incomplete freshness coverage. Phase 1 must enumerate current
run-store write paths and make freshness updates a store-owned invariant before
scan, SQLite, and list phases depend on it.

## Extensibility Assessment

The `RunCatalog` facade is the main extension point. Future v9 bundle import can
mark or rebuild catalog state after importing runs. Future v10 sweep
aggregation can reuse ordinary run summaries and filters. Later fast or strict
read modes can be added as explicit facade options without weakening the v8
default.

Keeping SQLite private leaves room for alternate backends, remote catalogs, or
watcher-driven refresh later. Those future implementations can preserve public
models and current-read semantics while changing storage details.

The result and warning models are also future-facing. New filters, comparison
sections, and warning codes can be added while preserving the result envelope.
Domain-specific comparison remains outside core Loom and can later attach
through project or plugin-owned mechanisms.

The run-store freshness protocol is intentionally backend-neutral. Local
filesystem stores can implement it with plain artifact-safe files; future remote
stores can implement equivalent freshness tokens without exposing local mtimes
or SQLite details.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Private SQLite schema becomes an internal compatibility surface | Needed for concurrent catalog writers and indexed large-collection queries without making DB rows authoritative. | External SQL access becomes a supported use case, schema rebuild is too costly, or migrations become repeatedly disruptive. |
| Run-store freshness protocol must be maintained across write paths | Query-time correctness depends on a cheap, reliable mutation signal. | A catalog-relevant mutation is missed, or future store implementations cannot support the marker cleanly. |
| Current-only reads can add latency for large collections | User prioritized correctness and up-to-dateness over stale-fast reads for v8. | Read latency is unacceptable and a fast stale-tolerant mode can be added without weakening the default. |
| Direct scan may be slow until SQLite phases land | It is the source-of-truth path needed before derived indexing is safe. | Direct-scan latency blocks phase validation or makes rebuild behavior impractical for expected fixture sizes. |
| Metadata-only comparison will not answer domain-specific questions | Keeps Loom domain-neutral and avoids project-code imports or artifact payload loading. | Plugin or project-owned comparison hooks are planned. |
| Exact CLI command spelling may need later adjustment | API behavior is the compatibility center; CLI grouping can evolve if future v9/v10 command organization demands it. | Bundle or sweep CLI design conflicts with `loom runs` grouping. |

## Plan Quality Gate

- Status: passed
- Required reviewer: `loom_plan_reviewer`
- Required before: creating any v8 phase execution plan or starting Phase 1
  implementation
- Review focus:
  - whether `loom.runs.RunCatalog` is the right public API shape and is small
    enough for an initial compatibility commitment;
  - whether run-store freshness belongs in the store boundary without coupling
    the store to catalog internals;
  - whether the plan adequately prevents `PipelineRunner` and executors from
    writing the collection catalog DB;
  - whether SQLite is correctly treated as a private derived index and not as
    run-store truth;
  - whether current refresh-on-read semantics are concrete enough to keep list
    and filter results up to date;
  - whether the concurrency model avoids long DB transactions and stale-row
    presentation risks;
  - whether warning-returning results are stable enough for Python API and CLI
    JSON consumers;
  - whether comparison boundaries are domain-neutral and metadata-only;
  - whether phase order isolates public contracts, run-store freshness, direct
    scan, SQLite storage, current listing, comparison, and CLI presentation into
    reviewable PRs;
  - whether package, unit, contract, integration, e2e, and synthetic concurrency
    test obligations are sufficient.
- Loop budget:
  - Initial review: used on 2026-05-09; verdict was pass with non-blocking
    notes about documenting the `loom.runs` package boundary in
    `docs/structure.md`, defining the bounded current-read consistency claim,
    and listing the minimum warning-code taxonomy before Phase 1 implementation.
  - Gate refinement pass: used on 2026-05-09; refined this plan to add the
    `docs/structure.md` obligation, bounded current-read language, warning-code
    taxonomy requirement, and optional freshness-evidence note.
  - Confirmation review: used on 2026-05-09; no blocking or non-blocking
    findings remained after refinement.
- Current gate result: passed. Phase implementation may begin after a
  scope-complete Phase 1 execution plan is created.

## Phased Implementation

### Phase 1 - Public Models And Run-Store Freshness

Status: merged
Branch: `codex/run-catalog-models`
PR: https://github.com/samcantrill/loom/pull/95

Goal:

- Establish the public `loom.runs` value-model vocabulary and the run-store
  freshness contract that current catalog reads depend on.

Scope:

- Add the `loom.runs` package with cheap public imports.
- Add immutable, JSON-serializable public models for run summaries, artifact
  summaries, catalog warnings, filters, list/index results, and comparison
  result shapes.
- Define the minimum stable warning-code taxonomy for invalid, unreadable,
  partial, actively-changing, disappeared, unsupported-schema, stale/corrupt
  catalog, and unrecoverable catalog errors.
- Add catalog-specific errors without importing CLI code.
- Add a run-store freshness/inventory protocol to store contracts.
- Implement freshness support in the local run store.
- Ensure catalog-relevant run-store writes update freshness metadata through
  run-store-owned code.
- Update `docs/structure.md` to document `loom.runs` ownership, private storage
  and extraction modules, allowed imports, and forbidden imports from run-store
  or execution modules back into catalog code.
- Add tests that verify run-store freshness support does not import catalog or
  CLI modules.

Out of scope:

- No SQLite catalog storage.
- No full collection scanning.
- No `RunCatalog.list()` query behavior.
- No CLI commands.
- No domain-specific comparison or artifact payload inspection.

Acceptance criteria:

- `from loom.runs import RunCatalog` and public model imports are stable and
  cheap.
- Public models validate required fields, preserve `run_uri` as canonical
  identity, and serialize to plain data.
- Filter models represent the v8 exact-match filter set.
- Catalog warning models support the minimum stable machine-readable codes and
  details required before CLI JSON exposes warnings.
- Local run-store writes expose a freshness token or inventory that changes
  when catalog-relevant run metadata changes.
- Run-store freshness support does not import `loom.runs` or `loom.cli`.
- `docs/structure.md` documents the new `loom.runs` package boundary.
- Existing run-store and execution behavior remains compatible.

Test expectations:

- Package: import checks for `loom.runs` and no optional dependency regressions.
- Unit: model validation, serialization, warning codes, filter validation, and
  freshness token behavior.
- Contract: run-store protocol expectations for freshness reads.
- Integration: local run-store write paths update freshness metadata.
- E2E: not required.
- Opt-in: none.

Design impact:

- This phase creates the initial public compatibility vocabulary and the
  authoritative freshness boundary.

Future compatibility:

- V9 bundles, v10 sweeps, future remote stores, and future read modes can reuse
  the same public models and freshness concept.

Alternatives rejected:

- Catalog-owned freshness markers.
- Runner-owned catalog updates.
- Public SQLite row models.
- CLI-first result models.

Debt introduced:

- Freshness correctness depends on all catalog-relevant run-store writes using
  the marker path.

Reviewability:

- Review public exports, model field names, serialization shape, warning code
  taxonomy, `docs/structure.md` boundary updates, and run-store import
  boundaries before downstream phases depend on them.

Notes:

- The phase execution plan must enumerate current local run-store write paths
  and identify which ones update freshness.
- The phase execution plan must list the initial warning codes and identify
  which are public compatibility commitments.

Completion summary:

- PR opened against `develop` on 2026-05-09:
  https://github.com/samcantrill/loom/pull/95
- Merged into `develop` on 2026-05-09 with squash merge
  `073a357ab13617bb7d146b1886cb7a1bdbbad7e7`.
- Implementation summary: added import-light public `loom.runs` models and
  placeholder facade, catalog warning/result/filter/comparison vocabulary, and
  store-owned local freshness metadata updates for catalog-relevant run-store
  writes.
- Validation: `make validate-pr` passed; `make test-summary` passed with
  package 55, unit 741, contract 73, integration 45, e2e 36, and config-extra
  413 tests passing. GitHub CI `checks` passed before merge.
- Stack maintenance: no successor branch depended on
  `codex/run-catalog-models`; branch cleanup was safe after merge.
- Follow-up notes: Phase 2 should consume `RunFreshnessRecord` through store
  protocols and preserve the Phase 1 explicit exclusions for event logs and
  stage log contents unless it intentionally expands summary scope.

### Phase 2 - Direct Scan And Summary Extraction

Status: pr_open
Branch: `codex/run-catalog-direct-scan`
PR: https://github.com/samcantrill/loom/pull/96

Goal:

- Build the correctness-first path that can discover local runs and extract
  current summaries directly from authoritative run-store records.

Scope:

- Implement local run collection discovery from run-store markers and local run
  directories.
- Implement summary extraction through run-store inspection/public store APIs.
- Read run status, user metadata, config/pipeline fingerprints, stage status and
  fingerprints, artifact identities/checksums, executor/backend identity,
  provenance facts, and submitted-operation summaries where available.
- Validate freshness before and after extraction; retry or warn when a run
  changes during extraction.
- Produce warning-returning direct-scan results for invalid, unreadable,
  partial, disappeared, actively-changing, and unsupported-schema runs.
- Introduce enough of the `RunCatalog` facade to open a collection and perform
  direct current scans.

Out of scope:

- No SQLite persistence or indexed filtering.
- No CLI commands.
- No metadata comparison implementation beyond shared models.
- No artifact payload loading.

Acceptance criteria:

- A Python API caller can open a local run collection and receive current
  direct-scan summaries plus warnings.
- Direct scan does not import project code or load artifact payloads.
- Invalid and partial directories are warnings by default, not whole-query
  failures.
- A run that changes during extraction is retried or reported as
  actively-changing/stale, not accepted as current.
- The direct-scan extractor becomes a reusable source for SQLite rebuild.

Test expectations:

- Package: `RunCatalog` public import remains stable.
- Unit: discovery classification, summary extraction helpers, warning codes,
  and actively-changing retry behavior.
- Contract: result envelopes and `to_dict` output.
- Integration: temporary run collections with valid, invalid, partial,
  unsupported, unreadable, and disappearing runs.
- E2E: not required.
- Opt-in: none.

Design impact:

- This phase proves the source-of-truth path before adding the derived SQLite
  optimization.

Future compatibility:

- Direct scan remains the rebuild source and fallback for missing, corrupted, or
  incompatible catalog DBs.

Alternatives rejected:

- Building SQLite first and treating direct scan as an afterthought.
- Hard-coded JSON path scraping when run-store APIs exist.
- Accepting stale summaries from actively changing runs.

Debt introduced:

- Direct scan may be slow for large collections until indexed phases land.

Reviewability:

- Review warning behavior and extraction boundaries carefully because later
  SQLite phases cache these summaries.

Notes:

- Keep extraction domain-neutral and metadata-only. If an expected field lacks a
  store API, prefer adding a store inspection helper over path-walking in the
  catalog when that preserves boundaries.

Completion summary:

- PR opened against `develop` on 2026-05-09:
  https://github.com/samcantrill/loom/pull/96
- Implementation summary: added `RunCatalog.scan_current()` with private local
  discovery, metadata-only run summary extraction, freshness retry validation,
  and warning-returning direct-scan results for invalid, partial, unsupported,
  disappeared, unreadable, and actively-changing candidates.
- Validation before PR: `make validate-pr` passed; `make test-summary` passed
  with package 55, unit 743, contract 73, integration 47, e2e 36, and
  config-extra 413 tests passing.
- GitHub CI: pending at PR open.
- Stack maintenance: no predecessor; Phase 3 must wait for Phase 2 merge before
  branching from `develop` unless a GitHub-side blocker requires stacked
  continuation.

### Phase 3 - SQLite Sidecar Storage And Rebuild

Status: pending
Branch: `codex/run-catalog-sqlite`
PR: pending

Goal:

- Add the private SQLite sidecar store and explicit rebuild path for large local
  collections and concurrent catalog readers/writers.

Scope:

- Implement schema-versioned SQLite sidecar storage under `.loom_catalog/`,
  likely `.loom_catalog/catalog.sqlite`.
- Store derived run summaries, artifact summary rows, filterable metadata, and
  catalog metadata needed for freshness checks.
- Implement `RunCatalog.rebuild()` to scan authoritative run directories and
  replace or update derived rows transactionally.
- Configure local connection behavior for concurrent readers/writers, including
  per-process connections, short transactions, and WAL mode where supported.
- Avoid holding a DB write transaction while reading run directories.
- Handle corrupt or incompatible DBs by rebuilding when possible.
- Keep schema and storage modules private.

Out of scope:

- No full refresh-on-read filtering semantics.
- No CLI commands.
- No domain-specific query language.
- No public SQL schema documentation.

Acceptance criteria:

- The catalog DB can be created, rebuilt, deleted, and rebuilt again from run
  directories.
- SQLite schema details are private to catalog storage implementation.
- Multiple catalog instances can rebuild or read without corrupting the DB.
- Rebuild results include warnings for invalid or skipped runs.
- Recoverable corruption or incompatibility produces a rebuild path, not
  run-store mutation.

Test expectations:

- Package: no new public storage imports.
- Unit: schema version checks, row mapping, transaction helpers,
  migration/rebuild decisions, and DB path handling.
- Contract: rebuild result shape and warning serialization.
- Integration: temporary collections, DB deletion, stale row replacement,
  corrupt/incompatible DB recovery, and multi-connection read/write smoke
  coverage.
- E2E: not required.
- Opt-in: none.

Design impact:

- This phase introduces the derived persistence layer while preserving
  rebuildability as the public guarantee.

Future compatibility:

- V9 import can mark or rebuild the sidecar without preserving derived DB
  contents in bundles.

Alternatives rejected:

- JSON sidecar as the concurrent-writer backend.
- Public DB schema commitment.
- DB-as-authoritative run state.
- Long catalog transactions around filesystem scans.

Debt introduced:

- Rebuild cost can grow with collection size.

Reviewability:

- Review transaction boundaries, schema versioning, private/public exports, and
  recovery behavior before list/filter APIs depend on the DB.

Notes:

- The phase execution plan should call out platform assumptions for SQLite WAL
  behavior and keep tests deterministic on local filesystems.

Completion summary:

- TBD

### Phase 4 - Current Listing, Refresh, And Filters

Status: pending
Branch: `codex/run-catalog-current-list`
PR: pending

Goal:

- Make `RunCatalog.list()` return current indexed results by refreshing the
  SQLite catalog on read before querying.

Scope:

- Implement collection census against DB rows and run-store freshness metadata.
- Refresh changed, missing, deleted, and newly discovered runs transactionally
  before returning list/filter results.
- Implement exact-match filters for run status, tag key/value, config
  fingerprint, pipeline fingerprint, git commit, stage status, artifact
  identity/checksum, and executor/backend identity.
- Return machine-readable warnings alongside list results.
- Ensure direct-scan fallback remains available when the DB is missing,
  rebuilding, or recoverably corrupted.
- Add deterministic ordering for list results if needed for stable output.

Out of scope:

- No fast stale-tolerant mode.
- No strict fail-on-uncertainty mode.
- No partial-text search, fuzzy matching, or advanced query language.
- No time/range filters except internal ordering support if needed.
- No CLI commands.

Acceptance criteria:

- Public API list calls return current summaries and warnings.
- Current means validated/refreshed against run-store freshness during the read
  operation; returned summaries do not claim continuous freshness after
  concurrent writers mutate run-store state.
- Stale DB rows are not presented as current without validation.
- Changed, missing, new, and deleted runs are reconciled before query results
  are returned.
- Filters are evaluated through the API and backed by SQLite where useful.
- Warning behavior remains nonfatal for ordinary invalid-run conditions.
- Concurrent readers/writers do not corrupt the catalog and do not accept
  actively changing summaries as current.

Test expectations:

- Package: public API exports unchanged.
- Unit: filter compilation/validation, freshness reconciliation decisions,
  query mapping, warning aggregation, and result ordering.
- Contract: list result JSON shape and warning codes.
- Integration: stale rows, changed runs, deleted runs, missing DB, corrupt DB,
  concurrent readers/writers, and thousands-of-runs synthetic fixture coverage.
- E2E: not required.
- Opt-in: none.

Design impact:

- This phase delivers the core v8 correctness/performance guarantee for
  many-run queries.

Future compatibility:

- Future read modes or backends can plug into the facade while preserving
  current behavior as the default.

Alternatives rejected:

- Periodic full reindex as the correctness mechanism.
- Querying stale DB rows and surfacing only a staleness warning.
- CLI-owned filtering logic.

Debt introduced:

- Current reads pay refresh overhead.

Reviewability:

- Review freshness guarantees, transaction scope, filter semantics, warning
  behavior, and concurrency tests as the main evidence.

Notes:

- This phase is the highest-risk correctness slice and should use the expanded
  path for phase planning and refinement unless the plan quality gate later
  narrows the risk.
- The phase execution plan should decide whether list/index results include
  `checked_at` or freshness-token evidence for JSON consumers.

Completion summary:

- TBD

### Phase 5 - Metadata Comparison API

Status: pending
Branch: `codex/run-catalog-comparison`
PR: pending

Goal:

- Implement metadata-only run comparison through the public Python API.

Scope:

- Add `RunCatalog.compare(left, right)` or equivalent facade behavior.
- Compare two runs by persisted metadata using confirmed sections: run
  status/timestamps, config and pipeline fingerprints, stage status and
  fingerprints, artifact identities/checksums, executor/backend identity, and
  selected provenance facts such as git commit and command/runtime summaries.
- Use current summaries and targeted direct extraction where needed.
- Return structured comparison sections and entries with `same`, `different`,
  `left_only`, `right_only`, and `unknown`.
- Surface warnings for missing, unsupported, or unreadable comparison inputs.

Out of scope:

- No artifact payload diffs.
- No domain metric interpretation.
- No binary, report, or notebook diffs.
- No plugin comparison hooks.
- No CLI diff command.

Acceptance criteria:

- `RunCatalog.compare(left, right)` returns a structured metadata comparison.
- Missing or unsupported metadata becomes explicit comparison output or
  warnings rather than domain-specific failures.
- Comparison does not import project code or load artifact payloads.
- Comparison output serializes cleanly for future CLI JSON presentation.

Test expectations:

- Package: comparison models exported from `loom.runs`.
- Unit: entry status computation, section ordering, missing metadata handling,
  provenance selection, and warning generation.
- Contract: comparison result JSON shape.
- Integration: identical runs, different fingerprints, left-only/right-only
  artifacts or stages, unsupported records, and warning cases.
- E2E: not required.
- Opt-in: none.

Design impact:

- This phase makes catalog summaries useful for review workflows without
  expanding Loom into a domain comparison engine.

Future compatibility:

- Later plugin or project-owned comparison hooks can add sections without
  changing the core metadata comparison statuses.

Alternatives rejected:

- Raw metadata dump as comparison output.
- Artifact payload loading.
- Domain-specific metric comparison in core Loom.

Debt introduced:

- Comparison is intentionally limited to metadata users can inspect without
  project code.

Reviewability:

- Review section boundaries, status semantics, and serialization independently
  from CLI formatting.

Notes:

- This phase should prefer stable, compact comparison sections over exposing raw
  persisted documents.

Completion summary:

- TBD

### Phase 6 - CLI Integration, Docs, And End-To-End Coverage

Status: pending
Branch: `codex/run-catalog-cli`
PR: pending

Goal:

- Expose the completed catalog and comparison behavior through thin CLI wrappers
  and update user-facing documentation.

Scope:

- Add a `loom runs` command group with likely subcommands `index`, `list`, and
  `diff`.
- Support text and JSON output using public API result models.
- Map catalog warnings and errors through existing CLI formatting and exit-code
  conventions.
- Add CLI argument parsing for v8 filters.
- Update relevant feature docs, CLI docs, README snippets if appropriate, and
  implementation-plan evidence expectations.
- Add end-to-end CLI tests over temporary local collections.

Out of scope:

- No CLI-specific catalog logic.
- No background daemon or watcher commands.
- No export/import bundle commands.
- No sweep commands.
- No CLI behavior that bypasses `loom.runs`.

Acceptance criteria:

- CLI commands call `loom.runs` APIs and do not duplicate scan/filter/diff
  behavior.
- Human output is concise and includes warnings.
- JSON output preserves API result and warning data.
- CLI errors follow existing formatting and exit-code conventions.
- Existing validation commands continue to pass.

Test expectations:

- Package: no CLI import regressions.
- Unit: CLI argument parsing and formatting helpers.
- Contract: JSON output envelopes and warning serialization.
- Integration: CLI command handlers with temporary stores.
- E2E: `loom runs index`, `loom runs list`, filtered list, and
  `loom runs diff` over synthetic run collections.
- Opt-in: none.

Design impact:

- This phase keeps CLI as the presentation layer after Python API behavior is
  complete.

Future compatibility:

- V9 and v10 CLI commands can reuse the same catalog APIs and warning/result
  conventions.

Alternatives rejected:

- Top-level CLI-only diff/list behavior.
- Making CLI output shape diverge from public API results.
- Implementing scan/filter/diff logic directly in command modules.

Debt introduced:

- Exact command spelling may need later adjustment if future bundle/sweep
  grouping changes CLI organization.

Reviewability:

- Review API/CLI layering and JSON compatibility rather than re-litigating
  catalog internals.

Notes:

- This phase should not start until API list and comparison behavior are stable
  enough for the CLI to be a thin formatter.

Completion summary:

- TBD
