# Codex Workflow Entrypoints

This directory is the user-facing "start here" layer for Loom's Codex
workflows.

Files here are intentionally short. They route a user request to the canonical
prompt sequence in `.codex/prompts/` and the durable artifacts in
`.codex/templates/`.

Do not put role authority, model, or sandbox policy here; that belongs in
`.codex/agents/`. Do not put full artifact schemas here; that belongs in
`.codex/templates/`. Do not duplicate long prompt bodies here; keep the
canonical behavior in `.codex/prompts/`.

## Entrypoints

| Entrypoint | Use when | Canonical prompts |
| --- | --- | --- |
| `roadmap-version-planning.md` | The user wants interactive roadmap planning, a functionality and behavior checkpoint, context compaction, then a design-decision queue review with user feedback before an implementation-plan draft after final confirmation | `roadmap-version-planning-notes-facilitate.md`, then `implementation-plan-draft.md` |
| `roadmap-version-implementation.md` | A roadmap-version implementation plan exists and Codex should execute phases through PRs and merges | `phase-loop-management.md` plus phase/PR prompts |

## Internal Capabilities

These are part of the automated workflows, not user-facing entrypoints:

- Implementation-plan quality gate: performed automatically by
  `roadmap-version-implementation.md` before phase selection or implementation
  using `implementation-plan-review.md` and, when needed,
  `implementation-plan-refinement.md`.
- Phase PR review: run by the managing agent or `loom_phase_reviewer` inside
  roadmap-version implementation.
- Architecture exploration: use `loom_architecture_explorer` only as an
  internal helper for bounded codebase questions.

## Typical Full Path

```text
roadmap-version-planning
implementation plan draft from confirmed planning notes
automatic implementation-plan quality gate
roadmap-version implementation
```

Routine phase execution usually follows the fast path:

```text
phase execution plan
implementation and phase-scoped tests
PR body and suite evidence
automated review or manager review
automatic CI-gated merge to develop
metadata update and cleanup
```
