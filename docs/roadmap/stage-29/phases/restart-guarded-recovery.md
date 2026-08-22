# Phase 9 Execution Plan: Restart And Guarded Unknown-Work Recovery

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 9
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9-restart-guarded-recovery`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop` after Phase 8 remotely merges
- PR target: `develop`
- PR title: `feat(scheduling): add guarded restart and recovery`
- Dependencies: Phases 1–8 merged with durable identities/stores, execution
  fences, managed and SLURM process/output facts, authenticated operator
  controls, retained provider/profile identity, cancellation, and reliability
  retry ownership
- Workflow path: expanded because privileged irreversible fencing, process
  evidence, stale results, retry, and session replacement interact
- Blockers: Phase 8 remote merge

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
  retained profile descriptors, status/audit, and process containment from
  earlier phases.
- Rediscover current reliability retry rules, process-group/supervisor evidence,
  SQLite corruption/schema behavior, and user-service documentation conventions.
- Use real child-process barriers plus fake clocks/transports. Recovery tests must
  exercise process/output state, not only mock status flags.
- Full Stage 29 validation and test-summary evidence are required in this final
  phase after phase-specific tests pass.

## Scope

In scope:

- Complete same-session agent restart:
  - acquire the exact role lock before opening mutable state;
  - reconstruct selected component/config identities required by live claims;
  - open/migrate the intact agent journal or fail closed;
  - publish zero availability and no work request;
  - recover accepted/grant/start/process/control/transfer/result/output/outbox
    facts;
  - query the configured process supervisor/containment boundary where exact
    recovery is supported;
  - never repeat an existing start fence;
  - authenticate/reconcile with the stable coordinator ID/current process epoch,
    replay ordered old-issuer events from the first unacknowledged sequence,
    finish output publication/cleanup, then observe and publish a fresh offer. The coordinator
    alone invokes the authenticated authority view; the agent receives no
    authority credential or direct access.
- Distinguish process restart from database loss. Missing, corrupt, incompatible,
  or copied required state is not an empty restart and must not produce fresh
  capacity. Return a safe blocked diagnostic for operator action.
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
- Provide abstract user-level service auto-restart guidance for coordinator and
  agent roles, including protected configuration, dependency/start ordering,
  restart backoff, separate state roots/locks, and safe readiness checks. Do not
  claim process adoption that the configured supervisor cannot prove.
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
  For a managed target, a trusted live agent/supervisor acknowledgement tied to
  the durable process identity may qualify. For a SLURM target, a configured
  trusted evidence resolver must tie positive terminal containment to the exact
  profile, submission operation, scheduler cluster/job handle, bootstrap
  incarnation/start permit, and execution fence. Queue/accounting absence,
  `scancel` success, retention expiry, scheduler timeout, job-name/PID/hostname
  text, unauthenticated reboot text, credential revocation, coordinator process-
  epoch change, or plain “mark failed” never qualifies alone.
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
role lock acquired
  -> journal opened and identity verified
  -> availability forced to zero
  -> live assignment/process/output set reconstructed
  -> exact supervisor facts reconciled
  -> coordinator authenticated and session resumed
  -> ordered events/results/outputs replayed and durably acknowledged
  -> physical claims released/reconciled or retained unavailable
  -> resources/config observed
  -> fresh availability published
```

If any exact live fact remains uncertain, the agent stays at zero for affected
capacity and reports unknown. It does not allocate around a possibly live claim
or call the launcher again.

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

Supervisor adapter internals, evidence storage layout, retry of reconciliation,
service-manager syntax, and status presentation remain private. The executor may
not broaden qualifying evidence, merge recovery with ordinary cancellation, or
make recovery automatically periodic.

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

1. Complete same-session agent restart, zero-availability startup, supervisor/
   journal/outbox/output reconciliation, duplicate-start rejection,
   required-store fail-closed behavior, and user-service operation guidance;
   add regression coverage for the Phase 5 coordinator/authority-restart
   contract with the new recovery records.
2. Complete coordinator restart of SLURM submission/bootstrap state with retained
   profiles, no-resubmit/no-second-start gates, exact handle discovery, result/
   output replay, and zero/one/multiple reconciliation regression.
3. Add privileged tagged-target recovery request/status/audit and trusted
   managed/SLURM positive-containment evidence projection with exact scope/
   version checks and comprehensive weak-evidence negatives.
4. Implement idempotent cross-store assignment fence/authority close/reliability
   retry saga, ordinary reconciliation of success/failure/cancellation facts,
   fresh placement/dispatch, execution-close/provider-or-profile-slot-release
   separation, stale-event/output rejection with exact old-target cleanup, crash
   recovery, and terminal/recovery races.
5. Add complete-reference-set different-session replacement, replacement zero-start,
   fresh full provider observation,
   authenticated CLI/Python/HTTP operations, operational docs, final E2E, and
   full Stage 29 validation/test-summary evidence.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Recovery interfaces remain scoped and optional | Import/public surface checks |
| Unit | Required | Evidence classification, SLURM reconciliation cardinality, expected states, complete-reference-set and release logic | Timeout/PID/reboot/credential/scheduler-absence/`scancel` negatives; zero/one/multiple job matches; all terminal kinds; exact identity, old-target cleanup, and idempotency |
| Contract | Required | Direct/HTTP recovery authorization, tagged targets, retained profiles, and authority/store CAS | Same operation/error semantics; body actor/evidence cannot authorize; exact replay and target/profile/job/bootstrap mismatch conflict |
| Integration | Required | Real managed-process restart, simulated SLURM submit/bootstrap/result restart, output replay, and cross-store recovery crashes | One-call/one-root barriers at every durable edge; each terminal commit, fence, retry, provider/profile-slot release, fresh observation, and complete-reference session replacement |
| E2E / opt-in | Required | Full Stage 29 lifecycle | Coordinator, authority, agent, and SLURM-operation restarts; authority continuity negatives; managed/SLURM unknown containment/requeue; known success/failure/cancellation precedence; capacity/slot withheld until target truth; stale old agent/bootstrap; multi-machine simulation; optional site receipts |

Targeted commands are fixed during phase preparation. Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: weak managed/SLURM evidence treated as containment; duplicate
  `sbatch` or authored launch after restart; copied/lost DB treated as fresh;
  known terminal facts overwritten; lifecycle close mistaken for physical/
  profile-slot release; stale submission/bootstrap identity copied into retry;
  two retries; incomplete session reference enumeration; or unsafe evidence/
  status leakage.
- Review focus: exact evidence authority, complete expected-state transaction,
  cross-store reconciliation, all-terminal precedence, provider/profile-slot
  release separation, exact SLURM handle/bootstrap containment, no-resubmit/no-
  second-start validation, stale-fence validation, complete session reference
  set, owner-labelled status, process barriers, and full regression evidence.
- Stop if: the configured supervisor cannot tie containment to exact assignment/
  process identity; authority cannot close one exact current fence idempotently;
  retry owner cannot be reused; provider truth cannot keep closed-but-unreleased
  capacity unavailable; database identity cannot distinguish restart from loss/
  clone; session replacement cannot enumerate the complete reference set; a
  `SUBMITTING` record can invoke `sbatch` again; or SLURM containment cannot be
  tied positively to the full operation/job/bootstrap/fence identity.
- Accepted debt: manual recovery can repeat authored external effects. Automatic
  failover remains deliberately unsupported until stronger external fencing or
  checkpoint contracts exist.

## Executor Handoff

- Read this file, Phase 8 completion record, the complete manifest trace, Phase
  7 completion evidence, and planning FR-9, FR-10, FR-14–FR-17, FR-19–FR-21,
  FR-25–FR-30, DQ-14, DQ-20, DQ-22, DQ-23, and DQ-25–DQ-30.
- Use real process barriers and fault injection for every irreversible edge.
  Finish phase-specific gates before full Stage 29 validation.
- Decisions not to revisit: zero availability on restart, no repeat start,
  positive exact target containment, no timeout/PID/scheduler-absence takeover,
  no resubmit or second root, ordinary reconciliation of every verified terminal
  fact, lifecycle-close/provider-or-profile-slot-release separation,
  reliability-owned fresh retry, and complete-reference-set session replacement.
- Escalate any missing containment/authority identity or proposal for automatic
  failover, power fencing, checkpointing, HA, or disaster-state reconstruction.

## Workflow State

- Manager preparation: pending Phase 8 merge, worktree/base recording, and
  exact supervisor/reliability/test rediscovery
- Expanded planning: required by privileged irreversible recovery; phase plan
  finalized
- Implementation: pending
- Refiner: not used
- Pre-submit gate: pending
- Independent review: expected because this phase can fence old execution and
  permit a fresh attempt; confirm during preparation
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
