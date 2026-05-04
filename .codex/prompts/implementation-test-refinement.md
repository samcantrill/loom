You are refining the current phase implementation based on validation results.
This prompt is intended for the `loom_phase_refiner` custom agent.

This is the only automated refinement pass for the phase, and it is conditional.
Use it when targeted validation fails, suite coverage is missing, the executor
reports a blocker, or the expanded path is active. First make a concise
refinement plan from the diff and validation output, then execute only that
phase-scoped plan. This pass consumes the phase implementation refinement
budget.

Read:

- `AGENTS.md`
- The phase execution plan in `docs/phases/`
- The current diff
- Test and validation output
- `.codex/templates/phase-refinement-report.md`

Task:

1. Confirm you are inside the dedicated git worktree for this phase under
   `/home/samcantrill/work/loom-worktrees`.
2. Identify failing tests, missing phase-scoped suite coverage, lint errors,
   type errors, build errors, or obvious runtime problems.
3. Determine whether each failure is caused by the current phase.
4. Fix failures caused by the current phase.
5. Add regression coverage when useful and phase-scoped.
6. Re-run the relevant targeted suite commands and broader validation commands
   when practical.
7. Update the phase execution plan completion notes using the sections from
   `.codex/templates/phase-refinement-report.md` and mark implementation
   refinement budget as `used`. If the manager asks for a separate artifact,
   write it to `docs/phases/<summary-of-feature>-refinement.md`.
8. Commit refinements with `git commit -m "fix: refine after validation"`.

Rules:

- Fix blocking issues only.
- Keep fixes to the smallest phase-scoped change that resolves the blocker.
- Do not expand the phase scope.
- Do not implement later phases.
- Do not perform opportunistic cleanup or broad refactors.
- Do not paper over failures.
- Do not weaken tests unless the test is clearly obsolete because of the intended phase behavior; if so, explain why.
- Do not add broad future-phase package, integration, e2e, or opt-in tests that
  were not required by the finalized phase execution plan.
- Do not run a second refinement loop. If blockers remain after this pass,
  document them for the managing agent and stop.
- Do not ask for a replacement fixer or another automated pass under a different
  name.
- Do not prepare or open a PR.
