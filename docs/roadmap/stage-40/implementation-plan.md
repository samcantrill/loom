# Roadmap Stage 40 Implementation Plan

Status: approved; implementation in progress
Roadmap stage: 40
Stage descriptor: Coordinator Client, Agent Preparation, And MCP
Workflow: .codex/workflows/roadmap-stage-implementation.md
Planning document: [planning.md](planning.md)
Behavior guide: [Detailed explanation and code examples](../../briefs/mcp-implementation-plan.md)
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: 2 - agent-preparation (pr_open)
Next phase: 3 - staged-preparation-inputs (after Phase 2 delivery and synchronization)
Blockers: Phase 2 independent review requires terminal rejection of malformed committed native evidence; correction passes affected checks and awaits the same reviewer's confirmation.
Maintainer approval: Stage 40 behavior and four-phase delivery approved on 2026-09-10.

## Summary

- Goal: operate Loom through one native coordinator client from Python, CLI or
  Codex; prepare coordinator-authored configuration on an eligible local/remote
  worker in a specified existing environment, then submit and observe its run.
- Agreed behavior: FR-40-01 through FR-40-12. Direct coordinator control, existing
  environments, shared NAS plus explicit staged preparation, stable IDs and
  project-neutral skills are user-confirmed.
- Design constraints: DQ-40-01 through DQ-40-07. Expanded design review passed;
  the native client sits above queue/diagnostics, an ordinary child performs
  preparation, and the existing publisher owns the canonical target.
- Minimum useful change: Phase 1 delivers complete native local/HTTPS control;
  Phase 2 delivers the complete shared-storage preparation-to-execution journey;
  Phase 3 adds staged inputs to that same lifecycle; Phase 4 gives Codex tools
  and portable operational instructions over both supported source modes.
- Excluded complexity: alternate schedulers/queues, agent client relays, general
  source deployment/path rewriting, environment builders, generic experiment
  models, MCP storage, remote MCP hosting and broad public renames.
- Validation and phase-shaping source: planning.md Examples And Validation and
  Phase Shaping, with executable obligations in each linked card.
- Out of scope: scientific choices/workloads, package installation by preparation,
  new SLURM/non-embedded preparation, arbitrary laptop uploads, per-project ACLs,
  large dataset delivery and unfinished unrelated roadmap work.

## Implement, Migrate, Remove, Preserve

| Treatment | Concrete changes | Why / contract owner |
| --- | --- | --- |
| Implement | Native CoordinatorClient facade, protected HTTPS client config, coordinator-identity guard, complete client operation parity, typed error detail and bounded I/O | Three consumers share one behavior; Phase 1 owns API/protocol |
| Implement | Coordinator prepare operation, fixed managed preparation child, finite shared input capture and checked-composition report | Worker environment is needed; publication/lifetime remain coordinator-owned; Phase 2 |
| Implement | Coordinator-only root upgrade and preparation evidence retention | New state must not require discarded existing work; Phase 2 |
| Implement | Staged archive capture, native relay/extraction and effective mode support | Complete non-shared preparation over the same operation/report/publisher; Phase 3 |
| Implement | Optional MCP adapter, 13 tools, four skills and isolated SDK validation | Assistant usability over native operations; Phase 4 |
| Migrate | CLI client constructors and shared socket/HTTPS method/decoder implementations | Thin compatibility facades delegate to one owner; Phase 1 |
| Migrate | Existing preflight checks to accept a supplied composition; normalize recipe evidence at publisher | Check/publish the same data and preserve nonempty recipe replay; Phase 2 |
| Migrate | Coordinator schema 12 to 13 under explicit offline lock/backup/transaction | Preserve IDs and admissions; leave worker roots/journals on their existing schema; Phase 2 |
| Remove | Duplicate internal client decoding and matching dispatch branches after consumers switch; socket wait busy retry | Reduce divergence and starvation; Phase 1 |
| Replace in docs | Long exploratory MCP brief becomes explanation linking this canonical plan | One implementation contract owner |
| Preserve | LocalDaemonSocketClient public behavior, native model names, QueueClient/QueueService, worker supervision and role policy | Different/established contracts do not need a breaking rewrite |
| Preserve | Managed publisher, authority, stage scheduler, native artifact transfer and diagnostic models | Existing owners already provide the substantive execution system |

No public legacy removal is scheduled. No phase may reset retained roots or
rewrite existing run/admission identities to make a migration easier.

## Shared Constraints

- The coordinator accepts every client mutation. Remote agents maintain their
  existing outbound sessions. MCP does not route through a worker daemon.
- Application behavior and durable truth stay native. Queue/application codecs
  sit below the integration facade; diagnostics and composition are wired above
  queue. Lower runtime imports never depend on MCP, diagnostics or project code.
- Successful results reuse native admission, operation, inspection and preparation
  receipt models. The new prepare result carries coordinator_id while the existing
  LocalDaemonOperation outer model and ManagedLocalPreparationReceipt stay intact.
  Reconnectable client, CLI and MCP calls can send expected_coordinator_id; the
  coordinator checks it before lookup or mutation. Observation state does not
  establish execution/containment. Phase 1 owns transport/error/guard/bounds;
  Phase 2 owns preparation request/result/state and its versioned input/report.
  Phase 3 owns staged archive/relay/extraction behavior over that same contract.
- Phase 2 publishes a complete lifecycle with shared source support only. Staged
  requests fail unsupported/not_applied before reservation, capture or dispatch;
  effective advertised modes intersect implementation support with protected
  policy. Phase 3 enables staged handling in qualified installations and preserves
  existing shared records, receipt/report shapes and coordinator schema 13 without
  a second root migration. Both modes remain required for Stage 40 completion.
- A complete prepare operation projection is at most 64 KiB. Reserve its state,
  coordinator, identifiers, full native prepared receipt and report reference
  before optionally inlining one complete native preflight result. Full reports
  remain pinned; no projection silently truncates evidence.
- Preparation uses a configured existing installation. Capture serves only the
  preparation child. Published executable values must be portable; target code/
  data use compatible installations and existing supported bindings. No new
  general resource URI scheme or arbitrary path rewriting.
- Same explicit request/ID replays the original accepted intent. Closing a client
  or MCP does not cancel work. Only explicit lifecycle requests initiate native
  cancellation; unknown mutation outcomes retain original IDs for reconciliation.
- Preserve published Stage 39 resource and failure contracts and existing query/
  operator/worker role distinctions. Reconcile intervening published source
  changes before starting each phase; never infer mutable facts from old cards.
- Execution paths and coordination are recorded in Execution Context below.
  Preserve the original dirty Loom checkout and unrelated worktrees.
- Each phase uses its own branch and PR in the persistent stage worktree. The
  successor starts after remote predecessor merge, published metadata and the
  shared synchronization gate. Required local gates remain make validate-pr and
  make test-summary, plus independent implementation review for every card.
  Hosted CI remains disabled.
- Phase 4 adds an isolated MCP dependency lane to those gates. Live Codex and
  physical NAS acceptance are separate release claims, not inferred from loopback
  tests. If unavailable, record the limitation without claiming success.
- This approval adopts the concrete contracts; it is not permission for
  scientific execution, remote environment installation or real-root upgrades
  during this planning task.

## Execution Context

- Execution worktree root: `/nas/home/can134/work/loom-worktrees`.
- Clean control checkout: `control` under that root; verify or create a clean
  linked checkout on develop without repurposing unrelated work.
- Persistent stage worktree: `stage-40` under that root; bootstrap before
  startup review or writes and retain through final synchronized closeout.
- Coordination branch: `agent/stage-40` for metadata and closeout.
- Shared Git gate: `.codex/prompts/phase-loop-management.md`.
- Execution-mechanics amendment: refined workflow adopted on 2026-09-10;
  phase scope/order, approvals, fixed contracts and validation remain unchanged.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | coordinator-client | merged | [Direct coordinator control](phases/coordinator-client.md) | agent/stage-40-p1-coordinator-client | [#298](https://github.com/samcantrill/loom/pull/298) | Native client, Unix/HTTPS, protected client config, CLI adapters | Same native control from any client host |
| 2 | agent-preparation | pr_open | [Durable preparation on shared storage](phases/agent-preparation.md) | agent/stage-40-p2-agent-preparation | [#300](https://github.com/samcantrill/loom/pull/300) | Common preparation lifecycle, shared capture/child/report, diagnostics/publisher, profile policy and root upgrade | Complete preparation and target execution using shared storage |
| 3 | staged-preparation-inputs | pending | [Preparation with transferred inputs](phases/staged-preparation-inputs.md) | agent/stage-40-p3-staged-preparation-inputs | pending | Archive capture, native relay/extraction, effective mode support and staged boundary validation | Same preparation lifecycle without shared project storage |
| 4 | mcp-skills | pending | [MCP and portable skills](phases/mcp-skills.md) | agent/stage-40-p4-mcp-skills | pending | Optional SDK adapter, tool contracts, skill distribution, examples and SDK lane | Use both native source modes from Codex across projects |

Each phase is one independently mergeable PR. Its card has four or five bounded
implementation steps with focused validation; steps do not create extra PRs.
Each card's Implementation Walkthrough explains core code changes, reuse and
migration, request/result handoffs, recovery and practical usage with illustrative
code. Fixed Contracts And Private Discretion remains its contract owner; private
helper sketches do not add public APIs or prescribe internal module layout.
Four phases are justified by the distinct archive/transfer/extraction boundary:
Phase 2 delivers the user's shared-NAS workflow with full recovery/cancellation,
and Phase 3 adds non-shared delivery in a focused review. Publication, recovery,
cancellation and the storage upgrade remain with their Phase 2 consumer. No
schema-only phase or incomplete durable lifecycle is released. The additional
phase changes delivery granularity, not the accepted final behavior.

## Quality Gate

This is the grandfathered authoritative readiness receipt. Reuse the recorded
approval/review below under the current workflow; no new product-plan review is
claimed by the skill/title metadata update. Phase scope/order, fixed contracts,
and all approved validation commands remain binding.

- Planning gate: user direction agreed; expanded removal-first design review
  passed. Its three material clarifications are integrated into Phase 2.
- Manager review: passed; source ownership, handoff corrections, manifest/card
  consistency, local links, examples, tool/skill inventory and whitespace checked.
  This is documentation validation; no runtime evidence is claimed.
- Independent plan review: one expanded pass completed; it found coordinator-ID
  reconnect and oversized preparation-projection blockers.
- Correction: one bounded correction passed; Phase 1 now owns the server-checked
  expected_coordinator_id guard, and Phase 2 owns a 64 KiB preparation projection
  with pinned full-report evidence and pre-publication receipt-size refusal.
- Maintainer approval: behavior and four-phase delivery approved on 2026-09-10.
- Startup gate: revised four-phase plan passed focused independent review on
  2026-09-10 with no blockers, optional concerns or required corrections. Mode
  rollout, installation qualification, retained shared-state compatibility and
  complete allocation of accepted validation agree across the cards and guide.
  HEAD, origin/develop and live published develop matched
  `382065646608f4f19fed17a6fc0ecc9fce4a6e3f`. Manager documentation checks passed
  for seven artifacts, four phase/branch mappings, links/anchors, example syntax,
  the unchanged native schema, thirteen tools and four skills.
- Ready for implementation: yes. Whole-stage execution is authorized. Startup
  on 2026-09-11 used published develop
  `1a21a78df89f766ef5c19eb6607512a41866ea17`, containing the approved packet
  from PR #295 and the execution-mechanics amendments from PRs #296 and #297.
  The shared Git setup/preflight gates created and verified the manifest's
  persistent stage worktree, Phase 1 branch and coordination branch. Review
  reuse and intervening source changes are recorded in the Phase 1 card.
- Accepted risks: existing source identity observations are finite; preparation
  has bounded inputs and one environment; partial targets remain conflicts;
  retained operation evidence consumes space; client policy is deployment-wide.
- Revisit triggers: a supported project needs code deployment, large runtime
  inputs, another authority/preparation family or multiple preparation environments.
- Phase 1 is merged and independently reviewed; Phase 2 is next. The published Stage 41 lifecycle guide remains separate
  product planning.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | [#298](https://github.com/samcantrill/loom/pull/298), merge `3b3942a88ee0729612f02fe3d7dbda3164c762d4` | Native control delivered; both required full gates and affected TLS checks passed; independent review found no issues. See the phase card for revisions and counts | Physical deployment/Codex deferred as planned | Remote branch retired; persistent stage worktree retained through remaining phases |
| 2 | [#300](https://github.com/samcantrill/loom/pull/300), open | Shared preparation lifecycle and native/CLI journeys implemented; focused worker placement, recovery, cancellation, report, retention and populated-root upgrade checks pass. Both required full gates pass. Independent review identified malformed-report decoder classification; the correction passes all 44 affected preparation cases and static checks, with reviewer confirmation pending. See the phase card | Loopback and fixture-root evidence; no physical deployment claim or real-root upgrade | Reuses the retained Stage 40 worktree; predecessor branches retired and synchronization passed |
| 3 | Not started | No staged-input or retained-state receipt | Transfer/extraction unvalidated | Reuses the retained Stage 40 worktree after predecessor synchronization |
| 4 | Not started | No runtime or live acceptance receipt | Codex/physical deployment unvalidated | Reuses the retained Stage 40 worktree through final closeout |
