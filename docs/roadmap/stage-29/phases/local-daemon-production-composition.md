# Phase 3B Execution Plan: Local Daemon Production Composition

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 29, Phase 3B
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p3b-local-daemon-production-composition`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-29-p3b-local-daemon-production-composition`
- Base revision: clean `origin/develop` at
  `b045f45c763568d8d8cd3e2fbb1e5a8bf80ddf43`
- PR target: `develop`
- PR title: `feat(queue): complete persistent local daemon runtime`
- Dependencies: Phases 1-2 remotely merged; Phase 3A explicitly blocked and its
  isolated worktree/branch retained only as implementation evidence
- Workflow path: expanded because this phase composes durable coordinator,
  authority, local-agent, public-facade, and filesystem owners across restart
- Blockers: none; expanded design/plan reviews and maintainer approval passed

## Objective And Context

- Vertical outcome: a user initializes fresh local-daemon state, starts one
  persistent single-machine runtime, submits an already-persisted immutable
  prepared run through its client surface, and observes Loom automatically
  prepare dependency-ready work through Phase 1 and execute it through the
  complete Phase 2 reservation-to-release saga. A real `preprocess -> train`
  run completes without the caller or test injecting authority, resolver,
  assignment, or stage-executor objects.
- Earlier dependency: Phase 1 owns authority-ready attempt preparation,
  `RunOrchestrator`, stage-work projection, placement decisions, and the pure
  kernel. Phase 2 owns assignment reservation, authority bind/grant, local
  provider preparation, one fenced root launch, output commit, logical release,
  physical release, and fresh availability.
- Recovery context: Phase 3A produced useful daemon-root, IPC, admission, and
  hand-off components, but its public request contains an opaque prepared-stage
  mapping and all meaningful production resolution remains behind supplied
  protocols/fakes. It failed the manager pre-submit gate after correction 3/3.
  Phase 3B starts from `develop`, may selectively reuse that source, and is not
  another correction or a stacked PR.
- Later work explicitly out of scope: Phase 4 remote authenticated agent
  sessions; Phase 8 disconnected/SLURM cancellation and reload/drain; Phase 9
  active-process adoption, unknown-work closure, and privileged takeover.

## Current Source And Harness

- Authoritative ready-stage path:
  `loom.pipeline.orchestration.RunOrchestrator`,
  `SQLiteStageWorkStore`, `ExecutionPlan`, authority snapshots, resolved stage
  placements, and the existing scheduling decision path.
- Authoritative local execution path:
  `loom.pipeline.execution.managed_local.SQLiteCoordinatorAssignments`,
  `SQLiteAgentJournal`, managed offers/assignments/claims/provider commands,
  `PreparedAttemptExecutionAuthority`, and
  `run_managed_local_assignment`.
- Existing run composition:
  `create_authority_backed_serial_run_store` supplies the persisted execution
  plan, runtime metadata, local payload access, and authority truth. Its
  concrete store/authority construction may be reused without transferring
  lifecycle ownership to the daemon. `PreparedRunRecord` is a delegated-Slurm
  continuation artifact and is not a managed-local admission prerequisite.
- Public paths that are not the solution: `PipelineRunner` remains a whole-run
  execution owner; `continue_prepared_run` and `loom prepared-run continue`
  intentionally fail for insufficient whole-run continuation state. Neither may
  become a second managed scheduler or a compatibility translator.
- Phase 3A evidence: branch
  `agent/stage-29-p3-local-daemon-control-boundary`, implementation `51ca432`,
  blocked record `9d2d7a0`, and its dedicated worktree. Useful candidate parts
  include explicit role-root initialization/open-only checks, stable coordinator
  identity/process epoch, owner-only Unix IPC, digest admission, and restart/
  cancellation sentinels. Candidate abstractions are not accepted merely
  because their component tests pass.
- Import direction: operational/deployment composition sits above queue
  transport and pipeline application ports. `loom.pipeline.execution` must not
  import `loom.queue` request/transport/domain types. `loom.scheduling` stays
  pure and imports no queue, pipeline, authority, SQLite, executor, or transport.

## Scope

In scope:

- Define one canonical managed-local admission containing client queue identity
  and `run_uri`. The service reloads the canonical `ExecutionPlan` and local
  runtime metadata from the protected run store, computes their normalized
  intent digest, and rejects missing, changed, wrong-run, unsupported, or
  incomplete content. A caller does not send an executable stage payload,
  callable, assignment, authority principal, state path, or provider token.
- Add one protected production composition above the queue and pipeline owners.
  It opens explicit coordinator/agent roots, authority/run stores, stage-work
  and assignment stores, configured local inventory/providers, scheduling
  components, executor/artifact adapters, and the owner-only client endpoint.
  Exact class/module decomposition is private if dependency direction remains
  correct and public imports stay intentional, typed, and cheap.
- Add the daemon wake/reconcile loop. For each active admission it reads the
  persisted execution plan/runtime metadata and one authoritative snapshot,
  resolves placements, calls `RunOrchestrator.reconcile`, obtains current local
  offers, calls the fixed scheduling decision path, converts the selected exact
  candidate into claims/provider commands/worker request/decision receipt,
  reserves through `SQLiteCoordinatorAssignments`, and invokes
  `run_managed_local_assignment`. It continues until blocked/waiting or the run
  reaches authority terminal truth; it does not create a whole-run backlog or
  another readiness interpretation.
- Keep authority as a separate owner behind a protected least-privilege adapter.
  The runtime supplies this adapter; clients/workers never do. Admission remains
  `PENDING_AUTHORITY` during outage and becomes schedulable only after the exact
  stable coordinator owner, intent digest, and durable operation receipt agree.
- Reuse one local agent supervisor capable of overlapping disjoint assignments
  up to configured capacity. Phase 2 remains the only grant/launch/commit/
  release saga. The daemon records accepted hand-off identities and never
  invokes a second root for the same assignment.
- Route the supported managed-local Python and CLI operations through the same
  client view: initialize, start/serve, submit, status, wait, and cancel. Exact
  command spelling/config file shape is private. Bounded embedded execution may
  reuse the same composition and retained roots or connect to the active owner;
  it never creates temporary production identity.
- Expose owner-labelled status sufficient to distinguish admission/control,
  authority lifecycle/cancellation, ready/placement wait, assignment/execution,
  and service health. Each axis carries its owner revision or accepted receipt
  evidence; the sequential join is labelled with coordinator `as_of` and does
  not infer global atomicity or physical release from lifecycle status.
- Implement connected-local cancellation: commit coordinator request, install
  the authority cancellation epoch, stop new preparation/reservation/grant,
  close never-assigned work under authority rules, and deliver exact fenced
  control to a connected active local assignment. Unknown/disconnected work
  remains cancelling; Phase 8/9 retains broader completion/recovery.
- Preserve the Phase 3A explicit initialize/open-only, owner-private distinct
  local roots/locks, stable coordinator identity/rotating process epoch,
  accepted-time high-water, safe stale-endpoint handling, crash-durable commit
  acknowledgement, and no memory fallback requirements. Ordinary restart begins
  with no assumed availability and does not retry an indeterminate launch.
- Complete the approved hard cut-over. Remove managed-local whole-run runtime,
  imports, requests, continuation/recovery, queue dispatch, and GPU runtime
  construction. Inspect only bounded root/schema metadata needed to identify
  and reject old managed-local state; do not read/interpret its domain rows,
  translate, cancel, resume, delete, or migrate it. Preserve generic/custom queue
  paths and historical whole-run delegated Slurm behavior.
- Replace demonstration-only examples with a runnable production composition
  using generic `machine-A` configuration and no host-specific paths/secrets.

Out of scope:

- Remote listener/agent protocol, mTLS agent sessions, artifact relay, GPU
  placement, ready-stage Slurm, config reload/drain, active-process adoption,
  unknown-work manual recovery, automatic failover, coordinator HA, database
  migration, or compatibility adapters.
- New scheduler, readiness evaluator, lifecycle store, provider protocol,
  generic daemon framework, plugin activation system, or public resolver
  extension. The current Phase 1/2 owners are the accepted consumers.
- Treating daemon restart, missing PID, future cancellation, or socket closure as
  proof that a process stopped or resources are reusable.

Assumptions:

- Authored prepared-run/project configuration is trusted project code; daemon
  state/configuration and authority/provider credentials remain protected.
- Same-user local IPC plus owner-private endpoint/root permissions is sufficient
  for this phase. Remote principals belong to Phase 4.
- A real prepared run and its authority state exist before managed admission.
  Creating/planning that run may remain an existing command/API responsibility.

## Fixed Contracts And Private Discretion

- Observable behavior: successful submit means the unique digest-bound admission
  transaction committed, not that authority accepted or a stage launched. A
  healthy daemon automatically advances eligible work without a manual operator
  reconciliation call. Wait/status/cancel use the retained queue/run identity.
- Public/durable shapes: admission pins stable coordinator ID, `run_uri`, queue
  item, normalized intent/plan digest, and execution owner. Stage work, assignment,
  attempt, process execution, claim, offer, and cancellation identities remain
  distinct and joinable. Existing Phase 1/2 codecs remain authoritative.
- Trust boundary: client credentials/principals come from direct construction or
  peer credentials, never request bodies. Only protected runtime composition
  has authority access, state-root paths, providers, and executor construction.
  Workers receive no daemon root, authority endpoint/credential, or provider
  live token beyond exact assignment-scoped commands.
- Causal boundary: admission commit precedes authority binding; authority-owned
  readiness precedes projection; complete placement decision and reservation
  precede Phase 2 bind; provider preparation precedes grant; journalled start
  precedes launch; authority terminal/output commit precedes logical then
  physical release/fresh availability. Cancellation epoch precedes fan-out.
- Restart boundary: stable owner survives while process epoch rotates.
  `PENDING` operations replay their same IDs; accepted/granted/running or
  dispatch-indeterminate work remains bound/unknown without duplicate launch.
  Phase 9 alone resolves exceptional unknown containment.
- Compatibility: managed-local is a one-way cut-over. Fresh roots are required;
  downgrade is unsupported. Delegated whole-run Slurm is outside this owner and
  unchanged.
- Private discretion: application module/class names, loop cadence/wakeup
  primitive, internal port shapes, SQLite table/index layout, CLI spelling,
  socket message envelope, and local concurrency helper may change. Review must
  evaluate the reachable trace and ownership, not require the Phase 3A helper
  layout.

## Proportionality

- Existing seams reused: persisted `ExecutionPlan`, authority-backed run store,
  `RunOrchestrator`, `SQLiteStageWorkStore`, scheduling kernel/default policy,
  `SQLiteCoordinatorAssignments`, `SQLiteAgentJournal`, existing local resource
  planners/providers, StageWorker request/materialization, and
  `run_managed_local_assignment`.
- Material additions: one protected production composition, one bounded daemon
  reconcile/wake loop, stage-based managed client/CLI wiring, and joined local
  status. Each exists because the accepted daemon has a current user and the
  Phase 3A failure demonstrates that protocols/examples alone are insufficient.
- Removal first: delete or relocate candidate protocol/fake layers that merely
  defer required construction. Do not add a public resolver registry or second
  lifecycle abstraction.
- Deferred: remote transport, generalized service hosting, plugins, migration,
  drain/reload, and recovery machinery without a current Phase 3B consumer.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Every accepted healthy local admission can reach the Phase 1/2 path | Production daemon composition | Socket/client stores request but runtime lacks authority/orchestrator/reservation wiring | Accepted run remains pending forever | Real no-fake prepared-run E2E and progress timeout diagnostic |
| Prepared input matches retained run truth | Admission validator + authority-backed run store | Caller supplies opaque/changed/wrong-run plan data | Fabricated readiness or wrong execution | Digest/run/schema/missing artifact tests |
| One readiness and lifecycle owner | `RunOrchestrator` + per-run authority | Daemon or `PipelineRunner` independently evaluates/executes managed DAG | Duplicate/early stage or overwritten status | Dependency-order/one-attempt sentinels and import/source audit |
| One exact reservation-to-release path | Coordinator assignment store + Phase 2 saga + agent journal/provider | Resolver fabricates assignment or launches directly | Overcommit, duplicate root, premature release | Exact decision/claim/fence trace and one-launch crash tests |
| Protected composition owns authority/provider secrets | Deployment composition and scoped adapters | Client/request/worker supplies or observes privileged objects | Unauthorized mutation or secret leakage | Direct/socket/CLI negative and worker-env/redaction tests |
| Stable owner and roots survive ordinary restart | Root/lock/identity/accepted-time owners | Missing/aliased/shared/unsafe root, second daemon, clock regression | Split owner, empty state, stale capacity | Bootstrap/open-only/permissions/lock/epoch/time tests |
| Cancellation epoch precedes execution control | Coordinator request + authority cancellation CAS | Cancel races activation/reservation/grant/start | Post-cancel work or false completion | Pending/active/start barrier and connected containment tests |
| Hard cut-over cannot mutate old state | Public/preflight boundary | Old import/request/database presented | Silent migration, fabricated facts, destructive upgrade | Rejection plus unchanged-file sentinel and delegated regression |
| Dependency direction remains acyclic | Package boundaries | Pipeline execution imports queue transport/composition | Import cycle and inverted ownership | Package import-boundary tests |

## Implementation Slices

1. Selectively adopt the Phase 3A root/identity/IPC/admission code into a clean
   branch, correct dependency direction, and replace opaque prepared-stage input
   with canonical persisted-plan/runtime resolution by admitted `run_uri`.
2. Build the protected authority-backed local composition using existing Phase
   1/2 stores, orchestrator, placement/scheduling, offers/providers, reservation,
   worker construction, and assignment saga; remove supplied resolver/executor
   fakes from the production path.
3. Add the persistent wake/reconcile/concurrency loop, joined status/wait, and
   authority-effective connected cancellation with ordinary restart barriers.
4. Route managed Python/socket/CLI operations and runnable examples through that
   composition; complete hard-cut-over removals while preserving delegated
   Slurm and package boundaries.
5. Add the real local vertical acceptance matrix, update docs/diagnostics, and
   remove candidate machinery that has no current production consumer.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Public hard cut-over and import direction | New client/runtime imports intentional and cheap; old managed-local imports fail; no pipeline-to-queue transport import |
| Unit | Required | Admission identity, root/endpoint/time, loop state, status join, cancellation gates | Wrong digest/run/schema, exact replay/conflict, lock/permissions/alias, pending/effective cancel, safe diagnostics |
| Contract | Required | Direct/socket/CLI application equivalence and authority scope | Same normalized request/result/idempotency; request actors ignored; client/worker cannot invoke authority/provider views |
| Integration | Required | Real production composition across authority/orchestrator/scheduler/reservation/agent | No injected authority/resolver/assignment/executor; exact offer/decision/claim/fence; multiple disjoint runs; outage and restart without duplicate hand-off |
| E2E / opt-in | Required local | Complete persistent-daemon user journey | Initialize/start, submit persisted `preprocess -> train`, first output unlocks second, joined wait/status succeeds, connected cancel settles conservatively, restart preserves owner/new epoch |
| Regression | Required | Hard cut-over does not broaden | Old root/request/import rejected and unchanged; delegated whole-run Slurm tests unchanged |

Targeted commands:

    uv run pytest -q tests/unit/loom/queue tests/unit/loom/pipeline/execution
    uv run pytest -q tests/integration/queue tests/integration/pipeline
    uv run pytest -q tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: copying Phase 3A while retaining its fake/manual gap; treating a
  plan digest as authority truth without reloading retained artifacts; adding a
  second readiness/scheduler loop; bypassing coordinator reservation; blocking
  the service loop on one stage; retrying an indeterminate dispatch; exposing
  authority/provider secrets; flattening owner status; or broadening deletion/
  compatibility changes into delegated Slurm.
- Review focus: the real submit-to-worker trace, invariant owners, absence of
  caller-injected production dependencies, durable causal ordering, restart/
  cancellation behavior, import direction, and removal of unused machinery.
- Stop if: current persisted plan/runtime artifacts cannot reconstruct the exact
  plan/runtime/placement inputs without inventing durable facts; the real path
  would require `PipelineRunner` to remain a second managed owner; Phase 2 lacks
  a safe exact assignment/reservation input; a worker needs authority/daemon
  credentials; or delegated Slurm behavior must change.
- Accepted debt: Phase 4 remote sessions, Phase 8 disconnected controls, and
  Phase 9 exceptional recovery remain visible. Ordinary restart may retain an
  unknown capacity-holding assignment; liveness is secondary to no duplicate
  authored root.

## Executor Handoff

- Read this file; manifest `Summary`, `Shared Constraints`, `Phase Index`, and
  `Quality Gate`; planning `Minimum Design`, `Refactor And Deprecation Map`,
  `Examples And Validation`, and `Phase Shaping`; Phase 1/2 completion records;
  and the blocked Phase 3A completion record.
- Evidence roots: clean phase worktree from current `origin/develop`; isolated
  Phase 3A worktree/branch only for selective reference. Do not base or open a
  stacked PR from Phase 3A.
- Decisions not to revisit: hard managed-local cut-over; canonical persisted
  persisted-plan/runtime resolution rather than opaque stage payload or a
  second prepared-run identity; one protected production
  composition; Phase 1 readiness/decision owner; Phase 2 execution owner;
  separate authority; no worker authority access; fresh roots; owner-only local
  IPC; delegated Slurm unchanged; correct dependency direction.
- Stop and return a qualified blocker if a real persisted local plan cannot be
  reconstructed into existing Phase 1/2 inputs without a new public/durable
  contract, or if the no-fake E2E cannot reach a real worker root.

## Workflow State

- Manager preparation: complete at clean `origin/develop` `b045f45`; dedicated
  branch/worktree, repository `samcantrill/loom`, target/title, Phase 1/2 source
  owners, focused test areas, final gates, and isolated Phase 3A evidence path
  are recorded
- Expanded planning: architecture exploration, design-safety review, and plan
  review completed; bounded plan corrections applied; no additional phase-
  planner pass is needed because the approved plan fixes the cross-owner trace,
  dependency direction, hard cut-over, and no-fake E2E acceptance
- Implementation: complete pending the full pre-submit gate; the production
  daemon, public client/CLI surface, owner-labelled status, connected-local
  cancellation, hard-cut-over removals, and runnable example are present
- Refiner: qualified blocker correction 1/3 complete
- Pre-submit gate: complete; `make validate-pr` passed Ruff, Pyright, the
  2,365-test default suite, the 141-test config-extra suite with three optional
  container skips, and package builds; `make test-summary` recorded 2,506
  categorized passes and no failures/errors
- Independent review: required because the phase crosses durable authority,
  coordinator, agent, public, and filesystem boundaries
- Blocker corrections: 3/3; all resolved
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added `loom.queue.local_daemon`, its protected production composition and owner-only transport; added shared Python/CLI initialize, serve, submit, status, wait, and cancel operations; connected persisted plan/runtime/config, authority, Phase 1 orchestration/scheduling, and the Phase 2 assignment saga; added connected cancellation polling and commit suppression in `loom.pipeline.execution.managed_local`; removed `loom.queue.managed_local` and its managed-local GPU runtime construction; updated examples and feature/roadmap documentation. Authority correction 1/3 remains intact at `afc245a` with replay-safe coordinator-admission/cancellation-epoch receipts and SQLite persistence. |
| Tests added or updated | Added daemon bootstrap/restart/lock/root tests and real persisted `preprocess -> train`, authority terminal projection, controller-only skip, independent-run overlap, digest-change, pending-cancel, active socket-cancel, hard-cut-over, CLI, package, contract, and example coverage. Added admission-scoped scheduling coverage. Removed tests for the deleted whole-run managed-local runtime and retained delegated-Slurm coverage. |
| Validated revision/tree state and evidence | Final tree passed `make validate-pr`: Ruff and Pyright clean; default isolated suite 2,365 passed/121 deselected; config-extra 141 passed/3 optional container skips/2,368 deselected; source distribution and wheel built. Fresh `make test-summary` passed 2,506 categorized tests with zero failures/errors: package 118, unit 1,692, contract 295, integration 203, E2E 57, config-extra 141. |
| Validation-relevant changes after evidence | This completion-record update only; no source, test, dependency, build, or validation configuration changed after the successful receipts. |
| PR, review, and merge | pending |
| Residual risk and cleanup | Corrections are exhausted and resolved: (1) authority lacked durable coordinator-admission/cancellation receipts; (2) the phase file accidentally promoted delegated Slurm's `PreparedRunRecord` into a local prerequisite, so managed local now uses the existing persisted `ExecutionPlan`, runtime metadata, and resolved config; (3) an active connected cancellation could previously arrive after root launch without suppressing success, so the running assignment now observes the authority epoch, waits for containment, and withholds output commit. The final composition also proves admission activation, authority run finalization, admission-scoped selection, independent-run capacity overlap, and owner-accurate status. No migration or compatibility path was added. Phase 4/8/9 remote, disconnected-control, and exceptional-adoption risks remain deferred as planned. Phase 3A branch/worktree remains retained as isolated evidence pending Phase 3B disposition. |
