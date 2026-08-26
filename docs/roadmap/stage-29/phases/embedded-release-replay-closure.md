# Phase 9D2 Execution Plan: Embedded Release Replay Closure

## Metadata

- Status: pr_open
- Roadmap stage and phase: Stage 29, Phase 9D2
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9d2-embedded-release-replay-closure`
- Worktree root: `/home/can134/work/active/loom-worktrees`
- Worktree path:
  `/home/can134/work/active/loom-worktrees/stage-29-p9d2-embedded-release-replay-closure`
- Base revision: clean `origin/develop` at
  `00ce27f380b4b8a8356089e5ee6541597e65cab0`
- PR target: `develop`
- PR title: `fix(scheduling): close embedded release replay`
- Dependencies: Phase 9C2 remotely merged as `b0ed116`. Blocked Phase 9D
  candidate `a7f3014` is read-only evidence; validated source/test revision
  `c516f63` is the selective reuse boundary. Phases 9E and 9F remain pending.
- Workflow path: expanded only for one final independent review because this
  phase closes a causal release sequence across two durable owners. The remedy
  is fixed, so no phase-planner pass is needed.
- Blocker corrections: 0/3

## Objective And Context

Merge the complete hard-cut embedded/local supervisor consumer from blocked
Phase 9D after making its final provider-release sequence replay-safe. A local
daemon restart at any durable boundary must reuse the exact committed release
revision, finish the final event while the assignment remains discoverable,
and only then remove the assignment from coordinator replay.

Phase 9D passed its 177-test focused matrix and full `make validate-pr` gate,
but required review found one release-order blocker after correction 3/3. This
fresh closure preserves the validated implementation without treating it as a
merge base and owns only that blocker plus causal proof.

## Current Source And Harness

- Current `origin/develop` contains Phase 9C2's private resident supervisor and
  remote released-state precedent in
  `src/loom/queue/agent_session_transport.py`.
- Blocked Phase 9D moves embedded composition to
  `src/loom/queue/_managed_local.py`. Its `finalize_result()` currently
  publishes journal availability, advances the coordinator to `released`, and
  then emits the final event. Its definitive-decline branch has the same shape.
- `SQLiteAgentJournal.read_availability_revision()` already exposes the exact
  persisted revision. `SQLiteCoordinatorAssignments.retained_assignments()`
  intentionally excludes coordinator state `released`.
- `LocalDaemonExecution.resume_retained_local_work()` synchronously reconciles
  retained local assignments before daemon visibility and capacity polling.
- Candidate tests already cover explicit profile/CLI cut-over, supervisor-only
  launch, resident bundle projection, result/output replay, cancellation, and
  same-PID restart. Missing coverage is the terminal release/event crash cut.

## Scope

In scope:

- Selectively reuse Phase 9D source, test, example, and operational-guidance
  commits through `c516f63`, excluding all Phase 9D roadmap commits.
- Make normal terminal release state-driven: if journal release is already
  durable, freshly observe the reconstructed provider set but reuse the exact
  persisted availability revision instead of publishing a replacement.
- Emit, durably record, and acknowledge the stable final release event while
  the coordinator assignment remains replay-visible; advance the coordinator
  to `released` only afterward.
- Apply the identical release invariant to definitive decline.
- Add deterministic crash-boundary tests proving restart completion, stable
  revision/event identity, no duplicate worker launch, and no early capacity.

Out of scope:

- Any compatibility alias, migration, fallback release algorithm, or support
  for roots created by the unmerged Phase 9D candidate.
- Changes to Phase 9C2 remote supervisor semantics, provider public APIs,
  resident bundle content, CLI/profile contracts, or durable schemas unless
  the fixed replay rule is impossible with the existing states.
- SLURM guarded recovery, different-session replacement, supervisor HA,
  automatic takeover, or Phase 9E/9F behavior.

## Fixed Contracts And Private Discretion

- This remains a hard cut. The complete Phase 9D behavior replaces the old
  callable/thread owner and optional service hooks; no old behavior survives.
- A journal state of `RELEASED` is an exact committed release fact. Restart
  must re-observe current provider truth, reject a still-live assignment claim,
  and reuse `read_availability_revision()` for replay.
- The final `provider_released_availability_fresh` or
  `definitive_decline_released` event uses its stable event ID and must be
  persisted to the coordinator and acknowledged in the journal before the
  coordinator assignment becomes `released`.
- A crash after event acknowledgement but before coordinator release remains
  replayable and completes idempotently without another physical release,
  availability revision, event identity, or worker launch.
- Startup continues to withhold scheduling and polling until the complete
  retained set has reconciled and providers have been freshly observed.
- The executor may use one private helper for the shared terminal/decline
  closure and may simplify local wiring. No new public surface or general saga
  framework is justified.

## Proportionality

- Reuse the existing journal states, stable event/outbox operations,
  coordinator retention query, synchronous startup barrier, and the remote
  consumer's released-state pattern.
- The only material addition is state-aware final release plus crash-cut tests;
  it is required because the supported daemon restart can otherwise fail or
  omit durable final evidence.
- New schemas, distributed transactions, generic workflow machinery, broader
  recovery, and compatibility handling are deferred or explicitly excluded.

## Invariant Ownership

| Invariant | Owner | Reachable invalid boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| A committed release keeps one exact revision | Agent journal | Restart after availability publication | Conflicting replay prevents daemon startup | Reconstructed-provider replay test |
| Final event is complete before replay removal | Coordinator release ordering | Stop before/during final event | Missing or unacknowledged release evidence | Event-boundary restart test |
| Terminal and decline share release semantics | Private local release closure | Definitive prepare decline | Declined assignment can disappear or conflict | Terminal/decline matrix |
| Capacity remains withheld through replay | Local daemon startup barrier | Fresh application startup | Released atoms can be offered too early | Causal capacity barrier assertions |

## Implementation Slices

1. Selectively carry the validated Phase 9D source/tests/guidance onto the
   clean Phase 9D2 base without its roadmap commits or blocked metadata.
2. Implement one replay-safe final release sequence for normal terminal and
   definitive-decline paths using fresh observation plus saved-revision replay.
3. Add deterministic crash injection at availability publication and final
   event/coordinator-release boundaries; verify exact revision/event replay,
   one launch, complete release, and withheld capacity.
4. Run the focused Phase 9D matrix and the full implementation gate; record
   exact evidence and any residual blocker in this plan's completion record.

## Test And Validation Plan

- Unit: journal released-state revision reuse and idempotent final event/order.
- Contract: no compatibility surface or pipeline-owned managed execution is
  restored.
- Integration: fresh local application restarts after journal release and
  after final event acknowledgement; normal terminal and definitive decline
  both settle exactly, without a second launch or early offer.
- Regression: the existing Phase 9D bundle, supervisor, cancellation, local
  daemon, CLI, provider, remote, package, and import-boundary matrices.

Targeted commands:

    uv run pytest -q tests/unit/loom/queue/test_managed_local.py tests/integration/pipeline/test_managed_local_execution.py tests/integration/queue/test_local_daemon_production.py
    uv run pytest -q tests/unit/loom/queue/test_local_daemon.py tests/unit/loom/cli/test_queue.py tests/contracts/test_queue_python_api_contract.py tests/package/test_pipeline_execution_api.py

Final command:

    make validate-pr

Phase 9F continues to own `make test-summary` and the final Stage 29 summary.

## Risks, Review, And Stops

- Main risks are recomputing a committed revision, hiding coordinator work
  before event acknowledgement, making only one of terminal/decline safe, or
  weakening the startup availability barrier.
- Independent review must inspect both crash cuts, both release callers, exact
  revision reuse after provider reconstruction, stable event replay, and the
  absence of compatibility or Phase 9E/F scope.
- Stop if the existing journal/coordinator states cannot express the ordering,
  if a new public/durable decision is required, or if selective reuse contains
  unrelated behavior. Do not reopen Phase 9C2 or broaden recovery.

## Executor Handoff

- Read this plan from `Current Source And Harness` through this heading; read
  blocked Phase 9D only at `Workflow State`, `Blocker`, and `Completion Record`.
- Reuse only the Phase 9D source/test/example/guidance commits through
  `c516f63`; exclude its roadmap commits and do not base or merge the branch on
  Phase 9D.
- Implement all four slices, commit coherent source/test changes, run the
  targeted commands and final gate, and update only this plan's completion
  record with result/evidence.
- Do not edit the manifest, prepare a PR, perform review/merge work, ask the
  maintainer, preserve old behavior, or delegate. Stop on a missing contract.

## Workflow State

- Manager preparation: complete on clean current `origin/develop` at
  `00ce27f`; repository/worktree/branch and Phase 9D evidence boundaries are
  verified, and maintainer approval is recorded.
- Expanded planning: not needed because the independent-review finding, remote
  precedent, required ordering, and stop conditions are exact.
- Implementation: executor ordering closure at `3457cc0`; correction 1/3 adds
  causal terminal and definitive-decline crash-after-final-acknowledgement
  replay proof and restores the replayed successful output receipt. Manager
  correction 2/3 adds the missing earlier crash cut where availability is
  durable but the final event does not yet exist, for both release callers.
- Refiner: correction 1/3 complete at `b9727ca`.
- Pre-submit gate: complete at `731b3c4`. The four-case causal matrix and
  102-test affected matrix passed. Refreshed `make validate-pr` passed Ruff,
  zero-finding Pyright, 2,553 default tests, 141 config-extra tests with three
  expected skips, and source/wheel builds.
- Independent review: required after manager validation.
- Blocker corrections: 2/3.
- PR and merge: [#247](https://github.com/samcantrill/loom/pull/247) is open,
  non-draft, mergeable, and verified with base `develop`, exact head/title, and
  body matching scope/evidence. Required independent review and CI are pending.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Complete selective Phase 9D source/test/example/guidance reuse plus replay-safe terminal and definitive-decline release in `src/loom/queue/_managed_local.py`: reconstructed providers are freshly observed, an existing journal revision is reused, the stable final event is acknowledged before coordinator release, and successful output receipts replay idempotently. No durable schema or compatibility path was added. |
| Tests added or updated | The managed-local integration now crashes both after availability publication with no final event and after final-event acknowledgement, for terminal success and definitive decline. Each case reconstructs journal/provider state, replays the saved revision, proves one acknowledged event at both stores, completes coordinator release, and retains one supervisor launch where applicable. |
| Validated revision/tree state and evidence | Source/test revision `731b3c4`: focused four-case causal matrix passed in 2.76s; affected Phase 9D2 matrix passed 102 tests in 47.42s; `make validate-pr` passed Ruff, zero-finding Pyright, 2,553 default tests (121 deselected), 141 config-extra tests (3 expected skips), and source/wheel builds. |
| Validation-relevant changes after evidence | none; this roadmap evidence update is non-validation metadata |
| PR, review, and merge | [#247](https://github.com/samcantrill/loom/pull/247) open against `develop`; required independent review and CI pending. |
| Residual risk and cleanup | pending |
