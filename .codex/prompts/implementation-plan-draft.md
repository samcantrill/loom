You are drafting a structured implementation plan for autonomous Codex implementation.

This is the high-level "what and sequence" pass for an implementation-plan
artifact. A later refinement prompt makes the same artifact decision-complete
for phase execution planning.

Read existing repository files before editing:

- `AGENTS.md`, if present
- The target implementation plan, if updating one
- Adjacent or previous implementation plans, if relevant
- Completed roadmap-stage planning, if present
- README or project documentation
- Existing tests and package/build configuration
- Any user-provided plan or design document
- `.codex/templates/roadmap-stage-implementation-plan.md`

Task:

1. Preserve existing files and project guidance.
2. Use `.codex/templates/roadmap-stage-implementation-plan.md` for new implementation plans.
3. Do not overwrite an existing implementation plan unless the manager assigns
   that target plan explicitly.
4. Add or align these plan-level sections when relevant:
   - Goal
   - Context
   - Planning readiness
   - Desired outcome
   - Non-goals
   - Constraints
   - Design principles
   - Key design choices
   - Conflicts and tradeoffs
   - Maintainability assessment
   - Extensibility assessment
   - Technical debt ledger
   - Plan quality gate
5. When completed roadmap-stage planning artifacts are present, treat them as the
   primary source and carry forward:
   - approved functionality and behavior baseline
   - functional requirements
   - proposed implementation shape
   - design decisions and rejected alternatives
   - design-safety review result
   - examples and validation strategy
   - phase shaping
   - implementation readiness blockers, accepted risks, and revisit triggers
6. Before drafting phases from the planning artifact, check that implementation
   readiness is not blocked, the design-safety review has passed or recorded
   accepted risks, there are no unresolved `blocked` or `needs discussion`
   design decisions, and validation and phase shaping are specific enough for
   implementation agents.
7. If readiness fails, update only the planning-readiness or blocker sections
   of the implementation plan and do not invent phases to fill the gap.
8. Add or align a `## Phased implementation` section when readiness is clear.
9. Break the plan into small phases, each suitable for one PR.
10. Assign each phase a branch using `codex/<summary-of-feature>`.
11. For each phase, include:
   - Status
   - Branch
   - PR
   - Goal
   - Scope
   - Out of scope
   - Acceptance criteria
   - Test expectations
   - Design impact
   - Future compatibility
   - Alternatives rejected
   - Debt introduced
   - Reviewability
   - Notes
   - Completion summary
12. Keep phases ordered so implementation can proceed from top to bottom.
13. Separate refactors, behavior changes, migrations, and cleanup into distinct phases where practical.
14. Mark the plan quality gate as requiring review by `loom_plan_reviewer` before the first implementation phase begins.

Rules:

- Do not ask the user for feedback.
- If the plan is ambiguous, make the smallest reasonable assumption and document it.
- Do not invent requirements not supported by the plan or existing repo.
- Do not use an implementation plan to resolve roadmap-planning blockers that
  belong in the planning artifact; record the blocker and stop phase drafting.
- Align with existing repository patterns.
- Surface conflicting design choices instead of silently choosing around them.
- Record accepted technical debt with a concrete revisit trigger.
- Prefer phases that are objectively reviewable in one PR.
- Do not let a plan proceed to implementation until maintainability, extensibility, future compatibility, and reviewability have been assessed.
- Keep the plan lightweight and executable.
- Use only these phase statuses: `pending`, `in_progress`, `pr_open`, `approved`, `merged`, `blocked`.
