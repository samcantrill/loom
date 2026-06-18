# Roadmap v9 Planning Notes: Persistence And Concurrency Foundation

## Metadata

- Roadmap version: v9
- Source roadmap:
  `docs/roadmap.md`
- Previous version status: complete for planning. `docs/roadmap/stage-8/implementation-plan.md`
  records v8 as implemented with all phases merged, providing the public
  `loom.runs.RunCatalog` facade, current local collection listing,
  rebuildable SQLite sidecar catalog, metadata-only comparison, warning result
  models, and `loom runs index/list/diff` CLI commands.
- Planning notes status: implementation-plan draft created and post-review
  refined
- Current discussion stage: Implementation-plan post-review refinement complete
- Stage gates:
  - Roadmap framing: complete
  - Intent discovery: complete
  - Feature brainstorming: complete
  - Functionality and behavior confirmation: complete
  - Context compaction/reset checkpoint: complete; resumed from checkpoint
  - Design decision review: complete
  - Phase shaping: complete
  - Handoff: complete; implementation-plan draft created and post-review
    refined
- Related implementation plans:
  - `docs/roadmap/stage-8/implementation-plan.md`
  - `docs/roadmap/stage-9/implementation-plan.md` (post-review
    refined draft created)
- Related feature docs:
  - `docs/features/run-store.md`
  - `docs/features/state.md`
  - `docs/features/execution.md`
  - `docs/features/reliability.md`
  - `docs/features/run-catalog.md`
  - `docs/features/sweeps.md`
  - `docs/features/remote-stores.md`
  - `docs/features/artifacts.md`
  - `docs/features/runtime-resources.md`
  - `docs/features/slurm.md`
  - `docs/features/testing.md`
  - `docs/loom.md`
  - `docs/structure.md`
- Blockers:
  - None for planning.
  - Implementation must not begin until the persistence, lifecycle,
    concurrency, backend capability, and compatibility contracts have passed a
    dedicated plan quality gate.

## Roadmap Extraction

Baseline roadmap outcome:

- V9 establishes Loom's authoritative persistence and concurrency foundation:
  run/sweep store capability contracts, stage attempts, leases, output commit
  semantics, active-query freshness rules, and backend capability limits for
  future concurrent execution.

Prerequisites:

- V8 is complete for planning and has merged all phases. It provides
  `loom.runs.RunCatalog`, local run collection scanning, a rebuildable derived
  SQLite sidecar, metadata-only comparison, catalog warnings, and `loom runs`
  CLI commands.
- Current run execution remains primarily serial and run-lock based. Current
  local run-store files, freshness tokens, stage status records, worker
  handoff records, and run-catalog refresh behavior are the concrete substrate
  V9 must evaluate.

Primary feature docs:

- `docs/features/run-store.md`
- `docs/features/state.md`
- `docs/features/execution.md`
- `docs/features/reliability.md`
- `docs/features/run-catalog.md`
- `docs/features/sweeps.md`
- `docs/features/remote-stores.md`
- `docs/features/artifacts.md`
- `docs/features/runtime-resources.md`
- `docs/features/slurm.md`
- `docs/features/testing.md`

Deferred or out-of-scope roadmap work:

- Full distributed workflow-engine behavior, hosted tracking services, remote
  catalog services, dynamic DAG mutation, adaptive sweep algorithms, concrete
  cloud backends, service-specific telemetry sinks, domain-specific metric
  stores, and broad parallel execution policy unless the V9 design proves a
  concrete coordination backend belongs in this version.
- V10 owns run bundles and exporters. V11 owns deterministic sweep user
  workflows. V13 and V14 own remote-store contract and operations.

Compatibility posture:

- Keep `run_uri` as canonical public identity.
- Replace the old local-run-file state model for active runs rather than
  preserving it as a compatibility mode.
- No migration path for old v0-v8 local run directories is required in V9.
- Existing human-readable run-state files such as `status.json` and
  `artifacts.json` should not remain live truth or fallback truth.
- `RunCatalog`, status, resume, execution, and diagnostics should obtain live
  truth from the new authoritative backend where relevant.
- Any catalog or query projection remains derived from the authoritative
  backend, not from old local state files.
- Keep default tests local, deterministic, synthetic, and filesystem-only.
- Keep optional backend work behind explicit capability contracts and avoid
  heavyweight runtime dependencies without a design reason.

## Version Briefing

What this version is:

- V9 is the planning and implementation step that turns Loom's current
  single-writer local run-state model into a reviewed, backend-neutral
  persistence contract that future concurrent DAG execution, sweeps, remote
  stores, and shared-filesystem workflows can depend on.

Why this version exists:

- The existing v0-v8 implementation is intentionally inspectable and local:
  a `PipelineRunner` holds a conservative run-level lock, writes stage files
  serially, updates a run-level artifact index with read/modify/write logic,
  and lets `RunCatalog` derive query rows from run-store freshness evidence.
  That is correct for current local workflows, but weak as the only foundation
  for multiple stage writers, distributed sweep controllers, remote stores, or
  shared filesystems with uncertain locking and visibility semantics. The
  confirmed V9 direction is to replace that active state model rather than
  preserve it as a compatibility layer.

Impacted or linked work:

- V9 directly impacts run-store protocols, local run-store behavior, state
  records, execution lifecycle helpers, run-catalog freshness guarantees,
  artifact commit/index semantics, reliability attempt records, SLURM worker
  handoffs, and future sweep coordination.
- V9 links forward to V10 bundles, V11 deterministic sweeps, V13 remote-store
  contracts, V15/V16 container and HPC executors, V17 reliability policies, and
  V18 cleanup/retention.

Likely public surfaces and durable artifacts:

- Public Python surfaces are likely to include backend capability models,
  store capability diagnostics, stage attempt/lease/commit value objects, and
  possibly new store protocol methods or result models.
- CLI impact includes bounded parallel execution flags plus diagnostic or
  preflight-oriented backend commands: users need warnings or loud failures
  when a selected backend cannot support a requested consistency or concurrency
  mode.
- Durable artifacts likely include attempt records or attempt directories,
  stage/run lease records, output commit records, backend revision/freshness
  evidence, and derived projection freshness metadata. These should live in or
  be read from the authoritative backend for active truth, not from legacy
  human-readable state files.

Structure rationale:

- V9 is placed immediately after run catalog because v8 made current-read
  semantics and derived SQLite projection explicit. It must land before
  bundles, sweeps, remote stores, and broader reliability features depend on
  accidental single-writer filesystem behavior.
- The workflow should start with problem framing and user intent, then confirm
  functionality and behavior, then checkpoint before design-decision review.
  The design review should focus on durable ownership and extensibility
  choices rather than implementation details.

Visible assumptions, risks, and constraints:

- The main architectural risk is split-brain truth if run directories, SQLite,
  event logs, sweep tables, or external trackers independently claim authority
  for active state.
- The main scope risk is adding too much execution policy too early. V9 should
  establish correctness contracts and proofs before turning on broad parallel
  execution.
- The old local filesystem state layout should not constrain the V9 active
  persistence model.
- SQLite is the preferred first stronger backend because it provides standard
  library transactions, compare-and-set-style updates, constraints, and
  consistent local reads. The public contract should remain backend-neutral so
  a later Postgres, service, or remote-capable backend can replace SQLite for
  workloads SQLite cannot safely coordinate.

User clarification questions and resolved answers:

- The user did not raise additional clarification questions about the startup
  framing.
- The user wants V9 to optimize for correctness contracts, near-term parallel
  DAG execution, shared-filesystem/HPC operation, future distributed sweeps,
  and remote/backend adapter readiness where those goals do not conflict. The
  user expects this may require a larger refactor and update rather than a
  minimal additive layer.

## Roadmap Reframing

The previous v9 roadmap item was "Run Bundles And Exporters." That work remains
valuable, but it depends on stable run-state semantics. Large distributed
sweeps, concurrent stages within one run, shared filesystems, remote stores,
and multiple writers expose limitations in the current local single-writer
filesystem assumptions. To avoid locking downstream features into an
insufficient persistence model, the next roadmap item is now the persistence
and concurrency foundation.

Existing roadmap items are pushed back one slot:

- Old v9 "Run Bundles And Exporters" becomes v10.
- Old v10 "Deterministic Sweeps" becomes v11.
- Old v11 "Plugin Discovery" becomes v12.
- Old v12 "Remote Store Contract" becomes v13.
- Old v13 "Remote Store Operations" becomes v14.
- Old v14 "Docker Container Executor" becomes v15.
- Old v15 "HPC Container Execution" becomes v16.
- Old v16 "Reliability Policies And Event Sinks" becomes v17.
- Old v17 "Cleanup And Retention" becomes v18.

## Problem Statement

The current implementation is correct for the v0-v8 local runtime path: one
coordinator mutates one run directory mostly serially, the local filesystem run
store is authoritative, and the v8 SQLite catalog is a derived query
projection. That model is intentionally inspectable and rebuildable, but it is
not sufficient as the only future persistence story.

The next major capabilities need stronger guarantees:

- Concurrent stage execution inside a single run, where independent DAG nodes
  can be claimed, run, committed, failed, retried, or cancelled by multiple
  workers or controller processes.
- Large sweeps where many trials are planned, claimed, run, retried, and
  summarized concurrently across processes, hosts, or schedulers.
- Shared filesystem execution where atomic rename, mtime visibility, lock-file
  behavior, and fsync semantics may vary by filesystem.
- Remote artifact or run-state stores where listing consistency, overwrite
  behavior, atomic commit support, and credential availability are backend
  capabilities rather than universal assumptions.
- Active-run queries where catalog, CLI, notebooks, and sweep controllers need
  correct state without treating a derived SQLite sidecar as a second source of
  truth.

The core risk is a dual-write or split-brain design. If run directories and a
database are both written as independent truth during active execution, failures
between writes make recovery ambiguous. V9 should instead define a stronger
authoritative persistence contract and let different backends implement that
contract with explicit capabilities.

## Goal

Define and, after planning approval, implement the persistence and concurrency
foundation that lets Loom support future concurrent DAG execution, large
concurrent sweeps, remote-capable stores, and shared-filesystem deployments
without introducing multiple sources of truth.

The target architectural direction is:

```text
authoritative RunStore contract
        |
        | implemented by SQLite-first authoritative backend in V9;
        | later by Postgres/service/remote/lease-capable backends
        v
run lifecycle, stage lifecycle, attempts, leases, commits, events
        |
        +--> derived RunCatalog query projections
        +--> sweep aggregation and trial status
        +--> CLI/notebook/status views
```

The new backend becomes the active source of truth. Local files may still exist
for logs, artifact payloads, config/provenance copies, exports, or derived
snapshots where useful, but live state readers must query the authoritative
backend rather than treating human-readable files as fallback truth.

## User Intent

Status: confirmed for goals, non-goals, done criteria, and constraints.

Target users:

- Loom users running large, reproducible research pipelines where independent
  stages in one DAG can execute concurrently.
- Users running many concurrent or distributed sweep trials.
- Users operating on shared filesystems or remote storage systems.
- Future adapter authors who need clear store capabilities and lifecycle
  semantics before adding remote stores, scheduler controllers, or tracking
  integrations.

User-visible outcome:

- Loom has a clear, future-compatible state model for active runs and sweeps.
- Active concurrent execution can be made correct without depending on hidden
  filesystem assumptions.
- Querying run and sweep state remains correct because all query projections
  are derived from one authoritative store contract.
- Downstream roadmap work can build on explicit stage-attempt, lease, commit,
  and event semantics rather than retrofitting them later.
- V9 should ship a stronger coordination backend and prefer a hard swap-over to
  a backend that enables, or is deliberately shaped to support, the future
  feature set rather than leaving the local filesystem as the only
  authoritative backend.
- New active run state should use the new backend as live truth. Loom should
  not rely on legacy human-readable state files to obtain current truth.

Success criteria:

- The selected design makes one component authoritative for run state.
- The old local filesystem state store is removed from the active truth path;
  any filesystem-backed behavior is limited to payload/log/config/provenance
  materialization or explicitly derived/exported artifacts.
- The contract supports multiple concurrent stage writers for different stages
  in one run without corrupting run state.
- The contract supports large concurrent sweeps through trial and resource
  leases without making v11 sweeps depend on ad hoc directory scans.
- Derived catalogs remain derived; they may accelerate queries but never win
  conflicts with authoritative run state.
- Backend capability declarations make unsupported consistency, transaction,
  lease, or remote-listing assumptions visible before execution starts.
- The implementation plan may include a substantial refactor when it reduces
  long-term inconsistency across persistence, execution, sweeps, catalogs,
  remote stores, and reliability.
- V9 proves safe concurrent stage claim, attempt, and commit semantics with
  synthetic local workers.
- V9 explicitly evaluates future user-facing parallel execution policy,
  concurrent runs, distributed sweeps, shared-filesystem operation, remote
  stores, and backend adapters, even when individual user-facing behaviors are
  deferred.
- Shared filesystem and remote-capable-store behavior is capability-gated with
  explicit, loud warnings rather than silently claiming full support.
- New V9 runs use the stronger backend as the authoritative state layer.
- Runner, resume, catalog/status queries, diagnostics, and future sweep
  consumers read live state from the authoritative backend where relevant.
- SQLite is the first intended implementation of the backend-neutral contract,
  with the contract shaped so a more capable backend can be added later without
  changing runner semantics.

Confirmed non-goals and deferrals:

- Distributed or scheduler-backed parallel execution policy can be deferred,
  but V9 should include a bounded user-facing parallel stage execution policy
  over the new backend when backend capabilities are satisfied.
- Full support for arbitrary shared filesystems or remote backends is deferred;
  V9 should expose capability limits and warning paths.
- No old-run migration path is required.
- No legacy local-file state compatibility mode is required.
- Human-readable state files are not a correctness or inspection requirement
  for live state. Derived state export/snapshot behavior is out of scope for
  V9 unless needed for tests or internal debugging, and must not be used as
  active truth.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | V9 is persistence and concurrency foundation inserted after v8; v8 catalog SQLite remains derived; implementation is not started from this workflow. User wants to optimize for all major drivers where non-conflicting and accepts that this may be a large refactor. | Initial framing favored explicit capability limits; intent discovery later sharpened this into a hard backend swap-over for active state. | Exact backend schema and package boundaries remain open. | Intent discovery. |
| Intent discovery | V9 should ship a stronger coordination backend and perform a hard swap-over for active state. No migration path or legacy local-file state compatibility mode is required. Human-readable state files must not be live truth or fallback truth. V9 should prove safe concurrent stage claim/attempt/commit semantics with synthetic local workers. V9 should design explicitly for future user-facing parallel execution policy, concurrent runs, sweeps, shared filesystems, remote stores, and backend adapters even when some behavior is deferred. Shared filesystem and remote-capable-store support should be capability-gated with loud warnings. | SQLite-first authoritative backend behind a backend-neutral contract; live state readers query the backend; derived catalogs stay non-authoritative; unsupported backend guarantees are loud diagnostics. | Exact backend schema, package boundaries, and phase split remain open for design review. | Feature brainstorming. |
| Feature brainstorming | Minimal backend inspection/debugging CLI is included. Derived state export/snapshot behavior is out of scope. A bounded user-facing parallel stage execution policy should be included through both Python API and CLI when capability-gated by the new backend. Deferred behaviors should be documented in the roadmap or feature docs. | Prefer real product validation of the backend through bounded parallel execution rather than contract-only proof. Keep distributed/scheduler-backed policies deferred. | Behavior details for defaults, failure handling, and CLI/API shape remain to confirm. | Functionality and behavior confirmation. |
| Functionality and behavior confirmation | Parallel stage execution is opt-in with serial execution as the default. Failure behavior defaults to stop leasing new stages while allowing already-running attempts to finish, with a configurable policy to continue scheduling non-dependent ready DAG branches when desired. Backend inspection/debugging CLI is read-only in V9. New runs auto-select the SQLite-first authoritative backend with no user setup. Parallel requests fail loudly when required backend capabilities are unavailable. Backend debug CLI is grouped under `loom backend ...`. | Use `max_parallel_stages=1` default and a CLI/API max-concurrency knob. Use a read-only debug CLI. Use a failure policy flag rather than hard-coding one failure response. Fail loudly rather than silently falling back to serial when parallel requirements are not met. | None for functionality/behavior. Design questions remain for schema, package boundaries, and exact API names. | Write checkpoint and reset before design decision review. |
| Context compaction/reset checkpoint | Functionality and behavior are confirmed; checkpoint written in notes. | Resume design review from this file as source of truth; do not reopen behavior unless the user explicitly asks. | Context reset/compaction is required before design decision review. | Design decision review queue. |
| Design decision review | D1 is confirmed: use hybrid authority with per-run authoritative state and separate sweep/workspace coordination authority. D5 is confirmed: keep `StageStatus` coarse and represent attempt/lease/commit detail in separate records and derived snapshots. D9 is confirmed: define a compact workspace/sweep coordination contract for cross-run claims and resource leases, not full scheduler behavior. Repo-supported recommendations are recorded directly. | Keep the hybrid design surface explicit and bounded. | None for design review. | Phase shaping. |
| Phase shaping | Confirmed initial six-phase split by risk and authority boundary. Implementation-plan refinement later expanded this into eight phases after hidden-decision and downstream-compatibility review. | Keep each phase reviewable and avoid smuggling future distributed scheduler or full sweep behavior into V9. | None for phase shaping. | Handoff. |
| Handoff | Planning notes fed `docs/roadmap/stage-9/implementation-plan.md` after explicit user confirmation; implementation-plan refinement expanded the phase split to eight phases. | Do not start implementation from the planning notes or refined draft plan until the implementation-plan quality gate passes. | None for planning notes. | Run implementation-plan quality gate. |

## Brainstormed Capabilities

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Backend-neutral authoritative persistence contract | include | Needed so SQLite can be swapped later for Postgres, service, or remote-capable backends without changing runner semantics. | Contract should cover transactions/compare-and-set, leases, attempt allocation, commits, snapshots, projections, and capabilities. |
| SQLite-first authoritative coordination backend | include | User wants a hard swap-over to a stronger backend; SQLite gives standard-library transactions and constraints for the first implementation. | Must document limits for shared filesystems, high write concurrency, and distributed controllers. |
| Replace active local-file run-state reads and writes | include | User does not want legacy local-file state to remain live truth or fallback truth. | Runner, resume, status, catalog, diagnostics, and tests must move to backend-backed truth where relevant. |
| Stage attempt and output commit records | include | Needed to make retries, interruptions, and concurrent writers unambiguous. | Record model should support later cleanup/retention and retry policy without relying on overwritten latest files. |
| Stage/run leases and abandoned-lease recovery | include | Core requirement for safe concurrent stage writers and future distributed sweeps. | Lease capability must be explicit and warn loudly when unsupported or unsafe. |
| Active-query revision rules for `RunCatalog` and future sweep projections | include | Keeps derived projections from becoming alternate truth. | Catalog reads should validate against authoritative backend revisions or snapshots. |
| Sweep trial/resource lease requirements | include | Future V11 large sweeps need coordination even if V9 does not implement sweep execution. | Trials should remain ordinary runs; sweep-level coordination boundary remains design-review scope. |
| Capability-gated shared filesystem and remote-store behavior | include | User wants loud warnings rather than silent unsupported assumptions. | This is diagnostic/preflight behavior, not full arbitrary shared filesystem support. |
| Minimal backend inspection/debugging CLI | include | User requested a small CLI surface for inspecting/debugging backend state. | Should read authoritative backend state only. It should not become an export/snapshot workflow. |
| Bounded user-facing parallel stage execution policy | include | User asked whether this can be included; including a scoped policy validates the new backend under real user-visible behavior. | Expose through both Python API and CLI. Scope should be capability-gated, local/SQLite-first, and likely expose a max-concurrency knob for independent ready DAG stages. Distributed controllers and scheduler-backed parallelism remain later work. |
| Derived state export/snapshot command | out of scope | User does not want human-readable files or snapshots to become part of live truth. | Export/snapshot behavior can be reconsidered in V10 bundle/export work, explicitly as derived artifacts. |

## Confirmed Functionality And Behavior

Included functionality:

- Backend-neutral authoritative persistence contract.
- SQLite-first authoritative coordination backend with hard swap-over for active
  run state.
- Backend-backed runner, resume, status, catalog, diagnostics, and tests where
  live state is required.
- Stage attempts, leases, output commits, backend revisions, and
  abandoned-lease recovery.
- Capability-gated shared filesystem and remote-store diagnostics with loud
  warnings.
- Minimal backend inspection/debugging CLI over authoritative backend state.
- Bounded user-facing parallel stage execution policy exposed through Python API
  and CLI.
- Sweep trial/resource coordination contracts required by future large sweeps.

User-visible behavior:

- Users get serial behavior by default.
- Users can opt into bounded local parallel stage execution through both Python
  API and CLI, likely with a `max_parallel_stages` option and a corresponding
  CLI flag such as `--max-parallel-stages`.
- Parallel execution only starts when the selected backend declares the
  required claim, lease, attempt allocation, commit, and recovery capabilities.
- If a user explicitly requests parallel execution and the backend lacks
  required capabilities, Loom fails loudly instead of silently falling back to
  serial execution.
- New runs auto-select the SQLite-first authoritative backend with no user
  setup.
- Minimal backend inspection/debugging CLI commands can show authoritative
  backend state, capabilities, attempts, leases, and consistency diagnostics.
- Backend inspection/debugging CLI commands are read-only in V9.
- Backend inspection/debugging CLI commands are grouped under `loom backend ...`.

Default behavior:

- Default execution remains serial, equivalent to `max_parallel_stages=1`.
- The SQLite-first authoritative backend is selected automatically for new runs.
- The default bounded-parallel failure policy stops leasing new stages after a
  terminal stage failure condition while allowing already-running attempts to
  finish and record durable outcomes.
- Dependents of failed stages are blocked once their dependency failure is
  durable.
- Debug CLI operations do not mutate backend state.

Failure behavior and diagnostics:

- A configurable failure policy can disable the stop-new-leases behavior for
  DAG-oriented runs where independent, non-dependent ready branches should keep
  launching and complete despite an unrelated stage failure.
- Runs that request parallel execution against a backend without required
  capabilities fail loudly; silent fallback to serial or unsafe behavior is not
  allowed.
- Shared filesystem or remote-capable-store assumptions produce explicit,
  loud diagnostics when the selected backend cannot prove the required
  guarantees.
- Backend debug CLI diagnostics report authoritative backend facts only and do
  not repair, mutate, export, or snapshot state in V9.

Explicit deferrals:

- Distributed or scheduler-backed parallel execution policy.
- Full arbitrary shared-filesystem support.
- Full remote backend or object-store authority.
- Postgres/service backend implementation.
- Old-run migration.
- Legacy local-file state fallback.
- Derived state export/snapshot command.
- Backend repair or mutation commands.

Out-of-scope behavior:

- Old-run migration or compatibility behavior.
- Mutating backend inspection/repair commands.
- Derived state export/snapshot workflows.
- Distributed/scheduler-backed parallel execution.
- Full arbitrary shared-filesystem or remote authoritative-store support.

Context compaction/reset checkpoint:

- Checkpoint status: written; pause/reset required before design decision
  review because direct context compaction is unavailable.
- Notes path: `docs/roadmap/stage-9/planning.md`
- Stage readback: V9 should hard-swap active run state to a SQLite-first
  backend-neutral authoritative persistence contract. New active state is
  backend truth; legacy local state files are not live truth or fallback truth.
  No old-run migration is required. The backend is selected automatically for
  new runs. Bounded parallel stage execution is opt-in through Python API and
  CLI with serial as default. Explicit parallel requests fail loudly if backend
  capabilities are missing. Default failure behavior stops leasing new stages
  while allowing already-running attempts to finish; a policy flag can continue
  launching independent non-dependent DAG branches. Minimal read-only backend
  diagnostics live under `loom backend ...`. Derived export/snapshot,
  mutation/repair CLI, distributed/scheduler-backed parallel execution,
  Postgres/service backend implementation, full shared-filesystem support, and
  full remote authority are deferred.
- Resume instruction: start a fresh/compacted pass, then reload this notes
  file, `.codex/prompts/roadmap-stage-planning-facilitate.md`, the v9
  roadmap section, and the feature docs listed in metadata. Start at design
  decision review by drafting the maintainability/extensibility decision queue
  implied by the confirmed behavior. Do not ask whether more design decisions
  should be reviewed, and do not reopen functionality or behavior unless the
  user explicitly asks.
- Functionality and behavior reopened after checkpoint: not applicable.

## Design Decision Review

Status: in progress.

### Design Decision Queue

| ID | Decision | Classification | Status | Why it is in the queue |
| --- | --- | --- | --- | --- |
| D1 | SQLite authority scope and database placement | needs discussion | confirmed | This determines whether run facts, stage leases, catalog refresh, and future sweep leases are coordinated per run, per collection/workspace, or through a hybrid authority model. |
| D2 | Package and import ownership for the new backend contract | recorded recommendation | confirmed | Current docs place run persistence in `loom.pipeline.stores`, execution in `loom.pipeline.execution`, sweeps in `loom.pipeline.sweep`, diagnostics above pipeline, and CLI as presentation. |
| D3 | Backend-neutral public contract with SQLite as first implementation | recorded recommendation | confirmed | Confirmed behavior requires a hard swap to SQLite-first active truth without baking SQLite semantics into runner logic. |
| D4 | Removal of legacy local-file active-state fallback | recorded recommendation | confirmed | Confirmed behavior explicitly rejects migration and compatibility fallback for v0-v8 local state files. |
| D5 | Public lifecycle vocabulary boundary for stage leases/attempts/commit phases | needs discussion | confirmed | The roadmap calls for claimed/leased, committing, interrupted, and retryable semantics, but widening the shared `StageStatus` enum affects public APIs, CLI output, and future compatibility. |
| D6 | Artifact commit authority under concurrency | recorded recommendation | confirmed | Current run-level artifact index read/modify/write is unsafe as the primary coordination point under concurrent stage commits. |
| D7 | RunCatalog and status query authority | recorded recommendation | confirmed | V8 catalog is documented as derived; V9 must keep query projections from becoming active truth. |
| D8 | Event records authority boundary | recorded recommendation | confirmed | Existing event logs are useful audit facts, but treating them as a second state machine would create split-brain recovery behavior. |
| D9 | Sweep coordination ownership where it overlaps run state | needs discussion | confirmed | Future sweeps need trial and resource leases across many ordinary runs, but V9 must decide how that coordination relates to the run-state backend without duplicating run execution state. |
| D10 | Backend diagnostics and CLI mutation boundary | recorded recommendation | confirmed | Confirmed behavior includes read-only `loom backend ...` inspection and explicitly defers repair, mutation, export, and snapshot commands. |
| D11 | Capability gating and unsupported-backend behavior | recorded recommendation | confirmed | Confirmed behavior requires loud failures for explicit parallel requests and loud diagnostics for unproven shared-filesystem or remote guarantees. |
| D12 | Optional dependency and backend upgrade path | recorded recommendation | confirmed | Repository rules avoid heavyweight required dependencies; stdlib SQLite can be first while future Postgres/service/cloud backends remain optional adapters. |
| D13 | Testing and conformance strategy | recorded recommendation | confirmed | Feature docs require domain-neutral tests, contract suites, synthetic pipelines, and explicit supported/unsupported backend behavior. |

### Recorded Recommendations

| ID | Selected approach | Rationale | Alternatives rejected | Debt and revisit trigger |
| --- | --- | --- | --- | --- |
| D2 | Keep the authoritative run-state contract and SQLite implementation under `loom.pipeline.stores`, with stable exports from `loom.pipeline.stores` and status/value objects in `loom.pipeline.status` or adjacent model modules. Keep execution orchestration in `loom.pipeline.execution`, sweep orchestration in `loom.pipeline.sweep`, reusable diagnostics in `loom.diagnostics`, and CLI presentation in `loom.cli`. | This follows `docs/structure.md`, `run-store.md`, and `execution.md`: stores persist state, execution decides transitions, sweeps delegate ordinary runs, diagnostics sit above pipeline, and CLI does not duplicate lifecycle logic. | A new top-level `loom.persistence` package is rejected for V9 because it would duplicate an existing subsystem boundary before there is more than one implemented backend family. Putting backend logic in `loom.runs` is rejected because catalogs are derived query projections. | If V9 or later adds a service-backed backend that coordinates multiple subsystems outside pipeline runs, revisit whether a top-level persistence package reduces coupling. |
| D3 | Define backend-neutral protocols, capability models, and result records first; implement SQLite as the first authoritative backend behind those contracts. Runner, resume, catalog/status, diagnostics, and future sweeps must depend on the contract rather than on SQLite-specific details. | The user confirmed a hard swap to a stronger backend while preserving an upgrade path to Postgres, service, or remote-capable backends. | Making SQLite APIs the public runner contract is rejected because it would make later backend upgrades invasive. A contract-only V9 without a real backend is rejected by the confirmed hard swap-over behavior. | Revisit when a second backend is implemented; contract tests must expose assumptions that were accidentally SQLite-only. |
| D4 | Remove legacy local-file state from the active truth path for new runs. Files may remain for payloads, logs, config/provenance copies, worker handoff materialization, and later derived exports, but not as fallback state truth. | The checkpoint explicitly confirms no migration, no compatibility mode, and no human-readable live truth requirement. | Dual-writing files and SQLite as coequal state is rejected because failures between writes create ambiguous recovery. Silent fallback to old local state is rejected because it hides unsupported backend behavior. | Old v0-v8 runs may become unreadable by new live-state tools unless separate later export/import work chooses to handle them. |
| D6 | Make per-stage committed artifact facts authoritative, and treat run-level artifact indexes as materialized/derived views unless a backend can update an index transactionally in the same commit operation. | Parallel stage commits make a single read/modify/write `artifacts.json` unsafe as the coordination source. Per-stage commit facts align with stage attempts, retries, retention, and remote manifest-last artifact commits. | Keeping `artifacts.json` as the sole active artifact authority is rejected for concurrent writers. Letting artifact stores decide stage success is rejected because execution owns lifecycle decisions. | Revisit if a future backend provides transactional aggregate indexes that can be updated atomically with stage commit records. |
| D7 | Keep `RunCatalog`, CLI listing, status summaries, and future sweep dashboards as projections over authoritative backend revisions/snapshots. Projections can cache, refresh, or warn, but they cannot win conflicts with backend truth. | V8 explicitly made the SQLite catalog rebuildable and derived. V9 strengthens the freshness source; it does not promote catalog SQLite into a second authority. | Promoting `.loom_catalog/catalog.sqlite` to active truth is rejected. Reading old local state files for current truth is rejected. | Revisit if Loom later adds a remote catalog service; that service must still declare whether it is authoritative or a projection. |
| D8 | Treat structured run/stage/attempt/lease/commit records as authoritative state. Treat append-only events as audit and diagnostics records unless a later roadmap version explicitly selects an event-sourced backend. | Events are useful for chronology and debugging, but deriving authoritative state from both tables and logs would create split-brain recovery semantics. | Event logs as the primary state machine are rejected for V9. Unstructured logs as recovery input are rejected. | Revisit only if an event-sourced backend becomes an explicit design goal with replay, compaction, and schema migration rules. |
| D10 | Keep `loom backend ...` read-only in V9. It may show capabilities, authoritative run facts, attempts, leases, revisions, and consistency diagnostics; it must not repair, mutate, export, or snapshot backend state. | This matches confirmed behavior and keeps debugging separate from normal execution APIs. | Mutating repair commands and export/snapshot workflows are rejected for V9. Reusing backend inspection as a human-readable state export is rejected. | Add repair/export commands only under later roadmap work with explicit safety, dry-run, and authority rules. |
| D11 | Gate parallel execution, shared-filesystem assumptions, and remote-capable-store assumptions on explicit backend capabilities. Explicit parallel requests fail loudly when capabilities are missing; diagnostics warn loudly when guarantees cannot be proven. | This is confirmed behavior and prevents unsafe silent serial fallback or accidental distributed assumptions. | Silent fallback to serial after an explicit parallel request is rejected. Treating all filesystem paths as equivalent is rejected. | Revisit capability names and thresholds after conformance tests exercise a second backend or a real shared-filesystem deployment. |
| D12 | Use the Python standard-library `sqlite3` backend for V9 and keep future stronger backends behind optional adapters or plugin boundaries. | Repository rules discourage heavyweight runtime dependencies without design reason, and SQLite gives transactions, constraints, and consistent local reads for the first implementation. | Requiring Postgres, cloud SDKs, or service processes in V9 is rejected. Encoding backend-specific SDK imports into core import paths is rejected. | Revisit dependency policy when a future backend provides a capability SQLite cannot safely provide and the implementation plan justifies the dependency. |
| D13 | Add contract/conformance tests for the backend protocol, capability gating, unsupported-capability failures, and synthetic concurrent stage claim/commit/recovery behavior. Keep default tests local, deterministic, synthetic, and filesystem-only. | This follows `testing.md` and directly validates the new correctness contract without downstream domain packages. | Testing only through one happy-path runner flow is rejected. Requiring network, cluster, or cloud resources by default is rejected. | Revisit suite boundaries when optional remote or scheduler backends land; mark those suites opt-in. |

### Needs Discussion Decisions

| ID | Decision | Status | Feedback needed |
| --- | --- | --- | --- |
| D1 | SQLite authority scope and database placement | confirmed | Hybrid authority selected, with explicit design-surface guardrails. |
| D5 | Public lifecycle vocabulary boundary for stage leases/attempts/commit phases | confirmed | Keep `StageStatus` coarse; model concurrency details through attempt, lease, commit, and derived snapshot records. |
| D9 | Sweep coordination ownership where it overlaps run-state storage | confirmed | Define a separate compact workspace/sweep coordination contract over the same capability vocabulary; defer full scheduler and sweep execution behavior. |

#### D1 Discussion Notes

Implication frame:

- Per-run authority gives the cleanest ownership for one run, easiest movement
  and bundling, and a direct replacement for current run directories, but it is
  weak for global sweep/resource coordination because no single place can
  atomically claim trials or enforce collection-level concurrency.
- Collection/workspace authority gives the strongest single coordination point
  for concurrent runs and future sweeps, but it makes each run less
  self-contained, risks turning the collection database into a second catalog,
  and complicates later bundle/export behavior.
- A hybrid model keeps run/stage/attempt/lease/commit/artifact facts in a
  per-run authoritative backend and uses a separate sweep/workspace
  coordination backend only for cross-run facts such as sweep manifests, trial
  leases, resource leases, global concurrency counters, and `run_uri`
  references.

Current recommendation:

- Prefer the hybrid model for strict delineation. It gives one authority for
  facts inside a run and a separate authority for facts across runs, while
  keeping derived catalogs out of both authority roles.
- The implementation plan should make the boundary explicit: per-run backend
  owns run correctness; sweep/workspace backend owns cross-run coordination;
  catalog owns only derived query projection.

Confirmed decision:

- Use a hybrid authority model.
- Per-run authoritative SQLite state owns run, stage, attempt, run/stage lease,
  output commit, artifact fact, event/audit, and run revision records for one
  run.
- A separate sweep/workspace coordination authority owns only cross-run facts:
  sweep manifests, trial leases, named resource leases, global concurrency
  counters, and references to ordinary `run_uri` values.
- The run catalog remains derived from authoritative state and must not become
  either the run authority or the sweep/workspace coordination authority.

User feedback:

- The user selected the hybrid model and asked to pursue it while being careful
  about design surface considerations.

Rejected alternatives:

- Strict per-run authority is rejected because it cannot cleanly coordinate
  large sweeps, global concurrency limits, or named resource slots without
  introducing hidden side channels.
- Strict collection/workspace authority is rejected because it makes individual
  runs less self-contained and increases the risk that query/catalog storage
  becomes confused with active truth.

Maintainability impact:

- The hybrid split keeps each subsystem's ownership narrower: run correctness
  remains local to a run-state contract, while cross-run scheduling and resource
  allocation remain sweep/workspace concerns.
- The implementation plan must avoid over-expanding V9 by defining compact
  coordination interfaces and shared capability vocabulary rather than
  implementing full distributed sweep behavior.

Extensibility and future expansion impact:

- Per-run state can later be bundled, inspected, retained, or moved without
  dragging sweep/workspace state into every run artifact.
- Sweep/workspace coordination can later move to Postgres, a service backend,
  or scheduler-aware controller without changing per-run stage lifecycle
  semantics.
- Backend capability records should make clear whether a backend supports
  per-run coordination only, sweep/workspace coordination, or both.

Debt and revisit trigger:

- V9 must carry the complexity of two authority scopes. Revisit the split if
  the first non-SQLite backend shows the contracts cannot share enough
  capability vocabulary, or if V11 sweeps require cross-run transactions that
  force a stronger workspace authority.

#### D5 Discussion Notes

Decision frame:

- Widening `StageStatus` with values such as `READY`, `LEASED`, `CLAIMED`,
  `COMMITTING`, `INTERRUPTED`, or `RETRYABLE` would make transient
  coordination phases part of Loom's durable public status vocabulary.
- Keeping `StageStatus` coarse preserves compatibility and keeps status focused
  on user-meaningful lifecycle outcomes, while first-class attempt, lease,
  commit, and recovery records carry the concurrency facts needed for
  correctness.
- A second public enum for runtime phase would be explicit, but it increases
  public API surface and can become nearly as compatibility-heavy as widening
  `StageStatus`.

External reference considered:

- Prefect v3 separates state `type` from state `name`: state types drive
  orchestration logic, while names are visual bookkeeping. Prefect also stores
  a timestamp, human message, result data, and structured `state_details` on
  state objects. Its type set is comparatively coarse (`SCHEDULED`, `PENDING`,
  `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `CRASHED`, `PAUSED`,
  `CANCELLING`), while names such as `Retrying`, `AwaitingRetry`, `Late`, or
  `Cached` refine display without changing the underlying type.
- This supports the Loom direction: keep orchestration-driving status coarse,
  and put detailed lifecycle facts into structured side records or derived
  views instead of growing the core status enum for every operational phase.
- Sources checked on 2026-05-09: Prefect v3 States docs
  (`https://docs.prefect.io/v3/concepts/states`) and Prefect SDK state schema
  reference
  (`https://reference.prefect.io/prefect/server/schemas/states/`).

Confirmed decision:

- Use option B: keep `StageStatus` coarse and model concurrency detail through
  first-class records and derived snapshots.
- Authoritative records should include `StageAttemptRecord`,
  `StageLeaseRecord`, `StageCommitRecord`, and recovery/interruption facts as
  needed by the backend contract.
- User-facing inspection should expose a derived lifecycle snapshot that can
  show a display phase such as ready, leased, running, committing, retryable,
  or lease-expired without making each display phase a durable `StageStatus`.

Reason, status, and message policy:

- `StageStatus` and `RunStatus` remain the coarse machine-state categories used
  for durable outcome logic and compatibility.
- Attempt, lease, commit, failure, and recovery records carry structured
  machine-readable reason codes, owner/worker data, timestamps, backend
  revision evidence, and plain-data details.
- Human-readable `message` fields remain allowed on status or record snapshots,
  but messages must not be the only source of machine behavior.
- Derived snapshots may expose a display name/phase for CLI/API presentation,
  analogous to Prefect's state name, but that display label is not
  authoritative for transition decisions.

User feedback:

- The user selected option B and asked that Prefect's lifecycle/status/reason
  handling be considered.

Rejected alternatives:

- Widening `StageStatus` for every coordination phase is rejected because it
  creates public API churn and blurs durable outcomes with transient backend
  mechanics.
- Adding a second public enum in V9 is rejected unless implementation planning
  finds that typed derived phases are required for API clarity; the default is
  a derived snapshot model with stable fields and structured reason codes.

Maintainability impact:

- Coarse status keeps execution, resume, CLI, and tests from depending on
  backend-specific transient states.
- Separate records make attempt history, retries, lease recovery, and commit
  ordering inspectable without overloading status semantics.

Extensibility and future expansion impact:

- Future backends can add richer lease, worker, scheduler, or recovery details
  without changing the stable status vocabulary.
- A later API can promote selected derived phases to stable public values if
  repeated user workflows prove they need that contract.

Debt and revisit trigger:

- V9 must design derived lifecycle snapshots carefully enough that CLI and API
  users can still understand "what is happening now." Revisit if users need a
  stable public display-phase enum for automation rather than just inspection.

#### D9 Discussion Notes

Future feature-set requirements:

- Multi-run concurrency requires a single coordination point for cross-run
  work admission: which run or trial may start now, which controller owns it,
  and which global or named resource slot it consumes.
- Large sweeps need atomic trial claims, trial attempt allocation,
  retry/cancellation bookkeeping, global concurrency limits, named resource
  leases, and abandoned-trial recovery across many ordinary `run_uri` values.
- Concurrent runs should not require the workspace authority to inspect or
  mutate per-stage state inside each run. Per-run authoritative backends remain
  responsible for each run's DAG, stage attempts, leases, output commits,
  artifact facts, and terminal outcome.
- Scheduler-backed execution should be able to map workspace leases to later
  worker pools, queue slots, scheduler jobs, or service-side controllers without
  changing per-run stage lifecycle records.
- Recovery needs idempotent, timestamped leases with owners, heartbeats or
  expirations, explicit release/failure records, and backend capability checks.
- Query surfaces need to compose the two scopes safely: a sweep or workspace
  status view can summarize trial/run references from the coordination store
  and then read each run's authoritative snapshot, while any aggregate table
  remains derived.

Recommended boundary:

- Define a compact cross-run coordination contract in V9, likely as
  `SweepCoordinationStore` or `WorkspaceCoordinationStore`, over the same
  backend capability vocabulary as the per-run store.
- Include only the primitives needed to avoid painting V11 into a corner:
  sweep/workspace identity, trial manifest references, trial/resource lease
  records, global concurrency counters, run references, and recovery scans.
- Do not implement full multi-run scheduler policy, adaptive sweeps,
  distributed controllers, fairness policies, or scheduler-specific queue
  semantics in V9.

Design-surface guardrails:

- The workspace/sweep authority must not become a second run-state backend.
- The workspace/sweep authority must not replace the derived run catalog.
- The per-run backend must not learn sweep-specific optimization, metrics, or
  adaptive-search semantics.
- Public capability diagnostics should say whether a backend supports per-run
  coordination, cross-run coordination, or both.

Confirmed decision:

- Define a separate compact workspace/sweep coordination contract in V9.
- The contract should share the backend capability vocabulary with the per-run
  authoritative backend, but it should own only cross-run facts: sweep/workspace
  identity, trial manifests or trial references, trial leases, named resource
  leases, global concurrency counters, run references, and recovery scans.
- Full multi-run scheduling policy, distributed controllers, adaptive sweeps,
  fairness policy, scheduler-specific queue behavior, and user-facing sweep
  execution workflows remain deferred.

User feedback:

- The user accepted the direction and asked that future feature-set needs such
  as multi-run concurrency be considered.

Rejected alternatives:

- Putting sweep trial/resource leases directly into the per-run `RunStore` is
  rejected because it would make run state responsible for cross-run scheduling
  and resource policy.
- Deferring all sweep/workspace coordination contracts to v11 is rejected
  because V9's backend design would otherwise risk missing the primitives
  needed by multi-run concurrency and large sweeps.
- Making the run catalog the sweep/workspace authority is rejected because the
  catalog remains a derived query projection.

Maintainability impact:

- A separate coordination contract keeps per-run correctness, cross-run
  admission/resource control, and derived query projection as distinct
  responsibilities.
- The V9 implementation plan must keep this contract compact so it documents
  and tests the required primitives without implementing a full sweep runner.

Extensibility and future expansion impact:

- V11 deterministic sweeps can build trial claiming, retry, and resource limits
  on an existing coordination boundary.
- Future scheduler-backed or service-backed multi-run execution can replace or
  extend the workspace coordination backend without changing per-run stage
  lifecycle semantics.

Debt and revisit trigger:

- V9 may only provide the contract plus SQLite/local conformance coverage for
  workspace coordination. Revisit when v11 defines concrete sweep execution
  flows or when a remote/service backend needs stronger cross-run transactions.

### Design Review Readback

- D1 confirmed hybrid authority: per-run authoritative state for run
  correctness, separate workspace/sweep coordination for cross-run facts, and
  derived catalogs outside both authority roles.
- D5 confirmed coarse `RunStatus`/`StageStatus` with separate attempt, lease,
  commit, recovery, reason, and derived snapshot records. Prefect's type/name
  split was considered as supporting evidence for keeping machine status coarse
  and display/reason detail structured separately.
- D9 confirmed compact cross-run coordination contract for future multi-run
  concurrency and sweeps, while deferring full scheduler, distributed
  controller, and sweep execution behavior.
- All other design decisions are recorded recommendations with rationale,
  alternatives, debt, and revisit triggers.

Design review status: complete.

## Phase Shaping

Status: complete.

### Initial Proposed Phase Breakdown

| Phase | Goal | Scope | Out of scope | Acceptance and tests |
| --- | --- | --- | --- | --- |
| 1. Authority contracts and public models | Define the backend-neutral contracts before behavior depends on them. | Per-run and workspace/sweep capability vocabulary; attempt, lease, commit, revision, reason, and derived snapshot models; status remains coarse; errors and unsupported-capability results; docs updates. | SQLite schema implementation; runner swap-over; parallel execution. | Unit and contract tests over fake/conformance stores; import-boundary checks; docs explain authority boundaries and deferrals. |
| 2. Per-run SQLite authoritative backend | Implement the first per-run authoritative backend behind the contract. | SQLite schema and repository/service layer for run, stage, attempt, lease, commit, artifact fact, event/audit, revision, and snapshot reads for one run. | Runner hard swap; workspace/sweep coordination; broad CLI. | Contract tests prove supported transactions, guarded transitions, attempt allocation, lease behavior, commit ordering, revisions, and unsupported capabilities. |
| 3. Serial active-state hard swap | Move new active runs to SQLite-backed truth while preserving serial user behavior. | New runs auto-select SQLite backend; runner/planner/resume/status paths read/write authoritative backend; legacy local state files removed from live truth; files remain for logs, payloads, config/provenance, and worker materialization only. | Parallel scheduling; sweep/workspace coordination; old-run migration. | Existing serial e2e behavior passes against the new backend; tests prove no fallback to legacy state files; old-run migration remains absent by design. |
| 4. Diagnostics, projections, and read-only backend CLI | Make the new authority inspectable without creating mutation or export surfaces. | `RunCatalog`/status projections validate against backend revisions; read-only `loom backend ...` commands show capabilities, attempts, leases, commits, revisions, and diagnostics; shared-filesystem and remote-store capability warnings. | Repair, mutation, export, snapshot, remote authority. | CLI/API tests for read-only behavior, warnings, stale projection handling, and no project-code imports during inspection. |
| 5. Bounded parallel stage execution | Validate the concurrency contract through user-facing local parallel execution. | Atomic ready-stage claim, attempt allocation, lease renewal/expiry, output commit, abandoned-lease recovery; API/CLI max parallel stages; failure policy for stop-new-leases versus continue-independent branches. | Distributed controllers; scheduler-backed parallelism; speculative execution. | Synthetic DAG integration/e2e tests with concurrent workers, failure branches, recovery, capability-gated loud failures, and serial default behavior. |
| 6. Workspace/sweep coordination foundation | Establish the cross-run coordination boundary required by future multi-run concurrency and large sweeps. | Compact workspace/sweep coordination contract and SQLite/local conformance for sweep/workspace identity, trial references, trial leases, resource leases, global concurrency counters, run references, and recovery scans. | Full sweep runner, adaptive sweeps, scheduler queues, fairness policy, remote service backend. | Contract tests over fake/SQLite coordination stores; docs show how v11 sweeps and future scheduler/service backends build on the boundary. |

Phase-shaping rationale:

- The first two phases isolate contract and backend risk before the runner is
  changed.
- The hard swap happens under serial behavior before parallel scheduling adds
  another variable.
- Diagnostics and projections are separate so inspection cannot quietly become
  repair/export or alternate truth.
- Bounded parallel execution comes after the authoritative backend is already
  serving live state.
- Workspace/sweep coordination lands as a foundation phase, not a full sweep
  implementation, preserving the confirmed design-surface guardrails.

Phase-shaping confirmation:

- The user confirmed the proposed initial six-phase split.
- The implementation-plan refinement expanded the split to eight phases after
  reviewing hidden decisions and downstream feature impacts. The refined plan
  separates contracts/schema/read-model policy, per-run SQLite backend,
  materialization/read models, internal serial write-path integration, public
  hard-swap/read-path swap, diagnostics CLI, bounded parallel execution, and
  workspace/sweep coordination.

## Handoff

Status: complete; explicit user confirmation was received and
`docs/roadmap/stage-9/implementation-plan.md` was drafted and
post-review refined on 2026-05-09 from these notes.

Primary source inputs:

- `docs/roadmap/stage-9/planning.md`
- `docs/roadmap.md`
- `docs/roadmap/stage-8/implementation-plan.md`
- `docs/features/run-store.md`
- `docs/features/state.md`
- `docs/features/execution.md`
- `docs/features/reliability.md`
- `docs/features/run-catalog.md`
- `docs/features/sweeps.md`
- `docs/features/remote-stores.md`
- `docs/features/artifacts.md`
- `docs/features/runtime-resources.md`
- `docs/features/slurm.md`
- `docs/features/testing.md`
- `docs/loom.md`
- `docs/structure.md`

Implementation-plan draft must preserve these confirmed decisions:

- Hard swap new active run state to a SQLite-first authoritative backend behind
  backend-neutral contracts.
- No old-run migration path and no legacy local-file state fallback.
- Hybrid authority: per-run authoritative backend for run correctness and a
  separate workspace/sweep coordination authority for cross-run claims,
  resource leases, global concurrency counters, and run references.
- `RunCatalog`, status summaries, and future sweep dashboards remain derived
  projections that validate against authoritative revisions or snapshots.
- `RunStatus` and `StageStatus` stay coarse. Stage attempts, leases, commits,
  recovery facts, structured reason codes, and derived snapshots carry
  concurrency detail.
- Submitted-operation records are first-class authoritative facts for
  scheduler submissions, worker handoff, cancellation attempts, active
  submission snapshots, and partial submitted-work facts. Coarse `SUBMITTED`
  statuses are summaries, not scheduler truth.
- Per-stage committed artifact facts are authoritative; run-level artifact
  indexes are materialized views unless a backend can update them
  transactionally with the commit.
- Submitted or scheduler-backed workers may self-finalize attempt-scoped facts
  only with a valid backend-issued attempt/lease fencing token. Local and
  subprocess execution remains controller-finalized by default, and run
  finalization remains controller or recovery owned.
- Artifact commit validates declared outputs and payload existence/checksums
  when supported, then records commit facts, artifact facts, derived index
  update, terminal stage status, backend revision, and event evidence through
  one backend transaction where capabilities allow.
- Lease acquire, renew, expire, and recovery comparisons use backend-owned
  time. SQLite uses a local UTC clock and is capability-declared safe only for
  local or same-host coordination.
- Minimal `loom backend ...` CLI is read-only and must not repair, mutate,
  export, or snapshot backend state in V9.
- Bounded local parallel stage execution is opt-in through Python API and CLI,
  serial remains the default, and explicit parallel requests fail loudly when
  required backend capabilities are unavailable.
- Default bounded-parallel failure behavior stops leasing new stages while
  already-running attempts finish; a policy flag can continue launching
  independent non-dependent ready DAG branches.
- Shared-filesystem and remote-store support is capability-gated with loud
  diagnostics; full arbitrary shared filesystem, full remote authority,
  Postgres/service backend, distributed/scheduler-backed parallelism, and
  derived export/snapshot workflows are deferred.

Confirmed refined implementation phase outline:

1. Authority contracts, schema policy, and compatibility surface.
2. Per-run SQLite backend and transaction semantics.
3. Materialization boundary and authoritative read models.
4. Serial execution write-path integration.
5. Public serial hard swap and read-path swap.
6. Read-only backend diagnostics CLI.
7. Bounded parallel stage execution.
8. Workspace/sweep coordination foundation.

Plan-quality-gate risks for the implementation plan:

- The plan must prevent split-brain truth between SQLite state, local files,
  derived catalogs, events, and future sweep/workspace tables.
- The plan must make transaction, compare-and-set, lease, commit, revision, and
  recovery semantics explicit before implementation phases depend on them.
- The plan must include submitted-operation state and fenced worker
  finalization so current SLURM-style submitted work and future scheduler
  workers do not require a separate authority path.
- The plan must keep Phase 4 independently mergeable by keeping backend
  selection internal/test-selectable until Phase 5 performs the public hard
  swap after read paths are backend-backed.
- The plan must define artifact commit failure semantics and backend-owned
  lease-time limitations clearly enough for parallel execution and future
  scheduler-backed work.
- The plan must define the internal authoritative read model needed by status,
  catalog, diagnostics, and future v10 bundles without adding a v9 user-facing
  export/snapshot workflow.
- The plan must keep the workspace/sweep coordination contract compact so V9
  does not become a full sweep scheduler or distributed workflow engine.
- The plan must define conformance tests for supported and unsupported
  capabilities, synthetic concurrent stage execution, abandoned-lease recovery,
  stale projection warnings, and read-only backend CLI behavior.
- The plan must document accepted SQLite limitations for network/shared
  filesystems, high write concurrency, distributed controllers, and future
  remote/service backend upgrade triggers.

Unresolved assumptions:

- Exact public API and CLI flag names remain implementation-plan scope.
- Exact SQLite schema, table names, and module file names remain
  implementation-plan scope.
- The hard swap has been split in the refined implementation plan into
  materialization/read-model, internal serial write-path integration, and
  public hard-swap/read-path phases for reviewability.

Next workflow action:

- Run the implementation-plan quality gate with `loom_plan_reviewer`. The
  local post-review decisions are incorporated, but they do not satisfy the
  formal gate. Refine the plan if needed, and do not begin phase
  implementation until the gate has passed.

## Reference Design Material

The sections below are evidence and candidate design material from roadmap and
repo analysis. Confirmed decisions above take precedence when this reference
material still uses earlier tentative wording.

## Design Principles

- One authoritative run-state contract. Avoid dual-write truth across files and
  SQLite or external trackers.
- Backend-neutral first. SQLite is the first authoritative implementation, but
  the contract must be shaped so stronger future backends can replace it.
- Explicit capabilities. Backends must say whether they support compare-and-set
  transitions, lease acquisition, lease renewal, atomic commit, consistent
  listing, append-only events, and transaction scopes.
- Stage attempts are first-class. Retries, interrupted work, concurrent
  workers, and cleanup cannot be represented safely by overwriting only the
  latest stage files.
- Success is a committed fact. A stage becomes `SUCCEEDED` only after outputs,
  artifact refs, fingerprints, provenance, and commit records are durable.
- Queries use projections, not alternate truth. Catalogs, status summaries, and
  sweep dashboards may materialize views, but they must refresh or validate
  against authoritative state.
- Domain neutrality remains non-negotiable. Loom owns generic lifecycle,
  persistence, artifacts, provenance, and execution records; project code owns
  metric meaning and artifact payload semantics.
- Large-scale features should fail clearly when the selected backend cannot
  provide required coordination guarantees.

## Core Design Questions

| Question | Why it matters | Current leaning |
| --- | --- | --- |
| What is the minimum authoritative `RunStore` transaction contract? | Determines whether concurrent stages can safely claim, commit, fail, and retry. | Add explicit compare-and-set transitions, attempt allocation, stage leases, and commit records. |
| Should V9 add a new backend, or only define the contract and adapt local filesystem? | A real coordination backend may be needed before large concurrency work is safe. | Plan thoroughly before deciding; a fake/contract backend is likely required, and a local SQLite coordination backend may be worth considering. |
| What guarantees must a backend provide for parallel DAG execution? | Prevents silent use of weak stores for unsafe workloads. | Capability-gate parallel execution on lease and atomic transition support. |
| How should run status be derived from concurrent stage state? | A run can be active while many stages are independently pending, leased, submitted, running, or terminal. | Treat run status as a lifecycle summary with stage-level state as authoritative detail. |
| How should sweep state differ from run state? | Large sweeps need trial claiming, global limits, and aggregation across many ordinary runs. | Keep trials as ordinary runs, but add sweep-level manifests and trial/resource leases. |
| How should shared filesystems be classified? | POSIX-like paths do not always imply reliable locking or cache visibility. | Add explicit local/shared-filesystem capability checks and warnings. |
| Which event records are authoritative and which are audit-only? | Event sourcing can become a second state model if not bounded. | Status/attempt/commit records are authoritative; events are append-only audit facts unless a later event-sourced backend is explicitly selected. |

## Lifecycle Implications

### Run Lifecycle

Concurrent execution changes run status from a simple serial controller marker
to a summary over the DAG's active state.

Candidate run-level model:

```text
CREATED/OPENED -> PLANNED -> RUNNING -> terminal
```

The run is `RUNNING` while any required stage is eligible, leased, submitted,
running, committing, retryable, or waiting on dependencies. A terminal run
status should be written only when the DAG reaches a stable outcome:

- `SUCCEEDED`: all required stages are succeeded, skipped, or reused according
  to the plan.
- `FAILED`: at least one required stage has failed without an allowed retry,
  and dependent stages are blocked.
- `CANCELLED`: cancellation has been requested and active/pending work has
  reached a cancelled or safely abandoned state.
- `INTERRUPTED` or equivalent: the controller or leases disappeared and the run
  needs recovery before correctness can be claimed.

Run summaries may be materialized for fast reads, but they must be derived from
stage, attempt, lease, and commit state.

### Stage Lifecycle

Concurrent stage execution needs an explicit lifecycle for claims and attempts:

```text
PENDING
  -> READY
  -> LEASED/CLAIMED
  -> RUNNING or SUBMITTED
  -> COMMITTING
  -> SUCCEEDED
```

Failure and interruption branches:

```text
RUNNING/SUBMITTED -> FAILED
RUNNING/SUBMITTED -> CANCELLED
LEASED/RUNNING/SUBMITTED -> LEASE_LOST or INTERRUPTED
FAILED -> READY for retry when policy and attempt records allow it
```

Important invariants:

- Only one active attempt for a stage may own the stage lease at a time unless
  a future design explicitly supports speculative execution.
- Attempt numbers are allocated atomically.
- Attempt-scoped files or records preserve failed and interrupted work.
- Latest-stage views are derived from the committed latest attempt.
- Stage `SUCCEEDED` is written only after the output commit record is durable.
- Downstream readiness is based on committed upstream outputs, not merely a
  worker process exit.

### Artifact And Output Commit

Parallel stage execution makes the artifact index a coordination point. A
single read-modify-write artifact index is fragile under concurrent commits.

Candidate directions:

- Use per-stage committed artifact records as the authoritative output facts,
  then build the run-level artifact index as a derived/materialized view.
- If the run-level artifact index remains authoritative, require serialized
  compare-and-set updates or transactions for index modifications.
- Make output commit records explicit:

```text
attempt started
outputs staged
outputs validated
artifact refs committed
stage marked succeeded
```

Remote artifact stores add additional commit semantics: manifest-last commits,
backend checksums, generation IDs, and explicit unsupported-operation errors.

### Active-Run Queries

V8 current reads use freshness validation and a derived SQLite sidecar. V9
should preserve that pattern but make the freshness source stronger:

- Query projections may use SQLite, cached summaries, or sweep tables.
- Query projections must validate against authoritative store revisions,
  tokens, or transaction sequence numbers.
- If a run changes while queried, the result should retry or return a
  machine-readable actively-changing warning.
- If a backend cannot provide a current-read guarantee, it must report the
  weaker guarantee explicitly.

## Sweep Implications

Large concurrent sweeps need coordination at two levels:

- Trial-level: plan, claim, run, retry, cancel, and summarize each trial.
- Global-level: enforce concurrency limits, shared resource limits, controller
  handoff, and recovery from abandoned trials.

Candidate sweep foundation:

```text
sweep manifest
trial manifest
trial lease records
resource lease records
trial run_uri references
trial attempt/retry records
derived sweep status summaries
```

Trials should remain ordinary Loom runs so catalogs, bundles, provenance, and
diagnostics continue to work. The sweep coordinator should not duplicate stage
execution logic. It should allocate or claim trials and then delegate each trial
to the ordinary run lifecycle.

Large concurrent sweeps probably require a backend with stronger coordination
than plain directory scans. The V9 contract should let v11 sweeps require a
lease-capable store for distributed execution while still supporting local
sequential sweeps through the SQLite-first authoritative backend.

## Persistence Model Ideas

### Option A - Strengthen Local Filesystem Only

Keep files as the only implemented authoritative backend, adding stage locks,
attempt directories, append-only records, and conservative compare-and-set
through file creation or rename patterns.

Benefits:

- Keeps the current inspection model.
- Avoids new runtime dependencies.
- Good for local and simple shared-filesystem workflows.

Risks:

- Weak on distributed locking and shared filesystem cache semantics.
- Hard to provide robust trial/resource leases.
- Hard to give strong active-query guarantees at scale.

### Option B - Define Contract In V9, Add Fake/Contract Backend Only

Specify the stronger `RunStore` and `SweepStore` capability contracts and add a
fake in-memory or local test backend for contract testing, while adapting the
current filesystem backend only for the guarantees it can safely provide.

Benefits:

- Maximizes planning quality before committing to a concrete backend.
- Makes backend capabilities explicit.
- Avoids premature dependency or schema commitment.

Risks:

- Delays real distributed concurrency until a concrete backend lands.
- Later implementation may reveal contract gaps.

### Option C - Add A Local SQLite Authoritative Coordination Backend

Introduce a SQLite-backed authoritative run-state backend for local and shared
single-host coordination, with filesystem files as export/inspection material
or compatibility views.

Benefits:

- Transactions, unique constraints, and compare-and-set updates become easier.
- Better fit for concurrent stage claims and sweep trial leases.
- Reuses standard library SQLite.

Risks:

- Major architectural shift from inspectable files as truth.
- SQLite on network filesystems can have caveats.
- Requires a clear internal state access path so status, catalog, resume, and
  diagnostics read live backend truth rather than old state files.

### Option D - Add A Server/Database Backend Later

Define the contract now, leave filesystem as local truth, and plan a future
Postgres/service-backed store for truly distributed workloads.

Benefits:

- Avoids overloading SQLite or shared filesystems with distributed guarantees.
- Better long-term fit for many controllers and large sweeps.

Risks:

- Distributed sweeps remain deferred until that backend exists.
- Core must still avoid assuming only filesystem semantics.

## Current Leaning

The confirmed direction is a hard swap-over to a new authoritative persistence
backend for active state, with SQLite as the first implementation of a
backend-neutral contract. The local filesystem state layout should stop being
the active truth source rather than being preserved through a migration or
legacy compatibility layer.

The design review should still validate the exact contract shape, SQLite schema
boundaries, backend package ownership, and upgrade path to stronger backends.
SQLite is acceptable as the first backend because it supports transactions,
constraints, compare-and-set-style guarded updates, atomic attempt allocation,
lease rows with expirations, consistent local reads, and concurrent readers.
Its known limitations must be capability-gated and loudly diagnosed, especially
for unreliable shared filesystems, high write concurrency, and distributed
controllers.

## Candidate Capability Contracts

Run-state backends may need to declare support for:

- Atomic create/open run.
- Atomic run status compare-and-set.
- Atomic stage status compare-and-set.
- Atomic stage attempt allocation.
- Stage lease acquire/renew/release/expire.
- Run lease or controller lease acquire/renew/release/expire.
- Atomic output commit or transaction record.
- Artifact fact append or transactional artifact-index update.
- Append-only event records with sequence numbers.
- Consistent read of a run snapshot.
- Consistent collection listing.
- Backend revision or freshness token for query projections.
- Safe cancellation propagation.
- Explicit recovery scan for abandoned leases or interrupted attempts.

Sweep-state backends may need to declare support for:

- Atomic sweep creation.
- Atomic trial manifest persistence.
- Atomic trial claim/lease.
- Trial retry attempt allocation.
- Global concurrency lease acquire/renew/release.
- Named resource slot leases.
- Sweep status snapshot.
- Efficient trial listing and filtering.
- Recovery of abandoned trial leases.

Artifact backends may need to declare support for:

- Transactional or manifest-last commit.
- Read-after-write behavior.
- Listing consistency.
- Checksum verification.
- Backend generation or version IDs.
- Local staging requirements.
- Payload materialization support.

## Compatibility Obligations

- Preserve `run_uri` as canonical public identity.
- Replace legacy local-file state as active truth; no migration path or legacy
  compatibility mode is required for old v0-v8 run directories.
- Keep `RunCatalog` and CLI catalog commands as query projections over the new
  authoritative backend.
- Avoid making v8 `.loom_catalog/catalog.sqlite` authoritative.
- Keep authored configs trusted, but do not import project code for state
  queries, catalog reads, sweep status, or recovery.
- Keep default tests local, deterministic, synthetic, and filesystem-only.
- Use optional dependencies or plugin boundaries for non-standard future
  backends.
- Document backend limitations clearly in preflight and runtime diagnostics.

## Non-Goals For V9 Planning

- No full distributed workflow engine.
- No runtime DAG mutation, dynamic fan-out/fan-in, or Bayesian/adaptive sweep
  controller.
- No hosted tracking server as a core dependency.
- No cloud SDK as a required dependency.
- No domain-specific metric store, report semantics, or artifact payload
  interpretation.
- No hidden second source of truth in SQLite, catalogs, event sinks, MLflow, or
  external trackers.

## Planning Quality Gate

The eventual v9 implementation plan should not pass quality review until it
answers:

- What is authoritative for run, stage, attempt, artifact, event, and sweep
  state?
- Which writes are transactional, compare-and-set, append-only, or derived?
- What exact guarantees does the SQLite-first backend provide, and which
  guarantees must be exposed as optional capabilities for future stronger
  backends?
- What guarantees are required for parallel stages within one run?
- What guarantees are required for large concurrent sweeps?
- How do active-run queries avoid stale or partially committed results?
- How are abandoned leases and interrupted attempts detected and recovered?
- How do stage and run lifecycle transitions remain valid under concurrency?
- How are artifact commits made safe across local and remote artifact stores?
- Which future roadmap items are unblocked, and which remain intentionally
  deferred?

## Candidate Phase Sketch

### Phase 1 - Lifecycle And Store Contract Plan

Goal:

- Define the authoritative run, stage, attempt, lease, commit, event, and
  sweep-state contract before code changes depend on it.

Scope:

- Audit current run-store, state, execution, reliability, sweep, remote-store,
  and catalog docs.
- Define required backend capabilities and unsupported-operation behavior.
- Define authoritative versus derived records.
- Confirm the SQLite-first backend contract, schema boundary, and hard
  swap-over semantics.

### Phase 2 - Public Models And Capability Surface

Goal:

- Add typed models and capability records without changing execution behavior.

Scope:

- Backend capability models.
- Stage attempt and lease value models.
- Transaction/commit result models.
- Store errors and preflight diagnostics for unsupported capabilities.

### Phase 3 - SQLite Authoritative Backend Swap-Over

Goal:

- Implement the first authoritative backend and move active run-state writes
  and reads off legacy local state files.

Scope:

- SQLite schema and repository/service layer for runs, stages, attempts,
  leases, commits, events, and revisions.
- Runner, resume, status, catalog, diagnostics, and tests updated to read live
  backend truth where relevant.
- Capability diagnostics for unsupported shared-filesystem or distributed
  assumptions.
- Contract tests proving supported and unsupported guarantees.

### Phase 4 - Concurrent Stage State Prototype

Goal:

- Prove claim/commit/fail/recover semantics with synthetic concurrent workers
  without adding broad parallel execution policy.

Scope:

- Atomic stage claim and attempt allocation.
- Output commit ordering.
- Abandoned lease recovery behavior.
- Integration tests with synthetic DAG branches.

### Phase 5 - Sweep Coordination Foundation

Goal:

- Define or implement the minimal sweep-state coordination primitives that v11
  large sweeps will need.

Scope:

- Trial claim/lease models.
- Global concurrency lease models.
- Recovery and status snapshot semantics.
- Contract tests over fake/SQLite backends.

This sketch is deliberately provisional. The implementation plan should refine
or replace it after design review.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Should v9 ship a concrete SQLite authoritative coordination backend, or only the contract and local/fake backend proof? | Scope, dependencies, migration, testing | Ship a stronger authoritative backend and hard-swap active state to it. SQLite-first behind a backend-neutral contract is the confirmed default; exact schema and boundaries remain design-review scope. | answered for intent |
| Is the local filesystem backend expected to support parallel stages on shared filesystems, or only local/single-host concurrency? | Backend capability matrix, preflight | Capability-gate shared filesystem and remote-capable-store behavior with loud warnings; do not claim full support by default. | answered |
| Should old v0-v8 run directories have a migration or compatibility path? | Scope, compatibility, docs, tests | No migration path and no legacy local-file state compatibility mode in V9. | answered |
| Should stage attempt archives become required before parallel execution? | Run-store layout, recovery, cleanup | Attempt records are required before parallel execution; exact file/archive materialization is an implementation detail. | answered for design |
| Is run-level status stored as authoritative state, derived summary, or both? | State model, catalog, recovery | Store a materialized run summary derived from authoritative stage/attempt/lease/commit facts, with consistency checks. | answered for design |
| Should sweep coordination live in `RunStore`, a separate `SweepStore`, or a shared persistence service interface? | Package boundaries, future sweeps | Use a separate compact workspace/sweep coordination contract over the same backend capability vocabulary. | answered |
| What active-query consistency guarantee should `RunCatalog.list()` promise after v9? | Catalog API, CLI, user expectations | Current reads validate against authoritative backend revisions/snapshots and warn when guarantees cannot be provided. | answered for design |
| Which roadmap items should be split further after this reframing? | Roadmap scope | Use the refined eight-phase v9 split in `docs/roadmap/stage-9/implementation-plan.md`; the six-phase split remains only historical planning context. | answered for planning |
