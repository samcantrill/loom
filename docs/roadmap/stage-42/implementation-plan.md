# Roadmap Stage 42 Implementation Plan

Status: maintainer-approved plan; independent plan readiness review passed;
implementation authorized; P1 and P2 merged, P3 next.
Roadmap stage: 42
Stage descriptor: Run Discovery, Annotations, Lineage, And Result Access
Planning document: [planning.md](planning.md)
Workflow: [roadmap-stage-implementation](../../../.codex/workflows/roadmap-stage-implementation.md)
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: between P2 and P3; publish completion metadata and synchronize.
Startup requirements: satisfied on 2026-09-24; explicit whole-stage execution requested.

## Summary

Give native clients a generic way to record why work was submitted, update run
annotations, discover executions, resolve exact published results, follow their
recorded dependencies, and retrieve their files. Extend existing coordinator,
authority, catalog, output-commit, and materialization owners. No new experiment
entity, service, domain vocabulary, or execution identity is introduced.

The maintainer accepted the intent on 2026-09-24, requested this detailed
implementation plan and code walkthrough, and then explicitly requested committing
and merging the packet into `develop`. The [approval record](planning.md#approval-and-publication-handoff)
owns that publication authorization. A subsequent explicit whole-stage request
authorized implementation, which is now underway in the recorded stage worktree.
The [walkthrough](implementation-walkthrough.md) explains the implementation in
plain language. Contracts live in the indexed planning cards, not the walkthrough.

## Shared Constraints

| Constraint / IDs | Authoritative owner | Consuming phases |
| --- | --- | --- |
| Native identity, inert application context, original submission versus current annotations; C requirements/decisions | [Run context](planning/run-context.md#detailed-implementation-contract) | P1–P6 |
| Replay, annotation revision, notes, migration, authority and transport limits; C validation | [Safe patches and notes](planning/run-context.md#safe-patches-and-notes) and adjacent storage/transport sections | P1, P2; P3 reads |
| Query vocabulary, typed truth rules, native provenance, scopes, live pages/coverage; Q requirements/decisions/validation | [Discovery](planning/discovery.md#detailed-implementation-contract) | P3; P4–P6 compose |
| Exact producer commit selection, complete declarations, retained attempt input identities, supported access paths; A requirements/decisions/validation | [Output access](planning/output-access.md#detailed-implementation-contract) | P4–P6 |
| CLI/Python/MCP parity and safe generic end-to-end journey | `FR-42-A09`, `VAL-42-A07`, `VAL-42-A08` in output access | Each phase owns its adapters; P6 owns composed acceptance |

Examples of `client.runs`, `client.outputs`, or similar facades in the original
intent examples are behavioral sketches. The detailed contract settles on the
existing flat `CoordinatorClient` plus inert value objects from `loom.runs`.
Private module/helper names below are suggested homes, not frozen architecture.
Durable/wire meanings and compatibility obligations are fixed for this approved plan.

## Execution Context

- Evidence revision: `220358ed26392f30bb2f36bf09d547607a57d442`.
- Clean control checkout at evidence capture:
  `/nas/home/can134/work/loom-worktrees/control-stage-40`.
- Execution worktree root: `/nas/home/can134/work/loom-worktrees`.
- Persistent stage worktree: `/nas/home/can134/work/loom-worktrees/stage-42`.
- Coordination branch: `agent/stage-42`.
- P1 approved base: `305ffa4416e53d3bb189e6251642641025993e98`.
- Shared Git gate: `.codex/prompts/phase-loop-management.md`.
- Before execution, land the approved packet, refresh source evidence against
  current `develop`, and follow the implementation workflow. Never edit local
  `develop`. All phase branches/PRs use the persistent stage worktree through
  synchronized closeout. Physical paths are startup context, not product API.

## Phase Index

| Phase | Slug / plan | Status | Branch | PR | Ownership and usable outcome | Validation |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | [submission-context](phases/submission-context.md) | merged | `agent/stage-42-p1-submission-context` | #349 | Capture submission context, initialize authority annotations once, inspect context and native associations | Submission/replay/schema/native-client contracts; full cross-cutting gate |
| P2 | [run-annotations](phases/run-annotations.md) | merged | `agent/stage-42-p2-run-annotations` | #351 | Revision-safe label/description/metadata changes and idempotent append-only notes | Both authority owners, concurrency/replay, read-only role rejection |
| P3 | [run-discovery](phases/run-discovery.md) | merged | `agent/stage-42-p3-run-discovery` | #352 | Typed run/submission/job queries, tag vocabulary and bounded live pages | Reconciled full-gate evidence and independent review/R1 confirmation passed |
| P4 | [output-selection](phases/output-selection.md) | in_progress | `agent/stage-42-p4-output-selection` | none | Exact current/historical output selection with original producer and reuse associations | Authority commit/reuse/history contracts and metadata-only guarantees |
| P5 | [dependency-lineage](phases/dependency-lineage.md) | pending | `agent/stage-42-p5-dependency-lineage` | none | Persist exact per-attempt input origins and query generic dependency graphs | Prepared-attempt/worker/store compatibility and multi-run graph; full gate |
| P6 | [artifact-access](phases/artifact-access.md) | pending | `agent/stage-42-p6-artifact-access` | none | Authorized complete-file retrieval, bounded previews, safe batch materialization and composed agent workflow | Real local/HTTPS transfer, failure/integrity matrix and final full gate |

Merge order is P1 → P2 → P3 → P4 → P5 → P6. Semantic dependencies: P2 needs P1;
P3 needs P1/P2; P4 consumes P3 run selection; P5 needs P4 identities; P6 needs P4
selection and uses P3/P5 for the complete journey. No cyclic dependency or
adapter-only closing phase is intended. Each phase ships its native routes,
Python surface, CLI/MCP adapters, tests, and behavior documentation together.

## Planning-To-Implementation Traceability

Ranges below include every numbered ID in the named card. Where an obligation
crosses phases, one owner establishes it and later phases test their own boundary.

| Planning card / accepted IDs | Implementation owner or shared reference |
| --- | --- |
| `FR-42-C01`, `C02`, `C03`, `C07`; `EX-42-C01`, `C03`; `VAL-42-C01`, `C02`, `C05`; `DQ-42-C01`, `C04` | P1; detailed context integration/storage contracts; initializes the storage portion of DQ-C02 |
| `FR-42-C04`, `C05`, `C06`; `EX-42-C02`; `VAL-42-C03`, `C04`; `DQ-42-C02`, `C03` | P2 owns editable annotations and identity invariance; P1 owns the submission-replay part of C06/C04 |
| `FR-42-Q01`–`Q07`; `EX-42-Q01`–`Q04`; `VAL-42-Q01`–`Q06`; `DQ-42-Q01`–`Q04` | P3; exact predicate and live-pagination rules at discovery owner |
| `FR-42-A04`, `A05`, `A08`; `EX-42-A04`; `VAL-42-A03`; `DQ-42-A02` | P4 fixes selected commit identity, history and availability distinction; P6 verifies bytes/failure outcomes against that selection |
| `FR-42-A01`, `A02`, `A03`; `EX-42-A01`, `A02`; `VAL-42-A01`, `A02`; `DQ-42-A01` | P5 records/traverses bindings; P4 preserves original reused-output producers |
| `FR-42-A06`, `A07`; `EX-42-A03`, `A05`; `VAL-42-A04`, `A05`, `A06`; `DQ-42-A03`, `A04` | P6 complete-file access, previews and per-item outcomes |
| `FR-42-A09`; `EX-42-A06`; `VAL-42-A07`, `A08`; `DQ-42-A05` | Every phase owns native/Python/CLI/MCP parity for its added methods; P6 owns the end-to-end composition |

No accepted feature is silently deferred. Intent refinements explicitly choose
live rather than snapshot search, append-only notes, whole declared publication
trees, and legacy-unknown lineage. Optional cloud SDKs, query snapshots/index
services, deep metadata patch languages, metric decoding, graph databases,
durable download resume, and note editing/deletion are not baseline requirements.

## Implementation Plan Review

This section is the authoritative complete-packet readiness receipt. The earlier
intent-only documentation review does not cover this expanded design.

- Status: passed on 2026-09-24 after one full independent `loom_plan_reviewer`
  pass and one targeted confirmation of the manager's R1 correction. No required
  findings remain.
- Reviewed packet revision/tree and exact paths: source HEAD above plus the roadmap
  v42 section, planning manifest, three domain cards, this manifest, six indexed
  phase cards, and the implementation walkthrough. Corrected reviewed packet
  SHA-256: `d5308ce3c672150eb04b2d912f2ce3b086602d885f83de3fb65fe7fbdad6c9dd`.
- Relevant source assumptions: revision above; native control/replay and role
  dispatch, coordinator operation journal, both authority backends, immutable
  output commits/reuse bindings, prepared-attempt records, shared publication
  receipts and transfer budgets.
- Architecture evidence: a bounded independent read-only pass verified existing
  output-commit and prepared-attempt storage. It found that preparation retains
  some bound inputs/upstream commits but does not establish complete historical
  per-input producer identity. P5 therefore adds that evidence at preparation,
  not by reconstructing it from current heads during queries.
- Findings and correction/confirmation disposition: R1 identifies missing durable
  start evidence for terminal attempts. The output-access owner and P5 now specify
  nullable monotonic authority-owned start confirmation, capture/terminal/replay
  rules, legacy unknown and restart checks in both stores without audit events.
  The same reviewer confirmed the correction and matching corrected tree digest;
  the complete packet passes independent plan readiness review.
- Initial review fingerprint: `5f882cef3b8a5064834998aa8d80f6111c18ad9494d358d423c40337b7515032`.
  Hash order is `docs/roadmap.md`, then stage packet paths sorted as relative POSIX
  strings; hash UTF-8 relative path + NUL + file bytes + NUL for each. Manager's
  initially supplied different digest used `Path` component ordering; recomputing
  string ordering reproduced the reviewer's digest. No content drift occurred.
- Accepted risks/revisit triggers: existing legacy evidence can be absent; live
  search is not a point-in-time snapshot; no retention pin; byte verification is
  limited by recorded digests. Drift at these owners reopens the affected review.
- Relevant post-review changes and affected verification: R1 in output-access,
  P5 and walkthrough received targeted confirmation. Subsequent edits only record
  this receipt/checks, maintainer approval/publication and planning/card status.
  On 2026-09-25 the maintainer explicitly chose limits for all initial tags,
  resolving the conflicting no-context compatibility promise. The run-context
  owner records that exception; P1 regression coverage and actual-head phase
  review assess its implementation. P2's run-scoped mutation identity was likewise
  explicitly selected by the maintainer; the contract and walkthrough now name
  the run scope, with implementation verification in P2. On 2026-09-25 the
  maintainer clarified that P3's 500-candidate budget caps detailed run/authority
  reads and evaluation, while allowing collection metadata enumeration to establish
  immutable ordering. The discovery owner records the scan-cost limitation;
  The maintainer also chose per-page vocabulary uniqueness with a deduplicating,
  coverage-preserving collector, as recorded at the discovery owner.
  P3 validation and actual-head independent review assess these boundaries. Other
  contracts are unchanged.
- Landing-base drift check through `e0892b350fde1e1def92531af591510890aa5072`:
  PR #346 adds remote prelaunch construction-failure reporting; PR #347 adds
  supervisor-backed rejection of unaccepted assignments during recovery. Their
  source/tests/docs preserve Stage 42's interfaces and authority evidence owners.
  Supervisor rejection is process no-start evidence, not a replacement for P5's
  retained authority acknowledgement across terminalization. Before-start
  failure/recovery is already in P5's validation scope. Reuse the independent
  review; refresh source again at implementation startup rather than claiming
  future drift is already checked.
- Manager documentation evidence: 12 packet Markdown files, 49 internal packet
  links/anchors resolved, 32 Python/JSON snippets syntax-checked without execution,
  68 uniquely owned IDs mapped to phases, one v42 roadmap entry, clean diff/prose
  whitespace checks. Runtime suites were not run for these documentation changes;
  planned phase checks are not claimed as implementation evidence.

| Finding | Severity | Owning contract/card | Resolution | Status |
| --- | --- | --- | --- | --- |
| R1: terminal attempt lacks retained start witness | Required correction | Output access / P5 / VAL-42-A01 | Add monotonic authority witness and restart/legacy validation at existing start owner | resolved; independently confirmed |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Independent full-packet review | Planning workflow | Full review and targeted R1 confirmation recorded above | passed |
| Concrete design approval | Maintainer | Recorded in planning approval owner | approved |
| Packet publication | Planning PR / implementation startup | PR #348 merged at selected base; packet matches approved PR head | passed |
| Source drift at startup | Implementation workflow | Only approved documentation changed since checked e0892b35; reuse readiness | passed |

## Implementation Workflow State

- Startup drift check and readiness reuse: passed at P1 base; exact packet comparison clean.
- Automatic merge mode: only under the approved implementation workflow after
  its local validation and independent review gates; authorized by explicit execution request.
- Phase statuses: P1–P3 merged; P4 in progress; P5–P6 pending. P3 reconciled validation and
  independent review/R1 confirmation passed. The maintainer selected per-page
  vocabulary uniqueness with collector deduplication. The maintainer chose
  run-scoped mutation IDs on 2026-09-25. The run-context contract and matching
  walkthrough now explicitly include the run in the receipt key; P2 regression
  coverage and independent actual-head review assess the implementation.
  On 2026-09-25 the maintainer
  resolved the limit conflict in favor of applying limits to all initial tags.
  The run-context owner records the accepted no-context compatibility exception;
  P1 owns regression coverage and repair of incomplete validation evidence.
- Stage cleanup and terminal disposition: persistent worktree retained; P1/P2 PRs
  #349/#351 remotely merged and exact remote phase branches retired by delivery.
- Improvement log entries: none.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| P1 | #349 / `ea4dba287c3d620c7be59356def76bd8d2bc53ad` | Required gate coverage and independent actual-head review passed; see P1 card | Universal initial-tag limits explicitly approved; no physical qualification required | Phase transition passed; worktree retained for P2 |
| P2 | #351 / `1282d9d9500bb0924cd5bdf4654919130c95e632` | Expanded gate coverage, base reconciliation and independent review/R1 confirmation passed | Run-scoped IDs approved; bounded legacy-note limitation documented | Phase transition passed; worktree retained for P3 |
| P3 | #352 / `c18130472e0f05b83c6cecc479e29f673c6c505f` | Reconciled full-gate evidence and independent review/R1 confirmation passed; see P3 card | Live pages, approved metadata scan cost/per-page vocabulary, unknown event times | Transition passed; stage worktree retained for P4 |
| P4–P6 | Not started | Planned checks are not executed test evidence | See phase cards | Not applicable yet |
