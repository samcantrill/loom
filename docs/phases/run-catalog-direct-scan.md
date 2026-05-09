# Phase 2 Execution Plan: Direct Scan And Summary Extraction

## Metadata

- Status: pr_open
- Feature focus: Run Catalog And Comparison
- PR title: `Run Catalog And Comparison - Phase 2: Direct Scan And Summary Extraction`
- Branch: `codex/run-catalog-direct-scan`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-catalog-direct-scan`
- Phase execution plan path: `docs/phases/run-catalog-direct-scan.md`
- Full plan: `docs/implementation-plans/implementation-plan-v8.md`
- Source phase: Phase 2 - Direct Scan And Summary Extraction
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- PR: https://github.com/samcantrill/loom/pull/96
- Merge eligibility: merge-eligible after automated review, local validation, and GitHub checks because Phase 1 is merged and this is a root phase targeting `develop`
- Workflow path: fast path
- Successor dependency notes: Phase 3 should reuse the private direct-scan and extraction helpers as the SQLite rebuild source instead of reimplementing store traversal.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v8.md` on 2026-05-09; manager verified the recorded evidence before Phase 1, and Phase 1 is merged.
- Plan quality gate loop budget: initial review used; gate refinement used; confirmation review used.
- Draft pass: completed by `loom_phase_planner`
- Refine pass: not needed on the fast path; no blocking direct-scan API ambiguity found.
- Setup limitations: worktree created from local `develop` at the same revision as `origin/develop`; network sync was not required because the assignment recorded `develop` as updated after Phase 1 merge.
- Blockers: none

## Objective

Build the correctness-first local direct-scan path that discovers run directories, extracts current metadata-only summaries from authoritative run-store records, validates freshness before and after extraction, and returns summaries plus warnings through the public `RunCatalog` facade.

## Full-Plan Context

V8 adds a Python-first run catalog over authoritative local run stores. Phase 1 delivered public `loom.runs` models, the placeholder `RunCatalog`, warning codes, and store-owned `RunFreshnessRecord`/`RunFreshnessStore`. This phase turns those contracts into a usable direct scan without adding SQLite, indexed listing, comparison, or CLI behavior. Later SQLite and current-list phases must treat this direct scan as the rebuild and correctness fallback source.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 1 merged through PR #95
- Why this base branch is correct: the assignment states Phase 1 is merged and `develop` contains the public models and freshness contracts this phase consumes.
- Retarget/rebase plan after predecessor merge: none; PR targets `develop` directly.
- Branch cleanup constraints: branch may be deleted after merge if no successor branch is stacked on it.

## Source Phase Summary

- Goal: build the correctness-first path that can discover local runs and extract current summaries directly from authoritative run-store records.
- Required scope: local run discovery from store markers/directories; summary extraction through run-store inspection/public APIs; status, metadata, fingerprints, stage, artifact, executor/backend, provenance, and submitted-operation facts where available; before/after freshness validation with retry or warnings; direct-scan warning-returning results; enough `RunCatalog` facade for collection open and direct current scans.
- Required checkpoints: no project-code imports, no artifact payload loading, no SQLite sidecar, warnings for invalid or partial directories, and active mutation detection through `RunFreshnessStore`.
- Acceptance criteria:
  - A Python API caller can open a local run collection and receive current direct-scan summaries plus warnings.
  - Direct scan does not import project code or load artifact payloads.
  - Invalid and partial directories are warnings by default, not whole-query failures.
  - A run that changes during extraction is retried or reported as actively-changing/stale, not accepted as current.
  - The direct-scan extractor becomes a reusable source for SQLite rebuild.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/runs/catalog.py` exposes `RunCatalog.open()` and currently raises for deferred behavior.
  - `src/loom/runs/models.py` already provides `ListRunsResult`, `RunSummary`, `StageSummary`, `ArtifactSummary`, `SubmittedOperationSummary`, and the required warning codes.
  - `src/loom/pipeline/stores/run_store.py` owns `RunFreshnessRecord`, `RunFreshnessStore`, `RunInspectionStore`, and aggregate run-store protocols.
  - `src/loom/pipeline/stores/local_runs.py` owns local run layout, path helpers, freshness reads, `inspect_run_state()`, artifact indexes, runtime metadata, provenance documents, and submitted-operation reads.
  - `docs/structure.md` already reserves private `loom.runs._scan` and `loom.runs._extract` modules and forbids lower layers from importing `loom.runs`.
- Existing tests or harness behavior:
  - `tests/package/test_runs_api.py` asserts `loom.runs` stays import-light and does not import `loom.pipeline.stores.local_runs`.
  - `tests/unit/loom/runs/test_run_catalog_models.py` covers model serialization and deferred facade behavior.
  - Store behavior is covered in `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/contracts/test_store_contract.py`, and `tests/integration/pipeline/test_local_stores.py`.
- Import-boundary or dependency constraints:
  - Public `loom.runs` imports must stay cheap. Concrete local-store imports may live in private scan helpers loaded only when scanning.
  - `loom.runs` code must not import CLI modules, execution runners, concrete executors, optional config dependencies, project packages, or artifact payload codecs.
  - Run-store modules must not import `loom.runs`.

## In-Scope Work

- Add a public `RunCatalog.scan_current()` method returning `ListRunsResult` for direct, current local scans.
- Add private direct-scan helpers, expected under `src/loom/runs/_scan.py`, that discover candidate run directories under the collection path while ignoring the future `.loom_catalog` sidecar.
- Add private extraction helpers, expected under `src/loom/runs/_extract.py`, that convert store inspection/public store reads into existing public summary models.
- Discover valid local runs from authoritative local run markers, primarily `run.json` with a matching `run_uri`, and classify invalid, partial, unreadable, disappeared, and unsupported-schema candidates as `CatalogWarning` records.
- Use `RunFreshnessStore.read_run_freshness()` before and after extraction. Retry a bounded number of times for changed freshness and return `actively_changing_run` if a stable current snapshot cannot be obtained.
- Extract metadata-only summaries for available run status/timestamps, run user metadata/tags, config and pipeline fingerprints, git commit, executor/backend, stage status/fingerprints, artifact identities/checksums, selected provenance facts, and submitted-operation summaries.
- Extend tests for package imports, direct-scan discovery/extraction, warning serialization, freshness retry behavior, and temporary local run collections.

## Out-of-Scope Work

- SQLite sidecar creation, schema, persistence, rebuild transactions, indexed filtering, or list refresh semantics.
- CLI commands or CLI output formatting.
- Metadata comparison implementation beyond using existing shared models where needed.
- Artifact payload loading, artifact codec imports, domain-specific metric/report interpretation, or project-code imports.
- Runner, executor, or run-store writes to a collection catalog database.
- Future stale-tolerant or strict fail-on-uncertainty read modes.

## Assumptions

- `RunCatalog.scan_current()` is the direct-scan API for this phase; `RunCatalog.list()` remains reserved for later indexed current-list semantics.
- `ListRunsResult` is the correct public result envelope for direct scans because it already carries summaries, warnings, filters, and `checked_at`.
- The direct scan is local-only. Non-local or unsupported run URI schemes should become `unsupported_schema` warnings unless an existing store API can resolve them safely.
- If a source metadata field is absent, the extractor should use `None` or an empty collection rather than inventing synthetic values.
- Existing Phase 1 exclusions remain in force: event logs and stage log contents/availability are not catalog-summary facts unless this phase intentionally adds tests and plan notes for expanding that scope. This plan does not expand it.

## Scope Contract

`RunCatalog.open(path).scan_current()` must scan the local collection at `path` and return a `ListRunsResult`. The returned `summaries` must contain only current summaries that passed before/after freshness validation. The returned `warnings` must contain ordinary scan uncertainty as data, using existing public warning codes instead of failing the whole scan.

`run_uri` remains canonical identity in all returned summaries and warnings. Local paths may appear only as presentation fields such as `RunSummary.path` or `CatalogWarning.path`. Summary extraction must use public run-store methods and inspection helpers, adding store inspection helpers if a needed persisted fact has no suitable API. It must not scrape arbitrary JSON when a store API exists, import project code, import artifact codecs, or read artifact payload bytes.

Discovery and extraction should be reusable by Phase 3. Keep collection traversal, candidate classification, freshness retry, and summary extraction in private helpers that SQLite rebuild can call without going through CLI or public SQL state.

## Design Impact

- Maintainability: keeps direct scan as a small private implementation behind the public facade and avoids duplicating extraction logic in future SQLite rebuilds.
- Extensibility: future SQLite, bundle import, and sweep aggregation can reuse the same summary extractor and warning model while changing storage internals.
- Domain neutrality: summaries describe persisted Loom metadata only; no project metric semantics or artifact payload interpretation enters the catalog.
- Source-tree boundaries: `loom.runs` may call store inspection/public APIs, but stores, execution, executors, CLI, and project packages remain outside the scan dependency direction.

## Future Compatibility

Direct scan is the durable rebuild and fallback path. Later phases may make `RunCatalog.list()` refresh or query SQLite, but they should be able to call the same private scan/extract helpers to rebuild missing or corrupt catalog state. Warning result data should remain compatible with CLI JSON output in later phases.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Implement `RunCatalog.list()` as the direct-scan method now | Later phases assign `list()` indexed current-read and filter semantics; using `scan_current()` preserves a clear direct-scan contract. |
| Build SQLite first and test direct scan through rebuild | Phase 2 must prove source-of-truth extraction before caching derived rows. |
| Path-walk every known JSON file directly from `loom.runs` | Existing store APIs own validation, schema handling, and run layout; bypassing them would duplicate store contracts. |
| Fail the entire scan on invalid or partial directories | V8 requires warning-returning results so healthy runs remain visible. |
| Accept a summary after freshness changed during extraction | Violates the current-read consistency claim; the scan must retry or warn. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Direct scan may be slow for large collections. | It is the correctness fallback and rebuild source before SQLite phases land. | Phase 3 indexed rebuild/list work is complete, or direct-scan latency blocks expected fixture validation. |
| Some summary fields may be `None` until persisted source metadata is available through stable store APIs. | Avoids inventing data or scraping unsupported private documents. | Users need a missing field and the run store has an authoritative source that can be exposed through inspection APIs. |

## Reviewability

- Expected PR size and shape: focused `loom.runs` direct-scan/extraction PR with small store-inspection additions only if required, plus package, unit, contract, and integration tests.
- Files and areas to inspect:
  - `src/loom/runs/catalog.py`
  - `src/loom/runs/_scan.py`
  - `src/loom/runs/_extract.py`
  - `src/loom/runs/__init__.py` only if public exports intentionally change
  - `src/loom/pipeline/stores/inspection.py` and `src/loom/pipeline/stores/local_runs.py` only for necessary inspection helper additions
  - `tests/package/test_runs_api.py`
  - new or updated `tests/unit/loom/runs/`
  - `tests/contracts/test_store_contract.py`
  - new or updated `tests/integration/pipeline/` run catalog coverage
- Scope-control checks: no `sqlite3`, no `.loom_catalog/catalog.sqlite`, no CLI command modules, no artifact payload reads, no project imports, no comparison algorithm, and no `PipelineRunner` or executor catalog writes.

## Implementation Steps

1. Add the direct-scan facade surface: `RunCatalog.scan_current()` returns `ListRunsResult` and delegates to private scan code.
2. Implement local candidate discovery and classification for collection children, ignoring future sidecar directories and turning invalid/unreadable/partial/disappeared/unsupported candidates into warnings.
3. Implement metadata-only extraction from public store APIs and inspection records into `RunSummary`, `StageSummary`, `ArtifactSummary`, and `SubmittedOperationSummary`.
4. Add freshness validation around extraction with a bounded retry loop and `actively_changing_run` warnings for unstable runs.
5. Add focused package, unit, contract, and integration tests, including reusable fixture helpers for temporary run collections.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_runs_api.py` and `tests/package/test_import_boundaries.py` if import-boundary assertions need expansion.
- Required assertions or deferral reason: `from loom.runs import RunCatalog` remains stable and import-light; importing `loom.runs` still does not import concrete local stores, CLI, execution, executors, optional config dependencies, `sqlite3`, project packages, or artifact codecs.

### Unit Suite

- Status: required
- Expected paths: new tests under `tests/unit/loom/runs/`, plus targeted updates to `tests/unit/loom/runs/test_run_catalog_models.py` if facade behavior expectations change.
- Required assertions or deferral reason: candidate discovery classification; warning-code mapping for invalid, unreadable, partial, disappeared, actively-changing, and unsupported-schema runs; extraction mapping for status/timestamps, tags/metadata, fingerprints, stages, artifacts, executor/backend, provenance, and submitted operations; `scan_current()` returns `ListRunsResult`; freshness retry accepts stable before/after records and warns after bounded unstable attempts.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_store_contract.py` and any focused `tests/contracts/test_run_catalog_contract.py` if local patterns favor a separate public result contract.
- Required assertions or deferral reason: direct-scan results serialize with `to_dict()` using canonical `run_uri`; extraction depends on `RunFreshnessStore`/`RunInspectionStore` style protocols instead of concrete runner or CLI behavior; any new store inspection helper is represented in protocol/contract tests.

### Integration Suite

- Status: required
- Expected paths: new `tests/integration/pipeline/test_run_catalog_direct_scan.py` or focused additions near `tests/integration/pipeline/test_local_stores.py`.
- Required assertions or deferral reason: temporary local run collections include valid, invalid, partial, unsupported-schema, unreadable when platform-permissible, and disappearing runs; valid summaries include persisted run, stage, artifact, provenance, runtime, and submitted-operation facts; invalid and partial entries are warnings; active freshness changes cause retry or `actively_changing_run`.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase.
- Required assertions or deferral reason: no user-facing CLI commands or full run-catalog workflow are introduced until later v8 phases.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected.
- Required assertions or deferral reason: no network, live scheduler, optional config-extra, or external-service behavior is introduced by direct local scans.

## Risks

- Direct-scan warnings are now part of public API behavior; keep messages useful but avoid making path-specific wording the compatibility contract.
- Freshness validation can be flaky if tests rely on timestamps; compare `RunFreshnessRecord.token` or `revision` instead.
- Unreadable-directory behavior can vary by platform and user permissions; tests should skip or isolate permission-sensitive assertions where needed.
- Summary field mapping can drift into broad private JSON parsing; prefer adding narrow store inspection helpers when the persisted fact is authoritative but not exposed.
- `scan_current()` creates a new public method. Keep the method small and clearly direct-scan-specific so later `list()` semantics are not constrained accidentally.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_runs_api.py tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/runs
uv run pytest tests/contracts/test_store_contract.py
uv run pytest tests/integration/pipeline/test_run_catalog_direct_scan.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: facade method and private scan skeleton first; discovery and warning classification next; extraction mapping next; freshness retry last; then tests and any minimal inspection helper additions.
- Tests to run with each slice: package import tests after facade/private-module changes; unit scan/extraction tests after helper changes; contract tests after any store protocol/inspection changes; integration direct-scan tests after end-to-end local collection behavior.
- Decisions the executor must not revisit: `run_uri` is canonical identity; ordinary invalid-run conditions are warnings in result data; store freshness is owned by stores; no SQLite, indexed listing, CLI, comparison, artifact payload loading, or project-code imports belong in this phase.
- Conditions that require stopping for the manager: direct scan cannot expose required summary fields without broad store or execution refactors; `scan_current()` conflicts with an existing public API decision; current-read freshness cannot be validated with `RunFreshnessStore`; import-boundary tests require forbidden dependencies.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: pending
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on 2026-05-09
- Final phase execution plan: pending implementation handoff
- Implementation summary: Added `RunCatalog.scan_current()` with lazy private
  direct-scan loading, private collection discovery in `loom.runs._scan`, and
  private metadata extraction/freshness validation in `loom.runs._extract`.
  Direct scans ignore `.loom_catalog`, classify invalid/partial/unsupported
  candidates as warnings, retry unstable freshness once, and return
  `ListRunsResult` summaries populated from run-store status, metadata, config
  manifest, plan fingerprints, runtime metadata, git provenance, stage status
  and fingerprints, artifact index records, and submitted-operation records.
- Implementation validation:
  - `uv run pytest tests/package/test_runs_api.py tests/package/test_import_boundaries.py`
    passed.
  - `uv run pytest tests/unit/loom/runs` passed.
  - `uv run pytest tests/contracts/test_store_contract.py` passed.
  - `uv run pytest tests/integration/pipeline/test_run_catalog_direct_scan.py`
    passed.
  - Combined targeted run passed: 46 tests.
  - `uv run ruff check src/loom/runs tests/unit/loom/runs tests/integration/pipeline/test_run_catalog_direct_scan.py`
    passed.
  - `uv run pyright src/loom/runs tests/unit/loom/runs/test_direct_scan_helpers.py tests/integration/pipeline/test_run_catalog_direct_scan.py`
    passed.
  - `make validate-pr` passed: Ruff, Pyright, default test harness,
    config-extra test harness, and build.
  - `make test-summary` passed and wrote `build/test-summary.md`: package 55
    passed, unit 743 passed, contract 73 passed, integration 47 passed, e2e 36
    passed, config-extra 413 passed.
- Refinement summary: unused
- Blocker-resolution summary: 0/3 used
- PR preparation: completed; PR #96 opened at
  https://github.com/samcantrill/loom/pull/96 and verified with base
  `develop` and head `codex/run-catalog-direct-scan`.
- Stack maintenance: no predecessor; successor handling TBD after PR state
- Remaining blockers: none known
