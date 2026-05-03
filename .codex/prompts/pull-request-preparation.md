You are preparing the PR for the completed phase.
This prompt is intended for the `loom_pr_preparer` custom agent.

Read:

- `AGENTS.md`
- `docs/implementation-plans/implementation-plan-v0.md`
- The expanded phase plan in `docs/phases/`
- The current diff
- Validation results
- `.github/PULL_REQUEST_TEMPLATE.md`

Task:

1. Confirm you are inside the dedicated git worktree for this phase under
   `/home/samcantrill/work/loom-worktrees`.
2. Confirm the branch name follows `codex/<summary-of-feature>`.
3. Confirm the PR targets `develop`. Use explicit GitHub CLI flags and checks;
   never rely on GitHub's default base branch.
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
11. Create a PR body using `.github/PULL_REQUEST_TEMPLATE.md`.
12. Open the PR if GitHub tooling and authentication are available. Prefer
    `gh auth status`, `gh auth setup-git`, and HTTPS `origin` when git SSH auth
    is unavailable. Push the branch, then create the PR with:

```sh
gh pr create --base develop --head codex/<summary-of-feature> --body-file <body>
```

13. After opening or finding an existing PR, run:

```sh
gh pr view <PR> --json baseRefName,headRefName,state,url
```

    Record the result in the expanded phase plan and PR body. If `baseRefName`
    is not exactly `develop`, stop and report the blocker to the manager. Do
    not leave a wrong-base PR as ready for review.
14. If PR creation cannot run, leave the PR body ready to use and document the
    exact reason the PR was not opened.

Rules:

- Do not merge.
- Do not perform implementation refinements; report any blocker to the manager.
- Do not create new test coverage at PR preparation time. If suite coverage is
  missing, report it as a blocker for the manager.
- Do not start another phase.
- Do not route blockers back into another automated refinement loop. The
  manager decides whether the phase can proceed or must be escalated.
