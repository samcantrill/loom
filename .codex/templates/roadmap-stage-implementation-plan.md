# Roadmap Stage <N> Implementation Plan

Status: draft
Roadmap stage: <N>
Stage descriptor: <approved roadmap descriptor or approved fallback>
Planning document: docs/roadmap/stage-<N>/planning.md
Workflow: .codex/workflows/roadmap-stage-implementation.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase:
Blockers:

## Summary

- Stage outcome and approved scope (planning owner links):
- Approval record (planning manifest section):
- Accepted risks, decisions, and deferrals (exact references):

## Shared Constraints

Reference exact contract paths/headings and owned IDs. Keep definitions at their
planning owner, including public/durable interfaces, trust boundaries, provenance,
compatibility, dependency direction, and invariant ownership.

| Constraint / IDs | Authoritative path and section | Consuming phases |
| --- | --- | --- |

## Execution Context

- Clean control checkout:
- Execution worktree root:
- Persistent stage worktree: <root>/stage-<N>
- Coordination branch: agent/stage-<N>
- Shared Git gate: .codex/prompts/phase-loop-management.md
- All phase branches/PRs use this worktree through final synchronized closeout.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal | Validation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | <slug> | pending | docs/roadmap/stage-<N>/phases/<slug>.md | agent/stage-<N>-p1-<slug> | pending |  |  |  |

Each card owns its observable result, cohesion, ownership, dependencies,
acceptance, supported merge boundary, and exclusions. No phase-count target
applies. Keep one invariant's producers/consumers/docs/tests together; split
independently acceptable outcomes.

## Planning-To-Implementation Traceability

| Planning card / accepted IDs | Shared reference, phase, or approved deferral |
| --- | --- |

## Implementation Plan Review

This is the authoritative final readiness receipt; planning links here. Reuse
it at startup unless relevant source/contract drift invalidates its evidence.

- Status: pending
- Reviewed packet revision/tree and exact paths:
- Relevant source assumptions and revision:
- Independent reviewer and result:
- Findings and correction/confirmation disposition:
- Accepted risks and revisit triggers:
- Relevant post-review changes and affected verification:

| Finding | Severity | Owning contract/card | Resolution | Status |
| --- | --- | --- | --- | --- |

Record only actual passes under .codex/prompts/subagent-lifecycle.md.

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |

## Implementation Workflow State

- Startup drift check and readiness reuse:
- Automatic merge mode: enabled after local validation and independent review
- Phase statuses: pending, in_progress, pr_open, approved, merged, blocked
- Stage cleanup and terminal disposition:
- Improvement log entries: none / relevant IDs

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 |  |  |  |  |
