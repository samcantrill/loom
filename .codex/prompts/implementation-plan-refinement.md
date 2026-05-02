You are refining a Loom implementation plan before phase work begins.

Read:

- `AGENTS.md`
- `docs/implementation-plan.md`
- Relevant design docs referenced by the plan
- The findings from `loom_plan_reviewer`

Task:

1. Update `docs/implementation-plan.md` to resolve the plan review findings.
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
   - Test expectations
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
- Do not invent requirements unsupported by the design docs or current plan.
- Prefer precise, reviewable text over generic assurances.
- If a finding cannot be fully resolved, document the remaining risk and the
  trigger for revisiting it.

