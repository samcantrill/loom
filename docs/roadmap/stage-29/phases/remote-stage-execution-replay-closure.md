# Phase 5A Execution Plan: Remote Stage Execution Replay Closure

## Metadata

- Status: planned
- Roadmap stage and phase: Stage 29, Phase 5A
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p5a-remote-stage-execution-replay-closure`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-29-p5a-remote-stage-execution-replay-closure`
- Base revision: clean `origin/develop`
  `4d0a9bb6708752d711701885a793dd28b915571d`
- PR target: `develop`
- PR title: `fix(scheduling): close remote transfer replay`
- Dependencies: Phase 4A [PR #239](https://github.com/samcantrill/loom/pull/239)
  squash-merged as `2d273b8`; blocked Phase 5 source/test candidate `d536a1e`
  and its required independent-review finding are selective evidence only
- Workflow path: expanded only for one independent implementation review. The
  accepted behavior is complete and the repair is bounded, so no phase-planner
  pass is needed.
- Blockers: none. Phase 5 stopped after correction 3/3 because input and output
  publication could survive a crash while their SQLite finalization did not.

## Objective And Context

- Vertical outcome: merge the complete approved Phase 5 remote CPU/memory stage
  execution path only after an interrupted file-finalization operation can be
  replayed without stranding input before grant or output before terminal
  commit.
- Earlier dependency: Phase 4A supplies authenticated no-launch agent sessions.
  The blocked Phase 5 candidate supplies the reviewed resident-profile,
  path-free assignment, bounded relay, process, authority, and release
  composition but is not part of `develop` and must be reused selectively.
- Later work explicitly out of scope: GPU placement, SLURM delegation, ordinary
  cancellation controls, guarded unknown-work recovery, generic execution APIs,
  code shipment, directory artifacts, and direct agent authority access remain
  outside this phase.

## Current Source And Harness

- Relevant candidate paths and symbols: `src/loom/queue/_remote_stage_execution.py`
  owns `RemoteAssignmentWorkspace.stage_input_chunk` and regular-file helpers;
  `src/loom/queue/agent_sessions.py` owns
  `_CoordinatorRemoteExecutionService.stage_output_chunk`; transport, daemon,
  managed execution, and worker changes complete the same vertical path.
- Candidate `d536a1e` passed `make validate-pr`, a fresh 2,576-pass categorized
  summary, and 50 focused remote/managed/session tests. Independent review found
  no other product blocker.
- Existing replay coverage pre-seeds a complete staging part. It does not inject
  a crash after `os.replace`/directory fsync but before the enclosing SQLite
  transaction commits. Both input and output need this exact barrier.
- Preserve `docs/structure.md` ownership and current private import direction.
  No new public import or runtime dependency is justified.

## Scope

In scope:

- Selectively reuse the complete Phase 5 source/test diff from candidate
  `d536a1e`; do not reuse its superseded roadmap metadata.
- Close the identical input and output publish-before-commit crash window.
- Add multi-chunk crash-injection tests for both directions and keep the Phase 5
  focused vertical matrix passing.

Out of scope:

- Compatibility readers, schema migration, dual protocol support, path-bearing
  requests, automatic redispatch, new recovery policy, or optional relay
  hardening.
- Any change to the approved owner split: resident profiles and paths stay on
  the agent; the coordinator retains run URI, authority operations, transfer
  authorization, and artifact relay.

Assumptions:

- Authored configuration remains trusted project code. Transferred artifacts
  remain no-follow regular files bounded to 64 MiB and 32 KiB chunks.
- Old protocol/root/request schemas are intentionally rejected. This is a hard
  cut-over with no migration or fallback behavior.

## Fixed Contracts And Private Discretion

- When durable transfer state says unfinished but the final target exists, the
  owner must open it without following links, require a regular file, and verify
  the exact declared byte count and SHA-256 digest.
- An exact already-published target is the durable evidence of the completed
  filesystem operation. In the same SQLite transaction, mark the transfer's
  received byte count complete and `finalized = 1`, then apply the ordinary
  finalized-replay range check and return the completed offset.
- A link, non-regular file, wrong size, wrong digest, or conflicting replay
  remains a hard conflict. Do not overwrite, delete, quarantine, or silently
  accept a conflicting target.
- A missing target continues through the existing staging/chunk/finalization
  path. A missing or shorter staging file alone must not defeat recovery when
  the exact final target proves publication already succeeded.
- Both directions own the same invariant at their durable boundary: the agent
  workspace owns input finalization; the coordinator relay owns output
  finalization. One shared private validation helper may be reused, but no new
  public abstraction is required.
- Preserve all accepted Phase 5 behavior: global local/remote CPU and memory
  selection, targeted authenticated delivery, durable acceptance/grant/start,
  one contained resident process, renewable transfer authorization, sequenced
  event/result replay, authority output commit, and ordered logical/physical
  release.
- The executor may choose private helper names and test injection seams. It may
  simplify duplicate input/output checks only if ownership and dependency
  direction stay clear.

## Proportionality

- Existing seam reused: the regular-file validation and atomic publication
  helpers plus each owner's existing SQLite transaction.
- Material additions and current justification: one recovery branch in each
  finalizer and two causal crash tests close the only reviewed blocker.
- Optional hardening and future capability deferred: directories, streaming
  stores, larger objects, cleanup of conflicting targets, and generalized
  filesystem transaction machinery have no current consumer.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Published input and durable input-finalized state converge after replay | Agent assignment workspace | Crash after durable rename and before SQLite commit | Input remains unaccepted and stage never receives a grant | Multi-chunk input publish-before-commit injection and replay |
| Published output and durable output-finalized state converge after replay | Coordinator artifact relay | Crash after durable rename and before SQLite commit | Completed stage cannot commit terminal output truth | Multi-chunk output publish-before-commit injection and replay |
| Conflicting published bytes never become accepted state | The same direction-specific owner | Existing link/non-file/wrong size/wrong digest target | Corrupt or substituted artifact could cross the execution boundary | Negative exact-target tests in both directions |

## Implementation Slices

1. Selectively restore the reviewed Phase 5 source and tests onto current
   `origin/develop`, excluding blocked phase metadata.
2. Add exact published-target adoption to input finalization and prove its crash
   replay plus conflict behavior.
3. Add the symmetric coordinator output adoption and prove its crash replay
   plus conflict behavior.
4. Run the focused remote/managed/session matrix, then the stable-tree full
   validation and categorized summary once.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Private modules ship in source and wheel | Existing package/build gate passes |
| Unit | Required | Exact input/output publication replay and conflicts | Inject after publish-before-commit for data larger than one chunk; replay finalizes; wrong target rejects |
| Contract | Required, existing | Hard-cutover protocol, auth, serialization, and ownership | Existing Phase 5 contract selection remains green |
| Integration | Required, existing | Real two-agent/two-stage transfer, restart, outage, and release | Existing Phase 5 vertical tests remain green |
| E2E / opt-in | Existing only | No new environment dimension causally interacts | Full repository gate remains green |

Targeted commands:

    .venv/bin/pytest -q tests/unit/loom/queue/test_remote_stage_execution.py
    .venv/bin/pytest -q tests/unit/loom/queue/test_agent_sessions.py tests/unit/loom/queue/test_agent_session_transport.py
    .venv/bin/pytest -q tests/integration/queue/test_local_daemon.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risk: fixing only the agent input direction or accepting target existence
  without exact regular-file identity would leave the same causal failure.
- Review focus: both owners check target identity before touching staging state,
  record finalization transactionally, preserve exact replay checks, and cover
  the actual post-publication rollback barrier.
- Stop if the fix requires a new durable schema, compatibility path, public
  executor/transfer API, authority move, code shipment, directory artifacts, or
  new recovery policy.
- Accepted debt and revisit trigger: coordinator relay throughput and bounded
  retained output remain accepted Phase 5 debt; revisit only with a concrete
  larger-artifact/backend consumer.

## Executor Handoff

- Read section range: `Current Source And Harness` through `Risks, Review, And
  Stops`, plus manifest `Shared Constraints` only where cited by this plan.
- Safe implementation slices: the four numbered slices above. The executor owns
  the selective source/test reuse and changes in `src/loom/**`, `tests/**`, and
  this phase plan completion record inside the dedicated worktree.
- Decisions not to revisit: hard cut-over, resident-profile owner split,
  coordinator authority/relay ownership, regular-file/size/chunk bounds, and no
  generic public executor or code shipment.
- Conditions requiring manager action: any stop condition above, a second
  product blocker outside exact finalization replay, or inability to preserve
  the previously validated Phase 5 vertical behavior.

## Workflow State

- Manager preparation: complete at clean `origin/develop` `4d0a9bb`; dedicated
  branch/worktree, candidate evidence, exact blocker, target/title, ownership,
  tests, and stop conditions recorded
- Expanded planning: not needed; accepted contracts are complete and the one
  crash window has a concrete minimum remedy
- Implementation: pending
- Refiner: not needed unless one qualified blocker consumes a correction pass
- Pre-submit gate: pending
- Independent review: required after the manager gate because the repaired
  boundary publishes executable input and authoritative output across crashes
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
