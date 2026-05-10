# Phase 1 Execution Plan: Inventory And Lifecycle Contracts

## Metadata

- Status: final phase execution plan
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
- Refine pass: completed by `loom_phase_planner` on 2026-05-10.
- Setup limitations: branch and worktree were created from local `develop`
  because the required v9-post plan commit is local-only in this checkout.
  `develop` is one commit ahead of `origin/develop`; do not drop or rebase away
  the local plan commit while preparing this phase.
- Blockers: none; ready for documentation-only implementation.

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
- The current `LocalRunStorePaths` protocol includes `resolve_run_uri`,
  `allocate_run_uri`, `local_run_dir`, `local_stage_dir`,
  `local_artifact_root`, `local_stage_artifact_dir`, `local_config_path`,
  `local_provenance_path`, `local_stage_log_path`,
  `local_stage_worker_request_path`, `local_stage_worker_result_path`,
  `local_stage_workspace_dir`, `local_generated_artifact_path`, and
  `local_run_freshness_path`.
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
- Add the line-item migration map to this phase artifact. Each line must
  identify file, line, symbol or call shape, current role, target role/action,
  owning future phase, and notes.
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
- Any source or test behavior changes. If the inventory cannot be completed
  without touching product behavior, stop for the manager instead of widening
  Phase 1.
- Changing public imports, dependency footprints, schemas, status enums, run
  directory layout, or backend behavior.
- Rewriting historical phase docs except to classify them as historical
  artifacts in the inventory.

## Assumptions

- The complete migration map lives in this phase artifact and counts as the
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

No new public runtime behavior is introduced in this phase. The implementation
is documentation-only and produces contract text that later implementation
phases must treat as authoritative.

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
| `LRS-001` | `path:line` | `LocalRunStore(...)` or helper call | one allowed classification | concise current role | concrete follow-up or no-op | `Phase 2`-`Phase 10` or `none` | evidence and secondary-role notes |

Rules:

- The final inventory must be generated from these searches, run immediately
  before the implementation commit:
  `rg -n "LocalRunStore|LocalRunStorePaths" src tests examples docs/features docs/implementation-plans docs/phases README.md`,
  `rg -n "\\bRunStore\\b" src tests examples docs/features docs/implementation-plans docs/phases README.md`,
  and the helper search in `Validation Commands`.
- Every `LocalRunStore` and `LocalRunStorePaths` hit from the required search
  scope gets a row. Do not group live source, test, example, feature-doc, or
  README hits.
- Every current `RunStore` hit gets a row when it is a type annotation,
  import/export, runtime construction requirement, protocol assertion,
  lifecycle/read call, contract-test target, or docs/example statement about
  store responsibilities. Historical implementation-plan or phase-plan hits may
  be marked historical artifact, but they still need an explicit row unless the
  row names the exact file and heading range covered.
- Every call or definition for `resolve_run_uri`, `allocate_run_uri`,
  `local_run_dir`, `local_stage_dir`, `local_artifact_root`,
  `local_stage_artifact_dir`, `local_config_path`, `local_provenance_path`,
  `local_stage_log_path`, `local_stage_worker_request_path`,
  `local_stage_worker_result_path`, `local_stage_workspace_dir`,
  `local_generated_artifact_path`, and `local_run_freshness_path` gets a row
  when it is reached through `LocalRunStore`, `LocalRunStorePaths`, a
  `RunStore` typed value, or a cast/check that depends on the current
  path-shaped store contract.
- Classification is exactly one of: `runtime mutation`, `authority read`,
  `artifact/materialized file access`, `test helper`, `docs/example`, or
  `historical artifact`. Use the notes field for secondary roles instead of
  creating new classifications.
- Rows must be dispositioned to a future phase or marked `none` for historical
  artifacts that require no migration.
- The inventory must preserve enough `rg` evidence in notes or adjacent prose
  for reviewers to reproduce coverage without reading hidden logs.
- Do not leave placeholder values in the final implementation inventory.

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

## Phase 1 Inventory Evidence

Final inventory searches were regenerated from the phase worktree before this
implementation commit. Counts include this phase artifact after the planning
sections existed, so the rows below are the authoritative disposition rather
than the raw count alone.

| Search | Matches | Distinct files | Coverage note |
| --- | ---: | ---: | --- |
| `rg -n "LocalRunStore|LocalRunStorePaths" src tests examples docs/features docs/implementation-plans docs/phases README.md` | 637 | 138 | Finds the concrete local store, path protocol, direct runtime construction, examples, tests, feature docs, and historical phase records. |
| `rg -n "\\bRunStore\\b" src tests examples docs/features docs/implementation-plans docs/phases README.md` | 376 | 72 | Finds the current path-shaped aggregate protocol plus runtime/read annotations and docs that describe the overloaded name. |
| `rg -n "resolve_run_uri|allocate_run_uri|local_run_dir|local_stage_dir|local_artifact_root|local_stage_artifact_dir|local_config_path|local_provenance_path|local_stage_log_path|local_stage_worker_request_path|local_stage_worker_result_path|local_stage_workspace_dir|local_generated_artifact_path|local_run_freshness_path" src tests examples docs/features docs/implementation-plans docs/phases README.md` | 374 | 55 | Finds local path helpers that must move to artifact/materialization roles or authority-backed factories in later phases. |

Review rule for this inventory:

- Source, active tests, examples, README, and feature docs are dispositioned by
  file or tightly related file family with concrete line evidence.
- Historical implementation-plan and phase artifacts are grouped when the row
  names exact files or phase families and classifies them as historical
  artifacts. They are not migration blockers unless they describe current
  public examples or current feature docs.
- The self-references in this phase artifact and the v9-post plan/notes are
  classified as current implementation guidance, not runtime code.

## Line-Item Migration Map

| ID | File:line | Symbol or call shape | Classification | Current role | Target role/action | Owner phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `LRS-001` | `src/loom/pipeline/stores/run_store.py:154-459` | `RunStore`, `RunLifecycleStore`, `LocalRunStorePaths`, local helper methods | runtime mutation | Current aggregate protocol mixes run lifecycle, status, plans, submitted operations, local documents, and local path helpers. | Reclaim `RunStore` for authority lifecycle and split path/document helpers into transitional or artifact-only surfaces. | Phase 2, Phase 3 | This is the central overload later phases must remove. |
| `LRS-002` | `src/loom/pipeline/stores/local_runs.py:87-1549` | `class LocalRunStore`, `resolve_run_uri`, local path helpers, lifecycle/status writers | runtime mutation | Concrete local filesystem implementation can create/open runs, write statuses, plans, submitted operations, events, locks, worker files, logs, and artifact indexes. | Keep only artifact/materialization/file-layout behavior; block or remove lifecycle behavior from supported runtime paths. | Phase 3, Phase 4, Phase 5, Phase 6 | Local files stay useful for payloads and diagnostics, not active behavior truth. |
| `LRS-003` | `src/loom/pipeline/stores/__init__.py:76,119,134,206,226-227` | Public exports for `LocalRunStore`, `LocalRunStorePaths`, `RunStore` | docs/example | Public package surface exposes overloaded runtime and local helper names. | Preserve cheap imports while moving public guidance to authority factory and artifact stores. | Phase 2, Phase 3, Phase 10 | Export cleanup waits until replacement surfaces exist. |
| `LRS-004` | `src/loom/pipeline/execution/authority_adapter.py:16,57-82,644-680,798,805` | `AuthorityBackedSerialRunStore`, `LocalRunStore`, local helper forwarding | artifact/materialized file access | Transitional adapter already uses authority for active write truth but exposes `RunStore`/`LocalRunStorePaths` shape for local materialization and compatibility. | Preserve as bridge until public `RunStore`/`StageStore` and artifact stores replace the combined shape. | Phase 2, Phase 3, Phase 9, Phase 10 | Authority semantics must not be weakened by helper forwarding. |
| `LRS-005` | `src/loom/pipeline/execution/runner.py:44-157,189,285,316,472,628,682-685,956-959,1067,1250-1265,1883` | `PipelineRunner(... run_store: RunStore)`, `_require_local_run_store`, local path helpers | runtime mutation | Direct Python runner accepts any current `RunStore`, including `LocalRunStore`, and requires local path helpers for execution. | Reject local-only mutating stores, route lifecycle through authority factory, and move file paths through artifact/materialization stores. | Phase 4, Phase 3 | This is the primary direct Python escape hatch. |
| `LRS-006` | `src/loom/pipeline/execution/lifecycle.py:16-553` | `RunStore` lifecycle helper functions | runtime mutation | Stage status, attempts, failure, skip, cancellation, and run finalization are written through the path-shaped store. | Move lifecycle mutations to authority `RunStore`/`StageStore` guarded transitions. | Phase 2, Phase 4, Phase 5 | These helpers define many behavior transitions Phase 2 must cover in contracts. |
| `LRS-007` | `src/loom/pipeline/execution/stage_attempts.py:17-138` | `RunStore`, `LocalRunStorePaths`, worker request/log path helpers | runtime mutation | Attempt preparation writes local attempt state and worker request paths through the current store. | Allocate attempts, leases, and fencing through stage authority; keep request/log paths artifact-only. | Phase 2, Phase 3, Phase 5 | Worker handoff cannot imply lifecycle authority. |
| `LRS-008` | `src/loom/pipeline/execution/stage_worker.py:25-407` | `run_stage_worker(... RunStore)`, `LocalRunStorePaths`, local artifact roots/workspaces | runtime mutation | Stage worker can load plan/request, execute, and finalize using local store plus local artifacts. | Require authority config, attempt id, lease/fence, and fenced finalization; keep local output/workspace paths as materialization. | Phase 5, Phase 8, Phase 9 | Deferred finalization must be a separate path, not a local status fallback. |
| `LRS-009` | `src/loom/pipeline/execution/continuation.py:27-1475` | `continue_prepared_run`, `run_stage_job`, `RunStore`, casts to `LocalRunStorePaths` | runtime mutation | Prepared-run and stage-job continuations resolve runs, read/write submitted state, finalization, and logs through the current store. | Acquire run/stage authority and update submitted operations and lifecycle through guarded transitions. | Phase 5, Phase 8, Phase 9 | `LocalRunStorePaths` casts may remain only for artifact/log evidence. |
| `LRS-010` | `src/loom/pipeline/execution/logs.py:14` | `local_stage_dir(...)/logs` | artifact/materialized file access | Traceback path helper assumes local stage directories. | Move under stage artifact/materialization helpers. | Phase 3, Phase 4 | No lifecycle meaning by itself. |
| `LRS-011` | `src/loom/pipeline/context.py:15-95` | `StageContext(... run_store: RunStore)` | artifact/materialized file access | Context validates the current store protocol while stages may access execution context. | Keep public context cheap and avoid exposing lifecycle-capable local stores to user stages. | Phase 4 | Any context store access must remain artifact-bound. |
| `LRS-012` | `src/loom/pipeline/planning/planner.py:13,45,105,273` | `RunStore.write_plan` | authority read | Planning persists execution plans through current `RunStore` but does not execute stages. | Route plan persistence/setup through run authority or a clearly artifact-only plan materialization boundary. | Phase 2, Phase 6 | Plan decisions must read behavior from authority when resume is involved. |
| `LRS-013` | `src/loom/pipeline/planning/resume.py:22,49,419` | `RunStore` prior-state reads | authority read | Resume planning reads prior stage state through local store interfaces. | Read stage behavior from authority snapshots/read models; use artifacts only for materialized refs. | Phase 6 | Local status/fingerprint files must not override authority facts. |
| `LRS-014` | `src/loom/cli/run.py:47,264,421,555-558,561-577,794,804,814,874,887,1079,1253,1273,1337-1340` | `_create_default_local_run_store`, `LocalRunStore()`, `allocate_run_uri`, `resolve_run_uri`, local artifact/failure paths | runtime mutation | CLI run still constructs local stores for SLURM planning/live paths, run URI resolution, executor construction, artifacts, and failure lookup. | Use the authority factory for mutating runs and capability admission before worker or SLURM submission; keep generated files artifact-only. | Phase 4, Phase 5, Phase 8, Phase 9 | Default serial local run already has authority-backed paths elsewhere, but SLURM and helper branches remain escape hatches. |
| `LRS-015` | `src/loom/cli/plan.py:27-29,188,262-310,319` | `LocalRunStore`, `RunStore`, `_create_default_run_store`, local artifact root | authority read | CLI planning uses a local store for run URI validation/resume reads and artifact root selection. | Use authority for behavior reads and artifact stores only for path/materialization selection. | Phase 6, Phase 3 | Plan CLI must remain read/projection-oriented. |
| `LRS-016` | `src/loom/cli/prepared_run.py:85-89`, `src/loom/cli/stage.py:116-119`, `src/loom/cli/stage_job.py:92-97` | CLI commands construct `LocalRunStore()` | runtime mutation | Continuation and worker commands default to local-only runtime store construction. | Require authority configuration/handoff and reject local-only finalization. | Phase 5, Phase 8, Phase 9 | These are direct operational escape hatches. |
| `LRS-017` | `src/loom/pipeline/executors/slurm/planning.py:12,51,83,93,132,460,479-480`, `paths.py:8,85,94,99`, `artifacts.py:12,78` | `RunStore`, `LocalRunStorePaths`, `local_generated_artifact_path` | artifact/materialized file access | SLURM dry-run planning uses local generated artifact paths and path protocol checks. | Keep scripts/manifests materialized via artifact store; run capability admission before planning/submission. | Phase 3, Phase 5, Phase 8 | Generated scripts are not lifecycle truth. |
| `LRS-018` | `src/loom/pipeline/executors/slurm/submission.py:11,97-107,330-340,613,624,685,713,861,904` | `RunStore`, `LocalRunStorePaths`, submitted operations | runtime mutation | Live SLURM submission writes submitted operations and validates local paths through the current store. | Authority-record submitted operations with idempotency and fail before `sbatch` when capabilities are missing. | Phase 5, Phase 8, Phase 9 | Submission must not happen before authority admission. |
| `LRS-019` | `src/loom/pipeline/executors/slurm/cancellation.py:11-12,158-170,321,351,540-545`, `status.py:11-13,229-241,338-343,752` | `LocalRunStore()`, `RunStore`, `LocalRunStorePaths`, manifest path lookup | runtime mutation | Cancellation and scheduler-status observation default to local stores and can write local submitted-operation facts/status. | Record scheduler observations and cancellation as authority submitted-operation/lifecycle updates; manifest lookup is artifact-only. | Phase 5, Phase 6, Phase 9 | Status observation may have a read-only mode, but mutation must be authority-backed. |
| `LRS-020` | `src/loom/diagnostics/inspection.py:462-527`, `preflight.py:491-505,601-604,1241-1244`, `backend.py:16,155` | `LocalRunStore`, local log/artifact helpers, backend diagnostics local paths | authority read | Diagnostics inspect local files and sometimes prefer authority where present. | Use authority for behavior; local files/logs/artifacts remain diagnostic materialization only. | Phase 6, Phase 9 | Diagnostics may explain unsupported historical layouts. |
| `LRS-021` | `src/loom/runs/_scan.py:16,90,133,197,314`, `_extract.py:15,137` | `LocalRunStore` local collection scanning and extraction | authority read | Run catalog scans local directories and overlays authority snapshots where available. | Source lifecycle facts from authority read models; local scans discover materialization only. | Phase 6, Phase 10 | Derived catalog SQLite can remain projection data. |
| `LRS-022` | `src/loom/pipeline/stores/materialization_read_models.py:33,165,246,288,302-344,358` | `LocalRunStorePaths`, config/provenance/log/worker path readers | artifact/materialized file access | Read model exposes materialized local file references alongside authority snapshot data. | Preserve as artifact/materialization read model without behavior inference. | Phase 3, Phase 6 | Good boundary if lifecycle remains authority sourced. |
| `LRS-023` | `src/loom/pipeline/stores/local_artifacts.py:116,231,244` | `LocalArtifactStore.local_stage_dir` | artifact/materialized file access | Artifact store has per-stage local path helpers independent of `LocalRunStore`. | Keep artifact-only; do not add lifecycle methods. | Phase 3 | This is the target kind of local path surface. |
| `LRS-024` | `README.md:79,109`; `examples/execution/local/run_pipeline.py:10,25`; `examples/execution/subprocess/run_subprocess_pipeline.py:13,41`; `examples/execution/subprocess/run_direct_worker.py:18,30,33`; `examples/execution/runtime-profile/run_runtime_profile.py:13,52`; `examples/operations/captured-logs/run_captured_logs.py:16,29`; `examples/operations/submitted-status/run_submitted_status.py:14,26,55` | Public examples import or instantiate `LocalRunStore` | docs/example | Public docs teach direct local-store runtime or read usage. | Replace runtime examples with authority-backed factory; keep local materialization examples explicitly artifact-only. | Phase 4, Phase 5, Phase 6 | README and examples are user-visible migration blockers. |
| `LRS-025` | `docs/features/run-store.md:20,38,255,330,1023,1105,1122-1153,1464-1470,1695-1703` | Feature-doc `RunStore`, `LocalRunStore`, `LocalRunStorePaths` contracts/examples | docs/example | Current feature doc still documents the overloaded local-file run store. | Rewrite around authority `RunStore`/`StageStore` and artifact stores, preserving historical context only where marked transitional. | Phase 2, Phase 3, Phase 10 | Highest-priority feature doc to revise. |
| `LRS-026` | `docs/features/execution.md:859,877,2048,2168-2170`; `pipeline.md:1836`; `artifacts.md:57,1075-1076`; `state.md:39,559,742-957`; `resume.md:35,1324`; `slurm.md:1085`; `sweeps.md:1156`; `provenance.md:1393,1886,2054`; `serialization.md:1704-1706`; `protocols.md:121,166,509,551,680`; `testing.md:160,573`; `cli.md:100`; `fingerprints.md:1561,2131` | Feature docs describe `RunStore` or direct local-store usage | docs/example | Feature docs assume path-shaped store writes/reads for behavior and persistence. | Update docs as corresponding implementation phases migrate interfaces, runtime, reads, and backend defaults. | Phase 2, Phase 3, Phase 4, Phase 5, Phase 6, Phase 10 | Not all docs change in one phase; each owner phase updates its topic. |
| `LRS-027` | `tests/contracts/test_store_contract.py:15-30,407-440,502,527,534,539,543-544,577` | `RunStore`/`LocalRunStorePaths` structural contract tests | test helper | Tests encode the current local-file aggregate and path protocol. | Split authority conformance from artifact/materialization contract tests. | Phase 2, Phase 3, Phase 10 | Contract matrix must stop proving local files are runtime authority. |
| `LRS-028` | `tests/contracts/test_cli_runs_contract.py:23-131`; `test_run_catalog_contract.py:9-15`; `test_run_catalog_comparison_contract.py:9-42`; `test_stage_worker_contract.py:16-41`; `test_executor_contract.py:11,28` | Contract tests construct `LocalRunStore` | test helper | Contract coverage normalizes local-store CLI/catalog/worker/executor behavior. | Replace runtime expectations with authority-backed fake/factory and artifact-only helpers. | Phase 4, Phase 5, Phase 6 | Some rows become artifact contract coverage after Phase 3. |
| `LRS-029` | `tests/package/test_pipeline_store_api.py:73,93-94,160-163`; `test_import_boundaries.py:840,860` | Public exports and import-boundary tests | test helper | Package tests expect `LocalRunStore` and local path protocol in public API. | Adjust once transitional aliases and final public factory/API are defined. | Phase 2, Phase 3, Phase 10 | Keep imports cheap while changing semantics. |
| `LRS-030` | `tests/unit/loom/pipeline/stores/test_local_runs.py:19,136-1093`; `test_materialization_read_models.py:22,253`; `test_store_errors.py:89,109-110` | Local store primitive tests | test helper | Unit tests cover local JSON/layout, path safety, statuses, submitted operations, locks, logs, worker files, and artifact indexes. | Retain local file-layout tests as artifact/materialization coverage; remove runtime-authority meaning. | Phase 3, Phase 6, Phase 10 | Many tests remain but get renamed/reframed. |
| `LRS-031` | `tests/unit/loom/pipeline/execution/test_runner.py:34-581`; `test_lifecycle.py:19-196`; `test_stage_attempts.py:19-98`; `test_stage_worker.py:24-92`; `test_stage_job.py:33-384`; `test_prepared_run_continue.py:23-96`; `test_authority_adapter.py:41-575`; `test_eventing.py:7-35`; `test_run_locks.py:10-50` | Runtime unit tests construct local stores | test helper | Tests cover runner, lifecycle, worker, continuation, events, locks, and adapter behavior through `LocalRunStore`. | Move runtime cases to authority fakes/factory; keep local path assertions under artifact/materialization tests. | Phase 4, Phase 5, Phase 6 | Add local-only rejection regressions in Phase 4/5. |
| `LRS-032` | `tests/unit/loom/pipeline/executors/test_local_executor.py:23-70`; `test_subprocess_executor.py:35-83`; `executors/slurm/test_slurm_submission.py:41-407`; `test_slurm_cancellation.py:19-223`; `test_slurm_paths.py:23` | Executor and SLURM unit tests use local store/path helpers | test helper | Tests assert executor path construction and SLURM generated artifacts/submitted state through local stores. | Use artifact stores for paths and authority fakes for submitted lifecycle. | Phase 3, Phase 5, Phase 8 | Real SLURM remains opt-in. |
| `LRS-033` | `tests/unit/loom/cli/test_run.py:30,433`; `test_plan.py:86`; `tests/unit/loom/pipeline/planning/test_planner.py:11,69,74`; `test_resume.py:24-524`; diagnostics unit tests from search output | test helper | CLI/planning/resume tests use local stores for default construction and prior-state reads. | Move behavior reads to authority snapshots and keep local roots artifact-only. | Phase 4, Phase 6 | Planning should never infer behavior from local status files after Phase 6. |
| `LRS-034` | `tests/integration/pipeline/test_local_execution.py:12-167`; `test_local_execution_resume.py:10-61`; `test_local_execution_failures.py:11-163`; `test_parallel_execution.py:17,125`; `test_subprocess_executor_integration.py:12-131`; `test_stage_worker_integration.py:20-77` | test helper | Integration tests validate runtime workflows using `LocalRunStore`. | Convert runtime workflows to authority-backed stores and artifact helpers. | Phase 4, Phase 5, Phase 9 | Failure-path tests should assert failure-closed authority diagnostics. |
| `LRS-035` | `tests/integration/pipeline/test_run_catalog_compare.py:15-152`; `test_run_catalog_direct_scan.py:16-23`; `test_run_catalog_current_list.py:16-278`; `test_run_catalog_sqlite.py:9-103`; `tests/integration/pipeline/test_cli_runs.py:18-153`; `tests/contracts/test_cli_runs_contract.py:23-131` | Catalog and runs tests use local scanning/store writes | test helper | Catalog projections can still be seeded by local files. | Source behavior facts from authority read models; keep local scan as materialization discovery. | Phase 6, Phase 10 | Derived SQLite projection remains non-authoritative if retained. |
| `LRS-036` | `tests/integration/pipeline/test_slurm_dry_run_planning.py:33-147`; `test_slurm_model_store_paths.py:14-61`; `test_slurm_cancellation_integration.py:17-109`; `tests/e2e/test_cli_slurm_live_single_job.py:13,81` | test helper | SLURM tests seed local stores and validate generated manifests/submitted status. | Gate submission through authority; keep scripts/manifests generated artifact evidence. | Phase 5, Phase 8, Phase 9 | Live-worker/deferred profile tests arrive after service/profile phases. |
| `LRS-037` | `tests/integration/diagnostics/test_cli_status_logs.py:18-269`; `tests/integration/config/test_cli_plan.py:13,110`; `tests/integration/docs/test_v0_python_examples.py:19,74`; `tests/support/slurm_status_fixtures.py:35-94` | Diagnostics/config/docs/support fixtures use `LocalRunStore` | test helper | Tests and fixtures seed logs, plans, runs, and manifests via local files. | Separate artifact/log fixtures from authority behavior fixtures. | Phase 4, Phase 5, Phase 6 | Fixture ownership matters for later broad migrations. |
| `LRS-038` | `tests/e2e/test_local_pipeline_run.py:14-325`; `test_cli_core.py:23-732`; `test_cli_runs_e2e.py:20-106` | E2E tests construct local stores or inspect local files | test helper | User-visible flows still validate local-store runtime or diagnostics behavior. | Move execution to authority-backed defaults; keep local file inspection only where commands are artifact/log readers. | Phase 4, Phase 5, Phase 6, Phase 9 | E2E coverage should track public behavior, not implementation store names. |
| `LRS-039` | `docs/implementation-plans/implementation-plan-v9-post.md`; `roadmap-v9-post-planning-notes.md` | Current plan guidance for `RunStore`, `StageStore`, `LocalRunStore` | docs/example | Active planning artifacts define this migration. | Keep as source-of-truth guidance and update status/metadata as phases complete. | All phases | Not a runtime escape hatch. |
| `LRS-040` | `docs/implementation-plans/implementation-plan-v0.md`; `implementation-plan-v0-post.md`; `implementation-plan-v9.md`; `roadmap-v3-planning-notes.md`; `roadmap-v9-planning-notes.md`; other roadmap notes from searches | Historical plan references | historical artifact | Older plans record the path-shaped local store history. | Do not rewrite unless a later doc-cleanup phase explicitly updates historical context. | none | Useful archaeology, not active behavior. |
| `LRS-041` | `docs/phases/v0-post-store-capabilities.md`; `add-local-stores-run-layout.md`; `add-local-execution.md`; `serial-write-integration.md`; `public-backend-swap.md`; `persistence-contracts.md`; `slurm-*`; `run-catalog-*`; `add-*`; corresponding PR bodies found by searches | Historical phase and PR artifacts | historical artifact | Past phase artifacts explain how the current local store became overloaded. | Preserve as historical records; future phases may cite them but should not mutate them for product behavior. | none | Current feature docs and code are the migration targets. |
| `LRS-042` | `docs/phases/authority-inventory-contracts.md` | This phase artifact self-references searches and classifications | docs/example | Current durable handoff and inventory. | Keep updated with completion notes and validation evidence. | Phase 1 | Self matches are expected after implementation. |

## Follow-Up Ownership By Future Phase

| Owner | Inventory scope owned |
| --- | --- |
| Phase 2 | Reclaim public authority `RunStore`; introduce scoped `StageStore`; define factory/configuration/capability vocabulary; build authority conformance harness; stop treating path-shaped local stores as authority implementations. |
| Phase 3 | Split local path, config, provenance, log, worker-file, generated manifest, and artifact-index access into `RunArtifactStore`/`StageArtifactStore` or equivalent materialization-only surfaces. |
| Phase 4 | Migrate direct Python runner construction, public examples, README execution snippets, and Python API tests away from `PipelineRunner(run_store=LocalRunStore(...))`; add local-only mutation rejection. |
| Phase 5 | Migrate `loom run` operational paths, stage worker CLI, stage-job continuation, prepared-run continuation, SLURM submission/status/cancellation, submitted operations, and worker finalization to authority-backed lifecycle. |
| Phase 6 | Move status, catalog, plan/resume reads, diagnostics, preflight, and extraction to authority read models; preserve local scans/logs/files only as materialization evidence. |
| Phase 7 | Prove the concrete service/database backend against the authority contracts; do not depend on direct shared-file SQLite authority. |
| Phase 8 | Model HPC deployment profiles and deferred finalization so offline envelopes are evidence for later authority reconciliation, not live lifecycle truth. |
| Phase 9 | Adopt service/profile configuration through runtime/read systems and handoff records after the backend and deployment semantics exist. |
| Phase 10 | Remove run-local SQLite authority from supported runtime behavior while keeping derived catalog SQLite sidecars only as rebuildable projections if retained. |
| None | Historical implementation plans, historical phase plans, and PR bodies that only describe already-merged work. |

## Authority Lifecycle Contracts

### Run Lifecycle

- Run admission creates or registers one unique `run_uri`, workspace reference,
  initial run metadata, initial lifecycle status, and initial authority
  revision before user-visible mutation begins.
- Opening or resuming a run requires authority reachability and, when the
  selected backend/profile can race with another controller, acquisition or
  renewal of a run-level controller lease with owner identity and fencing
  material.
- Planning and submission setup are authority facts when they affect future
  behavior. Local `plan.json`, prepared-run files, manifests, or scripts may
  materialize the selected plan, but they are not the active truth for whether
  a run is admitted, active, submitted, cancelled, failed, or complete.
- Run status transitions carry an expected prior status, expected revision, or
  equivalent compare-and-set guard. A stale expected value fails the transition
  instead of consulting local files.
- Cancellation and interruption are guarded authority transitions. If submitted
  work exists, the transition records scheduler/submitted-operation facts or a
  pending observation rather than only changing local status files.
- Run finalization is derived from authoritative stage terminal facts and
  committed through run authority. A run cannot become successful merely
  because local stage output files exist.
- Run snapshots are revisioned read models that can include stage summaries,
  active leases, expired leases, abandoned attempts, submitted operations,
  cleanup candidates, stale work, and recovery hints.
- Recovery scans read authority records for expired leases, abandoned attempts,
  stale submitted operations, incomplete commits, and cleanup candidates.
  Directory scans may find materialization but cannot decide lifecycle.

### Stage Lifecycle

- A stage is opened through a scoped `StageStore` under its parent run
  authority. Callers do not create independent stage lifecycle stores by
  pointing at a stage directory.
- Stage attempt allocation is atomic. It records the next attempt, owner id,
  planned stage action, initial attempt state, and resulting revision, and it
  may issue or require a stage lease in the same authority boundary.
- Workers and controllers that can race must hold a valid stage lease and
  fencing token before mutating stage lifecycle or committing terminal output.
- Running, submitted, failed, cancelled, blocked, skipped, or succeeded stage
  transitions carry expected status/revision and, where relevant, attempt id,
  lease id, owner id, and fencing token.
- Output commit is the only path that makes materialized outputs visible as a
  successful stage result. It atomically verifies attempt id, current stage
  state, lease/fence validity, absence of a prior successful commit, artifact
  facts/materialized refs, cleanup candidates, terminal status, and resulting
  revision.
- Local stage directories, worker requests/results, logs, failure files,
  fingerprints, and output manifests are materialization/evidence. They do not
  authorize success, retry, cancellation, or downstream reuse without an
  accepted authority transition.
- Stale attempts, expired leases, foreign fencing tokens, duplicate commits,
  cancelled runs, and superseded attempts reject terminal stage mutation before
  success is visible.
- Stage recovery scans are authority scans. They identify abandoned attempts,
  expired leases, retry candidates, stale submitted work, and cleanup
  candidates without trusting local status JSON.

### Submitted-Operation Lifecycle

- Submitted work is structured authority state keyed by run, submission id,
  and optionally an idempotency key. Submission creation is replay-safe and
  cannot create competing active records for the same operation.
- Scheduler observations, job ids, state changes, cancellation requests,
  cancellation observations, retry facts, and terminal scheduler outcomes are
  appended or updated through guarded authority operations.
- A submitted operation links to the run and, when applicable, the stage name,
  attempt id, owner id, deployment profile, and worker handoff authority
  reference. Local manifests/scripts/logs are artifacts linked from the record.
- Status observation may read scheduler state and local manifests as evidence,
  but mutating observation records or lifecycle state must go through
  authority. Read-only commands must be explicit when they do not mutate.
- Cancellation must update authority first or record authority-observable
  intent before scheduler-side cancellation results are treated as lifecycle
  facts.
- Retry handling uses authority idempotency and expected state. A replayed
  submit/status/cancel command either returns the existing compatible record or
  fails with stale/incompatible diagnostics.
- Worker finalization is either live authority commit with lease/fence material
  or deferred result envelope materialization for later reconciliation. It is
  never a local submitted-operation/status-file write that marks success.

### Failure-Closed Behavior

- `authority.unavailable`: mutating operations fail before irreversible work
  such as stage launch, worker finalization, or SLURM submission, unless the
  selected operation is explicitly deferred-finalization envelope production.
- `authority.schema_incompatible`: callers fail with a compatibility
  diagnostic and do not infer lifecycle from local layouts.
- `authority.unsupported_capability`: capability admission fails before
  scheduling/launch when the selected backend/profile lacks required
  guarantees.
- `authority.stale_transition`: expected status, revision, attempt, or
  submitted-operation state does not match; the caller reports stale state and
  does not overwrite local files to force progress.
- `authority.lease_expired` and `authority.foreign_fence`: stage/run mutation
  and output commit fail when the lease is expired, missing, or owned by a
  different fence.
- `authority.local_lifecycle_disallowed`: direct local-only lifecycle mutation
  or behavior reads are rejected with guidance to use authority-backed
  factories or artifact-only inspection.
- `authority.deferred_rejected`: deferred result envelopes are rejected when
  stale, duplicate, malformed, cancelled, superseded, or inconsistent with the
  recorded attempt/submission.
- Local materialization remains recoverable after failure. Recovery is a later
  authority-backed scan/reconciliation decision, not an automatic local-file
  promotion.

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
   artifact using the fixed inventory output contract above.
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
- Required assertions or deferral reason: package test execution is deferred
  because Phase 1 does not change exports, imports, or product code. A manual
  import-boundary review is required in the phase artifact; any package/source
  edit should stop the phase for manager review before tests are added.

### Unit Suite

- Status: deferred.
- Expected paths: `tests/unit/loom/pipeline/stores`,
  `tests/unit/loom/pipeline/execution`, `tests/unit/loom/diagnostics`.
- Required assertions or deferral reason: no contract constants, diagnostics,
  source logic, or test helpers are introduced in this phase; unit tests begin
  when later phases change those behaviors.

### Contract Suite

- Status: deferred.
- Expected paths: `tests/contracts/test_store_contract.py`,
  `tests/contracts/test_authority_store_contract.py`,
  `tests/contracts/test_stage_worker_contract.py`.
- Required assertions or deferral reason: Phase 1 documents the contract but
  does not implement interface or conformance changes. Contract test execution
  and new contract assertions begin in Phase 2.

### Integration Suite

- Status: deferred.
- Expected paths: integration tests for local execution, planning/resume,
  stage workers, SLURM, run catalog, and diagnostics.
- Required assertions or deferral reason: no runtime/read behavior changes are
  allowed in this phase, so integration execution is deferred.

### E2E Suite

- Status: deferred.
- Expected paths: CLI and local pipeline e2e tests.
- Required assertions or deferral reason: no executable workflows change in
  this documentation-only phase, so e2e execution is deferred.

### Opt-In Suites

- Status: deferred.
- Markers affected: real SLURM/HPC and any future external service/database
  suites.
- Required assertions or deferral reason: Phase 1 has no external runtime,
  service, database, or HPC behavior; opt-in suites remain intentionally
  deferred.

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
rg -n "resolve_run_uri|allocate_run_uri|local_run_dir|local_stage_dir|local_artifact_root|local_stage_artifact_dir|local_config_path|local_provenance_path|local_stage_log_path|local_stage_worker_request_path|local_stage_worker_result_path|local_stage_workspace_dir|local_generated_artifact_path|local_run_freshness_path" src tests examples docs/features docs/implementation-plans docs/phases README.md
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
- Expanded-path refinement notes: completed on 2026-05-10. The plan is
  implementable as a documentation-only phase; do not run another planning
  refine pass without explicit manager instruction.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-10
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on 2026-05-10 by `loom_phase_planner` in branch
  `codex/authority-inventory-contracts`.
- Final phase execution plan: completed on 2026-05-10 by expanded-path
  refinement in branch `codex/authority-inventory-contracts`.
- Implementation summary: completed locally after Spark executor quota was
  unavailable. Added Phase 1 inventory evidence, a migration map covering
  current source, tests, examples, feature docs, implementation docs,
  historical phase artifacts, and current planning artifacts, plus explicit
  run lifecycle, stage lifecycle, submitted-operation lifecycle, and
  failure-closed authority contracts. No source, test, example, workflow, or
  runtime behavior files were changed.
- Implementation validation: targeted inventory searches rerun after the
  inventory section was added:
  `LocalRunStore|LocalRunStorePaths` returned 637 matches across 138 files;
  `\bRunStore\b` returned 376 matches across 72 files; the local helper search
  returned 374 matches across 55 files. `git diff --check` passed. Broad
  `make validate-pr` and `make test-summary` are deferred to PR preparation
  because this phase is documentation-only.
- Refinement summary: inventory output rules tightened for `LocalRunStore`,
  `LocalRunStorePaths`, current path-shaped `RunStore`, and local helper calls;
  suite decisions and documentation-only stop conditions confirmed.
- Implementation refinement report: completed on 2026-05-10 for the single
  expanded-path implementation refinement pass. Reviewed the current
  documentation-only diff, source Phase 1 scope and acceptance criteria,
  recorded validation evidence, and this artifact's lifecycle contract
  coverage. The only phase-scoped fix was budget/completion-note bookkeeping:
  mark implementation refinement used and record this no-blocker refinement
  summary. No product source, tests, examples, workflow prompts/templates, or
  unrelated docs were changed.
- Implementation refinement validation: `git diff --check` was rerun after
  this artifact update and passed. Broad `make validate-pr` and
  `make test-summary` remain deferred to PR preparation as already recorded
  for this documentation-only phase.
- Blocker-resolution summary: none used; budget remains 0/3.
- PR preparation: draft body completed locally in
  `docs/phases/authority-inventory-contracts-pr-body.md`. Final validation
  passed before PR preparation: `make validate-pr` completed Ruff, Pyright,
  default harness, config-extra, and build successfully; `make test-summary`
  wrote `build/test-summary.md` with overall 1534 passed, 12 skipped, 1128
  deselected, and 0 failed/errors. Pre-submit blocker gate completed locally
  against the source plan, phase plan, diff, PR body, validation evidence,
  scope boundaries, and future-phase exclusions; no blockers found. PR body
  refine/open pass remains pending until branch push and explicit PR creation.
- Stack maintenance: not applicable yet.
- Remaining blockers: none known.
