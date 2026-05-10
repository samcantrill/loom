# Phase 1 Execution Plan: Inventory And Lifecycle Contracts

## Metadata

- Status: draft phase execution plan
- Feature focus: Authority Runtime Unification
- PR title: `Authority Runtime Unification - Phase 1: Inventory and Lifecycle Contracts`
- Branch: `codex/authority-inventory-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-inventory-contracts`
- Phase execution plan path: `docs/phases/authority-inventory-contracts.md`
- Full plan: `docs/implementation-plans/implementation-plan-v9-post.md`
- Source phase: Phase 1 - Exhaustive Inventory And Lifecycle Contracts
- Stack predecessor: none
- Base branch: local `develop` at `7b9a65e` (`plan: add v9-post implementation plan`)
- Target branch: `develop`
- Merge eligibility: root phase PR, merge-eligible after implementation, the
  pre-submit blocker gate, validation, automated review, and CI pass against
  `develop`.
- Workflow path: expanded path
- Successor dependency notes: Phase 2 depends on this phase for the complete
  local-store migration map and lifecycle-contract wording before it reclaims
  `RunStore` and introduces scoped `StageStore`.
- Plan quality gate: passed on 2026-05-10 by formal `loom_plan_reviewer`; no
  blocking or non-blocking findings remain.
- Plan quality gate loop budget: initial review used; refinement pass not
  needed; confirmation review not needed.
- Draft pass: completed by `loom_phase_planner` on 2026-05-10.
- Refine pass: pending for the expanded-path planner refinement pass.
- Setup limitations: branch and worktree were created from local `develop`
  because the required v9-post plan commit is local-only in this checkout.
  `develop` is one commit ahead of `origin/develop`; do not drop or rebase away
  the local plan commit while preparing this phase.
- Blockers: none for the draft plan.

## Objective

Produce the authoritative Phase 1 inventory and contract documentation needed
to remove local-store runtime escape hatches in later phases, without changing
runtime behavior or introducing new store interfaces.

## Full-Plan Context

V9-post moves every supported run and stage lifecycle mutation behind
authority-backed stores. Phase 1 is the scope-control phase: it records the
complete current `LocalRunStore`, `LocalRunStorePaths`, and path-shaped
`RunStore` surface, classifies each use, and writes the lifecycle contracts
that later phases must implement. Phase 2 owns the new authority interface and
conformance harness; Phase 3 owns artifact/materialization interface splits;
Phases 4-6 migrate runtime and read callers; Phases 7-10 add and adopt the
service backend, deployment profiles, and SQLite-authority removal. None of
that implementation work is in scope here.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: all earlier phases are absent, and the
  manager assigned local `develop` at `7b9a65e`, which contains the v9-post
  implementation plan even though it is not yet on `origin/develop`.
- Retarget/rebase plan after predecessor merge: none; PR targets `develop`.
- Branch cleanup constraints: no successor exists yet. The branch may be
  deleted after merge only if no later stacked branch has been created from it.

## Source Phase Summary

- Goal: establish the complete migration map and strict lifecycle contract
  before behavior changes.
- Required scope: exhaustive `LocalRunStore`, `LocalRunStorePaths`, and
  current path-shaped `RunStore` inventory across source, tests, examples,
  feature docs, and implementation docs; classify each hit as runtime mutation,
  authority read, artifact/materialized file access, test helper, docs/example,
  or historical artifact; record the line-item migration map; document run
  lifecycle, stage lifecycle, submitted-operation lifecycle, and failure-closed
  authority behavior; state that local files cannot be used for run/stage
  behavior reads.
- Required checkpoints: inventory evidence is reproducible from `rg`, every
  hit has a target role and follow-up phase, lifecycle contracts name guarded
  transitions, leases, fencing, revisions, snapshots, output commits,
  submitted-operation updates, and recovery scans, and exact follow-up
  ownership is recorded for source, tests, examples, and docs.
- Acceptance criteria: complete disposition for all current local-store runtime
  and behavior-read paths; lifecycle contracts are precise enough for Phase 2;
  local directory access is artifact/materialization-only; follow-up ownership
  is explicit.

## Current Source And Harness Findings

- `src/loom/pipeline/stores/run_store.py` still defines a broad `RunStore`
  aggregate for local-file documents, statuses, logs, submitted operations,
  locks, stage state, runtime metadata, and inspection. It also defines
  `LocalRunStorePaths` for explicit local path helpers.
- `src/loom/pipeline/stores/local_runs.py` implements `LocalRunStore` as the
  local filesystem reader/writer for run layout and still satisfies both
  `RunStore` and `LocalRunStorePaths`.
- `src/loom/pipeline/stores/authority.py` and
  `src/loom/pipeline/stores/read_models.py` already contain v9
  authority-shaped concepts: revisions, guarded run/stage transitions, leases,
  fencing tokens, attempts, submitted operations, output commits, snapshots,
  recovery records, cleanup candidates, and read-model warnings.
- `src/loom/pipeline/execution/authority_adapter.py` currently bridges
  authority and local files with `AuthorityBackedSerialRunStore`; this is a
  transitional runtime surface to inventory, not a contract to redesign in this
  phase.
- Preliminary search shows local-store references across CLI commands, runner
  and continuation code, stage worker code, SLURM planning/submission/status/
  cancellation helpers, diagnostics and preflight, run catalog scanning and
  extraction, materialization read models, examples, package tests, contract
  tests, unit tests, integration tests, e2e tests, feature docs, historical
  phase docs, and implementation docs.
- Import-boundary and dependency constraints remain those in `docs/structure.md`:
  store contracts and implementations stay under `loom.pipeline.stores`,
  execution orchestration stays under `loom.pipeline.execution`, CLI remains
  presentation over public APIs and diagnostics, and `loom.runs` remains a
  derived query facade rather than active authority.

## In-Scope Work

- Run and record an exhaustive inventory for `LocalRunStore`,
  `LocalRunStorePaths`, and current path-shaped `RunStore` usage across
  `src`, `tests`, `examples`, `docs/features`, `docs/implementation-plans`,
  `docs/phases`, and `README.md`.
- Classify every hit as exactly one primary role: runtime mutation, authority
  read, artifact/materialized file access, test helper, docs/example, or
  historical artifact. Add a secondary note when a hit combines roles.
- Add the line-item migration map to this phase artifact unless the refine pass
  chooses a narrower linked artifact. Each line must identify file, line,
  symbol or call shape, current role, target role/action, owning future phase,
  and notes.
- Document run lifecycle, stage lifecycle, submitted-operation lifecycle, and
  failure-closed authority behavior as contracts for later phases.
- State the local-file rule plainly: local run/stage files, directory scans,
  status JSON, worker result JSON, SLURM manifests, logs, and artifact indexes
  are materialization or derived evidence only; they cannot be used as active
  run/stage behavior truth.
- Record exact follow-up ownership for source, tests, examples, feature docs,
  implementation docs, and historical phase artifacts.

## Out-of-Scope Work

- New `RunStore`, `StageStore`, `RunArtifactStore`, or `StageArtifactStore`
  interfaces.
- Runtime caller migration, direct `PipelineRunner(LocalRunStore(...))`
  rejection, CLI/worker/SLURM migration, status/catalog/diagnostics migration,
  capability admission, service/database backend work, or SQLite authority
  removal.
- Editing behavior tests to use new stores or fakes.
- Changing public imports, dependency footprints, schemas, status enums, run
  directory layout, or backend behavior.
- Rewriting historical phase docs except to classify them as historical
  artifacts in the inventory.

## Assumptions

- The complete migration map may live in this phase artifact and count as the
  linked artifact required by the source plan.
- Historical phase docs and PR-body docs should be inventoried and classified,
  but they should not drive runtime migration ownership unless they describe
  still-current behavior.
- Current line numbers may shift while the implementation edits the artifact;
  the final inventory must be regenerated immediately before committing the
  implementation PR.
- If an occurrence spans multiple roles, the primary classification should be
  the role most likely to affect runtime authority safety.

## Scope Contract

No new public runtime behavior is introduced in this phase. The phase produces
documentation that later implementation phases must treat as a contract.

The contract decisions are:

- Active run lifecycle truth belongs to authority-backed `RunStore` semantics,
  not local files or directory scans.
- Active stage lifecycle truth belongs to scoped authority-backed `StageStore`
  semantics under the parent run, not stage directories or worker files.
- Submitted work is authority state. Submission creation, observation,
  cancellation, retry, scheduler status, and worker finalization must be
  represented as guarded submitted-operation lifecycle updates in later phases.
- Local filesystem access is artifact/materialization-only. Local files may
  contain payloads, logs, config snapshots, provenance, manifests, handoff
  records, materialized outputs, derived projections, and diagnostic evidence,
  but they must not answer run/stage behavior questions once authority-backed
  behavior is required.
- Failure closes toward no mutation. Missing authority, unavailable authority,
  stale revisions, expired leases, foreign fences, incompatible schema, and
  unsupported capabilities must reject lifecycle mutation or behavior reads
  rather than falling back to local files.
- Existing names are not redesigned here. Phase 1 records the current overload;
  Phase 2 owns the public authority naming and interface split.

## Inventory Output Contract

The implementation pass must add an inventory section with this line-item shape:

| ID | File:line | Symbol or call shape | Classification | Current role | Target role/action | Owner phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TBD | TBD | TBD | runtime mutation / authority read / artifact access / test helper / docs-example / historical artifact | TBD | TBD | Phase 2-10 or none | TBD |

Rules:

- Every `LocalRunStore` and `LocalRunStorePaths` hit from the required search
  scope gets a row.
- Every current `RunStore` hit that participates in path-shaped local lifecycle
  behavior, local behavior reads, or runtime mutation gets a row. Pure feature
  docs or historical references may be grouped only when the row names the
  exact files and explains why they are non-runtime.
- Rows must be dispositioned to a future phase or marked `none` for historical
  artifacts that require no migration.
- Do not use "TBD" in the final implementation inventory.

## Authority Lifecycle Contract Output

The implementation pass must add or complete contract text covering:

- Run lifecycle: admission/creation, opening/resume, controller lease, planning
  and submission setup, guarded status transitions by expected status or
  revision, cancellation/interruption, finalization, revisioned snapshots, and
  recovery scans.
- Stage lifecycle: scoped stage handle, atomic attempt allocation, owner id,
  stage lease and fencing token, running/submitted transitions, output commit,
  terminal success/failure/cancellation, stale or expired commit rejection,
  cleanup candidates, and recovery scans.
- Submitted-operation lifecycle: idempotent create/update by submission id or
  idempotency key, scheduler observations, cancellation observations, retry
  handling, stage/run linkage, stale observation behavior, and replay safety.
- Failure-closed behavior: authority unavailable, schema incompatible, stale
  transition, lease expired, foreign fence, missing capability, local lifecycle
  disallowed, malformed deferred evidence, and rejected deferred result.

## Design Impact

- Maintainability: this phase reduces later review risk by making every known
  local-store escape hatch explicit before code migration begins.
- Extensibility: later service, remote, HPC, sweep, retry, and catalog work can
  use the inventory to avoid reintroducing local behavior truth.
- Domain neutrality: the contract is about generic run/stage authority and
  materialization, not a domain-specific workflow.
- Source-tree boundaries: this phase should touch documentation artifacts only;
  any source-tree decisions recorded here must preserve the existing
  `loom.pipeline.stores`, `loom.pipeline.execution`, CLI, diagnostics, and
  `loom.runs` boundaries.

## Future Compatibility

- Phase 2 can use the map to rename or reclaim `RunStore` without preserving
  path-shaped local lifecycle behavior by accident.
- Phase 3 can use the artifact/materialization rows to define
  `RunArtifactStore` and `StageArtifactStore` without lifecycle methods.
- Phases 4-6 can use the runtime and read rows as migration checklists.
- Phases 7-10 can use the contracts to prove service backend behavior,
  deployment profiles, system-wide adoption, and SQLite-authority removal.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Start caller migration while inventorying | This would hide missed local-store roles inside implementation churn and weaken reviewability. |
| Inventory only `src` and tests | Examples, feature docs, implementation docs, and historical artifacts currently teach or preserve local-store semantics and must be classified. |
| Treat local files as a temporary behavior-read fallback | The full plan explicitly rejects local lifecycle read compatibility; preserving it here would undermine later authority contracts. |
| Define the new store interfaces in Phase 1 | Phase 2 owns public interface naming, factory shape, capability vocabulary, and conformance harness. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No product behavior changes in this phase | The expanded path requires a precise inventory and contract before public API and runtime migration. | Phase 2 begins interface work without a complete line-item map or contract language. |

## Reviewability

- Expected PR size and shape: documentation-only PR with this phase artifact
  updated to include the inventory map, lifecycle contracts, and completion
  notes. Source plan edits are acceptable only if they link to or summarize the
  final phase artifact.
- Files and areas to inspect: `docs/phases/authority-inventory-contracts.md`;
  optional updates to `docs/implementation-plans/implementation-plan-v9-post.md`;
  inventory evidence from `src/loom/pipeline/stores`, `src/loom/pipeline/execution`,
  `src/loom/pipeline/executors/slurm`, `src/loom/cli`, `src/loom/diagnostics`,
  `src/loom/runs`, `tests`, `examples`, `docs/features`, `docs/phases`,
  `docs/implementation-plans`, and `README.md`.
- Scope-control checks: no source behavior changes, no new interfaces, no test
  rewrites, no runtime migration, no service backend work, and no SQLite
  removal.

## Implementation Steps

1. Regenerate the search evidence for `LocalRunStore`, `LocalRunStorePaths`,
   and path-shaped `RunStore` usage across the required source, test, example,
   feature-doc, implementation-doc, phase-doc, and README scopes.
2. Convert the evidence into the line-item migration map in this phase
   artifact, grouping only historical/docs rows where grouping cannot hide a
   live runtime or test helper.
3. Add the lifecycle contract text for runs, stages, submitted operations, and
   failure-closed behavior, reusing the source plan vocabulary and existing v9
   authority record names where they constrain later behavior.
4. Add follow-up ownership by future phase for each category: Phase 2 for
   authority interfaces and conformance, Phase 3 for artifact/materialization,
   Phase 4 for Python runner and examples, Phase 5 for CLI/worker/SLURM,
   Phase 6 for read models and diagnostics, Phase 7-10 for backend adoption
   and removal work where relevant.
5. Re-run the inventory searches and review the diff to confirm this remains a
   documentation-only phase with no future-phase behavior changes.

## Test Plan

### Package Suite

- Status: deferred.
- Expected paths: `tests/package/test_pipeline_store_api.py`,
  `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: Phase 1 does not change exports,
  imports, or product code. Package checks become required only if the
  implementation accidentally edits package or source files, which should stop
  the phase for manager review.

### Unit Suite

- Status: deferred.
- Expected paths: `tests/unit/loom/pipeline/stores`,
  `tests/unit/loom/pipeline/execution`, `tests/unit/loom/diagnostics`.
- Required assertions or deferral reason: no contract constants, diagnostics,
  source logic, or test helpers are introduced in this phase.

### Contract Suite

- Status: deferred.
- Expected paths: `tests/contracts/test_store_contract.py`,
  `tests/contracts/test_authority_store_contract.py`,
  `tests/contracts/test_stage_worker_contract.py`.
- Required assertions or deferral reason: Phase 1 documents the contract but
  does not implement interface or conformance changes. Contract tests begin in
  Phase 2.

### Integration Suite

- Status: deferred.
- Expected paths: integration tests for local execution, planning/resume,
  stage workers, SLURM, run catalog, and diagnostics.
- Required assertions or deferral reason: no runtime/read behavior changes are
  allowed in this phase.

### E2E Suite

- Status: deferred.
- Expected paths: CLI and local pipeline e2e tests.
- Required assertions or deferral reason: no executable workflows change in
  this documentation-only phase.

### Opt-In Suites

- Status: deferred.
- Markers affected: real SLURM/HPC and any future external service/database
  suites.
- Required assertions or deferral reason: Phase 1 has no external runtime,
  service, database, or HPC behavior.

## Risks

- Inventory incompleteness is the main risk. The implementation must not rely
  on the source plan's draft baseline without re-running the searches.
- `RunStore` references are noisier than `LocalRunStore` references. The final
  map must include path-shaped runtime or behavior-read usage without turning
  every unrelated historical mention into a blocker.
- Documentation could accidentally define Phase 2 public APIs too early. Keep
  interface names aligned with the full plan but leave final shapes to Phase 2.
- Historical phase docs may be mistaken for current migration obligations.
  Classify them explicitly and avoid rewriting old records.

## Validation Commands

Targeted development commands:

```sh
rg -n "LocalRunStore|LocalRunStorePaths" src tests examples docs/features docs/implementation-plans docs/phases README.md
rg -n "\\bRunStore\\b" src tests examples docs/features docs/implementation-plans docs/phases README.md
rg -n "local_run_dir|local_stage_dir|local_artifact_root|local_stage_artifact_dir|local_stage_log_path|local_stage_worker_request_path|local_stage_worker_result_path|local_stage_workspace_dir|local_generated_artifact_path|local_run_freshness_path" src tests examples docs/features docs/implementation-plans docs/phases README.md
git diff --check
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: search evidence, line-item migration map,
  lifecycle contract text, follow-up ownership, and completion notes.
- Tests to run with each slice: targeted `rg` commands and `git diff --check`;
  broader validation is for PR preparation unless product files are changed by
  mistake.
- Decisions the executor must not revisit: local files cannot be behavior
  truth; new store interfaces belong to Phase 2; artifact store split belongs
  to Phase 3; runtime caller migration belongs to Phases 4-6; service backend
  and SQLite removal belong to Phases 7-10.
- Conditions that require stopping for the manager: inability to produce a
  complete inventory, discovery that Phase 1 must edit source behavior to make
  the contract true, missing source plan content because the local base commit
  was dropped, or any need to change the assigned branch/target/base.
- Expanded-path refinement notes: the next planner pass should verify the
  inventory output contract, tighten any under-specified contract language, and
  confirm that the implementation pass has enough detail without turning this
  document into a Phase 2 code recipe.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on 2026-05-10 by `loom_phase_planner` in branch
  `codex/authority-inventory-contracts`.
- Final phase execution plan: pending expanded-path refinement.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- Blocker-resolution summary: none used.
- PR preparation: pending.
- Stack maintenance: not applicable yet.
- Remaining blockers: none known.
