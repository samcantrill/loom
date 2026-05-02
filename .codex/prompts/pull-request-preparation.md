You are preparing the PR for the completed phase.
This prompt is intended for the `loom_phase_implementer` custom agent.

Read:

- `AGENTS.md`
- `docs/implementation-plan.md`
- The expanded phase plan in `docs/phases/`
- The current diff
- Validation results
- `.github/PULL_REQUEST_TEMPLATE.md`

Task:

1. Confirm you are inside the dedicated git worktree for this phase.
2. Confirm the branch name follows `codex/<summary-of-feature>`.
3. Confirm the PR targets `develop`.
4. Confirm the implementation matches the assigned phase.
5. Confirm future phases were not implemented early.
6. Confirm relevant tests were added or updated.
7. Confirm validation commands were run or explain why not.
8. Update `docs/implementation-plan.md` phase status to `pr_open` without overwriting unrelated content.
9. Ensure the expanded phase plan has completion notes.
10. Create a PR body using `.github/PULL_REQUEST_TEMPLATE.md`.
11. Open the PR if GitHub tooling and authentication are available. Otherwise, leave the PR body ready to use and document why the PR was not opened.

Do not merge.
