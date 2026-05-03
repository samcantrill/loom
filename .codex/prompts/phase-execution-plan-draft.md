You are drafting the phase execution plan for the assigned phase.
This prompt is intended for the `loom_phase_planner` custom agent.

This is the high-level "what" pass for the phase artifact. Create the branch,
create the worktree, inspect enough source and documentation context to make the
draft accurate, and write the durable phase execution plan artifact. A later
refine prompt will compact or reset context and fill in lower-level
implementation details in the same artifact.

Read:

- `AGENTS.md`
- The selected implementation plan assigned by the manager
- The assigned phase
- `.codex/templates/phase-execution-plan.md`

Create the phase branch/worktree from the manager-provided stack base, then
create a draft phase execution plan from `.codex/templates/phase-execution-plan.md`
in `docs/phases/` using this filename pattern:

```text
docs/phases/<summary-of-feature>.md
```

Worktree setup:

```bash
gh auth status
gh auth setup-git
git fetch origin
BRANCH="codex/<summary-of-feature>"
BASE_BRANCH="<develop-or-stack-predecessor-from-assignment>"
TARGET_BRANCH="<develop-or-stack-predecessor-from-assignment>"
WORKTREE_ROOT="/home/samcantrill/work/loom-worktrees"
WORKTREE="$WORKTREE_ROOT/<summary-of-feature>"
mkdir -p "$WORKTREE_ROOT"
git worktree add -b "$BRANCH" "$WORKTREE" "$BASE_BRANCH"
cd "$WORKTREE"
```

If `gh` is authenticated but `git fetch` fails through SSH, use the HTTPS
GitHub remote form `https://github.com/<owner>/<repo>.git` with the `gh`
credential helper before retrying fetch. In sandboxed Codex sessions,
`gh auth status` can falsely report an invalid token when network access is
restricted; rerun `gh auth status` with approved network access before treating
credentials as unavailable. If authentication is still invalid with network
access, ask the user to allow `gh auth logout -h github.com -u <user>`,
`gh auth login -h github.com -p https -w`, and `gh auth setup-git`; the user
may need to enter the printed device code at
`https://github.com/login/device`. If remote synchronization is still
unavailable after that setup, continue from the local recorded base branch and
document the limitation in the phase execution plan. Do not silently fall back
to `develop` when the assignment names a stack predecessor branch.

The draft phase execution plan must preserve the template's durable handoff
sections and include:

1. Branch name using `codex/<summary-of-feature>`.
2. Worktree path.
3. Source phase from the selected implementation plan.
4. Stack predecessor, base branch, target branch, and merge eligibility.
5. Objective.
6. Full-plan context.
7. In-scope work.
8. Out-of-scope work.
9. Assumptions.
10. Design impact.
11. Future compatibility.
12. Alternatives rejected.
13. Debt introduced.
14. Reviewability.
15. Files and areas to inspect.
16. Implementation steps.
17. Test plan, grouped by package, unit, contract, integration, e2e, and opt-in
    suites. For each suite, state required coverage, expected test paths,
    assertions, or the explicit reason it is deferred for this phase.
18. Risks.
19. Validation commands, including targeted suite commands for development and
    `make validate-pr` plus `make test-summary` before PR preparation.
20. Draft/refine status:
   - draft pass: completed by `loom_phase_planner`
   - refine pass: pending
21. Refinement and review budget status:
   - phase implementation refinement: unused
   - PR review: unused
22. Handoff notes for the phase execution plan refinement prompt.
23. Completion notes placeholder.

Planning rules:

- Be specific enough that the refine pass can become decision-complete without
  more user input.
- Do not expand the phase beyond its stated scope.
- Identify future-phase work and explicitly keep it out of scope.
- Prefer a plan that produces a small, reviewable PR.
- Explain how this phase preserves maintainability and extensibility.
- Document conflicting design choices and why this phase chooses one path.
- Avoid introducing technical debt. If debt is unavoidable, name it, justify it, and add a revisit trigger.
- Do not start implementation if the full plan has unresolved blocking findings from `loom_plan_reviewer`.
- Use repository validation commands from `AGENTS.md`.
- Preserve the recorded stack base and target branch. A stacked phase PR may
  target the predecessor branch for review, but it is merge-eligible only after
  retargeting to `develop`.
- Do not leave test-suite choices for the executor to invent. If a suite is not
  relevant, document that deferral in the phase execution plan.
- Commit the phase execution plan from inside the worktree with `git commit -m "plan: add phase execution plan"`.
- Stop after committing the draft phase execution plan. Do not implement code,
  run full validation, open a PR, or refine the plan in this pass.
