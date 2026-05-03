You are drafting a feature brief for Loom.

This is the high-level "what" pass for a feature artifact. Produce a durable
brief that captures intent, value, non-goals, done criteria, constraints, risks,
and the likely specification targets. A later refine prompt will compact or
reset context and make the same artifact ready for specification work.

Read:

- `AGENTS.md`
- `docs/loom.md`
- `docs/structure.md`
- Relevant existing files in `docs/features/`
- `.codex/templates/feature-brief.md`

Task:

1. Identify the smallest coherent feature or change request.
2. Create or update `docs/briefs/<summary>.md` from
   `.codex/templates/feature-brief.md`.
3. Fill the brief with the user-visible problem, why it matters, desired
   outcome, non-goals, done criteria, constraints, risks, assumptions, and
   likely specification targets.
4. Mark the draft pass complete and the refine pass pending.

Rules:

- Do not implement code.
- Do not create or edit feature specifications in this pass unless the manager
  explicitly assigns that artifact too.
- Do not invent requirements not supported by the user request or repository
  context.
- If high-impact intent is ambiguous after reading available context, record the
  ambiguity and stop for the manager.
