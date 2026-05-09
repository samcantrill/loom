# Phase 4 Execution Plan: Current Listing, Refresh, And Filters

## Metadata

- Status: in_progress
- Feature focus: Run Catalog And Comparison
- PR title: `Run Catalog And Comparison - Phase 4: Current Listing, Refresh, And Filters`
- Branch: `codex/run-catalog-current-list`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-catalog-current-list`
- Phase execution plan path: `docs/phases/run-catalog-current-list.md`
- Full plan: `docs/implementation-plans/implementation-plan-v8.md`
- Source phase: Phase 4 - Current Listing, Refresh, And Filters
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- PR: pending
- Merge eligibility: merge-eligible after implementation, automated review, local validation, and GitHub checks because Phases 1 through 3 are merged and this is a root phase targeting `develop`
- Workflow path: expanded path because this phase spans SQLite current-read semantics, refresh/reconciliation, exact-match filters, stale-row correctness, and local concurrency behavior
- Successor dependency notes: Phase 5 may use current summaries from `RunCatalog.list()` when comparing runs, but Phase 4 must not implement comparison behavior.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v8.md` on 2026-05-09; the plan records initial review, refinement, and confirmation review as complete.
- Plan quality gate loop budget: initial review used; gate refinement used; confirmation review used.
- Draft pass: completed by `loom_phase_planner`
- Refine pass: completed in this planning artifact for the expanded path; no unresolved blockers remain.
- Setup limitations: worktree and branch were created from local `develop` at commit `7cade2d`, which records the Phase 3 merge. Creating the branch/worktree required approved local Git metadata writes because sandboxed `.git` ref writes were read-only.
- Blockers: none

## Objective

Implement `RunCatalog.list()` as the default current indexed read path: reconcile the private SQLite sidecar with authoritative run-store freshness during the read operation, query exact-match filters, return deterministic summaries plus machine-readable warnings, and never present stale catalog rows as current without validation.

## Full-Plan Context

V8 keeps run-store metadata authoritative and treats SQLite as a private rebuildable sidecar. Phase 1 delivered public `loom.runs` models, warning codes, filters, and run-store freshness. Phase 2 delivered direct scan and metadata-only extraction with before/after freshness validation. Phase 3 delivered private SQLite storage and `RunCatalog.rebuild()`.

This phase connects those pieces into the core listing guarantee. It may expand private storage helpers and facade wiring, but it must not add CLI commands, comparison behavior, new read modes, public SQL contracts, artifact payload reads, project-code imports, or runner/executor writes to `.loom_catalog`.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phases 1, 2, and 3 are merged into `develop`
- Why this base branch is correct: the assignment requires current `develop`, and `develop` contains the public models, direct scan/extraction helpers, and private SQLite sidecar needed by Phase 4.
- Retarget/rebase plan after predecessor merge: none; PR targets `develop` directly.
- Branch cleanup constraints: branch may be deleted after merge if no successor branch is stacked on it.

## Source Phase Summary

- Goal: make `RunCatalog.list()` return current indexed results by refreshing the SQLite catalog on read before querying.
- Required scope: collection census against DB rows and run-store freshness metadata; refresh changed, missing, deleted, and newly discovered runs before returning results; exact-match filters for run status, tag key/value, config fingerprint, pipeline fingerprint, git commit, stage status, artifact identity/checksum, and executor/backend identity; warning-returning results; direct-scan fallback for missing/rebuilding/recoverably corrupt DBs; deterministic result ordering.
- Required exclusions: no fast stale-tolerant mode, strict fail-on-uncertainty mode, partial-text search, fuzzy matching, advanced query language, public time/range filters, CLI commands, comparison behavior, public SQL schema, or catalog writes from runner/executor code.
- Acceptance criteria:
  - Public API list calls return current summaries and warnings.
  - Current means validated/refreshed against run-store freshness during the read operation; returned summaries do not claim continuous freshness after concurrent writers mutate run-store state.
  - Stale DB rows are not presented as current without validation.
  - Changed, missing, new, and deleted runs are reconciled before query results are returned.
  - Filters are evaluated through the API and backed by SQLite where useful.
  - Warning behavior remains nonfatal for ordinary invalid-run conditions.
  - Concurrent readers/writers do not corrupt the catalog and do not accept actively changing summaries as current.

## Current Source And Harness Findings

- `src/loom/runs/catalog.py` exposes `RunCatalog.rebuild()` and `scan_current()`, while `list()` still raises `CatalogFeatureUnavailableError`.
- `src/loom/runs/models.py` already provides `RunFilter`, `RunFilterKind`, `ListRunsResult`, `RunSummary`, `CatalogWarning`, and the required warning codes. No new public result envelope is expected for this phase.
- `src/loom/runs/_scan.py` and `src/loom/runs/_extract.py` provide current direct-scan records and freshness-validated summary extraction for local collections.
- `src/loom/runs/_sqlite.py` owns the private sidecar path, schema version, rebuild logic, normalized `filter_facts`, freshness evidence columns, corrupt/incompatible DB recovery, and `read_catalog_summaries()` for private reads/tests.
- Existing run-catalog tests cover model contracts, direct scan helpers, SQLite rebuild storage, stale-row replacement during rebuild, corrupt sidecar recovery, and multi-catalog rebuild smoke coverage.
- Package import tests assert `import loom.runs` remains cheap; Phase 4 must keep SQLite and concrete local-store imports lazy behind list/rebuild/scan paths.

## In-Scope Work

- Replace the deferred `RunCatalog.list()` with a typed public facade method, expected as `list(filters: Sequence[RunFilter] = ()) -> ListRunsResult`.
- Add or extend private SQLite helpers for current listing, including:
  - loading DB row freshness evidence;
  - comparing DB rows with authoritative `RunFreshnessStore` records;
  - identifying new, changed, deleted, missing, and unreadable/invalid candidates;
  - replacing refreshed rows and deleting rows for disappeared runs in short transactions;
  - querying summaries by exact-match filters and deterministic ordering.
- Reuse direct-scan/extraction helpers for refresh of new or changed runs. Do not duplicate summary extraction in SQL code.
- Preserve direct-scan fallback and rebuild recovery for missing, deleted, or recoverably corrupt/incompatible DBs.
- Return `ListRunsResult` with `summaries`, `warnings`, requested `filters`, and `checked_at`. `checked_at` is the public freshness evidence for this phase; private freshness tokens remain internal unless implementation proves an existing public model cannot represent a necessary warning.
- Implement exact-match filter semantics:
  - all supplied filters are conjunctive;
  - run-level filters match rows by exact value;
  - tag filters require `key` and match one tag key/value pair;
  - stage-status filters use `key` as an optional stage name selector, with `None` meaning any stage with the status;
  - artifact identity and checksum filters use `key` as an optional logical name or artifact selector, with `None` meaning any artifact with the value;
  - unsupported key/value combinations should fail validation through `CatalogValidationError` rather than silently widening a query.
- Use deterministic default ordering by canonical `run_uri` unless a narrower existing convention already exists in private storage. Do not add public sort controls in this phase.
- Add focused package, unit, contract, and integration coverage for current refresh, filters, warnings, ordering, recovery, and concurrency.

## Out-of-Scope Work

- Fast stale-tolerant list mode or strict fail-on-uncertainty mode.
- Public sorting controls, time/range filters, substring search, fuzzy search, OR groups, arbitrary predicates, or a general query language.
- CLI commands, text/JSON formatting, exit-code behavior, or user-facing command docs.
- Metadata comparison, comparison sections, or `RunCatalog.compare()` implementation.
- Public SQLite schema docs, external SQL compatibility, or public storage helper exports.
- Artifact payload loading, project-code imports, domain-specific metrics/report interpretation, hosted tracker, daemon, filesystem watcher, or external database service.
- Any `PipelineRunner`, executor, or run-store write path that writes the collection catalog database directly.

## Assumptions

- `ListRunsResult.checked_at` is sufficient public evidence for the bounded current-read claim. Per-run freshness tokens stay private to the sidecar and warning details.
- `RunCatalog.list()` may create or repair the sidecar as part of a current read because the DB is derived and rebuildable.
- Full direct-scan/rebuild fallback is acceptable when the DB is missing or recoverably corrupt; performance tuning beyond thousands-of-runs synthetic coverage is not part of this phase.
- The SQLite sidecar may be unavailable because another process is rebuilding. The implementation should wait only through configured SQLite busy timeouts, then return or raise an unrecoverable catalog error according to existing warning/error contracts.
- Multiple filters are ANDed. OR behavior can be added later with an explicit public query model if users need it.
- Result ordering by `run_uri` is stable, domain-neutral, and does not require adding public time/range semantics.

## Scope Contract

`RunCatalog.open(path).list(filters=...)` must return only summaries that were validated or refreshed against authoritative run-store freshness during that call. The method may consult the private SQLite catalog for performance, but it must reconcile DB state before returning query results.

The reconciliation contract is:

- new run directories are discovered and indexed or warned before query results are returned;
- DB rows whose freshness evidence differs from run-store freshness are refreshed or warned as actively changing/unreadable/invalid before query results are returned;
- DB rows whose authoritative run directories disappeared are removed from current query results and may emit disappeared-run warnings;
- missing or recoverably corrupt sidecars are rebuilt from authoritative runs;
- unrecoverable sidecar failures do not mutate run-store truth.

The bounded consistency claim ends when the result is returned. The method does not claim continuous freshness if another process mutates run-store state afterward.

## Risky Decisions

- Refresh granularity: prefer targeted per-run reconciliation for changed/new/deleted rows, but fall back to direct scan or rebuild when DB state cannot be trusted. Do not present stale rows to preserve latency.
- Filter semantics: keep exact-match AND semantics simple and typed. Reject ambiguous key usage rather than broadening results unexpectedly.
- Transaction scope: perform filesystem census and summary extraction outside DB write transactions; use short transactions only to replace refreshed rows and delete disappeared rows.
- Recovery behavior: recover corrupt/incompatible derived DBs by rebuilding, but distinguish permission, readonly, and long-lived locking failures from safe rebuild cases.
- Concurrent mutation: if a run changes during extraction, reuse direct-scan retry behavior and surface `actively_changing_run` rather than accepting an unstable summary.
- Public evidence: use `checked_at` and warnings rather than adding per-run public freshness fields in this phase, preserving model compatibility for future read modes.

## Design Impact

- Maintainability: centralizes current-list correctness behind `RunCatalog.list()` and private SQLite helpers while reusing direct extraction as the only summary source.
- Extensibility: future stale-tolerant or strict modes can become explicit facade options without weakening default current behavior. Future backends can preserve `ListRunsResult` and filter semantics while replacing storage internals.
- Domain neutrality: filters operate on generic persisted Loom metadata only; there is no project metric, report, or artifact payload interpretation.
- Concurrency: correctness depends on SQLite short transactions plus run-store freshness checks, not runner-to-catalog coupling.
- Source-tree boundaries: `loom.runs` may read run-store freshness/inspection through existing protocols, but stores, execution, executors, and CLI must not import catalog code.

## Future Compatibility

Phase 4 should leave the public surface small: `RunCatalog.list()` with exact-match `RunFilter` values and `ListRunsResult`. Future v9 bundles can rebuild or refresh the derived sidecar after import. Future v10 sweeps can reuse list filters for aggregation. Later read modes, sort controls, pagination, or richer queries should be additive and explicit rather than changing default current semantics.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Periodic full reindex as the correctness mechanism | It leaves stale windows and contradicts the default current-read guarantee. |
| Query stale DB rows and return a staleness warning | V8 requires default list results to be validated/refreshed before presentation. |
| CLI-owned filtering logic | Python API is the compatibility center; CLI commands arrive later as wrappers. |
| Public SQL queries against `filter_facts` | Freezes private schema and bypasses warning/current-read semantics. |
| Long DB write transaction around census and extraction | Increases lock contention and active-run risk; filesystem reads belong outside write transactions. |
| Adding OR/fuzzy/range filters now | Expands public query semantics before exact-match correctness is proven. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Current reads pay refresh overhead. | Correctness and up-to-dateness are the v8 default priority. | Read latency becomes unacceptable and a stale-tolerant mode can be added without weakening default reads. |
| Filter semantics are intentionally narrow ANDed exact matches. | Keeps the first public query contract reviewable and stable. | Users need OR groups, pagination, sorting, or range filters for real workflows. |
| Private SQLite query helpers become more complex. | Necessary to reconcile derived rows with authoritative freshness while supporting indexed filters. | Query/reconciliation code becomes hard to reason about or alternate backends are planned. |
| `checked_at` is coarse result-level evidence. | Avoids adding public per-run freshness fields before read modes settle. | JSON consumers need per-run freshness evidence for audit workflows. |

## Reviewability

- Expected PR size and shape: focused facade plus private SQLite refresh/query helpers and tests. No CLI, comparison, public SQL, runner, or executor changes.
- Files and areas to inspect:
  - `src/loom/runs/catalog.py`
  - `src/loom/runs/_sqlite.py`
  - `src/loom/runs/_scan.py` and `src/loom/runs/_extract.py` only for small reusable refresh/census hooks
  - `src/loom/runs/models.py` only for narrowly justified validation tightening
  - `tests/package/test_runs_api.py`
  - `tests/unit/loom/runs/test_sqlite_storage.py`
  - new or updated `tests/unit/loom/runs/test_current_listing.py`
  - `tests/contracts/test_run_catalog_contract.py` if a new contract file is clearer than extending existing model tests
  - new or updated `tests/integration/pipeline/test_run_catalog_current_list.py`
- Scope-control checks: no CLI modules, no comparison implementation, no public SQL exports, no artifact payload reads, no project imports, no `sqlite3` import during `import loom.runs`, and no store/execution writes to `.loom_catalog`.

## Implementation Steps

1. Define the `RunCatalog.list()` facade signature and delegate lazily to private current-listing code.
2. Add private DB read helpers for row freshness evidence and deterministic filtered summary queries.
3. Add collection census/reconciliation logic that compares DB rows, discovered run candidates, and run-store freshness before querying.
4. Reuse direct extraction to refresh new or changed runs outside DB write transactions, then write replacements/deletions in short SQLite transactions.
5. Implement exact-match filter compilation using `filter_facts` and summary tables, with validation for ambiguous key usage and deterministic `run_uri` ordering.
6. Add warning aggregation for invalid, unreadable, partial, disappeared, actively-changing, unsupported-schema, stale/corrupt catalog, and unrecoverable catalog conditions.
7. Add package, unit, contract, and integration tests for current semantics, stale-row reconciliation, filters, ordering, recovery, and concurrent read/write smoke behavior.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_runs_api.py` and `tests/package/test_import_boundaries.py` if needed.
- Required assertions or deferral reason: `import loom.runs` and `from loom.runs import RunCatalog` remain stable and import-light; importing `loom.runs` still does not import `sqlite3`, concrete local stores, CLI, execution, executors, optional config dependencies, project packages, or artifact codecs. No private SQLite current-list helpers are exported.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/runs/test_sqlite_storage.py`, new `tests/unit/loom/runs/test_current_listing.py`, and focused updates to `tests/unit/loom/runs/test_run_catalog_models.py` if validation changes.
- Required assertions or deferral reason: filter validation and compilation; AND semantics; key semantics for tag, stage, and artifact filters; deterministic ordering; DB freshness-vs-store freshness decisions; refresh/write/delete transaction behavior with stubbed summaries; warning aggregation; missing/corrupt/incompatible DB recovery decisions; `ListRunsResult` content and requested filters.

### Contract Suite

- Status: required
- Expected paths: existing model contract coverage or a new focused `tests/contracts/test_run_catalog_contract.py`.
- Required assertions or deferral reason: `RunCatalog.list()` returns `ListRunsResult`; `to_dict()` output for list results, filters, summaries, warnings, and `checked_at` is JSON-safe and stable; warning codes remain the public taxonomy; filter behavior is API-owned and not CLI-owned. If repository convention keeps this in unit tests, record that no broader contract file was needed.

### Integration Suite

- Status: required
- Expected paths: new `tests/integration/pipeline/test_run_catalog_current_list.py` or focused additions near `tests/integration/pipeline/test_run_catalog_sqlite.py`.
- Required assertions or deferral reason: temporary local collections cover valid runs, new runs after prior rebuild, changed freshness, deleted run directories, stale injected DB rows, missing DB, corrupt DB recovery, invalid/partial/unsupported candidates as warnings, exact filters across all supported kinds, deterministic ordering, concurrent catalog instances listing/rebuilding without corruption, and a synthetic thousands-of-runs fixture sufficient to exercise indexed filters without relying on wall-clock performance thresholds.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase.
- Required assertions or deferral reason: no user-facing CLI command or full list/diff workflow is introduced until Phase 6.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected.
- Required assertions or deferral reason: this phase remains local, deterministic, filesystem-only, and uses standard-library SQLite. No live scheduler, network, hosted tracker, external service, config-extra, or other opt-in behavior is introduced.

## Risks

- Current-read reconciliation can accidentally accept stale rows if DB freshness evidence is missing or partial. Missing evidence should trigger rebuild/refresh or a warning, not silent acceptance.
- Thousands-of-runs tests can become slow if they create full execution fixtures. Prefer lightweight synthetic run-store records that still exercise real discovery, freshness, and SQL query paths.
- Concurrent tests can become flaky if they depend on precise lock timing. Prefer deterministic multi-instance smoke tests and explicit busy-timeout behavior.
- Filter facts can drift from public summary fields. Tests must verify every supported `RunFilterKind` against summaries returned through the public API.
- Recovery can hide real filesystem errors. Permission, readonly, and persistent lock failures should become unrecoverable catalog errors instead of deleting sidecar files repeatedly.

## Stop Conditions

- The executor cannot prevent stale DB rows from being returned without broad public model or schema-contract changes.
- Current listing requires runner, executor, or run-store code to write the collection catalog DB.
- Refresh/reconciliation would need artifact payload reads, project-code imports, CLI logic, or domain-specific interpretation.
- SQLite transaction or locking behavior cannot be tested deterministically on local temporary files.
- Recoverable catalog handling risks deleting or mutating anything outside `.loom_catalog`.
- Exact-match filter semantics cannot be expressed with existing `RunFilter` without an unplanned public query redesign.
- Targeted validation shows package import boundaries are broken and cannot be restored within this phase.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_runs_api.py tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/runs
uv run pytest tests/contracts/test_run_catalog_contract.py
uv run pytest tests/integration/pipeline/test_run_catalog_current_list.py
uv run pytest tests/integration/pipeline/test_run_catalog_sqlite.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

If `tests/contracts/test_run_catalog_contract.py` or `tests/integration/pipeline/test_run_catalog_current_list.py` is not created because coverage fits existing files better, the executor or PR preparer must record the actual equivalent command paths in the phase notes and PR body.

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: facade signature and import-boundary tests first; private freshness/census helpers next; targeted refresh and deletion transactions next; filter compilation/querying next; recovery and concurrency integration tests last.
- Tests to run with each slice: package import tests after facade/private import changes; unit current-list tests after reconciliation and filter helpers; integration current-list tests after facade wiring; full `make validate-pr` and `make test-summary` during PR preparation.
- Decisions the executor must not revisit: SQLite is private and derived; run-store freshness is authoritative; `run_uri` remains canonical identity and default order key; default reads are current-only; filters are exact-match AND semantics; CLI, comparison, public SQL, artifact payloads, project imports, runner writes, and executor writes are out of scope.
- Conditions that require stopping for the manager: any stop condition above, a need for public query model redesign, or a reconciliation path that cannot preserve the bounded current-read guarantee.

## Refinement And Review Budget Status

- Phase execution plan draft: completed
- Phase execution plan refinement: completed for expanded path
- Phase implementation refinement: unused; available only for one bounded refinement pass if targeted validation fails, suite coverage is missing, or the expanded-path implementation needs correction after review
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on 2026-05-09
- Refined plan: completed by `loom_phase_planner` on 2026-05-09
