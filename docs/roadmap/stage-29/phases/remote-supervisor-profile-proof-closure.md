# Phase 9C2 Execution Plan: Remote Supervisor Profile And Process Proof Closure

## Metadata

- Status: pr_open
- Roadmap stage and phase: Stage 29, Phase 9C2
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9c2-remote-supervisor-profile-proof-closure`
- Worktree root: `/home/can134/work/active/loom-worktrees`
- Worktree path:
  `/home/can134/work/active/loom-worktrees/stage-29-p9c2-remote-supervisor-profile-proof-closure`
- Base revision: clean `origin/develop` at
  `44d06f329be6660fb12ab3ccc37cc443681733f2`
- PR target: `develop`
- PR title: `feat(scheduling): close remote managed restart`
- Dependencies: merged through Phase 8A. Blocked Phases 9, 9A, 9B, and 9C
  are selective read-only evidence, never dependency bases or supported schemas.
- Workflow path: expanded because process isolation and a durable profile-set
  boundary need independent implementation review. Phase planning refinement is
  not needed: the Phase 9C review identified two exact, bounded closures.
- Blocker corrections: 1/3

## Objective And Context

Merge the already validated remote supervisor/restart vertical only after its
live configuration cannot diverge from the supervisor's initialized launch
profile set and its restart guarantees are proven across real agent application
processes. This is a hard cut: changing the executable profile set requires a
fresh explicitly initialized agent root; Loom does not migrate, update, or
dual-read the existing supervisor root.

Phase 9C at `d9cc0ae` passed the full local gate and established the separate
locked/authenticated service, exact materialized launch, positive process-group
containment, remote process-owner removal, retained-result replay, and zero-
capacity restart barrier. Required review blocked it because trusted reload can
install a profile set different from the service-bound set, and because its
restart matrix uses two client objects in one pytest process while its
two-profile test proves only configuration binding. Preserve that branch as
evidence; this successor owns exactly those findings and their causal tests.

## Scope

In scope:

- Selectively restore the validated Phase 9C source, tests, and remote operator
  guidance from `d9cc0ae` onto the fresh base. Do not copy its commit history or
  treat any earlier blocked schema as compatible state.
- Make trusted reload compare the complete canonical replacement launch-profile
  set with the supervisor-bound set before swapping configuration. Any member
  addition, removal, descriptor/executable/project change, or empty/non-empty
  transition is rejected and leaves the current drained configuration intact.
- Keep harmless ordering canonical and preserve currently valid non-launch
  reload behavior only when it cannot change what the supervisor may execute.
- Replace or extend the restart matrix so agent application A and agent
  application B run in independently spawned Python processes against the same
  continuously running supervisor. Cover crash before supervisor acceptance,
  after acceptance, before result commit, and before coordinator release.
- Exercise a single root bound to two distinct resident profiles and prove that
  supported selection routes each assignment to its exact allowed profile and
  records the matching durable launch identity.
- Retain the Phase 9C ownership, containment, exact-replay, cancellation,
  output/result, provider-release, and no-early-offer regressions.

Out of scope:

- In-place profile-set update, supervisor migration/restart/HA, compatibility
  adapters, old-root upgrade, or reload-driven supervisor replacement.
- Embedded/local execution, shared bundle projection, local CLI flags, SLURM,
  guarded recovery/retry, different-session replacement, or Phase 9D-9F work.
- A public supervisor protocol, public process-test hooks, a new deployment
  service manager, or broader configuration-reload redesign.

## Fixed Contracts

### Profile-set reload hard cut

The initialized supervisor remains the sole authority for executable bindings:

```text
current = canonical(supervisor-bound launch profiles)
candidate = canonical(replacement resident launch profiles)

if candidate != current:
    reject reload as requiring fresh agent-root initialization
else:
    validate and apply the remaining supported owner-local changes
```

The comparison includes every profile ID, protected descriptor, project root,
and Python executable and is insensitive only to input ordering. A rejected
reload cannot replace `_config`, `_profiles`, provider state, the supervisor
client, or the reported config/inventory revision. A no-profile agent may stay
no-profile; it cannot gain resident execution through reload. A resident agent
cannot drop, add, or change executable profiles through reload.

The service still validates every launch against its own durable configuration.
That final check is defense in depth; it is not the normal place to discover a
configuration mismatch after an offer, grant, or provider claim.

### Fresh-process restart proof

The causal proof uses fresh interpreter processes, not merely new objects:

```text
parent: coordinator + TLS endpoint + initialized agent root
agent process A: open root -> accept exact work -> reach named crash barrier -> exit
continuous supervisor: retain one launch/process group and exact receipt
agent process B: open same root -> reconcile retained work -> replay release
parent: observe one launch, terminal result, then one fresh offer
```

Use `spawn` or an equivalent fresh-interpreter subprocess. `fork` alone is not
sufficient because it can inherit memory, locks, monkeypatches, and client
objects. A process may install test-local wrappers around its own client to
reach a barrier, but production code gains no crash-test switch. Each barrier
must prove one durable supervisor launch, exact result/release replay, zero
offer/poll before reconciliation, and fresh capacity only afterward.

### Two-profile routing proof

One explicitly initialized root binds profiles A and B with the same supported
capacity domain and distinct launch identities. Supported assignment selection
must execute one assignment through A and another through B. The test verifies
both terminal results and the supervisor's two exact durable launch records,
including the selected profile ID/fingerprint. Reordering the same complete set
opens successfully; adding, removing, or changing a member fails before any
capacity can be advertised.

## Implementation Slices

1. Restore only the validated Phase 9C production/test changes and confirm the
   remote client still has no direct process owner.
2. Add the authoritative profile-set reload comparison and focused hard-cut
   positives/negatives without creating an update path.
3. Add the fresh-process four-barrier restart matrix and two-profile routing
   integration, then update only current remote guidance/evidence.

Private helper shape, subprocess orchestration, and test fixture layout remain
implementation details. Reuse existing supervisor/configuration fingerprints
and current supported assignment selection rather than adding another identity
owner or test-only production interface.

## Test And Validation Plan

- Unit/contract: canonical profile-set reorder; add/remove/change and
  empty/non-empty reload rejection; rejected reload leaves current state intact;
  exact service launch validation; no remote `_processes` or direct `Popen`.
- Integration: two selected profiles launch and finish through one service;
  fresh interpreter process A/B at all four crash barriers; exact one-root
  count; matching result digest; provider/outbox replay; no offer or poll before
  reconciliation; detached service teardown.
- Regression: affected supervisor, remote agent-session, managed journal,
  transfer/output, GPU environment, cancellation, and reload tests.
- Gate: focused changed-path Ruff/Pyright and affected tests, then
  `make validate-pr`. Phase 9F still owns the final stage test summary.

## Risks, Review, And Stops

- Main risks are comparing only profile IDs, mutating live config before the
  comparison, using fork/same-process objects as restart proof, inspecting a
  database row without exercising supported profile selection, weakening
  containment, or introducing embedded/recovery behavior.
- Required independent review must verify the reload rejection occurs before
  swap/offer/grant, both agent sides are fresh processes, two profiles route end
  to end, one continuous service owns all groups, and Phase 9D-9F remain absent.
- Stop if selective reuse conflicts with current `develop`, a supported
  two-profile assignment cannot be produced without a product decision, or the
  fresh-process proof would require a public/test-only production hook. Report
  the exact reachable path and smallest remedy; do not broaden the phase.

## Executor Handoff

- Read this plan completely, the Phase 9C Completion Record and review finding,
  and current source/tests. Selectively reuse Phase 9C production/test commits
  `718d3a5`, `9794173`, `34012a4`, `8eb99d3`, `6221b4e`, and `d9cc0ae`; do not
  reuse its roadmap-state commits or any Phase 9-9B schema/history.
- Implement all three slices, run focused validation, and commit source/tests/
  current remote guidance. Do not edit roadmap metadata, perform GitHub work,
  implement Phase 9D-9F, or delegate.
- Return committed implementation plus focused evidence, or one exact
  stop-condition blocker with the smallest remedy.

## Workflow State

- Manager preparation: complete on clean current `origin/develop`; dedicated
  branch/worktree and bounded successor plan recorded
- Implementation: complete through correction 1/3 at `db01737`. The six named Phase 9C production/test
  commits were selectively restored; the successor rejects divergent executable
  profile-set reload before swap, uses spawned interpreter A/B processes at all
  four crash barriers, routes two selected profiles through one supervisor, and
  updates current hard-cut guidance. Correction `db01737` rejects an empty-
  profile reopen when supervisor state exists before acquiring the root lock,
  while preserving a genuine supervisor-free root and valid configured reopen.
- Validation/review: complete. Required independent review found one empty-set
  reopen bypass and no optional hardening. Correction `db01737` closes that
  exact path; manager review verified the rejection precedes root-lock
  acquisition and a correctly configured reopen remains available. Refreshed
  focused and full validation passed with no detached supervisor.
- PR/merge: [#246](https://github.com/samcantrill/loom/pull/246) opened against
  `develop`; verified non-draft, correct title/head/base, and mergeable. CI
  pending.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and tests | `db01737` (`db8e9e2` closure plus correction 1/3); executable profile-set add/remove/change and empty/non-empty reload transitions reject before configuration swap/open, canonical reorder remains accepted, a rejected open does not retain the root lock, the four restart barriers use distinct spawned interpreter PIDs against one continuous supervisor, and two supported selected profiles produce matching durable launch identities and terminal runs. |
| Validated revision and evidence | `db01737`; focused reload/reopen/restart/two-profile integration passed, 9 tests in 25.32s. Refreshed `make validate-pr` exited 0 on 2026-08-26: repository Ruff passed; full Pyright reported 0 errors; default harness passed 2,549 tests with 121 deselected; config-extra passed 141 tests with 3 expected skips and 2,552 deselected; source and wheel builds passed. No detached Phase 9C2 supervisor remained. |
| PR, review, and merge | Required independent review identified one blocker and no optional hardening; correction `db01737` plus refreshed manager review/validation closed it. [#246](https://github.com/samcantrill/loom/pull/246) is open against `develop`; CI and merge pending. |
| Residual risk and cleanup | No known phase blocker. Supervisor HA/adoption, live profile-set migration, embedded/local execution, SLURM recovery, and replacement remain explicitly deferred. Worktree cleanup follows remote merge. |
