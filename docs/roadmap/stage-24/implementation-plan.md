# Roadmap Stage 24 Implementation Plan: Operational Lifecycle And Recovery Validation

Status: ready
Roadmap stage: `v24`
Planning document: `docs/roadmap/stage-24/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 3 PR open
Blockers: none; the maintainer approved the narrow replacement phase on
2026-08-20 after Phase 2 exhausted its correction budget

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
- Complexity deliberately excluded: new commands, dependencies, process
  reattachment, a Loom daemon, silent repair, automatic retry changes, a full
  backend/failure matrix, platform-wide signal support, and external runtime
  requirements. Phase 2 now includes the one demonstrated durable expansion:
  versioned append-only output-commit supersession.
- Validation and phase-shaping source: planning `Examples And Validation` and
  `Phase Shaping`. Phase 1 owns graceful termination while Loom is alive; Phase
  2 established most authoritative recovery and artifact-trust behavior but was
  blocked before publication. Phase 3 adopts that validated implementation and
  closes only the independently demonstrated HTTP-recovery and renewal-proof
  gaps in one replacement PR.
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
  - A checksum-repair rerun appends an attempt-specific commit naming the
    expected current commit. Authority validates the active fence and current
    head atomically, retains all earlier commits, and projects only the newest
    commit and facts as current. One `list_output_commits` authority read exposes
    retained commit/fact composites in revision order for inspection.
- Shared reproducibility, compatibility, and import constraints:
  - No status enum, config shape, CLI command, plugin, marker, or runtime
    dependency is added. The output-commit record/protocol and SQLite schema are
    versioned only as required for explicit append-only supersession.
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
  exclusive authority and recovery facts, not a dead PID; corruption repair
  uses fenced append-only supersession rather than commit reuse or overwrite;
  no automatic reattachment/repair command, fixed-sleep oracle, full matrix, or
  external Stage 24 runtime gate.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `real-interruption-and-cancellation` | merged | `docs/roadmap/stage-24/phases/real-interruption-and-cancellation.md` | `agent/stage-24-p1-real-interruption-and-cancellation` | [#216](https://github.com/samcantrill/loom/pull/216) | Serial/prepared cancellation, parallel settlement, CLI propagation, subprocess cleanup/timeout, managed-local cancel, and process test support | Prove that graceful stops reach truthful durable state and owned children exit before release. |
| 2 | `crash-recovery-and-artifact-trust` | blocked | `docs/roadmap/stage-24/phases/crash-recovery-and-artifact-trust.md` | `agent/stage-24-p2-crash-recovery-and-artifact-trust` | not opened | Controller renewal/parity, authority recovery/events, old-active resume, authority loss, artifact invalidation, and docs | Prove that unclean loss or corrupt output cannot become reusable success and explicit recovery produces a safe new attempt. |
| 3 | `http-recovery-parity-and-renewal-proof` | pr_open | `docs/roadmap/stage-24/phases/http-recovery-parity-and-renewal-proof.md` | `agent/stage-24-p3-http-recovery-parity-and-renewal-proof` | [#217](https://github.com/samcantrill/loom/pull/217) | Adopt Phase 2 implementation; expose repository run-recovery facts through HTTP; prove renewed ownership beyond original TTL | Publish the complete Stage 24 recovery behavior only after the supported HTTP authority path satisfies the same recovery contract as direct SQLite. |

Phase 1 is independently useful: operators receive correct Ctrl-C/timeout/cancel
semantics and real worker cleanup. Phase 2 started only after Phase 1 was
remotely merged. Phase 3 is permitted because Phase 2 is explicitly blocked; it
is a replacement publication path based on `origin/develop`, contains the
unpublished Phase 2 implementation, and will open the stage's single remaining
PR rather than a stacked PR.

## Quality Gate

- Planning gate: passed. The user accepted the recommendation and requested the
  new Stage 24 with the former Stages 24 and 25 pushed to 25 and 26.
- Manager review: passed. Requirements, decisions, invariant owners, phase
  boundaries, manifest, and linked phase plans are traceable and consistent.
- Optional independent review: required for Phase 2 after implementation
  exposed the one-commit-per-stage conflict and the maintainer approved the
  bounded append-only schema/protocol expansion on 2026-08-20. Completed on
  2026-08-20 with a publication blocker: repository recovery facts are not
  exposed through the supported HTTP authority adapter. Renewal coverage also
  does not yet advance beyond the original controller TTL.
- Maintainer remediation decision: approved on 2026-08-20. Preserve the
  runner's fail-closed proof, expose existing repository recovery facts through
  the v2 HTTP protocol, and add a deterministic post-original-TTL ownership
  assertion. Do not add schema/state/PID recovery machinery or weaken recovery.
- Phase 3 manager gate: passed. The supported HTTP adapter now returns exact
  repository recovery facts and drives the existing fail-closed runner recovery
  sequence; deterministic renewal crosses the original TTL while retaining
  controller exclusivity. Full validation and the durable receipt pass.
- Manager-local refresh correction: applied. Parallel interruption now preserves
  truthful in-flight results, and Phase 2 adds controller renewal and closes
  local-service lease parity before using recovery.
- Ready for implementation: yes.
- Accepted risks: POSIX-specific process tests; parallel local work settles
  rather than being forcibly stopped; no reattachment/machine-loss cleanup;
  external-runtime evidence stays scheduled/manual until Stage 26.
- Revisit triggers: an existing process seam cannot safely terminate/observe its
  owned child; recovery cannot distinguish live from abandoned authority;
  commit supersession cannot preserve old history and atomic current-head
  fencing; or Stage 26 makes a reliable external runtime part of CI.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | [#216](https://github.com/samcantrill/loom/pull/216) squash-merged to `develop` as `8cc9bfa` | 62 focused tests, `make validate-pr`, `make test-summary` (2,267 passed, 3 skipped), manager review, and CI passed | Linux/POSIX signal proof and settled rather than preempted parallel threads remain accepted limits | Phase branch/worktree removed after the merge record; local control-checkout fast-forward deferred to preserve unrelated committed and uncommitted user work |
| 2 | No PR opened; independent review blocked publication | Implementation and full validation passed at `69d3c22` (`make validate-pr`; `make test-summary` with 2,285 passes), but the HTTP recovery path lacks repository recovery facts and the renewal test does not prove exclusivity beyond initial expiry | A managed-service crash cannot currently reach safe explicit recovery through the supported adapter | Worktree and branch retained for maintainer-directed replanning; three correction passes are exhausted |
| 3 | [#217](https://github.com/samcantrill/loom/pull/217) open against `develop` | 50 focused tests; `make validate-pr`; `make test-summary` with 2,289 passes and three environment-dependent skips; manager review passed | External runtimes remain Stage 26 scope; no current correctness blocker | CI, merge, final metadata, and cleanup pending |
