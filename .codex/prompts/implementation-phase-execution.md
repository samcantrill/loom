You are implementing the assigned phase.
This prompt is intended for the `loom_phase_implementer` custom agent.

Read:

- `AGENTS.md`
- `docs/implementation-plan.md`
- The expanded phase plan in `docs/phases/`

Task:

1. Confirm you are inside the dedicated git worktree for this phase.
2. Inspect the files identified in the phase plan.
3. Implement the phase step by step.
4. Add or update tests as described in the phase plan.
5. Keep changes limited to the phase scope.
6. Make frequent commits after coherent units of work.
7. Run relevant validation commands.
8. Record results in the phase plan completion notes.

Commit guidance:

- Commit the implementation after meaningful checkpoints.
- Commit tests separately when practical.
- Use clear commit messages, such as:
  - `feat: implement phase behavior`
  - `test: add phase coverage`
  - `fix: refine after validation`

Rules:

- Do not ask the user for feedback.
- Do not implement future phases.
- Do not rewrite unrelated code.
- Do not hide failing tests.
- Do not remove tests just to make the suite pass.
- If a validation command is unavailable, document that in the phase plan and PR body.
