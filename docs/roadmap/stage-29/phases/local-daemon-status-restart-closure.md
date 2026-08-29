# Phase 3D Execution Plan: Local Daemon Status And Restart Closure

## Metadata

- Status: merged
- Roadmap stage and phase: Stage 29, Phase 3D
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p3d-local-daemon-status-restart-closure`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-29-p3d-local-daemon-status-restart-closure`
- Base revision: clean `origin/develop` at
  `6163d9e5fea6afe6a7c80651e2e97c66f6cf29a1`
- PR target: `develop`
- PR title: `feat(queue): close local daemon status and restart contracts`
- Dependencies: Phases 1-2 merged; Phases 3A-3C blocked and retained only as
  read-only evidence
- Workflow path: expanded for one independent implementation review because
  Phase 3C review demonstrated durable-owner and cross-owner restart failures;
  no phase-planner pass is needed because the maintainer approved their exact
  fresh-only resolution
- Blockers: none

## Objective And Context

- Vertical outcome: merge the already validated persistent local-daemon path
  only after status proves what each owner actually observed and a missing
  expected execution or journal store can never become healthy empty capacity.
- Earlier evidence: Phase 3C source/test revision `1879cd1` closes exact runtime,
  singleton/scoped authority, retained-claim, terminal cancellation, real
  execution, diagnostic redaction, and hard-cutover contracts. It passed local
  gates and CI but cannot merge because review found the two residual failures.
- Later work explicitly out of scope: remote agents, disconnected controls,
  process adoption, positive-containment recovery, disaster recovery, and any
  compatibility or migration path.

## Current Source And Harness

- Selective source evidence: Phase 3C `loom.queue.local_daemon`,
  `local_daemon_execution`, `local_daemon_runtime`, and
  `local_daemon_transport`; pipeline managed-local execution and authority
  stores; CLI/public imports; the production integration and contract tests.
- Durable owners on the validated candidate are the daemon admission/control
  store, authority run store, coordinator stage-work/assignment stores in
  `execution.sqlite`, and local-agent journal in `journal.sqlite`.
- Current failures: healthy scheduling/assignment/agent axes expose collections
  without aggregate state, owner revision/receipt, or freshness; file absence
  can bypass reads and let SQLite later recreate empty stores; and
  `LocalDaemon.start()` can retain locks/workers if execution construction
  raises.
- Import direction remains queue application composition -> pipeline runtime,
  orchestration, scheduling, stores, and execution. Pipeline execution must not
  import queue transport types.

## Scope

In scope:

- Selectively port Phase 3C validated source/tests onto the fresh Phase 3D base.
  Do not base or stack on the blocked branch and do not import its workflow
  metadata as current state.
- Separate explicit owner-store initialization from runtime open. Initializing a
  fresh current daemon root creates the current execution and agent store
  schemas. Start/status/reconcile/scheduling open those expected stores without
  permission to recreate them silently.
- If either expected owner store is missing, corrupt, or unreadable at start,
  fail closed with a stable safe diagnostic and release all partially acquired
  locks/workers. If it becomes unavailable while running, mark its axes and
  service degraded and prevent any new offer, reservation, assignment, or
  launch. Existing unknown work remains conservatively unresolved.
- Give every applicable status axis an owner, availability, aggregate state,
  owner-derived monotonic revision or accepted receipt, observation time, and
  freshness. Healthy-empty is explicit owner evidence, not inferred absence.
  Read the axis snapshot consistently at its owner, then set top-level `as_of`
  after the non-atomic join. Direct Python, socket, and CLI machine output use
  the same normalized shape.
- Preserve all Phase 3C behavior and hard-cutover removals, including exact
  runtime reconstruction, authority scope, retained exact claims, terminal
  cancellation, diagnostic redaction, real `preprocess -> train`, and delegated
  whole-run Slurm regressions.

Out of scope:

- Compatibility adapters, schema migrations, dual reads/writes, legacy-root
  recovery, warning periods, or automatic reconstruction of lost state.
- A public health framework, generic store protocol, remote owner freshness,
  process reattachment, or releasing unknown retained claims.

Assumptions:

- Only freshly initialized current roots are supported. Explicit initialization
  is therefore authoritative evidence that both owner stores must exist later.
- A revision may use an existing durable owner sequence or a small private
  owner-maintained counter updated atomically with mutations. Exact table/helper
  mechanics remain private, but empty state has revision zero and owner changes
  must change the revision.

## Fixed Contracts And Private Discretion

- Observable behavior: absence is never success. Healthy empty status means the
  owner store was opened and read during this join. Owner failure degrades
  service and cannot authorize capacity or mutation.
- Public/durable shape: scheduling, assignment, and local-agent axes gain
  aggregate `state`, revision/receipt, and freshness alongside existing owner,
  availability, `observed_at`, diagnostics, and records. Admission, authority,
  and service axes retain equivalent evidence. Exact enum names and private
  snapshot types may be simplified if all supported entrypoints agree.
- Causal boundary: initialize schemas before serving; verify/open owner stores
  before retained reconciliation; reconcile before offer; recheck availability
  before new scheduling mutation; observe axes before top-level `as_of`.
- Compatibility: hard cut-over only. Old or partially initialized roots are
  rejected untouched. Delegated Slurm is unchanged.
- Private choices: store initialization API, revision counter versus existing
  event high-water, aggregation helper, and internal degraded-state plumbing.

## Proportionality

- Reuse the complete validated Phase 3C production path and tests.
- Add only explicit store initialization/open policy, owner snapshot evidence,
  one fail-closed scheduling guard, and construction cleanup. Each answers a
  demonstrated reachable failure.
- Defer last-known snapshot retention, generalized health aggregation, online
  repair, migrations, and disaster recovery because no current consumer needs
  them.

## Invariant Ownership

| Invariant | Owner | Invalid boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Healthy empty is observed, not inferred | Each SQLite owner snapshot | Missing file or skipped read | False healthy status | Empty/populated/lost-store status cases |
| Retained state loss never frees capacity | Daemon execution startup and scheduling guard | Runtime auto-creates a missing store | Overcommit or duplicate effect | Each-store restart/live-loss cases with zero offer/launch |
| Axis evidence changes with owner truth | Owner revision/receipt | Collections change without axis revision | Indistinguishable stale snapshot | Mutation/revision and `observed_at <= as_of` tests |
| Failed construction leaves no live daemon ownership | `LocalDaemon.start()` cleanup | Execution constructor raises after acquisition | Lock/worker leak | Failure then successful restart test |

## Implementation Slices

1. Port Phase 3C source/tests without its phase metadata and confirm the focused
   production trace.
2. Add explicit owner-store initialize versus open-existing behavior and guard
   startup plus live scheduling against lost/unreadable stores.
3. Build complete owner snapshots and normalize them through direct/socket/CLI
   status, including degraded service evidence.
4. Add partial-start cleanup and focused restart/status tests, then retain the
   full Phase 3C regression matrix and docs.

## Test And Validation Plan

| Suite | Required | Minimal assertions |
| --- | --- | --- |
| Unit | yes | Explicit initialization; open-existing refusal; healthy-empty/populated state and revision; constructor cleanup |
| Contract | yes | Identical direct/socket/CLI axes; stable safe missing/corrupt-store diagnostics; no raw paths/errors |
| Integration | yes | Each store missing at restart and lost while live; no offer/reservation/launch; restored fresh root can start |
| E2E/regression | yes | Real two-stage success, restart/cancel/status, hard-cutover rejection, delegated Slurm unchanged |

Targeted commands:

    uv run pytest -q tests/unit/loom/queue tests/contracts/test_local_daemon_authority_contract.py tests/contracts/test_queue_python_api_contract.py
    uv run pytest -q tests/integration/queue/test_local_daemon_production.py tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: silently recreating a lost SQLite file, fabricating a revision,
  advancing work after partial owner failure, or weakening validated Phase 3C
  contracts while porting.
- Review focus: initialize/open split, every scheduling gate, healthy-empty
  evidence, revision causality, non-atomic `as_of`, cleanup, hard cut-over, and
  delegated Slurm isolation.
- Stop if safe closure requires compatibility, reconstructing lost owner truth,
  releasing an unknown claim, changing delegated ownership, or bypassing the
  Phase 1/2 path.
- Accepted debt: missing/corrupt state requires operator restoration or later
  disaster recovery; unknown work may hold capacity indefinitely.

## Executor Handoff

- Read this file from `Current Source And Harness` through `Risks, Review, And
  Stops`, plus manifest `Summary`, `Shared Constraints`, `Phase Index`, and
  `Quality Gate`.
- Own all Phase 3D source, tests, examples, and feature-doc changes in the
  dedicated worktree. Preserve unrelated work and do not delegate.
- Do not revisit hard cut-over, exact runtime, authority scope, conservative
  claims, terminal truth, public redaction, or delegated Slurm isolation.
- Return a qualified blocker if a stop condition occurs or a test needs an
  injected production collaborator.

## Workflow State

- Manager preparation: complete at clean `origin/develop` `6163d9e`; dedicated
  branch/worktree, repository `samcantrill/loom`, target/title, blocked
  predecessor evidence, source owners, tests, gates, and stop conditions are
  recorded
- Expanded planning: no phase-planner pass; accepted findings and maintainer
  resolution are decision-complete
- Implementation: complete at `2b48d0e`; owner stores initialize explicitly,
  runtime opens fail closed, owner-backed status evidence is normalized, and
  partial construction releases ownership; every retained owner store is bound
  to the stable identity of its fresh coordinator or local-agent root
- Refiner: correction 2/3 complete; fresh execution and journal stores bind to
  the coordinator and local-agent stable identities, every owner/status open
  verifies those bindings, and control opens are read-write-existing plus
  cached-coordinator identity checked
- Manager correction: correction 1/3 complete; runtime SQLite connections now
  use true open-existing mode, each owner reads revision and rows in one
  snapshot, unavailable axes cannot look empty, and focused tests prove empty,
  changed, degraded, direct, and socket status evidence
- Pre-submit gate: complete at `2b48d0e`; `make validate-pr` passed Ruff,
  complete Pyright, 2,397 default tests, 141 configuration-extra tests with 3
  environment skips, and source/wheel builds; a fresh `make test-summary`
  receipt recorded 2,538 passes and the same 3 skips
- Independent review: complete; the reviewer found that same-schema owner-store
  substitution was not yet rejected, correction 2/3 bound every retained store
  to its stable root identity, and manager verification plus the fresh full
  gate found no remaining blocker
- Blocker corrections: 2/3
- PR and merge: [#237](https://github.com/samcantrill/loom/pull/237) passed CI
  and was squash-merged into `develop` as `6a8cf9f`

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Selectively ported the validated Phase 3C local-daemon production path and its source, public wiring, examples, feature docs, and regression replacement. Phase 3D changes are concentrated in `src/loom/queue/local_daemon.py`, `local_daemon_execution.py`, `src/loom/pipeline/orchestration.py`, and `src/loom/pipeline/execution/managed_local.py`: fresh initialization creates both runtime owner schemas and binds them to immutable coordinator/local-agent identities; daemon runtime opens all stores existing-only, revalidates those bindings, and verifies its cached coordinator identity on each live control connection; lost/corrupt/substituted owners degrade service and block scheduling; owner snapshots carry aggregate state, durable revisions, observations, and freshness; and failed execution construction releases workers and both locks. |
| Tests added or updated | `tests/unit/loom/queue/test_local_daemon.py` covers each missing owner store without recreation, current-schema substitutions for control/execution/journal on restart, live control loss/substitution, live runtime-owner substitution degradation, live loss scheduling block, and construction cleanup. `tests/integration/queue/test_local_daemon_production.py` covers explicit owner schema setup, exact owner bindings for direct owner snapshots, healthy-empty and populated axes, monotonic owner revision changes, unavailable state/freshness, and direct/socket normalization. Retained Phase 3C contract, production, and CLI tests remain in the focused matrix. |
| Validated revision/tree state and evidence | Source/test revision `2b48d0e` with a clean tree. Focused: `uv run pytest -q tests/unit/loom/queue tests/contracts/test_local_daemon_authority_contract.py tests/contracts/test_queue_python_api_contract.py` (183 passed) and `uv run pytest -q tests/integration/queue/test_local_daemon_production.py` (28 passed). `make validate-pr` passed Ruff, complete Pyright, 2,397 default tests, 141 configuration-extra tests with 3 environment skips, and source/wheel builds. Fresh `make test-summary`: package 118, unit 1,704, contract 295, integration 223, E2E 57, and configuration-extra 141; 2,538 total passes and 3 environment skips. |
| Validation-relevant changes after evidence | None. Only evidence and merge metadata changed after the validated source/test revision. |
| PR, review, and merge | [#237](https://github.com/samcantrill/loom/pull/237) targeted `develop` with the required title, passed the required `checks` workflow in 5m14s, and was squash-merged as `6a8cf9f`. Independent review's stable-owner-identity blocker was corrected at `2b48d0e` and manager-verified before merge. |
| Residual risk and cleanup | Missing or corrupt owner truth remains deliberately unrecoverable and may retain unknown capacity until operator restoration; no migration, reconstruction, or release of unknown claims was added. The Phase 3D worktree and local/remote phase branch were removed after merge metadata was recorded; blocked Phase 3A-3C evidence remains untouched. |
