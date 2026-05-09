# Phase 3 Execution Plan: Materialization Boundary And Authoritative Read Models

## Metadata

- Status: PR opened; PR body refined
- Feature focus: Persistence And Concurrency Foundation
- Final PR title: `Persistence And Concurrency Foundation - Phase 3: Materialization Boundary And Authoritative Read Models`
- Branch: `codex/materialization-read-models`
- Worktree: `/home/samcantrill/work/loom-worktrees/materialization-read-models`
- Phase execution plan path: `docs/phases/materialization-read-models.md`
- Full plan: `docs/implementation-plans/implementation-plan-v9.md`
- Source phase: Phase 3 - Materialization Boundary And Authoritative Read Models
- Stack predecessor: none; Phases 1 and 2 merged into `develop`.
- Base branch: `develop` at `caa7190` (`docs: record v9 phase 2 merge`)
- Target branch: `develop`
- Merge eligibility: root phase PR; merge eligible after automated review, validation, and CI pass because it targets `develop`.
- Workflow path: expanded path because this phase spans materialization boundaries, backend-neutral read-model APIs, warnings, bundle-ready metadata, and future consumer compatibility.
- Successor dependency notes: Phases 4 and 5 depend on this shared read/materialization surface so runner writes, public status/catalog reads, diagnostics, and future bundle inputs do not query private SQLite tables or legacy local state files. Phase 6 diagnostics can reuse the warning and materialization classification here. Phase 7 parallel execution can reuse the same revision and active-run warnings. Phase 8 workspace coordination remains separate and must not be pulled into this phase.
- Plan quality gate: passed on 2026-05-09 by `loom_plan_reviewer`; no blocking or non-blocking findings remained.
- Plan quality gate loop budget: initial review used; gate refinement not needed; confirmation review not needed.
- Draft pass: complete by `loom_phase_planner` in this artifact.
- Refine pass: complete on 2026-05-10 by `loom_phase_planner`; expanded-path refinement tightened read-mode semantics, warning obligations, suite coverage, stop conditions, and scope boundaries.
- Setup limitations: branch/worktree creation used the manager-recorded local `develop` state matching `origin/develop` at `caa7190`; no `gh auth`, fetch, full validation, or PR operation was run during planning. Worktree creation required approved sandbox escalation after the default sandbox could not create the namespaced `codex/` branch ref.
- Blockers: none.

## Objective

Define and implement the backend-neutral authoritative read/materialization boundary that later status, catalog, diagnostics, and bundle code can consume without reading private SQLite internals or treating materialized files as active state truth.

## Full-Plan Context

V9 is replacing local-file active run state for new runs with a SQLite-first authoritative backend. Phase 1 established the authority contracts and read-model records, and Phase 2 implemented the first SQLite backend behind those contracts. Phase 3 turns those pieces into the shared read-consumption layer: authoritative snapshots, materialized reference classification, warnings, and metadata-only bundle-ready reads.

Later phases remain out of scope. Phase 4 owns serial runner write-path integration. Phase 5 owns the public default hard swap and catalog/status read-path conversion. Phase 6 owns read-only backend CLI presentation. Phase 7 owns bounded parallel execution. Phase 8 owns workspace/sweep coordination.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 1 merged by PR #101 and Phase 2 merged by PR #102.
- Why this base branch is correct: the manager recorded both earlier phases as merged into `develop`, and local `develop`/`origin/develop` are at `caa7190`.
- Retarget/rebase plan after predecessor merge: no predecessor retarget is needed. If `develop` advances before PR preparation, rebase this root branch onto updated `develop` and keep the PR target as `develop`.
- Branch cleanup constraints: branch can be deleted after merge if no successor branches depend on it.

## Source Phase Summary

- Goal: define and implement the materialization boundary and backend-neutral authoritative read models before runner and query paths are swapped.
- Required scope: authoritative run snapshot/read APIs over the Phase 2 backend; run and stage status facts; attempts; leases; submitted operations; commits; artifact facts; materialized payload/log/config/provenance/worker refs; cleanup candidates; event revision evidence where available; schema version; backend revision; warnings; local materialization helpers; and metadata-only bundle-ready completed-run reads.
- Required checkpoints: keep legacy local state files outside the read-model truth path; distinguish submitted-operation detail from coarse `SUBMITTED`; distinguish backend facts from materialized files; warn or fail for missing/corrupt materialization according to read request; avoid project-code imports and artifact payload loads.
- Acceptance criteria: status, catalog, diagnostics, and later bundles can consume one authoritative read model without SQLite internals; missing or corrupt files do not create alternate truth; bundle-ready metadata reads are payload-free and project-code-free; no user-facing export/snapshot CLI is added.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/stores/read_models.py` already defines `AuthoritativeRunSnapshot`, `StageLifecycleSnapshot`, `MaterializedRef`, `ReadModelWarning`, cleanup candidates, committed artifact facts, leases, attempts, revisions, and warning codes. `src/loom/pipeline/stores/authority.py` exposes `PerRunAuthorityStore.snapshot()` and schema/capability methods that consumers should use instead of backend-specific queries. `src/loom/pipeline/stores/sqlite_authority.py` implements the Phase 2 backend and currently keeps SQLite private; its root package is intentionally not exported from `loom.pipeline.stores`. `SQLitePerRunAuthorityStore` declares `MATERIALIZATION_REFS` unsupported after Phase 2, and snapshot construction currently returns backend facts but not top-level materialized refs or warnings. Keep this capability declaration honest: either the backend remains unsupported while the new read layer supplies local classification, or the implementation updates the declaration only if materialized-ref support is actually satisfied through the backend-neutral contract. `src/loom/pipeline/stores/local_runs.py`, `run_store.py`, and `_paths.py` provide safe local path helpers for logs, config/provenance files, artifacts, worker request/result files, and generated paths; those helpers can be used for materialized references but not for active truth. `src/loom/pipeline/stores/local_artifacts.py` can check artifact existence and checksums for local file refs without loading project code, but checksum verification must remain a materialization diagnostic, not a state transition.
- Existing tests or harness behavior: `tests/package/test_pipeline_store_api.py` asserts exact store exports and forbids importing `sqlite3`, `loom.runs`, CLI, or config through `loom.pipeline.stores`. `tests/unit/loom/pipeline/stores/test_authority_models.py` already covers read-model serialization and warning records. `tests/contracts/test_authority_store_contract.py` runs both the in-memory and SQLite authority stores through shared contract behavior. `tests/support/authority_stores.py` has an in-memory store whose snapshot shape is useful for new read-model contract tests. `tests/integration/pipeline/test_sqlite_authority_backend.py` already proves Phase 2 SQLite transaction and portability behavior.
- Import-boundary or dependency constraints: read-model and materialization helpers should live under the pipeline store boundary or a narrowly justified adjacent module. They must not import CLI modules, `loom.runs`, project stage packages, optional services, network clients, or non-stdlib dependencies. If stable public exports are added to `loom.pipeline.stores`, update exact package tests deliberately and preserve the root import-light guarantee.

## In-Scope Work

- Add a narrow backend-neutral authoritative read API over `PerRunAuthorityStore` snapshots and schema/capability checks, with request options for metadata-only reads, completed-run metadata reads, materialization verification, and strict versus warning-only handling.
- Populate or derive authoritative read-model fields for run status, stage statuses, attempts, leases, submitted operations, output commits, artifact facts, cleanup candidates, schema version, backend revision, materialized refs, and warnings.
- Add local materialization helpers for artifact payload refs, stage logs, config snapshots, provenance documents, worker request/result handoff files, and safe path/URI classification while keeping files as materialized references, not state authority.
- Define warning behavior for unsupported schema, missing materialized refs, stale projections, partial commits or inconsistent commit facts, and actively changing runs.
- Add bundle-ready metadata read behavior for completed runs using authoritative snapshots and materialized refs without creating an export command, reading artifact payloads, or importing project code.
- Keep additions small and store-boundary-local. Any stable export from `loom.pipeline.stores` must preserve exact package API tests and the root import-light guarantee.
- Update SQLite and in-memory contract coverage only through backend-neutral methods or helper APIs; consumers must not query SQLite tables directly.
- Update focused docs if the read/materialization boundary or internal compatibility surface needs explanation for later phases.

## Out-of-Scope Work

- No serial runner hard swap, public backend default flip, or execution write-path integration.
- No catalog/status read-path swap and no changes that make `RunCatalog`, status CLI, or resume consume the new API as public default.
- No backend CLI, repair command, mutation command, SQL command, export/import command, or user-facing snapshot command.
- No workspace/sweep coordination backend, trial/resource leases, global counters, or sweep runner behavior.
- No legacy local-file migration and no fallback that treats `status.json`, `artifacts.json`, event logs, or legacy freshness files as live truth for new runs.
- No public SQLite schema, table-name contract, or consumer query surface over private SQLite internals.
- No project-code import, artifact payload loading, domain-specific metadata interpretation, or non-stdlib dependency.

## Assumptions

- The executor may refine module/function names, but the shared behavior surface should be small, backend-neutral, and compatible with Phase 1 models.
- It is acceptable to augment existing read-model records or add narrow companion records only when needed for Phase 3 acceptance. Any change to the `PerRunAuthorityStore` protocol, status enums, submitted-operation schema, or public event model is a blocker unless it is strictly additive and reviewable.
- Local materialization helpers may depend on `LocalRunStorePaths` or safe path utilities for path construction. They should degrade to metadata-only refs when a backend is non-local or when a materialized file cannot be verified safely.
- Missing materialized files should normally become `ReadModelWarningCode.MISSING_MATERIALIZED_REF`; strict reads may raise a store/read-model error only when requested by the caller.
- Bundle-ready metadata reads are internal inputs for V10 planning. They should be stable enough for later phases, but they are not a public export format in v9 Phase 3.

## Scope Contract

The authoritative read API must consume backend authority through `PerRunAuthorityStore` snapshots, schema checks, capabilities, and Phase 1 read-model records. It must not read private SQLite tables, reconstruct current state from legacy local files, or derive lifecycle truth from event logs.

Materialized files are references with diagnostics. Artifact payloads, logs, config/provenance copies, and worker handoff files may be listed, classified, and checked for existence or checksum where safe, but their presence cannot promote a stage to success and their absence cannot roll back a committed backend fact.

Read modes are part of the contract. Metadata-only reads are the default for bundle-ready behavior. Materialization verification is opt-in and may check local existence/checksum metadata, but it must not read artifact payload contents. Strict reads may raise for missing/corrupt materialized refs or unsupported schema only when explicitly requested; warning-only reads must preserve machine-readable warning records.

Warning semantics are part of the contract. Unsupported schema, missing materialized refs, stale projection evidence, partial commit indicators, and active-run revision instability must be represented with machine-readable warning codes and safe detail payloads. The executor should avoid introducing consumer-specific warning strings that later status, catalog, diagnostics, or bundle code cannot share. If a needed warning code is missing, add the smallest compatible `ReadModelWarningCode` value and cover serialization and consumer-neutral detail fields.

Submitted-operation detail remains separate from coarse run or stage statuses. `SUBMITTED` status summaries must not be treated as the scheduler truth when submitted-operation records are present.

Bundle-ready metadata reads must be completed-run, payload-free, and project-code-free. They may include artifact refs, checksums, materialized refs, warnings, cleanup candidates, revision evidence, schema information, and submitted-operation detail, but they must not load artifacts, import stage factories, write files, or create export manifests. Non-terminal or actively changing runs should produce a warning or strict error according to the read request instead of inventing an export snapshot.

If materialization verification spans more than one backend read, capture revision evidence before and after the verification window and report `ACTIVE_RUN_CHANGING` when the backend revision changes. Do not hold long transactions or locks merely to suppress conservative active-run warnings.

## Acceptance Criteria

- One backend-neutral read path can serve later status, catalog, diagnostics, and bundle code without SQLite table access or legacy local-file truth.
- The read result carries run/stage lifecycle facts, attempts, leases, submitted operations, commits, artifact facts, cleanup candidates, materialized refs, schema version, backend revision, and warnings where supported.
- Submitted-operation records remain visible as first-class detail separate from coarse `SUBMITTED` statuses.
- Materialized refs distinguish payload/log/config/provenance/worker files from authoritative backend facts, and missing or corrupt refs become warnings or explicit strict failures without changing lifecycle truth.
- Bundle-ready completed-run reads are metadata-only, do not import project code, do not load payloads, and do not create a backend CLI/export/snapshot surface.
- Package, unit, contract, and integration tests cover the read model over fake/in-memory and SQLite stores; e2e and opt-in suites are intentionally deferred because no public read path changes in this phase.

## Design Impact

- Maintainability: creates one shared read/materialization path before status, catalog, diagnostics, and bundle consumers can drift into separate state interpretations.
- Extensibility: keeps the API backend-neutral so future service or remote backends can provide the same snapshots and materialization diagnostics without exposing SQLite.
- Domain neutrality: reports generic runtime facts, refs, warnings, and metadata only; no domain artifact, metric, model, or report semantics are interpreted.
- Source-tree boundaries: store/read-model code stays under the pipeline store boundary; execution orchestration, CLI presentation, `loom.runs` projections, and workspace coordination remain separate.

## Future Compatibility

- Phase 4 can write materialization refs and commit facts through backend contracts without inventing separate file truth.
- Phase 5 can move planning, resume, status, and catalog refresh to this read path instead of querying SQLite or legacy files directly.
- Phase 6 can present backend diagnostics by reusing the warning taxonomy and materialized-ref classification.
- V10 bundles can build metadata-only bundle manifests from the completed-run read behavior without reading private tables or loading payloads.
- Remote stores can later mark refs as metadata-only, staged, cached, or not locally materialized using the same materialization distinction.
- Reliability and cleanup work can consume cleanup candidates, missing materialized refs, and commit facts without a second lifecycle model.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Letting each consumer query SQLite directly | It would expose private schema and make future backends incompatible. |
| Reusing `status.json`, `artifacts.json`, or local event logs as the read model | Those files are legacy state, projections, or audit records, not active truth for new v9 runs. |
| Treating materialized payload presence as authority | Payload files can be missing, stale, or corrupt; backend commit facts decide active state. |
| Adding a public export or snapshot command now | V9 Phase 3 only prepares internal metadata reads; V10 owns user-facing bundle/export workflows. |
| Deferring warning taxonomy to diagnostics or bundles | Later consumers need shared warning semantics now to avoid incompatible interpretations. |
| Making the SQLite backend the public read API | SQLite is the first implementation, not the long-term contract. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| The authoritative read model becomes an internal compatibility surface before public export workflows exist | Status, catalog, diagnostics, and future bundles need one shared truth path before the hard swap. | V10 bundle/export planning promotes, reshapes, or versions a public metadata/export contract. |
| Local materialization helpers will initially cover local filesystem refs better than future remote refs | V9's first backend and current payload paths are local; remote authority and remote materialization are later roadmap work. | Remote store phases need richer ref states such as cached, staged, uploaded, or unavailable. |
| Active-run stability warnings may be conservative | Phase 3 should avoid long transactions or locking reads just to suppress warnings. | Phase 5 or Phase 7 needs stronger consistent-read guarantees for public status/catalog or parallel execution. |

## Reviewability

- Expected PR size and shape: moderate read/materialization PR with a small helper/API surface, focused updates to existing read-model/backend helpers, package/unit/contract/integration tests, and light docs updates. It should not include runner, CLI, catalog, or workspace coordination changes.
- Files and areas to inspect: `src/loom/pipeline/stores/read_models.py`, any new store-boundary read/materialization module, `src/loom/pipeline/stores/authority.py` only if a strictly additive helper is unavoidable, `src/loom/pipeline/stores/sqlite_authority.py` only through backend-neutral snapshot/capability behavior, `src/loom/pipeline/stores/local_runs.py`, `_paths.py`, and `local_artifacts.py` only for safe materialization helpers, `tests/support/authority_stores.py`, `tests/package/test_pipeline_store_api.py`, `tests/unit/loom/pipeline/stores/`, `tests/contracts/`, and `tests/integration/pipeline/`.
- Scope-control checks: no SQLite table queries outside the SQLite backend module; no legacy local-file fallback for current truth; no status enum widening; no public export/snapshot command; no backend CLI; no `loom.runs` or CLI imports from stores; no project-code import; no artifact payload loads in metadata reads; no workspace/sweep coordination implementation.

## Implementation Steps

1. Establish the minimal read/materialization boundary and request/result shape, preserving root import boundaries and using Phase 1 read-model records wherever possible.
2. Add materialized-ref classification helpers for artifact payloads, logs, config/provenance documents, and worker handoff paths, with optional existence/checksum verification that produces warnings rather than lifecycle truth.
3. Add authoritative read helpers that combine schema checks, capabilities, snapshots, cleanup candidates, submitted operations, revisions, materialized refs, and warning records without backend-specific queries.
4. Update SQLite and in-memory behavior only as needed so backend-neutral snapshot/read-model contract tests cover materialized refs, warnings, cleanup candidates, submitted operations, and revisioned reads. Do not expose private SQLite schema or table names.
5. Add bundle-ready completed-run metadata reads as internal payload-free, project-code-free projections over the authoritative read model.
6. Add focused tests and docs, then run targeted package, unit, contract, and integration commands.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_store_api.py`, `tests/package/test_import_boundaries.py` if import boundaries change, and any package API tests for intentional new exports.
- Required assertions or deferral reason: new read/materialization APIs are cheap and typed; importing `loom.pipeline.stores` still does not import `sqlite3`, `loom.runs`, CLI, project code, or optional dependencies; exact `__all__` updates are deliberate if stable exports are added.

### Unit Suite

- Status: required.
- Expected paths: new or updated tests under `tests/unit/loom/pipeline/stores/`, likely covering read-model helpers, materialized-ref classification, warning taxonomy, schema warning mapping, bundle metadata projection, and no-fallback behavior; update `tests/unit/loom/pipeline/stores/test_authority_models.py` if record serialization changes.
- Required assertions or deferral reason: materialized refs validate and serialize; missing/corrupt local files become warnings or strict errors according to request; submitted-operation projections stay separate from coarse statuses; unsupported schema maps to read-model warnings; active-run or revision-change reads carry conservative warnings; helper code does not read legacy status or artifact-index files as truth.

### Contract Suite

- Status: required.
- Expected paths: add or extend contract coverage such as `tests/contracts/test_authoritative_read_model_contract.py` and reuse `tests/contracts/test_authority_store_contract.py` fixtures for fake/in-memory and SQLite stores.
- Required assertions or deferral reason: the same authoritative read-model expectations pass over fake and SQLite stores: snapshots expose status, stages, attempts, leases, submitted operations, commits, artifact facts, cleanup candidates, materialized refs, warnings, schema version, and backend revision; consumers use backend-neutral methods only; SQLite private schema remains unobserved by contract tests.

### Integration Suite

- Status: required.
- Expected paths: new or updated tests under `tests/integration/pipeline/`, such as `test_authoritative_read_models.py` or `test_materialization_read_models.py`, plus existing `test_sqlite_authority_backend.py` if SQLite snapshot behavior changes.
- Required assertions or deferral reason: synthetic SQLite-backed runs with committed outputs, missing payload files, partial materialization, config/provenance/log/worker refs, submitted operations, cleanup candidates, schema warnings, and revisioned reads produce the expected authoritative read model and warnings without importing project code or loading payloads.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 3 does not change public runner, CLI, status, catalog, or bundle/export behavior. E2E coverage starts when Phase 5 or Phase 6 exposes read-path behavior publicly.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: deterministic package/unit/contract/integration coverage is sufficient. Do not add network, SLURM, remote-store, slow, or timing-stress requirements for this phase.

## Risks

- The read API could accidentally become a user-facing export contract before V10 has designed bundle/export behavior.
- Materialization helpers could blur the authority boundary by treating local file presence as state truth.
- Warning codes could become consumer-specific if status, catalog, diagnostics, and bundle needs are not considered together.
- Root store exports could accidentally import SQLite or optional modules through the convenience API.
- Active-run revision checks could become flaky if tests depend on wall-clock timing or concurrent mutation races instead of deterministic synthetic reads.
- Missing local payload diagnostics could accidentally load artifact data or import project stage code.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_store_api.py
uv run pytest tests/unit/loom/pipeline/stores/test_authority_models.py
uv run pytest tests/unit/loom/pipeline/stores/test_materialization_read_models.py
uv run pytest tests/contracts/test_authoritative_read_model_contract.py
uv run pytest tests/integration/pipeline/test_materialization_read_models.py
uv run pytest tests/contracts/test_authority_store_contract.py
uv run pytest tests/integration/pipeline/test_sqlite_authority_backend.py
make test-package
make test-unit
make test-contract
make test-integration
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Stop Conditions

- Stop before implementation if satisfying the plan requires a runner hard swap, public catalog/status read-path swap, backend CLI/export command, workspace/sweep coordination, SQLite table query surface, project-code imports, artifact payload loading, or legacy local files as truth.
- Stop if the `PerRunAuthorityStore` protocol, status enums, submitted-operation public schema, or event model needs more than a strictly additive, reviewable change.
- Stop if bundle-ready metadata cannot remain completed-run-only, payload-free, and project-code-free.
- Stop if materialization semantics would make committed backend facts ambiguous or would require payload presence to decide lifecycle truth.
- Stop if package import-boundary tests require importing `sqlite3`, `loom.runs`, CLI, config composition, project code, or optional dependencies through `loom.pipeline.stores`.

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: module/API boundary first; materialized-ref helpers second; authoritative read/warning assembly third; SQLite/in-memory snapshot support fourth; bundle-ready metadata projection fifth; tests and docs alongside each slice.
- Tests to run with each slice: package import-boundary tests after module/export changes; unit tests after record/helper changes; contract tests once fake and SQLite read expectations are aligned; integration tests after SQLite materialization and warning behavior is implemented.
- Decisions the executor must not revisit: no private SQLite query surface; no legacy file fallback as truth; no public export/snapshot command; no backend CLI; no runner hard swap; no catalog/status read-path swap; no workspace/sweep coordination; no project-code import; no artifact payload load for metadata reads; no new status enum values.
- Conditions that require stopping for the manager: Phase 1 `PerRunAuthorityStore` protocol changes are required; `ReadModelWarningCode` cannot express an acceptance-criteria warning without a public-contract decision; SQLite must expose table names to satisfy tests; bundle-ready metadata requires loading payloads or importing stage code; materialization semantics would make existing committed backend facts ambiguous.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-10 by
  `loom_phase_refiner`; bounded fix added checksum/corrupt materialized-ref
  verification and coverage, with targeted validation, full `make validate-pr`,
  and refreshed `make test-summary` passing after the fix.
- PR review: unused
- Blocker resolution: 0/3 used

## PR Preparation Notes

- PR body draft: complete on 2026-05-09 by `loom_pr_preparer`.
- Expanded-path PR body refine/open pass: complete on
  2026-05-09T17:13:04Z by `loom_pr_preparer`.
- Final PR title:
  `Persistence And Concurrency Foundation - Phase 3: Materialization Boundary And Authoritative Read Models`
- Target branch: `develop`
- Head branch: `codex/materialization-read-models`
- Stack predecessor: none; root phase PR targets `develop`.
- `make validate-pr`: passed on 2026-05-09T17:08Z; Ruff, Pyright, default
  harness (1016 passed, 17 skipped, 14 deselected), config-extra harness
  (416 passed, 1044 deselected), and `uv build` passed.
- `make test-summary`: passed on 2026-05-09T17:09:40Z; generated
  `build/test-summary.md` with 1457 passed, 0 failed, 0 errors, 11 skipped,
  and 1055 deselected.
- PR URL: https://github.com/samcantrill/loom/pull/103
- PR verification JSON:
  `{"baseRefName":"develop","headRefName":"codex/materialization-read-models","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/103"}`
- Blockers: none.

## Completion Notes

- Draft plan: complete on 2026-05-10 by `loom_phase_planner`.
- Expanded-path refine pass: complete on 2026-05-10 by `loom_phase_planner`.
- PR body draft: complete on 2026-05-09 by `loom_pr_preparer`.
- PR body refine pass: complete on 2026-05-09 by `loom_pr_preparer`.
- Final phase execution plan: complete and ready for `loom_phase_executor`.
- Implementation summary: complete in commits `3a7c1d8` and `21384fc`. Added
  `loom.pipeline.stores.materialization_read_models` with backend-neutral
  `read_authoritative_run`, strict/warning read options, local materialized-ref
  classification, artifact payload refs, completed-run bundle metadata
  projection, stale-projection warnings, partial-commit warnings,
  non-terminal completed-run warnings, missing and corrupt materialized-ref
  warnings, and active revision-change warnings. The API consumes
  `PerRunAuthorityStore`
  schema checks and snapshots only, preserves submitted operations as
  first-class detail, and does not query private SQLite tables, read legacy
  status/artifact-index files as truth, import project code, add CLI/export
  surfaces, or load artifact payloads.
- Implementation validation: complete. Initial sandboxed `uv run pytest` and
  `make` invocations could not create files in `/home/samcantrill/.cache/uv`;
  reruns with approved cache access passed. Post-refinement focused evidence:
  `uv run pytest tests/unit/loom/pipeline/stores/test_materialization_read_models.py tests/contracts/test_authoritative_read_model_contract.py`
  passed (15 passed). Post-refinement `make validate-pr` passed: Ruff, Pyright,
  default harness (1016 passed, 17 skipped, 14 deselected), config-extra
  harness (416 passed, 1044 deselected), and `uv build`. Post-refinement
  `make test-summary` passed and wrote `build/test-summary.md`: package 56
  passed/1 skipped; unit 785 passed/1 skipped; contract 92 passed/2 skipped;
  integration 71 passed/7 skipped/10 deselected; e2e 37 passed/1 deselected;
  config-extra 416 passed/1044 deselected.
- Phase-plan refinement summary: tightened final PR title, read-mode semantics, warning and revision obligations, suite acceptance criteria, and stop conditions while preserving the no-runner-swap, no-public-read-swap, no-CLI/export, no-workspace-coordination, no-SQLite-query-surface, no-project-code-import, no-payload-load, and no-legacy-truth boundaries.
- Implementation refinement summary: verified reads now classify checksum
  mismatches or unreadable checksum-backed local refs as
  `CORRUPT_MATERIALIZED_REF`, preserving warning-only reads and strict
  rejection while limiting payload access to checksum byte hashing.
- PR body draft pass: complete on 2026-05-10 by `loom_pr_preparer`; draft
  written to `docs/phases/materialization-read-models-pr-body.md` from the
  phase plan, final diff, PR template, phase PR-body template, refreshed
  `make validate-pr`, and refreshed `build/test-summary.md`.
- PR body refine pass: complete on 2026-05-09T17:10:10Z by
  `loom_pr_preparer`; evidence was refreshed and the concise implementation,
  test, validation, and risk summaries remained aligned with the diff.
- PR opened: complete on 2026-05-09T17:13:04Z at
  https://github.com/samcantrill/loom/pull/103.
- PR verification JSON:
  `{"baseRefName":"develop","headRefName":"codex/materialization-read-models","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/103"}`.
- Final PR-preparation validation evidence: refreshed on
  2026-05-09T17:09:40Z.
  `make validate-pr` passed: Ruff, Pyright, default harness (1016 passed,
  17 skipped, 14 deselected), config-extra harness (416 passed,
  1044 deselected), and `uv build`. `make test-summary` passed and wrote
  `build/test-summary.md` generated at 2026-05-09T17:09:40+00:00: package
  56 passed/1 skipped; unit 785 passed/1 skipped; contract 92 passed/2
  skipped; integration 71 passed/7 skipped/10 deselected; e2e 37 passed/1
  deselected; config-extra 416 passed/1044 deselected; overall 1457 passed,
  11 skipped, 1055 deselected, 129.71s.
- PR facts and target readiness: title remains `Persistence And Concurrency
  Foundation - Phase 3: Materialization Boundary And Authoritative Read
  Models`; branch is `codex/materialization-read-models`; stack predecessor is
  none; target branch is `develop`; PR body path is
  `docs/phases/materialization-read-models-pr-body.md`; local merge base with
  `develop` is `caa7190`, matching the recorded phase base. This is a root
  phase PR opened against `develop` and verified by `gh pr view 103 --json
  baseRefName,headRefName,state,url`.
- Blocker-resolution summary: no blocker-resolution passes used.
- PR preparation: PR opened and verified; no reviewers requested and no merge
  attempted.
- Stack maintenance: not needed; root phase branch targets `develop`.
- Remaining blockers: none known.
