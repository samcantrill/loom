# Phase 8 Execution Plan: Restart And Guarded Unknown-Work Recovery

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 8
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p8-restart-guarded-recovery`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop` after Phase 7 remotely merges
- PR target: `develop`
- PR title: `feat(scheduling): add guarded restart and recovery`
- Dependencies: Phases 1–7 merged with durable identities/stores, execution
  fences, process/output facts, authenticated operator controls, configuration
  identity, cancellation, and reliability retry ownership
- Workflow path: expanded because privileged irreversible fencing, process
  evidence, stale results, retry, and session replacement interact
- Blockers: Phase 7 remote merge

## Objective And Context

- Vertical outcome: a coordinator or agent can restart from its own intact
  durable state without duplicating a managed launch. Granted work continues or
  remains explicitly unknown until reconciled. When ordinary reconciliation
  cannot establish terminal truth, a separately authorized operator can close
  one exact positively contained assignment and allow existing reliability
  policy to consider a fresh attempt. A replacement agent session is admitted
  only after the complete unresolved old-session set is safe.
- Earlier dependency: Phase 7 deliberately leaves disconnected/ambiguous work
  bound. This phase supplies the only path that may fence such work without an
  authoritative terminal event.
- Later work explicitly out of scope: no later Stage 29 phase adds stronger
  failover. Coordinator HA, machine power fencing, checkpoint migration, and
  automatic takeover require separate future designs.

## Current Source And Harness

- Reuse all durable coordinator/authority/agent/transfer/control facts, expected-
  state operations, execution fences, role locks, component/config identities,
  outbox acknowledgements, status/audit, and process containment from earlier
  phases.
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
  - authenticate/reconcile with coordinator and authority, replay events, finish
    output publication/cleanup, then observe and publish a fresh offer.
- Distinguish process restart from database loss. Missing, corrupt, incompatible,
  or copied required state is not an empty restart and must not produce fresh
  capacity. Return a safe blocked diagnostic for operator action.
- Complete coordinator restart from its intact SQLite state with a new
  coordinator generation but the same durable coordinator identity. Rebuild
  scheduling projections, retain assignments/reservations/receipts/controls,
  accept reconnecting agent reconciliation, and never invalidate a current
  authority execution fence merely because generation changed.
- Provide abstract user-level service auto-restart guidance for coordinator and
  agent roles, including protected configuration, dependency/start ordering,
  restart backoff, separate state roots/locks, and safe readiness checks. Do not
  claim process adoption that the configured supervisor cannot prove.
- Add an exact assignment-level manual recovery operation for accepted unknown
  work. Require:
  - privileged recovery action plus exact run/object/pool/agent scope;
  - stable recovery operation ID and canonical request digest;
  - exact run, stage, attempt, stage-work, assignment, agent/session,
    `process_execution_id`, execution fence, and expected current state;
  - safe positive-containment evidence resolved by a configured trusted evidence
    owner, not a body assertion;
  - explicit terminal outcome, bounded reason, and optional request for existing
    reliability policy to consider a next attempt.
- Define positive containment narrowly: evidence must establish that the exact
  managed process/supervisor boundary for the assignment cannot still execute or
  later resume. A trusted live agent/supervisor acknowledgement tied to the
  durable process identity may qualify. Timeout, offer/lease expiry, connection
  loss, PID absence, unauthenticated reboot text, credential revocation,
  coordinator generation, or plain “mark failed” never qualifies alone.
- Persist a recovery decision in one coordinator transaction after revalidating
  the complete expected assignment/session/control/transfer state and confirming
  no authoritative success/output commit. Fence the old coordinator assignment
  so late events cannot mutate it.
- Close the exact authority execution fence/attempt through a separate
  idempotent expected-state operation. Because coordinator and authority stores
  are independent, model this as a reconciliable recovery saga keyed by the same
  recovery ID; never claim a distributed transaction.
- Only after the old attempt is definitively closed may the existing reliability
  policy decide whether one fresh attempt is permitted. The fresh attempt keeps
  authored run/stage requirements and hard target, but freshly resolves current
  pool/site policy. It copies no offer, candidate score, device ID, resource
  claim, availability revision, transfer grant, session, or provider token.
- Do not consume automatic retry budget while work is unknown. Record the
  operator-requested outcome and let the reliability owner apply normal policy
  after closure.
- Reject late old-agent events, start facts, results, uploads, or release messages
  from mutating the fenced assignment/new attempt. Retain them as bounded stale
  audit evidence where useful. Known authoritative success always prevents a
  recovery requeue.
- Add different-session replacement as a distinct privileged operation. Read the
  complete unresolved assignment/control/transfer/output set for the old
  session. Retire/fence it only when every member is terminal or has exact
  positive containment. Proof for one assignment cannot replace a session that
  owns another unknown assignment.
- Start a replacement session at zero availability and require ordinary
  registration, configuration/contract reconstruction, reconciliation, and
  fresh offer publication. A copied session ID or credential change is not
  replacement authority.
- Add joined recovery/restart/session status and authenticated Python/CLI/
  direct/HTTP operations showing expected/current identities, evidence kind,
  actor/principal reference, decision/result, retry disposition, and residual
  unknown set through bounded safe fields only.
- Add operational examples for coordinator restart, agent restart, unknown-work
  inspection, rejected weak recovery, positively contained recovery, and session
  replacement using only `machine-A` and `machine-B`.
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
  as containment, hidden force, or recovery that overwrites known success.

Assumptions:

- Positive-containment strength is limited to the configured supervisor/process-
  group boundary. Loom manages cooperative user processes and does not claim a
  hostile-code sandbox.
- Even after Loom proves its managed process is contained, authored external
  effects may have occurred before loss. Explicit requeue can repeat them and
  must remain visible in status/audit.
- Required databases and protected identity/config material are backed up and
  operated externally; Stage 29 implements restart, not disaster recovery.

## Fixed Contracts And Private Discretion

### Same-session restart state machine

```text
role lock acquired
  -> journal opened and identity verified
  -> availability forced to zero
  -> live assignment/process/output set reconstructed
  -> exact supervisor facts reconciled
  -> coordinator authenticated and session resumed
  -> events/results/outputs replayed and acknowledged
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
class RecoverUnknownAssignment:
    recovery_id: str
    run_uri: str
    stage_name: str
    attempt: int
    stage_work_id: str
    assignment_id: str
    agent_id: str
    session_id: str
    process_execution_id: str
    execution_fence: str
    expected_state_version: int
    requested_outcome: Literal["failed", "cancelled"]
    consider_retry: bool
    reason: str
```

Principal and evidence authority are derived separately. The payload may name
the expected process identity but cannot assert “contained=true.” A trusted
evidence resolver returns a bounded typed proof tied to the exact durable
boundary, or the operation fails without mutation.

### Cross-store recovery saga

```text
coordinator RECOVERY_INTENT + OLD_ASSIGNMENT_FENCED
  -> authority exact execution fence CLOSED with outcome
  -> coordinator RECOVERY_CLOSED
  -> reliability owner considers one next attempt
  -> orchestrator materializes fresh ready work if allowed
```

Crashes repeat the same `recovery_id`. Authority success discovered at any point
wins and prevents failed/cancelled replacement. A later old event is stale
because its assignment/fence is no longer current.

### Session replacement

Replacement operates on the old session's complete unresolved set, not one
convenient assignment:

```python
unresolved = coordinator.list_unresolved(old_session)
if not all(item.terminal or evidence.proves_contained(item) for item in unresolved):
    return REJECTED_INCOMPLETE_CONTAINMENT
```

The new session is a new identity. It cannot inherit live claims, work requests,
availability revisions, transfer grants, or provider tokens.

### Private discretion

Supervisor adapter internals, evidence storage layout, retry of reconciliation,
service-manager syntax, and status presentation remain private. The executor may
not broaden qualifying evidence, merge recovery with ordinary cancellation, or
make recovery automatically periodic.

## Proportionality

- Reuses exact facts already required for safe launch, output, cancellation, and
  provider release. Recovery adds no speculative cluster manager.
- Separates routine operations (Phase 7) from the only irreversible manual fence/
  retry path so authorization and evidence receive focused implementation and
  review.
- Defers high availability, power fencing, checkpointing, and automatic failover
  because Stage 29 has no external authority capable of proving them safely.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Restart never repeats start fence | Agent journal/supervisor reconciler | Crash after journal/spawn | Duplicate process | Crash at every start edge with launcher sentinel |
| Restart begins at zero availability | Agent startup owner | Stale offer/config | Resource collision | Startup/reconnect tests |
| DB loss is not empty state | Composition/store owner | Missing/corrupt/copied DB | Duplicate ownership | Failure/identity/schema tests |
| Coordinator generation does not revoke execution fence | Authority | Coordinator restart | Lost valid result | Restart/result replay test |
| Only positive exact containment permits manual close | Evidence resolver + authorizer | Timeout/PID/body assertion | Duplicate effects | Weak-evidence negative matrix |
| Recovery is idempotent across stores | Coordinator/authority recovery saga | Crash/replay | Two closures/retries | Crash-after-each-step tests |
| Known success prevents requeue | Authority terminal owner | Stale recovery snapshot | Duplicate attempt after success | Success/recovery race tests |
| Fresh attempt has fresh placement | Reliability/orchestrator | Recovery code | Stale resource/session reuse | Claim/offer/device non-copy assertions |
| Session replacement covers complete unresolved set | Session recovery owner | Partial evidence | Orphan live work | Multi-assignment complete-set tests |
| Late old facts cannot mutate new work | Assignment/fence validation | Reconnected old agent/upload | Corrupt new attempt/output | Stale event/output/release tests |

## Implementation Slices

1. Complete same-session agent/coordinator restart, zero-availability startup,
   supervisor/journal/outbox/output reconciliation, duplicate-start rejection,
   required-store fail-closed behavior, and user-service operation guidance.
2. Add privileged recovery request/status/audit and trusted positive-containment
   evidence projection with exact scope/version checks and comprehensive weak-
   evidence negatives.
3. Implement idempotent cross-store assignment fence/authority close/reliability
   retry saga, fresh placement, stale-event/output rejection, crash recovery,
   and success/recovery races.
4. Add complete-set different-session replacement, replacement zero-start,
   authenticated CLI/Python/HTTP operations, operational docs, final E2E, and
   full Stage 29 validation/test-summary evidence.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Recovery interfaces remain scoped and optional | Import/public surface checks |
| Unit | Required | Evidence classification, expected states, complete-set logic | Timeout/PID/reboot/credential negatives; exact identity and idempotency |
| Contract | Required | Direct/HTTP recovery authorization and authority/store CAS | Same operation/error semantics; body actor/evidence cannot authorize |
| Integration | Required | Real process restart, output replay, cross-store recovery crashes | Barrier at journal/start/exit/upload/commit/fence/retry/session replacement |
| E2E / opt-in | Required | Full Stage 29 lifecycle | Coordinator and agent restarts; unknown containment/requeue; stale old agent; multi-machine simulation; optional site receipts |

Targeted commands are fixed during phase preparation. Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: weak evidence treated as containment; duplicate launch after
  restart; copied/lost DB treated as fresh; old success overwritten; two retries;
  partial session replacement; unsafe evidence/status leakage.
- Review focus: exact evidence authority, complete expected-state transaction,
  cross-store reconciliation, success precedence, stale-fence validation,
  process barriers, and full regression evidence.
- Stop if: the configured supervisor cannot tie containment to exact assignment/
  process identity; authority cannot close one exact current fence idempotently;
  retry owner cannot be reused; database identity cannot distinguish restart
  from loss/clone; or session replacement cannot enumerate the complete set.
- Accepted debt: manual recovery can repeat authored external effects. Automatic
  failover remains deliberately unsupported until stronger external fencing or
  checkpoint contracts exist.

## Executor Handoff

- Read this file, Phase 7 completion record, the complete manifest trace, and
  planning FR-9, FR-10, FR-14–FR-16, FR-19–FR-21, FR-25, and FR-26.
- Use real process barriers and fault injection for every irreversible edge.
  Finish phase-specific gates before full Stage 29 validation.
- Decisions not to revisit: zero availability on restart, no repeat start,
  positive exact containment, no timeout/PID takeover, success precedence,
  reliability-owned fresh retry, and complete-set session replacement.
- Escalate any missing containment/authority identity or proposal for automatic
  failover, power fencing, checkpointing, HA, or disaster-state reconstruction.

## Workflow State

- Manager preparation: pending Phase 7 merge, worktree/base recording, and
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
