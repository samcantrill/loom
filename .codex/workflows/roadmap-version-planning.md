# Roadmap-Version Planning

Use this entrypoint when the user wants an interactive design discussion for one
roadmap version before drafting an implementation plan. When the planning
discussion is complete and the user explicitly confirms they are happy with the
roadmap-version notes, continue into implementation-plan drafting from the
confirmed notes.

Canonical prompts:

- `.codex/prompts/roadmap-version-planning-notes-facilitate.md`
- `.codex/prompts/implementation-plan-draft.md`, after final planning
  confirmation

Primary template:

- `.codex/templates/roadmap-version-planning-notes.md`
- `.codex/templates/implementation-plan.md`, after final planning confirmation

Typical artifacts:

- `docs/implementation-plans/roadmap-v<N>-planning-notes.md`
- `docs/implementation-plans/implementation-plan-v<N>.md`

User request shape:

```text
Use .codex/workflows/roadmap-version-planning.md for v<N>.
Facilitate the discussion and update the roadmap planning notes as decisions
are confirmed.
```

Expected flow:

1. Roadmap framing.
2. Intent discovery.
3. Feature brainstorming.
4. Practical design refinement.
5. Phase shaping.
6. Final planning confirmation.
7. Implementation-plan draft from the confirmed planning notes.

Ask small batches of high-impact questions and update the planning notes after
each confirmed stage. Do not start phase implementation from this entrypoint;
the drafted implementation plan still needs the normal plan quality gate before
phase work begins.
