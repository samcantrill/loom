# Phase 8 Execution Plan: Agent, Profile, And Stage-Aware Controls

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 29, Phase 8
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p8-agent-controls-cancellation`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`;
  `/home/can134/work/active/loom-worktrees/stage-29-p8-agent-controls-cancellation`
- Base revision: clean `origin/develop` at
  `74e4b8354d82eb4fb727453ac6e4c9307b8fb3fb`
- PR target: `develop`
- PR title: `feat(scheduling): add agent controls and cancellation`
- Dependencies: Phase 7B squash-merged as `d0da216` with complete local/remote
  stage lifecycle,
  authenticated operator views, configured resources/providers, exact live
  claims, explicit ready-stage SLURM profiles/submissions/bootstrap, primitive
  external observation/cancel evidence, and joined status
- Workflow path: expanded because configuration mutation, availability,
  cancellation, process containment, and authorization races interact
- Blockers: none

## Objective And Context

- Vertical outcome: an authorized operator can drain, resume, or reload an
  agent's trusted local pool configuration, including withdrawing selected GPUs
  from future use, without changing resources beneath live assignments. A client
  can cancel a run and Loom stops new descendants, handles every prepared/
  assigned/running/transferring stage truthfully, and reaches terminal
  cancellation only after exact completion or positive containment. An
  authorized coordinator operator can reload protected SLURM profiles without
  reinterpreting nonterminal submissions, and cancellation fans out to managed
  agents and exact SLURM handles while retaining their distinct truth.
- Earlier dependency: Phases 2–7 establish exact claims, provider/profile/config
  identities, assignment fences, remote control transport, SLURM submission and
  bootstrap identity, and output lifecycle that controls must preserve.
- Later work explicitly out of scope: Phase 9 adds same-session restart,
  containment-gated closure of already-unknown work, and different-session
  replacement. Phase 8 never resolves uncertainty merely to make an operation
  finish.

## Current Source And Harness

- Extend the authenticated application views and direct/HTTP dispatch in
  `src/loom/queue/local_daemon.py` and
  `src/loom/queue/agent_session_transport.py`; the existing client owns run
  cancellation and the operator owns status/reconciliation, so new operations
  must preserve role-derived principals and direct/HTTP semantic conformance.
- Reuse the durable client cancellation request in
  `src/loom/queue/local_daemon.py`, authority cancellation epochs in
  `src/loom/pipeline/stores/authority.py` and
  `src/loom/pipeline/stores/sqlite_authority.py`, readiness gating in
  `src/loom/pipeline/planning/readiness.py`, and reconciliation/fan-out in
  `src/loom/queue/local_daemon_execution.py`.
- Extend the existing managed process/claim cancellation and retained provider
  bindings in `src/loom/pipeline/execution/managed_local.py` and
  `src/loom/scheduling/registry.py`; do not introduce a second claim or
  provider owner.
- Extend the existing remote session/assignment journal and retained-profile
  seams in `src/loom/queue/agent_sessions.py`, ready-stage assignment owner in
  `src/loom/queue/slurm_ready_stage.py`, ready-stage cancel request in
  `src/loom/pipeline/executors/slurm/ready_stage.py`, and trusted local runtime
  reconstruction in `src/loom/queue/local_daemon_runtime.py`.
- Extend `loom queue daemon-*` operations in `src/loom/cli/queue.py` only as a
  thin adapter over the public authenticated Python operations; status remains
  owner-labelled and redacted.
- Reuse the cancellation, transport, process, profile, provider, status, and
  package tests named by the targeted commands below. Add causal barriers only
  where the new control/reload/cancellation ordering requires them.
- Remote control payloads remain versioned inert data. Trusted configuration is
  read locally by the owning daemon/coordinator from protected deployment state.
  This phase is a hard cut: new durable/wire shapes receive fresh final version
  identities and all older or candidate shapes are rejected without migration.

## Scope

In scope:

- Add exactly three ordinary agent controls: `drain`, `resume`, and whole-agent
  `reload`. Each command binds operation ID, expected agent/session/config
  revision, bounded reason, optional affected pool selector where safe, explicit
  cancellation choice, and principal derived from authenticated context.
- Authorize each action separately and against exact agent/pool scope. A body
  actor, agent name, or pool string cannot expand the connection principal's
  authority. Direct/HTTP adapters retain semantic conformance.
- Persist coordinator control intent states such as `pending_delivery`,
  `applying`, `applied`, and `failed` with safe codes. Coordinator commit
  precedes response. The agent journals local effect/result before reporting;
  coordinator acknowledgement governs outbox cleanup.
- Serialize ordinary controls per agent. Exact principal/operation/key/content
  replay is idempotent; changed content conflicts. Expected revisions reject
  delayed controls after reload/session change.
- Drain withdraws affected availability and cancels/supersedes the outstanding
  work request before waiting. Default drain lets already granted stages and
  output uploads finish under their original resource/config identities.
  Optional explicit cancellation follows the same stage control path; drain
  never frees a live claim merely because it is no longer advertised.
- Resume publishes capacity only after local observation/reconciliation proves a
  fresh compatible config/inventory/availability revision. It cannot resurrect
  an old withdrawn offer or unknown claim.
- Agent reload reads that daemon's trusted local configuration. Coordinator
  scheduling reload reads the coordinator's trusted site configuration. No
  remote payload may contain replacement config, code, import target, provider/
  policy object, secret, path, or command. The request asks its target owner to
  reload; it does not describe what to load.
- Validate the complete replacement plan before mutation: agent/pool mapping,
  principal scopes, resident projects/environments/executors and their selected
  validator/executor activations, provider/claim-contract descriptors required
  on the agent and their non-secret
  configuration fingerprints, units/granularity, GPU modes/device uniqueness,
  one cross-pool capacity domain, storage/retention, and collisions. The agent
  validates advertised validator/planner compatibility descriptors but does not
  instantiate or replace coordinator-owned planner/rule/scorer/policy code.
- Reload first withdraws all affected availability, then waits for safe release
  or applies explicitly requested cancellation when the replacement cannot
  coexist safely. Build a complete new configuration epoch before mutation.
  Fresh resolution uses its active bindings, while every exact descriptor still
  referenced by nonterminal prepared/stage work, assignments, live claims, or
  transfers remains in a descriptor-keyed retained set at its owning service.
  Atomically swap only when both the new active plan and all required retained
  agent-owned bindings are reconstructable. Never publish mixed old/new inventory.
- Preserve exact old agent implementation objects/config identities as long as
  an agent-owned durable reference requires them. A new provider/config cannot
  adopt an old live token. If retention is impossible, reject agent reload
  before swap and keep the old complete plan; capacity stays safely withdrawn
  or explicitly resumable. Drained bindings may be garbage-collected only after
  an agent-owner query proves no assignment, preparation/claim, transfer,
  result, event, or outbox fact names the descriptor.
- Add a separate serialized coordinator scheduling-configuration reload for
  site policy, validator/planner/rule/scorer/policy registries, and protected
  SLURM profiles. It validates and builds a complete new coordinator epoch,
  retains exact descriptor bindings referenced by nonterminal prepared/stage
  work, assignments, or SLURM submissions, and swaps in one coordinator
  transaction. It does not drain or mutate agent claims and does not change the
  route/profile of existing stage work.
  Every nonterminal SLURM submission must retain the exact old command/status/
  cancel, mapping, credential/bootstrap, and data-path implementation/config
  needed to reconcile it. If the new configuration cannot retain those
  bindings, reject reload before swap. Removing or disabling a profile prevents
  fresh admission only; it cannot erase, migrate, resubmit, or reclassify live
  operations.
  Agent and coordinator reload are not one distributed transaction: while
  claim-contract/capability versions differ, normal feasibility makes affected
  candidates ineligible until compatible epochs are present.
- Support local pool reconfiguration by editing trusted config and invoking
  reload. Removing a GPU, CPU capacity, pool view, project, or provider affects
  future availability only after drain/release; it never changes a live
  assignment's claim.
- Complete run cancellation at stage granularity:
  - commit the authenticated client `CancellationRequest` once in coordinator
    state before responding, then reconcile the same operation ID into one
    canonical authority cancellation intent/epoch by expected-state CAS;
  - distinguish coordinator `requested` from authority `effective`. If authority
    is unavailable, retain/retry the request and expose degraded requested state;
    do not claim the lifecycle barrier is installed;
  - once effective, make the shared readiness predicate plus authority prepare,
    bind, grant, descendant, and retry operations reject that cancellation epoch
    before fan-out controls are delivered, including rejecting a not-yet-granted
    SLURM bootstrap;
  - prevent any descendant from becoming assignable after intent, even if an
    upstream success later wins a race;
  - terminalize never-ready descendants and never-assigned prepared work under
    existing authority cancellation/block rules;
  - for assignment-bound pre-grant work, clear binding only after an exact agent
    acknowledgement proves grant/start cannot occur and staged inputs/claims are
    released;
  - for granted work with no start intent, durably revoke start and obtain an
    exact agent acknowledgement that the launcher was never invoked before
    abort/release;
  - for granted work with durable start intent but no confirmed process, keep it
    unknown and reconcile the same `process_execution_id`; cancellation cannot
    infer never-started from a missing `PROCESS_STARTED` event;
  - for confirmed-running/transferring work, deliver an assignment/fence-scoped
    cancel and wait for process containment/exit, output disposition, cleanup,
    and resource release;
  - for a SLURM assignment before durable `SUBMITTING`, suppress the external
    call and close/unbind only after exact durable proof that no call can occur;
  - for durable `SUBMITTING` without a known handle, retain the operation as
    cancellation-settling while reconciling the stable submission identity;
    never call `sbatch` again or infer non-acceptance from scheduler absence;
  - for an exact accepted handle, issue the idempotent profile-owned `scancel`
    primitive. A successful invocation proves only requested, not containment,
    terminal lifecycle, result disposition, or profile-slot release;
  - for a registered/granted bootstrap, deliver the exact Loom assignment/fence
    control where reachable as well as external cancellation, retain exact
    current-fence result/output facts, and wait for scheduler/bootstrap/process
    evidence to settle without allowing a second start;
  - if success/output commit wins, retain truthful success but do not unlock a
    descendant;
  - if the agent is disconnected or a control result is ambiguous, keep the
    assignment bound/unknown and cancellation pending.
- Define cancellation ordering against grant:

  ```text
  cancellation control durable before grant -> grant/start prohibited
  grant durable, no start intent             -> revoke start, prove never launched
  start intent durable, outcome unknown      -> reconcile/contain; never relaunch
  process start confirmed                    -> control active process, wait
  terminal success commit before cancel CAS -> retain success, stop descendants
  ambiguous/disconnected                    -> remain cancelling/unknown
  ```

- Ensure cancellation and drain do not discard retained result/output needed to
  prove terminal truth. Artifact cleanup follows explicit disposition and
  authority acknowledgement.
- Add joined control/cancellation status for requested actor/principal reference,
  target scope, coordinator request revision, authority cancellation epoch,
  requested/effective/settling/terminal state, safe result code, affected
  availability, active assignments/submissions, external cancel observations,
  and residual unknown work. Preserve the other owner-labelled lifecycle/
  scheduling/execution/external-scheduler/transfer/health axes;
  stale operational state cannot overwrite authority terminal truth. Never expose raw
  config, certificate subject, paths, commands, tokens, provider data, or unsafe
  evidence.
- Add authenticated Python/CLI/direct/HTTP operations and abstract operational
  examples for drain, edit trusted config, reload, resume, cancel, inspect, and
  wait using only `machine-A` and `machine-B`.
- Clarify credential/config interactions: credential removal prevents future
  connections but is not an execution fence; coordinator process-epoch change
  is not containment; a reload cannot silently retire a session with unresolved
  work.

Out of scope:

- Sending configuration remotely, per-provider hot mutation, automatic discovery
  or provisioning, hidden force, kill-by-unverified PID, or releasing because a
  machine is offline.
- Manually closing/requeueing unknown accepted work, different-session takeover,
  process adoption after restart, timeout/PID/reboot inference, automatic
  failover, or coordinator HA. Phase 9 owns guarded recovery.
- New scheduler/resource semantics, preemption, checkpointing, live migration,
  automatic managed-agent/SLURM fallback, allocation-fed agents, generic
  external-scheduler plugins, or SLURM lifecycle changes beyond composing the
  merged Phase 7B exact target/control evidence.

Assumptions:

- Trusted local config changes are made out-of-band under protected file
  permissions. Loom validates them before adoption.
- Providers can retain old implementation instances long enough to reconcile
  their own live claims, or reload must remain blocked/withdrawn.
- Process cancellation is cooperative/user-process containment, not a hostile
  workload sandbox. Uncertainty remains visible.

## Fixed Contracts And Private Discretion

### Serialized control command

Conceptually:

```python
@dataclass(frozen=True)
class AgentControl:
    operation_id: str
    kind: Literal["drain", "resume", "reload"]
    agent_id: str
    expected_session_id: str
    expected_config_revision: str
    pool: str | None
    cancel_active: bool
    reason: str
```

Coordinator scheduling reload is deliberately not an `AgentControl`:

```python
@dataclass(frozen=True)
class CoordinatorSchedulingReload:
    operation_id: str
    expected_scheduling_epoch: str
    reason: str
```

Both requests contain no configuration payload. Their authenticated target and
expected owner revision determine which protected local configuration is read.

The authenticated adapter supplies principal; it is not a field with authority.
The coordinator records intent before delivery. The agent records effect before
result. Reconciliation may repeat the exact command but may not apply a changed
one under the same ID.

### Reload sequence

```text
withdraw availability/work request
  -> read and validate complete trusted local config
  -> identify every agent-owned live durable component reference
  -> build new active provider/capability bindings plus exact retained bindings
  -> wait or deliver explicit cancellation
  -> prove replaced physical resources safely released or retained
  -> atomically install one configuration/inventory epoch
  -> observe and reconcile
  -> publish fresh availability only on explicit resume/readiness
```

At every interruption, pending work and old live claims remain associated with
their exact original descriptors/configuration revisions. Failure never yields
partially replaced offers or partially replaced component registries.

Coordinator scheduling configuration follows a separate owner-local sequence:

```text
pause new scheduling decisions
  -> read and validate complete trusted site policy/components
  -> identify coordinator-owned pending-work/assignment/submission references
  -> build new active planner/rule/scorer/policy/profile bindings
     plus exact retained bindings
  -> atomically install one coordinator scheduling epoch
  -> resume snapshots; incompatible agent opportunities or unavailable profiles
     remain ineligible
```

Neither operation writes the other owner's state. Their shared boundary is the
versioned claim/capability contract already checked during feasibility and final
assignment CAS. Profile reload is likewise owner-local: active profiles serve
fresh route admission while retained profile descriptors serve exact
nonterminal submissions. Reload never converts a retained SLURM target into a
managed target or vice versa.

### Cancellation state by assignment

The run-wide barrier precedes assignment controls:

```text
coordinator CANCELLATION_REQUESTED durable
  -> authority CANCELLATION_EFFECTIVE(epoch) by CAS
  -> readiness/bind/grant/descendant/retry reject epoch
  -> coordinator fans out exact assignment controls
  -> authority terminal cancellation only after every assignment settles
```

A crash at any arrow repeats the same cancellation operation. If the authority
reports that the run was already terminal, that terminal truth wins and no
cancellation epoch is fabricated. A stage terminal fact racing after the epoch
may remain truthful, but cannot unlock a new descendant.

| Assignment position | Required cancellation action | When capacity may release |
| --- | --- | --- |
| No assignment | Close/cancel prepared work under authority | After authority commit |
| Bound, not accepted | Revoke delivery and prove agent cannot accept | After exact acknowledgement and cleanup |
| Accepted, not granted | Persist control; prevent grant; abort/reconcile claim | After exact abort/release |
| Granted, no start intent | Revoke start and prove launcher was never invoked | After exact never-started acknowledgement and claim cleanup |
| Start intent, outcome unknown | Reconcile exact process identity; do not infer or relaunch | After terminal or positive containment and cleanup |
| Confirmed running | Deliver fenced control and contain process | After terminal/containment and cleanup |
| Output transfer | Decide truthful success/cancel disposition; retain evidence | After authority acknowledgement and transfer cleanup |
| SLURM intent, before `SUBMITTING` | Suppress call and prove dispatcher cannot invoke it | After exact no-call close/unbind |
| SLURM `SUBMITTING`, handle unknown | Reconcile stable operation; do not resubmit or infer absence | Only after exact terminal/positive containment in Phase 9 |
| SLURM handle accepted, bootstrap not granted | Block grant and request exact-handle external cancel | After exact scheduler/bootstrap containment and authority close |
| SLURM bootstrap granted/running | Send fenced Loom control plus exact-handle external cancel; retain result | After terminal/containment and result/output disposition |
| Terminal committed | Preserve terminal truth | Already governed by normal release |
| Disconnected/ambiguous | Keep bound unknown and cancellation pending | Never from timeout alone |

### Private discretion

Configuration parser layout, command delivery loop, signal escalation timing
within existing containment policy, status formatting, and internal control table
shape remain private. The executor may not add remote config content, weaken
expected-state checks, release unknown claims, or collapse ordinary control with
privileged Phase 9 recovery.

## Proportionality

- Reuses existing authenticated application operations, agent outbox, exact
  assignments/providers, configuration fingerprints, and process controls.
- Adds only ordinary operator behavior and complete cancellation required to run
  a persistent pool safely.
- Privileged irreversible recovery remains isolated in Phase 9 so routine drain/
  reload/cancel review is not conflated with takeover authority.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Availability withdraws before mutation | Agent control state machine | Reload/drain request | New work on changing resources | Barrier tests at every control step |
| Pending work and live claims retain exact implementation/config at their owner | Descriptor-keyed registries plus coordinator/agent durable references | Reload/provider/planner/rule/scorer change | Semantic reinterpretation, stranded work, or wrong token release/binding | Pure-pending, assigned/live, restart, drain, and old/new component tests |
| Each config replacement is owner-local, whole, and atomic | Agent config owner or coordinator scheduling-config owner | Invalid/partial config or cross-owner version skew | Mixed inventory/policy or hidden distributed swap | Full-plan validation, agent-first/coordinator-first skew, incompatibility, and failure tests |
| Nonterminal SLURM work retains its exact profile implementation/configuration | Coordinator profile registry plus durable submission references | Profile disable/removal/reload | Uninspectable job, wrong cancel, or reinterpreted request | Live submission across reload/restart; rejected non-retaining swap |
| Remote control cannot supply config | Codec/application authorizer | Crafted payload | Code/secret/config injection | Unknown/extra/path/import-field tests |
| Cancellation request survives before authority availability | Coordinator cancellation store/reconciler | Authority outage or response loss | Lost user intent or false effective state | Request commit/restart/replay and requested-versus-effective tests |
| One authority cancellation epoch stops lifecycle creation | Authority CAS + shared readiness/bind/grant/retry predicates | Concurrent preparation, grant, success, or retry | Work/descendants after cancel | Cancellation-epoch barriers across every lifecycle CAS |
| Pre-grant unbind needs exact proof | Authority/agent reconciliation | Disconnection/ambiguous control | Duplicate later launch | Cancel/grant/reconnect tests |
| Post-grant cancellation distinguishes never-started from start-unknown | Agent start journal/process owner | Grant/start/control race | Duplicate or uncontained process | Barriers before start intent, launcher return, and start event |
| Running capacity releases only after containment | Agent process/resource owner | Client timeout/control send | Resource collision | Real-process cancellation tests |
| SLURM cancellation blocks grant first and treats `scancel` only as requested | Authority epoch plus SLURM dispatcher/bootstrap/control projector | Submit/bootstrap/grant/cancel/status races | New authored start, false terminality, or unsafe retry | Every SLURM state crossed with effective cancel and observation lag |
| Terminal facts remain truthful | Authority terminal CAS | Cancel/result race | False history | Success/failure/cancel before/after-epoch table |
| Control/status is scoped, owner-labelled, and redacted | Authorizer/projector | Operator/client request or unavailable owner | Unauthorized mutation, leak, or false flattened state | Role/object/pool, revision/freshness precedence, and redaction tests |

## Implementation Slices

1. Add versioned control commands/states/receipts, per-action scopes,
   principal/content idempotency, expected revisions, serialized coordinator/
   agent transitions, and direct/HTTP negative/conformance tests.
2. Implement withdraw-first drain/resume and complete trusted agent-config epoch
   reload, plus separate serialized coordinator scheduling-config reload, with
   owner-local validation, active/descriptor-retained bindings, owner-checked
   garbage collection, atomic swap/rejection, retained live SLURM profiles,
   cross-owner compatibility skew, failure/reconnect behavior, and pool/GPU/
   profile removal examples.
3. Implement durable coordinator cancellation request -> canonical authority
   cancellation-epoch reconciliation, gate every readiness/creation CAS, then
   fan out across never-ready, prepared, ungranted, granted, transferring,
   disconnected, and terminal managed/SLURM states with authority-outage,
   submit/bootstrap/grant/terminal races. Compose exact-handle `scancel` and
   bootstrap control without treating either response as containment.
4. Add owner-labelled joined status/audit, CLI/Python operations, operational docs, multi-agent
   reconfiguration/cancellation E2E, and canonical contract propagation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Control models/views remain narrow and cheap | Import and public-operation surface |
| Unit | Required | Expected versions, owner-local config validation, retained-descriptor/profile reachability, cancellation request/epoch states | Replay/change conflicts, full validation, no partial/cross-owner swap, no premature retained-binding collection, requested/effective/settling transitions |
| Contract | Required | Direct/HTTP/operator, authority cancellation, component/provider/profile retention, and SLURM cancel evidence | Role/scope/body actor negatives; same cancellation outcome/idempotency; pure-pending and old/new provider/profile lifecycle; agent versus coordinator reload ownership; rejected non-retaining reload; `scancel` is request only |
| Integration | Required | Control delivery, independent config epoch replacement, cancellation and live managed/SLURM races | Agent-first/coordinator-first contract skew becomes ineligible then compatible; restart with pending custom work/live claim/submission; authority outage after request/before epoch; barriers at readiness, submit, bootstrap, bind, grant, before/after start intent, launcher outcome/event, terminal result, upload, commit, release |
| E2E / opt-in | Required loopback | Operable mixed-target pool | Drain/reload/resume resources/profiles and cancel a mixed managed/SLURM multi-stage run while another continues |

Targeted commands:

    uv run pytest -q tests/unit/loom/pipeline/stores/test_sqlite_authority.py
    uv run pytest -q tests/unit/loom/pipeline/execution/test_managed_local.py
    uv run pytest -q tests/unit/loom/queue/test_agent_sessions.py tests/unit/loom/queue/test_local_daemon.py tests/unit/loom/queue/test_slurm_ready_stage.py
    uv run pytest -q tests/unit/loom/cli/test_queue.py
    uv run pytest -q tests/contracts/test_local_daemon_authority_contract.py
    uv run pytest -q tests/integration/queue/test_local_daemon_production.py
    uv run pytest -q tests/integration/queue/test_agent_session_transport.py tests/integration/queue/test_slurm_ready_stage.py
    uv run pytest -q tests/package/test_import_boundaries.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: mutating a live provider, reinterpreting pending work through a new
  component, pretending agent/coordinator configuration swaps atomically,
  prematurely collecting retained descriptors, accepting config from network, mixed
  inventory, losing a request before authority intent, treating coordinator
  request or a sent cancel as the effective barrier/containment, losing truthful terminal facts, or
  treating granted-without-observed-start as never launched, or allowing
  credentials/generation to act as process fences; dropping a retained SLURM
  profile; treating `scancel` success or scheduler absence as containment; or
  granting a bootstrap after effective cancellation.
- Review focus: withdraw-first ordering, complete owner-specific durable-reference
  sets, independent agent/coordinator active/retained registry swaps and
  compatibility negotiation, provider retention,
  coordinator-request/authority-epoch cancellation ownership, every lifecycle
  gate, managed/SLURM cancellation/start state table, retained profile identity,
  exact-handle controls, owner-labelled status, role scopes, and race tests.
- Stop if: providers cannot retain/reconcile old claims; pending work cannot
  reconstruct its exact planner/rule/scorer identity; reload would require
  partial hot mutation; cancellation cannot identify exact assignment/fence; or
  current authority cannot preserve success while blocking descendants; a live
  submission cannot retain the profile needed to inspect/cancel it; or external
  cancel would be represented as terminal containment.
- Accepted debt: unknown cancellation may remain pending until Phase 9 guarded
  recovery. This is required correctness, not a retry bug.

## Executor Handoff

- Read `AGENTS.md`, `.codex/workflows/roadmap-stage-implementation.md`,
  `.codex/prompts/phase-loop-management.md`, and this file's `Metadata`,
  `Objective And Context`, `Current Source And Harness`, `Scope`, `Fixed
  Contracts And Private Discretion`, `Implementation Slices`, `Test And
  Validation Plan`, `Risks, Review, And Stops`, and `Executor Handoff`
  sections.
- Keep ordinary controls and cancellation separate from Phase 9 privileged
  recovery even if internal serialization helpers are shared.
- Decisions not to revisit: local trusted reload, withdraw first, exact
  descriptor retention for referenced pending/live state, reject-before-swap on
  retention failure, coordinator request then authority cancellation epoch
  before managed/SLURM fan-out, retained profile identity, `scancel` as request
  only, truthful terminal facts, owner-labelled status, no timeout-based
  release, and a fresh hard-cut schema with no compatibility or migration path.
- Escalate any need for remote config, hidden force, weak containment, or changed
  retry ownership.

## Workflow State

- Manager preparation: complete on clean merged Phase 7B baseline; worktree,
  base, current source owners, targeted commands, and hard-cut boundary recorded
- Expanded planning: required by mutable configuration and cancellation races;
  one bounded `loom_phase_planner` refinement pending
- Implementation: pending
- Refiner: not used
- Pre-submit gate: pending
- Independent review: expected because control races can release live resources
  or authorize mutation; confirm during preparation
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
