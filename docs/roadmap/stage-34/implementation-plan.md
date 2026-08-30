# Roadmap Stage 34 Implementation Plan

Status: implementation active
Roadmap stage: 34
Planning document: docs/roadmap/stage-34/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: Phase 2 `in_progress`
Blockers: none; Stage 32 replacement Phase 3 is remotely merged
Worktree root: `/home/can134/work/active/loom-worktrees`

## Summary

- Goal: inspect one known run through direct, owner-only Unix, or authenticated
  HTTP sources using one bounded, safe, versioned model.
- Approved behavior and requirement IDs: FR-1 through FR-12; functionality
  decisions FQ-1 through FQ-6.
- Key design constraints and decision IDs: DQ-1 through DQ-5; diagnostics owns
  the projection, existing owners retain truth, Stage 32 retains the exact
  run-to-item reference, and HTTP uses a dedicated read-only `query` role.
- Minimum useful change: `inspect_run` plus `loom inspect-run RUN_URI` returns
  lifecycle and operational axes, freshness, and artifact/log locations without
  bytes, global scans, mutation, or source fallback.
- Complexity deliberately excluded: persistence, another server/auth stack,
  run discovery, paging, streaming, payload relay, remote stores, path
  translation, hosted tenancy, and SSH implementation.
- Validation and phase-shaping source: `planning.md` Minimum Design, Examples And
  Validation, and Phase Shaping.
- Out of scope: modifying existing `status`, `logs`, `artifacts`, or `backend
  inspect` contracts; changing lifecycle/scheduler ownership; reopening the
  completed Stage 32 service-less contract.

## Shared Constraints

- Architecture and dependency direction: `loom.diagnostics` owns the public
  model/projection above queue and store reads; lower modules accept an injected
  plain-data query callable and never import diagnostics; CLI stays presentation
  only and public package imports remain lazy and cheap.
- Shared public and durable contracts: one strict schema-v1 result/error model,
  `loom.cli.inspect_run.v1`, canonical absolute run URI, named typed owner axes,
  typed locations, deterministic truncation counts, and the Stage 32 canonical
  queue-item reference. No Stage 34 database or owner schema is added.
- Shared reproducibility, compatibility, and import constraints: reads never
  mutate owners or load project code/plugins; direct/Unix/HTTP deserialize the
  same result; selected remote/local sources never fall back; existing command
  names and schemas remain unchanged.
- Shared invariant ownership: authority owns lifecycle; coordinator/queue own
  admission and operational axes; Slurm owns scheduler observations; artifact
  refs and materialization own locations; diagnostics only projects; transport
  authenticates/delivers; CLI renders.
- Decisions no phase may reopen: metadata/locations only, fixed allowlist,
  dedicated mTLS query role, explicit source selectors, 4-KiB URI, 256-record
  collection, and 1-MiB response limits, no list/search or content transfer.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | singular-run-inspection-core | merged | docs/roadmap/stage-34/phases/singular-run-inspection-core.md | agent/stage-34-p1-singular-run-inspection-core | [#263](https://github.com/samcantrill/loom/pull/263) | diagnostics model/projection, targeted owner reads, Unix operation, direct/Unix CLI/API and tests | Deliver safe singular-run inspection locally and through the owner socket. |
| 2 | authenticated-run-inspection | in_progress | docs/roadmap/stage-34/phases/authenticated-run-inspection.md | agent/stage-34-p2-authenticated-run-inspection | pending | query policy/HTTP operation and client config, remote CLI, security/parity tests and final docs | Deliver the same model through least-privilege mTLS inspection. |

## Quality Gate

- Planning gate: functionality and design agreements are locked; proportional
  design, invariant ownership, causal validation, and two-phase shape pass.
- Manager review: passed for artifact structure and requirement/decision
  coverage; the maintainer approved the complete packet on 2026-08-30.
- Optional independent review: not used; manager-local removal-first review is
  recorded in `planning.md`. Phase 2 remains expanded because it changes an
  authenticated trust boundary.
- Correction: not needed.
- Ready for implementation: yes; Stage 32 replacement Phase 3 merged in
  [#261](https://github.com/samcantrill/loom/pull/261) and preserves the exact
  run-to-item reference.
- Accepted risks: huge runs truncate without paging; location reachability is a
  label, not proof; real site TLS and Slurm policy remain operator-validated.
- Revisit triggers: a merged Stage 32 result lacks the approved durable queue
  reference, a source cannot avoid a global scan, or a consumer requires bytes,
  paging, tenant ACLs, subscriptions, or cross-coordinator search.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | [#263](https://github.com/samcantrill/loom/pull/263) squash-merged as `1f3f7fa` | Implementation and fresh repository validation passed; exact Stage 32 references, bounded projection, and direct/Unix parity are covered. | No known blocker; very large runs intentionally truncate without paging. | Worktree and local/remote phase branches removed. |
| 2 | pending | pending | Local TLS tests cannot certify site certificate issuance or path reachability. | pending |
