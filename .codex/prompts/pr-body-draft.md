You are preparing the PR body for the completed phase.
This prompt is intended for the `loom_pr_preparer` custom agent.

This is the default fast-path PR preparation pass. Concisely summarize the
diff, scope, acceptance criteria, implementation notes, validation evidence,
risks, and reviewer-facing context in the durable PR body artifact. On the fast
path, also verify and open or prepare the PR in this pass. Only leave a later
refine prompt pending when the manager selected the expanded path.

Read:

- `AGENTS.md`
- The source implementation plan recorded in the phase execution plan
- The phase execution plan in `docs/phases/`
- The current diff
- Validation results
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.codex/templates/phase-pr-body.md`

Task:

1. Confirm you are inside the dedicated git worktree for this phase under
   `/home/samcantrill/work/loom-worktrees`.
2. Confirm the branch name follows `codex/<summary-of-feature>`.
3. Confirm the PR target branch matches the phase execution plan. Use explicit
   GitHub CLI flags and checks; never rely on GitHub's default base branch.
   Root PRs target `develop`; stacked PRs target their recorded predecessor
   branch until retargeted.
4. Confirm the implementation matches the assigned phase.
5. Confirm future phases were not implemented early.
6. Confirm relevant tests were added or updated.
7. Confirm validation commands were run or explain why not. Prefer
   `make validate-pr` for the final local gate.
8. Record PR facts, stack predecessor, target branch, merge eligibility, and
   workflow internals in the phase execution plan completion notes, not as
   public PR-body sections. The managing agent owns mirroring the phase status
   to `pr_open` in the control checkout.
9. Ensure the phase execution plan has completion notes and records the
   implementation refinement budget as `used` or explicitly not needed.
10. Run `make test-summary` when practical and use compact Markdown tables from
    its output as the suite-level evidence in the PR body. Do not paste
    box-drawing tables, output tails, or long command listings. If it cannot
    run, explain why and summarize available targeted suite results.
11. Create a PR body at `docs/phases/<summary-of-feature>-pr-body.md` using
    `.codex/templates/phase-pr-body.md`, which mirrors the simplified public
    `.github/PULL_REQUEST_TEMPLATE.md`.
12. Mark the PR body draft pass complete. Mark refine pass `not needed` on the
    fast path, or `pending` on the expanded path.
13. On the fast path, open the PR if GitHub tooling and authentication are
    available. Use explicit `--base <target-branch>`,
    `--head codex/<summary-of-feature>`, and
    `--title "<plan-focus> - Phase <N>: <what-changed> E.g. Configuration - Phase 1: Boundary and Artifact Contracts "` flags from the
    phase execution plan. Otherwise, leave the PR body ready to use and
    document the exact blocker in phase notes.
14. On the fast path, verify an opened PR with `gh pr view <PR>
    --json baseRefName,headRefName,state,url` and confirm `baseRefName`
    matches the recorded target branch. Record verification details in phase
    notes.
15. Ensure the PR body mentions `@samcantrill` near the top. Do not request
    `samcantrill` as a GitHub reviewer. If the body cannot be edited after PR
    creation, add an immediate PR comment mentioning `@samcantrill` and record
    the comment link in phase notes.

Rules:

- Do not merge.
- Do not perform implementation refinements; report any blocker to the manager.
- Do not create new test coverage at PR preparation time. If suite coverage is
  missing, report it as a blocker for the manager.
- Do not expand the PR body into a full implementation log; keep only the
  evidence needed for review.
- Include enough technical detail in Implementation Notes for reviewers to
  understand changed modules, data flow, preserved contracts, and the behavior
  covered by new or changed tests.
- Do not open the PR in this pass when the expanded path is active; leave it for
  `.codex/prompts/pr-body-refine.md`.
- Do not start another phase.
- Do not change workflow prompts, templates, `AGENTS.md`, or implementation-plan
  process text from a product phase worktree unless explicitly assigned.
- Do not route blockers back into another automated refinement loop. The
  manager decides whether the phase can proceed or must be escalated.
