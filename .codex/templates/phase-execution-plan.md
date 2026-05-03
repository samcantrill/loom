# Phase <N> Execution Plan: <Title>

## Metadata

- Status: draft phase execution plan
- Branch: `codex/<summary-of-feature>`
- Worktree: `/home/samcantrill/work/loom-worktrees/<summary-of-feature>`
- Phase execution plan path: `docs/phases/<summary-of-feature>.md`
- Full plan: `docs/implementation-plans/implementation-plan-v<N>.md`
- Source phase:
- Stack predecessor:
- Base branch:
- Target branch:
- Merge eligibility:
- Successor dependency notes:
- Plan quality gate:
- Plan quality gate loop budget:
- Draft pass:
- Refine pass:
- Setup limitations:
- Blockers:

## Objective

State the phase objective in one or two paragraphs.

## Full-Plan Context

Summarize how this phase fits into earlier and later phases. Name future-phase
work that must remain out of scope.

## Stack Context

- Root or stacked phase:
- Current predecessor branch or PR:
- Why this base branch is correct:
- Retarget/rebase plan after predecessor merge:
- Branch cleanup constraints:

## Source Phase Summary

- Goal:
- Required scope:
- Required checkpoints:
- Acceptance criteria:

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
- Existing tests or harness behavior:
- Import-boundary or dependency constraints:

## In-Scope Work

- TBD

## Out-of-Scope Work

- TBD

## Assumptions

- TBD

## Decision-Complete Contract

Define the public behavior, module boundaries, data shapes, error behavior, and
edge cases the executor must not redesign. If no public contract changes are in
scope, state that explicitly.

## Design Impact

- Maintainability:
- Extensibility:
- Domain neutrality:
- Source-tree boundaries:

## Future Compatibility

- TBD

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
|  |  |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
|  |  |  |

## Reviewability

- Expected PR size and shape:
- Files and areas to inspect:
- Scope-control checks:

## Implementation Steps

1. TBD

## Test Plan

### Package Suite

- Status: required/deferred
- Expected paths:
- Required assertions or deferral reason:

### Unit Suite

- Status: required/deferred
- Expected paths:
- Required assertions or deferral reason:

### Contract Suite

- Status: required/deferred
- Expected paths:
- Required assertions or deferral reason:

### Integration Suite

- Status: required/deferred
- Expected paths:
- Required assertions or deferral reason:

### E2E Suite

- Status: required/deferred
- Expected paths:
- Required assertions or deferral reason:

### Opt-In Suites

- Status: required/deferred
- Markers affected:
- Required assertions or deferral reason:

## Risks

- TBD

## Validation Commands

Targeted development commands:

```sh

```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
- Tests to run with each slice:
- Decisions the executor must not revisit:
- Conditions that require stopping for the manager:

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan:
- Final phase execution plan:
- Implementation summary:
- Implementation validation:
- Refinement summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers:
