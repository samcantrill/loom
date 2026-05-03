You are refining the PR body for the completed phase.
This prompt is intended for the `loom_pr_preparer` custom agent.

This is the lower-level PR body pass. Work from the durable PR body artifact,
the phase execution plan, the actual diff, and validation evidence. The result
must be accurate enough to open or hand off the PR without relying on hidden
draft-pass context.

Read:

- `AGENTS.md`
- The source implementation plan recorded in the phase execution plan
- The phase execution plan in `docs/phases/`
- The draft PR body at `docs/phases/<summary-of-feature>-pr-body.md`
- The current diff
- Validation results
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.codex/templates/phase-pr-body.md`

Task:

1. Confirm you are inside the dedicated git worktree for this phase under
   `/home/samcantrill/work/loom-worktrees`.
2. Confirm the branch name follows `codex/<summary-of-feature>`.
3. Verify the PR body matches the phase execution plan, implementation diff,
   acceptance criteria, suite evidence, scope boundaries, assumptions, and risks.
4. Confirm future phases were not implemented early and no unrelated refactors
   are described as phase work.
5. Mark the PR body refine pass complete.
6. Open the PR if GitHub tooling and authentication are available. Use explicit
   `--base <target-branch>` and `--head codex/<summary-of-feature>` flags,
   where `<target-branch>` is the branch recorded in the phase execution plan.
   Otherwise, leave the PR body ready to use and document the exact blocker.
7. Verify an opened PR with `gh pr view <PR>
   --json baseRefName,headRefName,state,url` and confirm `baseRefName` matches
   the recorded target branch. Document whether the PR is already
   merge-eligible (`develop` target) or stacked for review only (predecessor
   branch target).

Rules:

- Do not merge.
- Do not perform implementation refinements.
- Do not create new test coverage.
- Do not retarget or rebase stack branches; the managing agent owns stack
  maintenance after predecessor PRs land.
- If the PR body cannot be made accurate from the artifact, diff, and validation
  evidence, report the blocker to the manager and stop.
