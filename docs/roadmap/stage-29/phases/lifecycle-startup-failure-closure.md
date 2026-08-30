# Phase 13A Execution Plan: Lifecycle Startup-Failure Closure

## Metadata

- Status: pr_open
- Roadmap stage and phase: Stage 29, Phase 13A
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p13a-lifecycle-startup-failure-closure`
- Worktree root and path: `/home/can134/work/active/loom-worktrees/stage-29-p13a-lifecycle-startup-failure-closure`
- Base revision: `f9b18c1cc7dba59de90310ceac4fbae8f4e1b837`
- PR target: `develop`
- PR title: `Stage 29 phase 13A: close supervisor startup failure leaks`
- PR: [#262](https://github.com/samcantrill/loom/pull/262)
- Dependencies: merged Phase 12 plus read-only Phase 13 candidate `748f938`
- Workflow path: expanded; a detached-process ownership boundary requires one
  independent review after validation
- Blockers: none

## Objective And Context

- Vertical outcome: retain the validated Phase 13 renewal, exact assignment
  replay, SLURM rejection, and supervisor lifecycle work while making both
  supported role constructors leak-free when protected configuration is
  rejected after process-free initialization.
- Earlier dependency: Phase 13 candidate `748f938` passed its focused matrices
  and full validation, but required review reproduced a newly started empty
  supervisor surviving local scheduling-fingerprint rejection and outbound
  deployment-fingerprint rejection. Phase 13 exhausted correction 3/3 and is
  read-only blocked evidence.
- Later work explicitly out of scope: reloadable configuration identity,
  complete protected authority/composition, management reads, CLI expansion,
  and examples remain Phases 14-15.

## Current Source And Harness

- `src/loom/queue/local_daemon.py` owns local role construction. The candidate
  starts or joins the supervisor before the durable scheduling fingerprint and
  later execution construction have completed; its exception path closes role
  locks but does not distinguish a newly started empty service from a joined
  pre-existing owner.
- `src/loom/queue/agent_session_transport.py` owns outbound construction. The
  candidate opens or starts the supervisor before validating the protected
  journal and deployment binding, so a binding rejection can leave the new
  service detached.
- `src/loom/queue/_agent_process_supervisor.py` already owns process-free
  initialization, start/join, launch quiescence, continuity epochs, and clean
  shutdown. Reuse those operations; do not add a second process owner.
- Existing Phase 13 tests cover process-free init, busy refusal, retained-
  journal refusal, clean rotation, production cleanup, and exact supervisor PID
  containment. Add only the two rejected-construction paths and the causal
  pre-existing-owner negative.

## Scope

In scope:

- Selectively reuse the complete validated Phase 13 source and causal tests.
- Complete all non-mutating durable role/configuration checks that can reject a
  supported startup before creating a supervisor process.
- Where later construction can still fail, track whether this invocation
  created an empty supervisor and invoke the existing clean shutdown operation
  on that exact owner before releasing construction state.
- Preserve a supervisor that was already running or that contains/retains work;
  a rejected second opener must not terminate another role instance.
- Add process-level tests for changed local scheduling configuration, mismatched
  outbound deployment fingerprint, and rejection while a valid pre-existing
  supervisor remains available.

Out of scope:

- Forced process termination, inference that unknown work is empty, migration,
  compatibility, another supervisor protocol, or broad constructor refactoring.
- Changing the accepted Phase 13 renewal/replay/release state machines.
- Phase 14 protected reload semantics or Phase 15 example/management changes.

Assumptions:

- The existing supervisor clean-shutdown proof is the only authority allowed to
  terminate the service.
- Protected configuration is trusted project code but still must match durable
  role bindings and active fingerprints before a role becomes live.

## Fixed Contracts And Private Discretion

- Observable behavior: fresh initialization remains process-free. Successful
  serve starts or joins one supervisor. An expected local or outbound
  configuration rejection leaves no newly created supervisor process.
- Ownership behavior: a failed constructor may clean only the empty supervisor
  it created. It must never stop a joined pre-existing service or bypass
  retained-launch/agent-journal quiescence checks.
- Public or durable shapes: retain the candidate's protocol v10, root schema
  v10, supervisor schema/continuity marker, renewal records, and assignment
  identities without another format change unless a demonstrated format
  conflict requires the manager to stop.
- Trust and failure boundaries: validate durable role identity and protected
  configuration before process creation where possible; later exception
  cleanup must be ownership-aware and use the normal protected shutdown proof.
- Reproducibility and compatibility: preserve the accepted hard cut; no
  migration or dual read.
- Private choices: validation ordering, a private started-versus-joined return
  value, and localized context-manager/try-finally structure are discretionary
  if the fixed ownership behavior and tests hold.

## Proportionality

- Existing seams reused: Phase 13 candidate source/tests and the existing
  supervisor start/join and `shutdown_clean` operations.
- Material addition: only ownership-aware construction cleanup and three causal
  tests correspond to the independently reproduced leak.
- Deferred: generic resource transaction helpers, forced administrative kill,
  automatic unknown-work cleanup, and constructor framework abstractions.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Local rejected startup leaves no service it newly created | `LocalDaemon.start()` construction transaction | changed protected scheduling fingerprint or later owner-construction failure | detached empty supervisor survives a failed role start | changed-config PID/process sentinel |
| Outbound rejected construction leaves no service it newly created | `LocalDaemonAgentHttpClient` construction transaction | deployment binding or journal rejection after supervisor start | detached empty supervisor survives a failed client open | mismatched-fingerprint PID/process sentinel |
| Failed opening never terminates another owner | existing supervisor plus clean-shutdown proof | second invalid opener encounters an already-running or retained-work service | live/recoverable work loses its process owner | pre-existing-service remains reachable and same epoch/PID |

## Implementation Slices

1. Selectively apply Phase 13 source/test changes to the fresh branch and verify
   that the diff contains no blocked-branch workflow metadata.
2. Reorder safe durable validation and add ownership-aware cleanup for the
   remaining post-start failure windows in local and outbound construction.
3. Add the three process-level causal tests, rerun the focused Phase 13 matrix,
   then run the full implementation gate and durable summary.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required if exports change | public import hard cut | no accidental export or dependency change |
| Unit | required | private ownership/cleanup decisions | created versus joined service is distinguished exactly |
| Contract | required for candidate protocol reuse | protocol/schema v10 | existing Phase 13 hard-cut tests remain green |
| Integration | required | both reproduced rejection paths and retained owner safety | rejection, zero new PID, existing PID/epoch remains reachable |
| E2E | required | init/serve/stop and production leak containment | exact process sentinel and normal cleanup |

Targeted commands:

    uv run pytest tests/unit/loom/queue/test_agent_process_supervisor.py tests/integration/queue/test_local_daemon_production.py tests/integration/queue/test_agent_session_transport.py
    uv run pytest tests/integration/queue/test_slurm_ready_stage.py tests/unit/loom/queue/test_agent_sessions.py tests/unit/loom/cli/test_queue.py tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risk: cleanup cannot infer ownership from endpoint presence alone and
  must not convert a failed opener into termination of pre-existing or retained
  work.
- Review focus: construction ordering, exact created-versus-joined ownership,
  clean-shutdown proof reuse, and process-level negative assertions.
- Stop if: the closure requires force-killing unknown work, changing the Phase
  13 durable state machines, weakening configuration validation, or expanding
  into Phase 14.
- Accepted debt: genuinely unknown or retained work deliberately keeps its
  supervisor alive; administrative forced termination remains deferred.

## Executor Handoff

- Read section range: this entire phase plan plus Phase 13's `Workflow State`
  and `Completion Record` only.
- Safe implementation slices: 1-3 above, in order.
- Decisions not to revisit: selective candidate reuse, process-free init,
  quiescence-only shutdown, and preservation of a joined/pre-existing owner.
- Conditions requiring manager action: any format/public contract change,
  inability to distinguish ownership safely, or need to touch Phase 14 scope.

## Workflow State

- Manager preparation: passed; clean current `origin/develop`, blocked candidate evidence, selective-reuse boundary, process ownership invariants, and targeted gates verified at `f9b18c1`
- Expanded planning: not needed; the independent Phase 13 finding fixes the
  accepted behavior and supplies the smallest remedy/test boundary
- Implementation: correction 1/3 complete; owner-store/execution-journal
  validation and the shared retained-work proof now run before supervisor
  creation, and created-service cleanup reuses that proof before clean shutdown
- Refiner: complete; correction 2/3 closes the current-epoch exited-root
  containment gap before a clean shutdown can retire the service owner
- Pre-submit gate: passed at final source/test revision `6a578f8`;
  `make validate-pr` passed Ruff, Pyright, 2,685 default tests, 156
  configuration-extra tests with 3 expected skips, and both distribution
  builds. Fresh `make test-summary` recorded 2,841 categorized passes and 3
  expected skips.
- Independent review: passed after the reviewer reproduced the pre-loop
  outbound stop-handoff leak and confirmed correction 3 closes every return
  after the initially opened client through retained-work-aware cleanup
- Blocker corrections: 3/3; correction 1 closes direct constructor cleanup's
  retained-work-proof bypass. Correction 2 contains a current epoch's exited
  root group before clean shutdown when owned group evidence shows descendants
  remain; historical clean-epoch terminal rows remain restartable. Correction
  3 carries the initially opened outbound client through the normal cleanup
  owner so a stop arriving during close cannot bypass clean shutdown.
- PR and merge: [#262](https://github.com/samcantrill/loom/pull/262) is open,
  non-draft, targets `develop`, and was verified cleanly mergeable; merge pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Selectively reused the Phase 13 source/test candidate under `src/loom/queue` and directly relevant queue tests, then changed `LocalDaemon.start()` and `LocalDaemonAgentHttpClient` construction to preserve created-versus-joined supervisor ownership. Correction 1 centralizes the local retained-work proof with normal shutdown, validates owner stores/journals before process creation, and permits created-service cleanup only after a fresh empty proof. Correction 2 changes `AgentProcessSupervisor` clean shutdown to contain an exited current-epoch root's still-live owned process group before writing the clean marker. Correction 3 removes the separate outbound pre-loop probe and carries that opened client through the ordinary cleanup-owned service iteration. |
| Tests added or updated | Added process-level proof for changed local scheduling rejection, mismatched outbound deployment binding, unavailable local owner-store and outbound execution-journal rejection, retained local owner preservation without a clean marker, and rejection that leaves a valid pre-existing outbound supervisor's PID and epoch reachable. Correction 2 adds supervisor proof that a gone exited group permits epoch rotation, and that clean service shutdown records containment and leaves no TERM-ignoring descendant alive after its root exits. Correction 3 adds a deterministic stop-during-initial-close handoff test with an exact supervisor-process assertion. |
| Validated revision/tree state and evidence | Original focused tests passed (3); targeted lifecycle matrix passed: 85 tests in 377.39s; targeted SLURM/session/CLI/E2E matrix passed: 69 tests in 121.57s. Correction 1 focused constructor/shutdown matrix passed: 7 tests in 2.25s; changed-file Ruff and Pyright passed. Correction 2 focused supervisor suite passed: 7 tests in 0.82s; changed-file Ruff and Pyright passed. Correction 3 passed its two causal service tests, the complete 38-test outbound/session integration file, Ruff, Pyright with zero findings, and an exact empty post-test process scan. At final source/test revision `6a578f8`, refreshed `make validate-pr` passed Ruff, Pyright with zero findings, 2,685 default tests, 156 configuration-extra tests with 3 expected skips, and source/wheel builds. Fresh `make test-summary` recorded 2,841 categorized passes and 3 expected skips in `build/test-summary.md`. |
| Validation-relevant changes after evidence | None. This final completion-record update is documentation-only. |
| PR, review, and merge | Required independent review found one supported outbound stop-handoff leak. Correction 3 closed it, and the same reviewer returned PASS after bounded confirmation. [#262](https://github.com/samcantrill/loom/pull/262) is open, non-draft, targets `develop`, and was verified cleanly mergeable; merge pending. |
| Residual risk and cleanup | An exact post-gate working-directory scan found no process created by either successful gate. One empty supervisor from an earlier deliberately interrupted pre-gate test run was identified by its exact worktree and durable root, stopped through its authenticated test-only shutdown operation, and repeated exact scans after cleanup, correction 3 tests, and the refreshed full gates were empty. No known phase blocker remains. |
