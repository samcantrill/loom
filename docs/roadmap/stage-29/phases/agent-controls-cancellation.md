# Phase 7 Execution Plan: Agent Controls And Stage-Aware Cancellation

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 7
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p7-agent-controls-cancellation`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop` after Phase 6 remotely merges
- PR target: `develop`
- PR title: `feat(scheduling): add agent controls and cancellation`
- Dependencies: Phase 6 merged with complete local/remote stage lifecycle,
  authenticated operator views, configured resources/providers, exact live
  claims, and joined status
- Workflow path: expanded because configuration mutation, availability,
  cancellation, process containment, and authorization races interact
- Blockers: Phase 6 remote merge

## Objective And Context

- Vertical outcome: an authorized operator can drain, resume, or reload an
  agent's trusted local pool configuration, including withdrawing selected GPUs
  from future use, without changing resources beneath live assignments. A client
  can cancel a run and Loom stops new descendants, handles every prepared/
  assigned/running/transferring stage truthfully, and reaches terminal
  cancellation only after exact completion or positive containment.
- Earlier dependency: Phases 2–6 establish the exact claims, provider/config
  identities, assignment fences, remote control transport, and output lifecycle
  that controls must preserve.
- Later work explicitly out of scope: Phase 8 adds same-session restart,
  containment-gated closure of already-unknown work, and different-session
  replacement. Phase 7 never resolves uncertainty merely to make an operation
  finish.

## Current Source And Harness

- Reuse authenticated operator/client/agent views, principal/object/pool scopes,
  idempotency receipts, expected revisions, agent journal/outbox, assignment
  controls, process containment, transfer state, provider registries, and safe
  status/audit from prior phases.
- Rediscover existing cancellation/status/reliability operations and local
  process cancellation helpers on the phase branch.
- Reuse fake clocks/networks, real process barriers, multi-agent loopback,
  provider partial-failure fixtures, and configuration/fingerprint tests.
- Remote control payloads remain versioned inert data. Trusted configuration is
  read locally by the daemon from protected deployment state.

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
- Reload reads the daemon's trusted local configuration. No remote payload may
  contain replacement config, code, import target, provider object, secret, path,
  or command. The request asks the daemon to reload; it does not describe what
  to load.
- Validate the complete replacement plan before mutation: agent/pool mapping,
  principal scopes, resident projects/environments/executors, validator/planner/
  provider/claim-contract descriptors and non-secret configuration fingerprints,
  units/granularity, GPU modes/device uniqueness, one cross-pool capacity domain,
  storage/retention, and collisions.
- Reload first withdraws all affected availability, then waits for safe release
  or applies explicitly requested cancellation. Atomically swap one complete
  config/inventory identity only when no affected live process/claim/transfer
  remains. Never publish mixed old/new inventory.
- Preserve exact old implementation objects/config identities only while old
  live claims/reconciliation require them. A new provider/config cannot adopt an
  old live token. If reload fails, retain the old complete plan and leave
  capacity safely withdrawn or explicitly resumable.
- Support local pool reconfiguration by editing trusted config and invoking
  reload. Removing a GPU, CPU capacity, pool view, project, or provider affects
  future availability only after drain/release; it never changes a live
  assignment's claim.
- Complete run cancellation at stage granularity:
  - commit run cancellation intent once and stop preparing/assigning new work;
  - prevent any descendant from becoming assignable after intent, even if an
    upstream success later wins a race;
  - terminalize never-ready descendants and never-assigned prepared work under
    existing authority cancellation/block rules;
  - for assignment-bound pre-grant work, clear binding only after an exact agent
    acknowledgement proves grant/start cannot occur and staged inputs/claims are
    released;
  - for granted/running/transferring work, deliver an assignment/fence-scoped
    cancel and wait for process containment/exit, output disposition, cleanup,
    and resource release;
  - if success/output commit wins, retain truthful success but do not unlock a
    descendant;
  - if the agent is disconnected or a control result is ambiguous, keep the
    assignment bound/unknown and cancellation pending.
- Define cancellation ordering against grant:

  ```text
  cancellation control durable before grant -> grant/start prohibited
  grant fence durable before cancellation   -> control active process, wait
  terminal success commit before cancel CAS -> retain success, stop descendants
  ambiguous/disconnected                    -> remain cancelling/unknown
  ```

- Ensure cancellation and drain do not discard retained result/output needed to
  prove terminal truth. Artifact cleanup follows explicit disposition and
  authority acknowledgement.
- Add joined control/cancellation status for requested actor/principal reference,
  target scope, expected/current revision, safe state/result code, affected
  availability, active assignments, and residual unknown work. Never expose raw
  config, certificate subject, paths, commands, tokens, provider data, or unsafe
  evidence.
- Add authenticated Python/CLI/direct/HTTP operations and abstract operational
  examples for drain, edit trusted config, reload, resume, cancel, inspect, and
  wait using only `machine-A` and `machine-B`.
- Clarify credential/config interactions: credential removal prevents future
  connections but is not an execution fence; coordinator generation change is
  not containment; a reload cannot silently retire a session with unresolved
  work.

Out of scope:

- Sending configuration remotely, per-provider hot mutation, automatic discovery
  or provisioning, hidden force, kill-by-unverified PID, or releasing because a
  machine is offline.
- Manually closing/requeueing unknown accepted work, different-session takeover,
  process adoption after restart, timeout/PID/reboot inference, automatic
  failover, or coordinator HA. Phase 8 owns guarded recovery.
- New scheduler/resource semantics, preemption, checkpointing, live migration,
  or delegated SLURM changes.

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

The authenticated adapter supplies principal; it is not a field with authority.
The coordinator records intent before delivery. The agent records effect before
result. Reconciliation may repeat the exact command but may not apply a changed
one under the same ID.

### Reload sequence

```text
withdraw availability/work request
  -> read and validate complete trusted local config
  -> identify affected live claims/transfers/providers
  -> wait or deliver explicit cancellation
  -> prove affected set safely released
  -> atomically install one config/inventory revision
  -> observe and reconcile
  -> publish fresh availability only on explicit resume/readiness
```

At every interruption, old live claims remain associated with their original
descriptor/config revision. Failure never yields partially replaced offers.

### Cancellation state by assignment

| Assignment position | Required cancellation action | When capacity may release |
| --- | --- | --- |
| No assignment | Close/cancel prepared work under authority | After authority commit |
| Bound, not accepted | Revoke delivery and prove agent cannot accept | After exact acknowledgement and cleanup |
| Accepted, not granted | Persist control; prevent grant; abort/reconcile claim | After exact abort/release |
| Granted/running | Deliver fenced control and contain process | After terminal/containment and cleanup |
| Output transfer | Decide truthful success/cancel disposition; retain evidence | After authority acknowledgement and transfer cleanup |
| Terminal committed | Preserve terminal truth | Already governed by normal release |
| Disconnected/ambiguous | Keep bound unknown and cancellation pending | Never from timeout alone |

### Private discretion

Configuration parser layout, command delivery loop, signal escalation timing
within existing containment policy, status formatting, and internal control table
shape remain private. The executor may not add remote config content, weaken
expected-state checks, release unknown claims, or collapse ordinary control with
privileged Phase 8 recovery.

## Proportionality

- Reuses existing authenticated application operations, agent outbox, exact
  assignments/providers, configuration fingerprints, and process controls.
- Adds only ordinary operator behavior and complete cancellation required to run
  a persistent pool safely.
- Privileged irreversible recovery remains isolated in Phase 8 so routine drain/
  reload/cancel review is not conflated with takeover authority.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Availability withdraws before mutation | Agent control state machine | Reload/drain request | New work on changing resources | Barrier tests at every control step |
| Live claim retains original implementation/config | Agent registry/journal | Reload/provider change | Wrong token release/binding | Old/new provider tests |
| Config replacement is whole and atomic | Local config owner | Invalid/partial config | Mixed inventory/policy | Full-plan validation/failure tests |
| Remote control cannot supply config | Codec/application authorizer | Crafted payload | Code/secret/config injection | Unknown/extra/path/import-field tests |
| Cancellation stops descendants immediately | Coordinator/orchestrator | Upstream success race | Work after cancel | Readiness/cancel barriers |
| Pre-grant unbind needs exact proof | Authority/agent reconciliation | Disconnection/ambiguous control | Duplicate later launch | Cancel/grant/reconnect tests |
| Running capacity releases only after containment | Agent process/resource owner | Client timeout/control send | Resource collision | Real-process cancellation tests |
| Success remains truthful | Authority terminal CAS | Cancel/result race | False history | Success-before/after-cancel table |
| Control/status is scoped and redacted | Authorizer/projector | Operator/client request | Unauthorized mutation/leak | Role/object/pool and redaction tests |

## Implementation Slices

1. Add versioned control commands/states/receipts, per-action scopes,
   principal/content idempotency, expected revisions, serialized coordinator/
   agent transitions, and direct/HTTP negative/conformance tests.
2. Implement withdraw-first drain/resume and complete trusted-config reload with
   validation, atomic swap, old-provider retention, failure/reconnect behavior,
   and pool/GPU removal examples.
3. Implement full run cancellation fan-out across never-ready, prepared,
   ungranted, granted, transferring, disconnected, and terminal states with
   grant/success/outage race tests.
4. Add joined status/audit, CLI/Python operations, operational docs, multi-agent
   reconfiguration/cancellation E2E, and canonical contract propagation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Control models/views remain narrow and cheap | Import and public-operation surface |
| Unit | Required | Expected versions, config validation, state transitions | Replay/change conflicts, full validation, no partial swap |
| Contract | Required | Direct/HTTP/operator and provider retention behavior | Role/scope/body actor negatives; old/new provider lifecycle |
| Integration | Required | Control delivery, cancellation and live process/resource races | Barrier at withdraw, grant, start, exit, upload, commit, release |
| E2E / opt-in | Required loopback | Operable multi-agent pool | Drain/reload/resume resources and cancel multi-stage run while another continues |

Targeted commands are fixed during phase preparation. Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: mutating a live provider, accepting config from network, mixed
  inventory, treating a sent cancel as containment, losing truthful success, or
  allowing credentials/generation to act as process fences.
- Review focus: withdraw-first ordering, complete affected-set calculation,
  provider retention, cancellation state table, role scopes, and race tests.
- Stop if: providers cannot retain/reconcile old claims; reload would require
  partial hot mutation; cancellation cannot identify exact assignment/fence; or
  current authority cannot preserve success while blocking descendants.
- Accepted debt: unknown cancellation may remain pending until Phase 8 guarded
  recovery. This is required correctness, not a retry bug.

## Executor Handoff

- Read this file, Phase 6 completion record, manifest control/security
  constraints, and planning FR-2, FR-10, FR-14–FR-16, FR-19, FR-21, FR-23,
  FR-25, and FR-26.
- Keep ordinary controls and cancellation separate from Phase 8 privileged
  recovery even if internal serialization helpers are shared.
- Decisions not to revisit: local trusted reload, withdraw first, old claim
  identity retention, cancel intent before fan-out, truthful success, and no
  timeout-based release.
- Escalate any need for remote config, hidden force, weak containment, or changed
  retry ownership.

## Workflow State

- Manager preparation: pending Phase 6 merge, worktree/base recording, and
  exact control/config/process test rediscovery
- Expanded planning: required by mutable configuration and cancellation races;
  phase plan finalized
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
