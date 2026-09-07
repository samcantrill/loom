# Roadmap Stage 38 Implementation Plan

Status: implementation in progress
Roadmap stage: 38
Planning document: docs/roadmap/stage-38/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: 1 — stage-target-validation
Blockers: none for Phase 1; independent review passed. Later phases require
runtime acceptance prerequisites and the explicit timeout design gate.

## Summary

- Goal: preserve useful local validation/resource behavior while retaining
  corrected upstream execution and adding truthful container timeout cleanup.
- Approved requirements: FR-1 through FR-5 in planning.md, derived from the
  maintainer's selective-port execution request.
- Key constraints: FQ-1 through FQ-4 and DQ-1 through DQ-4. The timeout outcome
  is approved; its lifecycle mechanism must be reviewed before implementation.
- Minimum useful change: three ordered vertical increments over existing owners.
- Excluded complexity: new resource registries, durable cleanup ledgers,
  scheduler replacements, blanket historical-patch application.
- Validation source: planning.md, Upstream Correctness Audit and Examples And
  Validation; each phase card owns its exact acceptance and commands.
- Out of scope: rphys science, determinism, remote submission, domain-failure
  transport, and retirement of the original dirty checkout.

## Shared Constraints

- Loom remains generic and import-light. No dependency from Loom to rphys or
  from low-level container command code to daemon supervision internals.
- Keep run-root normalization/clearing and merge precedence, explicit NVIDIA
  passthrough, zero-request handling, GPU redaction, and frozen serialization.
- Resource validation, physical allocation, runtime enforcement, process
  containment, and terminal-result publication remain distinct responsibilities.
- Preserve existing durable schemas unless a reviewed current boundary proves
  a change necessary. No phase can infer physical cleanup from launcher exit.
- Preserve the original dirty control checkout and parked Stage 81 worktree.
  Use the worktree root recorded once in planning.md, isolated phase branches,
  exact current develop bases, and ordered non-stacked PRs targeting develop.
- Every implementation receives independent correctness review, fresh local
  validation, and accurate evidence. Hosted CI is intentionally disabled.
- Missing live-runtime checks are limitations, not passing enforcement proof.
  Host administration and implicit image pulls are not implementation steps.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | stage-target-validation | approved | [phase plan](phases/stage-target-validation.md) | agent/stage-38-p1-stage-target-validation | [#277](https://github.com/samcantrill/loom/pull/277) | CLI validation, focused tests and docs | Respect stage-owned configuration during target checking |
| 2 | direct-container-resources | pending | [phase plan](phases/direct-container-resources.md) | agent/stage-38-p2-direct-container-resources | pending | Direct command mapping, capabilities/preflight, A-9 SLURM correction, tests/docs | Map CPU/memory requests without upstream GPU regression |
| 3 | container-timeout-lifecycle | pending | [phase plan](phases/container-timeout-lifecycle.md) | agent/stage-38-p3-container-timeout-lifecycle | pending | Container lifecycle and required worker-owner propagation, tests/docs | Truthful deadlines and supported-process cleanup |

## Quality Gate

- Planning gate: passed for the validation phase; independently reviewed
  upstream defects A-9 and legacy A-10 have bounded later dispositions.
- Manager review: scope and first two increments match the approved draft;
  detailed timeout design is explicitly held for its expanded pre-implementation
  review. Earlier increments may proceed independently once their gates pass,
  as the maintainer's draft explicitly permits.
- Independent baseline review: passed; current resident daemon retention
  verified separately from the confirmed legacy adapter containment gap.
- First-phase startup: manager verified scope, source, tests, locked baseline,
  independent audit, phase packet, and approval; no blocker.
- Ready for implementation: yes for Phase 1 only. Phase 3's card is an explicit
  design-gated handoff, not permission to implement its unresolved mechanism.
- Accepted risks: host-dependent cgroup/runtime availability; original control
  checkout cannot be advanced by discarding or stashing its dirty contents.
- Revisit triggers: a materially broader lifecycle/public contract, unrelated
  upstream gate failure, source overlap, or unavailable required runtime proof.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | #277 approved; merge pending | CLI guard and A-11 test correction implemented; targeted 24 + 15 passed; both required gates passed at `74f117c` | independent review passed with no findings | owned worktree retained |
| 2 | pending | not started | host acceptance pending | not created |
| 3 | pending | not started | design gate pending | not created |

Final integrated review must verify all selected changes on their merged
develop revision, not just each PR in isolation. The overall stage is incomplete
until all approved outcomes are proven and merged; a held timeout phase cannot
be relabelled as completion of a smaller stage.
