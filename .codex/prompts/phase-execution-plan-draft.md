You are drafting the phase execution plan for the assigned phase.
This prompt is intended for the `loom_phase_planner` custom agent.

This is the high-level "what" pass for the phase artifact. Create the branch,
create the worktree, inspect enough source and documentation context to make the
draft accurate, and write the durable phase execution plan artifact. A later
refine prompt will compact or reset context and fill in lower-level
implementation details in the same artifact.

Read:

- `AGENTS.md`
- `docs/implementation-plans/implementation-plan-v0.md`
- The assigned phase
- `.codex/templates/phase-execution-plan.md`

Create the phase branch/worktree, then create a draft phase execution plan from
`.codex/templates/phase-execution-plan.md` in `docs/phases/` using this filename
pattern:

```text
docs/phases/<summary-of-feature>.md
```

Worktree setup:

```bash
gh auth status
gh auth setup-git
git fetch origin
BRANCH="codex/<summary-of-feature>"
BASE_BRANCH="develop"
WORKTREE_ROOT="/home/samcantrill/work/loom-worktrees"
WORKTREE="$WORKTREE_ROOT/<summary-of-feature>"
mkdir -p "$WORKTREE_ROOT"
git worktree add -b "$BRANCH" "$WORKTREE" "$BASE_BRANCH"
cd "$WORKTREE"
```

If `gh` is authenticated but `git fetch` fails through SSH, use the HTTPS
GitHub remote form `https://github.com/<owner>/<repo>.git` with the `gh`
credential helper before retrying fetch. If remote synchronization is still
unavailable, continue from the local `develop` branch and document the
limitation in the phase execution plan.

The draft phase execution plan must preserve the template's durable handoff
sections and include:

1. Branch name using `codex/<summary-of-feature>`.
2. Worktree path.
3. Source phase from `docs/implementation-plans/implementation-plan-v0.md`.
4. Objective.
5. Full-plan context.
6. In-scope work.
7. Out-of-scope work.
8. Assumptions.
9. Design impact.
10. Future compatibility.
11. Alternatives rejected.
12. Debt introduced.
13. Reviewability.
14. Files and areas to inspect.
15. Implementation steps.
16. Test plan, grouped by package, unit, contract, integration, e2e, and opt-in
    suites. For each suite, state required coverage, expected test paths,
    assertions, or the explicit reason it is deferred for this phase.
17. Risks.
18. Validation commands, including targeted suite commands for development and
    `make validate-pr` plus `make test-summary` before PR preparation.
19. Draft/refine status:
   - draft pass: completed by `loom_phase_planner`
   - refine pass: pending
20. Refinement and review budget status:
   - phase implementation refinement: unused
   - PR review: unused
21. Handoff notes for the phase execution plan refinement prompt.
22. Completion notes placeholder.

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
- Do not leave test-suite choices for the executor to invent. If a suite is not
  relevant, document that deferral in the phase execution plan.
- Commit the phase execution plan from inside the worktree with `git commit -m "plan: add phase execution plan"`.
- Stop after committing the draft phase execution plan. Do not implement code,
  run full validation, open a PR, or refine the plan in this pass.
