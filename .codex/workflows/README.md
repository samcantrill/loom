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
| `roadmap-stage-planning.md` | The user wants interactive roadmap-stage planning with functionality-agreement review, behavior confirmation, design-agreement review, design-safety review, validation strategy, phase shaping, and implementation readiness before an implementation-plan draft | `roadmap-stage-planning-facilitate.md`, `roadmap-stage-functionality-agreement.md`, `roadmap-stage-design-agreement.md`, `roadmap-stage-design-safety-review.md`, then `implementation-plan-draft.md` |
| `roadmap-stage-implementation.md` | A roadmap-stage implementation plan exists and Codex should execute phases through PRs and merges | `phase-loop-management.md` plus phase/PR prompts |

## Internal Capabilities

These are part of the automated workflows, not user-facing entrypoints:

- Implementation-plan quality gate: performed automatically by
  `roadmap-stage-implementation.md` before phase selection or implementation
  using `implementation-plan-review.md` and, when needed,
  `implementation-plan-refinement.md`.
- Phase PR review: run by the managing agent or `loom_phase_reviewer` inside
  roadmap-stage implementation.
- Functionality-agreement review: run inside roadmap-stage planning to
  resolve requirement-level scope, defaults, and deferrals on the planning
  notes artifact before behavior confirmation proceeds.
- Design-agreement review: run inside roadmap-stage planning to resolve the
  dependency-ordered design queue on the planning artifact before
  design-safety review.
- Design-safety review: run by `loom_design_safety_reviewer` during
  roadmap-stage planning before implementation-plan drafting.
- Architecture exploration: use `loom_architecture_explorer` only as an
  internal helper for bounded codebase questions.

## Typical Full Path

```text
roadmap-stage-planning
functionality-agreement review and behavior confirmation
design-agreement review, design-safety review, and implementation readiness
implementation plan draft from confirmed planning artifact
automatic implementation-plan quality gate
roadmap-stage implementation
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
