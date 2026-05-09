# Phase 5 Execution Plan: Public Serial Hard Swap And Read-Path Swap

## Metadata

- Status: draft phase execution plan; expanded-path refine pass pending.
- Feature focus: Persistence And Concurrency Foundation
- Intended PR title: `Persistence And Concurrency Foundation - Phase 5: Public Serial Backend Swap And Read Path`
- Branch: `codex/public-backend-swap`
- Worktree: `/home/samcantrill/work/loom-worktrees/public-backend-swap`
- Phase execution plan path: `docs/phases/public-backend-swap.md`
- Full plan: `docs/implementation-plans/implementation-plan-v9.md`
- Source phase: Phase 5 - Public Serial Hard Swap And Read-Path Swap
- Stack predecessor: none; Phases 1, 2, 3, and 4 are merged into `develop`.
- Base branch: `develop` at `d89a8a8` (`docs: record v9 phase 4 merge`),
  matching local `origin/develop` at planning time.
- Target branch: `develop`
- Merge eligibility: root phase PR; merge eligible only after the plan refine
  pass completes, implementation stays in scope, validation passes, automated
  review has no blocking findings, CI passes, and the PR still targets
  `develop`.
- Workflow path: expanded path because this phase changes public default
  storage selection and moves planning, resume, status, diagnostics inputs, and
  catalog refresh onto authoritative backend read models.
- Plan quality gate: passed on 2026-05-09 by `loom_plan_reviewer`; no blocking
  or non-blocking findings remained.
- Plan quality gate loop budget: initial review used; gate refinement and
  confirmation review were not needed.
- Prerequisite phase status: Phase 1 merged by PR #101, Phase 2 by PR #102,
  Phase 3 by PR #103, and Phase 4 by PR #104.
- Draft pass: complete by `loom_phase_planner` in this artifact.
- Refine pass: pending by assignment; implementation should not begin until
  this artifact is refined and marked ready.
- Phase implementation refinement budget: unused.
- Phase PR review budget: unused.
- Blocker-resolution budget: 0/3 used.
- Setup limitations: no fetch, GitHub operation, broad validation, PR action,
  or implementation was run during planning. Branch/worktree creation required
  approved sandbox escalation after the default sandbox could not create the
  namespaced `codex/` branch ref.
- Blockers: none known for drafting; refine pass remains required before
  execution.

## Objective

Make the SQLite-backed authoritative backend the public default for new serial
runs and move live read consumers for planning, resume, status, diagnostics
inputs, artifact summaries, and `RunCatalog` refresh to backend snapshots or
backend-neutral read models. Legacy human-readable files remain materialized
evidence, not fallback truth, for new authoritative runs.

## Full-Plan Context

V9 has already established the authority contracts, the run-local SQLite
backend, the authoritative read/materialization helpers, and the internal
SQLite-backed serial write path. Phase 5 is the public hard swap for serial
execution: new public local/subprocess serial runs should use the same backend
authority that Phase 4 proved internally, and current-truth reads should use
backend snapshots/revisions instead of legacy status, output, artifact-index,
or submitted-operation files.

This phase is still serial-only. It must leave backend diagnostics CLI,
bounded parallel execution, workspace/sweep coordination, export/snapshot
commands, and migration for later phases or roadmaps.

## Stack Context

- Root or stacked phase: root phase based directly on `develop`.
- Current predecessor branch or PR: none; Phase 4 is merged.
- Why this base branch is correct: implementation plan v9 records Phases 1-4
  as `merged`, and local `develop` matches local `origin/develop` at
  `d89a8a8`.
- Retarget/rebase plan after predecessor merge: none expected unless `develop`
  moves before PR preparation; rebase onto updated `develop` if needed.
- Branch cleanup constraints: no known successor branch depends on
  `codex/public-backend-swap` at planning time.

## Source Phase Summary

- Goal: enable the public SQLite-first hard swap for new serial runs by moving
  live truth reads for planning, resume, status, diagnostics inputs, and
  catalog refresh to backend snapshots/revisions.
- Required scope: public default backend selection for new serial runs,
  backend-backed planning/resume reads, backend-backed status and artifact
  summaries, revision-validated catalog extraction/refresh, retirement of
  Phase 4 compatibility shims for new runs, no-fallback behavior for stale or
  corrupt legacy files, docs and tests for no migration.
- Required checkpoints: public serial execution still works, resume/status/
  catalog/artifact-summary reads use backend truth, submitted-operation detail
  remains available behind coarse statuses, derived projections cannot
  override backend facts, and old v0-v8 migration remains absent.
- Acceptance criteria source: implementation-plan v9 Phase 5.

## Current Source And Harness Findings

- `src/loom/cli/run.py` still creates a public default `LocalRunStore()` and
  passes it to `PipelineRunner`; Phase 5 must replace that public serial
  default with an authority-backed construction path for new runs without
  adding a user setup step.
- `src/loom/pipeline/execution/authority_adapter.py` contains the Phase 4
  `AuthorityBackedSerialRunStore` and
  `create_authority_backed_serial_run_store()`. It already maps many active
  reads and writes to `PerRunAuthorityStore`, but some inspection and
  materialized-document reads still delegate to `LocalRunStore` by design.
- Planning/resume reads in `src/loom/pipeline/planning/resume.py` consume
  `RunStore` methods for stage status, inputs, fingerprints, outputs, and
  artifact index. Phase 5 must make backend status/output/artifact facts the
  conflict winner while preserving local inputs/fingerprints as materialized
  evidence where the authority contract intentionally does not own them.
- Diagnostics in `src/loom/diagnostics/inspection.py` defaults to
  `LocalRunStore()` and uses `inspect_run_state()`, `read_artifact_index()`,
  stage provenance, and log helpers. Status and artifact summaries need the
  authoritative read-model path for lifecycle and artifact facts, while logs
  and provenance remain local materialized files.
- `RunCatalog` scanning in `src/loom/runs/_scan.py` and extraction in
  `src/loom/runs/_extract.py` currently use `LocalRunStore` plus
  `RunFreshnessRecord` stability checks. Phase 5 should validate current
  summaries against backend revisions or `AuthoritativeRunSnapshot` evidence
  for authoritative runs and keep warnings for unsupported, corrupt, missing,
  partial, or actively changing runs.
- `src/loom/pipeline/stores/materialization_read_models.py` already provides
  `read_authoritative_run()` and materialization warnings. Reuse this boundary;
  do not add private SQLite queries in planning, diagnostics, catalog, or CLI.
- `src/loom/pipeline/stores/sqlite_authority.py` keeps the SQLite database
  path and schema private. Public code may construct the backend, check schema,
  and consume snapshots/read models, but must not expose table names, SQL, or
  file paths as supported API.
- Phase 4 tests under `tests/unit/loom/pipeline/execution/test_authority_adapter.py`
  and `tests/integration/pipeline/test_sqlite_serial_execution.py` already
  prove the internal write path and conflict-winner behavior. Phase 5 should
  promote that coverage to public default behavior and read-path consumers.

## In-Scope Work

- Enable SQLite authority-backed serial runs as the public default for new
  local/subprocess serial execution through Python and CLI construction paths.
- Ensure explicit resume of new authoritative runs opens backend truth and
  reads current lifecycle/output/submitted-operation facts from backend
  snapshots/read models.
- Update planning and resume reads so backend status, committed outputs,
  artifact facts, submitted operations, revisions, and lifecycle summaries win
  over stale or contradictory legacy local files for authoritative runs.
- Update `loom status`, diagnostics status summaries, artifact list/show
  summaries, and any shared diagnostic inputs to use authoritative read models
  for lifecycle and artifact facts while retaining local logs/provenance as
  materialized refs.
- Update `RunCatalog` direct scan, rebuild, list, and compare inputs so
  authoritative runs validate current summaries with backend revisions or
  read-model evidence and derived sidecars cannot override backend facts.
- Retire or narrow Phase 4 compatibility shims for new authoritative runs
  where they keep legacy live-state files reachable only to preserve the old
  public default.
- Add no-fallback tests for deleted, corrupt, stale, or contradictory legacy
  status/output/artifact-index/submitted-operation files on new authoritative
  runs.
- Update relevant docs to state that new serial runs use backend authority,
  old v0-v8 migration remains absent, and human-readable files are not active
  truth.

## Out-of-Scope Work

- No backend CLI commands, including no `loom backend ...` user command beyond
  narrow test helpers if needed.
- No bounded parallel execution, worker pool, global scheduling policy, or
  multi-controller execution.
- No workspace/sweep coordination implementation.
- No user-facing export, import, bundle, snapshot, repair, or migration
  command.
- No old v0-v8 run migration, compatibility mode, or legacy local-file
  fallback for new active runs.
- No public SQLite schema, supported SQL access, or documented authority
  database path contract.
- No remote authoritative backend, Postgres/service backend, hosted tracker,
  scheduler-backed authority, or shared-filesystem coordination guarantee.
- No status enum widening and no redesign of SLURM or scheduler policy.

## Assumptions

- The public hard swap may preserve legacy local payload files for logs,
  config/provenance copies, stage inputs/fingerprints, worker handoff, and
  artifact payloads, but not as live lifecycle truth.
- Existing old local runs may produce loud unsupported-schema or no-authority
  warnings/errors. They should not be silently interpreted as new backend
  authoritative runs.
- The executor may introduce a small backend-selection helper or factory if it
  keeps CLI and Python construction consistent and avoids exposing SQLite
  internals.
- If public SLURM live submission remains built around local/submitted files in
  this codebase, Phase 5 should avoid broad scheduler redesign and update only
  serial public paths required by the phase.

## Scope Contract

New public serial runs must have one active source of truth: the per-run
authority backend. `LocalRunStore` files may be created for materialization and
compatibility with payload readers, but current lifecycle, stage status,
submitted-operation detail, committed outputs, artifact facts, revisions, and
catalog conflict resolution must come from backend contracts or
backend-neutral read models.

Public callers should continue to see coarse `RunStatus` and `StageStatus`
values. Attempt, lease, output commit, submitted-operation, warning, reason,
and revision detail may be exposed through existing result/read-model summary
shapes where already appropriate, but this phase must not invent a new public
snapshot/export workflow.

Read-path code outside `sqlite_authority.py` must not query SQLite tables or
depend on the private database path. It should use `PerRunAuthorityStore`,
`AuthoritativeRunSnapshot`, `read_authoritative_run()`, or a small
backend-neutral helper that can be implemented by future authority backends.

Conflict behavior is strict: for new authoritative runs, legacy status files,
stage output documents, artifact-index files, submitted-operation files, or
freshness sidecars may be missing, stale, corrupt, or contradictory without
becoming fallback truth. They may contribute materialized-file warnings when
appropriate.

## Acceptance Criteria

- New public serial runs initialize with SQLite authoritative backend by
  default and require no user setup.
- Public local and subprocess serial execution, failure, cancellation where
  already supported, resume, status, and artifact summary reads work through
  backend truth.
- Planning/resume decisions for authoritative runs use backend status,
  committed output facts, artifact facts, and revision evidence as the
  conflict winner.
- Submitted-operation details are readable through backend-backed read models
  and status/catalog summaries without treating status files or submitted
  operation files as truth.
- Catalog direct scan, rebuild, list, and compare use backend revision or
  read-model evidence for authoritative runs, keep compact warnings for
  unsupported/corrupt/partial/changing runs, and do not query private SQLite.
- Deleting, corrupting, or contradicting legacy human-readable state files
  cannot make new run readers fall back to those files for live state.
- Derived catalog projections and sidecars cannot override authoritative
  backend facts.
- Old v0-v8 migration remains absent by design and documented.
- Existing public serial e2e behavior passes after expected updates to the new
  authority.

## Design Impact

- Maintainability: centralizes public serial truth on the existing authority
  contracts and read models instead of letting local files, catalog sidecars,
  and SQLite snapshots drift independently.
- Extensibility: gives V10 bundles, Phase 6 diagnostics, Phase 7 parallelism,
  and future dashboards one backend-neutral read path rather than encouraging
  direct SQLite reads.
- Domain neutrality: status, catalog, and diagnostics continue to summarize
  generic run/stage/artifact metadata without interpreting artifact payloads or
  project code.
- Source-tree boundaries: execution orchestration stays under
  `loom.pipeline.execution`, authority/read-model logic stays under
  `loom.pipeline.stores`, catalog projection stays under `loom.runs`, and CLI
  remains presentation over public APIs.
- Public contract discipline: the SQLite backend becomes a default
  implementation, not a public schema or supported SQL interface.

## Future Compatibility

- Phase 6 can add read-only backend diagnostics over the same snapshots and
  warnings without retrofitting status/catalog readers.
- Phase 7 bounded parallelism can rely on public runs already using backend
  attempt, lease, commit, and revision semantics.
- Phase 8 workspace/sweep coordination can reference `run_uri` values without
  becoming a second per-run truth source.
- V10 bundle/export work can consume authoritative read models for metadata
  and warnings instead of reading local status files or private SQLite tables.
- Future service or remote-capable backends should be able to replace SQLite
  behind the same construction/read boundaries.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep `LocalRunStore` as the public default and leave SQLite internal | Phase 5 exists to complete the public serial hard swap after Phase 4 proved the write path. |
| Read legacy local files first and consult backend only on mismatch | This recreates split-brain truth and makes corrupt/stale files active inputs. |
| Let `RunCatalog` query SQLite tables directly | The schema and database path are private; catalog must use backend-neutral read models or revision evidence. |
| Add a public backend-selection CLI before diagnostics | The phase requires a default hard swap, not a user-facing backend-management surface. |
| Implement migration for old runs | V9 explicitly excludes old-run migration and fallback. |
| Combine Phase 5 with backend CLI or parallel execution | Those are separate v9 phases with different review and risk profiles. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Old v0-v8 run directories remain unsupported by new live-state readers | The hard swap avoids split-brain migration complexity in v9. | V10 import/export or a later roadmap defines a safe derived migration path. |
| Some materialized local documents remain necessary for resume inputs, fingerprints, logs, provenance, and payload handoff | The authority contract intentionally owns lifecycle and committed facts, not every local handoff document. | A future roadmap needs those facts backend-native for remote/materialized workers. |
| Public default is SQLite-first before alternate authoritative backends exist | SQLite is the stdlib implementation that proves the contract now. | Shared-filesystem, multi-host, service, or remote authority requirements exceed SQLite capabilities. |
| Catalog freshness may need compatibility code for non-authoritative or old directories | Collections may contain old or partial run directories during the no-migration period. | A public import/export/migration story changes old-run handling. |

## Reviewability

- Expected PR shape: moderate public-default and read-path PR touching
  execution construction, planning/resume reads, diagnostics/status/artifact
  summaries, run catalog extraction/refresh, docs, and focused tests. It
  should not include backend CLI, parallel execution, workspace coordination,
  export/snapshot behavior, or migration.
- Files and areas to inspect: `src/loom/cli/run.py`,
  `src/loom/pipeline/execution/authority_adapter.py`,
  `src/loom/pipeline/execution/runner.py`, planning/resume helpers under
  `src/loom/pipeline/planning/`, diagnostics under `src/loom/diagnostics/`,
  catalog helpers under `src/loom/runs/`, store read-model helpers under
  `src/loom/pipeline/stores/`, package import tests, execution tests, catalog
  tests, diagnostics tests, and local serial e2e tests.
- Scope-control checks: no SQLite table reads outside `sqlite_authority.py`; no
  backend CLI; no public SQL/schema/path contract; no parallel scheduler; no
  workspace/sweep implementation; no migration; no status enum widening; no
  project-code imports from stores, diagnostics, or catalog refresh.
- Reviewer should test conflict behavior explicitly: backend facts win when
  local status/output/artifact/submitted-operation files are missing, corrupt,
  stale, or contradictory.

## Stop Conditions

- Stop if public serial construction cannot select backend authority without
  exposing private SQLite schema/path or adding a broad public backend CLI.
- Stop if planning/resume, diagnostics, or catalog reads require private SQL
  table access rather than backend contracts/read models.
- Stop if the implementation needs legacy local files as fallback truth for
  new authoritative runs.
- Stop if old-run migration or compatibility mode becomes necessary to keep
  tests passing.
- Stop if the phase starts implementing bounded parallel execution, workspace/
  sweep coordination, export/snapshot/repair commands, or backend diagnostics
  CLI.
- Stop if package import boundaries would make cheap public imports load CLI,
  diagnostics, `loom.runs`, optional dependencies, project code, network
  clients, or heavyweight services.
- Stop if SQLite capability limits for shared-filesystem or remote authority
  cannot be expressed as loud unsupported behavior without redesigning later
  phases.

## Implementation Slices

1. Introduce or refine the public serial store construction path so CLI and
   Python serial execution create authority-backed stores for new runs while
   keeping SQLite internals private and imports cheap.
2. Convert planning/resume live-state reads for authoritative runs to backend
   snapshots/read models and assert backend conflict-winner behavior for
   status, outputs, artifact facts, submitted operations, and revisions.
3. Convert diagnostics status and artifact summary inputs to authoritative
   read models while preserving logs/provenance/payload refs as local
   materialization.
4. Convert `RunCatalog` scan/rebuild/list/compare extraction for authoritative
   runs to backend revision/read-model evidence and preserve warning behavior
   for unsupported, corrupt, partial, or changing runs.
5. Retire Phase 4 compatibility shims for new authoritative runs where they
   leave legacy live-state reads reachable, update docs, and add no-fallback
   tests across package/unit/contract/integration/e2e suites.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_api.py`,
  `tests/package/test_pipeline_execution_api.py`,
  `tests/package/test_pipeline_store_api.py`, `tests/package/test_runs_api.py`,
  and import-boundary tests if construction helpers move.
- Required assertions: public imports remain cheap and typed; SQLite internals
  are not accidentally exported as schema/path API; no import cycles between
  planning, execution, stores, runs, diagnostics, and CLI.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/execution/`,
  `tests/unit/loom/pipeline/planning/test_resume.py`,
  `tests/unit/loom/diagnostics/test_diagnostics_inspection.py`,
  `tests/unit/loom/runs/test_direct_scan_helpers.py`,
  `tests/unit/loom/runs/test_current_listing.py`, and focused store/read-model
  tests as needed.
- Required assertions: public default selection, resume/status derivation,
  submitted-operation projection, artifact summary derivation, revision
  validation, catalog extraction from authoritative snapshots, no-fallback
  behavior for stale/corrupt/missing legacy files, and old-run loud
  unsupported behavior.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_authority_store_contract.py`,
  `tests/contracts/test_authoritative_read_model_contract.py`,
  `tests/contracts/test_run_catalog_contract.py`,
  `tests/contracts/test_run_catalog_comparison_contract.py`, and store/CLI
  contracts if public result shapes change.
- Required assertions: backend conformance remains passing; read-model
  contracts support the new public consumers; catalog/status behavior remains
  backend-neutral; no contract blesses private SQLite tables.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/pipeline/test_sqlite_serial_execution.py`,
  `tests/integration/pipeline/test_local_execution.py`,
  `tests/integration/pipeline/test_local_execution_resume.py`,
  `tests/integration/pipeline/test_run_catalog_current_list.py`,
  `tests/integration/pipeline/test_run_catalog_sqlite.py`,
  `tests/integration/pipeline/test_run_catalog_compare.py`,
  `tests/integration/diagnostics/test_cli_status_logs.py`, and new focused
  integration coverage if needed.
- Required assertions: public serial success/failure/resume/status/catalog/
  artifact-summary flows use SQLite truth; submitted-operation reads use
  backend facts; deleting or corrupting legacy state files does not change
  live truth; derived catalog projections cannot override backend facts.

### E2E Suite

- Status: required.
- Expected paths: `tests/e2e/test_local_pipeline_run.py` and CLI e2e coverage
  for `loom run`, `loom status`, `loom artifacts`, and `loom runs` if not
  already represented.
- Required assertions: representative public CLI serial run completes under
  the new default and later status/artifact/catalog reads agree with backend
  authority, including no-fallback cases that are practical at e2e scope.

### Opt-In Suites

- Status: deferred.
- Markers affected: existing SLURM live/acceptance, network, remote, or
  service-backed suites remain out of scope.
- Required assertions or deferral reason: Phase 5 should be covered by local,
  deterministic package/unit/contract/integration/e2e suites. Do not add
  network services, real clusters, hosted trackers, non-local databases, or
  timing-sensitive stress tests.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_execution_api.py
uv run pytest tests/package/test_pipeline_store_api.py
uv run pytest tests/package/test_runs_api.py
uv run pytest tests/unit/loom/pipeline/execution/test_authority_adapter.py
uv run pytest tests/unit/loom/pipeline/execution/test_runner.py
uv run pytest tests/unit/loom/pipeline/planning/test_resume.py
uv run pytest tests/unit/loom/diagnostics/test_diagnostics_inspection.py
uv run pytest tests/unit/loom/runs/test_direct_scan_helpers.py
uv run pytest tests/contracts/test_authority_store_contract.py
uv run pytest tests/contracts/test_authoritative_read_model_contract.py
uv run pytest tests/contracts/test_run_catalog_contract.py
uv run pytest tests/contracts/test_run_catalog_comparison_contract.py
uv run pytest tests/integration/pipeline/test_sqlite_serial_execution.py
uv run pytest tests/integration/pipeline/test_local_execution.py
uv run pytest tests/integration/pipeline/test_local_execution_resume.py
uv run pytest tests/integration/pipeline/test_run_catalog_current_list.py
uv run pytest tests/integration/pipeline/test_run_catalog_sqlite.py
uv run pytest tests/integration/pipeline/test_run_catalog_compare.py
uv run pytest tests/integration/diagnostics/test_cli_status_logs.py
uv run pytest tests/e2e/test_local_pipeline_run.py
make test-package
make test-unit
make test-contract
make test-integration
make test-e2e
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Risks

- Public default selection could leave hidden legacy read paths reachable if
  construction and read consumers are not updated together.
- Planning/resume code still needs materialized inputs and fingerprints; tests
  must distinguish materialized evidence from active lifecycle truth.
- Catalog refresh currently uses local freshness metadata; replacing or
  pairing that with backend revision evidence must preserve warnings for
  changing or partial runs.
- Diagnostics may need both backend lifecycle facts and local logs/provenance,
  which can obscure conflict-winner rules unless no-fallback tests are direct.
- Collections may contain old v0-v8 runs; loud warnings/errors must be clear
  without becoming migration behavior.

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: follow the five implementation slices above;
  keep each commit focused on construction, planning/resume, diagnostics,
  catalog, or docs/tests.
- Tests to run with each slice: run the targeted unit/integration tests for the
  touched area before broader suite commands.
- Decisions the executor must not revisit: SQLite schema is private; no old-run
  migration; no backend CLI; no parallel execution; no workspace/sweep
  coordination; no public SQL/path contract; no legacy local-file fallback for
  new authoritative runs.
- Conditions requiring stop: any stop condition above, especially needing
  private SQLite queries or fallback local files to make live reads pass.

## Refinement And Review Budget Status

- Phase plan draft: complete.
- Phase plan refine: pending; required before implementation.
- Phase implementation refinement: unused.
- PR review: unused.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: created in this artifact from implementation-plan v9 and current
  Phase 4-merged source context.
- Final phase execution plan: pending refine pass.
- Implementation summary: not started.
- Implementation validation: not run.
- Refinement summary: pending.
- Blocker-resolution summary: none.
- PR preparation: not started.
- Stack maintenance: none needed at draft time.
- Remaining blockers: none known; refine pass pending by expanded-path policy.
