# Phase <P> Execution Plan: <Title>

## Metadata

- Status: pending
- Roadmap stage and phase:
- Manifest:
- Branch: agent/stage-<N>-p<P>-<phase-slug>
- Stage worktree: from manifest execution context
- Coordination branch: from manifest execution context
- Base revision:
- PR target: develop
- PR title: Stage <N> <manifest Stage descriptor> - Phase <P>: <phase heading title>
- Dependencies:
- Named refinement uncertainty: none / exact question and affected contract
- Blockers:

## Objective And Context

- Vertical outcome:
- Earlier dependency:
- Cohesion (why these edits ship together):
- Supported state after this merge if later phases never run:
- Contract supplied to later phases:
- Later work explicitly out of scope:

## Current Source And Harness

- Relevant files and symbols:
- Existing tests and seams:
- Import, dependency, or harness constraints:

## Scope

In scope:

-

Out of scope:

-

Assumptions:

-

## Fixed Contracts And Private Discretion

- Observable behavior:
- Public or durable shapes:
- Trust and failure boundaries:
- Cross-phase contracts:
- Reproducibility and compatibility:
- Private choices the executor may simplify:

## Proportionality

- Existing seam reused:
- Material additions and current justification:
- Optional hardening and future capability deferred:

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## Implementation Slices

Use reviewable slices appropriate to the outcome; no count target applies.

1.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package |  |  |  |
| Unit |  |  |  |
| Contract |  |  |  |
| Integration |  |  |  |
| E2E / opt-in |  |  |  |

Targeted commands:

    <commands>

Selection rationale and expansion triggers:

- Affected contracts and consumers:
- Why these checks cover the change:
- New evidence that would expand selection:
- Required dependency environments and unavailable physical qualification:

Final gate commands and rationale:

    <selected tests and applicable static checks, affected suites, or make validate-pr>

Use `$loom-targeted-validation`. Full validation covers broad/unbounded impact
and explicitly approved gates. Summary targets run tests again; include
make test-summary only when required or its report is needed. Keep existing
approved obligations until deliberately revised at their owner.

## Risks, Review, And Stops

- Main risks:
- Review focus:
- Stop if:
- Accepted debt and revisit trigger:

## Executor Handoff

- Read section range:
- Safe implementation slices:
- Decisions not to revisit:
- Conditions requiring manager action:

## Workflow State

- Manager preparation:
- Named uncertainty refinement: not needed / result
- Implementation:
- Refiner: not needed / result
- Pre-submit gate:
- Independent review: required; reviewed head and result
- Blocker corrections: 0/3
- PR and merge:
- Improvement log entries: none / relevant IDs

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths |  |
| Tests added or updated |  |
| Validated revision/tree state and evidence |  |
| Validation-relevant changes after evidence | none / details |
| PR, review, and merge |  |
| Residual risk and cleanup |  |
