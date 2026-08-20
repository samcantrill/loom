# Roadmap Stage 24 Implementation Plan: Operational Lifecycle And Recovery Validation

Status: ready
Roadmap stage: `v24`
Planning document: `docs/roadmap/stage-24/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 2 pending
Blockers: none

## Summary

- Goal: prove with real local processes that Loom's interruption, cancellation,
  timeout, shutdown, unclean-loss, recovery, authority, artifact, and resume
  behavior agrees across process liveness and durable state.
- Approved behavior and requirement IDs: planning `FR-1` through `FR-12`
  distinguish graceful cancellation, timeout/failure, and unclean recovery;
  require exit-before-terminal-release ordering and no false output commit; and
  keep default validation hermetic.
- Key design constraints and decision IDs: `FQ-1` through `FQ-7` and `DQ-1`
  through `DQ-7` retain existing lifecycle owners, propagate Ctrl-C after
  durable cancellation, use authority rather than PID guesses for recovery,
  and combine tests only where boundaries causally interact.
- Minimum useful change: align the runner's keyboard-interrupt behavior with the
  accepted cancellation contract, then add one real operational proof for each
  currently simulated boundary and the smallest production cleanup/recovery fix
  each proof demonstrates.
- Complexity deliberately excluded: new public records or commands, new schema,
  new dependency, process reattachment, a Loom daemon, silent repair, automatic
  retry changes, a full backend/failure matrix, platform-wide signal support,
  and external runtime requirements.
- Validation and phase-shaping source: planning `Examples And Validation` and
  `Phase Shaping`. Phase 1 owns graceful termination while Loom is alive; Phase
  2 owns authoritative recovery and artifact trust after Loom or authority was
  unavailable.
- Out of scope: real Docker, Apptainer, SLURM, GPU, scheduler-accounting,
  notification, and remote-service profiles; Stage 26 owns those environment
  gates and evidence contracts.

## Shared Constraints

- Architecture and dependency direction:
  - Runner/lifecycle decides run and stage status.
  - Executors and managed-local process handles terminate and observe children.
  - Authority owns active truth, attempts, leases, and recovery transitions.
  - Planner owns stale/reuse actions; artifact stores own payload/checksum facts.
  - CLI maps a propagated `KeyboardInterrupt` to exit 130 and does not own
    lifecycle mutation.
  - Test-support modules may consume public Loom surfaces; production modules
    must not import CLI or tests against existing source-direction rules.
- Shared public and durable contracts:
  - Authored early stop and explicit cancel produce `CANCELLED`.
  - A caught keyboard interrupt cancels the run and any identifiable,
    uncommitted triggering stage, records an existing typed reason, completes
    owned cleanup, and is re-raised. Parallel local execution stops new starts
    but settles already-running non-preemptible stages truthfully; committed
    success is never relabelled.
  - Ordinary exceptions and real enforced timeout remain `FAILED`; timeout uses
    existing reliability facts.
  - A live authority-backed runner privately renews its controller lease.
    Uncatchable death writes no fictional terminal state; later recovery first
    acquires exclusive authority and verifies old-controller/incomplete-attempt
    facts, then records existing interruption/stale transitions and events.
  - A process-backed item or stage cannot become terminal and release owned
    resources before the process exit used to justify cleanup is observed.
  - Stage success and artifact reuse require validated output commit and index
    consistency. Incomplete, timed-out, cancelled, stale, corrupt, or
    interrupted outputs are not reusable.
- Shared reproducibility, compatibility, and import constraints:
  - No status enum, public model, config shape, persisted schema, CLI command,
    plugin, marker, or runtime dependency is added by default.
  - Existing normal success/failure, `stop_early()`, fake-process, fake-
    authority, delegated execution, retry, and valid-resume behavior stays
    compatible.
  - Default tests remain domain-neutral, self-contained, external-network-free,
    and bounded. POSIX signal/process-group tests may run in the default Linux
    gate and skip with an explicit platform reason elsewhere.
- Shared invariant ownership:
  - Runner owns cancellation/recovery decisions and downstream stop.
  - Executor/runtime owns child termination and exit observation.
  - Authority owns conflict, renewal, expiry, transitions, attempts, and leases.
  - Output commit owns the success/index boundary.
  - Planner/artifact store owns checksum mismatch and branch invalidation.
  - Test fixtures own every PID/process group they signal and always clean up in
    `finally`.
- Decisions no phase may reopen: Ctrl-C cancels without pretending parallel
  threads were preempted; timeout is failure; hard loss is classified from
  exclusive authority and recovery facts, not a dead PID; no automatic
  reattachment/repair, fixed-sleep oracle, full matrix, or external Stage 24
  runtime gate.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `real-interruption-and-cancellation` | merged | `docs/roadmap/stage-24/phases/real-interruption-and-cancellation.md` | `agent/stage-24-p1-real-interruption-and-cancellation` | [#216](https://github.com/samcantrill/loom/pull/216) | Serial/prepared cancellation, parallel settlement, CLI propagation, subprocess cleanup/timeout, managed-local cancel, and process test support | Prove that graceful stops reach truthful durable state and owned children exit before release. |
| 2 | `crash-recovery-and-artifact-trust` | pending | `docs/roadmap/stage-24/phases/crash-recovery-and-artifact-trust.md` | `agent/stage-24-p2-crash-recovery-and-artifact-trust` | pending | Controller renewal/parity, authority recovery/events, old-active resume, authority loss, artifact invalidation, and docs | Prove that unclean loss or corrupt output cannot become reusable success and explicit recovery produces a safe new attempt. |

Phase 1 is independently useful: operators receive correct Ctrl-C/timeout/cancel
semantics and real worker cleanup. Phase 2 starts only after Phase 1 is remotely
merged so crash recovery inherits one settled graceful lifecycle contract.

## Quality Gate

- Planning gate: passed. The user accepted the recommendation and requested the
  new Stage 24 with the former Stages 24 and 25 pushed to 25 and 26.
- Manager review: passed. Requirements, decisions, invariant owners, phase
  boundaries, manifest, and linked phase plans are traceable and consistent.
- Optional independent review: not needed on the lean path. Existing public and
  durable vocabulary is reused; no novel abstraction, schema, dependency, or
  irreversible migration is planned.
- Manager-local refresh correction: applied. Parallel interruption now preserves
  truthful in-flight results, and Phase 2 adds controller renewal and closes
  local-service lease parity before using recovery.
- Ready for implementation: yes.
- Accepted risks: POSIX-specific process tests; parallel local work settles
  rather than being forcibly stopped; no reattachment/machine-loss cleanup;
  external-runtime evidence stays scheduled/manual until Stage 26.
- Revisit triggers: an existing process seam cannot safely terminate/observe its
  owned child; recovery cannot distinguish live from abandoned authority; a new
  durable field/schema becomes unavoidable; or Stage 26 makes a reliable
  external runtime part of CI.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | [#216](https://github.com/samcantrill/loom/pull/216) squash-merged to `develop` as `8cc9bfa` | 62 focused tests, `make validate-pr`, `make test-summary` (2,267 passed, 3 skipped), manager review, and CI passed | Linux/POSIX signal proof and settled rather than preempted parallel threads remain accepted limits | Phase branch/worktree removed after the merge record; local control-checkout fast-forward deferred to preserve unrelated committed and uncommitted user work |
| 2 | pending | pending | pending | pending |
