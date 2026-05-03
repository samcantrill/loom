You are refining a Loom feature brief.

This is the lower-level refinement pass for the same durable feature brief
created by `.codex/prompts/feature-brief-draft.md`. Work from the brief plus the
compacted or current context, not hidden prior chat. The result should be clear
enough to hand off to specification drafting.

Read:

- `AGENTS.md`
- The draft feature brief in `docs/briefs/`
- Relevant existing files in `docs/features/`
- `docs/loom.md`
- `docs/structure.md`
- `.codex/templates/feature-brief.md`

Task:

1. Check that the problem, outcome, non-goals, done criteria, constraints, risks,
   and assumptions are internally consistent.
2. Refine the brief until it names the relevant specification target documents
   and any implementation-plan implications.
3. Mark the refine pass complete.
4. If the feature is not ready for specification, record the blocker in the
   brief and stop for the manager.

Rules:

- Do not implement code.
- Do not silently widen scope.
- Do not start an implementation plan from a brief with unresolved blockers.
