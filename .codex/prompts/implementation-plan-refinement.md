You are refining a Loom implementation plan before phase work begins.

This is the only automated refinement pass for the plan quality gate. Resolve
the reviewer findings that can be resolved safely, document any accepted risk
with a revisit trigger, and do not chase open-ended perfection. This pass
consumes the plan quality gate's refinement budget.

Read:

- `AGENTS.md`
- `docs/implementation-plans/implementation-plan-v0.md`
- Relevant design docs referenced by the plan
- The findings from `loom_plan_reviewer`

Task:

1. Update `docs/implementation-plans/implementation-plan-v0.md` to resolve the plan review findings.
2. Preserve existing project-specific guidance and plan intent.
3. Keep the plan Markdown-based and lightweight.
4. Add or update these plan-level sections when relevant:
   - Design principles
   - Key design choices
   - Conflicts and tradeoffs
   - Maintainability assessment
   - Extensibility assessment
   - Technical debt ledger
   - Plan quality gate
5. For each phase, add or tighten:
   - Objective acceptance criteria
   - Explicit out-of-scope work
   - Test expectations by package, unit, contract, integration, e2e, and opt-in
     suites
   - Design impact
   - Future compatibility
   - Alternatives rejected
   - Debt introduced
   - Reviewability
6. Split phases that are too broad for one reviewable PR.
7. Separate behavior-preserving refactors from behavior changes where practical.
8. Document accepted tradeoffs instead of hiding them.

Rules:

- Do not implement product code.
- Do not add heavy process, schemas, dashboards, or exhaustive matrices.
- Do not add a new testing agent stage unless the user explicitly asks; keep
  test creation inside planning, execution, refinement, and PR preparation.
- Do not invent requirements unsupported by the design docs or current plan.
- Prefer precise, reviewable text over generic assurances.
- If a finding cannot be fully resolved, document the remaining risk and the
  trigger for revisiting it.
- Stop after one coherent refinement pass. The managing agent will run one
  confirmation review or escalate remaining blockers to the user.
- Do not request another automated refinement pass, reviewer, or fixer for this
  plan quality gate.
