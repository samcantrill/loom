# Roadmap Stage 38 Implementation Plan

Status: Phase 2 PR #278 open; implementation, full gates, and independent review passed
Roadmap stage: 38
Planning document: docs/roadmap/stage-38/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: 2 — direct-container-resources
Blockers: none for Phase 2; fresh full gates and independent closure passed at `04443ed`.
The maintainer authorized this specific correction and a fresh bounded independent
verification, without resetting other budgets. Targeted checks pass 80 tests and
the latest SIF smoke passes one test. Both full gates passed with 2,994 summary
passes and five optional skips; only roadmap metadata changed afterward.
Positive runtime-limit proof remains deferred to a compatible host.
Phase 3 retains its timeout design gate.

## Summary

- Goal: preserve useful local validation/resource behavior while retaining
  corrected upstream execution and adding truthful container timeout cleanup.
- Approved requirements: FR-1 through FR-5 in planning.md, derived from the
  maintainer's selective-port execution request, with the 2026-09-07 FQ-5/DQ-5
  scheduling-only CPU/RAM amendment and separately approved FQ-6/DQ-6 bounded
  coordinator-responsiveness amendment. No host settings may be changed.
- Key constraints: FQ-1 through FQ-6 and DQ-1 through DQ-6. The timeout outcome
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
- Preserve CPU/RAM requests and managed reservations when direct enforcement
  is explicitly disabled. GPU, SLURM, ownership, and release remain separate.
- Make admission status waits passive without changing lock ownership, periodic
  reconciliation, mutation wakeups, deadlines, replacement fences, or release.
  One additional bounded amendment is expressly authorized; the three historical
  corrections stay consumed and no general correction budget is reset.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | stage-target-validation | merged | [phase plan](phases/stage-target-validation.md) | agent/stage-38-p1-stage-target-validation | [#277](https://github.com/samcantrill/loom/pull/277) | CLI validation, focused tests and docs | Respect stage-owned configuration during target checking |
| 2 | direct-container-resources | pr_open | [phase plan](phases/direct-container-resources.md) | agent/stage-38-p2-direct-container-resources | [#278](https://github.com/samcantrill/loom/pull/278) | Direct resource policy/mapping, capabilities/preflight, A-9 SLURM correction, bounded retry/passive-wait corrections, tests/docs | Retain scheduling intent with explicit CPU/RAM enforcement policy and responsive managed control |
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
- Implementation readiness: Phase 1 is merged; Phase 2 resource mapping and
  its first two corrections are independently reviewed. The third retry
  candidate does not resolve the observed coordinator lock delays. The approved
  scheduling-only policy design passed independent review. The separately approved
  passive-wait correction has measured cause-backed evidence; independent
  combined startup review passed with no findings. The amendments are implemented
  at `8702e06`; fresh full gates and the scheduling-only live smoke passed.
  Independent review accepted the queue correction but found policy-diagnostic
  gaps. Bounded correction `6b831e7` closes namespace selection and explicit/global
  fallback warnings. The separately approved `04443ed` correction adds visible
  mapping warnings for mixed explicit/implicit stages without inventing runtime
  limits. Fresh full gates and independent closure passed; ready for PR/merge checks.
  Phase 3's card is a design-gated handoff,
  not permission to implement its unresolved mechanism.
- Policy amendment: use `cpu_memory_enforcement` in existing Apptainer/Singularity
  adapter options, with `runtime` default and explicit `scheduling_only`. The
  selected-policy live smoke is required; positive hard-limit proof on a suitable
  host is separately deferred, never relabelled as passing. Existing 3/3 fault
  corrections remain consumed. Coordinator changes have separate bounded authority
  below; neither approval bypasses independent review or fresh full gates.
- Accepted risks: host-dependent cgroup/runtime availability; original control
  checkout cannot be advanced by discarding or stashing its dirty contents.
- Revisit triggers: a materially broader lifecycle/public contract, unrelated
  upstream gate failure, source overlap, or unavailable required runtime proof.
- Previously approved A-13 pre-grant retry correction: reproduce a transient pre-grant control-response
  failure, reuse the existing bounded assignment retry owner, and independently
  review cancellation/replay and exhausted-retry retention. No global retry,
  automatic restart adoption, deadline extension, or capacity-release redesign.
  The original uninstrumented full-suite trigger remains unproven; a matching
  deterministic failure mode is documented in planning.md.
- Independent amendment review: no policy-design blocker; manager corrected
  FQ/DQ traceability and the earlier A-13 authority label. Combined startup has
  since passed; independent implementation review and fresh full gates also passed.
  Existing profile composition preserves the
  proposed option payload and resource demand in a read-only diagnostic; this
  is not a policy implementation receipt.
- Coordinator amendment authority: maintainer approves one bounded,
  cause-backed responsiveness correction and resumption of the scheduling-only
  work after design review. The previous missing-authority stop is superseded;
  3/3 historical corrections stay consumed, with no new general correction budget.
  Diagnosis shows a 15.575-second acquisition wait overlapping 271 short cycles;
  making the two admission waits passive reduced the largest observed wait to
  0.112 seconds. Both three-case diagnostic runs passed; this is cause evidence,
  not a full gate receipt. Remove only their reconciliation wakeups, preserving
  the service loop and mutation wakeups. Independent startup review passed with
  no findings; regression coverage and both full gates now pass at `8702e06`.
  Independent review accepted this queue correction; the separate `04443ed`
  policy-warning correction passed its newly approved verification without findings.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | #277 merged at `133505b` | CLI guard and A-11 test correction implemented; targeted 24 + 15 passed; both required gates passed at `74f117c` | independent review passed with no findings | phase worktree and branches removed; generated evidence retained in clean integration worktree |
| 2 | [#278](https://github.com/samcantrill/loom/pull/278) open to develop; manager PR checks passed | `04443ed`: 80 focused passes, both full gates passed, 2,994 summary passes / five optional skips, SIF smoke 1 passed | independent review passed; hard-limit proof deferred | worktree/branch retained for merge; receipts preserved in integration `build/stage-38-p2-04443ed` |
| 3 | pending | not started | design gate pending | not created |

Final integrated review must verify all selected changes on their merged
develop revision, not just each PR in isolation. The overall stage is incomplete
until all approved outcomes are proven and merged; a held timeout phase cannot
be relabelled as completion of a smaller stage.
