# Roadmap Stage 32 Implementation Plan

Status: complete
Roadmap stage: 32
Planning document: docs/roadmap/stage-32/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: Phase 3 `merged`; Phase 2 is superseded
Blockers: none
Worktree root: `/home/can134/work/active/loom-worktrees`

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
  remain the scheduler-job inventory owner and retain the canonical queue item
  ID for Stage 34's exact run-to-item lookup.
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
| 1 | durable-many-run-admission | merged | docs/roadmap/stage-32/phases/durable-many-run-admission.md | agent/stage-32-p1-durable-many-run-admission | [#257](https://github.com/samcantrill/loom/pull/257) merged | queue request/receipt, service, SQLite schema/index, bounded reads and identity tests | Admit and replay large ordinary-run request streams without duplicate queue work. |
| 2 | service-less-slurm-driving | blocked | docs/roadmap/stage-32/phases/service-less-slurm-driving.md | agent/stage-32-p2-service-less-slurm-driving | not opened | rejected delegated controller/CLI candidate retained for review evidence | Record the exhausted candidate and its FR-9/FR-10 review blockers. |
| 3 | service-less-slurm-completion | merged | docs/roadmap/stage-32/phases/service-less-slurm-completion.md | agent/stage-32-p3-service-less-slurm-completion | [#261](https://github.com/samcantrill/loom/pull/261) merged | complete delegated controller/CLI and prepared-run Slurm outcome, per-job snapshot fallback, shared-workspace proof, HPC docs/tests | Deliver the full service-less Slurm outcome in one replacement PR from current `develop`. |

## Quality Gate

- Planning gate: behavior, minimum design, complexity delta, invariant owners,
  causal validation, and the replacement phase shape are complete.
- Manager review: passed; every requirement maps to one phase and the previous
  duplicate deployment/query/data-transfer scope has been removed.
- Optional independent review: the Phase 2 implementation review identified
  concrete FR-9 and FR-10 gaps; both are fixed acceptance conditions for the
  approved replacement and Phase 3 retains expanded-path review.
- Correction: the maintainer approved one replacement phase on 2026-08-30;
  Phase 2 remains blocked rather than receiving a fourth correction pass.
- Implementation gate: complete; Phase 1 and replacement Phase 3 are remotely
  merged, while Phase 2 remains the superseded blocked record.
- Accepted risks: project fingerprint correctness is trusted, old queue
  databases are rejected, shared storage is required, and incomplete work with
  expired accounting remains unknown.
- Revisit triggers: a phase requires queue migration, a second job inventory,
  dynamic controller behavior, non-shared payload movement, remote query, or
  guaranteed reporting.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | [#257](https://github.com/samcantrill/loom/pull/257) squash-merged as `b93d4ac` | Full local gate passed: 2,770 tests overall plus package build, Ruff, and Pyright. | Project semantic normalization can be incorrect. | Dedicated worktree and local/remote phase branches removed. |
| 2 | No PR; blocked after independent review. | Candidate `c9cbd2c` passed Ruff, Pyright, package build, 2,676 default tests, and 157 config-extra tests (3 expected skips); `make test-summary` reported 2,833 passing tests. | FR-9 retained scheduler facts were not persisted/merged per missing job; FR-10 lacked positive compute-visible-path proof before `sbatch`. | Superseded worktree and local branch removed after replacement merge; no remote branch existed. |
| 3 | [#261](https://github.com/samcantrill/loom/pull/261) squash-merged as `0bee233` | Full local gate and expanded review passed: 2,844 tests with 3 expected skips plus package build, Ruff, and Pyright. | Fake Slurm cannot certify site accounting visibility or shared-mount policy beyond explicit project evidence. | Dedicated worktree and local/remote phase branches removed. |

Final requirement audit: FR-1 through FR-5 are present in merged Phase 1
[#257](https://github.com/samcantrill/loom/pull/257); FR-6 through FR-11 are
present in replacement Phase 3 [#261](https://github.com/samcantrill/loom/pull/261).
The merged source, causal tests, documentation, and cleanup records leave no
pending Stage 32 implementation phase.
