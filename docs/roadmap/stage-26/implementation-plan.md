# Roadmap Stage 26 Implementation Plan: Operational Correctness And Lifecycle Guidance

Status: complete
Roadmap stage: `v26`
Planning document: `docs/roadmap/stage-26/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: complete
Blockers: none

## Summary

- Goal: make current stage authoring, artifacts, logs, and lifecycle facts easy
  to use correctly through one evidence-backed downstream guide.
- Approved behavior and requirement IDs: planning `FR-1` through `FR-5` cover
  context/artifact usage, executor-specific logging truth, demonstrated
  compatibility corrections, the lifecycle catalog and post-commit ordering,
  and unchanged validation/adjacent-stage ownership.
- Key design constraints and decision IDs: planning `FQ-1` through `FQ-5` and
  `DQ-1` through `DQ-4` add no public or durable shape and leave exact event
  subscriptions and plugin activation to Stage 28.
- Minimum useful change: one copyable guide plus the smallest correction that
  makes a fresh `run.preparation_failed` observable only after `FAILED` is
  committed.
- Complexity deliberately excluded: notification message/severity/notifier
  contracts, registration adapters, service clients, event subscriptions,
  plugin activation, delivery machinery, logging facades, scheduling,
  sampling, resume changes, and new validation gates.
- Validation and phase-shaping source: planning `Examples And Validation` and
  `Phase Shaping`; only preparation failure and committed observation require
  combined coverage.
- Out of scope: every planning deferral plus Stage 25, 27, 28, and 29 policy or
  authority work.

## Shared Constraints

- Architecture and dependency direction:
  - current context, artifact, executor, store, lifecycle, event, and observer
    owners remain authoritative;
  - project examples depend on public Loom APIs; core Loom never imports a
    project, provider, or service SDK; and
  - docs route to detailed feature owners instead of inventing a facade.
- Shared public and durable contracts:
  - no new public type, registry, message, record, schema, or store capability;
  - stage outputs remain declared `ArtifactRef` values; workspace files remain
    private until registered and returned; and
  - fresh preparation failure changes ordering only: commit `FAILED`, then emit
    `run.preparation_failed`; an already-terminal opened run is unchanged.
- Shared reproducibility, compatibility, and import constraints:
  - examples are dependency-free and hermetic;
  - backend-specific log behavior remains explicit; and
  - existing package imports, defaults, and validation gates remain unchanged.
- Shared invariant ownership:
  - `StageContext` owns stage-facing paths and artifact helpers;
  - each executor/store/scheduler layer owns its streams and log paths; and
  - runner/store owns lifecycle state before event code publishes the fact.
- Decisions no phase may reopen: no notification abstraction, subscription,
  service adapter, logger facade, implicit output, mutable store access,
  scheduler, sampler, resume semantics, or validation-policy work.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `stage-author-correctness-and-logging` | merged | `docs/roadmap/stage-26/phases/stage-author-correctness-and-logging.md` | `agent/stage-26-p1-stage-author-correctness-and-logging` | [#220](https://github.com/samcantrill/loom/pull/220) | Downstream guide, artifact/log/event truth, preparation-failure ordering, examples/tests | Give stage authors one truthful operational path and ensure observers see committed lifecycle state. |

The former generic-lifecycle-notifications phase is no longer accepted. It was
removed because the proposed message/severity/helper surface had no concrete
core consumer and duplicated the generic subscription/registration path owned
by Stage 28.

## Quality Gate

- Planning gate: the removal-first cross-stage correction is confirmed; no
  behavior or public contract remains unresolved.
- Manager review: planning, this manifest, the sole phase plan, roadmap entry,
  and Stage 28 ownership are consistent.
- Optional independent review: not rerun; the correction removes the prior
  external-side-effect contract rather than adding a novel decision.
- Correction: the Stage 26 notification phase and all dependencies on its
  proposed public types were removed; Stage 28 now owns generic observer
  mechanics and direct provider examples.
- Implementation complete: yes. Phase 1 passed targeted and full local gates,
  manager review, required CI, remote squash merge, and cleanup.
- Accepted risks: executor logging remains intentionally heterogeneous and the
  source audit may narrow prose rather than change behavior.
- Revisit triggers: a demonstrated public artifact/log gap, a new lifecycle
  ordering mismatch, or at least two real provider integrations needing one
  shared notification projection.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | [#220](https://github.com/samcantrill/loom/pull/220) squash-merged to `develop` as `e5bfa9b` | Targeted tests, `make validate-pr`, and `make test-summary` passed (2,307 passed); manager review and required CI passed at final PR revision `3db0c58` | Executor logging remains intentionally heterogeneous. | Phase worktree and local/remote phase branches removed; dirty control checkout preserved. |
