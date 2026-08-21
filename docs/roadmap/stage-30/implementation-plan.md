# Roadmap Stage 30 Implementation Plan

Status: in_progress
Roadmap stage: 30
Planning document: docs/roadmap/stage-30/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: 1
Blockers: none

## Summary

- Goal: make already-implemented Loom capabilities understandable through
  complete, copyable, validated user journeys and concise current-state docs.
- Approved behavior and requirement IDs: FR-1 through FR-8 in `planning.md`.
- Key design constraints and decision IDs: FQ-1 through FQ-3 and DQ-1 through
  DQ-3; examples/docs/tests only, fake/local by default, no runtime contract
  additions.
- Minimum useful change: seven focused examples, one strengthened resume
  example, catalog routing, focused integration/e2e evidence, and bounded
  current-support summaries.
- Complexity deliberately excluded: tracking services, notification adapters,
  event filters, providers/SDKs, real HPC requirements, cleanup policy changes,
  new schemas, and docs generation machinery.
- Validation and phase-shaping source: `planning.md` Examples And Validation and
  Phase Shaping.
- Out of scope: all `src/loom` behavior changes.

## Shared Constraints

- Architecture and dependency direction: example/project code may import Loom;
  Loom must not import examples. No new runtime dependency.
- Shared public and durable contracts: consume existing CLI JSON envelopes,
  Python APIs, run/bundle/sweep/artifact records, and example manifest fields
  without changing them.
- Shared reproducibility, compatibility, and import constraints: examples are
  domain-neutral, deterministic, network-free, output-root aware, rerunnable,
  and use public behavior for the demonstrated journey.
- Shared invariant ownership: runtime/store code remains authoritative for
  lifecycle and durable facts; examples assert those facts but do not redefine
  them.
- Decisions no phase may reopen: no runtime machinery; setup-only fakes must be
  named honestly; live external systems remain optional/manual.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | operations-portability-and-cleanup | pr_open | docs/roadmap/stage-30/phases/operations-portability-and-cleanup.md | agent/stage-30-p1-operations-portability-and-cleanup | [#224](https://github.com/samcantrill/loom/pull/224) | operations examples, catalog, focused tests | Demonstrate multi-run comparison/transfer and safe candidate-only cleanup. |
| 2 | experiments-observers-and-apptainer | pending | docs/roadmap/stage-30/phases/experiments-observers-and-apptainer.md | agent/stage-30-p2-experiments-observers-and-apptainer | pending | experiments/extensions/Apptainer examples, routing, tests | Demonstrate sweeps, observe-only sinks, and hermetic HPC container execution. |
| 3 | resume-storage-and-guide-clarity | pending | docs/roadmap/stage-30/phases/resume-storage-and-guide-clarity.md | agent/stage-30-p3-resume-storage-and-guide-clarity | pending | local resume example, storage example, related feature docs, final validation | Explain reuse/invalidation, explicit materialization, and current/deferred support. |

## Quality Gate

- Planning gate: passed on 2026-08-21; requirements, design, validation, and
  three-phase shape are locked.
- Manager review: passed; phase plans are vertical, runtime-neutral, and cover
  every requested journey.
- Optional independent review: not needed on the lean docs/examples path.
- Correction: not needed.
- Ready for implementation: yes.
- Accepted risks: fake adapters prove Loom integration rather than live external
  infrastructure; cleanup setup uses an isolated fixture because candidate
  invention is not a supported public authoring surface.
- Revisit triggers: a phase requires runtime behavior, a public/durable shape
  change, or a live/provider dependency to satisfy an acceptance criterion.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | [#224 open](https://github.com/samcantrill/loom/pull/224); merge pending | Implementation and manager validation passed; CI pending | Cleanup candidate setup is an explicitly documented private fixture | Branch and worktree cleanup pending remote merge |
| 2 | pending | pending | pending | pending |
| 3 | pending | pending | pending | pending |
