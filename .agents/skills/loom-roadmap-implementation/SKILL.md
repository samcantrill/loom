---
name: loom-roadmap-implementation
description: Execute or continue an approved Loom roadmap stage through its stage worktree, validation, phase PRs, independent review, merge, synchronization, and cleanup workflow. Do not use for ordinary coding, plan-only review, or an unapproved stage.
---

# Loom Roadmap Implementation

Route explicit implementation intent to the approved manifest and canonical
workflow. These repository development skills do not operate Loom experiments.

1. Identify the requested stage and confirm its packet records approval. Skill
   selection alone does not authorize implementation or external mutations;
   use the user's request and existing session authorization.
2. Read `AGENTS.md`, `.codex/workflows/roadmap-stage-implementation.md`,
   `docs/roadmap/stage-<N>/implementation-plan.md`, and the next unfinished phase
   card plus its exact referenced contracts.
3. Load `.codex/prompts/phase-loop-management.md` and other assets as routed.
   The manifest owns execution paths, coordination branch, readiness, and stage
   descriptor. Do not require the user to repeat those facts in their prompt.
4. Follow the workflow through the requested scope. A whole-stage request
   continues across its phases and closeout; it does not start another stage.

Bootstrap the persistent stage worktree before startup review or writes. The
manager prompt owns the shared Git gate and publication/synchronization order.
Reuse current readiness and validation evidence, including grandfathered plan
layouts, as the workflow permits. Keep explicitly approved checks binding.

Use `$loom-targeted-validation` for selection and evidence. Return to
`$loom-roadmap-planning` if accepted behavior, durable shape, trust boundaries,
or cross-phase contracts must change. Use `$loom-process-improvement` only for
a qualifying reusable weakness; logging does not widen phase scope.
