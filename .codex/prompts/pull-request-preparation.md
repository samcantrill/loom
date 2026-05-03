You are preparing the PR for the completed phase.
This prompt is intended for the `loom_pr_preparer` custom agent.

Read:

- `AGENTS.md`
- `docs/implementation-plans/implementation-plan-v0.md`
- The expanded phase plan in `docs/phases/`
- The current diff
- Validation results
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.codex/templates/phase-pr-body.md`

Task:

1. Confirm you are inside the dedicated git worktree for this phase under
   `/home/samcantrill/work/loom-worktrees`.
2. Confirm the branch name follows `codex/<summary-of-feature>`.
3. Confirm the PR targets `develop`.
4. Confirm the implementation matches the assigned phase.
5. Confirm future phases were not implemented early.
6. Confirm relevant tests were added or updated.
7. Confirm validation commands were run or explain why not. Prefer
   `make validate-pr` for the final local gate.
8. Update `docs/implementation-plans/implementation-plan-v0.md` phase status to `pr_open` without overwriting unrelated content.
9. Ensure the expanded phase plan has completion notes and records the
   implementation refinement budget as `used` or explicitly not needed.
10. Run `make test-summary` when practical and use its Markdown output as the
    suite-level evidence in the PR body. If it cannot run, explain why and
    summarize available targeted suite results.
11. Create a PR body at `docs/phases/<summary-of-feature>-pr-body.md` using
    `.codex/templates/phase-pr-body.md`, which mirrors
    `.github/PULL_REQUEST_TEMPLATE.md` and adds budget/creation-status fields.
12. Open the PR if GitHub tooling and authentication are available. Otherwise, leave the PR body ready to use and document why the PR was not opened.

Rules:

- Do not merge.
- Do not perform implementation refinements; report any blocker to the manager.
- Do not create new test coverage at PR preparation time. If suite coverage is
  missing, report it as a blocker for the manager.
- Do not start another phase.
- Do not route blockers back into another automated refinement loop. The
  manager decides whether the phase can proceed or must be escalated.
