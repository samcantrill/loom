# Phase 1 Execution Plan: Dependency-Aware Scheduler And Local Daemon Boundary

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 1
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p1-local-daemon-control-boundary`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop`; record exact prerequisite symbols
- PR target: `develop`
- PR title: `feat(scheduling): add dependency-aware local stage scheduler`
- Dependencies: implemented queue/managed-local paths, pipeline planner/runner,
  runtime resources/profiles, prepared stage worker, per-run SQLite authority,
  local resource admission/providers, reliability, and process containment
- Workflow path: expanded because this phase migrates the managed execution unit,
  adds durable schemas and authority CAS/fences, and changes concurrency/locks
- Blockers: none; stop if preparation finds a material contradiction with the
  accepted ownership or compatibility contracts

## Objective And Context

- Vertical outcome: both a bounded local call and a persistent single-machine
  daemon admit a run, durably resolve its DAG, expose only dependency-ready
  executable attempts, place them using exact local CPU/memory capacity, execute
  through a local agent, unlock descendants after authoritative output commit,
  and provide later status/cancel/restart behavior through the same path.
- Earlier dependency: reuse current plan actions/readiness, prepared attempt,
  stage worker/finalization, resource admission, queue SQLite, authority, and
  managed facade rather than building a second pipeline runtime.
- Later work explicitly out of scope: Phase 2 adds remote agents, global GPU/
  VRAM placement, cross-machine artifact relay, and disconnected remote replay.
  Phase 3 adds live reload and containment-gated recovery.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/queue/models.py`, `service.py`, `repository.py`, `_sqlite.py`,
    `selection.py`, `controller.py`, `local.py`, `managed_local.py`,
    `assignments.py`, and `status.py` own current whole-run admission/dispatch;
  - `src/loom/pipeline/execution/runner.py` owns the in-memory ready-stage loop,
    run lock, stage retry loop, and direct resource admission;
  - `continuation.py`, `stage_attempts.py`, and `stage_worker.py` own prepared
    single-stage reconstruction, with a current `SUBMITTED` continuation gap;
  - `lifecycle.py`, `reliability.py`, and per-run authority stores own statuses,
    attempts, leases, output commits, and retry facts;
  - `runtime/options.py`, `profiles.py`, `metadata.py`, `resources.py`, and
    `specs.py` own exact-stage runtime and authored resource parsing.
- Existing tests and seams: queue record/repository/controller/managed-local
  unit and integration tests; pipeline serial/parallel/retry/resume/continuation
  tests; authority contract/SQLite tests; local resource/provider tests; process
  fault helpers; public import and CLI E2E tests.
- Import, dependency, and harness constraints: follow `docs/structure.md` before
  adding `loom.scheduling`; pure scheduling stays import-light. Tests use fake
  clocks, barriers, stores, providers, and processes—no real GPU/network.

## Scope

In scope:

- Extend exact-stage runtime options with versioned placement policy: built-in
  hard target/attribute constraints, tagged soft preferences, fallback, and pool
  selection. Run policy supplies defaults/concurrency and may hard-pin every
  executable stage; exact-stage policy cannot weaken pool/site hard rules.
- Add one resolution function that composes `StageSpec.resource_request` and
  exact-stage runtime `ResourceRequest`. Built-in CPU/memory planners retain the
  existing `resources.entries` grammar, positive integer CPU, and normalize
  memory to integer bytes. Duplicate-kind composition must preserve the authored
  minimum or reject ambiguity; there is no second resource request codec.
- Add import-light `loom.scheduling` values for stage candidates, inventory,
  availability, claims, built-in hard/soft specs, preference reasons, and
  complete/infeasible/exhausted search. Add one concrete deterministic engine
  and explicitly supplied resource-planner registry; no public Scheduler API.
- Extract one shared authority-side readiness predicate over persisted
  `ExecutionPlan`, current stage/attempt status, and committed upstream output
  identities. Use it in orchestration and authority assignment CAS. Refactor or
  retire runner and `run_stage_job` duplicate dependency checks; agent execution
  validates only exact assignment/grant/input identities.
- Add a durable `RunOrchestrator` that reconciles controller-only plan actions,
  prepares each ready `PlanAction.RUN` attempt idempotently, enforces
  `max_parallel_stages`, materializes `StageWorkRecord`, records retry-derived
  next attempts, blocks descendants, and finalizes run/queue state.
- Extend coordinator SQLite with schema-versioned stage work, local agent offer,
  logical resource reservation, assignment state, control intent, idempotency,
  and event acknowledgement. Stage work is rebuildable and cannot write stage
  success/failure. Scheduling runs outside transactions; commit revalidates
  exact work/authority/order/offer/claim versions.
- Extend per-run authority with expected-state operations required by the saga:
  bind the exact still-ready prepared attempt to one assignment and mark it
  submitted; unbind only the same definitively declined ungranted assignment;
  create a durable execution fence on grant; accept a late result after liveness
  expiry while that fence remains current; reject it after terminal or explicit
  fence. Preserve existing stage/output/reliability ownership.
- Add a separate local agent SQLite journal and runtime: configured inventory,
  zero-to-current availability, work receipt, local input/request durability,
  physical resource admission, accept/decline, grant/start fence, one root
  launcher invocation, process containment, terminal/outbox facts, and release.
  Phase 1 local artifact transport maps existing local refs without network
  transfer but uses the same pre-grant and final-ref port required by Phase 2.
- Refactor the current stage worker/request path to execute a `SUBMITTED` exact
  assignment safely without reacquiring managed resources or independently
  allocating an attempt. Remove the full-run managed lock as execution owner;
  use authority CAS/controller lease and stage/attempt fences that allow safe
  parallel branches.
- Keep queue item/run identity as public admission/cancellation. Introduce a new
  managed orchestration state rather than reinterpreting historical
  `DISPATCHED`. Derive terminal queue status from authoritative run completion.
- Preserve `PipelineRunner`, `ManagedLocalQueueRuntime`, queue service, Python
  API, and CLI entrypoints as facades over an embedded or persistent coordinator
  plus local agent. Deprecate managed whole-run resources/argv and direct
  claim-dispatch through documented compatibility reads/warnings. Preserve
  `continue_prepared_run` import/validation/structured safe failure exactly.
- Add the bounded application port, shared authorizer, direct adapter, and a
  loopback persistent daemon/client composition with protected configuration,
  role locks, duplicate-start rejection, graceful shutdown, restart scan, safe
  status, and cancellation. Transport routes contain no policy.
- Update `docs/structure.md`, glossary/feature docs, public imports, migration
  notes, and a `machine-A` single-machine example only where the checkout is
  clean and conflict-free.

Out of scope:

- Remote agent registration/session replacement, cross-host artifact bytes,
  GPU model/VRAM/fabric/share placement, multi-machine offers, or real mTLS
  topology evidence; Phase 2 owns them.
- Drain/reload, disconnected cancellation completion, positive-containment
  manual close/requeue, and different-session replacement; Phase 3 owns them.
- Fair-share, preemption, optimal packing, general solver, distributed/gang
  stage, public custom constraint/preference callables, process-global plugin
  registries, arbitrary code shipment, or delegated SLURM changes.

Assumptions:

- One local stage claim fits wholly inside the configured local agent.
- Authored project/deployment config is trusted. Runtime/queue/API data is
  untrusted versioned plain data and cannot select Python implementations.
- The local coordinator and agent use separate durable SQLite files even when
  composed in one process; in-memory doubles are tests only.

## Fixed Contracts And Private Discretion

- Observable behavior: for `preprocess -> train -> evaluate`, only preprocess is
  initially schedulable; each authoritative output commit triggers reconciliation
  and may expose the next stage. Reuse/skip consumes no agent capacity. Failure,
  retry, cancellation, and independent-branch behavior match current policy.
- Public/durable shapes: `ResolvedStagePlacement` contains `ResourceRequest`,
  hard/soft/fallback policy and fingerprint—never `stage_work_id`. Stage work
  contains identity/readiness evidence; assignments contain exact coordinator,
  authority, local agent/session/offer/claim and grant fences.
- Atomicity: no cross-store transaction is claimed. An ungranted definitive
  decline must authority-unbind before coordinator release. Ambiguous acceptance
  stays bound. Grant creates a non-liveness execution fence; every transition is
  idempotent and expected-state checked.
- Stage truth: coordinator status is a joined projection. Only authority output
  commit unlocks descendants. Agent success/outbox receipt alone never does.
- Resource truth: scheduler proposal is logical; final agent admission is
  authoritative. Managed worker execution must not reacquire the same claim.
- Compatibility: old queue rows remain readable; new managed submissions use the
  new orchestration schema. Public synchronous calls may wait on the durable run
  but cannot call the old in-memory ready loop. Delegated adapters remain intact.
- Trust/failure: required store failure blocks ack/grant/start. Direct and local
  daemon calls use the same principal/scope authorizer. Payloads cannot supply
  arbitrary argv, local paths, credentials, providers, or actor identity.
- Cross-phase: Phase 2 reuses exact stage-work/placement/assignment/fence/journal/
  application-port contracts and replaces only local offer/transport adapters.
- Private choices: SQLite table/index names, internal event-loop wakeup, exact
  module subdivision below documented owners, local socket/loopback HTTP wiring,
  migration helper layout, and test fixture construction.

## Proportionality

- Existing seam reused: queue admission/CAS, runner readiness semantics,
  `ResourceRequest`, runtime profiles, prepared attempts, stage worker,
  authority attempts/output commits, retry facts, local admission/providers,
  process containment, and managed facades.
- Material additions and current justification: durable stage work for restart;
  pure scheduler for one local/remote policy; authority assignment/fence CAS for
  cross-store correctness; separate agent journal for daemon restart; one
  shared readiness predicate to remove duplication.
- Optional hardening and future capability deferred: configurable scheduler
  implementations, custom rule callables, optimal search, online database
  backup, automatic unknown recovery, remote data transfer, and HA.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Exact attempt is ready under one shared predicate. | Authority readiness function | stale coordinator projection or duplicate worker validator | dependency bypass or false rejection | reuse/retry/diamond and assignment-CAS tests |
| Resolved request cannot weaken authored minimum. | Runtime resolver + resource planner | profile/explicit merge | under-allocation/OOM | CPU/memory merge negatives |
| Same complete snapshot gives same decision. | Pure scheduler | input order/search budget | nondeterministic placement | permutation/exhaustion tests |
| Stage work never owns stage terminal truth. | Coordinator repository boundary | event/restart projection | downstream starts on false success | store/API ownership tests |
| One active assignment binds one prepared attempt. | Coordinator uniqueness + authority CAS | concurrent cycles/lost response | duplicate launch | barrier/idempotency tests |
| Definitive decline restores only its ungranted attempt. | Authority unbind CAS | stale decline/parallel grant | dead or incorrectly reopened attempt | decline/grant race tests |
| Liveness expiry cannot invalidate a current execution result. | Authority execution fence | coordinator outage/late replay | valid output becomes uncommittable | fake-clock restart test |
| Grant/start fences precede one launcher call. | Agent journal/runtime | crash around accept/grant/start | unauthorized or duplicate process | injected crash table |
| Input identity and local durability precede grant. | Local artifact port + agent journal | incomplete preparation | granted process cannot continue | pre-grant fault tests |
| Output commit alone unlocks descendants. | Authority + orchestrator | agent terminal event before commit | consumer reads absent output | event/commit barrier test |
| Physical claims release exactly after terminal/containment. | Agent provider/journal | worker/store/process failure | overlap or leak | admission/cleanup injection |
| Managed facade has no whole-run scheduling fork. | Composition root | legacy controller/runner fast path | divergent behavior | trace/call-path integration test |

## Implementation Slices

1. Record current prerequisite contracts; add exact-stage placement parsing and
   resolution, CPU/memory resource planners, scheduling values/registry, and the
   concrete pure scheduler with import/codec/unit/property tests.
2. Extract the shared readiness predicate; add durable orchestrator/stage-work
   reconciliation and refactor runner/stage-job readiness, run locks,
   controller-only actions, retry, and terminal derivation with DAG tests.
3. Add coordinator schema/transactions and authority bind/unbind/grant-fence
   operations; implement the idempotent saga and crash/race/restart tests before
   connecting any launcher.
4. Add local agent journal/runtime, local artifact hand-off, provider binding,
   submitted worker execution, grant/start/process/outbox/release behavior, and
   fault-injected one-launch tests.
5. Add application port/authorizer and bounded/persistent local compositions;
   migrate public managed/runner/CLI facades, queue schema compatibility,
   status/cancel/restart, docs/examples, and end-to-end evidence.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Cheap intentional `loom.scheduling` and facade imports. | No SQLite/routes/vendor/project imports from scheduling root. |
| Unit | required | Placement merge, integer CPU/bytes, rule order, tri-state engine, readiness, state machines. | Invalid weaken/unit/version; deterministic decisions; one readiness result. |
| Contract | required | Runtime/placement codecs, authority CAS/fence, coordinator/agent stores, public compatibility. | Round trip; idempotent replay; old rows/import/failure remain. |
| Integration | required | DAG reconciliation, cross-store crash table, local admission, process/outbox, cancellation, restart. | No descendant early; exact unbind; late result commits under current fence; one launch/release. |
| E2E / opt-in | required local | Bounded and persistent local user journeys. | Submit two-stage/diamond runs, later status/cancel, restart both roles, same results/trace. |

Targeted commands:

    uv run pytest tests/unit/loom/pipeline tests/unit/loom/queue tests/unit/loom/scheduling
    uv run pytest tests/contracts/test_queue_python_api_contract.py tests/contracts/test_authority_store_contract.py
    uv run pytest tests/integration/pipeline tests/integration/queue tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: retaining two readiness interpreters; turning stage work into
  lifecycle authority; ambiguous resource merge; double admission; false
  cross-store atomicity; stuck submitted attempt after decline; lease-expired
  valid result; run-lock serialization; launch before durable grant; old-row
  reinterpretation; or a hidden whole-run fast path.
- Review focus: shared predicate call graph, authority/coordinator ownership,
  saga transition table, unbind/grant race, execution fence semantics, exact
  resource accounting, worker hand-off, one managed composition, compatibility.
- Stop if: existing authority cannot express the required expected-state fence
  without changing its accepted ownership; resource merging needs a universal
  DSL; safe local execution requires a distributed transaction; successful
  compatibility is demanded from `continue_prepared_run`; or delegated SLURM
  would be altered.
- Accepted debt and revisit trigger: deterministic FIFO-with-bypass, bounded
  search, no remote transfer/GPU ranking, and compatibility adapters. Revisit
  only with measured harm or Phase 2's accepted consumer.

## Executor Handoff

- Read section range: implementation manifest `Summary` and `Shared Constraints`;
  planning FR-1 through FR-20, FR-22, DQ-1 through DQ-10, `Refactor And
  Deprecation Map`, and this full phase.
- Safe implementation slices: the five ordered slices above; preserve a working
  local vertical path after each slice and stop after Phase 1 acceptance.
- Decisions not to revisit: prepared stage attempt is scheduling unit; one
  readiness predicate; one concrete pure scheduler; existing `ResourceRequest`;
  integer CPU; stage work is projection; exact unbind; outage-stable fence;
  authority commit unlocks; separate role stores; facade compatibility.
- Conditions requiring manager action: public/durable shape expansion beyond
  this plan, source contradiction, another scheduler/readiness owner, weakening
  an authored requirement, cross-store transaction dependency, or stop condition.

## Workflow State

- Manager preparation: pending clean worktree/base and exact source-map record
- Expanded planning: Stage 29 design review passed after one bounded seven-item correction
- Implementation: pending one `loom_phase_executor`
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: required because Phase 1 changes durable authority,
  cross-store launch fencing, and public managed execution behavior
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none / pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
