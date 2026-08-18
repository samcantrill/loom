# Roadmap Stage 23-post Planning: Managed-Local Runtime Operations

Status: confirmed; implementation-plan quality gate passed
Roadmap stage: 23-post
Evidence tree: `/home/can134/work/active/loom` at `4c7059bcf4358da866700df416d068eaab62c80b`; relevant pre-existing dirty paths are `docs/roadmap.md`, `docs/roadmap/stage-24/**`, and `src/loom/queue/models.py`; broader unrelated dirty work was not used or changed
Planning route: expanded because the stage adds one public runtime surface and an explicit trust boundary for local-process crash recovery; the manager completed a removal-first review locally and did not use an optional spawned review
Current gate: planning workflow complete; Phase 1 not started
Blockers: none

This follows completed Stage 23 without replacing Stage 25 or reopening Stage
24 queue-selection policy.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence / functionality / design / validation / detailed plan / approval | Stage 23 source, tests, docs, and example were inspected. The confirmed plan adds one pool-bound runtime, preserves established authority/provider ownership, assigns causal validation, and has three linked phase plans. | None. | Begin Phase 1 through the roadmap implementation workflow. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| Stage 23 plan/spec | Construction, loop ownership, crash recovery, reattachment, and supervision remain downstream. | Accepted baseline. | all |
| Controller and local adapter | Cycles reconcile before fill and stop on degradation; process/provider state and renewal deadlines are in memory; foreign local work is not mutated. | Runtime, health, recovery. | FR-4 through FR-8 |
| Config, assignments, and preflight | Static inventory parses and amount two already leases two slots, but no config-to-runtime factory exists. | Factory and resources. | FR-2, FR-3, FR-10 |
| Status, example, and e2e | Status is persistence-first and live only for matching owner/session. The example mismatches `example-controller` and `controller-1`, and its test misses the fallback. | Truthful status and defect. | FR-1, FR-9, FR-11 |
| Roadmap and Stage 24 | Stage 23 status text is stale. Stage 24 owns candidate selection, not managed-local process maintenance. | Docs and compatibility. | FR-11, FR-12 |

- User-visible outcome: a downstream project can construct and operate one
  managed-local queue pool with one small Python API instead of manually
  assembling a service, provider, adapter, controller, timing loop, status
  joins, and shutdown behavior.
- Existing end-to-end path: authored queue spec -> `QueueService` ->
  `QueueController.run_cycle()` -> `LocalQueueDispatchAdapter` -> logical
  authority admission -> concrete provider assignment -> local process and
  logs -> renewal/reconciliation -> terminal state -> lease release -> refill.
- Included scope: one pool, factory, read-only validation, automatic timing,
  health, drain/cancel, recovery gate/resolution, truthful status, and examples.
- Non-goals: daemon/CLI service, reattachment/PID killing, discovery, distributed
  active limits, provisioning, generic scheduling, or weighted core slots.
- Consumers/failures: the canonical example, requested downstream integration,
  its owner mismatch, and restart without live process/provider state.
- Public or durable surfaces affected: a public
  `loom.queue.managed_local.ManagedLocalQueueRuntime`, its in-process state and
  status records, and an explicit recovery-resolution method. Existing queue
  config, queue-item records, assignment evidence schema, SQLite schema, and
  CLI status envelope remain unchanged.

## Minimum Useful Change

- Smallest useful behavior: bind one runtime to one configured managed pool,
  derive one owner ID from `spec.controller.owner_id`, build the established
  objects once, keep them alive, call controller cycles before their reported
  maintenance time, stop refill while degraded or recovery-blocked, and shut
  down without releasing resources before process exit.
- Reuse `QueueService`, `QueueController`, the local adapter, static provider,
  reconciliation, and pool status. A new facade is needed because none owns
  identity, object lifetime, timing, health, and shutdown together; copying the
  example already produced an owner defect.
- Explicitly deferred behavior: surviving and reattaching to local work after
  controller death. That requires durable supervisor process identity and
  provider recovery tokens, which Stage 23 deliberately does not persist.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | One configured owner ID is authoritative for the runtime, controller, local adapter, claims, and same-session status matching. | No independent owner override at lower construction layers. | `QueueControllerSpec.owner_id`. | Construction and live-status assertions. | locked |
| FR-2 | `ManagedLocalQueueRuntime.from_spec(...)` binds one selected managed pool and constructs one service, local adapter, controller, log root, and static provider when authored assignments exist. | No multi-pool runtime, daemon, registry, or CLI factory. | Existing public queue components. | Unit and integration construction tests. | locked |
| FR-3 | Startup revalidates the mutable external boundary: coordination capabilities, selected logical limits, authored static-slot limits, selected pool mode, and built-in process support. It never creates or changes limits. | A custom provider owns its provider-specific readiness checks. | Existing reconciliation/preflight helpers. | Mismatch and no-mutation tests. | locked |
| FR-4 | `serve(...)` owns the maintenance loop and runs reconciliation no later than the earlier of its bounded poll interval or the controller's `next_maintenance_at`. | Advanced direct controller use remains possible and retains caller-owned timing. | Stage 23 cycle result. | Deterministic clock/wait and renewal tests. | locked |
| FR-5 | A degraded current-session item continues to stop refill until a complete later reconciliation is healthy. Whole-cycle exceptions also leave the runtime degraded and retry reconciliation without a separate dispatch path. | No `ignore_degraded` or optimistic refill switch. | Existing controller fail-closed behavior. | Degrade/recover/refill causal test. | locked |
| FR-6 | On startup, any pre-existing active item in the selected pool puts the runtime in `RECOVERY_REQUIRED` and prevents new claims. Active work created by this runtime remains eligible for same-session reconciliation. | No PID inference, foreign mutation, or simultaneous-leader claim. | Recovery scan and session identity. | Restart and cold-race-safe tests. | locked |
| FR-7 | Normal stop defaults to drain: stop claiming, continue maintenance and reconciliation, then stop the service after owned work is terminal. An explicit cancel mode terminates current-session work and still waits for exit and lease cleanup. A timeout never forces lease release. | No guarantee that an unkillable process exits before an external supervisor timeout. | Reconciliation-only controller path and existing cancellation. | Drain, cancel, pending-exit, and timeout tests. | locked |
| FR-8 | `resolve_recovery_unknown(...)` may resolve one exact foreign item ID per call only after an operator explicitly confirms the previous process group is stopped. It marks that attempt `UNKNOWN` with safe audit evidence and never releases or renews foreign leases. | No automatic or batch recovery, requeue, success/failure inference, or lease takeover. | Guarded repository transitions. | Confirmation, stale-snapshot, exact-target, and no-release tests. | locked |
| FR-9 | Runtime status separates live in-process health from persisted pool evidence and states that hardware/lease liveness was not observed. Same-session process status remains explicitly labelled; persisted expiry evidence is never described as current availability. | No new authority lease-read API or hardware probe. | Existing `QueuePoolStatus`. | Plain-data shape and wording tests. | locked |
| FR-10 | Documentation and validated examples show the normal two-slot request (`resources={"accelerator": 2}`) and a custom indivisible-bundle provider that acquires the same underlying physical member keys used by every other allocator. | No weighted built-in slot or synthetic bundle key that can overlap separate member allocation. | Existing provider protocol and leases. | Two-slot integration plus acquire-all/rollback/release provider tests. | locked |
| FR-11 | Fix the example owner mismatch, assert `same_session_live`, correct stale Stage 23 roadmap status, and document POSIX/supervisor/recovery expectations. | No broad historical-plan rewrite. | Existing example/e2e/docs. | Example rerun and docs review. | locked |
| FR-12 | Fake, delegated SLURM, direct controller, schema-v1, CPU-only, and Stage 24 selection behavior remain compatible. The runtime calls the controller's public cycle and owns no candidate policy. | Managed-local runtime is opt-in. | Existing contracts. | Focused compatibility and import-boundary tests. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1, FR-2 | Runtime granularity | Use one runtime per managed pool and derive the owner once from the spec. | Multiple pools need multiple runtime objects and explicit deployment ownership. | repo-resolved |
| FQ-2 | FR-2, FR-10 | Assignment construction | Auto-build authored static assignments; accept one explicit custom provider only when the selected pool has no authored provider. | Rejects ambiguous override layering. | repo-resolved |
| FQ-3 | FR-4, FR-5 | Recommended operation | Make `serve()` the documented path; keep `run_cycle()` as an advanced/test seam with its maintenance result visible. | Long-lived use requires a foreground process or external supervisor. | repo-resolved |
| FQ-4 | FR-6, FR-8 | Crash policy | Gate on foreign work and require explicit process-exit attestation before marking it unknown. | Recovery needs an operator/supervisor decision; no transparent restart. | repo-resolved |
| FQ-5 | FR-7 | Stop policy | Default to drain; allow explicit cancel and a bounded caller-selected timeout. Never release on timeout. | Drain can exceed deployment stop time. | repo-resolved |
| FQ-6 | FR-9 | Truth wording | Report persisted queue evidence, same-session runtime observation, and unobserved hardware as different scopes. | Status is more explicit but cannot claim device health. | repo-resolved |
| FQ-7 | FR-10 | Two-device model | Recommend amount two over two physical slots; use a custom provider only for a genuinely indivisible topology bundle. | Downstream topology code remains downstream. | repo-resolved |

## Behavior Baseline

- Default: an opt-in pool-bound `serve()` validates, recovery-gates,
  reconcile/fills, wakes for maintenance, and drains on stop. States are
  `READY`, `DEGRADED`, `RECOVERY_REQUIRED`, `DRAINING`, `CANCELLING`, and
  `STOPPED`.
- Fail closed on mismatch, degradation, foreign work, unsupported built-in
  process platform, or shutdown timeout. Durable queue/audit/log/assignment
  evidence remains; runtime/process/provider state is in memory. Reattachment,
  orphan killing, lease takeover, telemetry, and leadership remain deferred.

## Minimum Design

- Modules and ownership:
  - `loom.queue.managed_local`: construction, timing, health, recovery gate,
    shutdown.
  - Controller: reconcile/fill order, counts, budgets, candidate policy, and a
    minimal reconciliation-only/current-session seam.
  - Local adapter/provider: process/log/lease cleanup and concrete placement.
  - Authority/repository: exclusivity/fencing and guarded queue/audit facts.
  - External supervisor: process restart and whole-tree containment.
- Data and control flow:

  ```text
  spec + store + pool
          |
          v
  ManagedLocalQueueRuntime --one owner--> service + provider + adapter + controller
          |
          +--> startup validation / foreign-work gate
          +--> reconcile -> healthy? -> fill
          +--> wait until poll or maintenance deadline
          +--> drain/cancel -> observe exit -> release -> stop
  ```

- Fixed public, durable, trust-boundary, and cross-phase contracts:
  `ManagedLocalQueueRuntime.from_spec`, `start`, `run_cycle`, `serve`, `status`,
  and `resolve_recovery_unknown`; one selected pool; spec-owned owner identity;
  explicit process-exit attestation; `UNKNOWN` recovery outcome; no foreign
  lease mutation; existing durable schemas unchanged.
- Private discretion covers helpers, waits, classification, factory layout, and
  internal exceptions. The assignment provider remains the topology seam;
  Stage 24 may change controller candidate policy, not runtime maintenance.
- Import and dependency direction: `loom.queue.managed_local` may import
  queue-local modules and public `loom.pipeline.stores` contracts. Core
  controller/config/service modules must not import the managed-local runtime.
  The runtime is imported from its explicit submodule rather than eagerly from
  `loom.queue`, preserving the current lightweight root import. No dependency
  is added.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Pool-bound runtime facade | Demonstrated downstream wiring and maintenance failure boundary. | Copy the example downstream. | keep; copying already produced an owner defect |
| Runtime state/status record | Operators need degraded/recovery/maintenance truth separate from persistence. | Return only the last cycle. | keep; last cycle cannot describe restart blocking |
| Reconciliation-only controller path | Drain/cancel must stop claims while maintaining active leases. | Keep calling `run_cycle()`. | keep; `run_cycle()` may refill |
| Explicit recovery resolution | Restart otherwise remains permanently blocked without unsafe DB edits. | Automatically inspect/kill a PID. | keep explicit; defer automation |
| Completion audit evidence | Recovery attestation must be reviewable without a new item schema. | Encode everything in free-text reason. | keep the smallest plain-data audit addition |
| Built-in weighted/bundle slots | Not needed: amount-two and custom provider already cover current consumers. | Add slot capacity/topology schema. | defer |
| Authority per-lease live read | No current status contract requires it. | Add to every coordination backend. | defer; say unobserved |
| Daemon/leader election/reattachment | Future unattended multi-controller capability. | External supervisor plus recovery gate. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1, FR-2, FR-12 | Public module | Put the heavy operational facade in `loom.queue.managed_local`, not the eager queue root. | One explicit import path preserves cheap imports. | repo-resolved |
| DQ-2 | FR-3 | Startup boundary | Recheck mutable authority limits at runtime start and never provision them. | Startup can fail after config parsing, as it should. | repo-resolved |
| DQ-3 | FR-4, FR-5 | Timing owner | Runtime computes bounded waits from the controller deadline; adapter remains the renewal owner. | Runtime must stay alive and scheduled. | repo-resolved |
| DQ-4 | FR-6 through FR-8 | Crash ownership | Supervisor proves process containment; runtime gates/refuses; authority leases expire normally; repository records unknown resolution. | No seamless continuation after crash. | repo-resolved |
| DQ-5 | FR-9 | Status contract | Reuse pool status and add observation scope instead of querying hardware or changing the CLI envelope. | Persisted evidence may be stale and is labelled accordingly. | repo-resolved |
| DQ-6 | FR-10 | Bundle ownership | Every allocator leases the same physical member keys; a bundle is a provider placement decision, not a second independent resource namespace. | Custom provider has acquire/rollback/renew/release code. | repo-resolved |

## Expanded Design Review

The manager performed a local removal-first review because the current request
does not require an independent planning pass.

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| A root export would eagerly import local execution and pipeline-store modules. | FR-2, FR-12 | Existing package tests require `import loom.queue` to remain lightweight. | Use the explicit `loom.queue.managed_local` public path. | resolved |
| Automatic restart recovery cannot distinguish a dead orphan from a live foreign controller using PID evidence safely. | FR-6, FR-8 | Process handles/provider tokens are memory-only and PIDs can be reused. | Gate and require external process-exit attestation; never take over leases. | resolved |
| Releasing persisted lease IDs after restart would bypass fencing ownership. | FR-8 | Fencing tokens are intentionally not in safe durable evidence. | Mark queue work unknown only; let authority expire foreign leases. | resolved |
| A weighted slot would duplicate existing two-slot behavior and create topology/packing questions. | FR-10 | Static assignment already atomically compensates partial acquisition. | Document amount two and provide a downstream bundle-provider pattern. | resolved |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Owner and status | Owner mismatch downgrades live evidence. | Runtime factory/read model. | Construction plus e2e `same_session_live`. | planned |
| Maintenance/degradation | Missed or failed renewal must not permit refill. | Runtime/controller/adapter. | Fake timing plus degrade/recover/refill. | planned |
| Restart/recovery | Fresh adapter lacks live state; stale mutation can hide work. | Gate, operator attestation, repository. | Recreate runtime, reject/resolve/CAS/no-release. | planned |
| Shutdown | Drain/cancel must not claim or release before exit. | Runtime/local adapter. | Drain/cancel/pending/timeout. | planned |
| Status truth | Persisted evidence is not hardware availability. | Runtime/read model. | Observation-scope assertions. | planned |
| Multi-slot/bundle | Two-device placement must use distinct common member keys. | Static/custom providers and authority. | Binding, rollback, renew/release, contention. | planned |

Causal interactions requiring combined coverage:

- Owner/session determine live status; renewal failure/degradation determine
  whether refill is allowed.
- Restart, foreign process ownership, recovery confirmation, guarded queue
  completion, and later admission require one crash-recovery integration test.
- Shutdown mode, process exit observation, and lease release ordering require
  combined coverage.
- Bundle acquisition and individual allocation must contend on the same member
  keys in one test. Other validations remain focused rather than Cartesian.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Safe managed-local runtime | Downstream can construct one runtime, validate it, serve it with automatic maintenance, see truthful health, stop by draining, and fail closed on foreign work. | Runtime module plus the smallest controller/resources seams; no foreign resolution, cancel mode, daemon, or docs migration. | Stage 23 merged; independent of Stage 24 policy. | Owner, factory, static/custom provider, validation, wake timing, degraded no-refill, recovery gate, drain, status, and import tests pass. | pending |
| 2. Explicit recovery and shutdown | Operators can explicitly resolve contained foreign work as unknown and request bounded cancel shutdown without lease takeover or early release. | Recovery transition/audit and runtime shutdown only; no PID kill, reattach, requeue, or lease read API. | Phase 1 merged. | Crash, two-slot crash, attestation, CAS, no-release, cancel, pending-exit, and timeout tests pass. | pending |
| 3. Downstream operations proof | Canonical docs/example use the runtime correctly, prove a two-slot item, provide a safe bundle-provider pattern, and explain supervisor/status/recovery boundaries. | Examples/docs/tests and small Stage 23 defects; no core GPU logic or generic operations redesign. | Phase 2 merged. | Rerunnable e2e reports `same_session_live`, two slots, correct logs/counts; bundle tests and docs review pass. | pending |

Three phases separate safe normal operation, high-consequence recovery, and
downstream proof.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | FR/FQ rows cover construction, operation, failure, recovery, shutdown, status, resources, and compatibility. | pass |
| Minimum design justified | The facade composes existing Stage 23 owners and adds only missing lifecycle orchestration. | pass |
| Complexity delta proportionate | Daemon, reattachment, lease reads, weighted slots, discovery, and generic scheduling are removed or deferred. | pass |
| Contracts and private discretion clear | Public runtime/recovery behavior is fixed; helper layout and wait mechanics remain private. | pass |
| Invariant ownership and validation proportionate | Each safety invariant has one owner and only five causal interactions use combined coverage. | pass |
| Phases vertical and reviewable | Normal operation, risky recovery, and downstream proof are separated into three useful increments. | pass |
| No unresolved blocker | Repository-backed decisions are resolved and the maintainer approved the plan on 2026-08-18. | pass |

Gate result: planning is confirmed and ready for Phase 1 implementation. The
maintainer approved the plan on 2026-08-18.

Accepted risks and revisit triggers:

- One runtime per pool is a deployment rule, not distributed leader election.
  Revisit if two controllers must enforce one exact shared active-item limit.
- External containment is required after controller death. Revisit reattachment
  only when an unattended consumer requires process survival and can provide a
  durable supervisor job identity plus provider recovery state.
- Custom providers own topology correctness and readiness. Revisit a built-in
  bundle model only after two independent real consumers need the same shape.
- Runtime status does not observe hardware health or current lease rows. Revisit
  when an operator feature requires an authority-backed per-lease read or a
  real device-health provider.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Roadmap placement | Use Stage 23-post and leave Stage 25's broad design scope intact. | This is a demonstrated Stage 23 operational follow-up. | Maintainer prefers folding it into Stage 25. |
| Runtime identity/scope | `spec.controller.owner_id`; one managed pool. | Prevents mismatch and matches one cycle owner. | Multi-tenant or atomic multi-pool requirement. |
| Default stop | Drain. | Preserves work by default. | Deployments consistently require cancel-on-restart. |
| Crash/leases | Mark contained foreign work `UNKNOWN`; never mutate its leases. | No trustworthy result/token survives; authority owns expiry. | Durable reattachment or safe authority recovery exists. |
| Multi-slot/bundle | Amount two over two slots; custom bundles acquire/rollback all member keys. | Keeps physical ownership explicit. | Repeated generic topology consumers. |
| CLI/daemon | Deferred. | A Python foreground runtime plus external supervisor satisfies the current consumer. | A current user needs Loom-owned daemon lifecycle or remote control. |
