# Implementation Plan v11: Queue Service, Resource Pools, And Delegated Dispatch

## Metadata

- Status: refined draft
- Source planning notes:
  `docs/implementation-plans/roadmap-v11-planning-notes.md`
- Related implementation plans:
  - `docs/implementation-plans/implementation-plan-v10.md`
  - `docs/implementation-plans/implementation-roadmap.md`
- Related source docs:
  - `README.md`
  - `docs/structure.md`
  - `docs/features/execution.md`
  - `docs/features/runtime-resources.md`
  - `docs/features/slurm.md`
  - `docs/features/preflight.md`
  - `docs/features/cli.md`
  - `src/loom/pipeline/stores/authority_factory.py`
  - `src/loom/pipeline/stores/authority_client.py`
  - `src/loom/pipeline/stores/coordination.py`
  - `src/loom/pipeline/execution/resource_admission.py`
  - `src/loom/pipeline/execution/runner.py`
- Draft pass: complete on 2026-05-13 from confirmed roadmap v11 planning notes
  and the combined `v10-post -> v11` workflow handoff.
- Refine pass: complete on 2026-05-13 after local plan-quality-gate review for
  prerequisite-contract traceability, example-to-validation mapping, and
  snapshot/verification ownership.
- Plan quality gate: passed on 2026-05-13 after one local refinement pass and
  one local confirmation review.
- Blockers:
  - None for `v10-post` Phase 1 start once normal phase selection begins.
  - Main queue phases must not begin until the `v10-post -> v11` transition
    checkpoint is recorded after `v10-post` Phase 4 automated review and
    validation.

## Goal

Implement one stacked `v10-post -> v11` workflow.

The `v10-post` prefix hardens the authority, supervisor, SLURM live-path,
diagnostic, coordination, admission, and offline-import contracts that queue
work will depend on. The main `v11` tranche then adds a queue service under
`loom.queue` with SQLite-backed persistence, whole-run queue items, one FIFO
queue per pool, managed and delegated capacity modes, local and SLURM launch
adapters, daemon-first controller behavior, and a thin operational CLI.

## Context

The current repository already has the core v10 surfaces a queue can build on:

- authority service/client boundaries under `src/loom/authority/` and
  `src/loom/pipeline/stores/authority_client.py`;
- strict authority creation through `create_authority_client(...)`;
- authority-backed coordination and resource-lease contracts in
  `WorkspaceCoordinationStore`;
- runner-side resource admission through
  `acquire_resource_admission(...)` and
  `PipelineRunner._acquire_stage_resource_admission(...)`;
- live SLURM submit, status, and cancellation modules under
  `src/loom/pipeline/executors/slurm/`.

The confirmed v11 planning notes deliberately do not start queue work directly
from that baseline. They first require a namespaced `v10-post` hardening
tranche to freeze the queue-facing contracts around authority truth, strict
live-path behavior, diagnostics labeling, coordination ownership, and
offline-import semantics. Only after that prefix lands should the queue phases
rely on those surfaces.

The queue itself is intentionally scoped:

- separate service from authority;
- top-level `loom.queue` package ownership;
- SQLite as the built-in queue repository;
- whole-run queue items only;
- one FIFO queue per pool in the first version;
- managed local capacity and delegated downstream capacity;
- local and SLURM built-in adapters only;
- Python-first control surface, thin operational CLI later;
- queue state separate from authority lifecycle truth, joined only in read
  models.

## Planning Readiness

- Source planning notes:
  `docs/implementation-plans/roadmap-v11-planning-notes.md`
- Functionality and behavior baseline:
  complete; the notes lock whole-run queueing, separate queue service
  boundaries, managed plus delegated capacity, local plus SLURM adapters,
  strict cancellation/status truth, explicit-path queue config loading, and
  daemon-first controller behavior.
- Design-safety review:
  passed on 2026-05-13 by specialist design-safety review plus local
  confirmation. No design-safety blocker remains open in the planning notes.
- Examples and validation strategy:
  complete; managed local dispatch, delegated SLURM dispatch, foreground drain,
  accurate cancellation reporting, and snapshot-drift reporting are mapped to
  concrete validation obligations.
- Phase shaping:
  complete; four `v10-post` phases plus five main `v11` phases are already
  shaped and ordered in the planning notes.
- Implementation readiness blockers:
  none in the planning notes. The remaining workflow gates are this plan's own
  quality gate and the explicit `v10-post -> v11` transition checkpoint before
  main queue execution starts.
- Accepted risks and revisit triggers:
  delegated SLURM still relies on pre-staged/shared-workspace assumptions until
  later run-bundle work; SQLite is the first workspace-scoped durability
  default and may need a later broker-backed path; retries, fairness, and
  multi-queue policy remain deferred until later roadmap work proves the need.

## Locked Prerequisite Contract

The planning notes require the `v10-post` prerequisite contract to remain a
first-class part of the implementation plan rather than collapsing into phase
bullets alone.

`v10-post` traceability to preserve:

| ID | Locked contract | Why main queue work depends on it | Owning phase |
| --- | --- | --- | --- |
| `V10P-1` | Live authority readiness gates all online mutation; registry is a hint only; supervisor workspace-default behavior stays explicit. | Queue lifecycle and later co-management hooks must build on live authority entrypoints rather than stale registry state. | Phase 1 |
| `V10P-2` | Runtime, worker, continuation, and live SLURM mutation paths fail closed; deferred finalization remains explicit compatibility only. | Queue launch, cancellation, and delegated observation must assume strict online mutation semantics instead of best-effort fallback. | Phase 2 |
| `V10P-3` | Diagnostics, coordination, and admission semantics distinguish authoritative/local/deferred or offline state and keep coordination mutation authority-owned. | Queue read models and managed pools depend on explicit source labeling plus stable admission and lease semantics. | Phase 3 |
| `V10P-4` | Offline import remains historical-only with strict collision rejection and fenced terminal writes. | Queue recovery and later reliability work must not treat imported offline attempts as resumable live work. | Phase 4 |

`v10-post` design decisions to preserve:

| ID | Decision | Selected approach | Main queue implication |
| --- | --- | --- | --- |
| `V10PD-1` | Runtime mutation truth | Authority is the only mutation truth; local materialization is read-only fallback and diagnostics only. | Queue joins authority truth; it never invents a second lifecycle writer. |
| `V10PD-2` | Strict live SLURM and deferred finalization | Strict live SLURM requires direct authority reachability; deferred finalization is compatibility-only, not the normal path. | Delegated SLURM queueing must assume strict live-authority behavior by default. |
| `V10PD-3` | Coordination and admission ownership | Coordination mutation stays authority-owned; admission stays fail-fast by default with explicit bounded wait. | Managed pools may use read/reconcile plus lease/admission contracts without becoming a second coordination owner. |
| `V10PD-4` | Offline import and mutation safety | Offline import is historical-only with strict collision rejection and same-attempt fenced terminal writes. | Queue recovery and later reliability work must not treat imported attempts as active resumable work. |

Verified queue-facing seams to keep explicit:

- `create_authority_client(...)` in
  `src/loom/pipeline/stores/authority_factory.py`
- authority coordination routes in
  `src/loom/pipeline/stores/authority_client.py`
- `WorkspaceCoordinationStore.acquire_resource_lease(...)` and
  `WorkspaceCoordinationStore.scan_recovery(...)` in
  `src/loom/pipeline/stores/coordination.py`
- `acquire_resource_admission(...)` and `ResourceAdmissionRequest` in
  `src/loom/pipeline/execution/resource_admission.py`
- `PipelineRunner._acquire_stage_resource_admission(...)` in
  `src/loom/pipeline/execution/runner.py`

Required non-mutating authority limit read/reconcile contract:

- Before Phase 7, queue code must be able to read current authority-managed
  named resource limits for a managed pool and compare them against the queue
  pool's desired configuration without creating, updating, or deleting limits.
- The surface must return machine-readable success, mismatch, missing-limit, or
  unavailable-authority outcomes so queue preflight and dispatch can fail
  clearly before launch.
- Queue phases must not target
  `WorkspaceCoordinationStore.set_resource_limit(...)` or any equivalent
  authority-side mutation shortcut unless a later roadmap explicitly redesigns
  provisioning ownership.

## Desired Outcome

When all phases are complete:

- authority resolution, supervisor lifecycle, strict live runtime behavior,
  source labeling, coordination ownership, admission semantics, and historical
  import semantics are frozen by the `v10-post` prefix;
- Loom has a top-level `loom.queue` package with versioned queue models,
  repository contracts, a built-in SQLite repository, service/client/controller
  boundaries, and queue-owned run identity semantics;
- queue items are durable, whole-run records with immutable `queue_item_id`,
  persisted queue-owned `run_uri`, enqueue-time normalized launch contracts,
  and explicit `dispatch_attempt` semantics;
- queue policy remains separate from authority truth, and queue code reaches
  authority only through public authority-service APIs;
- managed pools validate against pre-provisioned authority resource limits via
  a non-mutating read/reconcile surface and use authority-backed leases at
  dispatch time;
- delegated SLURM pools submit, observe, and cancel through adapter-backed
  external handles without holding Loom resource leases by default;
- daemon/service mode is the primary operational path, while foreground drain
  remains a supported compatibility mode;
- status, cancellation, diagnostics, docs, and preflight surfaces explain the
  ownership split between queue state, authority run state, and delegated
  scheduler state clearly.

## Non-Goals

- Per-stage or DAG-level global scheduling.
- Multiple queues per pool, priorities, fair sharing, borrowing, preemption,
  or quota sharing.
- Automatic retries.
- Generic SSH launch or SLURM-over-SSH in the first version.
- Run-bundle transport, file synchronization, remote artifact stores, or
  payload shipping.
- External broker-backed queue services, hosted multi-tenant queue services,
  or site-wide orchestration.
- Queue mutation of authority private storage or authority-owned resource
  limits.
- Queue state becoming authoritative run lifecycle truth.
- Bulk CLI submission as the primary first-version queue interface.

## Constraints

- Keep `loom` domain-neutral.
- Preserve source-tree and import boundaries from `docs/structure.md`.
- Treat authored configs as trusted project code.
- Do not introduce heavyweight runtime dependencies without an explicit design
  reason recorded in a later refinement pass or phase artifact.
- Keep queue persistence private and versioned; the compatibility surface is
  queue models, service/client contracts, adapter contracts, and read models.
- Queue code may depend on public authority-service clients and coordination
  ports only; it must never open private authority storage.
- Queue code must keep authority truth, queue policy, and adapter execution
  ownership separate.
- Managed pools must validate against pre-provisioned authority resource limits
  through a non-mutating read/reconcile surface; queue phases must not target
  `WorkspaceCoordinationStore.set_resource_limit(...)`.
- Daemon/service mode is the primary guarantee path. Foreground drain remains a
  supported compatibility mode and may exit delegated work only after durable
  delegated handoff is persisted and observed once.
- The v11 scheduler-selection seam must remain internal/private in the first
  version even though persisted queue fields should remain future-compatible.
- Default validation must remain local and deterministic. Real SLURM coverage
  stays opt-in.
- Before each phase PR is prepared, run `make validate-pr` and
  `make test-summary`, or record why either command could not run.

## Design Principles

- **Harden prerequisites before depending on them.** Queue work must build on
  the tightened `v10-post` authority/runtime contracts, not on pre-hardening
  assumptions.
- **Queue policy is not authority truth.** Authority owns run lifecycle and
  coordination mutation; queue owns scheduling, dispatch, and queue-local
  durability.
- **Persist intent before launch.** Enqueue-time snapshots, queue-owned run
  identity, and explicit dispatch attempts are the reproducibility and recovery
  root.
- **Fail closed before dispatch.** Missing authority facts, resource-limit
  mismatches, snapshot drift, or unverifiable cancellation outcomes must be
  explicit diagnostics, not silent fallback behavior.
- **Make capacity ownership explicit.** Managed pools use Loom-owned admission
  and leases; delegated pools let downstream schedulers own pending/running
  capacity.
- **Daemon-first, compatibility second.** The long-running service path is the
  strongest-trust operational mode; foreground drain is supported but narrower.
- **Keep extension seams private until proven.** Adapter and scheduler seams
  should exist, but v11 should not promise a public scheduler-plugin contract.
- **Use existing Loom primitives where they fit.** Reuse authority clients,
  coordination, admission, and SLURM command boundaries instead of creating
  parallel ownership systems.

## Key Design Choices

- Draft and execute one combined `v10-post -> v11` implementation workflow,
  rather than separate prerequisite and queue implementation plans.
- Keep `v10-post` as a namespaced prerequisite tranche inside the v11 plan.
- Start queue code under top-level `loom.queue`.
- Keep queue service separate from authority and route queue-to-authority access
  only through public authority-service APIs.
- Use SQLite for the built-in queue repository.
- Limit v11 scheduling units to whole runs.
- Keep one FIFO queue per pool in v11, but route selection through an
  internal/private scheduler-selection seam.
- Support both managed and delegated capacity modes.
- Ship local and SLURM adapters only; defer generic SSH and SLURM-over-SSH.
- Persist a normalized launch contract at enqueue time.
- Give each queue item an immutable `queue_item_id`, a persisted queue-owned
  `run_uri`, and a `dispatch_attempt` that changes only on explicit
  requeue/resubmit.
- Keep managed-pool limit ownership validation-only in the first version.
- Keep queue state, authority run state, and delegated scheduler state separate
  and join them only in read models.
- Use explicit-path, versioned YAML queue config loading with a small direct
  loader and optional `loom[config]` composition for complex authored configs.
- Make daemon/service mode primary and keep foreground drain as a supported
  compatibility mode.

## Conflicts And Tradeoffs

- **One combined plan vs. separate prerequisite and queue plans:** the combined
  plan preserves the true dependency chain and stacked workflow, but it makes
  the artifact broader. The plan offsets that breadth by keeping the
  `v10-post` prefix explicitly namespaced and reviewable.
- **Top-level `loom.queue` vs. narrower `loom.pipeline.queue`:** the top-level
  package gives the queue room to grow into its own public surface, but it
  raises the bar for import-boundary discipline from the start.
- **SQLite-first repository vs. future scale:** SQLite is the right built-in
  workspace default, but it is not a promise that the first design also solves
  future distributed-controller throughput.
- **Daemon-first guarantees vs. foreground compatibility:** daemon/service mode
  gives stronger long-running guarantees, while foreground drain exists for
  restricted environments and accepts a narrower delegated-observation
  contract.
- **Strict truth reporting vs. convenience:** explicit `cancel_unknown`,
  missing-authority diagnostics, and snapshot-drift failures are slightly less
  convenient than optimistic success, but they preserve operator trust.
- **Explicit config loading vs. discovery convenience:** explicit-path loading
  avoids hidden behavior now, at the cost of more typing and less implicit
  project convention.
- **Private scheduler seam vs. extensibility pressure:** keeping the
  scheduler-selection seam internal avoids over-promising a policy plugin API
  too early, but phase design still needs to preserve future-compatible record
  and selector inputs.

## Maintainability Assessment

This plan is maintainable if it preserves a small number of hard boundaries:

- `v10-post` hardens existing authority/runtime behavior without mixing queue
  concerns into the prerequisite work.
- `loom.queue` owns queue models, repositories, service/client/controller
  boundaries, adapters, and queue docs.
- `loom.authority` stays responsible for authority truth and optional
  co-management hooks only, not scheduler policy.
- queue models and adapter contracts remain stable, typed, and framework-light;
  SQLite details stay private.
- docs and preflight surfaces explain ownership splits clearly enough that
  future contributors do not re-collapse queue and authority truth.

The highest maintainability risks are queue-policy leakage into authority,
over-broad supervisor/CLI hooks, SQLite schema leakage, and accidental
reintroduction of SSH or multi-queue policy through phase creep.

## Extensibility Assessment

This plan should leave room for:

- future SSH and SLURM-over-SSH adapters;
- future run-bundle transport replacing pre-staged/shared-workspace
  assumptions;
- richer scheduler policy such as priorities, fairness, or resource-dependent
  arbitration;
- future broker-backed or hosted queue repositories;
- richer queue read models, reconciliation, and reliability tooling.

The primary extension mechanisms are stable queue records, queue-owned run
identity, adapter contracts, normalized enqueue-time launch contracts, and a
private scheduler-selection seam. v11 should not expose more extension surface
than it can validate.

## Technical Debt Ledger

| Debt | Accepted For v11 Because | Revisit Trigger |
| --- | --- | --- |
| SQLite is the built-in queue repository | It satisfies the first workspace-scoped durability need without adding broker dependencies | Write contention, multiple controllers, or site-wide queue usage outgrow SQLite |
| One FIFO queue per pool | It is the smallest useful queue shape and keeps first-version arbitration reviewable | Users need priorities, fairness, multi-queue routing, or resource-dependent policy |
| No automatic retries | Retry policy belongs to later reliability work and would broaden queue semantics substantially | Users need bounded retry budgets for launch failures or failed runs |
| No generic SSH or SLURM-over-SSH | It avoids remote-wrapper and workspace-transport complexity before local and SLURM semantics are proven | Non-SLURM remote dispatch becomes a real user need or bundle transport lands |
| Delegated execution still relies on pre-staged/shared workspaces | Run-bundle transport is intentionally deferred and adapter evidence is enough for the first version | Remote reproducibility requires shipped bundles rather than local/shared assumptions |
| Foreground drain remains weaker than daemon/service mode for delegated observation | Compatibility mode is needed for restricted environments, but the daemon path is the stronger guarantee path | Operators require daemon-level guarantees in restricted environments too |
| Queue config uses explicit-path loading with a small direct loader plus optional `loom[config]` composition | It preserves dependency-light queue-core imports and avoids implicit discovery | Users repeatedly need a standard project-default discovery convention or more config composition |
| The scheduler-selection seam is private in v11 | Public scheduler policy contracts would be premature before richer policy work exists | A later scheduler roadmap needs a stable public policy extension API |

## Validation Strategy

The plan must preserve the examples and validation obligations confirmed in the
planning notes, not just general "add tests" language.

| Example or behavior | Primary owning phases | Validation obligation |
| --- | --- | --- |
| Managed local GPU pool | Phases 7 and 9 | Prove managed pools respect authority-backed limits and leases, queue the second run, and surface clear status plus preflight diagnostics. |
| Delegated SLURM queue | Phases 8 and 9 | Prove delegated dispatch persists external handles, does not hold Loom leases for pending SLURM work by default, and reports scheduler-backed status/cancel results. |
| Foreground drain compatibility behavior | Phases 6, 7, 8, and 9 | Prove local active work stays observed to terminal or explicit unknown state, while delegated foreground exit requires durable handoff plus one downstream status read. |
| Accurate cancellation reporting | Phases 7, 8, and 9 | Prove cancel never claims success without adapter evidence and uses explicit unknown outcomes when proof is unavailable. |
| Snapshot drift and delegated-launch verification reporting | Phases 5, 7, 8, and 9 | Persist launch-contract drift-detection fields, fail local dispatch on proven drift, and report which delegated launch assumptions were or were not proven by the adapter. |

## Plan Quality Gate

- Status: passed on 2026-05-13
- Review pass: local review on 2026-05-13 found two blocking gaps:
  missing carried-forward `v10-post` traceability/design-decision sections, and
  missing explicit example-to-validation ownership for snapshot drift and
  delegated verification.
- Refinement pass: complete on 2026-05-13; added `Locked Prerequisite
  Contract`, `Validation Strategy`, explicit non-mutating limit
  read/reconcile expectations, and clearer phase ownership for launch-contract
  drift and delegated verification behavior.
- Confirmation review: complete on 2026-05-13; no blocking findings remain.
- Planning-readiness dependencies:
  - `docs/implementation-plans/roadmap-v11-planning-notes.md` records readiness
    `pass`
  - design-safety review is already complete and passed
  - no unresolved `blocked` or `needs discussion` planning decisions remain
  - examples, validation strategy, and phase shaping are specific enough to
    draft phases
- Blockers:
  - No blocker remains for `v10-post` Phase 1 start.
  - Main queue phases remain gated on the explicit `v10-post -> v11`
    transition checkpoint after Phase 4.
  - If the checkpoint shows the prerequisite prefix changed a queue-facing
    contract materially, refresh this plan before starting Phase 5.

Before any phase execution begins, this plan must receive a plan-quality review,
typically via `loom_plan_reviewer`, covering maintainability, extensibility,
future compatibility, conflicting design choices, accepted technical debt, test
strategy, planning readiness, and reviewability.

This local gate pass satisfies the artifact-readiness step for drafting and
phase selection. If a later review or implementation change materially alters
the prerequisite contract or main queue scope, rerun the gate before starting a
dependent phase.

## Phased Implementation

### Phase 1: `v10-post` Authority Resolution And Supervisor Hardening

- Status: merged
- Branch: `codex/authority-resolution-hardening`
- PR: https://github.com/samcantrill/loom/pull/137

**Goal**

Finalize strict authority resolution, registry semantics, and explicit
workspace-default supervisor state-directory behavior before queue work depends
on those surfaces.

**Scope**

- Enforce mandatory live readiness checks before online mutation.
- Keep registry records as bootstrap hints only, never authority truth.
- Preserve one-authority-per-workspace assumptions for the current contract.
- Land the explicit `--use-workspace-default` supervisor surface resolving to
  `<workspace-root>/.loom/authority/service`.
- Make restart generation changes invalidate stale clients immediately.

**Out Of Scope**

- Queue service or queue models.
- Multi-authority workspace support.
- Hidden implicit supervisor defaults for `start`.

**Acceptance Criteria**

- Mutating paths reject stale registry data or missing live readiness.
- Supervisor commands expose a consistent explicit workspace-default
  state-directory surface.
- Restart generation changes invalidate stale clients immediately.

**Test Expectations**

- Package: not required.
- Unit: authority resolution and registry validation coverage.
- Contract: resolver outcome and stale-generation coverage where appropriate.
- Integration: supervisor lifecycle and workspace-default path coverage.
- E2E: not required.
- Opt-in: not required.

**Design Impact**

This phase locks the authority entrypoint semantics that every later queue and
controller phase will rely on.

**Future Compatibility**

The resolution contracts should stay transport-neutral and should not assume
localhost-specific behavior beyond the current supervisor implementation.

**Alternatives Rejected**

- Treating registry entries as authority truth.
- Hidden implicit supervisor defaults for normal startup.
- Delaying strict readiness enforcement until queue phases.

**Debt Introduced**

Some runtime callers may still rely on pre-hardening behavior until later
`v10-post` phases land.

**Reviewability**

Review should focus on resolver correctness, stale-client invalidation, and the
explicitness of supervisor surfaces.

**Notes**

- This phase is the semantic root for the later queue service co-management
  hooks.

**Completion Summary**

- Merged on 2026-05-13 via squash merge commit
  `ffa980cdcb064d7c2481f199da5e42e4169029ce`.
- Implemented explicit workspace-default supervisor state-directory handling via
  `--use-workspace-default`, resolving to
  `<workspace-root>/.loom/authority/service`, while keeping normal startup
  explicit.
- Added a live duplicate-authority guard that treats registry records as
  bootstrap hints and confirms supervisor state, process liveness, and readiness
  before rejecting a second authority for the same workspace.
- Preserved restart generation observability and strict resolver coverage.
- Resolved full-gate validation blockers for invalid offline-manifest CLI
  classification and offline-import replay-event assertions.
- Validation: `make validate-pr` passed; `make test-summary` passed with 1821
  passed, 12 skipped, and 1402 deselected. GitHub CI `checks` passed before
  merge.
- Follow-up: continue with Phase 2 from updated `develop`.

### Phase 2: `v10-post` Strict Runtime, Worker, And SLURM Live Paths

- Status: pending
- Branch: `codex/strict-runtime-live-paths`
- PR: pending

**Goal**

Tighten runtime mutation paths so local runners, workers, continuations, and
live SLURM jobs all preserve the same fail-closed authority contract.

**Scope**

- Remove best-effort local resume-by-inspection from normal live paths.
- Fail worker and continuation validation before user code when authority facts
  are stale or missing.
- Keep recovery controller-driven rather than worker-invented.
- Require direct authority reachability for strict live SLURM commits.
- Keep deferred finalization behind explicit compatibility acknowledgement only.
- Stop further stage launches immediately when authority is lost.

**Out Of Scope**

- Repair-by-inspection workflows.
- Partial-attempt resume.
- Queue dispatch behavior.

**Acceptance Criteria**

- No user stage code starts with stale or missing authority lease or fencing
  facts.
- Live SLURM fails closed if authority is unreachable at worker start or commit
  time.
- No runtime path silently falls back to deferred finalization.

**Test Expectations**

- Package: not required.
- Unit: worker, continuation, and live-path error classification coverage.
- Contract: stage-worker and continuation contract updates where needed.
- Integration: runner, worker, continuation, and live SLURM lifecycle tests.
- E2E: targeted CLI/behavior coverage only if current CLI surfaces are touched.
- Opt-in: real SLURM not required.

**Design Impact**

This phase freezes the online mutation contract that queue launch, cancellation,
and observation later assume.

**Future Compatibility**

Later repair workflows can still exist, but they must remain explicit and
separate from the normal live runtime path.

**Alternatives Rejected**

- Keeping deferred finalization as a normal live-path fallback.
- Allowing worker start before authority validation is complete.
- Queue phases compensating for weaker runtime truth later.

**Debt Introduced**

Restricted topologies may still depend on explicit compatibility paths until a
later roadmap designs stronger alternatives.

**Reviewability**

Review should focus on fail-closed runtime behavior and whether any fallback
path still silently mutates lifecycle truth.

**Notes**

- Queue delegated SLURM later depends on this phase keeping deferred
  finalization out of the normal live submission path.

**Completion Summary**

- Pending.

### Phase 3: `v10-post` Diagnostics, Coordination, And Resource Admission Tightening

- Status: pending
- Branch: `codex/diagnostics-admission-tightening`
- PR: pending

**Goal**

Freeze the read-path, coordination, and resource-admission semantics that main
queue status and managed resource pools will assume.

**Scope**

- Live-first read-only diagnostics with explicit authoritative/local/deferred
  or offline source labeling.
- Distinct deferred-finalization and offline-evidence labeling.
- Authority-owned coordination mutation only.
- Fail-fast admission by default with explicit bounded-wait support and
  machine-readable outcomes.

**Out Of Scope**

- Queue status/read models.
- Worker self-acquisition of coordination or resource leases.
- New scheduler policy.

**Acceptance Criteria**

- Read-only surfaces clearly distinguish authoritative, local, deferred, and
  offline sources.
- Resource admission preserves `admitted`, `rejected`, and `blocked` outcomes
  with machine-readable reasons.
- Authority restart or lease loss fails and requires controller reacquisition.

**Test Expectations**

- Package: not required.
- Unit: source-label and admission outcome coverage.
- Contract: workspace coordination contract updates where needed.
- Integration: diagnostics, coordination, and resource-admission coverage.
- E2E: not required.
- Opt-in: not required.

**Design Impact**

This phase freezes the exact read and admission semantics that the queue will
join against, so ambiguity here would spread into managed-pool behavior.

**Future Compatibility**

Later richer scheduling can build on stable admission outcomes without changing
the basic authority-owned coordination boundary.

**Alternatives Rejected**

- Queue-owned coordination mutation.
- Hidden indefinite waits.
- Read-only surfaces that flatten source ownership.

**Debt Introduced**

The phase does not yet add richer scheduler policy or reconciliation behavior.

**Reviewability**

Review should focus on source-label clarity, authority ownership, and admission
outcome completeness.

**Notes**

- The later managed-pool phase depends on a non-mutating authority
  read/reconcile surface for resource-limit validation.

**Completion Summary**

- Pending.

### Phase 4: `v10-post` Offline Import, Mutation Safety, And Deferred Repair Contracts

- Status: pending
- Branch: `codex/offline-import-safety-hardening`
- PR: pending

**Goal**

Lock offline import and terminal mutation semantics so later queue and recovery
features build on strict historical truth instead of soft repair behavior.

**Scope**

- Keep offline-first explicit.
- Require complete manifests and terminal run state for import.
- Keep collision handling strict reject-by-default.
- Preserve imported provenance when safe.
- Keep successful stage completion atomic and fence-guarded.
- Keep imported offline attempts historical rather than resumable live work.

**Out Of Scope**

- Merge, overwrite, or fork-style import policies.
- Normal-path repair or inspection-based resume.
- Partial-attempt resume.

**Acceptance Criteria**

- Incomplete, non-terminal, or colliding offline imports fail explicitly.
- Imported runs preserve offline provenance while becoming authoritative
  historical truth.
- Terminal success cannot be recorded without the same-attempt fenced output
  commit.

**Test Expectations**

- Package: not required.
- Unit: import rejection and mutation-safety coverage.
- Contract: offline import contract updates where needed.
- Integration: offline evidence/import and lifecycle repository tests.
- E2E: not required.
- Opt-in: not required.

**Design Impact**

This phase prevents later queue recovery or reliability work from quietly
treating imported offline attempts as active live attempts.

**Future Compatibility**

Later repair/import workflows can add new explicit policies, but v11 should not
inherit ambiguous semantics from historical import behavior.

**Alternatives Rejected**

- Soft collision handling.
- Import-as-live-resume behavior.
- Relaxed same-attempt success fencing.

**Debt Introduced**

Import remains deliberately strict and may reject historical cases a later
repair workflow could treat separately.

**Reviewability**

Review should focus on historical-vs-live truth separation and terminal safety.

**Notes**

- Completion of this phase triggers the explicit transition checkpoint before
  any main queue phase begins.

**Completion Summary**

- Pending.

### Transition Checkpoint After Phase 4

Before `v11` queue implementation begins:

- compare the actual `v10-post` authority, supervisor, SLURM, diagnostics,
  resource-admission, and offline-import seams against the assumptions carried
  in this plan;
- refresh this plan and any dependent phase artifacts if the prefix changed any
  queue-facing contract materially;
- record the exact changed seams before Phase 5 starts.

### Phase 5: `v11` Queue Records And SQLite Repository

- Status: pending
- Branch: `codex/queue-records-sqlite-repository`
- PR: pending

**Goal**

Define versioned queue pool, queue, run intent, item, dispatch handle,
cancellation, and audit records plus a SQLite-backed queue repository.

**Scope**

- Add `loom.queue` record and validation modules.
- Persist immutable `queue_item_id`, queue-owned `run_uri`, and
  `dispatch_attempt`.
- Persist normalized launch contracts, including drift-detection inputs and
  adapter-visible dispatch or verification evidence slots.
- Define queue schema versioning and repository operations.
- Add FIFO selection primitives for one queue per pool.
- Add the minimal internal/private scheduler-selection seam for future policy
  replacement.

**Out Of Scope**

- Real launch adapters.
- Authority resource leasing.
- Supervisor or CLI operations.

**Acceptance Criteria**

- Queue DB persists and recovers queue state across restart.
- Records are versioned and reject unsafe or unknown fields.
- Repository operations support enqueue, claim, dispatch-handle persistence,
  terminal completion, cancellation, and recovery scans.
- Launch-contract records preserve enough information for later phases to
  detect local drift and to report delegated verification evidence without
  redefining the queue item schema.

**Test Expectations**

- Package: `loom.queue` import-boundary coverage.
- Unit: model validation, serialization, schema-version, selector, and
  launch-contract drift or verification-field coverage.
- Contract: queue-record and repository-shape contract tests where useful.
- Integration: SQLite enqueue/claim/transition/restart recovery tests.
- E2E: not required.
- Opt-in: not required.

**Design Impact**

This phase defines the durable queue vocabulary and persistence contract that
every later service, controller, adapter, and docs surface will build on.

**Future Compatibility**

Persisted selector inputs and launch-contract fields should support later
policy, adapter, and bundle evolution without forcing a schema break.

**Alternatives Rejected**

- Storing queue state in authority tables.
- Unversioned queue records.
- Hard-coded FIFO selection with no later seam.

**Debt Introduced**

The first repository is SQLite-only and the scheduler-selection seam remains
private.

**Reviewability**

Review should focus on record ownership, idempotency semantics, schema
versioning, and repository recovery behavior.

**Notes**

- This phase should keep queue docs and queue package ownership aligned from the
  start.

**Completion Summary**

- Pending.

### Phase 6: `v11` Queue Service, Client, And Python Control Surface

- Status: pending
- Branch: `codex/queue-service-python-surface`
- PR: pending

**Goal**

Add queue service/client boundaries and a clean Python-first control surface
without merging queue policy into authority.

**Scope**

- Queue service process boundary and lifecycle semantics.
- Queue client methods for enqueue, inspect, cancel, and controller operations.
- Python controller entrypoints for daemon/service mode and foreground-drain
  compatibility mode.
- Explicit-path queue config loading with normalized trusted YAML parsing.
- Optional `loom[config]` composition path that still normalizes into the same
  queue-spec model.

**Out Of Scope**

- Real local or SLURM launch behavior beyond fakes.
- Bulk CLI submission.
- Managed resource dispatch.

**Acceptance Criteria**

- Queue can be configured, started, and controlled from Python against fake
  work.
- Foreground-drain compatibility mode works against fake work without
  orphaning locally managed claims.
- Queue code does not import or touch private authority repository modules.

**Test Expectations**

- Package: queue-to-authority import-boundary tests.
- Unit: service/client/controller API and loader normalization tests.
- Contract: queue config schema and Python API contract tests where useful.
- Integration: fake-controller and service lifecycle tests.
- E2E: not required.
- Opt-in: not required.

**Design Impact**

This phase defines the public queue control surface and the dependency boundary
between queue-core, config extras, and authority clients.

**Future Compatibility**

Python APIs and normalized config loading should remain transport-neutral so a
later CLI, SSH adapter, or bundle layer can reuse them directly.

**Alternatives Rejected**

- CLI-first queue definition and enqueueing.
- Implicit config discovery.
- Direct queue imports of private authority storage.

**Debt Introduced**

The first surface remains Python-first and keeps the CLI deliberately thin.

**Reviewability**

Review should focus on public API clarity, config-loader boundaries, and
authority import hygiene.

**Notes**

- Daemon/service mode is the primary guarantee path even though foreground drain
  is supported here for compatibility and tests.

**Completion Summary**

- Pending.

### Phase 7: `v11` Managed Resource Pools And Local Launcher

- Status: pending
- Branch: `codex/managed-pools-local-launcher`
- PR: pending

**Goal**

Connect queue dispatch to the post-`v10-post` authority-backed resource
limit/lease contracts and add a local launch adapter with accurate
status/cancel behavior.

**Scope**

- Managed resource dispatch mode.
- Non-mutating authority resource-limit read/reconcile behavior for queue pool
  validation.
- Authority-backed lease acquisition or release around local dispatch.
- Pre-dispatch local snapshot drift detection against the persisted launch
  contract.
- Local adapter process-group tracking, status observation, and cancellation.
- Queue plus authority joined read-model behavior for local active work.

**Out Of Scope**

- SLURM or SSH adapters.
- Automatic retries.
- Queue-side resource-limit mutation.

**Acceptance Criteria**

- Local queued runs respect configured resource limits and active limits.
- Queue validates configured managed-pool resource expectations against
  authority without mutating authority truth.
- Local dispatch fails with clear diagnostics when the persisted launch contract
  no longer matches the trusted local inputs required for launch.
- Cancellation works for pending and active local work.
- Foreground drain does not exit while locally managed work remains active
  unless it has recorded explicit unknown or recovery-needed state.

**Test Expectations**

- Package: import-boundary coverage where adapter modules touch execution
  helpers.
- Unit: local adapter lifecycle, cancellation, and snapshot-drift detection
  tests.
- Contract: managed-pool limit read/reconcile behavior where useful.
- Integration: service-backed resource integration and queue status tests.
- E2E: targeted public API or CLI status/cancel coverage if touched.
- Opt-in: not required.

**Design Impact**

This phase is where queue policy first touches live authority coordination and
active execution, so ownership mistakes here would be expensive to unwind.

**Future Compatibility**

Managed-pool behavior should preserve a clean seam for future richer scheduling
without changing the authority-owned lease model.

**Alternatives Rejected**

- Queue-side mutation of resource limits.
- Local launch without process-group tracking.
- Treating queue state as lifecycle truth for local runs.

**Debt Introduced**

The first managed-pool phase depends on a separate authority read/reconcile
surface rather than a broader provisioning contract.

**Reviewability**

Review should focus on authority ownership, local adapter correctness, and
cancel/status truth.

**Notes**

- This phase must name the exact v10 seams it uses after the transition
  checkpoint confirms them.

**Completion Summary**

- Pending.

### Phase 8: `v11` Delegated SLURM Dispatch

- Status: pending
- Branch: `codex/delegated-slurm-queue-dispatch`
- PR: pending

**Goal**

Add delegated SLURM dispatch using existing Loom SLURM command boundaries.

**Scope**

- Submit, status, and cancel through fakeable SLURM command runners.
- External job-id dispatch handles and delegated-hand-off persistence.
- At least one successful downstream status read before delegated foreground
  handoff can be treated as durable.
- Missing-authority-run diagnostics while an external handle is active.
- Delegated-launch verification reporting that records which required launch
  assumptions the adapter proved and which remain unproven until later
  bundle/transport work exists.
- Docs and read-model behavior explaining that Loom leases are not held for
  SLURM-pending work by default.

**Out Of Scope**

- Real cluster requirements in default tests.
- SLURM-over-SSH submit hosts.
- Job arrays, fairness policy, or controller-side DAG scheduling.

**Acceptance Criteria**

- Fake SLURM jobs can be submitted, inspected, and cancelled through queue
  status/cancel paths.
- Queue recovery reuses the same `run_uri` and external handle after partial
  delegated handoff.
- Delegated mode does not acquire Loom leases for SLURM-pending work by
  default.
- Delegated status and diagnostics report missing-authority conditions and
  adapter-proven or unproven launch checks without overstating remote
  equivalence.

**Test Expectations**

- Package: not required.
- Unit: SLURM adapter submit/status/cancel, durable-handoff, and delegated
  verification-reporting tests.
- Contract: delegated dispatch-handle and cancellation outcome tests where
  useful.
- Integration: fake command-runner controller and recovery tests.
- E2E: targeted public API or CLI status/cancel coverage if touched.
- Opt-in: real SLURM smoke.

**Design Impact**

This phase defines the first delegated-capacity path and the strongest recovery
stress for queue-owned run identity and adapter handoff semantics.

**Future Compatibility**

The adapter and dispatch-handle model should leave room for future SSH submit
hosts and bundle-backed delegated launch without changing queue-core identity
semantics.

**Alternatives Rejected**

- Holding Loom leases for delegated pending work.
- Requiring authority run visibility before delegated handoff can be persisted.
- Fresh run identity on controller recovery.

**Debt Introduced**

Delegated launch still depends on shared/pre-staged workspace assumptions until
bundle transport exists.

**Reviewability**

Review should focus on durable handoff, delegated capacity ownership, recovery,
and truthful cancellation/status behavior.

**Notes**

- This phase should continue to rely on existing SLURM command boundaries
  instead of inventing a second SLURM execution surface.

**Completion Summary**

- Pending.

### Phase 9: `v11` Operational UX, Minimal CLI Wrapper, Docs, And Hardening

- Status: pending
- Branch: `codex/queue-ops-cli-docs-hardening`
- PR: pending

**Goal**

Finalize queue status/cancel/daemon-service/foreground-drain operations,
examples, preflight checks, and queue-owned documentation.

**Scope**

- Thin operational CLI wrapper for queue service lifecycle, foreground drain,
  status, and cancel.
- Preflight diagnostics for queue service reachability, authority connection,
  resource-pool configuration, SLURM command availability, and delegated-launch
  workspace assumptions.
- Dedicated queue/workflow-scheduler docs with cross-links from
  `execution.md`, `runtime-resources.md`, `slurm.md`, `preflight.md`, and
  `cli.md`.
- Example docs for managed local resource queues and delegated SLURM queues.
- Final hardening for status rendering and operator-facing diagnostics.

**Out Of Scope**

- Bulk CLI submission.
- Priorities, fairness, retries, cross-run dependencies, or bundles.

**Acceptance Criteria**

- Users can follow docs to configure and operate a managed local queue and a
  delegated SLURM queue in deterministic or fakeable environments.
- CLI remains a thin operational wrapper over the Python service/client
  surface.
- Preflight and status outputs explain ownership and weaker delegated
  assumptions clearly.

**Test Expectations**

- Package: CLI import smoke where useful.
- Unit: preflight and status rendering coverage.
- Contract: not required.
- Integration: CLI/service status/cancel/foreground-drain tests.
- E2E: queue CLI smoke coverage in deterministic local environments.
- Opt-in: real SLURM or site-specific docs verification not required by
  default.

**Design Impact**

This phase fixes the public operator contract for the first queue version, so
sloppy wording here would reintroduce ambiguity the earlier phases intentionally
removed.

**Future Compatibility**

Docs and CLI wording should leave room for later SSH, bundle, and richer policy
work without claiming those capabilities now.

**Alternatives Rejected**

- Making the CLI the primary queue definition or enqueue surface.
- Folding queue docs into `execution.md` alone.
- Hiding delegated-assumption caveats from preflight and docs.

**Debt Introduced**

The first operational CLI is intentionally narrow and may need later expansion
once the queue behavior surface is proven stable.

**Reviewability**

Review should focus on operator clarity, doc routing, and whether CLI surfaces
stay thin rather than becoming a second orchestration layer.

**Notes**

- This phase should align docs ownership with top-level `loom.queue` package
  ownership.

**Completion Summary**

- Pending.

## Cross-Phase Review Notes

- Main queue phases must continue to cite the exact public authority seams they
  target after the transition checkpoint:
  `create_authority_client(...)`, authority coordination routes,
  `WorkspaceCoordinationStore.acquire_resource_lease(...)`,
  `WorkspaceCoordinationStore.scan_recovery(...)`,
  `acquire_resource_admission(...)`, and
  `PipelineRunner._acquire_stage_resource_admission(...)`.
- The managed-pool phase must not assume queue-owned resource-limit mutation.
  If the prerequisite prefix does not yet expose a sufficient non-mutating
  authority read/reconcile contract, that gap must be addressed explicitly
  before Phase 7 starts.
- Queue docs should be treated as a first-class feature-doc set owned alongside
  `loom.queue`, not as incidental notes added only at the end.
- Phase execution plans should preserve the namespaced `v10-post` and `v11`
  terminology even though this implementation plan uses a single sequential
  phase list.
- If the plan-quality review finds that any phase would force invention of
  public queue behavior not already recorded in the planning notes, the plan
  should be refined instead of allowing the phase plan to guess.
