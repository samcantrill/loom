You are planning the assigned phase before implementation.
This prompt is intended for the `loom_phase_implementer` custom agent.

Read:

- `AGENTS.md`
- `docs/implementation-plan.md`
- The assigned phase

Create an expanded phase plan in `docs/phases/` using this filename pattern:

```text
docs/phases/<summary-of-feature>.md
```

The phase plan must include:

1. Branch name using `codex/<summary-of-feature>`.
2. Worktree path.
3. Source phase from `docs/implementation-plan.md`.
4. Objective.
5. Full-plan context.
6. In-scope work.
7. Out-of-scope work.
8. Assumptions.
9. Files and areas to inspect.
10. Implementation steps.
11. Test plan.
12. Risks.
13. Validation commands.
14. Completion notes placeholder.

Planning rules:

- Be specific enough that implementation can proceed without more user input.
- Do not expand the phase beyond its stated scope.
- Identify future-phase work and explicitly keep it out of scope.
- Prefer a plan that produces a small, reviewable PR.
- Use repository validation commands from `AGENTS.md`.
- Commit the phase plan from inside the worktree with `git commit -m "plan: add phase plan"`.
