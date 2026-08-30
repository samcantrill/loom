# Roadmap Stage 35 Implementation Plan

Status: approved
Roadmap stage: 35
Planning document: docs/roadmap/stage-35/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: Phase 2 review and merge
Blockers: none

## Summary

- Goal: let an ordinary composed runtime config select its CLI run collection
  and let one bare exclusive GPU request drive truthful direct/Slurm-afterok
  container admission.
- Approved behavior and requirement IDs: FR-1 through FR-10 in `planning.md`.
- Key design constraints and decision IDs: FQ-1 through FQ-5 and DQ-1 through
  DQ-6; preserve authority/plugin trust ordering, make resources automatically
  enable GPU access, and validate visibility only where it exists.
- Minimum useful change: optional run-store root plus local and Slurm-afterok
  GPU projection/visibility over existing factories, resources, and executors.
- Complexity deliberately excluded: store backends/migrations, distributed
  launch, GPU discovery/share modes, CPU/memory flags, timeout enforcement, and
  required live infrastructure.
- Validation and phase-shaping source: `planning.md` Examples And Validation and
  Phase Shaping.
- Out of scope: all downstream rphys science and its private process protocol;
  rphys pin/test changes follow only after both Loom phases merge.

## Shared Constraints

- Architecture and dependency direction: runtime and executor modules remain
  domain-neutral; Loom never imports the downstream reference project.
- Shared public and durable contracts: optional `RunOptions.run_store`, the
  executor GPU helper module, existing resource/runtime metadata, and existing
  CLI/run-store authority contracts.
- Shared reproducibility, compatibility, and import constraints: omitted config
  keeps current behavior; paths and physical device tokens remain operational
  evidence; base imports remain cheap.
- Shared invariant ownership: CLI bootstrap owns store location before plugin
  activation; `ResourceRequest` owns GPU request validity; direct executor or
  Slurm allocation script owns visibility admission at its external boundary.
- Decisions no phase may reopen: no new store backend, physical GPU selection,
  distributed launch, share-mode interpretation, CPU/memory projection, timeout
  change, or mandatory live external test.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | configurable-run-store-root | merged | docs/roadmap/stage-35/phases/configurable-run-store-root.md | agent/stage-35-p1-configurable-run-store-root | #258 | runtime options/profiles, CLI bootstrap/store factories, docs/tests | Use one configured run collection across fresh, resume, plan, Slurm, and offline CLI paths. |
| 2 | gpu-container-admission | ready to merge | docs/roadmap/stage-35/phases/gpu-container-admission.md | agent/stage-35-p2-gpu-container-admission | pending | executor GPU helper, direct Apptainer/Singularity, Slurm planning/rendering, preflight/docs/tests | Project one bare exclusive GPU request into truthful container access and visibility. |

## Quality Gate

- Planning gate: passed after the bounded expanded design review.
- Manager review: behavior, minimum design, proportionality, phase split, and
  all three concrete review corrections confirmed.
- Independent reviews: completed once per expanded phase for the
  resume-bootstrap and scheduler/container trust boundaries; all concrete
  blockers are corrected and manager-verified.
- Correction: single-job GPU aggregation deferred, rich GPU attributes rejected,
  and authored `nv` compatibility locked.
- Ready for merge: yes; both phases passed their implementation gates and
  independent review blockers are resolved.
- Accepted risks: canonical absolute path requirement; operator/scheduler owns
  physical allocation; fake-backed default validation.
- Revisit triggers: store backend selection, executor GPU share support,
  distributed launch, or reliable live hardware availability.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | #258 squash-merged as `a332bb3` | corrected pre-submit gate passed at `842a8d0` after independent review | no phase blocker | remote/local phase branches and phase worktree removed |
| 2 | pending | corrected head `04bb2f0` passed focused tests and the complete pre-submit gate after independent review | no phase blocker; live CUDA/container/Slurm remains opt-in | pending verified merge |
