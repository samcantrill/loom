# Phase 3 Execution Plan: Service-Less SLURM Completion

## Metadata

- Status: merged
- Roadmap stage and phase: Stage 32, Phase 3
- Manifest: docs/roadmap/stage-32/implementation-plan.md
- Branch: agent/stage-32-p3-service-less-slurm-completion
- Worktree root and path: `/home/can134/work/active/loom-worktrees/stage-32-p3-service-less-slurm-completion`
- Base revision: `f9b18c1cc7dba59de90310ceac4fbae8f4e1b837`
- PR target: develop
- PR title: `Stage 32 phase 3: complete service-less SLURM driving`
- Dependencies: Stage 32 Phase 1 remotely merged; Phase 2 explicitly blocked;
  retained candidate `c9cbd2ccbdff0a55c7b3924ec7afeca45af8bfc6`
- Workflow path: expanded; external scheduler evidence and compute-visible path
  admission remain material trust and durability boundaries
- Blockers: none

## Objective And Context

- Vertical outcome: deliver the complete approved service-less SLURM driver in
  one PR based on current `develop`, including safe many-run handoff, exact
  scheduler-call recovery, per-job retained scheduler evidence, and rejection
  of prepared runs whose shared workspace is not explicitly proven.
- Earlier dependency: Phase 1 supplies ordinary-run admission and bounded queue
  reads. The blocked Phase 2 candidate supplies reviewed implementation input,
  but is not a merge base and must not create a stacked diff.
- Later work explicitly out of scope: remote stores or log relay, dynamic stage
  driving, arrays, allocation-fed agents, coordinator HA, and durable reporting.

## Current Source And Harness

- Relevant files and symbols: retained candidate changes in `src/loom/queue`,
  `src/loom/cli/queue.py`, and the existing whole-run SLURM live/controller
  seams; `LaunchContract.delegated_verification`; run-local
  `SlurmSchedulerStatusSnapshot` and live-manifest atomic writes.
- Existing tests and seams: the retained candidate passed the full gate and
  covers both modes, ambiguous calls, partial `afterok`, driver restart,
  authority ownership, bounds, CLI JSON, and the executable HPC journey. Its
  retained-snapshot test injects evidence manually, and its prepared-path test
  proves only submit-host file existence.
- Import, dependency, or harness constraints: optional SLURM remains a fakeable
  CLI boundary; queue consumes plain verification evidence without importing
  bundle/transfer models; pipeline/core modules do not import queue or CLI.

## Scope

In scope:

- Carry the complete Phase 2 implementation and applicable tests/docs from
  `c9cbd2c` into this current-`develop` replacement branch. Resolve current-base
  changes normally and do not copy Phase 2 blocked-status metadata.
- During prepared-run inspection, persist every usable current scheduler fact
  for an accepted handle into the existing run-local live-manifest snapshot
  owner before returning the joined outcome. Preserve logical key, scheduler
  job ID, capture time, source, state, and available exit status.
- Build effective scheduler state per accepted handle: use that handle's current
  selected fact first, otherwise its newest retained snapshot. A retained fact
  fills only a missing current handle; it never replaces a current fact. Failure
  or cancellation of any effective handle remains terminal scheduler evidence;
  all-success wording requires facts for every accepted handle. Loom authority
  remains the only owner of scientific success.
- Before any prepared-run `sbatch`, require
  `LaunchContract.delegated_verification["shared_workspace"]` to be explicitly
  proven using the existing boolean or `{status: proven}` plain-data shape.
  Missing, false, unproven, unsupported, or malformed evidence is a safe
  pre-start rejection with no scheduler call. The retained operation path must
  not retroactively reject already accepted jobs.
- Update the executable example, CLI/programmatic guidance, and tests so all
  prepared queue submissions provide the explicit proof and operators understand
  that projects attest site visibility; Loom does not mount, copy, or probe a
  compute node.

Out of scope:

- A new filesystem-probing protocol, remote transfer/store, archive-model queue
  dependency, scheduler retry policy, generic verification schema, or changes
  to direct non-queued and Stage 29 managed execution.
- Reworking already-passing recovery, capacity, identity, CLI, reporting, or
  artifact-reference behavior beyond conflicts required by current `develop`.

Assumptions:

- Project code is trusted to attest shared-workspace visibility correctly.
- Scheduler accounting can be partial or pruned; retained snapshots are the
  bounded durable fallback, not scientific completion evidence.

## Fixed Contracts And Private Discretion

- Observable behavior: absent compute-visible proof prevents the first prepared
  scheduler call; proven shared workspace permits existing single-job and
  `afterok` behavior. Later inspection cannot forget a previously persisted fact
  merely because one accounting row disappears.
- Public or durable shapes: reuse `delegated_verification.shared_workspace` and
  the existing live-manifest `status_snapshots`; add no new job inventory,
  remote locator, or lifecycle authority.
- Trust and failure boundaries: project evidence is trusted authored input;
  scheduler output remains bounded/untrusted; manifest persistence occurs at
  the current scheduler-read boundary; authority terminal state is evaluated
  before scheduler fallback.
- Cross-phase contracts: Phase 1 queue IDs/digests and the run-local queue-item
  reference remain unchanged; Stage 34 may observe but not reinterpret them.
- Reproducibility and compatibility: replacement diff includes all accepted
  Phase 2 behavior, direct SLURM serialized shape remains unchanged, and no
  uncertain scheduler call is replayed.
- Private choices the executor may simplify: fact-selection helpers, snapshot
  append/deduplication mechanics consistent with existing status behavior,
  reason wording, and focused fixture arrangement.

## Proportionality

- Existing seam reused: live-manifest snapshots, atomic manifest write,
  delegated-verification plain data, prepared adapter, and fake scheduler.
- Material additions and current justification: one per-handle persist/merge
  path and one pre-submit proof gate directly close the independent findings.
- Optional hardening and future capability deferred: remote mount validation,
  snapshot compaction policy, multi-driver HA, and scheduler/accounting SLAs.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Last-known scheduler evidence survives per handle | run-local live manifest | partial/pruned `sacct`/`squeue` after an earlier observation | failed job disappears or run regresses to unknown | observe, reopen, partial/all-pruned matrix |
| Current facts override retained facts only for the same handle | prepared inspection join | mixed current and retained multi-job state | stale fact masks a current transition | two-job conflicting-source test |
| Prepared paths are positively attested before submission | launch contract and prepared adapter boundary | submit-host-local but compute-invisible files | accepted job cannot read/write project state | absent/false/unsupported/proven pre-call matrix |
| Scientific success remains authority-owned | per-run authority | scheduler `COMPLETED` or retained success | false experiment success | authority/scheduler status matrix |

## Implementation Slices

1. Reconstruct the reviewed Phase 2 candidate on the current base and resolve
   only genuine current-base compatibility differences.
2. Enforce explicit shared-workspace evidence before prepared submission and
   update all prepared producers/examples.
3. Persist selected current facts and join current/retained state per accepted
   scheduler handle without changing authority ownership.
4. Add causal review-finding tests, refresh docs, and rerun the existing Phase 2
   focused matrix.
5. Run full validation, independent review, and the normal PR/merge workflow.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | public imports remain intentional and optional | existing package boundary suite |
| Unit | required | proof parsing and safe pre-start rejection | missing/false/unproven/unsupported/proven shapes; zero `sbatch` on rejection |
| Contract | required | existing plain-data and manifest shapes | no new owner; direct manifest remains compatible |
| Integration | required | per-job persistence and mixed fallback | observe then prune all; retain one failed while another is current; all-success requires every handle |
| E2E / opt-in | required fake/manual live | project-facing service-less journey | explicit proof in fake journey; manual site attestation remains documented |

Targeted commands:

    uv run pytest tests/unit/loom/queue/test_slurm_adapter.py tests/integration/queue/test_delegated_slurm_controller.py
    uv run pytest tests/integration/pipeline/test_slurm_live_models.py tests/e2e/test_queue_cli.py tests/e2e/test_example_journeys.py
    uv run ruff check src/loom/queue src/loom/pipeline/executors/slurm tests/unit/loom/queue tests/integration/queue
    uv run pyright src/loom/queue src/loom/pipeline/executors/slurm tests/unit/loom/queue tests/integration/queue

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: copying a second job inventory, stale retained facts overriding
  current facts, success with a missing handle, proof checked after `sbatch`, or
  accidental stacking on the blocked branch.
- Review focus: per-handle selection/persistence, zero-call proof rejection,
  authority-first outcomes, sole live-manifest inventory, and current-base diff.
- Stop if: the fix needs remote probing/transfer, a new verification authority,
  a new manifest/job model, or changes to Stage 29/direct SLURM behavior.
- Accepted debt and revisit trigger: project attestation and fake scheduler are
  sufficient now; revisit on a demonstrated false attestation or live-site
  accounting behavior the current fact model cannot represent.

## Executor Handoff

- Read section range: `Objective And Context` through `Risks, Review, And Stops`.
- Safe implementation slices: the five slices above in the dedicated Phase 3
  worktree, including carrying the reviewed candidate but excluding its blocked
  workflow metadata.
- Decisions not to revisit: existing snapshot and delegated-verification owners,
  project attestation, authority-only scientific success, no bytes/network/new
  scheduler abstraction, and one replacement PR from current `develop`.
- Conditions requiring manager action: any source conflict that changes accepted
  behavior, inability to preserve one manifest inventory, or need for a new
  public/durable shape beyond the named existing fields.

## Workflow State

- Manager preparation: passed; dedicated worktree created from current
  `origin/develop` at `cae37be`, exact branch/PR metadata verified, and the
  executor packet remains within the planned bounded scope.
- Expanded planning: fixed by the approved replan; no planner pass required.
- Implementation: complete; carried the replacement service-less controller,
  exact operation recovery, CLI/example/docs, explicit shared-workspace
  attestation gate, and per-handle current/retained scheduler-fact join.
- Refiner: not needed. Manager correction 1/3 added direct causal coverage for
  a retained failed handle beside a different current handle and for withholding
  all-complete wording when any accepted handle lacks current/retained evidence.
- Independent-review correction 2/3 makes append order break equal timestamp
  ties for retained per-handle facts and covers same-second `RUNNING` then
  `FAILED` observations followed by pruned accounting.
- Pre-submit gate: passed. `make validate-pr` completed with Ruff, Pyright,
  2,687 default tests, 157 config-extra tests with 3 expected skips, and source/
  wheel build. `make test-summary` passed 2,844 tests with 3 expected skips.
- Independent review: passed after correction 2/3. The single review found
  equal-timestamp retained fact ordering; append-order tie-breaking and the
  same-second prune test close that finding. Manager-local correction review and
  fresh full validation found no remaining blocker.
- Blocker corrections: 2/3.
- PR and merge: [#261](https://github.com/samcantrill/loom/pull/261)
  squash-merged into `develop` as `0bee2332bf53d610cf112193e6a42fe5915c2078`.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Queue SLURM adapter/controller and CLI; existing live-manifest operation/snapshot seams; queue/SLURM docs; deterministic service-less operations example. |
| Tests added or updated | Prepared proof rejection/proven matrix; same-second observe-then-prune retained failure; per-handle current-over-retained join; retained failure beside a different current handle; missing-handle all-complete guard; existing controller, CLI, live-model, and example journey coverage updated for explicit proof. |
| Validated revision/tree state and evidence | Pre-rebase candidate `b1bfa20`: focused integration 20 passed with Ruff/Pyright; `make validate-pr` passed 2,687 default and 157 config-extra tests with 3 expected skips plus build; final `make test-summary` passed 2,844 tests with 3 skips. One prior summary attempt hit the existing PID-marker empty-read race; the exact test passed twice and an unchanged full summary rerun passed. The final PR and squash-merge tree changed only unrelated Stage 29 and Stage 32 roadmap metadata after that evidence. |
| Validation-relevant changes after evidence | None. Rebase input was Stage 29 roadmap documentation only; this completion/review record is documentation only. Source, tests, dependencies, build, and validation configuration are unchanged. |
| PR, review, and merge | Independent expanded review passed after correction 2/3; [#261](https://github.com/samcantrill/loom/pull/261) was squash-merged into `develop` as `0bee2332bf53d610cf112193e6a42fe5915c2078`. |
| Residual risk and cleanup | Fake Slurm cannot certify site accounting visibility or shared-mount policy beyond explicit project evidence. Phase 2 and Phase 3 worktrees and local branches were removed; GitHub removed the Phase 3 remote branch during merge and Phase 2 had no remote branch. |
