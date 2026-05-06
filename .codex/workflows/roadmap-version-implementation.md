# Roadmap-Version Implementation

Use this entrypoint when a roadmap-version implementation plan exists and Codex
should implement its phases through branch/worktree creation, validation, PRs,
CI-gated merges, metadata updates, and cleanup.

The managing agent must perform the implementation-plan quality gate as the
first workflow preflight before selecting or assigning any phase. The quality
gate is automatic workflow behavior, not a separate user-facing entrypoint.

"Perform" means:

1. Read the selected implementation plan's Plan quality gate section.
2. If the gate is missing, incomplete, stale, ambiguous, or not passed for the
   current plan content, run the review/refinement/confirmation sequence using
   the implementation-plan prompts listed below.
3. If the gate already records a current passed result, verify that evidence and
   continue.
4. Stop before phase planning if blocking plan findings remain.

Canonical manager prompt:

- `.codex/prompts/phase-loop-management.md`

Primary downstream prompts:

- `.codex/prompts/implementation-plan-review.md`
- `.codex/prompts/implementation-plan-refinement.md`
- `.codex/prompts/phase-execution-plan-draft.md`
- `.codex/prompts/phase-execution-plan-refine.md`
- `.codex/prompts/implementation-phase-execution.md`
- `.codex/prompts/implementation-test-refinement.md`
- `.codex/prompts/pr-body-draft.md`
- `.codex/prompts/pr-body-refine.md`
- `.codex/prompts/pull-request-review.md`

Primary templates:

- `.codex/templates/phase-assignment.md`
- `.codex/templates/phase-execution-plan.md`
- `.codex/templates/phase-implementation-handoff.md`
- `.codex/templates/phase-refinement-report.md`
- `.codex/templates/phase-pr-body.md`
- `.codex/templates/phase-pr-review-report.md`
- `.codex/templates/phase-merge-record.md`

User request shape:

```text
Use .codex/workflows/roadmap-version-implementation.md.
Begin or continue implementation of docs/implementation-plans/<plan>.md.
Use Codex-managed automatic merges. Do not gate implementation on human PR
review.
```

Manager responsibilities:

- Read `AGENTS.md`, the selected implementation plan, existing phase artifacts,
  and `.codex/templates/README.md`.
- Perform the plan quality gate before phase selection or implementation.
- Select one phase at a time.
- Use `/home/samcantrill/work/loom-worktrees` for phase worktrees.
- Use fast path unless expanded-path triggers apply.
- Run or record `make validate-pr` and `make test-summary`.
- Open phase PRs with explicit base/head/title.
- Poll CI and merge eligible phase PRs into `develop` without waiting for human
  approval; use admin merge authority for review-only branch protection when
  available after automated gates pass.
- Record merge metadata in the implementation plan and clean up phase branches
  and worktrees when safe.
