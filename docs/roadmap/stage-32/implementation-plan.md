# Roadmap Stage 32 Implementation Plan

Status: approved
Roadmap stage: 32
Planning document: docs/roadmap/stage-32/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: Phase 1 `pending`
Blockers: Stage 29 Phase 12 must merge before Phase 1 begins
Worktree root: record once at implementation start; default to a
`loom-worktrees` sibling of the discovered control checkout

## Summary

- Goal: let project code durably submit thousands of ordinary runs and drive
  them through service-less Slurm with safe replay after client, driver, or
  scheduler-call interruption.
- Approved behavior and requirement IDs: FR-1 through FR-11 in `planning.md`;
  nullable scientific deduplication was selected on 2026-08-28.
- Key design constraints and decision IDs: FQ-1 through FQ-5 and DQ-1 through
  DQ-7; reuse existing queue-item identity, the historical whole-run queue and
  run-local Slurm manifests, keep owner axes distinct, and force only with a new
  stable queue item ID.
- Minimum useful change: streaming many-run admission, indexed exact/optional
  scientific deduplication, bounded foreground driving, prepared-run single-job
  and `afterok` dispatch, exact ambiguous-submit discovery, and truthful joined
  terminal behavior.
- Complexity deliberately excluded: sweep/batch lifecycle, dynamic ready-stage
  coordination, remote stores/log relay/query gateway, arrays, allocation-fed
  agents, coordinator HA, and durable reporting delivery.
- Validation and phase-shaping source: `planning.md` Examples And Validation and
  Phase Shaping.
- Out of scope: changing Stage 29 managed scheduling, Stage 31 event sinks, or
  the independently approved Stage 33 coordinator reporter.

## Shared Constraints

- Architecture and dependency direction: queue application/repository code may
  consume generic fingerprints and public Slurm execution operations; pipeline,
  planning, store, and scheduler modules never import queue or CLI.
- Shared public and durable contracts: existing `queue_item_id` is exact retry
  identity; `scientific_fingerprint` is canonical or null; force bypasses
  semantic deduplication only; run-local submitted-operation/manifest records
  remain the scheduler-job inventory owner.
- Shared reproducibility, compatibility, and import constraints: queue records
  and the SQLite schema hard-cut together with no migration; generated examples
  are deterministic; default tests use fake commands/filesystems and no network.
- Shared invariant ownership: queue repository owns admission; per-run authority
  owns scientific lifecycle; Slurm owns scheduler facts; project stores own
  bytes; query/reporting code only joins or observes.
- Decisions no phase may reopen: no sweep collection, full-batch transaction,
  blind `sbatch` retry, scheduler-completed-as-run-success, remote byte relay,
  compute/agent webhook, or intermittent Stage 29 bootstrap.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | durable-many-run-admission | pending | docs/roadmap/stage-32/phases/durable-many-run-admission.md | agent/stage-32-p1-durable-many-run-admission | pending | queue request/receipt, service, SQLite schema/index, bounded reads and identity tests | Admit and replay large ordinary-run request streams without duplicate queue work. |
| 2 | service-less-slurm-driving | pending | docs/roadmap/stage-32/phases/service-less-slurm-driving.md | agent/stage-32-p2-service-less-slurm-driving | pending | delegated controller/CLI, prepared-run Slurm adapter, marker recovery, lifecycle join, HPC docs/tests | Submit and reconcile many single-job or `afterok` runs without a long-running coordinator. |

## Quality Gate

- Planning gate: behavior, minimum design, complexity delta, invariant owners,
  causal validation, and two-phase shape are complete.
- Manager review: passed; every requirement maps to one phase and the previous
  duplicate deployment/query/data-transfer scope has been removed.
- Optional independent review: not used; manager-local removal-first review is
  recorded in `planning.md`. Reconsider only if implementation needs a new
  scheduler or authority format beyond the fixed contracts.
- Correction: not needed.
- Ready for implementation: planning is approved; Phase 1 remains gated on the
  Stage 29 Phase 12 merge.
- Accepted risks: project fingerprint correctness is trusted, old queue
  databases are rejected, shared storage is required, and incomplete work with
  expired accounting remains unknown.
- Revisit triggers: a phase requires queue migration, a second job inventory,
  dynamic controller behavior, non-shared payload movement, remote query, or
  guaranteed reporting.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | Project semantic normalization can be incorrect. | pending |
| 2 | pending | pending | Fake Slurm cannot certify site accounting/visibility policy. | pending |
