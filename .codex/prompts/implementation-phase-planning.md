You are planning the assigned phase before implementation.
This prompt is intended for the `loom_phase_implementer` custom agent.

Read:

- `AGENTS.md`
- `docs/implementation-plans/implementation-plan-v0.md`
- The assigned phase

Create an expanded phase plan in `docs/phases/` using this filename pattern:

```text
docs/phases/<summary-of-feature>.md
```

The phase plan must include:

1. Branch name using `codex/<summary-of-feature>`.
2. Worktree path.
3. Source phase from `docs/implementation-plans/implementation-plan-v0.md`.
4. Objective.
5. Full-plan context.
6. In-scope work.
7. Out-of-scope work.
8. Assumptions.
9. Design impact.
10. Future compatibility.
11. Alternatives rejected.
12. Debt introduced.
13. Reviewability.
14. Files and areas to inspect.
15. Implementation steps.
16. Test plan.
17. Risks.
18. Validation commands.
19. Completion notes placeholder.

Planning rules:

- Be specific enough that implementation can proceed without more user input.
- Do not expand the phase beyond its stated scope.
- Identify future-phase work and explicitly keep it out of scope.
- Prefer a plan that produces a small, reviewable PR.
- Explain how this phase preserves maintainability and extensibility.
- Document conflicting design choices and why this phase chooses one path.
- Avoid introducing technical debt. If debt is unavoidable, name it, justify it, and add a revisit trigger.
- Do not start implementation if the full plan has unresolved blocking findings from `loom_plan_reviewer`.
- Use repository validation commands from `AGENTS.md`.
- Commit the phase plan from inside the worktree with `git commit -m "plan: add phase plan"`.
