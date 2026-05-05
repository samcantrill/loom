You are creating the phase execution plan for the assigned phase.
This prompt is intended for the `loom_phase_planner` custom agent.

This is the default fast-path planning pass for a phase artifact. Create the
branch, create the worktree, inspect enough source and documentation context to
make the plan accurate, and write the durable phase execution plan artifact.
Keep it concise and scope-first. Only mark a later refine prompt as needed when
the manager selected the expanded path.

Read:

- `AGENTS.md`
- The selected implementation plan assigned by the manager
- The assigned phase
- `.codex/templates/phase-execution-plan.md`

Create the phase branch/worktree from the manager-provided stack base, then
create a phase execution plan from `.codex/templates/phase-execution-plan.md`
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
2. Feature focus and intended PR title using
   `<plan-focus> - Phase <N>: <what-changed> E.g. Configuration - Phase 1: Boundary and Artifact Contracts `.
3. Worktree path.
4. Source phase from the selected implementation plan.
5. Stack predecessor, base branch, target branch, and merge eligibility.
6. Objective.
7. Full-plan context.
8. In-scope work.
9. Out-of-scope work.
10. Assumptions.
11. Design impact.
12. Future compatibility.
13. Alternatives rejected.
14. Debt introduced.
15. Reviewability.
16. Files and areas to inspect.
17. Implementation steps as small reviewable slices, not a full code recipe.
18. Test plan, grouped by package, unit, contract, integration, e2e, and opt-in
    suites. For each suite, state required coverage, expected test paths,
    assertions, or the explicit reason it is deferred for this phase.
19. Risks.
20. Validation commands, including targeted suite commands for development and
    `make validate-pr` plus `make test-summary` before PR preparation.
21. Workflow path and draft/refine status:
   - workflow path: fast path by default, or expanded path when assigned
   - draft pass: completed by `loom_phase_planner`
   - refine pass: not needed for fast path, or pending for expanded path
22. Refinement and review budget status:
   - phase implementation refinement: unused
   - PR review: unused
23. Handoff notes for implementation, plus any expanded-path refinement notes
    if the manager selected the expanded path.
24. Completion notes placeholder.

Planning rules:

- Be specific enough that the executor can implement without another planning
  pass on the fast path.
- Spend planning detail on scope boundaries, acceptance criteria, test
  obligations, risky decisions, and stop conditions.
- Avoid exhaustive implementation recipes, broad file inventories, and
  speculative abstractions.
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
- Stop after committing the phase execution plan. Do not implement code, run
  full validation, open a PR, or refine the plan in this pass.
