# Phase 1 Execution Plan: Public Models And Run-Store Freshness

## Metadata

- Status: implementation complete; PR preparation pending
- Feature focus: Run Catalog And Comparison
- PR title: `Run Catalog And Comparison - Phase 1: Public Models And Freshness`
- Branch: `codex/run-catalog-models`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-catalog-models`
- Phase execution plan path: `docs/phases/run-catalog-models.md`
- Full plan: `docs/implementation-plans/implementation-plan-v8.md`
- Source phase: Phase 1 - Public Models And Run-Store Freshness
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: merge-eligible after automated review, local validation, and GitHub checks because this is a root phase targeting `develop`
- Workflow path: fast path
- Successor dependency notes: Phase 2 depends on these public models and freshness reads before direct scan and summary extraction can be implemented.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v8.md` on 2026-05-09; manager verified recorded review, refinement, and confirmation evidence before assignment.
- Plan quality gate loop budget: initial review used; gate refinement used; confirmation review used.
- Draft pass: completed by `loom_phase_planner`
- Refine pass: not needed on the fast path; no blocking public-contract ambiguity found.
- Setup limitations: approved network/auth checks succeeded; worktree was created from fetched local `develop`. Initial sandboxed worktree creation could not create the branch ref and succeeded with approved git worktree access.
- Blockers: none

## Objective

Establish the stable public `loom.runs` value-model vocabulary and the run-store freshness contract that later current catalog reads use to decide whether derived catalog data reflects authoritative run-store state.

## Full-Plan Context

V8 adds a Python-first run catalog and metadata comparison layer over local run directories. This phase is the contract foundation: public models, warnings, catalog errors, run-store freshness protocols, local freshness implementation, and boundary documentation. Later phases may scan collections, build SQLite storage, refresh and query current catalog reads, compare metadata, and expose CLI commands; those behaviors must not be implemented in this phase.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: the assignment states v8 has no earlier phase and `develop` contains the selected implementation plan.
- Retarget/rebase plan after predecessor merge: none; PR targets `develop` directly.
- Branch cleanup constraints: branch may be deleted after merge if no successor branch is stacked on it.

## Source Phase Summary

- Goal: add the public `loom.runs` model vocabulary and store-owned freshness signal required by current catalog reads.
- Required scope: `loom.runs` package and public models; warning taxonomy; catalog errors; run-store freshness/inventory protocol; local run-store freshness implementation; freshness updates for catalog-relevant store writes; `docs/structure.md` boundary update; import-boundary tests.
- Required checkpoints: public imports remain cheap; models are immutable and serializable; `run_uri` is canonical identity; freshness is store-owned and independent of catalog/CLI imports; existing store/execution behavior remains compatible.
- Acceptance criteria:
  - `from loom.runs import RunCatalog` and public model imports are stable and cheap.
  - Public models validate required fields, preserve `run_uri` as canonical identity, and serialize to plain data.
  - Filter models represent the v8 exact-match filter set.
  - Catalog warning models support the minimum stable machine-readable codes and details required before CLI JSON exposes warnings.
  - Local run-store writes expose a freshness token or inventory that changes when catalog-relevant run metadata changes.
  - Run-store freshness support does not import `loom.runs` or `loom.cli`.
  - `docs/structure.md` documents the new `loom.runs` package boundary.
  - Existing run-store and execution behavior remains compatible.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/pipeline/stores/run_store.py` owns store protocols and aggregate `RunStore`.
  - `src/loom/pipeline/stores/local_runs.py` owns local run metadata writes and atomic persistence.
  - `src/loom/pipeline/stores/__init__.py` owns public store exports.
  - `src/loom/pipeline/stores/inspection.py` already supplies read-only run inspection models.
  - `src/loom/__init__.py` is intentionally cheap and should not re-export `loom.runs` if that would import stores, CLI, or heavy layers.
- Existing tests or harness behavior:
  - Package tests assert cheap imports and import direction in `tests/package/test_import.py`, `tests/package/test_import_boundaries.py`, and `tests/package/test_pipeline_store_api.py`.
  - Store contract tests in `tests/contracts/test_store_contract.py` use dummy protocol implementers and must be updated for any new freshness capability.
  - Local store behavior is covered in `tests/unit/loom/pipeline/stores/test_local_runs.py` and `tests/integration/pipeline/test_local_stores.py`.
- Import-boundary or dependency constraints:
  - `loom.runs` public models must be import-light and must not import CLI, execution runners, concrete executors, project packages, or optional config dependencies.
  - Store freshness code must stay below the catalog boundary and must not import `loom.runs`, `loom.cli`, diagnostics, or project packages.

## In-Scope Work

- Add `src/loom/runs/` as the public run catalog namespace with cheap imports.
- Add a placeholder `RunCatalog` facade sufficient for stable import and future construction surface; do not implement listing, scanning, SQLite, comparison logic, or CLI behavior.
- Add immutable public models for run summaries, artifact summaries, exact-match filters, catalog warnings, list/index result envelopes, and comparison result shapes.
- Add catalog-specific public errors without depending on CLI modules.
- Commit these public warning codes as compatibility values: `invalid_run`, `unreadable_run`, `partial_run`, `actively_changing_run`, `disappeared_run`, `unsupported_schema`, `stale_or_corrupt_catalog`, and `unrecoverable_catalog_error`.
- Add a run-store freshness/inventory protocol and export it through store public APIs.
- Implement local run-store freshness reads and updates with a run-local token or inventory file owned by the store.
- Ensure catalog-relevant local run-store write paths update freshness metadata through a shared store-owned helper.
- Update `docs/structure.md` with `loom.runs` ownership, private future storage/extraction modules, allowed imports, and forbidden reverse imports from stores/execution into catalog.
- Add package, unit, contract, and integration tests for public models, warnings, filter validation, freshness behavior, and import boundaries.

## Out-of-Scope Work

- SQLite catalog storage, schema, migrations, WAL policy, or sidecar DB creation.
- Direct collection scanning or run discovery.
- `RunCatalog.list()` query behavior or refresh-on-read orchestration.
- CLI commands under `loom runs`.
- Metadata comparison implementation beyond value-model shapes.
- Artifact payload loading or domain-specific comparison.
- Any project-code imports, external services, hosted trackers, filesystem watchers, or future v9/v10 behavior.

## Assumptions

- The placeholder `RunCatalog` may raise a catalog-specific not-implemented error for behavior deferred to later phases, but it must remain a stable, cheap public import.
- Public models can use standard-library dataclasses or existing Loom plain-data helpers; no new runtime dependency is justified.
- Freshness should be represented as public store protocol data, not as a catalog model, so store modules do not depend on `loom.runs`.
- Lock files and workspace directory creation are not catalog-summary metadata by themselves; they should not become freshness obligations unless implementation chooses an inventory that intentionally tracks all run-directory mutations.

## Scope Contract

The public `loom.runs` contract for this phase is model vocabulary, not behavior. `run_uri` is the required canonical identity in run-summary, artifact-addressed, result, warning, and comparison models; local paths or display names are optional presentation fields only. Models must serialize to plain JSON-safe data without exposing internal SQLite or run-store document layouts.

The exact-match filter model must cover the v8 filter set: run status, tag key/value, config fingerprint, pipeline fingerprint, git commit, stage status, artifact identity/checksum, and executor/backend identity. It must not introduce a general query language.

Warning codes are a public compatibility commitment. Later phases may add codes, but they must not rename or repurpose the initial eight codes listed above.

Freshness is a store-owned protocol. Catalog code in later phases may read freshness before and after extraction, but run-store modules must not import catalog, comparison, or CLI modules. Local freshness must change when these current local write paths mutate catalog-relevant metadata:

- `create_run`, through initial run metadata persistence
- `write_run_user_metadata`
- `write_run_status`
- `write_plan`
- `write_prepared_run`
- `write_runtime_metadata`
- `write_submitted_operation`
- `write_artifact_index`
- `write_config_snapshot`
- `write_composition_manifest`
- `write_recipe_manifest`
- `write_provenance_document`
- `append_event` if event-derived facts are included in freshness inventory or future summaries
- `write_stage_status`
- `write_stage_inputs`
- `write_stage_outputs`
- `write_stage_fingerprint`
- `write_stage_failure`
- `write_stage_worker_request`
- `write_stage_worker_result`
- `write_stage_provenance`
- `write_stage_log` only if log availability or log metadata is included in the inventory

The implementation must make the final include/exclude decision explicit in code or tests for `append_event`, worker request/result, and stage logs so downstream scan code does not guess which mutations affect current catalog reads.

## Design Impact

- Maintainability: centralize freshness updates behind one local-store helper and keep public run catalog models separate from storage/extraction internals.
- Extensibility: future SQLite, direct scan, bundle import, sweep aggregation, and read modes can reuse the same models and store freshness concept without changing runner semantics.
- Domain neutrality: summaries and comparison shapes must describe Loom metadata only; no domain metric semantics or artifact payload interpretation.
- Source-tree boundaries: `loom.runs` becomes a public API namespace above foundational models and below CLI presentation; store freshness stays in `loom.pipeline.stores`.

## Future Compatibility

Future phases can add private modules such as `loom.runs._scan`, `loom.runs._sqlite`, or `loom.runs._extract` behind the public facade. Future remote stores can implement equivalent freshness tokens without exposing local file mtimes. Future v9 bundles and v10 sweeps can reuse `run_uri`, summary, filter, warning, and result envelopes.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Catalog-owned freshness marker | Would make catalog correctness depend on catalog writes and couple stores to derived index state. |
| Runner or executor writes directly to the catalog database | Violates the v8 plan boundary; execution should write authoritative run state only. |
| Public SQLite row models | Freezes private storage internals before SQLite phases and weakens rebuildability. |
| CLI-first warning/result vocabulary | Risks API/CLI drift; Python models are the compatibility center. |
| Stale-tolerant freshness mode now | Explicitly deferred by v8; default reads must be current in later phases. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Freshness correctness depends on every catalog-relevant write path using the store helper. | Required for cheap current-read validation without runner-to-catalog coupling. | A catalog-relevant mutation is missed, or a future store cannot implement the helper cleanly. |
| Initial `RunCatalog` facade is import-stable before behavior exists. | Lets downstream phases depend on the public namespace and model vocabulary. | Users need callable list/scan behavior, which belongs to Phase 2 or later. |

## Reviewability

- Expected PR size and shape: small public-model and store-contract PR with focused docs and tests; no SQLite, scan, CLI, or comparison implementation.
- Files and areas to inspect:
  - `src/loom/runs/`
  - `src/loom/pipeline/stores/run_store.py`
  - `src/loom/pipeline/stores/local_runs.py`
  - `src/loom/pipeline/stores/__init__.py`
  - `docs/structure.md`
  - package, unit, contract, and integration tests listed in the test plan
- Scope-control checks: no `.loom_catalog` creation, no SQLite imports, no collection directory walk, no CLI command wiring, no artifact payload reads, no public model that uses local paths as canonical identity.

## Implementation Steps

1. Add the public `loom.runs` namespace, catalog errors, `RunCatalog` import surface, and immutable plain-data model vocabulary.
2. Add package/unit tests for cheap imports, public exports, validation, serialization, warning codes, comparison statuses, and exact-match filter shapes.
3. Add store freshness protocols/models to `loom.pipeline.stores.run_store` and export them through `loom.pipeline.stores`.
4. Implement local run-store freshness reads and shared update helper, then thread it through catalog-relevant local write paths.
5. Add unit, contract, and integration tests proving freshness changes on required writes and store freshness imports no catalog or CLI modules.
6. Update `docs/structure.md` to document `loom.runs` ownership and import boundaries.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`, `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_store_api.py`, and a new `tests/package/test_runs_api.py` if needed.
- Required assertions or deferral reason: `import loom` remains cheap; `import loom.runs` and `from loom.runs import RunCatalog` do not import CLI, execution, concrete executors, project packages, optional config dependencies, or SQLite internals; public `__all__` exports are stable; store public exports include the new freshness protocol/model names.

### Unit Suite

- Status: required
- Expected paths: new `tests/unit/loom/runs/` tests and `tests/unit/loom/pipeline/stores/test_local_runs.py`.
- Required assertions or deferral reason: public model required fields, immutability, plain-data serialization, `run_uri` identity, warning-code validation, comparison status validation, exact-match filter validation, catalog error hierarchy, local freshness token/inventory read shape, and freshness changes after representative local write methods.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_store_contract.py` and any new catalog model contract test if local patterns call for one.
- Required assertions or deferral reason: dummy and local run stores satisfy the new freshness protocol; freshness reads are available through store protocols without importing `loom.runs` or `loom.cli`; missing or unsupported freshness behavior is explicit rather than accidental.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_local_stores.py` or a focused new integration test under `tests/integration/pipeline/`.
- Required assertions or deferral reason: a realistic local run lifecycle updates freshness across catalog-relevant run, config, provenance, artifact, submitted-operation, and stage metadata writes while preserving existing persisted files and reads.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase.
- Required assertions or deferral reason: no user-facing run catalog command or end-to-end catalog behavior exists until later v8 phases.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected.
- Required assertions or deferral reason: no network, live scheduler, optional config-extra, or external-service behavior is introduced by this phase.

## Risks

- Public model field names and warning codes become compatibility commitments immediately; keep them minimal and aligned with the v8 plan.
- Freshness can be silently incomplete if one local write path bypasses the shared helper; tests must cover representative paths and the implementation should make exclusions explicit.
- Import direction can regress if `loom.runs` imports store implementations or if stores import catalog models; package subprocess import tests should catch this.
- Timestamp-only freshness may be too coarse on fast successive writes; prefer a token/inventory shape that changes reliably for sequential writes in unit tests.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py
uv run pytest tests/unit/loom/runs tests/unit/loom/pipeline/stores/test_local_runs.py
uv run pytest tests/contracts/test_store_contract.py
uv run pytest tests/integration/pipeline/test_local_stores.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: public `loom.runs` models first, then store protocol exports, then local freshness implementation, then docs and integration tests.
- Tests to run with each slice: package import tests after public namespace changes; unit model tests after model changes; contract tests after protocol exports; local store unit/integration tests after freshness updates.
- Decisions the executor must not revisit: `run_uri` is canonical identity; the eight initial warning codes are public compatibility commitments; SQLite, scan, list, CLI, and comparison behavior are out of scope; stores must not import `loom.runs` or `loom.cli`.
- Conditions that require stopping for the manager: a public model cannot represent the required v8 filter/warning set without expanding the implementation-plan contract; existing store APIs make freshness impossible without broad execution refactors; import-boundary tests require a dependency direction not allowed by `docs/structure.md`.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by `loom_phase_planner` in this commit.
- Final phase execution plan: fast path; refine pass not needed unless later implementation finds a blocking public-contract ambiguity.
- Implementation summary: Added import-light public `loom.runs` facade,
  catalog errors, immutable summary/filter/warning/result/comparison models,
  the stable initial warning-code taxonomy, store-owned
  `RunFreshnessRecord`/`RunFreshnessStore`, local freshness marker updates for
  catalog-relevant writes, explicit exclusions for event logs and stage log
  contents, and `docs/structure.md` package-boundary documentation.
- Implementation validation:
  - `uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py tests/package/test_runs_api.py`
    passed, 39 tests.
  - `uv run pytest tests/unit/loom/runs tests/unit/loom/pipeline/stores/test_local_runs.py`
    passed, 53 tests.
  - `uv run pytest tests/contracts/test_store_contract.py` passed, 8 tests.
  - `uv run pytest tests/integration/pipeline/test_local_stores.py` passed, 1
    test.
  - `uv run ruff check ...` on touched Phase 1 files passed.
  - `uv run pyright ...` on touched Phase 1 files passed.
  - First `make validate-pr` run exposed a pytest import-name collision from
    the new `tests/unit/loom/runs/test_models.py`; the test was renamed to
    `test_run_catalog_models.py`.
  - Second `make validate-pr` run exposed an existing store export assertion
    that needed the new freshness public exports; the assertion was updated.
  - Final `make validate-pr` passed: Ruff, Pyright, default test harness,
    config-extra test harness, and build.
  - `make test-summary` passed and wrote `build/test-summary.md`: package 55
    passed, unit 741 passed, contract 73 passed, integration 45 passed, e2e 36
    passed, config-extra 413 passed.
- Refinement summary: Not needed; targeted validation passed and no
  implementation blocker was found.
- Blocker-resolution summary: 0/3 used. The Spark executor assignment could not
  run because the Spark usage limit was exhausted, so the manager used the
  workflow's allowed non-Spark fallback implementation path without consuming a
  blocker-resolution pass.
- PR preparation: PR body pending at
  `docs/phases/run-catalog-models-pr-body.md`; PR not yet opened.
- Stack maintenance: TBD
- Remaining blockers: none at planning time
