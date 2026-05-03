You are converting a rough implementation plan into a structured phased plan for autonomous Codex implementation.

Read existing repository files before editing:

- `AGENTS.md`, if present
- `docs/implementation-plans/implementation-plan-v0.md`, if present
- README or project documentation
- Existing tests and package/build configuration
- Any user-provided plan or design document

Task:

1. Preserve existing files and project guidance.
2. Do not overwrite `docs/implementation-plans/implementation-plan-v0.md` if it already exists.
3. Add or align these plan-level sections when relevant:
   - Goal
   - Context
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
4. Add or align a `## Phased implementation` section.
5. Break the plan into small phases, each suitable for one PR.
6. Assign each phase a branch using `codex/<summary-of-feature>`.
7. For each phase, include:
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
8. Keep phases ordered so implementation can proceed from top to bottom.
9. Separate refactors, behavior changes, migrations, and cleanup into distinct phases where practical.
10. Mark the plan quality gate as requiring review by `loom_plan_reviewer` before the first implementation phase begins.

Rules:

- Do not ask the user for feedback.
- If the plan is ambiguous, make the smallest reasonable assumption and document it.
- Do not invent requirements not supported by the plan or existing repo.
- Align with existing repository patterns.
- Surface conflicting design choices instead of silently choosing around them.
- Record accepted technical debt with a concrete revisit trigger.
- Prefer phases that are objectively reviewable in one PR.
- Do not let a plan proceed to implementation until maintainability, extensibility, future compatibility, and reviewability have been assessed.
- Keep the plan lightweight and executable.
- Use only these phase statuses: `pending`, `in_progress`, `pr_open`, `approved`, `merged`, `blocked`.
