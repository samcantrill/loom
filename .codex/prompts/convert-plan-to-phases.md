You are converting a rough implementation plan into a structured phased plan for autonomous Codex implementation.

Read existing repository files before editing:

- `AGENTS.md`, if present
- `docs/implementation-plan.md`, if present
- README or project documentation
- Existing tests and package/build configuration
- Any user-provided plan or design document

Task:

1. Preserve existing files and project guidance.
2. Do not overwrite `docs/implementation-plan.md` if it already exists.
3. Add or align a `## Phased implementation` section.
4. Break the plan into small phases, each suitable for one PR.
5. Assign each phase a branch using `codex/<summary-of-feature>`.
6. For each phase, include:
   - Status
   - Branch
   - PR
   - Goal
   - Scope
   - Out of scope
   - Acceptance criteria
   - Test expectations
   - Notes
   - Completion summary
7. Keep phases ordered so implementation can proceed from top to bottom.
8. Separate refactors, behavior changes, migrations, and cleanup into distinct phases where practical.

Rules:

- Do not ask the user for feedback.
- If the plan is ambiguous, make the smallest reasonable assumption and document it.
- Do not invent requirements not supported by the plan or existing repo.
- Align with existing repository patterns.
- Keep the plan lightweight and executable.
- Use only these phase statuses: `pending`, `in_progress`, `pr_open`, `approved`, `merged`, `blocked`.

