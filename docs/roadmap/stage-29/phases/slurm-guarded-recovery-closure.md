# Phase 9E Execution Plan: SLURM And Guarded Recovery Closure

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 29, Phase 9E
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9e-slurm-guarded-recovery-closure`
- Worktree root: `/home/can134/work/active/loom-worktrees`
- Worktree path: `/home/can134/work/active/loom-worktrees/stage-29-p9e-slurm-guarded-recovery-closure`
- Base revision: `eadeead37099fac834d0c40f32910f4ee9d39bb8`
- PR target: `develop`
- PR title: `feat(scheduling): close SLURM guarded recovery`
- Dependency: Phases 9C2 and 9D2 remotely merged as `b0ed116` and `82b311f`.
  Blocked Phases 9 through 9D
  remain read-only evidence; the blocked Phase 9 plan's `Recovery request and
  evidence` and `Cross-store recovery saga` headings retain the approved
  behavior contract.
- Workflow path: expanded. Irreversible fence closure, external containment,
  and retry causally interact, so implementation requires one executor and one
  independent review unless manager evidence removes the residual risk.
- Blocker corrections: 1/3 in progress

## Objective And Context

Close the exceptional recovery vertical after Phases 9C2/9D supply trustworthy
managed-supervisor receipts. A coordinator restart must not repeat a ready-stage
SLURM submission. An operator may close genuinely unknown managed or SLURM work
only when a trusted target-specific owner proves positive containment. The
authority arbitrates an ordinary terminal fact against recovery close, and the
existing reliability owner alone decides whether a fresh attempt is permitted.

This phase does not reopen the hard-cut decision. Old Phase 9, supervisor,
coordinator, authority, agent, or SLURM candidate schemas are rejected rather
than migrated, adopted, or inferred.

## Current Source And Harness

- `src/loom/queue/local_daemon_execution.py` is the production coordinator and
  already reconstructs retained managed and SLURM assignments. Its
  `_reconcile_slurm_run()` path mirrors durable submission state and observes an
  accepted operation without resubmitting it; extend this owner rather than
  creating another restart loop.
- `src/loom/queue/slurm_ready_stage.py` owns atomic SLURM assignment reservation,
  submission/bootstrap facts, result evidence, and physical release state.
  `src/loom/pipeline/executors/slurm/ready_stage.py` owns the retained profile,
  durable submission operation, and site helper boundary.
- `src/loom/queue/_managed_local.py` and the merged supervisor journal own exact
  managed launch containment. `src/loom/queue/agent_sessions.py` and
  `src/loom/queue/local_daemon.py` own authenticated operator scopes and the
  daemon-facing operation surface.
- `src/loom/pipeline/stores/sqlite_authority.py` owns fenced attempt truth and is
  the only acceptable terminal-or-close arbitration point.
  `src/loom/pipeline/execution/reliability.py` already owns
  `record_retry_decision_for_stage_result()`; the current orchestrator remains
  the only owner that materializes another attempt.
- Primary harnesses are
  `tests/integration/queue/test_local_daemon_production.py`,
  `tests/integration/queue/test_slurm_ready_stage.py`,
  `tests/integration/queue/test_agent_session_transport.py`,
  `tests/unit/loom/queue/test_local_daemon.py`,
  `tests/unit/loom/queue/test_agent_sessions.py`,
  `tests/unit/loom/pipeline/stores/test_sqlite_authority.py`, and
  `tests/contracts/test_managed_authority_contract.py`. Reuse their production
  composition helpers; do not prove the phase with an isolated replacement
  state machine.

## Scope

In scope:

- Reconstruct coordinator restart state for every managed and ready-stage SLURM
  assignment while withholding scheduling until current state is reconciled.
- Reconcile zero, one, or conflicting SLURM submission handles from durable
  operation identity, scheduler observation, bootstrap, relay, result, output,
  provider-revoke, and profile-slot facts. Never issue a second `sbatch` for an
  accepted submission operation.
- Add the approved privileged `RecoverUnknownAssignment` operation as a closed
  managed/SLURM tagged target with exact operator scope, immutable request
  digest, idempotent `recovery_id`, expected state version, and audit/status.
- Resolve managed evidence only from the Phase 9C2/9D supervisor's persisted exact
  `CONTAINED` receipt for the complete launch identity.
- Resolve SLURM evidence only from the retained profile's optional protected,
  fingerprinted containment helper. Exact echoed identity plus a typed
  `CONTAINED` receipt qualifies; timeout, mismatch, malformed output, accounting
  disappearance, `scancel`, capability revocation, or helper absence is
  `UNKNOWN` and causes no close.
- Freeze ordinary mutation for the exact assignment while recovery is pending,
  recheck complete ordinary terminal facts, and use one authority
  terminal-or-close expected-state CAS as the arbitration point.
- If an ordinary terminal fact wins, commit it normally and mark recovery
  superseded. If close wins, reject every later old-fence fact as stale.
- Feed a closed failure/cancellation only through the existing
  `record_retry_decision_for_stage_result()` reliability evaluation and current
  `RunOrchestrator` attempt materialization. Do not create recovery-local retry
  facts, counters, or policy.
- Keep lifecycle close separate from physical managed provider release or SLURM
  profile-slot release. Unknown or incompletely released capacity stays held.
- Add focused operator guidance and joined diagnostics for restart, evidence,
  arbitration, close, retry decision, and retained physical ownership.

Out of scope:

- Different-session agent replacement, final public operation consolidation,
  final Stage 29 E2E, and `make test-summary`; Phase 9F owns them.
- Automatic takeover, scheduler-disappearance inference, PID adoption, power
  fencing, checkpoint migration, supervisor HA, or a second retry policy.

## Fixed Contracts

The recovery request names identity and requested outcome; it never supplies or
asserts containment evidence:

```python
RecoverUnknownAssignment(
    recovery_id="recovery-7",
    assignment_id="assignment-3",
    process_execution_id="process-5",
    execution_fence="fence-11",
    target=ManagedRecoveryTarget(agent_id="agent-a", session_id="session-4"),
    expected_state_version=19,
    requested_outcome="failed",
    consider_retry=True,
    reason="operator-confirmed host isolation",
)
```

The trusted resolver independently returns one bounded result:

```text
exact managed supervisor CONTAINED receipt -> qualifying evidence
exact retained SLURM helper CONTAINED receipt -> qualifying evidence
anything else                              -> UNKNOWN, no mutation
```

The cross-store order is fixed:

```text
durable recovery intent + ordinary mutation frozen
  -> exact terminal facts rechecked
  -> authority ordinary terminal commit wins and supersedes recovery
     OR authority exact fence close wins and makes later old facts stale
  -> coordinator records the matching outcome
  -> existing reliability owner considers retry once
  -> physical ownership remains held until its own exact release proof
```

Crashes replay the same operation IDs. A transport timeout never authorizes a
new intent, submission, close, retry decision, or physical release.

## Invariant Ownership

| Invariant | Owner | Material consequence | Required evidence |
| --- | --- | --- | --- |
| An accepted SLURM operation is submitted at most once | Ready-stage dispatcher | Duplicate external effects | Fresh-coordinator crash barriers around durable prepare/submit/handle commit |
| Only the target owner proves containment | Supervisor or retained SLURM helper | Concurrent old and replacement execution | Exact positive and weak-evidence negative tests |
| Terminal fact and close cannot both win | Per-run authority CAS | Contradictory run truth | Reordered terminal/recovery race matrix |
| Retry policy has one owner | Existing reliability evaluator | Duplicate or policy-divergent attempts | Replay and success/failure/cancellation policy tests |
| Lifecycle close does not imply capacity release | Provider/profile owner | Unsafe capacity reuse | Status and scheduling barriers until exact release |

## Proportionality And Implementer Discretion

The phase may add only the private durable request/status state, exact authority
transition, scoped daemon operation, and optional retained-profile containment
helper needed by the accepted end-to-end consumers. It must not add a generic
recovery framework, a second retry abstraction, a public plugin surface, or a
compatibility reader. Any changed durable identity is a hard cut: fresh roots
use the new shape and older/candidate shapes fail closed.

Private type, table, helper, and method names are implementer discretion. So are
transaction-local representations and how the existing coordinator resumes the
saga, provided the fixed cross-store order, trust boundaries, externally
observable status, and causal crash behavior above remain exact.

## Implementation Slices

1. Complete fresh coordinator restart and exact ready-stage SLURM submission/
   bootstrap/result reconciliation with no-resubmit causal tests.
2. Add the scoped recovery request, retained managed/SLURM evidence resolvers,
   durable status/audit, and strict weak-evidence rejection.
3. Compose the authority terminal-or-close saga, existing-policy retry, stale
   fact rejection, and independent physical-release reconciliation.

## Test And Validation Plan

- Unit: tagged target/request codecs, scope/auth, request digest replay/conflict,
  helper echo validation, bounded evidence states, stale-fence decisions.
- Contract: direct and HTTP operations call the same authorizer/state machine;
  managed and SLURM evidence remain target-specific and non-forgeable.
- Integration: fresh coordinator processes at every submission boundary; real
  Phase 9C2/9D supervisor receipts; fake protected SLURM helper; reordered terminal
  fact versus close; crash/replay at every saga commit; retry exactly once.
- Regression: Phase 7B verifier/bootstrap/provider-revoke lifecycle and Phase 8A
  cancellation settlement remain unchanged.
- Gate: focused suites, changed-path Ruff/Pyright, then `make validate-pr`.
  Phase 9F owns the fresh final summary.

## Risks, Review, And Stops

- Main risks are weak evidence promoted to containment, a second `sbatch`, close
  racing an ordinary success, retry performed outside reliability policy, or
  capacity released from lifecycle state alone.
- Stop if a supported SLURM path lacks a stable submission identity, the
  authority cannot atomically choose terminal-or-close, or a proposed evidence
  path is not owned by the continuously responsible target boundary.
- Do not implement Phase 9F replacement or final-surface work here.

## Executor Handoff

- Start from prepared revision recorded in metadata; the branch is based on the
  current post-9D2 `origin/develop`.
- Read this plan, Phase 9C2/9D2 completion records, and the blocked Phase 9 plan's
  `Recovery request and evidence` and `Cross-store recovery saga` sections.
- Implement the three slices, tests, and phase-specific operational guidance.
- Do not edit roadmap metadata, perform GitHub operations, add compatibility,
  or delegate.

## Workflow State

- Manager preparation: complete on the post-9D2 branch; maintainer approval
  recorded
- Implementation: candidate `024faaf` requires correction 1/3. Its durable
  operation stops at `pending` after a crash, authority close does not replay as
  the same recovery, and the SLURM evidence binding is an in-process callable
  rather than the approved protected helper. The candidate also lacks the
  causal end-to-end proof that rechecks ordinary terminal facts and feeds the
  existing retry/orchestrator owners.
- Validation and review: pending
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and tests | Candidate `024faaf` added the initial operation, authority transition, and evidence shapes. Manager verification found that the supported authenticated recovery path is not yet a replay-safe cross-store saga and its SLURM evidence boundary is not the accepted protected helper. Correction 1/3 is active. |
| Validated revision and evidence | Candidate focused authority/SLURM suites passed (41 tests), focused local-daemon tests passed (11 tests), and Ruff/Pyright passed. The full gate was intentionally stopped because the qualified blocker made its receipt stale. |
| PR, review, and merge | pending |
| Residual risk and cleanup | Qualified blocker: a crash can strand `pending`, a post-authority-close replay can be misclassified, uncommitted ordinary terminal evidence can lose, retry is written with no policy to the wrong consumer store, and an in-memory callback can stand in for protected SLURM evidence. Smallest fix: complete the one existing daemon/authority saga with replayable states, target-owned persisted evidence, the fixed retained helper adapter, current-policy retry consumed by `RunOrchestrator`, authenticated transport wiring, and causal tests; retain physical ownership. |
