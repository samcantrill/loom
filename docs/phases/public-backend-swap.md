# Phase 5 Execution Plan: Public Serial Hard Swap And Read-Path Swap

## Metadata

- Status: blocker-resolution update ready.
- Feature focus: Persistence And Concurrency Foundation
- Final PR title: `Persistence And Concurrency Foundation - Phase 5: Public Serial Backend Swap And Read Path`
- Branch: `codex/public-backend-swap`
- Worktree: `/home/samcantrill/work/loom-worktrees/public-backend-swap`
- Phase execution plan path: `docs/phases/public-backend-swap.md`
- PR body artifact: `docs/phases/public-backend-swap-pr-body.md`
- Full plan: `docs/implementation-plans/implementation-plan-v9.md`
- Source phase: Phase 5 - Public Serial Hard Swap And Read-Path Swap
- PR: https://github.com/samcantrill/loom/pull/105
- Stack predecessor: none; Phases 1, 2, 3, and 4 are merged into `develop`.
- Base branch: `develop` at `d89a8a8` (`docs: record v9 phase 4 merge`),
  matching local `origin/develop` at initial planning time. This plan refine
  commit is based on draft-plan commit `39a5c08`.
- Target branch: `develop`
- Merge eligibility: root phase PR; merge eligible only after implementation
  stays in Phase 5 scope, required validation passes or unavailable checks are
  justified, automated review has no blocking findings, CI passes, and the PR
  still targets `develop`.
- Workflow path: expanded path because this phase changes public default
  storage selection and moves planning, resume, status, diagnostics inputs,
  artifact summaries, and catalog refresh onto authoritative backend read
  models.
- Plan quality gate: passed on 2026-05-09 by `loom_plan_reviewer`; no
  blocking or non-blocking findings remained.
- Plan quality gate loop budget: initial review used; gate refinement and
  confirmation review were not needed.
- Prerequisite phase status: Phase 1 merged by PR #101, Phase 2 by PR #102,
  Phase 3 by PR #103, and Phase 4 by PR #104.
- Draft pass: complete by `loom_phase_planner` in this artifact.
- Refine pass: complete on 2026-05-10 by expanded-path assignment. The refine
  pass read `AGENTS.md`, implementation-plan v9, the draft plan, and relevant
  source/test files for public run construction, authority-backed execution,
  resume, diagnostics, catalog scan/extraction, materialization read models,
  package import boundaries, and serial execution coverage.
- Phase implementation refinement budget: used on 2026-05-10 by the
  expanded-path implementation/test refinement pass. The pass fixed catalog
  scan warning conversion for malformed or unsupported authority DB schemas
  and added focused coverage.
- PR body draft pass: complete on 2026-05-10 by `loom_pr_preparer`.
- PR body refine/open pass: complete on 2026-05-10 by expanded-path
  assignment. The pass verified the PR body against the implementation plan,
  phase plan, actual diff, validation evidence, scope boundaries, assumptions,
  and risks; reran final validation; pushed the branch; opened PR #105; and
  verified the PR target.
- Phase PR review budget: used on 2026-05-10. Automated review found
  blocking missing-authority fallback issues in diagnostics/catalog reads and
  a non-blocking import-boundary issue in catalog extraction.
- Blocker-resolution budget: 1/3 used. Pass 1 fixed the review blockers by
  rejecting missing/unavailable authority reads for authority-marked runs,
  preserving catalog warnings for missing authority databases, and replacing
  the catalog execution-adapter dependency with direct backend read-model
  extraction.
- Setup limitations: no fetch, GitHub operation, broad validation, PR action,
  or implementation was run during planning/refinement. Initial branch and
  worktree creation required approved sandbox escalation after the default
  sandbox could not create the namespaced `codex/` branch ref.
- Blockers: none.

## Objective

Make the SQLite-backed authoritative backend the public default for new serial
runs and move live read consumers for planning, resume, status, diagnostics
inputs, artifact summaries, and `RunCatalog` refresh to backend snapshots or
backend-neutral read models. Legacy human-readable files remain materialized
evidence, not fallback truth, for new authoritative runs.

## Full-Plan Context

V9 has established the authority contracts, run-local SQLite backend,
authoritative read/materialization helpers, and internal SQLite-backed serial
write path. Phase 5 is the public serial hard swap: new public local and
subprocess serial runs should use the same backend authority that Phase 4
proved internally, and current-truth reads should use backend snapshots,
revisions, and read models instead of legacy status, output, artifact-index, or
submitted-operation files.

This phase is still serial-only. It must leave backend diagnostics CLI,
bounded parallel execution, workspace/sweep coordination, export/snapshot
commands, and old-run migration for later phases or roadmaps.

## Stack Context

- Root or stacked phase: root phase based directly on `develop`.
- Current predecessor branch or PR: none; Phase 4 is merged.
- Why this base branch is correct: implementation-plan v9 records Phases 1-4
  as `merged`, and the draft worktree was created from the Phase 4 merge state.
- Retarget/rebase plan after predecessor merge: none expected unless `develop`
  moves before PR preparation; rebase onto updated `develop` if needed.
- Branch cleanup constraints: no known successor branch depends on
  `codex/public-backend-swap` at refinement time.

## Source Phase Summary

- Goal: enable the public SQLite-first hard swap for new serial runs by moving
  live truth reads for planning, resume, status, diagnostics inputs, and
  catalog refresh to backend snapshots/revisions.
- Required scope: public default backend selection for new serial runs,
  backend-backed planning/resume reads, backend-backed status and artifact
  summaries, revision-validated catalog extraction/refresh, retirement of
  Phase 4 compatibility shims for new authoritative runs, no-fallback behavior
  for stale or corrupt legacy files, docs and tests for no migration.
- Required checkpoints: public serial execution still works, resume/status/
  catalog/artifact-summary reads use backend truth, submitted-operation detail
  remains available behind coarse statuses, derived projections cannot override
  backend facts, and old v0-v8 migration remains absent.

## Current Source And Harness Findings

- `src/loom/cli/run.py` still creates `LocalRunStore()` in
  `_create_default_run_store()` and uses it for `loom run` plus SLURM dry-run
  preparation. Phase 5 must change the public local/subprocess serial default
  with no user setup while avoiding broad SLURM policy changes.
- `src/loom/pipeline/execution/runner.py` and `run_pipeline()` require a
  `RunStore` that also exposes `LocalRunStorePaths` for payload/log/config/
  worker materialization. The authority-backed default must continue to satisfy
  these local path needs without making local files active truth.
- `src/loom/pipeline/execution/authority_adapter.py` provides
  `AuthorityBackedSerialRunStore` and
  `create_authority_backed_serial_run_store()`. It already routes lifecycle,
  attempts, leases, submitted operations, output commits, artifact facts, and
  most status/artifact reads to `PerRunAuthorityStore`, while delegating
  materialized config, provenance, logs, stage inputs, fingerprints, worker
  handoff, and some inspection compatibility to `LocalRunStore`.
- Phase 4 compatibility shims still write legacy status/output/artifact/
  submitted documents. Phase 5 may keep these files as materialized or
  compatibility evidence, but new authoritative readers must not require them
  or treat them as fallback truth.
- `src/loom/pipeline/planning/resume.py` uses `RunStore` reads for prior stage
  status, inputs, fingerprints, outputs, and artifact index validation. For
  authoritative runs, backend status/output/artifact facts must be the conflict
  winner; local inputs/fingerprints remain materialized resume evidence and may
  make a stage stale when missing or corrupt.
- `src/loom/diagnostics/inspection.py` defaults to `LocalRunStore()` and builds
  status/artifact summaries from `inspect_run_state()` and `read_artifact_index()`.
  Phase 5 must move status and artifact-summary truth to authoritative read
  models while preserving local log/provenance lookups as materialized refs.
- `src/loom/cli/status.py` and `src/loom/cli/artifacts.py` are presentation
  over diagnostics inspection. They should not learn SQLite details.
- `src/loom/runs/_scan.py`, `src/loom/runs/_extract.py`, and
  `src/loom/runs/_sqlite.py` direct-scan local collections with `LocalRunStore`
  and `RunFreshnessRecord` evidence before writing the derived sidecar. Phase 5
  should extract authoritative-run summaries from backend snapshots/read models
  with before/after revision evidence, then keep the sidecar as projection only.
- `src/loom/pipeline/stores/materialization_read_models.py` already provides
  `read_authoritative_run()`, schema warnings, projection-revision warnings,
  active-run-changing warnings, and materialized-ref classification. Reuse this
  boundary for status, catalog, diagnostics, and artifact summaries.
- `src/loom/pipeline/stores/sqlite_authority.py` keeps database placement and
  schema private. Public code may construct/open the backend and consume
  contract/read-model records, but must not expose table names, SQL, or a
  supported database path contract.
- Existing Phase 4 tests in
  `tests/unit/loom/pipeline/execution/test_authority_adapter.py` and
  `tests/integration/pipeline/test_sqlite_serial_execution.py` prove internal
  authority-backed serial writes and basic conflict-winner behavior. Phase 5
  must promote coverage to public defaults and read consumers.
- Package tests currently enforce cheap imports and forbid accidental imports
  such as `sqlite3` through `loom.pipeline.stores`, plus forbidden imports
  through `loom.pipeline.execution`. Any new public helper must preserve lazy
  imports and import-boundary expectations.

## In-Scope Work

- Enable SQLite authority-backed serial runs as the public default for new
  local/subprocess serial execution through CLI construction and any public
  Python helper/default path used by docs and tests.
- Keep explicit `LocalRunStore` constructible as a local-file store if needed
  for old fixtures or materialized-file APIs, but do not use it as the new
  public default or as Phase 5 proof of live-state behavior.
- Ensure explicit resume of new authoritative runs opens backend truth and
  reads current lifecycle/output/submitted-operation facts from backend
  snapshots or read models.
- Update planning and resume reads so backend status, committed outputs,
  artifact facts, submitted operations, revisions, and lifecycle summaries win
  over stale or contradictory legacy local files for authoritative runs.
- Update `loom status`, diagnostics status summaries, artifact list/show
  summaries, and shared diagnostic inputs to use authoritative read models for
  lifecycle and artifact facts while retaining local logs/provenance as
  materialized refs.
- Update `RunCatalog` direct scan, rebuild, list, and compare inputs so
  authoritative runs validate current summaries with backend revisions or
  read-model evidence, and derived sidecars cannot override backend facts.
- Preserve compact warnings for unsupported, corrupt, missing, partial, or
  actively changing runs during collection scans.
- Retire or narrow Phase 4 compatibility shims for new authoritative runs where
  they leave legacy live-state reads reachable only to preserve the old public
  default.
- Add no-fallback tests for deleted, corrupt, stale, or contradictory legacy
  status/output/artifact-index/submitted-operation files on new authoritative
  runs.
- Update relevant docs and examples to state that new serial runs use backend
  authority, old v0-v8 migration remains absent, and human-readable files are
  not active truth.

## Out-of-Scope Work

- No backend CLI commands, including no `loom backend ...` user command beyond
  narrow test helpers if already present.
- No bounded parallel execution, worker pool, global scheduling policy, or
  multi-controller execution.
- No workspace/sweep coordination implementation.
- No user-facing export, import, bundle, snapshot, repair, or migration
  command.
- No old v0-v8 run migration, compatibility mode, or legacy local-file fallback
  for new active runs.
- No public SQLite schema, supported SQL access, or documented authority
  database path contract.
- No remote authoritative backend, Postgres/service backend, hosted tracker,
  scheduler-backed authority, or shared-filesystem coordination guarantee.
- No status enum widening and no redesign of SLURM or scheduler policy.

## Assumptions

- The executor may introduce a small public or semi-public default serial store
  factory if it keeps CLI and Python construction consistent and avoids
  exporting SQLite schema/path details. The exact name is an implementation
  choice.
- Existing docs/tests that construct `PipelineRunner(run_store=LocalRunStore(...))`
  can be updated where they represent public new-run behavior. Tests that
  intentionally exercise local-file store primitives may remain explicit.
- Existing old local runs should produce loud unsupported/no-authority warnings
  or errors from new live readers. They should not be silently interpreted as
  authoritative runs and should not be migrated in this phase.
- Public SLURM dry-run/live-submission paths remain outside this serial hard
  swap except for avoiding regressions in shared helper imports or materialized
  file APIs they still use.

## Scope Contract

New public serial runs must have one active source of truth: the per-run
authority backend. `LocalRunStore` files may exist for materialization,
payloads, legacy-shaped documents, and compatibility with local readers, but
current lifecycle, stage status, submitted-operation detail, committed outputs,
artifact facts, revisions, and catalog conflict resolution must come from
backend contracts or backend-neutral read models.

Public callers should continue to see coarse `RunStatus` and `StageStatus`
values. Attempt, lease, output commit, submitted-operation, warning, reason,
and revision detail may be exposed through existing result/read-model summary
shapes where already appropriate, but this phase must not invent a new public
snapshot/export workflow.

Read-path code outside `sqlite_authority.py` must not query SQLite tables or
depend on the private database path. Use `PerRunAuthorityStore`,
`AuthoritativeRunSnapshot`, `read_authoritative_run()`, or a small
backend-neutral helper that can be implemented by future authority backends.

Conflict behavior is strict for new authoritative runs:

- backend run/stage status beats legacy status files;
- backend output commits and artifact facts beat legacy `outputs.json` and
  run-level artifact-index files;
- backend submitted-operation records beat submitted-operation files;
- backend revision/read-model evidence beats catalog freshness sidecars and
  derived catalog rows;
- missing, stale, corrupt, or contradictory legacy files may produce warnings,
  stale resume decisions, or materialized-ref diagnostics, but never fallback
  live truth.

## Acceptance Criteria

- New public local/subprocess serial runs initialize with the SQLite
  authoritative backend by default and require no user setup.
- Public serial success, failure, cancellation where already supported,
  subprocess execution, resume, status, and artifact summary reads work through
  backend truth.
- Planning/resume decisions for authoritative runs use backend status,
  committed output facts, artifact facts, and revision evidence as the conflict
  winner while retaining local inputs/fingerprints as materialized evidence.
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

- Maintainability: centralizes public serial truth on authority contracts and
  read models instead of letting local files, catalog sidecars, and SQLite
  snapshots drift independently.
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
  implementation, not a public schema, supported SQL interface, or documented
  database path.

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
| Keep `LocalRunStore` as the public default and leave SQLite internal | Phase 5 completes the public serial hard swap after Phase 4 proved the write path. |
| Read legacy local files first and consult backend only on mismatch | This recreates split-brain truth and makes corrupt/stale files active inputs. |
| Let `RunCatalog` query SQLite tables directly | The schema and database path are private; catalog must use backend-neutral read models or revision evidence. |
| Add a public backend-selection CLI before diagnostics | The phase requires a default hard swap, not a user-facing backend-management surface. |
| Implement migration for old runs | V9 explicitly excludes old-run migration and fallback. |
| Combine Phase 5 with backend CLI, parallel execution, workspace coordination, or export/snapshot behavior | Those are separate phases or roadmaps with different review and risk profiles. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Old v0-v8 run directories remain unsupported by new live-state readers | The hard swap avoids split-brain migration complexity in v9. | V10 import/export or a later roadmap defines a safe derived migration path. |
| Some materialized local documents remain necessary for resume inputs, fingerprints, logs, provenance, worker handoff, and payload paths | The authority contract intentionally owns lifecycle and committed facts, not every local handoff document. | A future roadmap needs those facts backend-native for remote/materialized workers. |
| Public default is SQLite-first before alternate authoritative backends exist | SQLite is the stdlib implementation that proves the contract now. | Shared-filesystem, multi-host, service, or remote authority requirements exceed SQLite capabilities. |
| Catalog freshness handling must bridge old local freshness records and new backend revision evidence | Collections may contain old, partial, or actively changing run directories during the no-migration period. | A public import/export/migration story changes old-run handling or catalog no longer supports local collection scans. |

## Reviewability

- Expected PR shape: moderate public-default and read-path PR touching
  execution construction, planning/resume reads, diagnostics/status/artifact
  summaries, run catalog extraction/refresh, docs, and focused tests.
- Areas to inspect: `src/loom/cli/run.py`,
  `src/loom/pipeline/execution/authority_adapter.py`,
  `src/loom/pipeline/execution/runner.py`, planning/resume helpers under
  `src/loom/pipeline/planning/`, diagnostics under `src/loom/diagnostics/`,
  catalog helpers under `src/loom/runs/`, store read-model helpers under
  `src/loom/pipeline/stores/`, package import tests, execution tests, catalog
  tests, diagnostics tests, and local/subprocess serial e2e tests.
- Scope-control checks: no SQLite table reads outside `sqlite_authority.py`; no
  backend CLI; no public SQL/schema/path contract; no parallel scheduler; no
  workspace/sweep implementation; no export/snapshot/repair/migration command;
  no status enum widening; no project-code imports from stores, diagnostics,
  or catalog refresh.
- Reviewer should test conflict behavior explicitly: backend facts win when
  local status/output/artifact/submitted-operation files are missing, corrupt,
  stale, or contradictory, and catalog sidecars cannot make stale facts current.

## Stop Conditions

- Public default behavior: stop if public local/subprocess serial construction
  cannot select backend authority by default without exposing private SQLite
  schema/path details, adding a user setup step, or adding a broad backend CLI.
- Live read fallback: stop if planning, resume, status, diagnostics, artifact,
  or catalog reads for new authoritative runs require legacy status/output/
  artifact-index/submitted-operation files as fallback truth.
- Catalog/status conflict rules: stop if a derived catalog row, freshness
  sidecar, legacy status file, legacy artifact index, or local submitted file
  can override backend status, artifact, submitted-operation, or revision facts.
- Old-run compatibility: stop if old v0-v8 migration or a compatibility mode
  becomes necessary to keep tests passing, or if no-authority old directories
  are silently treated as new authoritative runs.
- Import boundary risk: stop if cheap public imports start loading CLI,
  diagnostics, `loom.runs`, project code, network clients, optional
  dependencies, heavyweight services, or `sqlite3` through modules whose
  package tests forbid it. Prefer lazy construction boundaries.
- Private backend coupling: stop if read consumers need private SQL table
  access rather than backend contracts/read models.
- Scope breach: stop if the phase starts implementing bounded parallel
  execution, workspace/sweep coordination, export/snapshot/repair commands,
  old-run migration, backend diagnostics CLI, status enum widening, or SLURM
  scheduler redesign.
- Capability boundary: stop if SQLite capability limits for shared-filesystem
  or remote authority cannot be expressed as loud unsupported behavior without
  redesigning later phases.

## Implementation Slices

1. Introduce or refine the public serial store construction path so CLI and
   public Python serial examples/tests create authority-backed stores for new
   runs while keeping SQLite internals private and imports cheap.
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
  and import-boundary tests if construction helpers move or exports change.
- Required assertions: public imports remain cheap and typed; any new default
  serial construction helper is lazily imported; SQLite internals are not
  accidentally exported as schema/path API; no import cycles between planning,
  execution, stores, runs, diagnostics, and CLI.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/cli/test_run.py`,
  `tests/unit/loom/pipeline/execution/test_authority_adapter.py`,
  `tests/unit/loom/pipeline/execution/test_runner.py`,
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
  backend-neutral; no contract blesses private SQLite tables, database paths,
  or old-run migration behavior.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/pipeline/test_sqlite_serial_execution.py`,
  `tests/integration/pipeline/test_local_execution.py`,
  `tests/integration/pipeline/test_local_execution_resume.py`,
  `tests/integration/pipeline/test_subprocess_executor_integration.py`,
  `tests/integration/pipeline/test_run_catalog_current_list.py`,
  `tests/integration/pipeline/test_run_catalog_sqlite.py`,
  `tests/integration/pipeline/test_run_catalog_compare.py`,
  `tests/integration/diagnostics/test_cli_status_logs.py`, and new focused
  integration coverage if needed.
- Required assertions: public serial success/failure/resume/status/catalog/
  artifact-summary flows use SQLite truth; submitted-operation reads use
  backend facts; deleting or corrupting legacy state files does not change
  live truth; derived catalog projections cannot override backend facts;
  subprocess execution still materializes worker files but commits/reads
  authoritative facts.

### E2E Suite

- Status: required.
- Expected paths: `tests/e2e/test_local_pipeline_run.py` and CLI e2e coverage
  for `loom run`, `loom status`, `loom artifacts`, and `loom runs` if not
  already represented.
- Required assertions: representative public CLI serial run completes under
  the new default and later status/artifact/catalog reads agree with backend
  authority, including practical no-fallback cases.

### Opt-In Suites

- Status: deferred.
- Markers affected: existing SLURM live/acceptance, network, remote, or
  service-backed suites remain out of scope.
- Required assertions or deferral reason: Phase 5 is local deterministic
  serial behavior and should be covered by package/unit/contract/integration/
  e2e suites. Do not add network services, real clusters, hosted trackers,
  non-local databases, or timing-sensitive stress tests.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_execution_api.py
uv run pytest tests/package/test_pipeline_store_api.py
uv run pytest tests/package/test_runs_api.py
uv run pytest tests/unit/loom/cli/test_run.py
uv run pytest tests/unit/loom/pipeline/execution/test_authority_adapter.py
uv run pytest tests/unit/loom/pipeline/execution/test_runner.py
uv run pytest tests/unit/loom/pipeline/planning/test_resume.py
uv run pytest tests/unit/loom/diagnostics/test_diagnostics_inspection.py
uv run pytest tests/unit/loom/runs/test_direct_scan_helpers.py
uv run pytest tests/unit/loom/runs/test_current_listing.py
uv run pytest tests/contracts/test_authority_store_contract.py
uv run pytest tests/contracts/test_authoritative_read_model_contract.py
uv run pytest tests/contracts/test_run_catalog_contract.py
uv run pytest tests/contracts/test_run_catalog_comparison_contract.py
uv run pytest tests/integration/pipeline/test_sqlite_serial_execution.py
uv run pytest tests/integration/pipeline/test_local_execution.py
uv run pytest tests/integration/pipeline/test_local_execution_resume.py
uv run pytest tests/integration/pipeline/test_subprocess_executor_integration.py
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

Initial planning/refinement intentionally did not run validation because that
pass edited only the phase execution plan. Implementation and implementation
refinement validation are recorded in the completion notes below.

## Risks

- Public default selection could leave hidden legacy read paths reachable if
  construction and read consumers are not updated together.
- Planning/resume code still needs materialized inputs and fingerprints; tests
  must distinguish materialized evidence from active lifecycle truth.
- Catalog refresh currently uses local freshness metadata; replacing or
  pairing that with backend revision evidence must preserve warnings for
  changing or partial runs.
- Diagnostics need both backend lifecycle facts and local logs/provenance,
  which can obscure conflict-winner rules unless no-fallback tests are direct.
- Collections may contain old v0-v8 runs; loud warnings/errors must be clear
  without becoming migration behavior.
- Import boundaries are fragile because public defaults may need SQLite-backed
  construction while package tests intentionally keep base imports cheap.

## Handoff Notes For `loom_phase_executor`

- Follow the five implementation slices above; keep commits focused on
  construction, planning/resume, diagnostics, catalog, or docs/tests.
- Run the targeted unit/integration tests for each touched area before broader
  suite commands.
- Preserve hard decisions: SQLite schema is private; no old-run migration; no
  backend CLI; no parallel execution; no workspace/sweep coordination; no
  export/snapshot command; no public SQL/path contract; no legacy local-file
  fallback for new authoritative runs.
- Treat explicit `LocalRunStore` tests as either store-primitive tests or
  fixtures to update, not proof of the new public default.
- Stop on any stop condition above, especially needing private SQLite queries,
  fallback local files, or sidecar projections to make live reads pass.

## Refinement And Review Budget Status

- Phase plan draft: complete.
- Phase plan refine: complete; expanded-path refinement pass consumed on
  2026-05-10.
- Phase implementation refinement: used on 2026-05-10; the pass fixed
  authority DB schema warning conversion during catalog direct scans and added
  focused unit coverage for malformed and unsupported authority DB schemas.
- PR body draft: complete on 2026-05-10 in
  `docs/phases/public-backend-swap-pr-body.md`.
- PR body refine/open: complete for expanded-path PR preparation.
- PR review: used; automated review found blockers before merge.
- Blocker resolution: 1/3 used; pass 1 complete.

## Completion Notes

- Draft plan: created in this artifact from implementation-plan v9 and current
  Phase 4-merged source context.
- Final phase execution plan: refined in this artifact from implementation
  plan v9, current source/test seams, and expanded-path stop-condition review.
- Implementation summary: complete. Public `loom run` local/subprocess serial
  construction now creates an `AuthorityBackedSerialRunStore` with the
  run-local SQLite authority by default, while SLURM dry-run/live preparation
  keeps the explicit local materialization store path. The authority-backed
  store now exposes backend revision evidence for catalog freshness. Status and
  artifact diagnostics prefer `read_authoritative_run()`/backend snapshots for
  authoritative runs and keep local logs, provenance, inputs, and failure
  documents as materialized evidence only. `RunCatalog` direct scans open the
  authority-backed store when a run has valid SQLite authority, so status,
  stage, submitted-operation, artifact, and freshness extraction come from
  backend facts without querying private SQLite tables.
- Implementation validation:
  - `uv run pytest tests/unit/loom/cli/test_run.py tests/unit/loom/diagnostics/test_diagnostics_inspection.py tests/unit/loom/runs/test_direct_scan_helpers.py`
    passed: 27 passed.
  - `uv run pytest tests/unit/loom/cli/test_run.py tests/unit/loom/diagnostics/test_diagnostics_inspection.py tests/unit/loom/pipeline/execution/test_authority_adapter.py tests/unit/loom/pipeline/planning/test_resume.py tests/unit/loom/runs/test_direct_scan_helpers.py tests/unit/loom/runs/test_current_listing.py`
    passed: 58 passed.
  - `uv run pytest tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_store_api.py tests/package/test_runs_api.py tests/package/test_import_boundaries.py`
    passed: 37 passed.
  - `uv run pytest tests/contracts/test_authority_store_contract.py tests/contracts/test_authoritative_read_model_contract.py tests/contracts/test_run_catalog_contract.py tests/contracts/test_run_catalog_comparison_contract.py`
    passed: 14 passed.
  - `uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_subprocess_executor_integration.py`
    passed: 3 passed, 2 skipped.
  - `uv run pytest tests/integration/pipeline/test_run_catalog_current_list.py tests/integration/pipeline/test_run_catalog_sqlite.py tests/integration/pipeline/test_run_catalog_compare.py`
    passed: 14 passed.
  - `uv run pytest tests/e2e/test_local_pipeline_run.py` collected 0 items and
    skipped 1 because the suite is gated by optional dependencies in this
    environment.
  - `uv run pytest tests/integration/pipeline/test_sqlite_serial_execution.py tests/integration/diagnostics/test_cli_status_logs.py`
    initially could not run config-driven CLI coverage in the base environment
    because optional config dependencies were absent; the final config-extra
    validation below ran those suites with `--extra config`.
  - After implementation refinement, `make validate-pr` passed: Ruff, Pyright,
    default harness (1036 passed, 18 skipped, 14 deselected), config-extra
    harness (420 passed, 1064 deselected), and `uv build`.
  - After implementation refinement, `make test-summary` passed and wrote
    `build/test-summary.md`: package 56 passed/1 skipped; unit 804 passed/1
    skipped; contract 92 passed/2 skipped; integration 72 passed/8 skipped/10
    deselected; e2e 37 passed/1 deselected; config-extra 420 passed/1064
    deselected.
- Implementation refinement summary: complete. `src/loom/runs/_scan.py` now
  converts authority store schema failures discovered after the local run
  metadata open into the same compact catalog warning path used by local store
  failures, so malformed authority DBs produce `PARTIAL_RUN` warnings and
  unsupported newer authority schemas produce `UNSUPPORTED_SCHEMA` warnings
  instead of escaping the scan.
- Implementation refinement validation:
  - `uv run pytest tests/unit/loom/runs/test_direct_scan_helpers.py`
    passed: 4 passed.
  - `uv run pytest tests/unit/loom/runs/test_direct_scan_helpers.py tests/unit/loom/runs/test_current_listing.py tests/integration/pipeline/test_run_catalog_current_list.py tests/integration/pipeline/test_run_catalog_sqlite.py tests/integration/pipeline/test_run_catalog_compare.py`
    passed: 21 passed.
- PR review blocker-resolution summary: complete. Automated review found that
  default diagnostics and catalog scans could still fall back to legacy local
  status/artifact truth when an authority-marked run lost its
  `.loom/authority.sqlite3` database, and that catalog extraction depended on
  `loom.pipeline.execution.authority_adapter`. Pass 1 changed diagnostics to
  raise `DiagnosticsInspectionError` for missing or unavailable authority
  backends when an authority marker exists, changed catalog scans to return a
  `PARTIAL_RUN` warning for authority-marked runs with a missing authority
  backend, and replaced the execution-adapter dependency with a read-only
  summary adapter over `read_authoritative_run()`.
- PR review blocker-resolution validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/runs/test_direct_scan_helpers.py tests/unit/loom/diagnostics/test_diagnostics_inspection.py`
    passed: 17 passed.
  - `make validate-pr` passed: Ruff, Pyright, default harness (1038 passed,
    18 skipped, 14 deselected), config-extra harness (420 passed, 1066
    deselected), and `uv build`.
  - `make test-summary` passed and wrote `build/test-summary.md`: package 56
    passed/1 skipped; unit 806 passed/1 skipped; contract 92 passed/2
    skipped; integration 72 passed/8 skipped/10 deselected; e2e 37 passed/1
    deselected; config-extra 420 passed/1066 deselected.
- PR body draft pass: complete on 2026-05-10. Confirmed the dedicated worktree
  `/home/samcantrill/work/loom-worktrees/public-backend-swap`, branch
  `codex/public-backend-swap`, stack predecessor `none`, target branch
  `develop`, root merge eligibility, and final title `Persistence And
  Concurrency Foundation - Phase 5: Public Serial Backend Swap And Read Path`.
  Confirmed `develop` is an ancestor of the phase branch and `git diff --check`
  passed after the draft docs update.
- PR body artifact: drafted `docs/phases/public-backend-swap-pr-body.md` from
  `.codex/templates/phase-pr-body.md`, checked against
  `.github/PULL_REQUEST_TEMPLATE.md`, the final diff, implementation-plan v9
  Phase 5 scope, this phase execution plan, and existing validation evidence.
  The public body keeps workflow internals in this phase plan and uses compact
  validation and suite tables.
- PR opening status: opened PR #105 at
  https://github.com/samcantrill/loom/pull/105 during the expanded-path
  refine/open pass.
- PR body draft validation evidence used: existing `make validate-pr` pass from
  implementation refinement, and existing `make test-summary` output in
  `build/test-summary.md` generated 2026-05-09T20:16:47Z with overall status
  `passed` (1481 passed, 12 skipped, 1075 deselected). Validation was not
  rerun in the draft pass because this pass made documentation/artifact updates
  only and the current test-summary evidence was already available.
- PR body refine validation evidence: reran `make validate-pr` on
  2026-05-09 during the expanded-path refine/open pass; Ruff, Pyright, the
  default harness (1036 passed, 18 skipped, 14 deselected), the config-extra
  harness (420 passed, 1064 deselected), and `uv build` passed. Reran
  `make test-summary`; `build/test-summary.md` generated
  2026-05-09T20:30:35Z with overall status `passed` (1481 passed,
  12 skipped, 1075 deselected).
- PR body blocker-resolution evidence: updated after pass 1 with
  `make validate-pr` and `make test-summary` evidence from the blocker fix.
  The refreshed summary passed with 1483 passed, 12 skipped, and 1077
  deselected.
- Accepted limitations: old v0-v8 local-only run directories remain
  intentionally unsupported by the new authority read path and are not
  migrated. Local files are still materialized for logs, provenance, inputs,
  fingerprints, worker handoff, staged payloads, and old explicit
  `LocalRunStore` tests. This phase did not add backend CLI commands,
  bounded parallel execution, workspace/sweep coordination, export/snapshot/
  repair/migration behavior, public SQL/schema/database-path contracts, or
  SLURM policy redesign.
- Refinement summary: tightened public default behavior, live read fallback
  rules, catalog/status conflict rules, old-run compatibility limits, import
  boundary risks, suite obligations, and executor handoff notes.
- Blocker-resolution summary: pass 1/3 used for automated-review blockers.
- PR verification: `gh pr view 105 --json baseRefName,headRefName,state,url`
  returned `{"baseRefName":"develop","headRefName":"codex/public-backend-swap","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/105"}`
  at 2026-05-09T20:33:18Z. The verified base matches the recorded target
  branch `develop`; this is a root PR, so it is merge-eligible after manager
  automated review and CI gates pass.
- PR preparation: complete; PR body refined, branch pushed, PR opened, and
  target verification recorded.
- Stack maintenance: none needed at PR open time. Stack predecessor remains
  none, target branch is `develop`, and no known successor branch depends on
  `codex/public-backend-swap`.
- Remaining blockers: none.
