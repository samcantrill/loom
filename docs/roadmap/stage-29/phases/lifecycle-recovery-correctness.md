# Phase 13 Execution Plan: Lifecycle And Recovery Correctness

## Metadata

- Status: blocked
- Roadmap stage and phase: Stage 29, Phase 13
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p13-lifecycle-recovery-correctness`
- Worktree root and path: `/home/can134/work/active/loom-worktrees/stage-29-p13-lifecycle-recovery-correctness`
- Base revision: `135773663d899d6fc28e6251d4f99fb8641cf3b6`
- PR target: `develop`
- PR title: `Stage 29 phase 13: close lifecycle recovery gaps`
- Dependencies: merged Phase 12 and current Stage 29 correction agreement
- Workflow path: expanded; durable cross-owner lifecycle and detached-process continuity require independent review
- Blockers: required independent review reproduced two expected construction-
  rejection paths that start a fresh empty detached supervisor and then fail
  without stopping it. Correction 3/3 is exhausted; candidate head `824e935`
  is read-only blocked evidence and no PR was opened.

## Objective And Context

- Vertical outcome: an idle outbound agent remains schedulable through repeated
  lease periods; all local assignment futures are observed and reconciled live;
  definite SLURM rejection clears authority before release; initialization and
  serving have explicit, leak-free supervisor lifetimes.
- Earlier dependency: Phases 9-12 provide the exact assignment, offer,
  supervisor, global scheduler, and service-command paths being corrected.
- Later work explicitly out of scope: configuration fingerprint partitioning,
  complete protected composition, management read commands, and expanded
  examples belong to Phases 14-15.

## Current Source And Harness

- `src/loom/queue/deployment.py` republishes one 30-second offer with an
  availability-derived idempotency key inside the outbound service loop.
- `src/loom/queue/agent_sessions.py` owns session/offer/receipt durability and
  current-offer expiry; `agent_session_transport.py` owns the protected agent
  journal and HTTP operation dispatch.
- `src/loom/queue/local_daemon_execution.py` owns assignment-scoped futures,
  startup replay, local/remote/SLURM sagas, and definite-rejection paths.
- `src/loom/queue/_agent_process_supervisor.py` owns supervisor state, IPC,
  detached service start, launch containment, and existing test-only shutdown.
- Closest tests are queue deployment/session/production integrations, managed
  local execution, ready-stage SLURM integration, CLI queue tests, and the
  managed-local example E2E.

## Scope

In scope:

- A versioned offer-renewal value/receipt and transport operation.
- One compact coordinator renewal state and one compact agent-journal intent
  per session, with exact replay and next-sequence semantics.
- Continuous observation/reconciliation of exact retained local assignments.
- One idempotent definite-SLURM-rejection transition used by ordinary and
  restart paths, with authority unbind before logical/provider/final release.
- Supervisor initialization without a surviving process, serve-time start/join,
  a clean shutdown operation that checks both supervisor launches and retained
  agent-journal epoch dependencies, continuity marker/epoch, and shared
  test/example cleanup.
- Necessary hard-cut schema/protocol/version bumps.

Out of scope:

- Renewing a changed availability revision; that publishes a new offer.
- Replacement assignment allocation after observation failure.
- Supervisor termination while work is active or uncertain.
- Authority/configuration/management changes owned by later phases.

Assumptions:

- Coordinator-accepted time remains the expiry owner.
- Offer TTL stays configurable only where already supported; tests may use a
  short deterministic TTL.
- Existing assignment IDs, attempt/fence IDs, and SLURM provider capabilities
  are sufficient for exact replay.

## Fixed Contracts And Private Discretion

- Observable behavior: unchanged capacity renews before expiry without creating
  a new availability revision or offer identity. Response loss retries one
  sequence and returns the same receipt. A gap or stale request fails closed.
- Public or durable shapes: renewal binds session, offer, availability revision,
  and positive monotonic sequence; only the latest sequence/digest/receipt is
  retained per session at each owner.
- Trust and failure boundaries: only the authenticated session principal may
  renew its current offer. Authority unbind is the release safety gate. Clean
  supervisor shutdown is owner-local and permitted only after positive launch
  quiescence plus proof that the agent journal retains no assignment dependent
  on the retiring epoch.
- Cross-phase contracts: Phase 14 may reload offer capacity only by publishing a
  changed availability revision; it may not turn renewal into configuration
  mutation. Phase 15 uses the production shutdown path in examples.
- Reproducibility and compatibility: old affected store/protocol identities are
  rejected; no migration or dual read.
- Private choices: exact table/column names, renewal margin, notification queue,
  and supervisor IPC command encoding may be simplified while preserving the
  fixed state machines and bounds.

## Proportionality

- Existing seam reused: authenticated agent application dispatch, session
  store transactions, assignment reconciliation, SLURM lifecycle stores, and
  supervisor IPC.
- Material additions: one renewal operation and bounded replay row, one
  completed-future reconciliation loop, one rejection helper, and one safe
  supervisor terminal operation each correspond to a demonstrated failure.
- Deferred: leader election, lease transfer, forced supervisor kill, generic
  task runtime, and automatic unknown-work recovery.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Only a current unchanged offer is renewable in exact sequence | agent-session coordinator transaction | retrying service/HTTP response loss | expired idle capacity or unbounded receipts | idle/replay/gap/bounded-row integration |
| Every assignment future result is observed and exact work is replayed | daemon execution reconciliation | post-start exception | stranded nonterminal assignment | injected future failure and same-ID replay |
| Definite SLURM rejection cannot release before authority unbind | SLURM assignment rejection transition | crash/exception between stores/provider | retained bound attempt with released slot | crash after every arrow |
| Supervisor shutdown requires launch and cross-owner journal quiescence | agent role operation plus supervisor service/store | role stop after terminal observation but before journal reconciliation | inaccessible retained receipt, killed live work, or leaked process | busy refusal, terminal-before-journal-reconcile restart, clean stop/restart, process sentinel |

## Implementation Slices

1. Add renewal models, store/journal operations, transport codec/dispatch, and
   exact sequence/replay tests; update the outbound loop to publish on change and
   renew otherwise.
2. Extract exact local assignment replay from startup, consume completed
   futures during every bounded reconcile cycle, and persist health/retry state.
3. Consolidate definite SLURM rejection and add crash-boundary reconciliation
   tests proving unbind-before-release.
4. Make initialization process-free, add serve-time start/join plus clean
   quiescent shutdown/continuity records, require the agent journal to have no
   dependency on the retiring epoch, and migrate production/test/example cleanup
   to that role-level operation.
5. Bump affected hard-cut identities and run the combined lifecycle/leak gate.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required if exports change | cheap typed public imports | exact intentional exports only |
| Unit | required | renewal codec/sequences, supervisor state, rejection helper | replay/gap/busy/order matrices |
| Contract | required for application/authority protocol changes | structural downstream adapters and version hard cut | dummy adapter and old-version rejection |
| Integration | required | idle offer, live future recovery, SLURM crash arrows, process lifetime | exact retained identities, terminal-before-journal-reconcile refusal, and no leaked PID |
| E2E | required | init/serve/stop and embedded example cleanup | subprocess PID/process sentinel |

Targeted commands:

    uv run pytest tests/unit/loom/queue tests/integration/queue/test_agent_session_transport.py tests/integration/queue/test_local_daemon_production.py tests/integration/pipeline/test_managed_local_execution.py
    uv run pytest tests/integration/queue/test_slurm_ready_stage.py tests/unit/loom/cli/test_queue.py tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: renewal and availability revisions becoming competing owners;
  replay allocating new work; releasing a SLURM slot while authority is bound;
  clean shutdown mistaking process absence for containment.
- Review focus: durable ordering and exact crash recovery at all four owners.
- Stop if: renewal requires weakening session principal checks; assignment replay
  cannot preserve exact identity; authority lacks an idempotent unbind; or
  supervisor quiescence cannot be positively established from retained state.
- Accepted debt: genuinely unknown work intentionally keeps the supervisor and
  capacity alive; forced administrative termination is deferred.

## Executor Handoff

- Read section range: this entire phase plan plus Stage 29 planning FR-31-34 and
  DD-31-34.
- Safe implementation slices: 1-5 above, in order; commit cohesive tested
  slices as useful.
- Decisions not to revisit: offer versus renewal separation, bounded one-row
  replay, exact-assignment replay, unbind-before-release, process-free init, and
  quiescence-only shutdown.
- Conditions requiring manager action: any public/durable contract conflict,
  need for compatibility/migration, inability to prove quiescence, or scope
  expansion into Phase 14/15.

## Workflow State

- Manager preparation: passed at base `1357736`
- Expanded planning: design-safety findings on supervisor epoch references and long-poll saturation were corrected; bounded plan review passed after narrowing Phase 14 CLI failure semantics
- Implementation: candidate complete at source/test revision `748f938`; renewal rollover, durable exact-future replay, definite-rejection ordering, and process-free/clean supervisor lifecycle landed
- Refiner: complete; correction budget 3/3 is exhausted
- Pre-submit gate: targeted lifecycle matrices and fresh `make validate-pr` passed; `make test-summary` was stopped after review found the blocker because a closure correction makes the receipt stale
- Independent review: blocked submission after reproducing a leaked supervisor on changed local scheduling configuration and mismatched outbound deployment fingerprint
- Blocker corrections: 3/3
- PR and merge: no PR opened; preserve branch `agent/stage-29-p13-lifecycle-recovery-correctness` at `824e935` as read-only evidence

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Candidate adds renewal/session transport and hard-cut schemas, unchanged-offer outbound renewal, completed-future observation, authority-unbind-before-release rejection replay, and process-free/quiescent supervisor lifecycle. |
| Tests added or updated | Renewal replay/gap/stale/bounded-row, three-TTL idle assignment, two-failure exact local replay, six SLURM rejection crash cuts, and process-free/busy/retained/clean supervisor coverage. |
| Validated revision/tree state and evidence | Source/test `748f938` plus documentation head `824e935`; focused lifecycle matrices and fresh `make validate-pr` passed with Ruff, pyright, 2,676 default tests, 156 configuration-extra tests plus three skips, and source/wheel builds. |
| Validation-relevant changes after evidence | Documentation only after `748f938`. |
| PR, review, and merge | Required independent review blocked submission; no PR opened and correction 3/3 is exhausted. |
| Residual risk and cleanup | Expected local and outbound configuration rejection can leak a newly started empty detached supervisor because service start precedes complete durable validation. The reviewer reproduced and cleaned both exact processes. Other reviewed FR-31 through FR-34 behavior had no blocker. |
