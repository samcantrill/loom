# Roadmap Stage 25-post Implementation Plan: Unified Queue Scheduling Boundaries

Status: approved
Roadmap stage: 25-post
Planning document: `docs/roadmap/stage-25-post/planning.md`
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: Phase 2, factual dispatch outcomes
Blockers: none; the maintainer authorized one explicit correction-budget
exception and the independent-review finding is resolved locally.

## Summary

- Goal: replace the remaining split FIFO/managed claim paths and ambiguous
  dispatch retry instruction with one bounded select/acquire operation followed
  by factual adapter outcomes and controller-owned queue transitions.
- Approved behavior and requirement IDs: planning `FR-1` through `FR-11`,
  including the manager-local bounded `START_UNCERTAIN` correction accepted
  after the expanded removal-first review.
- Key design constraints and decision IDs: `FQ-1` through `FQ-4` and `DQ-1`
  through `DQ-7`; especially hard removal, preference-only policy, one private
  scheduling operation, construction-time repository capability checks, and
  safe capacity as the sole automatic requeue case.
- Minimum useful change: managed and delegated entrypoints choose then acquire
  through one bounded operation; adapters state whether work started,
  completed, definitely did not start, or may have started without a usable
  handle; the controller makes the only queue-policy decision.
- Complexity deliberately excluded: scheduler hierarchy or role protocols,
  repository scheduling public API, compatibility shims, schemas, durable
  scheduler history, reservations, fairness, placement, agents, or transport.
- Validation and phase-shaping source: planning `Examples And Validation` and
  `Phase Shaping`.
- Out of scope: resource-assignment provider vocabulary, Stage 29 assignment
  state, persistent reservations, priority/aging/preemption, and any domain-
  specific scheduling behavior.

## Shared Constraints

- Architecture and dependency direction:
  - import-light `selection.py` retains the five public preference types;
  - controller/private queue code may compose selection, models, service, and
    repository capabilities but selection imports no adapters or authority;
  - repository/SQLite never import controller, local, SLURM, or Stage 29 code;
  - authority/provider/adapters keep admission, placement, process, and cleanup
    truth; the controller keeps queue transition policy.
- Shared public and durable contracts:
  - remove `QueueService.claim_next` and `QueueRepository.claim_next` without a
    shim; exact ownership remains internal;
  - keep `QueueSelectionCandidate`, `QueueSelectionContext`,
    `QueueSelectionDecision`, `QueueSelectionDisposition`, and
    `QueueSelectionPolicy` unchanged;
  - Phase 2 exposes typed dispatch disposition, non-start cause, and cleanup
    status. `START_UNCERTAIN` is terminal queue-local `UNKNOWN`, stops fill, and
    is never treated as non-start or retried;
  - queue item, config, SQLite, run, authority, artifact, and audit schemas do
    not migrate. Existing audit evidence fields may carry bounded facts.
- Shared reproducibility, compatibility, and import constraints:
  - bounded candidate order remains `(enqueued_at, queue_item_id)`;
  - policy ID is validated and frozen at controller construction;
  - the hard cut-over is allowed by the current `0.1.0` surface and no accepted
    external compatibility commitment was found;
  - package imports remain typed and cheap, with no new dependency.
- Shared invariant ownership:
  - selection owns eligibility projection and preference validation;
  - SQLite owns exact compare-and-set ownership and claim audit;
  - adapters own factual start/terminal/cause/cleanup evidence;
  - `QueueDispatchResult` owns cross-field validity;
  - controller owns requeue/fail/unknown/continue/stop decisions.
- Decisions no phase may reopen: one private scheduling operation rather than
  role abstractions; no FIFO shortcut; no legacy outcome normalization; safe
  capacity only requeues; no reservation state in this stage.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `unified-selection-ownership` | merged | `docs/roadmap/stage-25-post/phases/unified-selection-ownership.md` | `agent/stage-25-post-p1-unified-selection-ownership` | #223 | Private scheduling operation, policy binding, repository capability/cut-over, controller and caller migration | Make every current path select and acquire through one bounded implementation. |
| 2 | `factual-dispatch-outcomes` | in_progress | `docs/roadmap/stage-25-post/phases/factual-dispatch-outcomes.md` | `agent/stage-25-post-p2-factual-dispatch-outcomes` | pending | Public dispatch facts, built-in adapters, controller transition table, diagnostics/evidence | Make retry impossible unless capacity non-start and cleanup are both proven safe. |

## Quality Gate

- Planning gate: expanded planning passed after one removal-first review and one
  bounded correction for reachable start uncertainty.
- Manager review: requirements, decisions, invariants, and two vertical phases
  are internally consistent; no accepted requirement remains open.
- Optional independent review: completed one expanded readiness pass; it found
  one Phase 2 transition blocker and one removable orphan export.
- Correction: one bounded correction locks cleanup-sensitive invalid-work
  behavior and removes the public `QueueClaimResult` export.
- Ready for implementation: yes.
- Accepted risks: hard removal breaks unknown external Python callers; bounded
  selection can starve large requests; a start-uncertain external job cannot be
  inspected or cancelled by Loom without a usable handle.
- Revisit triggers: a concrete compatibility commitment before Phase 1 merge,
  measured starvation with an accepted objective, or a current durable
  reservation consumer.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | PR #223 passed CI and squash-merged as `0267a2c` | implementation and manager review complete; required local validation passed at `3cd8759` | Hard removal may affect unknown external callers; private repository scheduling capability intentionally remains unstable until Stage 29. | remote/local branch and dedicated worktree removed |
| 2 | pending PR | independent-review blocker resolved under one maintainer-authorized correction-budget exception; manager pre-submit review and required validation pass at `0bfb546` | Start uncertainty has no external recovery without a handle; no contradictory definite non-start evidence remains | branch/worktree retained through PR and remote merge |
