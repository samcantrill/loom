# Roadmap Stage 37 Implementation Plan

Status: complete; merged
Roadmap stage: 37
Planning document: docs/roadmap/stage-37/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: complete
Blockers: none

## Summary

- Goal: let stage code read which boundary owns descendant-process containment
  without environment, metadata, or route inference.
- Approved behavior and requirement IDs: FR-1 through FR-4.
- Key design constraints and decision IDs: FQ-1 through FQ-3 and DQ-1 through
  DQ-4; `ProcessContainmentOwner.STAGE` versus `OUTER_BOUNDARY`, conservative
  compatibility default, explicit internal propagation, and no persistence.
- Minimum useful change: one public enum, one immutable keyword-only
  `StageContext` field, current construction/entry wiring, docs, and focused
  propagation tests.
- Complexity deliberately excluded: config/environment protocol, route enum,
  executor capability, durable/fingerprint field, process helper, registry,
  cgroup abstraction, and new containment mechanism.
- Validation and phase-shaping source: planning `Examples And Validation` and
  `Phase Shaping` after the expanded design-safety correction.
- Out of scope: changing agent-supervisor or SLURM containment, cancellation,
  result trust, retry, scheduler, or execution-policy behavior.

## Shared Constraints

- Architecture and dependency direction: import-light pipeline context defines
  the public fact; queue/execution callers pass it without pipeline importing
  queue, executors, or scheduler code.
- Public and durable contracts: `loom.pipeline.ProcessContainmentOwner` and
  `StageContext.process_containment_owner` are public; no durable format or wire
  contract changes.
- Compatibility and import constraints: omitted manual construction remains
  `STAGE`; exact enum instances are required when supplied; pipeline lazy
  imports remain cheap.
- Invariant ownership: `StageContext` owns type/default validation; each context
  constructor or resident entry owns propagation; existing agent/scheduler
  boundaries retain actual containment proof.
- Decisions no phase may reopen: exact public names and two values, no string
  coercion, no environment/config/persistence/helper/registry, and no changes to
  containment mechanisms.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | stage-context-containment-owner | merged | docs/roadmap/stage-37/phases/stage-context-containment-owner.md | codex/stage-context-containment-owner | [#269](https://github.com/samcantrill/loom/pull/269) | pipeline context/export, current context constructors and resident callers, feature docs, focused tests | Expose and propagate one typed containment-owner fact across ordinary and enclosing-boundary execution. |

## Quality Gate

- Planning gate: passed after the independent design-safety reviewer identified
  and the manager corrected the implementation-specific `LOOM` member to
  `OUTER_BOUNDARY`.
- Manager review: requirement/design/phase traceability, one-phase vertical
  shape, and proportional validation pass.
- Optional independent review: passed with no blocker. It identified one
  non-blocking direct shared-helper call in the SLURM integration fixture; the
  phase inventory and focused validation now include it.
- Correction: one manager-local planning clarification added the existing
  SLURM integration caller/test file; no behavior or phase shape changed.
- Ready for implementation: yes.
- Accepted risks: the semantic contract is POSIX/process-boundary oriented;
  manually constructed contexts can assert `OUTER_BOUNDARY`, so documentation
  must state its precondition.
- Revisit triggers: a maintained non-POSIX route, a third materially different
  owner, or a concrete durable inspection/replay consumer.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | PR #269 squash-merged as `f81330eec309fcf0c656613da7498154c2e2c6ca` | Implementation and correction complete; final full validation passed | POSIX/process-boundary semantics, unsupported manual owner assertions, and an unrelated timestamp-test flake remain documented | Remote branch deleted; local worktree cleanup pending metadata push |
