# Phase 9 Execution Plan: Restart And Guarded Unknown-Work Recovery

## Metadata

- Status: blocked
- Roadmap stage and phase: Stage 29, Phase 9
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9-restart-guarded-recovery`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`;
  `/home/can134/work/active/loom-worktrees/stage-29-p9-restart-guarded-recovery`
- Base revision: clean `origin/develop` at
  `44d06f329be6660fb12ab3ccc37cc443681733f2`
- PR target: `develop`
- PR title: `feat(scheduling): add guarded restart and recovery`
- Dependencies: Phases 1–3D, 4A, 5A, 6, 7B, and 8A merged with durable
  identities/stores, execution fences, managed and SLURM process/output facts,
  authenticated operator controls, retained provider/profile identity,
  cancellation, and reliability retry ownership. Phase 8A merged as `900a461`.
- Workflow path: expanded because privileged irreversible fencing, process
  evidence, stale results, retry, and session replacement interact
- Blockers: correction budget 3/3 is exhausted. The final executor pass committed
  only the resident-worker service-injection hard cut as `ef3be2f` and then
  reported it could not complete the remaining supervisor, restart, recovery,
  SLURM, retry, replacement, API, and validation scope within its turn. There is
  no unresolved behavior decision. The smallest workflow-compliant remedy is a
  fresh Phase 9A closure from current `origin/develop`, selectively reusing the
  validated `ef3be2f` source change as read-only evidence rather than continuing
  this branch or spending a fourth correction.

## Objective And Context

- Vertical outcome: an agent can restart from its intact durable state without
  duplicating a managed launch, and a coordinator can reopen SLURM submission/
  bootstrap records without resubmitting or granting another authored root,
  while the Phase 5 coordinator/authority-restart
  contract remains compatible with the new recovery records. Granted work continues or
  remains explicitly unknown until reconciled. When ordinary reconciliation
  cannot establish terminal truth, a separately authorized operator can close
  one exact positively contained assignment and allow existing reliability
  policy to consider a fresh attempt. A replacement agent session is admitted
  only after the complete unresolved old-session set is safe.
- Earlier dependency: Phase 8 deliberately leaves disconnected/ambiguous
  managed or SLURM work bound. This phase supplies the only path that may fence
  such work without an authoritative terminal event.
- Later work explicitly out of scope: no later Stage 29 phase adds stronger
  failover. Coordinator HA, machine power fencing, checkpoint migration, and
  automatic takeover require separate future designs.

## Current Source And Harness

- Reuse all durable coordinator/authority/agent/transfer/control facts, expected-
  state operations, execution fences, role locks, component/config identities,
  outbox acknowledgements, SLURM submission/bootstrap/observation facts,
  retained profile descriptors, and status/audit from earlier phases.
- The current managed execution boundary is not restart evidence. Embedded
  execution stores `_ManagedWorkerHandle` thread objects only in
  `SQLiteAgentJournal._process_handles`; the remote agent stores `Popen` objects
  only in `LocalDaemonAgentHttpClient._processes` while its durable workspace
  records only a PID and `process_execution_id`. Neither owner can rebind a live
  or contained process to exact `(assignment_id, process_execution_id)` evidence
  after the agent process exits. PID/workspace presence or absence cannot repair
  that gap.
- The embedded helper also accepts optional in-process execution services
  (`executor`, artifact-store/resource-validator/plugin objects, and a Python
  `process_launcher`). The production daemon supplies none of them, and the
  remote resident path already supports only the fixed serializable worker
  request. They are an obsolete test/helper seam, not a supported managed
  execution contract. The approved compatibility-free cut removes them from the
  managed path instead of making arbitrary Python objects serializable.
- The current `SlurmReadyStageProfile` similarly supplies operation discovery,
  `squeue`/`sacct` observation, `scancel`, and job-private capability revocation,
  but no operation can produce an exact positive-containment receipt. Those
  mechanisms remain reconciliation/control inputs, never recovery evidence.
- Reuse the current fixed resident-stage-worker request/result path, but replace
  both managed handle maps with the one agent-side supervisor boundary fixed
  below. `record_retry_decision_for_stage_result()` remains the existing
  reliability evaluator and `RunOrchestrator` already consumes authority-owned
  retry decisions, but production `LocalDaemonExecution` does not currently
  compose that evaluator. Generalize/compose this existing path as fixed below;
  do not create recovery-local retry rows or policy. Rediscover SQLite
  corruption/schema behavior and user-service documentation conventions only
  where the slices below require them.
- Use real child-process barriers plus fake clocks/transports. Recovery tests must
  exercise process/output state, not only mock status flags.
- Full Stage 29 validation and test-summary evidence are required in this final
  phase after phase-specific tests pass.

## Scope

In scope:

- Complete same-session agent restart:
  - acquire the exact role lock before opening mutable state;
  - reconstruct selected component/config identities required by live claims;
  - open the exact current agent journal/supervisor schemas or fail closed;
  - publish zero availability and no work request;
  - recover accepted/grant/start/process/control/transfer/result/output/outbox
    facts;
  - query the mandatory configured agent process supervisor through the exact
    durable launch identity fixed below;
  - never mint a second launch operation or managed root for an existing start
    fence;
  - authenticate/reconcile with the stable coordinator ID/current process epoch,
    replay ordered old-issuer events from the first unacknowledged sequence,
    finish output publication/cleanup, then observe and publish a fresh offer.
    The coordinator alone invokes the authenticated authority view; the agent
    receives no authority credential or direct access.
- Distinguish process restart from database loss. Missing, corrupt, incompatible,
  or copied required state is not an empty restart and must not produce fresh
  capacity. Return a safe blocked diagnostic for operator action.
- Hard-cut both production managed paths to the supervisor-backed schema and
  protocol. Remove the embedded thread handle and remote-agent `Popen` map as
  lifecycle/containment owners; do not add a legacy branch. An agent journal,
  workspace, or role root created before this supervisor binding exists is
  unsupported state: ordinary open fails before session resume or offer, reports
  `managed_supervisor_state_requires_reinitialization`, and never treats the old
  PID, missing handle, result file, or empty-looking tables as containment. No
  in-place schema/data migration or old-process adoption is permitted. A fresh
  root/session may be initialized only through the existing explicit
  initialization/replacement workflow after old work is externally resolved;
  unresolved old work remains fenced and unknown.
- Retain Phase 5 as the sole implementation owner of coordinator and authority
  outage/restart from intact state. Phase 9 adds no second coordinator- or
  authority-restart state machine; its regression coverage proves the new
  recovery decisions, evidence, receipts, and session-replacement facts survive
  those established restarts and that a correctly reconciled generation change
  still cannot invalidate a current authority execution fence.
- Complete coordinator restart reconciliation for every Phase 7 SLURM stage
  dispatch state:
  - reopen the exact retained profile descriptor/configuration or fail closed;
  - leave pre-call intent eligible only for the already-recorded ordinary
    dispatcher transition, while any durable `SUBMITTING` state forbids a new
    `sbatch` invocation;
  - inspect exact known handles and reconcile unknown handles through stable
    scheduler-visible operation identity and authenticated bootstrap
    registration;
  - treat zero unproven matches as unknown and multiple matches as conflict;
  - reconcile bootstrap grant/start/result/output facts under the exact issuer
    epoch and fence, never granting a second authored root;
  - preserve separate dispatch, scheduler, bootstrap/process, transfer/result,
    control, and authority axes through restart.
- Provide abstract user-level service auto-restart guidance for coordinator,
  agent, and the separate agent process supervisor, including protected
  configuration, dependency/start ordering, restart backoff, separate state
  roots/locks, and safe readiness checks. The supervisor must be healthy before
  the agent can resume or offer. Do not claim process adoption after supervisor
  continuity is lost.
- Add an exact assignment-level manual recovery operation for accepted unknown
  work. Require:
  - privileged recovery action plus exact run/object and target-specific pool/
    agent or SLURM-profile scope;
  - stable recovery operation ID and canonical request digest;
  - exact run, stage, attempt, stage-work, assignment, target-specific agent/
    session or SLURM profile/submission operation/job/bootstrap incarnation,
    `process_execution_id`, execution fence, and expected current state;
  - safe positive-containment evidence resolved by a configured trusted evidence
    owner, not a body assertion;
  - explicit terminal outcome, bounded reason, and optional request for existing
    reliability policy to consider a next attempt.
- Define positive containment narrowly: evidence must establish that the exact
  execution boundary for the assignment cannot still execute or later resume.
  For a managed target, only the configured agent process supervisor's durable
  receipt tied to the complete launch identity may qualify. For a SLURM target,
  only the retained profile's optional configured site-owned containment helper
  may qualify, and its receipt must tie positive terminal containment to the
  exact profile/configuration, submission operation, scheduler cluster/job
  handle, bootstrap incarnation, `process_execution_id`, and execution fence.
  A profile without that helper, a helper identity/configuration mismatch, or
  an unavailable/unknown helper result leaves work unknown. Queue/accounting
  absence, `scancel` success, retention expiry, scheduler timeout, job-name/PID/
  hostname text, unauthenticated reboot text, credential revocation, coordinator
  process-epoch change, or plain “mark failed” never qualifies alone.
- Persist a recovery decision in one coordinator transaction after revalidating
  the complete expected target-specific assignment/session/physical-claim/
  provider-preparation or SLURM operation/job/bootstrap, control/transfer/
  result/outbox state. Any complete verified current-fence terminal fact already
  retained by the coordinator or reachable execution owner must first
  follow its ordinary authority path, or must block recovery with an explicit
  unresolved-result reason. Success/output is finalized and committed and
  supersedes recovery; definitive failure/cancellation commits its own outcome
  and cannot be overwritten by the operator's requested outcome. Recovery intent freezes
  ordinary assignment/control/retry/release mutation but continues to durably
  retain exact-current-fence terminal facts in a bounded quarantine. Recheck
  that quarantine immediately before authority close.
- Close the exact authority execution fence/attempt through a separate
  idempotent expected-state operation. Because coordinator and authority stores
  are independent, model this as a reconciliable recovery saga keyed by the same
  recovery ID; never claim a distributed transaction. Every ordinary terminal
  commit and recovery close uses the same expected execution fence. If a
  terminal fact commits first, recovery becomes `SUPERSEDED_BY_TERMINAL` and
  normal success/failure/cancellation policy owns the result. If close commits
  first, the coordinator fences the assignment and any later execution result
  is stale audit data.
- Only after the old attempt is definitively closed may the existing reliability
  policy decide whether one fresh attempt is permitted. The fresh attempt keeps
  authored run/stage requirements, hard target, and explicit execution route/
  profile alias, but freshly resolves current pool/site/profile policy. It
  copies no offer, candidate score, device ID, resource claim, availability
  revision, transfer identity/authorization, agent session/provider token,
  submission operation, scheduler handle, bootstrap incarnation, or start
  permit. Retry never switches between managed and SLURM routes automatically.
- Keep `record_retry_decision_for_stage_result()` as the sole retry evaluator.
  Generalize its concrete store typing only as needed to accept the existing
  authority-backed reliability-store contract, and expose only its required
  run-status/transaction/decision reads and decision write through the scoped
  coordinator authority adapter. `LocalDaemonExecution` invokes the existing
  terminal reliability transition and then this evaluator after a definitive
  authoritative managed or SLURM `FAILED`/`CANCELLED` commit, including a
  recovery close, never while work is unknown and never after success. Inputs
  are the immutable attempt's recorded retry policy, exact terminal status,
  stable terminal/recovery-close timestamp, and ordinary `ExecutionFailure` or
  cancellation classification. A recovery-requested failure with no worker
  result uses one bounded existing `executor_infrastructure` failure fact tied
  to the `recovery_id` and validated containment receipt; it does not invent a
  second classification policy. `consider_retry=false` passes the disabled
  policy path and durably records a non-retry decision. Exact replay uses the
  same terminal transaction and decision identity. `RunOrchestrator` then
  consumes that authority decision through its existing readiness path; the
  coordinator never inserts a retry row or attempt directly.
- Do not consume automatic retry budget while work is unknown. Record the
  operator-requested outcome and let the reliability owner apply normal policy
  after closure.
- Reject late old-agent or SLURM-bootstrap start facts, results, or uploads from
  mutating the fenced assignment/new attempt. Retain them as bounded stale audit evidence where
  useful. An exact idempotent cleanup/provider-release acknowledgement may close
  only its old claim; it cannot change terminal truth, touch a new attempt, or
  re-advertise capacity without a fresh reconciled offer. Known authoritative
  success always prevents a recovery requeue.
- Keep execution closure and physical resource release as different states.
  Closing/fencing authority permits reliability to consider a new attempt, but
  old-session capacity remains unavailable until each provider reports exact
  release/reconciliation or a positively contained replacement session performs
  a fresh full observation and publishes a new inventory/availability revision.
  For SLURM, authority closure does not itself prove external containment or
  release the retained profile admission slot: exact trusted job/bootstrap
  containment and result disposition must already be recorded, after which the
  coordinator may release that slot idempotently.
- Add different-session replacement as a distinct privileged operation. Read the
  complete unresolved assignment, physical claim/provider preparation, work
  request/delivery, control, transfer, result/output, event, and outbox set for the old
  session. Retire/fence it only when every member is terminal or has exact
  positive containment. Proof for one assignment cannot replace a session that
  owns another unknown assignment.
- Start a replacement session at zero availability and require ordinary
  registration, configuration/contract reconstruction, reconciliation, and
  fresh full provider observation plus inventory/availability publication. A
  copied session ID, credential change, offer expiry, or connection loss is not
  replacement authority. Cooperative empty-set rollover remains the ordinary
  Phase 4 path; this operation is only for a non-empty or unavailable old
  session.
- Add owner-labelled joined recovery/restart/session status and authenticated Python/CLI/
  direct/HTTP operations showing expected/current identities, evidence kind,
  actor/principal reference, decision/result, retry disposition, and residual
  unknown set through bounded safe fields only. Preserve authority lifecycle,
  execution containment, external-scheduler observation, provider/profile-slot
  release, transfer, control, and service-health revisions/freshness separately.
- Add operational examples for coordinator/authority restart, agent restart,
  unknown-work inspection, rejected weak recovery, positively contained
  managed/SLURM recovery, and session replacement using only `machine-A` and
  `machine-B`.
- Run complete Stage 29 compatibility, security, resource, execution, outage,
  cancellation, recovery, package, validation, and test-summary gates.

Out of scope:

- Automatic timeout-based close/retry/reassignment, periodic takeover workers,
  inferred reboot fencing, unverified PID kill/adoption, live migration,
  checkpoint/resume, node power fencing, or exactly-once authored effects.
- Coordinator election/replication/federation, two live coordinators from copied
  state, agent mesh, disaster restoration from lost databases, or silent state
  reconstruction from process lists.
- Arbitrary evidence plugins selected by request, remote shell, credential change
  as containment, hidden force, or recovery that overwrites any verified
  current-fence terminal fact.
- Automatic managed-agent/SLURM fallback, a second `sbatch` for an unknown
  operation, generic external-scheduler evidence plugins, or treating
  `squeue`/`sacct` absence and `scancel` acknowledgement as positive containment.

Assumptions:

- Positive-containment strength is limited to the configured supervisor/process-
  group boundary. Loom manages cooperative user processes and does not claim a
  hostile-code sandbox.
- Even after Loom proves its managed process is contained, authored external
  effects may have occurred before loss. Explicit requeue can repeat them and
  must remain visible in status/audit.
- Required databases and protected identity/config material are backed up and
  operated externally; Stage 29 implements restart, not disaster recovery.
- Each supported SLURM site profile either provides exact positive terminal
  containment evidence tied to the full durable identity or leaves the work
  unknown for operator/external resolution; Loom does not weaken the proof.

## Fixed Contracts And Private Discretion

### Same-session restart state machine

```text
supervisor continuity and protected identity verified
  -> agent role lock acquired
  -> current journal/workspace schemas opened and identity verified
  -> availability forced to zero and work requests suppressed
  -> nonterminal assignment/process/output set reconstructed
  -> each exact supervisor launch/query receipt joined to its journal binding
  -> coordinator authenticated and session resumed
  -> ordered events/results/outputs replayed and durably acknowledged
  -> physical claims released/reconciled or retained unavailable
  -> resources/config observed
  -> fresh availability published
```

The one authoritative managed-process owner is a separately running,
agent-local supervisor. It is mandatory in both production compositions:
embedded/local execution and `LocalDaemonAgentHttpClient` use the same client
and protocol. The supervisor is application infrastructure under `loom.queue`,
not a public scheduler/executor/plugin protocol. `loom.queue` may consume the
import-light `StageWorkerRequest`/`StageWorkerResult` and the fixed resident
worker entrypoint from `loom.pipeline.execution`; `loom.pipeline.execution`,
`loom.scheduling`, stores, and public root imports must not import the supervisor
or queue application. The agent journal/workspace owns assignment, provider,
event, transfer, and result replay facts, but no longer owns an in-memory process
handle or infers process state. The supervisor exclusively owns spawn, process-
group containment, exit observation, and containment evidence.

Initialization creates a protected, separately locked supervisor root and one
stable `supervisor_id` bound to the configured `agent_id`; ordinary start is
open-only. One live supervisor continuity epoch may span any number of agent
daemon restarts. The supervisor uses a protected local authenticated endpoint
and accepts only a fixed, fully materialized resident-worker launch
specification, never an authored command or Python callable. Both managed paths
stage the existing execution-only request in an agent-private assignment
workspace before launch. Exact private file layout, IPC syntax, and process-
group mechanism remain discretionary.

The supervisor root is the protected `supervisor` child of the existing
`agent_root`; it is derived by `LocalDaemonConfig`/`AgentTlsClientConfig`, not an
independently authored path. Explicit fresh agent-root initialization creates
and binds it, the separately running supervisor service opens and locks it, and
the agent daemon/client only opens the matching endpoint. An absent, old, or
mismatched supervisor root fails before resume or availability. This adds no
second public configuration choice and gives both embedded and remote managed
paths the same lifecycle.

The fixed launch specification contains only canonical plain data: the staged
`StageWorkerRequest`, workspace/result locations, the bounded environment
derived from retained provider commands (including GPU bindings), and the
complete identity below. Remove `executor`, `artifact_store_factory`,
`selected_plugin_records`, `resource_validator_registry`, and `process_launcher`
from `run_managed_local_assignment`; do not preserve an alternate callable
branch. Orchestration callbacks that stay in the agent process are not part of
the launch specification. Tests that need start failure or launch races inject
them at the supervisor client/protocol boundary or use the real supervisor's
fault barriers, while lower-level stage-worker tests continue to cover custom
execution services outside managed execution.

The shared staged assignment workspace is private queue application
infrastructure. Extract/generalize the existing queue-owned
`_RemoteAssignmentWorkspace` for both embedded/local and remote agents; it may
import `StageWorkerRequest`, `StageWorkerResult`, and the resident worker
entrypoint from `loom.pipeline.execution`. Move/split the embedded composition
currently named `run_managed_local_assignment` above that queue-owned workspace
and supervisor client, and remove it from the pipeline execution surface. The
pipeline package retains generic worker models/execution and does not import
`loom.queue`. This is the existing documented direction—agent application owns
physical binding/execution—and does not create a public workspace or supervisor
protocol.

### Fixed local resident launch-profile decision

The shared workspace removes any need to serialize or reconstruct
`LocalRunStore`: the parent stages each immutable input before launch, the
resident worker writes outputs under the assignment workspace, and the queue
composition imports those outputs through the ordinary authority path. What is
not currently configured for embedded execution is the child process's exact
Python executable, project root, and durable environment/project/executor
descriptor.

Add one required protected `ResidentWorkerLaunchProfile` value
containing that descriptor plus resolved `project_root` and
`python_executable`. `LocalDaemonConfig` binds one local value, and the existing
remote `ResidentExecutionProfile` composes the same launch-profile value with
its capacity inventory. The launch profile is included in the supervisor
configuration fingerprint and launch digest; initialization records it and
ordinary restart requires an exact match. This preserves one owner for launch
environment while local capacity remains owned by the existing local daemon
capacity fields. Under the approved hard cut, configs and roots without this
value are rejected rather than inferred or migrated.

Rejected alternative: deriving the profile from `sys.executable` and
`Path.cwd()` at agent start would avoid one explicit config value, but a restart
from another environment/directory could silently launch different code under
the retained execution fence.

The durable launch identity is:

```text
supervisor_id + supervisor_continuity_epoch
+ agent_id + session_id
+ assignment_id + process_execution_id + execution_fence
+ launch_operation_id + canonical_launch_spec_digest
```

Before calling the supervisor, the agent journal durably records that complete
identity and the supervisor descriptor/configuration fingerprint. `launch` is
idempotent by `launch_operation_id`: an exact replay returns the same accepted
record and a changed field conflicts. The continuously running supervisor
persists acceptance before spawning one new process group and never spawns a
second root for an accepted operation. Its bounded query result is one of
`NOT_ACCEPTED`, `STARTING`, `RUNNING`, `EXITED`, `CONTAINED`, or `UNKNOWN`, and
echoes the complete identity, supervisor revision, and launch-spec digest.
`EXITED` carries the root exit and optional durable worker-result digest but does
not prove that descendants are gone. `CONTAINED` carries the final exit/result
digest, if any, and is issued only after the supervisor that continuously owned
the boundary has positively observed that its complete process group can no
longer execute or resume. An idempotent `request_stop` is bound to the same
launch identity plus one control operation ID; its acknowledgement means only
requested, and only a later `CONTAINED` query is containment. `UNKNOWN`, endpoint
absence, an identity/configuration/continuity mismatch, a raw PID, an unbound
result file, or a stop acknowledgement proves nothing.

Restart reconciliation is causal:

- `NOT_ACCEPTED` permits submission of the same recorded launch operation, not a
  new start fence or operation. This covers a crash after journal intent but
  before the supervisor call.
- `STARTING` or `RUNNING` resumes observation/control without launch.
- `EXITED` retains the result but continues to withhold the claim while any
  descendant can execute. `CONTAINED` plus a matching result digest imports the
  result into the ordinary journal/outbox path. Positive containment without a
  valid result becomes the existing bounded executor-infrastructure failure; it
  is not a recovery close.
- `UNKNOWN` or any mismatch keeps the exact claims/capacity unavailable and the
  assignment unknown. The agent does not allocate around it or invoke launch.

If the supervisor process itself loses its continuity epoch, it must mark every
previously nonterminal record unknown and must not adopt or kill by PID. This
phase guarantees agent restart under a continuous configured supervisor, not
supervisor HA, reboot fencing, or recovery after supervisor-state loss. A
managed positive-containment proof used by privileged recovery is the
supervisor's persisted `CONTAINED` receipt for the complete launch identity;
status or an agent assertion cannot synthesize it.

### Recovery request and evidence

Conceptually:

```python
@dataclass(frozen=True)
class ManagedRecoveryTarget:
    agent_id: str
    session_id: str

@dataclass(frozen=True)
class SlurmRecoveryTarget:
    profile_id: str
    submission_operation_id: str
    cluster_id: str
    job_id: str
    bootstrap_incarnation_id: str | None

@dataclass(frozen=True)
class RecoverUnknownAssignment:
    recovery_id: str
    run_uri: str
    stage_name: str
    attempt: int
    stage_work_id: str
    assignment_id: str
    target: ManagedRecoveryTarget | SlurmRecoveryTarget
    process_execution_id: str
    execution_fence: str
    expected_state_version: int
    requested_outcome: Literal["failed", "cancelled"]
    consider_retry: bool
    reason: str
```

Exact private type names may differ, but the target is a closed tagged value.
Principal and evidence authority are derived separately. The payload may name
the expected execution identity but cannot assert “contained=true.” A trusted
target-specific evidence resolver returns a bounded typed proof tied to the
full durable boundary, or the operation fails without mutation.

For SLURM, the only additional evidence owner is one optional protected
site-owned containment helper configured on, fingerprinted into, and retained
with `SlurmReadyStageProfile`. It is a fixed helper adapter, not a generic
external-scheduler/evidence plugin and not selectable by an authored config or
recovery request. Its adapter/descriptor lives beside the ready-stage profile in
`loom.pipeline.executors.slurm`; coordinator recovery in `loom.queue` invokes
the retained profile binding and persists the validated receipt. It does not
enter `loom.scheduling`, a generic executor protocol, or public root imports.
The coordinator sends bounded canonical data naming
`assignment_id`, profile ID/configuration fingerprint/helper descriptor,
submission operation, cluster/job, bootstrap incarnation,
`process_execution_id`, and execution fence. The helper returns either
`CONTAINED` with an evidence ID/revision and an exact echo of every field, or
`UNKNOWN`; malformed output, mismatch, conflict, timeout, or unavailability is
`UNKNOWN`. The coordinator validates and persists the complete receipt before
recovery intent can close the fence. Profiles without a configured helper
remain fully usable for ordinary submission, observation, result, and
cancellation, but their unknown work has no SLURM recovery-close path. Neither
scheduler/accounting disappearance, terminal-looking state, `scancel`, nor
job-private capability revocation can be promoted into this receipt.

### Cross-store recovery saga

```text
coordinator RECOVERY_INTENT + ORDINARY_MUTATION_FROZEN
  -> retain/recheck exact-current-fence terminal facts
  -> authority ordinary TERMINAL_COMMITTED
       -> coordinator RECOVERY_SUPERSEDED_BY_TERMINAL (stop)
  or authority exact execution fence CLOSED
       -> coordinator OLD_ASSIGNMENT_FENCED + RECOVERY_CLOSED
       -> reliability owner considers one next attempt
       -> old provider claims or SLURM profile slot remain retained
          until exact target-specific release/containment is recorded
       -> orchestrator materializes fresh ready work if allowed
```

Crashes repeat the same `recovery_id`. Authority expected-state CAS is the
arbitration boundary: any complete verified terminal fact discovered before
close follows normal commit and supersedes the operator outcome; success also
prevents a replacement retry, while failure/cancellation follows existing
reliability/cancellation policy. Close winning makes later execution facts
stale. An unobservable result on an unavailable machine remains part of the
operator's explicit residual risk.

### Session replacement

Replacement operates on the old session's complete unresolved set, not one
convenient assignment:

```python
unresolved = coordinator.list_complete_session_references(old_session)
if not all(item.terminal_or_released or evidence.proves_contained(item) for item in unresolved):
    return REJECTED_INCOMPLETE_CONTAINMENT
```

The complete set includes assignments, provider preparations/claims, delivery
requests, controls, transfers, results/outputs, sequenced events, and outbox
facts. The new session is a new identity. It cannot inherit live claims, work
requests, availability revisions, transfer identities/authorizations, or
provider tokens, and it
publishes no capacity before a fresh full provider observation.

### Private discretion

Supervisor IPC/process-group internals, evidence storage layout, retry of
reconciliation, service-manager syntax, and status presentation remain private.
The owner/import boundary, complete launch identity, bounded supervisor states,
hard-cut old-state failure, and SLURM helper trust binding above are fixed. The
executor may not add another process owner, broaden qualifying evidence, merge
recovery with ordinary cancellation, or make recovery automatically periodic.

## Proportionality

- Reuses exact facts already required for safe launch, output, cancellation, and
  provider release. Recovery adds no speculative cluster manager.
- Separates routine operations (Phase 8) from the only irreversible manual fence/
  retry path so authorization and evidence receive focused implementation and
  review.
- Defers high availability, power fencing, checkpointing, and automatic failover
  because Stage 29 has no external authority capable of proving them safely.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Restart never repeats start fence | Agent journal/supervisor reconciler | Crash after journal/spawn | Duplicate process | Crash at every start edge with launcher sentinel |
| Coordinator restart never repeats `sbatch` or a SLURM authored root | Submission/start stores plus SLURM/bootstrap reconcilers | Crash at intent/call/handle/bootstrap/grant/start/result | Duplicate external job or authored effects | Every durable edge with one-call and one-root sentinels |
| Restart begins at zero availability | Agent startup owner | Stale offer/config | Resource collision | Startup/reconnect tests |
| DB loss is not empty state | Composition/store owner | Missing/corrupt/copied DB | Duplicate ownership | Failure/identity/schema tests |
| Coordinator or reconciled authority generation does not revoke execution fence | Authority + generation reconciler | Coordinator/authority restart | Lost valid result or stale service adoption | Restart/result replay and authority-continuity tests |
| Every verified current-fence terminal fact follows its normal path before close | Coordinator result quarantine/transfer reconciler + authority CAS | Success/failure/cancellation retained before/during recovery intent | Terminal truth overwritten or wrong retry/cancel outcome | Each terminal kind before/during intent and terminal-versus-close barriers |
| Only positive exact target containment permits manual close | Evidence resolver + authorizer | Timeout/PID/scheduler absence/`scancel`/body assertion | Duplicate effects | Managed and SLURM weak-evidence negative matrix |
| Recovery is idempotent across stores | Coordinator/authority recovery saga | Crash/replay | Two closures/retries | Crash-after-each-step tests |
| Authority CAS gives one terminal-or-close outcome | Authority terminal owner | Concurrent terminal commit and recovery close | Duplicate/wrong attempt or ambiguous recovery | Every terminal kind in both CAS orderings, crash/replay, and post-close stale-result tests |
| Fresh attempt has fresh placement/dispatch identity | Reliability/orchestrator | Recovery code | Stale resource/session/submission reuse | Claim/offer/device/submission/job/bootstrap non-copy assertions |
| Execution close does not imply physical/profile-slot release | Agent provider/replacement inventory or coordinator SLURM owner | Authority close or stale release | Capacity/slot reused beside old process/job | Close-before-release, exact old cleanup/containment, and fresh-observation tests |
| Session replacement covers complete unresolved references | Session recovery owner | Omitted claim/control/transfer/event/outbox evidence | Orphan live work or replay | Multi-assignment/provider/outbox complete-set tests |
| Late old execution facts cannot mutate new work | Assignment/fence validation | Reconnected old agent/upload | Corrupt new attempt/output | Stale event/output tests; exact cleanup can close only old claim |

## Implementation Slices

1. Add the one protected agent process-supervisor owner/client, stable identity/
   continuity and launch/query/containment records, and fixed resident-worker
   launch/result path. Route both embedded/local and remote HTTP-agent managed
   execution through it; remove `_ManagedWorkerHandle`, `_process_handles`, and
   remote `_processes` as owners rather than adapting them. Remove the obsolete
   embedded execution-service/launcher injection arguments; provider-derived
   environment is the only bounded launch variation. Derive the supervisor root
   from `agent_root`, initialize it only with a fresh agent root, and require the
   separately locked/open supervisor before the agent opens. Bump agent journal/
   workspace/root schemas as a hard cut, make old roots fail before resume/
   offer, and add no migration or PID-adoption branch.
   Generalize the existing private queue assignment workspace for both paths and
   move/split `run_managed_local_assignment` into the queue application
   composition; pipeline execution supplies only the import-light request,
   result, and resident-worker behavior and never imports queue.
2. Complete same-session agent restart at zero availability by joining exact
   journal/workspace and supervisor receipts, replaying result/output/outbox
   facts, reconciling or retaining claims, and publishing fresh availability
   only after the complete live set is known. Add user-service guidance for the
   supervisor-before-agent ordering and regression coverage for the Phase 5
   coordinator/authority-restart contract with the new records.
3. Complete coordinator restart of SLURM submission/bootstrap state with retained
   profiles, no-resubmit/no-second-start gates, exact handle discovery, result/
   output replay, and zero/one/multiple reconciliation regression.
4. Add privileged tagged-target recovery request/status/audit, managed
   supervisor `CONTAINED` receipt validation, and the one optional retained-
   profile SLURM site-helper adapter. Enforce exact full-identity echoes and
   comprehensive weak-evidence negatives; no helper means safe unknown.
5. Implement idempotent cross-store assignment fence/authority close/reliability
   retry saga. Generalize the existing retry evaluator to its authority-capable
   reliability-store contract, compose it through the least-privilege scoped
   authority view for ordinary managed/SLURM terminal failures and recovery
   closes, and let existing orchestrator readiness consume only its decision.
   Include ordinary reconciliation of success/failure/cancellation facts, fresh
   placement/dispatch, execution-close/provider-or-profile-slot-release
   separation, stale-event/output rejection with exact old-target cleanup, crash
   recovery, and terminal/recovery races.
6. Add complete-reference-set different-session replacement, replacement zero-start,
   fresh full provider observation,
   authenticated CLI/Python/HTTP operations, operational docs, final E2E, and
   full Stage 29 validation/test-summary evidence.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Recovery interfaces remain scoped and optional | Import/public surface checks |
| Unit | Required | Supervisor and site-helper trust/identity classification, existing retry evaluator composition, SLURM reconciliation cardinality, expected states, complete-reference-set and release logic | Exact launch replay returns one receipt; any launch field/digest conflict rejects; bounded supervisor states; continuity loss is unknown; timeout/PID/reboot/credential/scheduler-absence/`scancel`/capability-revoke negatives; every SLURM helper identity field mismatch; one authority retry decision for ordinary managed/SLURM failure and recovery failure, disabled/no retry for `consider_retry=false` and cancellation, none while unknown/success; zero/one/multiple job matches; all terminal kinds; exact old-target cleanup and idempotency |
| Contract | Required | Direct/HTTP recovery authorization, tagged targets, retained supervisor/helper descriptors, and authority/store CAS | Embedded and remote agents expose the same supervisor-backed semantics; body actor/evidence cannot authorize; exact replay and target/supervisor/profile/helper/operation/job/bootstrap/process/fence mismatch conflict; no helper is unknown, not unsupported ordinary SLURM execution |
| Integration | Required | Real supervisor-owned process restart, simulated SLURM submit/bootstrap/result and helper evidence, authority-backed retry consumption, output replay, and cross-store recovery crashes | Crash after journal intent/before supervisor acceptance permits only the same operation; crash after acceptance/before agent receipt, while running, and after result-before-journal each produces one root and ordinary replay in both managed paths; supervisor loss/mismatch withholds capacity; crash before/after terminal transaction and retry decision replays one decision and one orchestrator-prepared fresh attempt only when existing policy allows; each terminal commit, fence, provider/profile-slot release, fresh observation, and complete-reference session replacement |
| E2E / opt-in | Required | Full Stage 29 lifecycle | Coordinator, authority, agent, and SLURM-operation restarts; authority continuity negatives; managed/SLURM unknown containment/requeue; known success/failure/cancellation precedence; capacity/slot withheld until target truth; stale old agent/bootstrap; multi-machine simulation; optional site receipts |

Use process barriers that count fixed resident-worker root creation, not mocked
launcher calls. Explicitly prove a live child continues across an agent restart
under the unchanged supervisor continuity and that a supervisor continuity
change never adopts it. Run these targeted commands before the final gates:

    pytest -q tests/unit/loom/queue/test_agent_process_supervisor.py tests/unit/loom/pipeline/execution/test_managed_local.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/executors/slurm/test_ready_stage.py tests/unit/loom/queue/test_slurm_ready_stage.py tests/unit/loom/pipeline/test_orchestration.py
    pytest -q tests/integration/pipeline/test_managed_local_execution.py tests/integration/queue/test_agent_session_transport.py tests/integration/queue/test_local_daemon_production.py tests/integration/queue/test_slurm_ready_stage.py
    pytest -q tests/contracts/test_local_daemon_authority_contract.py tests/contracts/test_reliability_contract.py

Then run:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: weak managed/SLURM evidence treated as containment; duplicate
  `sbatch` or authored launch after restart; a second managed process owner
  surviving in either production path; supervisor continuity loss treated as
  adoption/containment; old thread/PID state silently migrated; copied/lost DB
  treated as fresh; a scheduler/control fact promoted to a SLURM helper receipt;
  recovery or daemon code constructing retry decisions outside the existing
  evaluator; an ordinary definitive managed/SLURM failure never reaching that
  evaluator; known terminal facts overwritten; lifecycle close mistaken for
  physical/profile-slot release; stale submission/bootstrap identity copied into retry;
  two retries; incomplete session reference enumeration; or unsafe evidence/
  status leakage.
- Review focus: one authoritative supervisor used by embedded and remote agents;
  complete durable launch identity and exact replay; hard-cut schema/open
  behavior; continuous process-group ownership; exact managed/helper evidence
  authority; retained SLURM helper descriptor and full-field receipt validation;
  complete expected-state transaction; cross-store reconciliation; all-terminal
  precedence; least-privilege authority reliability adapter; one terminal
  transaction/evaluator decision and existing orchestrator consumption;
  provider/profile-slot release separation; no-resubmit/no-second-root
  validation; stale-fence validation; complete session reference set; owner-
  labelled status; process barriers; and full regression evidence.
- The earlier managed configured-supervisor stop is resolved by the mandatory
  supervisor architecture above; the earlier SLURM stop is resolved by making
  the exact site helper optional and leaving helper-less work unknown. Stop only
  if implementation cannot keep that supervisor continuously authoritative
  across an agent restart and emit the fixed full-identity receipt; authority
  cannot close one exact current fence idempotently; the existing retry evaluator
  cannot consume the scoped authority reliability facts without exposing broad
  authority access to the agent or adding a second policy; provider truth cannot
  keep closed-but-unreleased capacity unavailable; database identity cannot
  distinguish restart from loss/clone; session
  replacement cannot enumerate the complete reference set; a `SUBMITTING`
  record can invoke `sbatch` again; or code would need to accept something weaker
  than the fixed SLURM helper receipt. Absence of a helper on a profile is not a
  blocker.
- Accepted debt: manual recovery can repeat authored external effects. Automatic
  failover remains deliberately unsupported until stronger external fencing or
  checkpoint contracts exist.

## Executor Handoff

- Read this file, Phase 8 completion record, the complete manifest trace, Phase
  7 completion evidence, and planning FR-9, FR-10, FR-14–FR-17, FR-19–FR-21,
  FR-25–FR-30, DQ-14, DQ-20, DQ-22, DQ-23, and DQ-25–DQ-30.
- Use real process barriers and fault injection for every irreversible edge.
  Finish phase-specific gates before full Stage 29 validation.
- Implement the shared supervisor boundary first. Both embedded/local and remote
  HTTP agents must submit the fixed resident-worker launch spec through it; do
  not retain `_ManagedWorkerHandle`, `Popen` maps, or alternate callable launch
  paths as production fallbacks. Delete the optional managed-path executor,
  artifact-store, resource-validator, plugin-record, and process-launcher
  arguments; current production has no caller for them. Move fault injection to
  the supervisor boundary and keep custom execution-service coverage at the
  lower-level worker boundary. Exact replay of `NOT_ACCEPTED` uses the same
  operation; every other nonterminal state queries instead of launching.
- Keep workspace and supervisor ownership together under the private queue
  application. Generalize `_RemoteAssignmentWorkspace` for both agent
  compositions and move/split the current embedded managed-assignment runner
  above it. Do not put queue workspace/supervisor types under pipeline execution
  and do not make pipeline import queue.
- Compose `record_retry_decision_for_stage_result()` after the authoritative
  terminal transaction for ordinary managed/SLURM failures and recovery closes.
  Generalize its store dependency and scoped coordinator adapter only; do not
  duplicate its classifier/evaluator, let the agent call authority, construct a
  `RetryDecisionRecord` in coordinator/recovery code, or prepare an attempt
  without the existing `RunOrchestrator` readiness check.
- Decisions not to revisit: hard cut with no legacy managed-state migration;
  zero availability on restart; one supervisor process owner; no repeat launch
  operation/root; managed `CONTAINED` receipt or optional retained-profile SLURM
  helper receipt as the only positive evidence; no timeout/PID/scheduler-absence/
  `scancel`/capability-revoke takeover; no resubmit or second root; ordinary
  reconciliation of every verified terminal fact; lifecycle-close/provider-or-
  profile-slot-release separation; reliability-owned fresh retry; and complete-
  reference-set session replacement.
- Escalate any missing containment/authority identity or proposal for automatic
  failover, power fencing, checkpointing, HA, disaster-state reconstruction, or
  a new public/durable behavior choice beyond the accepted hard cut. Helper-less
  SLURM recovery and supervisor continuity loss stay unknown without escalation.

## Workflow State

- Manager preparation: complete on clean merged Phase 8A baseline `44d06f3`;
  worktree/base, supervisor, SLURM evidence, reliability, schema, and focused
  test seams recorded
- Expanded planning: required by privileged irreversible recovery; phase plan
  refined with one authoritative managed supervisor, optional exact SLURM site
  helper, hard-cut old-state semantics, and existing authority-backed retry
  evaluator composition; configured-supervisor and retry-owner stops resolved
- Implementation: blocked candidate `ef3be2f` changes only
  `src/loom/pipeline/execution/stage_worker.py` to remove injected executor,
  clock, and resource-validator services from resident execution. The shared
  profile/workspace/supervisor and every later Phase 9 slice remain unimplemented
- Refiner: one bounded pass used; it confirmed the callable/root ambiguity and
  made no source change
- Pre-submit gate: not run because the phase implementation is incomplete
- Independent review: expected because this phase can fence old execution and
  permit a fresh attempt; confirm during preparation
- Blocker corrections: 3/3; the first removes obsolete callable launch services
  and derives the mandatory supervisor root from `agent_root`; the second fixes
  the shared staged workspace and embedded composition under `loom.queue`;
  the approved third fixes an explicit `ResidentWorkerLaunchProfile` rather
  than an implicit current-process profile. No further correction is available;
  any repeated or new blocker stops the phase
- PR and merge: no PR opened; branch/worktree retained as read-only evidence

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Blocked candidate `ef3be2f`; only `src/loom/pipeline/execution/stage_worker.py` removes optional resident executor/clock/resource-validator injection. All substantive Phase 9 slices remain absent. |
| Tests added or updated | None. Existing SLURM ready-stage integration coverage remains applicable to the hard cut. |
| Validated revision/tree state and evidence | Clean `ef3be2f`; manager reran `uv run ruff check src/loom/pipeline/execution/stage_worker.py`, `uv run pyright src/loom/pipeline/execution/stage_worker.py`, and `PYTHONPATH=src pytest -q tests/integration/queue/test_slurm_ready_stage.py`: all passed, with 6 focused tests. |
| Validation-relevant changes after evidence | None. |
| PR, review, and merge | No PR opened; incomplete scope is not submit-eligible. |
| Residual risk and cleanup | The entire supervisor/restart/recovery outcome remains missing. Retain this branch/worktree and commit evidence read-only for a fresh Phase 9A selective closure. |
