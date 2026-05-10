# Roadmap v9-post Planning Notes: Authority-Backed Runtime Unification And Service Backend

## Metadata

- Roadmap version: v9-post
- Source roadmap:
  `docs/implementation-plans/implementation-roadmap.md`
- Previous version status: complete. `implementation-plan-v9.md` records v9 as
  implemented with all phases merged, including per-run authority contracts,
  the run-local SQLite authority backend, materialization read models,
  authority-backed serial execution, backend diagnostics, bounded local
  parallel execution, and workspace coordination contracts.
- Planning notes status: confirmed; implementation-plan draft handoff complete
- Current discussion stage: Implementation-plan draft complete
- Stage gates:
  - Roadmap framing: complete for initial post-v9 reframing
  - Intent discovery: initial user intent recorded
  - Feature brainstorming: initial target capabilities recorded
  - Functionality and behavior confirmation: revised behavior confirmed by user
  - Context compaction/reset checkpoint: prepared in notes; formal reset not run because the design questions were resolved in-session
  - Design decision review: revised queue recorded
  - Phase shaping: complete; ten-phase plan after post-draft HPC deployment
    refinement
  - Handoff: complete; `implementation-plan-v9-post.md` drafted and refined
- Related implementation plans:
  - `docs/implementation-plans/implementation-plan-v9-post.md`
  - `docs/implementation-plans/implementation-plan-v9.md`
  - `docs/implementation-plans/roadmap-v10-planning-notes.md`
- Related feature docs:
  - `docs/features/run-store.md`
  - `docs/features/state.md`
  - `docs/features/execution.md`
  - `docs/features/reliability.md`
  - `docs/features/resume.md`
  - `docs/features/remote-stores.md`
  - `docs/features/sweeps.md`
  - `docs/features/run-catalog.md`
  - `docs/features/slurm.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
  - `docs/structure.md`
- Blockers:
  - None known for planning. The implementation plan now needs its normal plan
    quality gate before phase execution begins.

## Roadmap Extraction

Baseline roadmap outcome:

- Make authority-backed state mandatory for every run and stage mutation path.
- Deprecate `LocalRunStore` as a runtime entrypoint while retaining local
  path/materialization helpers as an internal implementation detail.
- Preserve backend-neutral contracts so the current run-local SQLite authority
  can be replaced or complemented by a real service/database authority backend.
- Define the target control-plane shape for concurrent runs, multi-host
  controllers, concurrent stages, submitted jobs, and workspace/sweep
  coordination.
- Move SLURM dry-run/live submission, stage worker, stage-job continuation,
  prepared-run continuation, examples, and public Python docs away from direct
  `LocalRunStore` mutation.
- Clarify run and stage lifecycle state machines as contract-level behavior:
  controller lease, run status transitions, stage attempt allocation, stage
  lease/fencing, output commit, terminal stage status, run finalization,
  recovery scans, and diagnostics.
- Add service-backend planning for a durable central authority implementation
  with one source of truth across terminals, hosts, workers, submitted jobs,
  and future sweep controllers.
- Do not preserve old local-only run/stage lifecycle compatibility. Provide
  explicit local artifact/materialization interfaces so users can inspect or
  consume run and stage directories programmatically without reading, writing,
  or inferring run/stage behavior from local files.

Prerequisites:

- v9 per-run authority contracts and read models.
- v9 SQLite per-run authority backend and authority-backed serial adapter.
- v9 workspace coordination contract and local SQLite coordination backend.
- v5 durable stage-worker request/result contracts.
- v7 submitted-operation and stage-job continuation contracts.
- v8 catalog projections and freshness/read-model concepts.

Primary feature docs:

- `run-store.md`
- `state.md`
- `execution.md`
- `reliability.md`
- `remote-stores.md`
- `sweeps.md`
- `run-catalog.md`
- `slurm.md`
- `cli.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Deleting local materialization files or removing local artifact/log/config
  helpers.
- Hosted deployment, authentication, tenancy, and operations for a production
  service.
- A distributed scheduler, work queue, worker daemon, or workflow engine.
- Full sweep execution, adaptive search, or scheduler admission policy.
- Remote artifact payload movement or remote object-store authority.
- Migration or lifecycle interpretation of historical local-only v0-v8 runs.
- Changing core run or stage status enums solely to describe UI phases.

Compatibility obligations:

- New mutating runs must not have a local-only fallback.
- Local JSON/log/config/provenance/worker files are materialization and
  diagnostic surfaces, not active truth.
- Public examples must stop teaching `PipelineRunner(run_store=LocalRunStore(...))`.
- `LocalRunStore` may remain importable temporarily for internal adapter
  construction while it is renamed or split, but documentation must mark it
  unsuitable for runtime mutation and unsuitable for local lifecycle reads.
- Local run/stage directories may be exposed through artifact/materialization
  interfaces only. Those interfaces must not read or write run status, stage
  status, attempts, leases, submitted operations, output commits, recovery
  records, or any other lifecycle behavior.
- Existing stage-worker handoff files remain useful, but finalization must be
  fenced by authority when an authority backend exists.
- The v9 run-local SQLite authority backend is transitional. Once the revised
  service/database backend is available, embedded SQLite authority should no
  longer be the recommended runtime backend. Derived catalog SQLite sidecars
  are separate and remain rebuildable projection data, not active authority.

## Version Briefing

What this version is:

- V9-post is the authority unification and service-backend planning step after
  v9. V9 built the contracts and local SQLite authority path; v9-post closes
  the remaining escape hatches so all active run and stage lifecycle mutations
  enter through authority-backed stores. It also plans the stronger
  service/database backend needed for multi-host and concurrent-controller
  use cases.

Why this version exists:

- V9 made default local `loom run` authority-backed, but several real
  entrypoints can still mutate local-only files: direct Python API usage,
  examples, SLURM dry-run/live submission, `loom stage run`, `loom stage-job
  run`, and prepared-run continuation scaffolding. That split makes future
  features harder because they cannot assume every run has attempts, leases,
  fencing tokens, guarded transitions, committed artifact facts, revisions,
  or recovery scans.
- A service/database authority backend is needed before Loom can claim robust
  multi-host behavior. The current run-local SQLite authority gives local or
  same-host correctness when SQLite file locking is reliable; it is not a
  central control plane for arbitrary shared filesystems or remote workers.

Impacted or linked work:

- Direct predecessor: v9 persistence and concurrency foundation.
- Direct successor: v10 bundles/exporters. Bundles should archive
  authority-backed truth and materialized refs rather than local-only active
  state.
- Later successor: v11 deterministic sweeps. Sweeps should allocate trials,
  run URIs, and resource leases through workspace coordination rather than
  directory scans.
- Later successor: v13/v14 remote stores. Remote artifact payload work should
  not be confused with active lifecycle authority.
- Later successor: v17 reliability. Retry, timeout, and event-sink behavior
  should build on mandatory attempt/lease/commit records.

Likely public surfaces and durable artifacts:

- `AuthorityBackedRunStore` or equivalent public factory as the only supported
  runtime store constructor.
- A store factory/registry surface that can select embedded SQLite authority,
  local service authority, or future remote service authority by capability.
- Deprecation warnings or documentation for direct `LocalRunStore` runtime
  use.
- Service authority protocol or adapter implementation, likely preserving
  `PerRunAuthorityStore` and `WorkspaceCoordinationStore` logical contracts.
- CLI and Python API updates for all mutating entrypoints to open authority
  stores.
- Diagnostics that explain when a run is local-only, authority-backed, or using
  an unavailable/incompatible authority backend.

Structure rationale:

- This version is a post-v9 hardening step rather than v10 because bundles and
  sweeps should not inherit local-only mutation paths. It has one product
  outcome: every active run and stage lifecycle mutation goes through the same
  authority contract, and service-backed authority becomes the next concrete
  backend direction.

Visible assumptions, risks, and constraints:

- The target is not necessarily a daemon for every local run. The contract is
  mandatory authority, not mandatory process topology. Embedded SQLite can
  remain a supported single-host backend; a service/database backend is needed
  for multi-host guarantees.
- A real service backend may physically combine workspace and per-run tables,
  but the logical boundaries should remain separate: workspace coordination
  handles cross-run admission and resource facts; per-run authority handles
  run and stage lifecycle facts.
- Stage-worker and submitted-job flows need careful fencing. A worker must not
  finalize output commits solely because it can write local files.
- API deprecation must distinguish runtime mutation, authority read models, and
  local artifact/materialization helpers. Local helper APIs must not become a
  compatibility route for run/stage lifecycle behavior.
- Renaming is part of the design work. `LocalRunStore` currently combines too
  many meanings: local path allocation, local document persistence, lifecycle
  state, submitted operations, logs, worker handoff files, and artifact index
  materialization.

User clarification questions and resolved answers:

- Clarification: Should `LocalRunStore` be deprecated because all runs and
  stages need authority-backed lifecycle management?
  Resolved answer: Yes. Deprecate `LocalRunStore` as a runtime entrypoint.
  Retain or replace it only as internal local artifact/materialization/path
  support, with no run/stage lifecycle read compatibility.
- Clarification: Does authority require a persistent DB worker process?
  Resolved answer: Not for every backend. The invariant is that all mutating
  entrypoints use the authority interface. The current embedded SQLite backend
  provides a single run-local database file; a future service/database backend
  provides stronger multi-host and concurrent-controller guarantees.
- Clarification: Should the root have a workspace authority and each run have
  a run authority?
  Resolved answer: Conceptually, yes, but public runtime names should be
  `RunStore` and `StageStore`. `RunStore` owns run admission/opening,
  run-level leases, run lifecycle, submitted operations, snapshots, and access
  to scoped stage stores. `StageStore` is within a run and owns stage
  lifecycle, attempts, leases, fencing, output commits, submitted facts,
  recovery, and cleanup candidates. A separate workspace/coordination surface
  may remain for sweep/resource facts that are not run lifecycle.
- Clarification: Should SQLite authority remain a long-term runtime backend?
  Resolved answer: No. It can remain as transitional v9 machinery and possibly
  as a local development/test backend while the service/database backend is
  introduced, but the target runtime behavior should be service/database backed
  for declared consistency guarantees.
- Clarification: Should old local-only run directories remain readable as run
  or stage lifecycle state?
  Resolved answer: No. Do not preserve old local lifecycle compatibility. A
  local programmatic interface is still useful for artifact and materialized
  file access, but it must not read, write, or infer run/stage behavior.
- Clarification: Should the root authority be called `RunStore` instead of
  `WorkspaceAuthorityStore`?
  Resolved answer: Public runtime naming should make `RunStore` the authority
  surface that manages runs, run-level leases, run admission/opening, and
  run-level lifecycle. A separate workspace-oriented contract may remain for
  non-run workspace/sweep/resource coordination when needed, but it should not
  obscure that `RunStore` manages runs.

## Current LocalRunStore Runtime Entry Point Inventory

Inventory categories:

- Runtime mutation escape hatch: a supported path can create, resume, submit,
  cancel, finalize, or otherwise mutate run/stage lifecycle without authority.
- Authority-backed but local-materialized: authority is active truth, but the
  implementation still uses `LocalRunStore` for local paths or documents.
- Local artifact/materialization access: not an active lifecycle entrypoint and
  not a lifecycle read path. These interfaces may expose local files,
  directories, logs, generated manifests, and payload refs, but not run or
  stage behavior.

| Area | Current files | Current behavior | Category | Required v9-post action |
| --- | --- | --- | --- | --- |
| Default local/subprocess `loom run` | `src/loom/cli/run.py`, `src/loom/pipeline/execution/authority_adapter.py` | `_create_default_run_store()` returns `AuthorityBackedSerialRunStore`, which delegates active run/stage writes to `PerRunAuthorityStore` but still constructs `LocalRunStore` for run URI allocation, documents, paths, logs, worker files, and artifact materialization. | Authority-backed but local-materialized. | Keep authority path, rename/materialize local helper, replace SQLite default once service backend is ready, and remove public typing that implies `LocalRunStore` is a runtime store. |
| Direct Python runner construction | Examples and many tests call `PipelineRunner(run_store=LocalRunStore(...))`. | Users can bypass authority by constructing the runner with `LocalRunStore` directly. | Runtime mutation escape hatch. | Public examples should use an authority-backed factory. `PipelineRunner` should reject local-only runtime stores unless a narrowly scoped test/materialization compatibility hook is used. |
| SLURM dry-run planning | `src/loom/cli/run.py` `build_slurm_dry_run_result()` and SLURM planning helpers. | Uses `_create_default_local_run_store()`, creates run directories, writes plans/prepared-run records, and generates local manifests without authority. | Runtime mutation escape hatch. | Use authority-backed run creation and planning state. Treat generated scripts/manifests as materialization only. |
| SLURM live submission | `src/loom/cli/run.py`, `src/loom/pipeline/executors/slurm/submission.py` | Uses `LocalRunStore` to create runs, persist plans/prepared records, write submitted operations, and write run/stage `SUBMITTED` status. | Runtime mutation escape hatch. | Submitted-operation writes and run/stage submitted transitions must go through authority with submission idempotency and fencing. Local manifests remain materialized artifacts. |
| Stage worker CLI | `src/loom/cli/stage.py`, `src/loom/pipeline/execution/stage_worker.py` | `loom stage run` constructs `LocalRunStore()` and may execute/finalize a prepared attempt from local files. | Runtime mutation escape hatch. | Worker CLI must open the configured authority for the run, require the prepared attempt/lease/fencing token, and commit success/failure through authority. |
| Stage-job continuation CLI | `src/loom/cli/stage_job.py`, `src/loom/pipeline/execution/continuation.py` | `loom stage-job run` constructs `LocalRunStore()` and finalizes self-contained submitted stage jobs. | Runtime mutation escape hatch. | Stage-job finalization must be authority-backed and reject local-only finalization for authority-backed runs. |
| Prepared-run continuation CLI | `src/loom/cli/prepared_run.py`, `src/loom/pipeline/execution/continuation.py` | `loom prepared-run continue` constructs `LocalRunStore()` and resumes whole-run submitted state from local records. | Runtime mutation escape hatch. | Whole-run continuation must acquire controller authority and update run/stage lifecycle through guarded authority transitions. |
| SLURM cancellation | `src/loom/pipeline/executors/slurm/cancellation.py` | Defaults to `LocalRunStore()`, reads the latest submitted operation, calls `scancel`, writes cancellation facts, and writes run/stage `CANCELLED` status. | Runtime mutation escape hatch. | Cancellation must be a guarded submitted-operation update plus authority stage/run cancellation transition. |
| SLURM scheduler status inspection | `src/loom/pipeline/executors/slurm/status.py` | Defaults to `LocalRunStore()`, reads submission state, queries scheduler facts, and writes updated submitted-operation metadata. | Operational mutation escape hatch. | Scheduler facts should be recorded through authority as submitted-operation observations, or the command should run in explicit read-only mode. |
| `loom plan` | `src/loom/cli/plan.py` | Constructs `LocalRunStore` for run URI validation, resume reads, and local artifact root selection. Plan persistence is disabled for the CLI plan result. | Runtime-adjacent read/projection path. | Source any run/stage behavior from authority only. Local artifact root selection should use artifact/materialization interfaces and must not read local lifecycle state. |
| Execution internals needing local paths | `runner.py`, `stage_worker.py`, `stage_attempts.py`, `continuation.py`, subprocess and SLURM helpers. | Runtime code checks `LocalRunStorePaths` for local stage dirs, artifact roots, worker request/result paths, logs, and generated artifacts. | Local artifact/materialization access. | Replace `LocalRunStorePaths` with run/stage artifact-materialization protocols, and keep lifecycle mutation behind authority APIs. |
| Diagnostics and preflight | `src/loom/diagnostics/inspection.py`, `src/loom/diagnostics/backend.py`, `src/loom/diagnostics/preflight.py` | Builds `LocalRunStore` for local run inspection, filesystem checks, logs, and compatibility readbacks. Some diagnostics already prefer authority when present. | Mixed authority read and local materialization access. | Active run/stage behavior must come from authority. Local diagnostics may inspect files/logs/artifacts only and must not present local files as lifecycle truth. |
| Run catalog and extraction | `src/loom/runs/_scan.py`, `src/loom/runs/_extract.py`, `src/loom/runs/_sqlite.py` | Scans local collections with `LocalRunStore` and has authority snapshot overlay where available. | Projection path that currently risks local lifecycle compatibility. | Catalog lifecycle facts must come from authority-backed read models. Local directory scans may discover artifact/materialization files but must not infer run/stage behavior. |
| Store primitive tests | `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/contracts/test_store_contract.py` | Tests `LocalRunStore` as the local file layout/store primitive. | Materialization/store primitive. | Rename tests around run/stage artifact-materialization classes. Do not use these tests as runtime authority or lifecycle read evidence. |
| Runtime behavior tests | Runner, local execution, resume, parallel execution, subprocess, stage-worker, stage-job, SLURM, and CLI run tests. | Many tests construct `LocalRunStore` because it used to be the default runtime store. | Runtime mutation escape hatch in tests. | Replace with authority-backed fake/service-backed factories. Add regression tests that local-only runtime mutation fails. |
| Public examples and feature docs | `examples/execution/local`, `examples/execution/subprocess`, `examples/operations/captured-logs`, `examples/operations/submitted-status`, `docs/features/run-store.md`, `docs/features/pipeline.md`, `docs/features/execution.md`. | Several examples teach `LocalRunStore` as the normal runner store. | Public API escape hatch. | Update examples to the authority-backed factory and move local materialization examples to explicit advanced/internal docs. |

This inventory should be kept current in the eventual implementation plan. A
planning phase should run `rg -n "LocalRunStore|LocalRunStorePaths"` and classify
each remaining result before implementation begins.

## User Intent

Target audience:

- Loom maintainers and users running concurrent local or cluster workloads.
- Future sweep, SLURM, subprocess, container, and remote-store users who need
  one lifecycle model independent of entrypoint.
- Operators who need a central source of truth across terminals or hosts.

User-visible outcome:

- Users no longer need to know which entrypoints are authority-backed. Every
  normal run, stage worker, submitted job, and continuation path uses authority
  state automatically.
- Concurrent runs can start from different terminals without directory-level
  race assumptions becoming the lifecycle source of truth.
- Concurrent stages in a run are admitted through stage attempts, leases, and
  fenced commits.
- Diagnostics can explain active, stale, abandoned, submitted, succeeded,
  failed, cancelled, or blocked work from authoritative facts.

Success criteria:

- `PipelineRunner` rejects local-only runtime mutation.
- CLI run, SLURM submission, stage worker, stage-job, and prepared-run commands
  use authority-backed stores for any mutating behavior.
- Public docs and examples stop constructing `LocalRunStore` for execution.
- Local run/stage directory access is available through artifact/materialization
  interfaces only, not as lifecycle compatibility.
- A service/database backend design exists with capability and failure-mode
  definitions for multi-host operation.

Non-goals:

- Removing local files used for artifacts, logs, config snapshots, provenance,
  worker request/result handoff, or bundle materialization.
- Implementing a scheduler or worker pool.
- Making SQLite over arbitrary network filesystems a supported distributed
  database.
- Preserving old local-only run/stage behavior reads.

Constraints:

- Keep backend contracts domain-neutral and import-light.
- Preserve `run_uri` as the public run identity.
- Keep service backend optional until explicitly selected, but make
  authority-backed mutation mandatory.
- Do not add heavyweight runtime dependencies without a design gate.
- Default tests must remain local and deterministic; service backend tests
  should use fake or local-process adapters unless a later phase adds opt-in
  integration tests.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Add a v9-post authority-unification step before v10 bundles; deprecate `LocalRunStore` as runtime entrypoint; keep local materialization helpers. | Authority-backed mutation is mandatory; embedded SQLite is transitional; service/database authority is the target for declared multi-host guarantees. | None blocking. | Implementation-plan drafting. |
| Intent discovery | User wants every run/stage entrypoint authority-backed and future feature sets available through any entrypoint. | Treat local-only mutation as a bug to close. | None blocking. | Implementation-plan drafting. |
| Feature brainstorming | Inventory direct runtime uses; split active authority from local artifact/materialization access; add generic authority interfaces, conformance harness, and concrete service/database backend; use clearer `RunStore`/`StageStore` vocabulary. | Expand beyond three phases to keep reviews small. | Exact number of implementation phases. | Refine phase sketch. |
| Functionality and behavior confirmation | Local-only mutation should be completely deprecated; direct `PipelineRunner(LocalRunStore)` hard-fails for mutation; no old local lifecycle read compatibility; local run/stage directory access is artifact/materialization-only; SQLite authority is removed after the concrete backend exists. | `RunStore` manages runs and run-level leases; `StageStore` is scoped within a run and manages stage lifecycle/leases; artifact interfaces cannot access lifecycle behavior. | Exact public class/module names can be finalized in implementation planning. | Refine phase sketch. |
| Context compaction/reset checkpoint | Checkpoint text records selected functionality, defaults, deferrals, notes path, and resume instruction. | Do not reopen functionality after reset unless the user asks. | Formal context reset/compaction did not happen because remaining decisions were resolved directly. | Implementation-plan drafting. |
| Design decision review | Confirmed active authority, hard-fail local mutation, no local lifecycle compatibility, artifact-only local interfaces, `RunStore`/`StageStore` authority convention, generic conformance harness before concrete backend, concrete backend implementation, and SQLite removal. | Use repo-supported defaults where exact import names remain implementation-plan details. | Public factory exact spelling can be finalized during implementation-plan drafting. | Refine phase sketch. |
| Phase shaping | Expand from the initial three-phase plan into smaller reviewable phases, with concrete backend implementation separate from system-wide backend adoption/refactor. | Split interface/conformance, artifact split, runtime migration, read-path cleanup, concrete backend, HPC deployment/fallback profiles, system integration, and SQLite removal. | Complete. | Implementation-plan quality gate. |
| Handoff | Planning notes were used as source material for `implementation-plan-v9-post.md`. | Do not start implementation from this workflow. | Complete; implementation plan refined for HPC deployment/fallback concerns. | Plan quality gate. |

## Brainstormed Capabilities

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Mandatory authority-backed runtime store | include | Future features need attempts, leases, fencing, commits, revisions, and recovery across all entrypoints. | Applies to Python API and CLI mutation. |
| `LocalRunStore` runtime deprecation | include | Prevents local-file state from remaining a second active truth path. | Keep internal materialization usage. |
| `LocalRunStore` rename or split | include | Current name implies local files can be the run store. | Use artifact/materialization-only interfaces such as `RunArtifactStore` and `StageArtifactStore`; no lifecycle methods. |
| Authority-backed SLURM submission | include | Current SLURM live paths write `SUBMITTED` local files directly. | Needs submitted-operation and stage-job fencing alignment. |
| Authority-backed stage/job continuation | include | Submitted or remote workers must not finalize through local-only status files. | Requires CLI path changes and authority fencing defaults. |
| Generic authority interface and conformance harness | include | Runtime migration and backend implementation need a backend-neutral contract first. | Must cover `RunStore`, scoped `StageStore`, leases, fencing, submissions, commits, snapshots, and recovery. |
| Concrete service/database authority backend | include | Multi-host and concurrent-controller guarantees require more than run-local SQLite files. | Define desired feature set first, then show how implementation satisfies it. |
| System-wide concrete backend adoption | include | Implementing the backend is separate from refactoring all runtime/read systems to select, configure, and validate it. | Dedicated phase should cover runner, CLI, workers, status/catalog/plan/diagnostics, config, tests, and examples. |
| Run-level authority naming | include | Users expect `RunStore` to manage runs and run-level leases. | Keep separate workspace/sweep coordination only where it is genuinely not run lifecycle. |
| Public `RunStore`/`StageStore` scoped handles | include | Users need an understandable model: `RunStore` manages runs; each run exposes a scoped `StageStore`. | Stage handles must not be physically independent stores if atomic run/stage transitions are needed. |
| SQLite authority removal | include | User wants hard deprecation and removal after concrete service/database backend exists. | Derived catalog SQLite sidecars are separate projection data. |
| Old local-only lifecycle compatibility | out of scope | Local files must not remain a behavior source. | Artifact/materialization-only local access remains useful. |
| Worker daemon or scheduler | out of scope | Authority is state correctness; scheduling belongs to future orchestration. | Service backend may be state service only. |

## Confirmed Functionality And Behavior

Included functionality:

- Authority-backed runtime mutation for all normal run/stage entrypoints.
- Explicit deprecation of `LocalRunStore` as a user-facing runtime store.
- Run lifecycle and stage lifecycle documentation tied to authority contracts.
- Cross-run coordination design for concurrent runs and future sweeps.
- Service/database backend design and capability matrix for multi-host use.
- A documented inventory of all current `LocalRunStore` runtime entrypoints and
  read/materialization uses.
- Naming and public interface decisions that separate workspace/run/stage
  authority from local materialization.
- A generic authority interface and conformance harness before the concrete
  service/database implementation.
- A concrete service/database implementation with documented feature support.

User-visible behavior:

- Mutating commands use authority by default.
- Local-only mutation attempts fail with a clear diagnostic or deprecation
  warning during the transition period defined by the implementation plan.
- `loom status`, catalog, and diagnostics use authority for run/stage behavior.
  Local directory interfaces expose artifacts, logs, generated files, and
  materialized payloads only.

Default behavior:

- Serial execution remains default, but it is authority-backed.
- Bounded parallel stage execution remains opt-in and capability-gated.
- Embedded SQLite authority remains transitional only until a revised
  service/database backend is configured and supported; it should be hard
  deprecated and removed after the service backend lands.

Failure behavior and diagnostics:

- Missing authority for a new mutating run is an error.
- Incompatible authority schema is a loud error.
- Stale run or stage transitions fail as stale transitions.
- Expired or mismatched stage leases/fencing tokens fail before output commit.
- Service-backend unavailability fails mutating operations unless the selected
  operation is explicitly read-only and a safe fallback exists.

Explicit deferrals:

- Full service deployment and authentication model.
- Historical local-only migration.
- Historical local-only lifecycle read compatibility.
- Scheduler/work queue.
- Remote artifact payload movement.

Out-of-scope behavior:

- Treating local materialization files as authoritative lifecycle state.
- Reading local materialization files as run/stage lifecycle behavior.
- Allowing worker finalization without authority fencing when a run is
  authority-backed.

Context compaction/reset checkpoint:

- Checkpoint status: prepared but not formally compacted/reset in the current
  session
- Notes path: `docs/implementation-plans/roadmap-v9-post-planning-notes.md`
- Resume instruction: Reload this planning notes file, the v9 implementation
  plan, and `.codex/prompts/roadmap-version-planning-notes-facilitate.md`,
  then continue from design decision review confirmation or phase-shaping
  confirmation. Do not reopen functionality unless the user explicitly asks.
- Functionality and behavior reopened after checkpoint: not applicable

## Design Decision Review Queue

| Decision | Why it matters | User feedback needed | Status |
| --- | --- | --- | --- |
| Public runtime store factory name and import path | This becomes the recommended Python API replacement for `LocalRunStore`. | Use an import-light factory that hides backend internals; exact spelling can be finalized in the implementation plan. | confirmed |
| Service backend scope | Determines whether v9-post ships the first real service/database backend or only the interface plus conformance harness. | User confirmed concrete backend. | confirmed |
| Legacy local-only mutation policy | Determines whether direct `PipelineRunner(LocalRunStore)` hard-fails immediately or emits a short deprecation warning first. | User confirmed hard-fail for mutating execution. | confirmed |
| Run versus workspace naming | Determines whether the root authority is understandable as the store that manages runs. | Use `RunStore` as the public authority that manages runs and run-level leases; keep workspace/sweep coordination separate only for non-run concerns. | confirmed |
| Run/stage store naming | Current `RunStore` name is overloaded; user suggested `RunStore` for runs and per-run `StageStore` for stages. | Use `RunStore` for run lifecycle/admission/leases and scoped `StageStore` inside a run for stage lifecycle/leases/commits. | confirmed |
| Artifact/materialization naming | Useful local file access needs a programmatic surface that cannot touch lifecycle behavior. | Use `RunArtifactStore` and `StageArtifactStore` direction for artifact/materialization-only access. | confirmed |
| SQLite authority deprecation | Embedded SQLite authority is already implemented but not the desired long-term multi-host backend. | Hard deprecate and remove SQLite authority once the concrete service/database backend lands. | confirmed |

## Design Decisions

| Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Debt and revisit trigger |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Active state authority | All mutating entrypoints use authority-backed stores. | User requested all runs and stages managed through the new interface. | Keeping direct local-file mutation as supported runtime path. | Avoids split-brain lifecycle semantics. | Simplifies future feature assumptions. | Enables service, parallel, sweep, retry, and recovery features across entrypoints. | Temporary read-only local compatibility remains until old-run strategy is finalized. |
| Artifact/materialization access | Keep local files as payload/log/config/provenance/worker materialization, not truth, and expose them through artifact-only interfaces. | User wants local directory access, but no local run/stage behavior access. | Removing local path helpers; preserving local lifecycle readers. | Artifacts and logs still need programmatic surfaces, but lifecycle behavior must remain authority-only. | Requires clearer naming and docs. | Service backends can still materialize local or remote refs. | Revisit if service backend introduces non-local materialization. |
| RunStore convention | Use `RunStore` as the public authority that manages runs, run admission/opening, run lifecycle, and run-level leases. | User asked whether `WorkspaceAuthorityStore` should simply be called `RunStore`. | Making workspace authority the main public runtime name. | Users expect a store that manages runs to be called `RunStore`; workspace/sweep coordination can stay separate for non-run concerns. | Reduces conceptual load. | Allows future workspace/sweep services without hiding run lifecycle behind workspace terminology. | Revisit only if non-run workspace coordination dominates the public API. |
| Scoped stage interface | Expose stage operations as `StageStore` scoped within a run authority, not as an independent authority database. | User confirmed `StageStore` should be within a run and manage stage lifecycle and leases. | Fully separate per-stage stores. | Stage attempts, output commits, downstream blocking, and run finalization need shared transaction/revision semantics. | Public API can be clearer without weakening consistency. | Future worker APIs can receive a stage handle or lease token without owning the whole run API. | Revisit if a real distributed scheduler needs coarser-grained worker tokens. |
| SQLite authority removal | Treat embedded SQLite authority as transitional, hard deprecate it, and remove it after the concrete service/database backend exists. | User explicitly wants removal after the concrete backend exists. | Keeping run-local SQLite as dev/test runtime authority indefinitely. | SQLite files are not a general multi-host control plane, especially on HPC/shared filesystems. | Reduces backend support matrix once service backend is stable. | Service-backed consistency becomes the common path for local, HPC, and multi-host entrypoints. | Derived catalog SQLite sidecars remain projection data; authority SQLite removal happens after service backend parity. |
| Local-only mutation hard-fail | Direct `PipelineRunner(LocalRunStore)` and equivalent mutating paths fail instead of warning. | User confirmed yes. | Warning-only deprecation period. | Warnings would preserve a second active truth path and weaken future feature assumptions. | Simplifies migration target and tests. | Ensures every future entrypoint can rely on attempts, leases, fencing, commits, and snapshots. | Local artifact/directory access remains available without lifecycle behavior. |
| Generic interface before concrete backend | Define generic authority interfaces and conformance harness before implementing the concrete service/database backend. | User requested both the generic interface/harness and the concrete implementation. | Jumping straight to one backend implementation. | The harness lets the implementation prove the feature set instead of encoding behavior accidentally in one backend. | Adds one phase but improves contract clarity. | Makes later backend swaps or service deployments more realistic. | Concrete backend still lands in v9-post, so this is not an indefinite abstraction phase. |
| Service backend phase scope | A later phase implements a concrete service/database backend after the generic interface and harness are defined. | User confirmed concrete backend. | Interface-only or conformance-harness-only version. | Multi-host and HPC design need a real consistency target before later features depend on it. | Higher implementation cost, but avoids another abstract planning version. | Establishes a usable runtime backend for concurrent terminals, workers, and future sweeps. | Hosted operations/auth/tenancy remain deferred unless explicitly selected. |
| Backend implementation versus adoption | Keep concrete backend implementation separate from the system-wide refactor to use and support that backend. | User explicitly requested this separation. | Combining backend implementation with all caller migration and default selection. | The backend should first prove its contract in isolation; adoption then reviews configuration, entrypoints, diagnostics, and operational behavior separately. | Reduces PR size and makes regressions easier to localize. | Allows later backends to follow the same implement-then-adopt pattern. | Temporary dual-backend support exists until adoption and SQLite removal complete. |
| Public naming defaults | Use authority-backed `RunStore`, scoped `StageStore`, and local `RunArtifactStore`/`StageArtifactStore` direction for non-lifecycle materialization. | User accepted and refined defaults. | Keeping `LocalRunStore` as runtime name; using independent per-stage stores; preserving local lifecycle readers. | Names align with ownership and reduce accidental local-only runtime use. | Improves API readability but requires coordinated test/doc updates. | Leaves room for service-backed handles and local/remote materialization. | Exact import paths and aliases can be refined in the implementation plan. |

## Practical Design Notes

Public Python API surface:

- Replace examples of `PipelineRunner(run_store=LocalRunStore(...))` with an
  authority-backed factory.
- Prefer a stable import-light factory in `loom.pipeline.stores`, such as
  `create_run_store(...)`, that returns authority-backed run handles without
  exposing backend implementation classes.
- Keep direct `LocalRunStore` usage documented only for read/materialization
  compatibility or internal adapter construction.
- Prefer constructors that select a backend by capability and configuration,
  not by naming a storage implementation. For example, a public factory should
  let users ask for local development, service-backed, or remote-capable
  authority without importing `SQLitePerRunAuthorityStore`.

Target naming model:

- `RunStore`: public authority surface that manages runs. It owns run
  admission/allocation/opening, run-level leases, run lifecycle transitions,
  submitted-operation records, run snapshots, run recovery, and access to each
  run's scoped stage authority.
- `StageStore`: scoped authority surface within one run. It owns stage
  lifecycle, stage attempts, stage leases, fencing-token checks, submitted
  stage state, failure/cancellation, output commit, stage recovery, and
  cleanup candidate facts. A `StageStore` shares the same backend
  transaction/revision boundary as its parent `RunStore`.
- `WorkspaceStore` or a retained `WorkspaceCoordinationStore`: optional
  non-runtime-lifecycle surface for workspace/sweep/resource coordination that
  is not naturally part of run lifecycle. It should not be the public name for
  the store that manages runs.
- `RunArtifactStore`: programmatic per-run artifact/materialization interface
  for local or remote payloads, generated manifests, config snapshots,
  provenance documents, logs, and other non-lifecycle files.
- `StageArtifactStore`: programmatic per-stage artifact/materialization
  interface for stage payloads, logs, worker request/result materialization,
  generated files, and local directories.
- `RunArtifactStore` and `StageArtifactStore` must not expose read or write
  methods for run status, stage status, attempts, leases, submitted
  operations, output commits, recovery records, lifecycle snapshots, or any
  behavior-derived status.
- Avoid using `RunStore` for both active authority and local files. Reserve
  `RunStore` for authority-backed run management.

RunStore and StageStore behavior conventions:

- `RunStore` is the only public surface that creates, opens, admits, lists, or
  leases runs.
- `RunStore` exposes or creates a scoped `StageStore` for a given run and stage
  rather than letting callers construct an independent stage authority.
- `StageStore` operations are scoped by a parent run identity and backend
  revision context. They may be passed to workers with lease/fencing material,
  but they cannot outlive or bypass the parent run authority.
- Cross-run coordination that is not run lifecycle, such as sweep trial claims
  or global resource counters, may live in a separate workspace/coordination
  surface. The implementation may use one physical database for both, but the
  public lifecycle model remains `RunStore` -> `StageStore`.

Public consistency interface requirements:

- Run creation/admission must be performed through `RunStore` or a
  service-backed factory that records a unique `run_uri` and initial revision.
- Every mutating run transition must carry an expected prior status or
  revision, and return the resulting backend revision.
- Every controller or worker mutation must carry an owner id and lease/fencing
  token when the operation can race with another controller or worker.
- Stage attempt allocation, stage status transition, submitted-operation write,
  and output commit must be transactional or compare-and-set guarded.
- Output commit must atomically record the attempt, fencing token, artifact
  refs/facts, cleanup candidates, and terminal stage success.
- Submitted-operation updates need idempotency keys or submission ids so
  submit/retry/status/cancel operations can be replayed safely.
- Snapshots must be revisioned and explicit about stale/expired leases,
  abandoned attempts, active submitted operations, and cleanup candidates.
- Backend capability declarations must say whether the backend supports
  single-host only, multi-host, shared filesystem safety, remote service use,
  transaction isolation, monotonic revisions, lease TTLs, and clock semantics.
- Local materialization writes must not imply lifecycle success. A worker can
  write files first, but success is not visible until authority accepts the
  fenced output commit.

CLI surface:

- `loom run`, SLURM live submission, `loom stage run`, `loom stage-job run`,
  and `loom prepared-run continue` should open the same configured authority
  backend.
- Add diagnostics for local artifact directories, unsupported local lifecycle
  reads, and authority backend selection.
- Avoid exposing SQLite paths or SQL details.

Persisted records and file layout:

- Per-run authority remains the owner of run status, stage status, attempts,
  leases, submitted operations, output commits, artifact facts, revisions, and
  snapshots.
- Workspace authority owns workspace identity, run allocation/admission,
  sweep/trial refs, trial/resource leases, global counters, and cross-run
  recovery scans.
- Local files remain materialized config snapshots, provenance docs, logs,
  worker handoff files, artifact payloads, and optional projections.

Service/database backend design notes:

- The service/database authority can physically store workspace and per-run
  records in one database while exposing separate workspace, run, and stage
  scopes in the public API.
- The database needs unique run identity, monotonic revisions, compare-and-set
  transitions, lease rows with fencing tokens, submitted-operation idempotency,
  transactional output commits, and recovery scans.
- A service process is useful when workers or HPC compute nodes should not
  hold direct database credentials. A direct database adapter may be acceptable
  in trusted single-host development, but it should declare a weaker capability
  set unless multi-host safety is proven.
- HPC jobs need the run URI, backend endpoint or database/service reference,
  attempt id, owner id, and fencing token in the job environment or worker
  request. If compute nodes cannot reach the authority service, the job must
  fail safe or leave recoverable materialization, not mark success locally.
- Shared filesystems should be treated as payload/materialization transport,
  not as the authority mechanism. SQLite on NFS or parallel filesystems should
  not be advertised as multi-host safe.
- Lease TTLs must account for scheduler queue delays and long-running jobs.
  Long jobs need renewal support or a scheduler-aware lease strategy; expired
  leases should produce recovery records and reject stale commits.
- Network partitions and service unavailability should fail closed for
  mutation. Read-only diagnostics may show the last known authoritative
  snapshot if the backend supports that safely.

Import boundaries and dependencies:

- Store contracts stay under `loom.pipeline.stores`.
- Execution orchestration stays under `loom.pipeline.execution`.
- CLI stays presentation-only over public APIs.
- A service backend must be optional and capability-declared.

Failure modes and diagnostics:

- Missing authority for new mutation.
- Unsupported backend capability for requested parallel, service, shared,
  remote, or cross-run behavior.
- Stale transition, expired lease, missing lease, foreign fencing token,
  duplicate output commit, and incompatible schema.
- Legacy local-only run detected during read-only inspection.

Extension points and flexibility boundaries:

- Service backend may implement both workspace and per-run logical contracts.
- Embedded SQLite can remain transitional local/same-host machinery until the
  service/database backend replaces it as the recommended runtime backend.
- Remote/service adapters must not make external trackers authoritative.

Maintainability assessment:

- Removing local-only mutation reduces duplicated lifecycle reasoning and
  makes future phases easier to review.
- Short-term churn is expected in tests, examples, and CLI helper construction.

Extensibility assessment:

- Mandatory authority unlocks future retries, cleanup, sweep concurrency,
  service state, and multi-host diagnostics without retrofitting each
  entrypoint again.

Flexibility and expansion assessment:

- Backend-neutral contracts keep the physical backend flexible: embedded
  SQLite, local service process, network service, or transactional database can
  satisfy the same logical calls.

Scalability and future compatibility:

- Same-run concurrent stages use leases and fenced output commits.
- Multiple concurrent runs use workspace-level run references and optional
  counters/resource leases.
- Multi-host safety requires a backend that declares and proves service-grade
  consistency rather than relying on local file locking assumptions.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Historical local-only lifecycle behavior is not preserved. | Preserving local lifecycle reads would keep a second behavior source. | Users require a migration tool for old local-only runs. |
| Embedded SQLite remains temporarily available. | It already exists and can help bridge from v9 contracts to service authority. | Multi-host service backend is selected as default, then deprecate SQLite authority. |
| Service backend deployment details are not yet designed. | Product contract and lifecycle migration should come first. | Implementation plan selects a real service/database backend. |

## Phase Sketch (Planning Baseline)

This sketch records the planning baseline used for the first implementation
plan draft. The implementation plan was later refined to insert a dedicated
HPC deployment and fallback phase after Phase 7. The current controlling phase
sequence is in `implementation-plan-v9-post.md`.

### Phase 1 - Exhaustive Inventory And Lifecycle Contracts

Goal:

- Establish the complete migration map and strict lifecycle contract before
  changing behavior.

Scope:

- Run an exhaustive `LocalRunStore` and `LocalRunStorePaths` inventory across
  source, tests, examples, feature docs, and implementation docs.
- Classify every hit as runtime mutation, authority read, artifact/materialized
  file access, test helper, docs/example, or historical artifact.
- Document run lifecycle, stage lifecycle, submitted-operation lifecycle, and
  failure-closed behavior as authority contracts.
- Define that local files cannot be used for run/stage behavior reads.

Out of scope:

- Implementing new store interfaces.
- Moving runtime entrypoints.
- Implementing service/database authority.

Acceptance criteria:

- The implementation plan contains a line-item migration map for every current
  local-store runtime and behavior-read path.
- Lifecycle contracts identify required guarded transitions, leases, fencing,
  revisions, snapshots, output commits, submitted-operation updates, and
  recovery scans.
- Local directory access is explicitly artifact/materialization-only.

Test expectations:

- Package: none beyond import-boundary review.
- Unit: not required unless contract constants or diagnostics are introduced.
- Contract: not required.
- Integration: not required.
- E2E: not required.
- Opt-in: not required.

Design impact:

- High. The phase prevents undercounting local-store escape hatches.

Future compatibility:

- The inventory becomes the source of truth for later phase scoping and review.

Alternatives rejected:

- Relying on ad hoc migration while editing callers.

Debt introduced:

- None intended.

Reviewability:

- Review focuses on inventory completeness and lifecycle precision.

### Phase 2 - Generic RunStore/StageStore Interfaces And Conformance Harness

Goal:

- Define the generic authority contract and prove it with backend-neutral
  conformance tests before selecting implementation details.

Scope:

- Introduce or rename public authority interfaces around `RunStore` and
  scoped `StageStore`.
- Define the factory/config surface, likely `loom.pipeline.stores.create_run_store(...)`.
- Define capability declarations for single-host, multi-host, service-backed,
  shared-filesystem-safe, lease TTL, monotonic revision, transaction isolation,
  and recovery behavior.
- Build a conformance harness for run lifecycle, stage lifecycle, leases,
  fencing, submitted operations, output commits, snapshots, and recovery.

Out of scope:

- Migrating all runtime entrypoints.
- Implementing the concrete service/database backend.
- Removing SQLite authority.

Acceptance criteria:

- `RunStore` manages run admission/opening, run lifecycle, run-level leases,
  and access to scoped stage stores.
- `StageStore` is scoped within a run and manages stage lifecycle, attempts,
  leases, submissions, commits, and recovery facts.
- The conformance harness can be run against any backend implementation.

Test expectations:

- Package: public exports and import boundaries for the authority interfaces
  and factory.
- Unit: interface validation and capability diagnostics.
- Contract: full authority conformance harness.
- Integration: minimal factory smoke test if implemented.
- E2E: not required.
- Opt-in: not required.

Design impact:

- Very high. This phase defines the API all runtime paths and backends depend
  on.

Future compatibility:

- Enables future service, remote, retry, sweep, and HPC behavior without
  rewriting the runtime store API.

Alternatives rejected:

- Encoding the authority contract only in a concrete backend.
- Making `StageStore` independent from the parent run transaction boundary.

Debt introduced:

- Compatibility adapters may exist until migration phases remove legacy usage.

Reviewability:

- Review focuses on public naming, interface scope, and conformance coverage.

### Phase 3 - RunArtifactStore And StageArtifactStore Split

Goal:

- Preserve useful local and future remote file access without allowing local
  files to masquerade as lifecycle state.

Scope:

- Rename or split useful local filesystem machinery into `RunArtifactStore`
  and `StageArtifactStore` direction, or equivalent artifact/materialization
  names selected by implementation planning.
- Move config snapshots, provenance docs, logs, generated manifests, worker
  handoff files, local directories, and payload refs behind these interfaces.
- Remove or block local lifecycle reads and writes from the artifact surfaces.
- Update tests that currently treat `LocalRunStore` as the local file layout
  primitive.

Out of scope:

- Runtime entrypoint migration.
- Service/database implementation.
- Artifact payload remote-store operations beyond the interface boundaries.

Acceptance criteria:

- Artifact/materialization interfaces do not expose status, attempts, leases,
  submitted operations, output commits, snapshots, recovery, or behavior
  summaries.
- Existing local file needs are covered without importing lifecycle authority
  through local files.
- `LocalRunStore` is no longer documented as a local lifecycle reader.

Test expectations:

- Package: import-boundary tests for artifact interfaces.
- Unit: path safety, read/write helpers for artifacts/logs/config/provenance,
  and absence of lifecycle methods.
- Contract: artifact/materialization contract tests.
- Integration: local materialization round trips.
- E2E: not required.
- Opt-in: not required.

Design impact:

- High. This phase separates useful local files from lifecycle authority.

Future compatibility:

- Keeps room for remote artifact materialization without weakening authority
  semantics.

Alternatives rejected:

- Keeping `LocalRunStore` as the catch-all local interface.
- Preserving old local status readers as compatibility.

Debt introduced:

- Temporary aliases may be needed while callers migrate.

Reviewability:

- Review focuses on local interface capability and absence of lifecycle access.

### Phase 4 - Python Runner And Public Example Migration

Goal:

- Make direct Python runtime execution authority-only.

Scope:

- Make mutating `PipelineRunner` usage reject local-only runtime stores.
- Replace direct Python examples and docs that teach
  `PipelineRunner(run_store=LocalRunStore(...))`.
- Update package/API tests and runtime tests that normalize local-only runner
  construction.
- Add clear diagnostics for local-only mutating attempts.

Out of scope:

- CLI worker and SLURM migration.
- Concrete service/database backend.
- Historical local-run migration.

Acceptance criteria:

- Direct mutating `PipelineRunner(LocalRunStore)` hard-fails.
- Public examples use the authority-backed factory.
- Tests distinguish runtime authority from artifact/materialization helpers.

Test expectations:

- Package: public API examples/import tests.
- Unit: runner rejection and factory behavior.
- Contract: authority-backed runner behavior through existing conformance fake
  or adapter.
- Integration: local/subprocess execution and resume through authority-backed
  stores.
- E2E: Python example execution if covered by existing docs tests.
- Opt-in: not required.

Design impact:

- High. This phase changes the primary Python extension surface.

Future compatibility:

- Future users can rely on authority-backed attempts, leases, commits, and
  snapshots through Python APIs.

Alternatives rejected:

- Warning-only deprecation.

Debt introduced:

- None intended beyond temporary compatibility aliases from Phase 3.

Reviewability:

- Review focuses on public API behavior and direct local-store rejection.

### Phase 5 - CLI, Worker, Submitted Job, And SLURM Migration

Goal:

- Close operational runtime mutation escape hatches.

Scope:

- Move `loom run`, SLURM dry-run/live submission, `loom stage run`,
  `loom stage-job run`, and `loom prepared-run continue` to authority-backed
  `RunStore`/`StageStore` construction.
- Move SLURM cancellation and scheduler-status mutation to authority-backed
  submitted-operation updates and guarded run/stage transitions.
- Ensure workers and submitted jobs carry run URI, attempt id, owner id,
  lease/fencing material, and backend configuration needed for safe finalize.
- Ensure local manifests/scripts/logs remain artifact/materialization only.

Out of scope:

- Concrete service/database backend.
- New scheduler, worker daemon, queue, retry, or timeout policy.
- Real SLURM acceptance changes beyond existing opt-in coverage.

Acceptance criteria:

- No supported CLI/worker/submitted mutating entrypoint constructs
  `LocalRunStore` as runtime authority.
- Submitted operations are idempotent and authority-recorded.
- Worker finalization cannot succeed without active authority and correct
  fencing.

Test expectations:

- Package: CLI imports remain presentation-only.
- Unit: CLI helper construction, worker requests, submitted-operation updates,
  cancellation/status transitions, and failure diagnostics.
- Contract: submitted-operation and stage commit behavior in authority
  harness.
- Integration: SLURM dry-run/live with fakes, worker continuation, stage-job
  continuation, prepared-run continuation, cancellation/status paths.
- E2E: CLI run, CLI stage/job continuation where deterministic, and CLI SLURM
  dry-run.
- Opt-in: real SLURM acceptance remains opt-in.

Design impact:

- Very high. This phase changes the operational execution paths most likely to
  run on HPC or in separate terminals.

Future compatibility:

- Future HPC/container/remote workers inherit authority-fenced finalization.

Alternatives rejected:

- Migrating only `loom run` while leaving worker or submitted paths local-only.

Debt introduced:

- Service backend still follows in a later phase, so authority may temporarily
  use transitional backend implementations.

Reviewability:

- Review should be split by entrypoint family with concrete validation for
  each migrated command path.

### Phase 6 - Authority Read Models For Status, Catalog, Plan, And Diagnostics

Goal:

- Ensure user-visible read paths do not infer lifecycle behavior from local
  files.

Scope:

- Route status, catalog, plan-resume reads, diagnostics, preflight, and
  extraction behavior through authority read models where lifecycle behavior is
  involved.
- Allow local artifact/materialization interfaces to expose files, logs,
  payloads, and generated artifacts only.
- Remove or loudly reject old local-only lifecycle read compatibility.

Out of scope:

- Bundle/export behavior that belongs to v10.
- Historical migration into authority.

Acceptance criteria:

- `loom status`, catalog summaries, plan resume decisions, and diagnostics use
  authority for run/stage behavior.
- Local run/stage directories are exposed only as artifacts/materialization.
- Old local-only lifecycle reads are not preserved as a supported behavior.

Test expectations:

- Package: run-catalog/status APIs avoid local lifecycle imports.
- Unit: read-model selection, local-file rejection for behavior, diagnostics.
- Contract: authority snapshot/read-model coverage.
- Integration: status, catalog, plan, diagnostics, and preflight over
  authority-backed runs.
- E2E: CLI status/logs/runs commands where applicable.
- Opt-in: not required.

Design impact:

- High. This phase prevents local lifecycle compatibility from reentering
  through read paths.

Future compatibility:

- Bundles, sweeps, dashboards, and reliability features can depend on
  authority-backed facts.

Alternatives rejected:

- Keeping local status files as a fallback behavior source.

Debt introduced:

- Users with old local-only runs may need external/manual migration if they
  need lifecycle behavior.

Reviewability:

- Review focuses on read-path behavior and strict local artifact-only access.

### Phase 7 - Concrete Service/Database Backend

Goal:

- Implement the real backend needed for concurrent terminals, multi-host
  workers, and HPC submitted jobs, while keeping system-wide adoption for a
  separate phase.

Scope:

- Select and implement the first concrete service/database backend behind the
  generic `RunStore`/`StageStore` contracts.
- Document the feature set it supports: multi-host consistency, transaction
  isolation, revisions, leases/fencing, idempotency, snapshots, recovery,
  stale transition handling, service unavailability, and clock/TTL semantics.
- Add local service/database configuration and diagnostics.
- Prove the backend against the conformance harness.
- Define HPC usage: endpoint/config propagation, worker tokens, lease renewal,
  failure-closed mutation, and recovery scans.

Out of scope:

- Hosted production operations, authentication, authorization, and tenancy
  unless explicitly selected in the implementation plan.
- A distributed scheduler or work queue.
- Remote artifact payload movement.
- Refactoring every runtime/read system to default to or fully exercise the
  new backend.
- Removing SQLite authority.

Acceptance criteria:

- The concrete backend passes the generic conformance harness.
- Backend diagnostics declare the consistency guarantees it proves.
- Multi-process or service-backed integration tests demonstrate concurrent
  run/stage behavior with deterministic synthetic stages.
- HPC and multi-host workflows have explicit backend requirements and failure
  modes.
- The backend is selectable in targeted tests without becoming the default
  runtime authority.

Test expectations:

- Package: optional backend modules do not add heavyweight imports to core
  packages.
- Unit: backend config, capability diagnostics, stale transitions, lease
  failure, idempotency, unavailable service.
- Contract: full conformance harness.
- Integration: local service/database adapter with concurrent controllers and
  workers.
- E2E: CLI configured against the service/database backend if practical.
- Opt-in: real HPC or multi-host tests only.

Design impact:

- Very high. This phase defines Loom's durable consistency story.

Future compatibility:

- Supports later sweeps, retry/recovery, remote workers, containers, and HPC
  execution without another authority rewrite.

Alternatives rejected:

- Treating SQLite on shared filesystems as multi-host authority.
- Letting HPC jobs finalize locally when authority is unreachable.

Debt introduced:

- Hosted operations and tenancy remain deferred unless explicitly brought into
  scope.

Reviewability:

- Review focuses on backend correctness, consistency claims, failure-closed
  behavior, dependency footprint, and conformance evidence, not on all caller
  migrations.

### Phase 8 - System-Wide Service Backend Adoption

Goal:

- Refactor Loom's runtime and read systems to use, configure, diagnose, and
  support the concrete service/database backend.

Scope:

- Route runner construction, public factories, CLI commands, workers,
  submitted-job continuations, SLURM planning/submission/cancel/status,
  status/catalog/plan/diagnostics/preflight, examples, and tests through the
  concrete backend where service-backed authority is selected.
- Add backend configuration resolution for terminals, subprocess workers,
  stage jobs, and HPC jobs, including endpoint propagation and safe diagnostic
  redaction.
- Prove that every supported mutating entrypoint can run against the concrete
  backend.
- Update docs and examples to show backend selection and service-backed
  execution without exposing internal backend classes.
- Keep SQLite authority available only as transitional support until the final
  removal phase.

Out of scope:

- Implementing the concrete backend itself.
- Removing SQLite authority.
- Hosted production operations, authentication, authorization, and tenancy
  unless explicitly selected in the implementation plan.

Acceptance criteria:

- All runtime and behavior-read systems support the concrete backend through
  the public factory/configuration path.
- Worker and HPC handoff records carry the information needed to reconnect to
  the concrete authority backend without local lifecycle fallback.
- Status, catalog, plan, diagnostics, and preflight behave correctly against
  service-backed runs.
- Tests and examples cover service-backed execution and read paths.

Test expectations:

- Package: public factory and import-boundary tests for service-backed
  selection.
- Unit: configuration resolution, endpoint propagation, CLI construction,
  worker handoff, diagnostics, and redaction.
- Contract: existing conformance harness continues to cover backend behavior.
- Integration: runner, subprocess, worker, stage-job, SLURM fake flows,
  status/catalog/plan/diagnostics/preflight against the concrete backend.
- E2E: CLI run and representative worker/submitted flows against the concrete
  backend where practical.
- Opt-in: real HPC or multi-host tests only.

Design impact:

- Very high. This phase makes the concrete backend operational across Loom
  without mixing that adoption work into backend implementation.

Future compatibility:

- Later backends can follow the same implementation phase plus adoption phase
  pattern.

Alternatives rejected:

- Combining backend implementation and all system refactors in one oversized
  phase.
- Switching defaults before every runtime/read system supports the concrete
  backend.

Debt introduced:

- SQLite authority remains temporarily available until the final removal phase.

Reviewability:

- Review focuses on call-site coverage, configuration propagation, operational
  diagnostics, and service-backed behavior across systems.

### Phase 9 - Service Default And SQLite Authority Removal

Goal:

- Complete the transition by making the service/database backend the runtime
  authority path and removing run-local SQLite authority from supported runtime
  behavior.

Scope:

- Switch default runtime authority selection away from run-local SQLite.
- Hard deprecate and remove SQLite authority runtime use after service/backend
  parity is established.
- Keep derived SQLite catalog sidecars only as rebuildable projection data
  where still applicable.
- Update docs, diagnostics, tests, examples, and feature docs to reflect the
  final backend matrix.

Out of scope:

- Removing all SQLite usage from derived non-authoritative projections if those
  projections remain useful.
- Historical migration of old local-only runs.

Acceptance criteria:

- New runtime authority no longer uses `SQLitePerRunAuthorityStore`.
- Attempts to configure removed SQLite runtime authority fail with clear
  diagnostics.
- Docs and examples present the service/database backend as the supported
  runtime authority.

Test expectations:

- Package: imports no longer expose SQLite authority as public runtime API.
- Unit: backend selection, deprecation/removal diagnostics.
- Contract: conformance harness excludes removed SQLite authority from runtime
  backend matrix.
- Integration: default runtime path uses service/database authority.
- E2E: CLI default run through service/database authority where practical.
- Opt-in: not required unless backend operations need external services.

Design impact:

- High. This phase removes the transitional backend and simplifies future
  runtime assumptions.

Future compatibility:

- Future phases can assume service/database-backed lifecycle state.

Alternatives rejected:

- Keeping SQLite authority as a permanent dev/test runtime backend.

Debt introduced:

- None intended; any retained derived SQLite projections must be documented as
  non-authoritative.

Reviewability:

- Review focuses on removal completeness and avoiding accidental deletion of
  non-authoritative catalog projections.

## Open Questions

Post-draft implementation-plan refinement:

- The implementation plan inserts a dedicated HPC deployment and fallback
  phase after concrete backend implementation. This supersedes the original
  nine-phase sketch with a ten-phase plan.
- New Phase 8 defines managed service, allocation-scoped service, direct
  transactional database, co-located single-process, and deferred finalization
  capability profiles.
- Deferred finalization is explicitly weaker than live worker authority:
  offline workers may write sealed result envelopes and materialized outputs,
  but only an authority-backed controller or reconciler can make lifecycle
  success visible.
- Strict capability gates are now part of the plan. Unsupported concurrent
  stages, concurrent run admission, live multi-host workers, submitted-job
  commits, sweeps, and shared resource coordination fail before worker launch
  or scheduler submission.
- The implementation plan now records whole-plan implementation details for
  factory/config construction, capability admission, service record shape,
  transaction boundaries, worker handoff, deferred envelopes, and deterministic
  topology fixtures.
- A later implementation-detail pass added candidate module ownership, draft
  CLI/environment authority options, service constraints, concrete admission
  examples, failure diagnostic codes, and phase review checkpoints.
- Original Phase 8, system-wide service backend adoption, becomes Phase 9.
- Original Phase 9, service default and SQLite authority removal, becomes
  Phase 10.

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Should v9-post implement the first real service/database backend, or prepare an implementation-ready service adapter plus conformance harness? | Phase scope and dependencies. | Define generic interfaces and conformance harness first, then implement a concrete backend in the same version. | confirmed |
| What should the public authority-backed runtime factory be named? | Python API and examples. | Prefer `loom.pipeline.stores.create_run_store(...)`; exact spelling can be finalized in the implementation plan. | confirmed |
| Should direct `PipelineRunner(LocalRunStore)` hard-fail immediately? | Compatibility and tests. | Hard-fail for new mutating runtime paths; no local lifecycle read compatibility remains. | confirmed |
| Should useful `LocalRunStore` machinery be renamed or split into run-level and stage-level artifact/materialization interfaces? | Naming, imports, and tests. | Use artifact/materialization-only `RunArtifactStore` and `StageArtifactStore` direction; no lifecycle methods. | confirmed |
| Should `RunStore` be reserved for an authority-backed run handle, with `StageStore` as a scoped handle under it? | Public API semantics and transaction boundaries. | Use authority-backed `RunStore` for run management and scoped `StageStore` within each run for stage lifecycle. | confirmed |
| Should `WorkspaceCoordinationStore` be renamed to `WorkspaceAuthorityStore`? | API semantics and migration cost. | Prefer public `RunStore` for run management; keep workspace/coordination naming only for non-run sweep/resource concerns. | confirmed |
| Should embedded SQLite authority be kept as dev/test-only after the service backend lands, or removed from public runtime documentation entirely? | Backend support matrix. | Hard deprecate and remove SQLite authority runtime behavior once service/database authority is available. | confirmed |
| Is the phase count larger than three? | Reviewability and phase scope. | Use the ten-phase plan unless formal implementation-plan review finds a safer split. | confirmed |
| Should concrete backend implementation, HPC deployment/fallback support, and system-wide backend adoption be separate phases? | Reviewability, test scope, and regression isolation. | Yes. Phase 7 implements/proves the backend; Phase 8 defines and tests deployment/fallback capability profiles; Phase 9 refactors systems to use/support it; Phase 10 changes defaults and removes SQLite authority. | confirmed |
