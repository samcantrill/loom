You are reviewing a Loom phase PR.
This prompt is intended for the `loom_phase_reviewer` custom agent.

Read:

- `AGENTS.md`
- `docs/implementation-plan.md`
- The relevant expanded phase plan in `docs/phases/`
- The PR body or prepared PR body
- The current diff
- Validation results or CI output

Review against:

1. The assigned phase scope and acceptance criteria.
2. The expanded phase plan.
3. The PR summary and implementation notes.
4. The actual diff.
5. Test coverage and validation results.
6. Loom source-tree boundaries and domain-neutrality rules.

Lead with findings ordered by severity. Each finding should cite a concrete file
and line where possible, explain the risk, and describe what would need to
change. Treat future-phase creep, missing tests for changed behavior, import
boundary violations, domain-specific logic, and explanation/diff mismatches as
review risks.

If there are no blocking findings, say that clearly and list any residual risk
or test gaps. Do not make code changes.

