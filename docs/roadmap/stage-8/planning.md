# Roadmap v8 Planning Notes: Run Catalog And Comparison

## Metadata

- Roadmap version: v8
- Source roadmap:
  `docs/roadmap.md`
- Previous version status: complete for planning. `docs/roadmap/stage-7/implementation-plan.md`
  records v7 as completed with Phases 1-7 merged into `develop`, providing live
  SLURM submission, submitted-operation records, scheduler-aware status and
  cancellation, and cluster-free fake-command coverage.
- Planning notes status: complete; implementation-plan draft created
- Current discussion stage: Handoff complete
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Feature brainstorming: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: confirmed after context reset
  - Design decision review: confirmed
  - Phase shaping: confirmed
  - Handoff: complete; `docs/roadmap/stage-8/implementation-plan.md` drafted after explicit
    confirmation
- Related implementation plans:
  - `docs/roadmap/stage-7/implementation-plan.md`
- Related feature docs:
  - `docs/features/run-catalog.md`
  - `docs/features/run-store.md`
  - `docs/features/artifacts.md`
  - `docs/features/provenance.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
  - `docs/loom.md`
  - `docs/structure.md`
- Blockers:
  - None known for planning. Implementation must verify the actual v7 run-store,
    CLI, status, submitted-operation, artifact-index, and provenance contracts
    before phase work begins.

## Roadmap Extraction

Baseline roadmap outcome:

- Make many local runs discoverable, searchable, and comparable without adding
  an external database service, tracking server, or domain-specific artifact
  reader. V8 now includes a standard-library SQLite sidecar because concurrent
  writers are expected.
- Add run catalog value models, including `RunSummary`, artifact summaries,
  catalog index records, and catalog warning records.
- Scan local run collections by reading authoritative run-store markers and
  metadata.
- Build a rebuildable SQLite-backed local sidecar catalog index with
  direct-scan and per-run refresh fallback. This intentionally expands the
  roadmap's initial "no database" default because v8 must support concurrent
  catalog writers while staying correct and scalable.
- Expose a CLI rebuild command, named by the roadmap as `loom runs index` or an
  equivalent.
- Expose `loom runs list` with core filters such as status, tag, fingerprint,
  commit, stage status, and machine-readable JSON output.
- Detect stale indexes and surface warnings for invalid, unreadable, partial, or
  disappeared runs.
- Compare two runs using metadata only: config fingerprints, pipeline
  fingerprints, stage statuses, stage fingerprints, artifact identities,
  checksums, executor identities, and selected provenance facts.
- Expose a metadata diff CLI with human and JSON output.
- Add tests using temporary run collections, synthetic run stores, stale indexes,
  invalid directories, and comparison fixtures.

Prerequisites:

- v0 local runtime kernel: durable local run-store layout, artifacts, status
  records, stage inputs/outputs, fingerprints, failures, logs, provenance, and
  conservative resume.
- v1 rebuildable config composition: artifact-safe config source records,
  composition manifests, config fingerprints, and provenance summaries.
- v2 CLI core: thin argparse command wrappers, JSON output conventions, and
  shared error handling.
- v3 diagnostics and preflight: local inspection patterns and CLI status/logs/
  artifact diagnostics.
- v4 runtime options/resources: normalized runtime metadata and executor
  descriptors that catalog summaries may expose without domain interpretation.
- v5 stage worker/subprocess execution: worker records, attempt-aware stage
  state, subprocess logs, and baseline failure records.
- v6 SLURM script planning: generated submission artifacts, wrapper log paths,
  and dry-run manifest records that remain inspectable as run metadata.
- v7 SLURM operations: submitted-operation records and persisted scheduler
  facts that v8 should summarize without requiring live scheduler access.

Primary feature docs:

- `run-catalog.md`
- `run-store.md`
- `artifacts.md`
- `provenance.md`
- `cli.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- No export/import bundles. That is v9.
- No sweeps or trial orchestration. That is v10, though v10 expects every trial
  to remain an ordinary run that v8 tools can inspect.
- No hosted service, dashboard UI, remote catalog service, or incremental
  filesystem watcher.
- No domain-specific artifact diffs, metrics semantics, binary diffs, notebook
  rendering, or project-specific comparison logic.
- No remote-store operations or cross-machine catalog synchronization.
- No required network access, real cluster, cloud service, or heavyweight
  runtime dependency in default tests.

Compatibility obligations:

- Keep the catalog derived data. The run store remains authoritative for run
  state, stage state, attempts, artifact records, provenance records, and
  submitted-operation records.
- Preserve the current run identity migration: public, protocol, and persisted
  run identity is `run_uri`. Catalog and comparison models may expose display
  names or path summaries, but they should not reintroduce old `run_id` as the
  canonical identity.
- Preserve source-tree boundaries from `docs/structure.md`: run-store modules
  own persisted state and path-safe helpers; catalog/comparison code should read
  through public store or inspection APIs where available; CLI should parse
  arguments, call Python APIs, format text/JSON, and map errors without
  duplicating low-level store logic.
- Keep `loom` domain-neutral. Project code owns metric meaning, model
  semantics, domain artifact payloads, reports, and any domain-specific
  comparison plugins added later.
- Keep default validation local, deterministic, synthetic, and filesystem-only.
- Treat invalid, unreadable, partial, actively-changing, unsupported-schema, and
  disappeared runs as visible catalog warnings. Strict fail-on-uncertainty
  behavior is deferred beyond v8.
- Keep sidecar indexes schema-versioned, rebuildable, and artifact-safe. They
  must not silently repair or override authoritative run-store files.
- SQLite is in v8 scope as the default local catalog backend because concurrent
  catalog writers are expected. The database remains a derived index, not an
  authoritative run store. Deleting it must leave the run collection
  rebuildable from run directories.

## Version Briefing

What this version is:

- V8 is the local many-run discovery and comparison layer. Up through v7, Loom
  can create, execute, inspect, and operate on individual runs. V8 adds the
  ability to point Loom at a local run collection, maintain a transactional
  derived SQLite index, list and filter runs, and compare two runs using
  persisted metadata. It should make local experiment directories manageable
  without turning Loom into a hosted tracking server.

Why this version exists:

- The current run-store design is intentionally inspectable one run at a time.
  That is enough for execution and debugging, but not enough once a user has
  dozens or hundreds of local run directories. V8 closes that gap by deriving
  compact summaries from existing run metadata, making stale or invalid entries
  visible, and explaining high-level differences between two runs without
  loading artifact payloads or importing project code.

Impacted or linked work:

- Direct predecessor: v7. Submitted and scheduler-operated runs should remain
  catalogable from persisted state alone. V8 should summarize statuses,
  submitted-operation presence, executor identities, and provenance facts
  without requiring `squeue`, `sacct`, `sbatch`, or a live cluster query.
- Direct successor: v9. Bundles will use catalog-compatible summaries and must
  be able to mark an index stale after import. V8 should keep catalog indexes
  rebuildable so v9 does not need to preserve derived index data as truth.
- Later successor: v10. Sweeps are many ordinary runs. V10 status aggregation
  and collection should be able to reuse v8 summary and filtering concepts
  rather than inventing a separate experiment database.
- Later links: remote stores in v12 and v13 may eventually need remote
  references or remote preflight summaries, but v8 should stay local and
  backend-neutral. Cleanup and retention in v17 may later use catalog summaries
  to choose deletion candidates, so v8 warning and staleness semantics should be
  conservative.

Likely public surfaces and durable artifacts:

- A new runtime package area for catalog and comparison models and APIs, with
  the public namespace and facade shape to be settled during design review.
- Value models for run summaries, artifact summaries, catalog index metadata,
  catalog warnings, comparison sections, and comparison entries.
- A sidecar index under a run collection, likely
  `runs/.loom_catalog/catalog.sqlite` or an equivalent schema-versioned SQLite
  file.
- Read-only catalog APIs for scanning a collection, building or rebuilding an
  index, listing/filtering summaries, checking index freshness, and comparing
  two runs.
- CLI command group for many-run operations, likely `loom runs index` and
  `loom runs list`, plus a metadata comparison command such as `loom runs diff`
  or `loom diff`.
- JSON envelopes for index, list, and diff commands following the existing CLI
  style.
- Focused tests for package imports, value-model serialization, local
  collection scanning, index rebuilds, warning behavior, filters, stale-index
  cases, and metadata-only comparisons.

Structure rationale:

- The roadmap isolates v8 from bundles and sweeps because run discovery and
  comparison are valuable without archive/export behavior or sweep orchestration.
  That keeps the version centered on one product outcome: local users can find,
  filter, and compare existing runs.
- The version should be one implementation-plan unit because the core model,
  index, filters, and comparison all depend on the same summary extraction
  boundary. Splitting comparison away too early would likely force the summary
  model to be redesigned immediately.
- The sidecar index is explicitly derived. In v8 it is SQLite-backed because
  concurrent writers are expected, but it remains rebuildable from run-store
  metadata and hidden behind public APIs so future storage changes do not leak
  into callers.

Visible assumptions, risks, and constraints:

- Assumption: v8 should use `run_uri` as canonical identity even when commands
  accept local collection paths or display compact path labels.
- Assumption: listing should work when no index exists by direct scanning for
  small collections, while still nudging users toward explicit index rebuilds
  for repeatable or larger workflows.
- Assumption: invalid, unreadable, partial, disappeared, and stale runs should
  produce warnings by default instead of failing the entire list command.
- Assumption: comparison is metadata-only by default and should not load large
  artifact payloads, parse domain metrics, or import project stage code.
- Assumption: `tags` and `notes` come from existing run metadata where present;
  v8 should not create a large mutable annotation system unless the planning
  discussion identifies a narrow need.
- Assumption: SQLite is acceptable in v8 because it is a standard-library
  dependency and concurrent catalog writers are expected.
- Risk: a richer index can improve performance and concurrency, but the larger
  it gets, the more it risks duplicating run-store truth and becoming a schema
  burden.
- Risk: direct scanning is simple and always fresh, but can be slow for large
  collections if every command reads every run directory.
- Risk: comparison output can become noisy if it dumps raw metadata. The plan
  needs a small, stable set of sections that users can understand and machines
  can consume.
- Risk: local path handling must be strict because v9 import/export safety and
  future cleanup work may rely on catalog boundaries.
- Risk: run collections may contain runs from older schema versions or partially
  written interrupted executions. V8 should report uncertainty rather than
  silently normalizing incompatible data.
- Constraint: no external database dependency, no service process, no network
  access, no real-cluster dependency, and no domain-specific payload
  inspection. SQLite is acceptable because it is in the Python standard
  library.

User clarification questions and resolved answers:

- User had no clarifying questions or corrections about the startup v8
  briefing.
- User confirmed the planning priority should optimize for both local,
  rebuildable auditability and catalog performance, with robust public API
  design treated as a first-class outcome rather than a secondary
  implementation detail.
- User raised the freshness/performance tradeoff as a likely high-impact design
  decision: v8 must scale to thousands of runs while remaining correct and
  up-to-date, so the plan must explicitly consider whether a JSON sidecar plus
  freshness validation is sufficient, whether incremental refresh is required,
  and whether the roadmap's deferred SQLite-backed catalog should be reopened.
- User clarified that concurrent writers are expected. This makes a
  SQLite-backed local catalog a likely v8 requirement despite the roadmap's
  initial deferral, provided the catalog remains derived from run-store metadata
  and code boundaries stay modular.
- User confirmed SQLite-backed local catalogs should be included in v8 scope.
  The selected direction is a transactional SQLite derived index, run-store
  freshness markers, no direct runner-to-DB coupling, and public APIs centered
  on a catalog facade that owns refresh/query policy.

## User Intent

Target audience:

- Primary focus: Python API consumers building project-local tooling,
  notebooks, scripts, and future Loom features on top of many-run metadata.
- Secondary surface: CLI users managing local run folders. The CLI must remain
  a thin wrapper over public catalog and comparison APIs rather than owning
  catalog logic.
- Maintainers remain a target audience for validation, schema evolution,
  import-boundary review, and future roadmap reuse.

User-visible outcome:

- Users can rebuild and refresh a SQLite-backed local catalog, list/filter run
  summaries efficiently enough for thousands of local runs through an
  index-normal path, see stale or invalid run warnings, and compare two runs
  using metadata only through a small stable public API and a thin CLI wrapper.

Success criteria:

- Public APIs are the implementation center of gravity. CLI commands call those
  APIs and do not duplicate catalog scanning, filtering, freshness, warning, or
  comparison logic.
- The sidecar index is the normal path for large local collections and is
  designed for thousands of runs with concurrent readers/writers through
  SQLite.
- Direct scan remains correct and freshness-preserving. It can be slower, but
  it must remain a reliable fallback when the catalog database is missing,
  stale, unreadable, or needs to refresh individual changed entries.
- Staleness and invalid-run conditions are visible and machine-readable rather
  than silently ignored.
- A small public API is exposed immediately for summary models, scan/index/list
  behavior, warnings, filters, and metadata comparison results.
- The run store remains authoritative; indexes can be deleted and rebuilt.
- Catalog correctness is query-time by default: the SQLite database may be
  stale between operations, but default API/CLI reads perform freshness checks,
  refresh changed entries, and report stale/partial warnings before presenting
  results as current.
- V8 exposes only current refresh-on-read behavior. It does not expose fast or
  strict freshness modes.

Non-goals:

- No non-SQLite database backend in v8.
- No tracking service, daemon, dashboard, or remote catalog.
- No domain-specific artifact payload comparison or metric interpretation.
- No bundle export/import, except for leaving compatible stale-index semantics
  for v9.
- No sweep orchestration or trial semantics, except for keeping summaries
  reusable by v10.
- No hidden project-code imports while scanning, listing, or comparing runs.
- No fast stale-tolerant catalog read mode in v8.
- No strict fail-on-uncertainty catalog read mode in v8.

Constraints:

- Keep `loom` domain-neutral and source-tree boundaries intact.
- Treat `run_uri` as canonical run identity.
- Keep catalog indexes derived, schema-versioned, transactional, and
  rebuildable.
- Preserve correctness and up-to-dateness as explicit design goals even when
  the index is optimized for larger local collections.
- Do not rely on a naive stale-index policy or periodic full reindex alone as
  the correctness model for listing/filtering. The index strategy must define
  when summaries are fresh, when changed runs are refreshed, and when direct
  scan or strict verification is required.
- Decide whether execution/run-store writes need to expose a run-local
  freshness token or inventory marker for catalog refresh. Avoid making
  `PipelineRunner` write a collection-level catalog or database unless the
  design review finds no cleaner way to satisfy correctness and scale.
- Treat concurrent catalog readers/writers as a design constraint. Catalog DB
  writes must be transactional and recoverable, and stale DB rows must be
  checked against authoritative run-store freshness metadata before being
  presented as current.
- Define the catalog guarantee as query-time freshness by default, not
  continuous background synchronization. The SQLite catalog may be stale between
  operations, but default public API and CLI reads must perform the cheap
  collection/run freshness checks needed to refresh changed entries or report
  stale/partial warnings before returning results as current.
- V8 supports only one freshness mode: current. Public API and CLI reads
  refresh on read, using collection census and run-local freshness metadata to
  update changed, missing, or deleted DB rows transactionally before querying.
  Fast stale-tolerant reads and strict fail-on-uncertainty reads are deferred.
- Keep default tests local, deterministic, and synthetic.
- Avoid heavyweight runtime dependencies.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | v8 is scoped to local derived run catalogs and metadata-only comparison; v7 is treated as complete for planning; bundles, sweeps, remote catalogs, dashboards, and domain artifact diffs are deferred; robust public API design is a first-class outcome. | Optimize for both local rebuildable auditability and scalable-enough catalog performance. Use `run_uri` as canonical identity and keep run store authoritative. | None. | Intent discovery: confirm workflows, success criteria, non-goals, constraints, and API audience. |
| Intent discovery | Python API is the primary focus; CLI is a thin wrapper. V8 should design for thousands of runs and concurrent catalog readers/writers via a SQLite sidecar while keeping direct scan and per-run refresh correct and freshness-preserving. A small public API should be exposed immediately. | SQLite-backed index-normal path for scale/concurrency; direct scan remains correctness fallback; run store stays authoritative. | None. | Feature brainstorming: sort candidate capabilities into include, defer, maybe, and out of scope. |
| Feature brainstorming | Include public catalog/comparison APIs, SQLite-backed rebuildable sidecar index, correct direct-scan/per-run refresh fallback, list/filter behavior, warnings, metadata-only comparison, and thin CLI wrappers. Defer daemons/watchers, remote catalogs, dashboards, bundles, sweeps, domain-specific diffs, and payload loading. | Keep v8 centered on API-first local run discovery and metadata comparison. | None. | Functionality and behavior confirmation: lock defaults, filters, comparison sections, and failure behavior. |
| Functionality and behavior confirmation | Freshness, filters, comparison defaults, and warning behavior confirmed. V8 includes exact-match filters for run status, tag key/value, config fingerprint, pipeline fingerprint, git commit, stage status, artifact identity/checksum, and executor/backend identity. Metadata comparison includes run status/timestamps, config/pipeline fingerprints, stage status/fingerprints, artifact identities/checksums, executor/backend identity, and selected provenance facts such as git commit and command/runtime summaries. Current reads return results plus warnings for invalid, unreadable, partial, actively-changing, disappeared, or unsupported-schema runs rather than failing the whole query. | Current refresh-on-read only; exact-match filters first; metadata-only comparison; warning-returning behavior by default. | None for functionality. | Write checkpoint and reset context before design decision review. |
| Context compaction/reset checkpoint | Functionality and behavior checkpoint written in this file. Design review resumed from these notes after context reset. Functionality is not reopened unless explicitly requested. | Reload `docs/roadmap/stage-8/planning.md`, `.codex/prompts/roadmap-stage-planning-facilitate.md`, and relevant source/feature docs before design questions. | None. | Design decision review queue and triage. |
| Design decision review | Clear recommendations recorded for SQLite derived catalog ownership, run-store freshness participation, schema/rebuild policy, concurrent access model, result/warning contracts, CLI ownership, testing strategy, and the public API namespace/facade shape. | Public API uses `loom.runs` centered on a `RunCatalog` object facade, with small immutable result models and private SQLite/extraction internals. | None. | Phase shaping: confirm implementation phase order, granularity, dependencies, and review boundaries. |
| Phase shaping | User confirmed the six-phase implementation shape and order: public models/run-store freshness, direct scan/extraction, SQLite sidecar/rebuild, current listing/refresh/filters, metadata comparison API, then CLI/docs/e2e. | Build API and correctness foundations before SQLite querying, and keep CLI last as a thin wrapper over completed public APIs. | None. | Handoff: mark notes ready and request explicit implementation-plan drafting confirmation. |
| Handoff | Planning notes fed `docs/roadmap/stage-8/implementation-plan.md` after explicit user confirmation. | Use these notes as the primary source for plan review and refinement. | None for planning notes. | Plan quality gate review and implementation-plan refinement. |

## Brainstormed Capabilities

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Public catalog and comparison API | include | User confirmed Python API is the primary focus and a small public API should be exposed immediately. | CLI must wrap this API rather than duplicate catalog logic. |
| Local run collection scan | include | Required for correctness, freshness, and rebuilding derived indexes. | Should identify valid runs from run-store markers and metadata. |
| SQLite-backed rebuildable sidecar index | include | Required for thousands-of-runs posture, repeatable list/filter commands, and expected concurrent catalog writers. | Must remain derived data and be rebuildable from run directories. |
| Direct-scan fallback | include | User emphasized correctness and up-to-dateness. | Used when the catalog database is missing, stale, unreadable, or refreshing changed entries. |
| Run list filters | include | Roadmap names core filters and user accepted the include set. | Exact-match filters: run status, tag key/value, config fingerprint, pipeline fingerprint, git commit, stage status, artifact identity/checksum, and executor/backend identity. |
| Stale and invalid run warnings | include | Critical for trust in derived indexes. | Current reads return results plus warnings for invalid, unreadable, partial, actively-changing, disappeared, and unsupported-schema runs. |
| Metadata-only run comparison | include | Roadmap-owned capability and user accepted the include set. | Default sections: run status/timestamps, config/pipeline fingerprints, stage status/fingerprints, artifact identities/checksums, executor/backend identity, and selected provenance. |
| Thin CLI wrappers | include | CLI is secondary but required as a thin wrapper over public APIs. | Likely `loom runs index`, `loom runs list`, and `loom runs diff` or equivalent. |
| Export/import bundles | defer | Roadmap assigns this to v9. | V8 should leave catalog-compatible hooks only where needed. |
| Sweep aggregation | defer | Roadmap assigns this to v10. | V8 summaries should be reusable by future sweeps. |
| SQLite-backed local catalog | include | User clarified concurrent writers are expected and confirmed SQLite belongs in v8 scope. | Must remain derived data and hidden behind public APIs so storage internals can evolve. |
| Domain-specific artifact diff | defer | Roadmap defers domain comparison reports. | Future plugin or project code responsibility. |
| Daemon, incremental watcher, dashboard, remote catalog | out of scope | Roadmap explicitly defers these beyond v8. | Avoids service lifecycle and remote consistency concerns. Incremental refresh on command/API calls remains under consideration and is distinct from a watcher daemon. |
| Artifact payload loading during list or diff | out of scope | Violates metadata-only comparison and domain-neutrality boundaries. | Checksums and metadata are allowed. |

## Confirmed Functionality And Behavior

Included functionality:

- SQLite-backed derived local run catalog.
- Run-local freshness metadata produced through run-store-owned state, not
  direct runner-to-catalog writes.
- Refresh-on-read catalog APIs that update changed, missing, and deleted runs
  before returning current query results.
- Public API and CLI behavior for current listing/filtering only.
- Exact-match list filters for run status, tag key/value, config fingerprint,
  pipeline fingerprint, git commit, stage status, artifact identity/checksum,
  and executor/backend identity.
- Metadata-only run comparison covering run status/timestamps, config and
  pipeline fingerprints, stage status/fingerprints, artifact identities and
  checksums, executor/backend identity, and selected provenance facts such as
  git commit and command/runtime summaries.
- Warning-returning current reads for invalid, unreadable, partial,
  actively-changing, disappeared, and unsupported-schema runs.

User-visible behavior:

- Python API consumers can create/open a run catalog for a local run collection,
  refresh it on read, list/filter current summaries, inspect warnings, and
  compare two runs without importing project code or loading artifact payloads.
- CLI commands wrap the public API and expose the same current read behavior.
- Catalog reads may update the SQLite sidecar as part of normal current reads,
  but the run store remains authoritative and the catalog can be rebuilt.
- Concurrent catalog readers/writers are supported through SQLite transactions.

Default behavior:

- Reads are current by default and by design. V8 does not expose stale-tolerant
  or fail-on-uncertainty read modes.
- The catalog database may be stale between operations, but current reads must
  reconcile it with run-store freshness metadata before presenting results.

Failure behavior and diagnostics:

- Invalid, unreadable, partial, actively-changing, disappeared, and
  unsupported-schema runs produce machine-readable warnings and do not fail the
  whole list/filter query by default.
- A run that changes during summary extraction is retried or reported as an
  actively-changing/stale warning rather than accepted as current.
- Catalog database corruption or incompatibility should trigger rebuild from
  authoritative run directories when possible; unrecoverable catalog errors are
  reported as catalog errors without mutating run-store truth.
- Metadata comparison uses `same`, `different`, `left_only`, `right_only`, and
  `unknown` statuses for entries. Missing or unsupported records become
  explicit comparison entries or warnings instead of domain-specific failures.

Explicit deferrals:

- Fast stale-tolerant reads.
- Strict fail-on-uncertainty reads.
- Time/range filters unless needed by implementation as internal ordering
  support.
- Partial-text search, fuzzy matching, and advanced query language.
- Domain-specific comparison sections.

Out-of-scope behavior:

- Direct `PipelineRunner` writes to the collection catalog database.
- Treating the catalog database as authoritative state.
- Background synchronization daemon or filesystem watcher.
- Artifact payload loading during list or comparison.
- Domain-specific metric interpretation, binary diffs, report diffs, or
  notebook rendering.

Context compaction/reset checkpoint:

- Checkpoint status: written; context reset/resume required before design
  decision review
- Notes path: `docs/roadmap/stage-8/planning.md`
- Resume instruction: after functionality and behavior are confirmed, reload
  this planning notes file and `.codex/prompts/roadmap-stage-planning-facilitate.md`
  before beginning design decision review. Treat the confirmed functionality and
  behavior as the stable baseline unless the user explicitly reopens it.
- Functionality and behavior reopened after checkpoint: no

## Design Decision Review Queue

| Decision | Why it matters | User feedback needed | Status |
| --- | --- | --- | --- |
| Catalog freshness and index backend strategy | Determines whether v8 can be both correct/up-to-date and scalable to thousands of runs with concurrent writers. | None. User already confirmed SQLite in v8, current refresh-on-read, run-store freshness metadata, and no direct runner-to-DB writes. | confirmed |
| Public API namespace and facade shape | Becomes a durable compatibility surface for Python API users and future v9/v10 features. | User agreed to the recommended `loom.runs.RunCatalog` facade approach. | confirmed |
| SQLite schema, migration, and rebuild policy | Affects persistence compatibility, corruption recovery, and whether implementation details leak into public contracts. | None. Repo boundaries and confirmed derived-index requirement support a private versioned schema with rebuild on incompatibility. | confirmed |
| Concurrent access and freshness transaction model | Determines whether catalog reads/writes stay correct with multiple processes and actively changing run directories. | None. SQLite plus run-store authority gives a clear optimistic-refresh recommendation. | confirmed |
| Result, warning, and comparison contracts | Affects API stability, CLI JSON compatibility, and domain-neutral comparison semantics. | None. Confirmed behavior already fixes warning and comparison status semantics. | confirmed |
| CLI command ownership | Affects layering and whether CLI becomes a second implementation of catalog behavior. | None. Existing CLI docs require thin wrappers over Python APIs. | confirmed |
| Testing strategy for scale and concurrency | Affects reviewability and long-term confidence in correctness-first catalog behavior. | None. Repo testing docs and v8 risks support synthetic local concurrency/integration coverage. | confirmed |

## Design Decisions

| Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Debt and revisit trigger |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Catalog backend, ownership, and freshness | Use a SQLite-backed sidecar catalog as a derived index owned by the catalog API layer. Default reads refresh changed, missing, and deleted runs before querying. The run store exposes run-local freshness metadata or inventory data; the runner does not write the collection catalog DB directly. | User confirmed concurrent writers are expected, SQLite belongs in v8, only current refresh-on-read mode is supported, run-store freshness participation is needed, and direct runner-to-DB writes are out of scope. | JSON-only sidecar, direct scan as the normal large-collection path, periodic full reindex as the correctness model, DB-as-truth, runner-owned catalog writes, background daemon or watcher, and fast/strict freshness modes in v8. | This is the smallest design that supports thousands of runs, concurrent catalog writers, and query-time correctness while preserving the run directory as source of truth. | Separates execution, run-store persistence, and catalog query policy. Centralizes refresh/query behavior behind one API surface instead of scattering freshness checks through CLI commands. | Future fast/strict modes, remote catalogs, watcher refresh, bundle imports, and sweep aggregation can build behind the catalog facade without changing runner semantics. | SQLite schema and freshness-token semantics become internal compatibility surfaces. Revisit if current reads are too slow for large collections, if multi-machine catalogs arrive, or if v9/v10 need stronger invalidation hooks. |
| Public API namespace and facade shape | Expose a public `loom.runs` package centered on a `RunCatalog` object facade. The facade owns opening a run collection, rebuilding or refreshing the catalog, listing/filtering summaries, returning warnings, and comparing runs. Keep SQLite storage, extraction, and refresh internals private. | User agreed to the recommended `loom.runs.RunCatalog` facade approach. | Flat functions as the primary API, `loom.catalog`, `loom.run_catalog`, public SQLite store APIs, and making CLI commands the primary public surface. | `loom.runs` aligns with the planned `loom runs` CLI and avoids ambiguity with config recipe catalogs. A catalog object can encapsulate collection path, SQLite connection policy, refresh behavior, warnings, and future backend options better than a flat function set. | Gives Python users one durable entrypoint while keeping the public surface small. Prevents callers from depending on SQLite internals or copying CLI behavior. | Future v9 bundle import, v10 sweep aggregation, additional filters, optional read modes, and alternate backends can extend through the facade and value models. Thin convenience functions can be added later without replacing the facade. | The facade shape becomes a compatibility commitment. Revisit only if implementation proves that common usage is clumsy or if future backend support needs an explicit factory/protocol split. |
| SQLite schema, migration, and rebuild policy | Keep the SQLite schema private, schema-versioned, and rebuildable. Compatible migrations may be internal; incompatible or corrupt DBs should be rebuilt from authoritative run directories when possible. Catalog recovery must not mutate run-store truth. | User confirmed the catalog remains derived and rebuildable. | Publicly documented DB schema, treating migrations as a user-facing contract, failing all reads on recoverable catalog corruption, and repairing catalog problems by changing run-store records. | The DB is an optimization and concurrency tool, not a storage contract. Rebuildability is the compatibility promise users can rely on. | Keeps persistence complexity isolated in catalog storage code and reduces pressure to preserve accidental table layouts. | Leaves room for future schema evolution, backend changes, or remote catalog adapters while keeping public result models stable. | Rebuild can be expensive for very large collections. Revisit if users need stable external SQL access or if rebuild time becomes unacceptable. |
| Concurrent access and freshness transaction model | Use SQLite transactions for catalog updates, preferably WAL mode when available, with short write transactions and per-process connections. Do not hold a DB write transaction while reading run directories. Extract summaries optimistically by checking run-local freshness before and after extraction; retry once or return an actively-changing warning if the run changes. | User confirmed concurrent writers and correctness-first behavior. | File-level JSON locking as the concurrency model, long catalog transactions around filesystem scans, trusting stale rows without verification, and accepting summaries from runs that changed during extraction. | This gives useful concurrency without coupling catalog refresh to execution locks or blocking long filesystem work under a DB write lock. | Keeps locking rules local to catalog storage and summary extraction, reducing deadlock risk with run-store locks. | Supports future incremental refresh strategies and possible background refresh without changing the public current-read guarantee. | Correctness depends on the freshness marker being cheap and reliably updated by run-store writes. Revisit if freshness checks become too broad or miss mutation classes. |
| Result, warning, and comparison contracts | Expose typed, immutable, JSON-serializable value models for summaries, filters, warnings, list results, and comparisons. Results include machine-readable warnings. Comparison entries use `same`, `different`, `left_only`, `right_only`, and `unknown`. | User confirmed warning behavior, exact-match filters, metadata-only comparison sections, and comparison statuses. | Ad hoc dictionaries only, warning text only, raising on all invalid runs, artifact payload comparison, domain metric interpretation, and unstructured diff output. | Stable value models make the Python API useful directly and let CLI JSON output be a presentation of the same contract. | Prevents CLI and catalog internals from growing separate result shapes. | Leaves room for new optional sections or filters while preserving the core result envelope. | Initial comparison will be intentionally metadata-only and may not answer domain questions. Revisit when plugin or project-owned comparison hooks are designed. |
| CLI command ownership | Add catalog commands as thin wrappers around public APIs, with a grouped `loom runs` surface for v8 commands such as `index`, `list`, and `diff`. CLI owns argument parsing, text/JSON formatting, and exit codes only. | User confirmed CLI is secondary and must be a thin wrapper over Python APIs. | CLI-owned scan/filter/diff logic, top-level commands that bypass public APIs, and duplicating freshness or warning behavior in command modules. | Existing CLI docs define the CLI as the outer layer over public APIs. Grouping many-run commands keeps v8 behavior discoverable without making the CLI the design center. | Keeps one implementation of catalog behavior and makes tests able to cover API behavior independently from presentation. | Future bundle and sweep commands can either reuse the `runs` group or call the same API layer without changing catalog internals. | Exact command spelling is lower-risk and can be refined during implementation-plan drafting. Revisit if CLI discoverability conflicts with the grouped command surface. |
| Testing strategy for scale and concurrency | Require package/import tests, model serialization tests, unit tests for filters and summary extraction, integration tests for SQLite refresh/rebuild/warnings, CLI e2e tests over temporary collections, and synthetic multi-connection concurrency tests. Do not require real clusters, network services, or project-code imports. | User confirmed correctness, concurrency, and API-first behavior; repo docs require local deterministic validation. | Real SLURM or network tests, relying only on direct-scan unit tests, skipping concurrency coverage, and treating CLI e2e as the primary behavior proof. | The highest risks are stale data, concurrent writes, and presentation/API drift; tests should target those risks directly with local fixtures. | Makes the plan reviewable and keeps future phases from hiding correctness regressions behind CLI-only tests. | Provides a base for v9 bundle/import stale-index tests and v10 sweep aggregation reuse. | Synthetic concurrency cannot prove every filesystem interleaving. Revisit if platform-specific SQLite locking issues appear in CI or user reports. |

## Practical Design Notes

Public Python API surface:

- Confirmed: public `loom.runs` package centered on a `RunCatalog` object
  facade plus small immutable value models. Internal SQLite and extraction
  modules remain private.

CLI surface:

- Group v8 commands under `loom runs`: likely `loom runs index`,
  `loom runs list`, and `loom runs diff`. CLI modules parse arguments, call the
  public API, and format text/JSON output.

Persisted records and file layout:

- Sidecar SQLite catalog under the run collection, likely
  `.loom_catalog/catalog.sqlite`.
- Catalog DB is derived and may be deleted/rebuilt.
- Run-local freshness metadata or inventory belongs to the run-store layout and
  is updated through run-store-owned writes.

Import boundaries and dependencies:

- Catalog APIs may import run-store inspection/public store APIs,
  serialization helpers, plain value models, and `sqlite3`.
- Run store must not import catalog modules.
- Pipeline runner must not import or write the catalog DB.
- CLI imports public catalog/comparison APIs.
- No new heavyweight runtime dependency is expected; SQLite is standard
  library.

Failure modes and diagnostics:

- Invalid, unreadable, partial, actively-changing, disappeared, and
  unsupported-schema runs return machine-readable warnings with current reads.
- Catalog corruption or incompatibility triggers rebuild when possible and
  remains a catalog error when unrecoverable.
- A run that changes during extraction is retried or reported as
  actively-changing/stale, not accepted as current.

Extension points and flexibility boundaries:

- Public extension boundary is the catalog/comparison result model, not the
  SQLite schema.
- Future freshness modes, remote catalogs, watcher refresh, bundle imports, and
  sweep aggregation should integrate through the catalog facade.
- Domain-specific comparison remains project or plugin owned and is deferred.

Maintainability assessment:

- The design keeps core responsibilities modular: run store owns authoritative
  state and freshness metadata, catalog owns summary extraction/indexing/query
  refresh, comparison owns metadata diffs, and CLI owns presentation.
- The main maintainability risk is the freshness protocol becoming too implicit
  across run-store write paths.

Extensibility assessment:

- Stable public value models and a facade leave room for additional filters,
  comparison sections, and backends without exposing SQLite table details.
- Keeping current-only behavior in v8 avoids committing prematurely to stale or
  strict read-mode semantics.

Flexibility and expansion assessment:

- V9 bundles can mark or refresh catalog state after import without preserving
  derived DB contents.
- V10 sweeps can reuse ordinary run summaries and filters.
- Future remote catalogs can be added as backends if the v8 public API does not
  assume local SQLite details.

Scalability and future compatibility:

- SQLite is the large-collection path for thousands of local runs and expected
  concurrent writers.
- Direct scan remains correctness fallback and rebuild source.
- Current reads may pay freshness-check overhead by design.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Private SQLite schema and run-store freshness protocol become internal compatibility surfaces. | Needed to support concurrent writers and query-time correctness in v8 without making DB rows authoritative. | Revisit if external SQL access becomes a supported use case, schema rebuild is too costly, or freshness markers miss real mutations. |
| Current-only reads can add latency for large collections. | User prioritized correctness/up-to-dateness over stale-fast reads for v8. | Revisit if read latency is unacceptable and a fast stale-tolerant mode can be added without weakening the default. |
| Metadata-only comparison will not answer domain-specific metric or artifact-payload questions. | Keeps Loom domain-neutral and avoids loading project code or large payloads. | Revisit when plugin-owned or project-owned comparison hooks are planned. |

## Phase Sketch

### Phase 1 - Public Models And Run-Store Freshness

Goal:

- Establish the public value-model vocabulary and the run-store freshness
  contract that current catalog reads depend on.

Scope:

- Add the `loom.runs` package with immutable, JSON-serializable public models
  for run summaries, artifact summaries, filters, list/index results,
  warnings, and comparison result shapes.
- Add catalog-specific errors without importing CLI code.
- Add a run-store-owned freshness/inventory protocol and local run-store
  implementation support so catalog code can cheaply detect whether a run has
  changed.
- Ensure freshness metadata is updated by run-store writes, not by the pipeline
  runner or catalog DB code.

Out of scope:

- SQLite catalog storage.
- Full collection scanning.
- CLI commands.
- Domain-specific comparison or artifact payload inspection.

Acceptance criteria:

- `loom.runs` imports are stable and cheap.
- Public models validate and serialize to plain data.
- Local run-store writes expose a freshness token or inventory that changes
  when catalog-relevant run metadata changes.
- Run-store freshness support does not import catalog or CLI modules.

Test expectations:

- Package: import checks for `loom.runs`.
- Unit: model validation, serialization, warning codes, filter validation, and
  freshness token behavior.
- Contract: run-store protocol expectations for freshness reads.
- Integration: local run-store write paths update freshness metadata.
- E2E: not required.
- Opt-in: none.

Design impact:

- This phase creates the public compatibility vocabulary and the authoritative
  freshness boundary.

Future compatibility:

- v9/v10 can reuse the same summary and warning models.
- Future catalog backends depend on the freshness protocol, not local file
  mtimes alone.

Alternatives rejected:

- Catalog-owned freshness markers.
- Runner-owned catalog updates.
- Public SQLite row models.

Debt introduced:

- Freshness coverage depends on all catalog-relevant run-store writes using the
  marker path.

Reviewability:

- Review public exports, model field names, serialization shape, and run-store
  import boundaries before downstream phases depend on them.

### Phase 2 - Direct Scan And Summary Extraction

Goal:

- Build the correctness-first path that can discover local runs and extract
  current summaries directly from authoritative run-store records.

Scope:

- Implement run collection discovery from run-store markers and local run
  directories.
- Implement summary extraction through run-store inspection/public store APIs.
- Validate freshness before and after extraction; retry or warn when a run
  changes during extraction.
- Produce warning-returning direct-scan results for invalid, unreadable,
  partial, disappeared, actively-changing, and unsupported-schema runs.
- Introduce the `RunCatalog` facade enough to open a collection and perform
  direct current scans.

Out of scope:

- SQLite persistence and indexed filtering.
- CLI commands.
- Metadata comparison beyond shared models.

Acceptance criteria:

- A Python API caller can open a local run collection and receive current
  direct-scan summaries plus warnings.
- Direct scan does not import project code or load artifact payloads.
- Invalid and partial directories are warnings by default, not whole-query
  failures.

Test expectations:

- Package: `RunCatalog` public import.
- Unit: discovery classification, summary extraction helpers, warning codes,
  and actively-changing retry behavior.
- Contract: result envelopes and `to_dict` output.
- Integration: temporary run collections with valid, invalid, partial, and
  disappearing runs.
- E2E: not required.
- Opt-in: none.

Design impact:

- This phase proves the source-of-truth path before adding the derived SQLite
  optimization.

Future compatibility:

- The direct-scan extractor becomes the rebuild source for SQLite and a fallback
  for DB corruption or missing indexes.

Alternatives rejected:

- Building SQLite first and treating direct scan as an afterthought.
- Hard-coded JSON path scraping when run-store APIs exist.

Debt introduced:

- Direct scan may be slow for large collections until indexed phases land.

Reviewability:

- Review warning behavior and extraction boundaries carefully because later
  SQLite phases cache these summaries.

### Phase 3 - SQLite Sidecar Storage And Rebuild

Goal:

- Add the private SQLite sidecar store and explicit rebuild path for large local
  collections and concurrent writers.

Scope:

- Implement schema-versioned SQLite sidecar storage under `.loom_catalog/`.
- Store derived run summaries, artifact summary rows, filterable metadata, and
  catalog metadata needed for freshness checks.
- Implement `RunCatalog.rebuild()` to scan authoritative run directories and
  replace/update derived rows transactionally.
- Configure connection behavior for local concurrent readers/writers, including
  short transactions and WAL where supported.
- Handle corrupt or incompatible DBs by rebuilding when possible.

Out of scope:

- Full refresh-on-read filtering semantics.
- CLI commands.
- Domain-specific query language.

Acceptance criteria:

- The catalog DB can be created, rebuilt, deleted, and rebuilt again from run
  directories.
- SQLite schema details are private to the catalog storage implementation.
- Multiple catalog instances can rebuild or read without corrupting the DB.

Test expectations:

- Package: no new public storage imports.
- Unit: schema version checks, row mapping, migration/rebuild decisions.
- Contract: rebuild result shape and warning serialization.
- Integration: temporary collections, DB deletion, stale row replacement,
  corrupt/incompatible DB recovery.
- E2E: not required.
- Opt-in: none.

Design impact:

- This phase introduces the derived persistence layer while preserving
  rebuildability as the public guarantee.

Future compatibility:

- V9 import can mark or rebuild this derived sidecar without treating DB rows
  as bundle contents.

Alternatives rejected:

- JSON sidecar as the concurrent-writer backend.
- Public DB schema commitment.
- DB-as-authoritative run state.

Debt introduced:

- Rebuild cost can grow with collection size.

Reviewability:

- Review transaction boundaries, schema versioning, and recovery behavior before
  list/filter APIs depend on the DB.

### Phase 4 - Current Listing, Refresh, And Filters

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
- Return machine-readable warnings alongside results.
- Ensure direct-scan fallback remains available when the DB is missing,
  rebuilding, or recoverably corrupted.

Out of scope:

- Fast stale-tolerant mode.
- Strict fail-on-uncertainty mode.
- Time/range filters unless needed internally for stable ordering.
- CLI commands.

Acceptance criteria:

- Public API list calls return current summaries and warnings.
- Stale DB rows are not presented as current without validation.
- Deleted run directories are reconciled before query results are returned.
- Filters are evaluated through the API and backed by SQLite where useful.

Test expectations:

- Package: public API exports unchanged.
- Unit: filter compilation/validation, freshness reconciliation decisions, and
  warning aggregation.
- Contract: list result JSON shape and warning codes.
- Integration: stale rows, changed runs, deleted runs, missing DB, corrupt DB,
  concurrent readers/writers, and thousands-of-runs synthetic fixture coverage.
- E2E: not required.
- Opt-in: none.

Design impact:

- This phase delivers the core correctness/performance guarantee for many-run
  queries.

Future compatibility:

- Future read modes or backends can plug into the facade after this current
  behavior remains the default.

Alternatives rejected:

- Periodic full reindex as the correctness mechanism.
- Querying stale DB rows and surfacing only a staleness warning.
- CLI-owned filtering logic.

Debt introduced:

- Current reads pay refresh overhead.

Reviewability:

- Review freshness guarantees, transaction scope, and filter semantics with
  concurrency tests as evidence.

### Phase 5 - Metadata Comparison API

Goal:

- Implement metadata-only run comparison through the public Python API.

Scope:

- Compare two runs by persisted metadata using the confirmed sections: run
  status/timestamps, config and pipeline fingerprints, stage status and
  fingerprints, artifact identities/checksums, executor/backend identity, and
  selected provenance facts.
- Use current summaries and targeted direct extraction where needed.
- Return structured comparison sections and entries with `same`, `different`,
  `left_only`, `right_only`, and `unknown`.
- Surface warnings for missing, unsupported, or unreadable comparison inputs.

Out of scope:

- Artifact payload diffs.
- Domain metric interpretation.
- Plugin comparison hooks.
- CLI diff command.

Acceptance criteria:

- `RunCatalog.compare(left, right)` returns a structured metadata comparison.
- Missing or unsupported metadata becomes explicit comparison output or
  warnings rather than domain-specific failures.
- Comparison does not import project code.

Test expectations:

- Package: comparison models exported from `loom.runs`.
- Unit: entry status computation, section ordering, missing metadata handling.
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

- Review section boundaries and status semantics independently from CLI
  formatting.

### Phase 6 - CLI Integration, Docs, And End-To-End Coverage

Goal:

- Expose the completed catalog and comparison behavior through thin CLI
  wrappers and update user-facing documentation.

Scope:

- Add a `loom runs` command group with likely subcommands `index`, `list`, and
  `diff`.
- Support text and JSON output using public API result models.
- Map catalog warnings and errors through existing CLI formatting and exit-code
  conventions.
- Update relevant feature docs, CLI docs, and implementation-plan evidence
  expectations.
- Add end-to-end CLI tests over temporary local collections.

Out of scope:

- CLI-specific catalog logic.
- Background daemon or watcher commands.
- Export/import bundle commands.
- Sweep commands.

Acceptance criteria:

- CLI commands call `loom.runs` APIs and do not duplicate scan/filter/diff
  behavior.
- Human output is concise; JSON output preserves API result/warning data.
- Existing validation commands continue to pass.

Test expectations:

- Package: no CLI import regressions.
- Unit: CLI argument parsing and formatting helpers.
- Contract: JSON output envelopes and warning serialization.
- Integration: CLI command handlers with temporary stores.
- E2E: `loom runs index`, `loom runs list`, filtered list, and `loom runs diff`
  over synthetic run collections.
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

Debt introduced:

- Exact command spelling may need later adjustment if future bundle/sweep
  grouping changes CLI organization.

Reviewability:

- Review API/CLI layering and JSON compatibility rather than re-litigating
  catalog internals.

## Handoff

Planning-notes readiness:

- Complete. `docs/roadmap/stage-8/implementation-plan.md` was drafted
  from these notes after explicit user confirmation.

Source inputs for implementation-plan draft:

- `docs/roadmap/stage-8/planning.md`
- `docs/roadmap.md`
- `docs/roadmap/stage-7/implementation-plan.md`
- `docs/features/run-catalog.md`
- `docs/features/run-store.md`
- `docs/features/artifacts.md`
- `docs/features/provenance.md`
- `docs/features/cli.md`
- `docs/features/testing.md`
- `docs/loom.md`
- `docs/structure.md`

Unresolved assumptions:

- The final implementation plan should verify current v7 run-store write paths
  before assigning exact freshness-marker update locations.
- The final implementation plan should decide exact private filenames and table
  names, but those are implementation details behind the public API.
- The final implementation plan should preserve the confirmed
  `loom.runs.RunCatalog` public facade and avoid public SQLite schema exposure.

Blockers:

- None known for implementation-plan drafting.

Plan-quality-gate risks:

- Public API design and persisted catalog schema require expanded-path phase
  planning/review.
- Concurrency and freshness guarantees require focused integration tests,
  including synthetic multi-connection SQLite coverage.
- The run-store freshness protocol could miss catalog-relevant mutations if the
  implementation plan does not enumerate write paths carefully.
- Current refresh-on-read could become expensive for large collections; the plan
  should record accepted latency debt and revisit triggers.
