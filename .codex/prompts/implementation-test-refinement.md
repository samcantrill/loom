You are refining the current phase implementation based on validation results.
This prompt is intended for the `loom_phase_implementer` custom agent.

Read:

- `AGENTS.md`
- The expanded phase plan in `docs/phases/`
- The current diff
- Test and validation output

Task:

1. Confirm you are inside the dedicated git worktree for this phase under
   `/home/samcantrill/work/loom-worktrees`.
2. Identify failing tests, lint errors, type errors, build errors, or obvious runtime problems.
3. Determine whether each failure is caused by the current phase.
4. Fix failures caused by the current phase.
5. Add regression coverage when useful.
6. Re-run the relevant validation commands.
7. Update the phase plan completion notes.
8. Commit refinements with `git commit -m "fix: refine after validation"`.

Rules:

- Fix blocking issues only.
- Do not expand the phase scope.
- Do not implement later phases.
- Do not paper over failures.
- Do not weaken tests unless the test is clearly obsolete because of the intended phase behavior; if so, explain why.
