# Phase 3 Execution Plan: SQLite Sidecar Storage And Rebuild

## Metadata

- Status: pr_open
- Feature focus: Run Catalog And Comparison
- PR title: `Run Catalog And Comparison - Phase 3: SQLite Sidecar Storage And Rebuild`
- Branch: `codex/run-catalog-sqlite`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-catalog-sqlite`
- Phase execution plan path: `docs/phases/run-catalog-sqlite.md`
- Full plan: `docs/implementation-plans/implementation-plan-v8.md`
- Source phase: Phase 3 - SQLite Sidecar Storage And Rebuild
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- PR: https://github.com/samcantrill/loom/pull/97
- Merge eligibility: merge-eligible after automated review, local validation, and GitHub checks because Phases 1 and 2 are merged and this is a root phase targeting `develop`
- Workflow path: expanded path because this phase introduces private SQLite schema, persistence, recovery, and local concurrency behavior
- Successor dependency notes: Phase 4 depends on the private sidecar storage and rebuild APIs for current listing, refresh, filters, and stale-row reconciliation.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v8.md` on 2026-05-09; the plan records initial review, refinement, and confirmation review as complete.
- Plan quality gate loop budget: initial review used; gate refinement used; confirmation review used.
- Draft pass: completed by `loom_phase_planner`
- Refine pass: completed in the same planning artifact for the expanded path; no unresolved blockers remain.
- Setup limitations: worktree and branch were created from local `develop` at commit `c463f2f`, which records the Phase 2 merge.
- Blockers: none

## Objective

Add the private rebuildable SQLite sidecar under the local run collection so large collections and concurrent catalog readers/writers can share derived run summaries without making the database authoritative.

## Full-Plan Context

V8 keeps run-store metadata as the source of truth. Phase 1 delivered public `loom.runs` models, warning codes, and store-owned freshness records. Phase 2 delivered direct current scanning and metadata-only extraction in private helpers. This phase adds only private SQLite persistence and an explicit rebuild path. It must not implement refresh-on-read listing, filter query semantics, CLI commands, comparison behavior, or public SQL access.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phases 1 and 2 are merged into `develop`
- Why this base branch is correct: the assignment requires current `develop`, and `develop` contains the public model, freshness, direct-scan, and extraction contracts this phase consumes.
- Retarget/rebase plan after predecessor merge: none; PR targets `develop` directly.
- Branch cleanup constraints: branch may be deleted after merge if no successor branch is stacked on it.

## Source Phase Summary

- Goal: add private schema-versioned SQLite sidecar storage and explicit rebuild support for local run collections.
- Required scope: `.loom_catalog/catalog.sqlite` creation; schema metadata; derived run summaries, artifacts, filterable metadata, and freshness evidence; `RunCatalog.rebuild()`; transaction-safe replacement of derived rows; local connection policy for concurrent readers/writers; recoverable corrupt or incompatible DB handling; private storage modules only.
- Required exclusions: no full refresh-on-read filtering semantics, CLI commands, domain-specific query language, public SQL schema docs, runner/executor catalog writes, or run-store mutation during catalog recovery.
- Acceptance criteria:
  - The catalog DB can be created, rebuilt, deleted, and rebuilt again from run directories.
  - SQLite schema details are private to catalog storage implementation.
  - Multiple catalog instances can rebuild or read without corrupting the DB.
  - Rebuild results include warnings for invalid or skipped runs.
  - Recoverable corruption or incompatibility produces a rebuild path, not run-store mutation.

## Current Source And Harness Findings

- `src/loom/runs/catalog.py` exposes `RunCatalog.rebuild()` as a deferred public facade method and `scan_current()` as the direct-scan path.
- `src/loom/runs/models.py` already provides `CatalogIndexResult`, `ListRunsResult`, `RunSummary`, `StageSummary`, `ArtifactSummary`, `SubmittedOperationSummary`, `RunFilter`, and stable warning codes including stale/corrupt and unrecoverable catalog errors.
- `src/loom/runs/_scan.py` discovers local run candidates and ignores `.loom_catalog`.
- `src/loom/runs/_extract.py` validates run freshness before and after extraction and returns metadata-only `RunSummary` values plus warnings.
- `docs/structure.md` reserves `src/loom/runs/_sqlite.py` as private derived sidecar storage and forbids lower layers from importing `loom.runs`.
- `tests/package/test_runs_api.py` currently asserts `import loom.runs` does not import `sqlite3`; keep that true by lazy-loading any SQLite implementation from facade methods or private modules.
- Current run-catalog tests live in `tests/unit/loom/runs/`; no integration run-catalog test file exists yet beyond direct-scan unit coverage.

## In-Scope Work

- Add a private SQLite module, expected as `src/loom/runs/_sqlite.py`, loaded only by rebuild/storage paths.
- Use standard-library `sqlite3` only; no runtime dependency addition is justified.
- Store the sidecar at `.loom_catalog/catalog.sqlite` under the collection path, creating the sidecar directory as needed.
- Define a private schema version in a metadata table and private tables for:
  - run summary rows keyed by canonical `run_uri`;
  - serialized summary payloads sufficient to reconstruct `RunSummary`;
  - normalized filterable facts needed by later Phase 4 exact-match filters, including run status, tags, config fingerprint, pipeline fingerprint, git commit, stage status, artifact identity/checksum, executor, and backend;
  - artifact and stage summary rows where useful for Phase 4 queries or future comparison reads;
  - freshness evidence from `RunFreshnessRecord` so later phases can detect stale derived rows.
- Implement `RunCatalog.rebuild()` to direct-scan the authoritative collection, write derived summaries transactionally, and return `CatalogIndexResult` with indexed/skipped counts, warnings, and `checked_at`.
- Replace stale derived rows during rebuild, including rows for runs that disappeared or are skipped with warnings.
- Configure connections for local concurrency: per-call/per-instance connections, short transactions, `busy_timeout`, and WAL mode where available on the local filesystem.
- Keep DB write transactions outside filesystem scan and summary extraction. Rebuild should first obtain direct-scan results, then write the derived state in one short transaction or small bounded transactions.
- Detect missing, corrupt, or incompatible DB files as catalog-side problems and rebuild when possible.
- Convert unrecoverable storage failures into catalog storage errors or `CatalogIndexResult` warnings without mutating run-store truth.
- Add focused package, unit, contract, and integration tests for private storage and rebuild behavior.

## Out-of-Scope Work

- `RunCatalog.list()` current refresh-on-read behavior, indexed filtering, query compilation, deterministic list ordering, stale-row reconciliation on reads, or fast/strict read modes.
- `loom runs` CLI commands, text/JSON formatting, exit codes, or user-facing docs beyond phase artifact needs.
- Metadata comparison implementation.
- Public SQL schema, migrations as a supported external contract, or documentation that invites direct SQL querying.
- Any project-code imports, artifact payload loading, domain-specific metric/report interpretation, hosted tracker, daemon, filesystem watcher, or external database service.
- Any `PipelineRunner`, executor, or run-store write path that writes the collection catalog database directly.

## Assumptions

- `CatalogIndexResult` is the rebuild result shape for this phase; no new public result type is needed unless implementation finds a missing field that cannot be represented by indexed/skipped counts, warnings, and `checked_at`.
- Private row payloads may serialize public models with existing `to_dict()` plain-data shapes. This does not make the SQL schema public.
- The schema can be rebuild-only in this phase. In-place migrations are not required unless needed to distinguish incompatible versions from corrupt files.
- WAL is best-effort. Tests should assert behavior through successful local multi-connection operations, not through platform-specific journal-file details.
- Direct scan remains the source of summary truth for rebuild. The storage layer should not reimplement discovery, extraction, or freshness retry.

## Scope Contract

`RunCatalog.open(path).rebuild()` must build or replace private derived SQLite state from authoritative run directories under `path`. It may call direct-scan helpers, but it must not query stale SQLite rows to decide which summaries are current. The returned `CatalogIndexResult` must count summaries actually written and skipped warning cases from the scan/rebuild.

SQLite tables are private implementation details. The only public contract is the facade method, existing public value models, warnings, and errors. The implementation may add private helpers for later Phase 4 reads, but it must not expose those helpers from `loom.runs.__all__`.

Run-store truth is immutable from the catalog perspective. If the catalog DB is missing, corrupt, incompatible, locked, or unrecoverable, recovery may delete or replace only derived sidecar files and rows. It must not edit run directories, freshness files, run metadata, artifacts, stage records, submitted-operation records, or provenance.

## Risky Decisions

- Private schema shape: include enough normalized facts for Phase 4 filters without overfitting to public SQL access. The executor should keep the schema small and explain any denormalization in tests or comments.
- Corruption recovery: distinguish recoverable DB corruption or incompatible schema from filesystem permission and locking errors. Rebuild is safe only for derived sidecar state.
- Transaction boundary: scan before write. Holding a write transaction while reading run directories is explicitly forbidden.
- Concurrency smoke coverage: test real multiple-connection behavior with local temporary files and timeouts, but do not create flaky thread timing tests that depend on exact SQLite scheduling.
- Import boundary: `sqlite3` must remain absent from `import loom.runs`; SQLite loading belongs behind rebuild/private storage paths.

## Design Impact

- Maintainability: isolates persistence in private `loom.runs` storage code and keeps direct scan/extraction as the only source of derived summary data.
- Extensibility: Phase 4 can query private SQLite rows for current listing and filters while preserving the public facade and model contracts. Future v9 bundle import can delete or rebuild the sidecar instead of preserving DB contents.
- Domain neutrality: stored summaries remain Loom metadata only; no artifact payloads or project semantics are introduced.
- Concurrency: standard-library SQLite becomes the local coordination mechanism for derived catalog state, with short transactions and no runner coupling.
- Source-tree boundaries: `loom.runs` may read run-store inspection/freshness data, but stores, execution, executors, and CLI must not import catalog storage.

## Future Compatibility

The sidecar must be rebuildable and disposable. Future migrations, v9 bundle import, v10 sweep aggregation, remote catalogs, and optional read modes should be able to either reuse the private storage helper or replace it behind `RunCatalog` without changing public models. Schema metadata should make incompatible DBs detectable so future versions can choose rebuild, migration, or a clear unrecoverable warning.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| JSON sidecar as the concurrent-writer backend | The v8 plan expects concurrent catalog readers/writers and thousands-of-runs listing; SQLite gives transaction and query support in the standard library. |
| Public SQL schema | Freezes private storage before list/filter behavior is complete and weakens the rebuildable-derived-index guarantee. |
| DB-as-authoritative run state | Violates the run-store source-of-truth design; deleting the DB must not lose run information. |
| Long rebuild transaction around scan and extraction | Would hold write locks while reading run directories and increase concurrency and active-run risk. |
| Runner or executor writes into the sidecar | Couples execution to a derived optimization and bypasses store-owned freshness. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Private schema becomes an internal compatibility burden. | Needed for indexed local reads and concurrent writers without adding an external database. | Rebuilds become too expensive, Phase 4 requires repeated schema churn, or users need supported external SQL access. |
| Rebuild cost grows with collection size. | Rebuild is the correctness and recovery path; incremental refresh is assigned to Phase 4. | Rebuild validation becomes impractical for expected local collections or v9 bundle import needs faster refresh. |
| WAL behavior is platform-dependent. | SQLite WAL is useful where available, but Loom must remain local-filesystem deterministic. | Temporary-file tests show unreliable behavior on supported platforms or network filesystems become a target. |
| Corrupt/incompatible catalog handling is coarse-grained. | Rebuildability is more important than preserving derived rows in v8. | Future versions need durable migration of expensive derived metadata. |

## Reviewability

- Expected PR size and shape: focused private storage and rebuild PR, with lazy facade wiring and tests. No CLI, list/filter query API, comparison, or runner changes.
- Files and areas to inspect:
  - `src/loom/runs/catalog.py`
  - new `src/loom/runs/_sqlite.py`
  - `src/loom/runs/_scan.py` only if the sidecar ignore rule or reusable scan API needs a small adjustment
  - `src/loom/runs/models.py` only if `CatalogIndexResult` needs a narrowly justified addition
  - `tests/package/test_runs_api.py`
  - new or updated `tests/unit/loom/runs/`
  - new integration coverage under `tests/integration/pipeline/` or `tests/integration/loom/runs/` following existing layout
- Scope-control checks: no public SQL exports, no `sqlite3` import during `import loom.runs`, no `RunCatalog.list()` behavior, no CLI modules, no comparison implementation, no project imports, no artifact payload reads, and no store/execution writes to `.loom_catalog`.

## Implementation Steps

1. Add private SQLite connection, path, schema-version, and schema-initialization helpers with lazy `sqlite3` import.
2. Add row mapping helpers from `RunSummary` and `RunFreshnessRecord` evidence into private tables, plus reconstruction helpers only if tests or Phase 4 prep need them.
3. Wire `RunCatalog.rebuild()` to scan first, then replace derived SQLite state in a short transaction and return `CatalogIndexResult`.
4. Add corruption/incompatible-version detection and rebuild behavior for recoverable sidecar failures.
5. Add deterministic unit and integration tests for DB path handling, schema metadata, rebuild counts, warning propagation, stale row replacement, DB deletion/rebuild, corruption/incompatibility recovery, and multi-connection smoke behavior.
6. Keep package import-boundary tests current, especially the absence of `sqlite3` after importing `loom.runs`.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_runs_api.py` and `tests/package/test_import_boundaries.py` if needed.
- Required assertions or deferral reason: `import loom.runs` and `from loom.runs import RunCatalog` remain stable and do not import `sqlite3`, concrete local stores, CLI, execution, executors, optional config dependencies, project packages, or artifact codecs. No private SQLite storage names are exported from `loom.runs.__all__`.

### Unit Suite

- Status: required
- Expected paths: new tests under `tests/unit/loom/runs/`, likely `test_sqlite_storage.py`, plus focused updates to facade/model tests if needed.
- Required assertions or deferral reason: sidecar path resolution; schema creation and version checks; incompatible-version and corrupt-DB decisions; transaction helper rollback behavior; summary, stage, artifact, tag, filterable fact, submitted-operation, and freshness-evidence row mapping; rebuild result counts and warning propagation with stubbed scan results; lazy import behavior for private storage.

### Contract Suite

- Status: required
- Expected paths: existing public model contract tests if present, or a focused new contract test for rebuild result serialization.
- Required assertions or deferral reason: `CatalogIndexResult.to_dict()` remains JSON-safe for rebuild outputs, warnings retain stable public codes, and the rebuild facade returns public result data without exposing SQLite row shapes. If no dedicated contract suite pattern fits, record the coverage in package/unit tests and keep contract suite unchanged.

### Integration Suite

- Status: required
- Expected paths: new `tests/integration/pipeline/test_run_catalog_sqlite.py` or the nearest existing integration location for run-catalog behavior.
- Required assertions or deferral reason: temporary local collections can rebuild the DB from valid runs; invalid/partial/skipped candidates become warnings; deleting `.loom_catalog/catalog.sqlite` and rebuilding succeeds; stale rows from a prior rebuild are removed or replaced; corrupt or incompatible DB files are recovered by rebuilding when possible; multiple `RunCatalog` instances or connections can rebuild/read without corrupting the DB; run-store files are unchanged by catalog recovery.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase.
- Required assertions or deferral reason: no user-facing CLI workflow or full list/filter behavior is introduced until later v8 phases.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected.
- Required assertions or deferral reason: this phase uses only local filesystem and standard-library SQLite. No network, live scheduler, external service, config-extra, or heavy opt-in behavior is introduced.

## Risks

- SQLite lock behavior can become flaky if tests depend on precise timing. Prefer simple multi-connection smoke tests with short busy timeouts and deterministic cleanup.
- Corrupt DB recovery can accidentally hide permission or data-loss bugs. Only sidecar files may be rebuilt or replaced; run directories must remain untouched.
- Over-normalizing the private schema can turn Phase 3 into Phase 4. Store enough filterable facts for later phases, but leave actual current-list filtering and refresh semantics out of scope.
- Reusing direct scan means rebuild inherits scan warnings and latency. That is intentional for correctness; performance tuning belongs after indexed reads exist.
- Adding `sqlite3` to public imports would violate package import-light guarantees and should block the phase.

## Stop Conditions

- The executor cannot implement sidecar rebuild without changing public model contracts or exposing SQL schema.
- Rebuild requires modifying run-store truth, runner behavior, executor behavior, or project-code imports.
- Direct-scan helpers cannot provide current summaries and warnings without broad refactoring outside Phase 3 scope.
- SQLite concurrency cannot be tested deterministically on local temporary files.
- Corrupt or incompatible DB recovery risks deleting or mutating anything outside `.loom_catalog`.
- Targeted validation shows package import boundaries are broken and cannot be restored within this phase.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_runs_api.py tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/runs
uv run pytest tests/integration/pipeline/test_run_catalog_sqlite.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: private `_sqlite.py` path/schema helpers first; row mapping and transaction helpers next; `RunCatalog.rebuild()` facade wiring next; recovery and concurrency tests last.
- Tests to run with each slice: package import tests after any facade/private import change; unit storage tests after schema and mapping helpers; integration rebuild tests after facade wiring; full `make validate-pr` and `make test-summary` during PR preparation.
- Decisions the executor must not revisit: SQLite is private and derived; direct scan is the rebuild source; `run_uri` remains canonical identity; WAL is best-effort; no list/filter, CLI, comparison, public SQL, artifact payload, project import, runner write, or executor write behavior belongs in this phase.
- Conditions that require stopping for the manager: any stop condition above, a need for public API/schema expansion, or a storage recovery path that cannot be made safe for run-store truth.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed after targeted validation, full
  PR validation, and manager scope review passed without concrete
  storage/concurrency blockers.
- PR review: pending
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on 2026-05-09
- Refined plan: completed by `loom_phase_planner` on 2026-05-09
- Final phase execution plan: implemented
- Implementation summary: Added private `_sqlite.py` sidecar storage under
  `.loom_catalog/catalog.sqlite`, schema metadata, summary/stage/artifact/
  submitted-operation/filter-fact tables, freshness evidence persistence,
  recoverable corrupt/incompatible DB rebuild, private summary readback helpers,
  and `RunCatalog.rebuild()` facade wiring. Extended private scan/extract
  helpers to return freshness evidence for rebuild while keeping public
  `scan_current()` unchanged.
- Validation evidence:
  - `uv run ruff check src/loom/runs tests/unit/loom/runs tests/integration/pipeline/test_run_catalog_sqlite.py`
    passed.
  - `uv run pyright src/loom/runs tests/unit/loom/runs tests/integration/pipeline/test_run_catalog_sqlite.py`
    passed.
  - `uv run pytest tests/package/test_runs_api.py tests/package/test_import_boundaries.py tests/unit/loom/runs tests/integration/pipeline/test_run_catalog_sqlite.py`
    passed with 45 tests.
  - `make validate-pr` passed: Ruff, Pyright, default test harness,
    config-extra test harness, and build.
  - `make test-summary` passed and wrote `build/test-summary.md`: package 55
    passed, unit 748 passed, contract 73 passed, integration 51 passed, e2e 36
    passed, config-extra 413 passed.
- PR preparation: completed; PR #97 opened at
  https://github.com/samcantrill/loom/pull/97 and verified with base
  `develop` and head `codex/run-catalog-sqlite`.
- PR: https://github.com/samcantrill/loom/pull/97
