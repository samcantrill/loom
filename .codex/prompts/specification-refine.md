You are refining a Loom feature specification.

This is the lower-level refinement pass for the same `docs/features/` artifact
created or updated by `.codex/prompts/specification-draft.md`. Work from the
specification plus compacted or current context, not hidden prior chat. The
result should be ready for implementation-plan drafting.

Read:

- `AGENTS.md`
- The draft or updated specification in `docs/features/`
- The approved feature brief, if present
- `docs/loom.md`
- `docs/structure.md`
- Related tests and source boundaries
- `.codex/templates/specification.md`

Task:

1. Check the specification for missing behavior, edge cases, failure modes,
   examples, acceptance criteria, and source-tree boundary conflicts.
2. Refine it until implementation planning can split the work without making
   product or public API decisions.
3. Record accepted deferrals or debt with revisit triggers when relevant.
4. If blocking ambiguity remains, record it and stop for the manager.

Rules:

- Do not implement code.
- Do not create phase execution plans from an unresolved specification.
- Do not over-specify future behavior beyond the approved feature scope.
