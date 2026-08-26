# Phase 9E Execution Plan: SLURM And Guarded Recovery Closure

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 9E
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9e-slurm-guarded-recovery-closure`
- Worktree root: `/home/can134/work/active/loom-worktrees`
- Worktree path: create after Phase 9D is remotely merged
- Base revision: current `origin/develop` after the Phase 9D merge
- PR target: `develop`
- PR title: `feat(scheduling): close SLURM guarded recovery`
- Dependency: Phases 9C2 and 9D remotely merged. Blocked Phases 9 through 9C
  remain read-only evidence; the blocked Phase 9 plan's `Recovery request and
  evidence` and `Cross-store recovery saga` headings retain the approved
  behavior contract.
- Workflow path: expanded. Irreversible fence closure, external containment,
  and retry causally interact, so implementation requires one executor and one
  independent review unless manager evidence removes the residual risk.
- Blocker corrections: 0/3

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

- Start only after Phase 9D is remotely merged and this branch is based on
  current `origin/develop`.
- Read this plan, Phase 9C2/9D completion records, and the blocked Phase 9 plan's
  `Recovery request and evidence` and `Cross-store recovery saga` sections.
- Implement the three slices, tests, and phase-specific operational guidance.
- Do not edit roadmap metadata, perform GitHub operations, add compatibility,
  or delegate.

## Workflow State

- Manager preparation: pending Phase 9D merge
- Implementation: pending
- Validation and review: pending
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and tests | pending |
| Validated revision and evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
