You are drafting or updating a Loom feature specification.

This is the high-level "what" pass for a specification artifact. Create or
update the relevant `docs/features/` document from an approved feature brief,
existing repository guidance, and current source boundaries. A later refine
prompt will make the same artifact decision-complete for implementation
planning.

Read:

- `AGENTS.md`
- The approved feature brief, if present
- `docs/loom.md`
- `docs/structure.md`
- Related `docs/features/` documents
- Existing source and tests that constrain the feature boundary
- `.codex/templates/specification.md`

Task:

1. Identify the target specification document under `docs/features/`.
2. Draft the behavior, public API or document-shape expectations, invariants,
   configuration or runtime semantics, failure modes, examples, non-goals, and
   acceptance criteria needed for implementation planning.
3. Preserve domain neutrality and source-tree boundaries.
4. Use `.codex/templates/specification.md` for new specifications; preserve the
   existing document shape when updating an established spec.
5. Mark draft status in the specification or a short status note where the
   document already has a compatible metadata section.

Rules:

- Do not implement code.
- Do not produce phase execution details; implementation planning owns the how.
- Do not contradict the canonical roadmap or accepted implementation-plan
  tradeoffs without explicitly recording the conflict.
