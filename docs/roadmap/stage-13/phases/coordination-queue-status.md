# Phase 4 Execution Plan: Coordination, Queue Dispatch, And Status

## Metadata

- Status: merged
- Feature focus: Deterministic Sweeps
- PR title:
  `Deterministic Sweeps - Phase 4: Coordination, Queue Dispatch, And Status`
- Branch: `codex/coordination-queue-status`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/coordination-queue-status`
- Phase execution plan path:
  `docs/roadmap/stage-13/phases/coordination-queue-status.md`
- Full plan: `docs/roadmap/stage-13/implementation-plan.md`
- Source phase: Phase 4, `coordination-queue-status`
- Stack predecessor: none; Phases 1 through 3 are merged into `develop`.
- Base branch:
  `origin/develop` at `8854cb7fd727de2ae9c0fe4fd9966fb27ad48514`
- Target branch: `develop`
- PR: [#154](https://github.com/samcantrill/loom/pull/154)
- Merge eligibility: complete; root phase PR targeted `develop`, validation,
  automated review, CI, and target-branch verification passed before merge.
- Workflow path: expanded path
- Successor dependency notes: Phase 5 should branch from
  `codex/coordination-queue-status` if Phase 4 is `pr_open` or `approved` but
  not merged; otherwise Phase 5 should branch from updated `develop`.
- Plan quality gate: passed in the implementation plan on 2026-05-14.
- Plan quality gate loop budget: implementation-plan review, refinement, and
  confirmation were used before Phase 1; no blocking findings remain.
- Draft pass: complete for this phase execution plan.
- Refine pass: complete for this expanded-path phase; the artifact is final for
  implementation.
- Setup limitations: the original control checkout has unrelated dirty and
  untracked files; phase work is isolated in the worktree above.
- Blockers: none.

## Objective

Connect planned sweeps to cross-run coordination records, queue whole-run trial
submission, and a sweep status read model. The phase must keep queue dispatch as
enqueue-only behavior, keep coordination as additional indexing facts, and let
ordinary run lifecycle remain the source of run truth.

## Full-Plan Context

Phases 1 and 2 established finite sweep plans, manifests, dispatch records, and
stable trial run URIs. Phase 3 added cooperative early stop and direct
sequential dispatch through `PipelineRunner`. Phase 4 now adds the coordination
and queue-facing surfaces that Phase 5 CLI/status commands can call.

Future-phase work remains out of scope: no `loom sweep` CLI, no collection API,
no controller loop ownership, no scheduled-trial cancellation, no bounded local
concurrency, no SLURM per-trial submission policy, and no metric or artifact
payload extraction.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 3 PR
  [#153](https://github.com/samcantrill/loom/pull/153) was squash-merged into
  `develop` and recorded by `8854cb7`.
- Why this base branch is correct: Phase 4 depends on Phase 3 direct dispatch,
  early-stop lifecycle metadata, and final Phase 3 merge metadata now present on
  `develop`.
- Retarget/rebase plan after predecessor merge: none for this root phase.
- Branch cleanup constraints: this branch can be deleted after merge only if no
  successor phase still targets or branches from it.

## Source Phase Summary

- Goal: implement coordination projection helpers, queue-backed finite-trial
  enqueue behavior, and status aggregation from manifests plus available run,
  queue, and coordination read models.
- Required scope: `SweepIdentity` and `TrialReference` projection when a
  `WorkspaceCoordinationStore` is supplied, queue enqueue request construction
  over Phase 1 dispatch records and Phase 2 trial run URIs, queue submission
  result records, and status models that derive counts including
  `early_stopped`.
- Required checkpoints: in-memory and SQLite coordination stores receive sweep
  and trial records; queue dispatch enqueues one whole-run item per finite
  trial; status aggregation derives pending/queued/running/succeeded/failed/
  cancelled/early-stopped trial summaries without controlling the queue.
- Acceptance criteria: focused unit, contract, and integration evidence covers
  coordination projection, queue enqueue shape, queue progress readback, status
  counts, early-stop derivation, and import boundaries.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/pipeline/stores/coordination.py` already defines
    `WorkspaceCoordinationStore`, `SweepIdentity`, `TrialReference`, and
    `TrialState`; stores only create sweeps and upsert trial references.
  - `src/loom/pipeline/stores/sqlite_coordination.py` and
    `tests/support/authority_stores.py` already satisfy the coordination
    protocol and can be used for coverage.
  - `src/loom/queue/service.py` owns `QueueEnqueueRequest` and
    `QueueService.enqueue`; the service must be running before enqueue.
  - `src/loom/queue/models.py` owns `QueueItem`, `RunIntent`, and
    `QueueItemStatus`; queue item IDs are stricter than sweep IDs, so the sweep
    adapter needs a stable safe ID helper.
  - `src/loom/pipeline/sweep/dispatch.py` already owns neutral dispatch
    intents and direct-dispatch results; queue dispatch should extend this
    boundary rather than import queue internals elsewhere.
  - `src/loom/pipeline/sweep/__init__.py` and package tests lock public sweep
    exports.
- Existing tests or harness behavior:
  - Sweep unit and contract tests cover dispatch record round-trips, direct
    dispatch, package exports, and manifest compatibility.
  - Queue service/client tests cover enqueue, readback, cancellation, and
    stopped-service rejection.
  - Workspace coordination contract tests cover in-memory, SQLite, and service
    coordination stores.
- Import-boundary or dependency constraints:
  - Keep sweep code domain-neutral and dependency-light.
  - Queue may remain independent of sweep internals; sweep may import queue
    public records for adapter construction but must not own controller loops.
  - Do not introduce optimizer, metric, project-code, SLURM policy, or remote
    service dependencies.

## In-Scope Work

- Add `src/loom/pipeline/sweep/coordination.py` with helper functions to:
  - ensure workspace and sweep identities when a coordination store is supplied;
  - project planned trials into `TrialReference` records;
  - map run or queue status to coordination `TrialState`;
  - update coordination records after direct or queue dispatch outcomes.
- Extend direct dispatch with optional coordination projection parameters while
  preserving existing behavior when no coordination store is supplied.
- Add queue dispatch records and `enqueue_sweep_trials(...)` in the sweep
  dispatch boundary:
  - consume `SweepPlan` and `SweepDispatchRequest` values;
  - build one `RunRequest` per trial with the Phase 3 helper;
  - create a stable safe queue item ID per trial;
  - enqueue whole-run `QueueEnqueueRequest` values through `QueueService`;
  - continue after per-trial enqueue failures and return submission results.
- Add `src/loom/pipeline/sweep/status.py` with status records and aggregation
  helpers that join plan trials with optional run statuses, queue items, and
  coordination trial references.
- Export the new public sweep records/helpers through
  `loom.pipeline.sweep.__init__`.
- Add focused unit, contract, integration, and package tests for coordination,
  queue dispatch, and status aggregation.

## Out-of-Scope Work

- CLI commands, CLI output formatting, or user docs beyond phase artifact notes.
- Queue service/controller draining, polling, foreground loops, or cancellation.
- Bounded local concurrency or distributed sweep controllers.
- SLURM per-trial submission semantics.
- Retry/rerun/filter policy.
- Collection of artifact refs or extraction diagnostics beyond existing Phase 1
  contracts.
- New core run, stage, queue, or coordination lifecycle states.

## Assumptions

- `WorkspaceCoordinationStore.create_workspace` and `create_sweep` can be
  treated as ensure-style operations by ignoring duplicate-identity errors.
- `TrialReference.revision` may use an external deterministic revision token
  when the source state is a run status record or queue item rather than an
  authority snapshot.
- Queue `RunIntent.request` only needs a plain-data snapshot sufficient for
  later CLI/controller handoff; Phase 4 does not execute queued items.
- `RunStatus.CANCELLED` plus `reason_code=early_stop` or
  `metadata.reason.code=early_stop` is the canonical early-stopped derivation.

## Scope Contract

- Coordination helpers must be optional and side-effect only when a store is
  explicitly provided.
- Queue dispatch must call public queue service APIs and must not inspect or
  mutate queue repository internals.
- Queue dispatch must enqueue finite planned trials and return submission
  records; it must not drain, poll, cancel, or complete queue items.
- Status aggregation must read supplied state snapshots and must not mutate run
  stores, queue services, or coordination stores.
- Run lifecycle remains authoritative for run outcomes; queue and coordination
  facts are presentation/index inputs.

## Design Impact

- Maintainability: queue and coordination behavior stay in sweep-specific
  adapter/read-model modules with narrow public helpers.
- Extensibility: later distributed controllers can reuse the coordination
  projection and queue item metadata without changing manifests.
- Domain neutrality: status and queue metadata contain sweep/trial identifiers,
  lifecycle states, run URIs, and plain proposal metadata only.
- Source-tree boundaries: queue owns queue lifecycle, stores own coordination,
  and sweep owns orchestration projections over its own manifests.

## Future Compatibility

- Phase 5 CLI can call queue dispatch and status helpers directly without
  parsing manifests or queue records itself.
- Future reliability work can layer retry/timeout policy over queue and
  coordination facts without changing trial manifests.
- Future adaptive providers can reuse coordination projection for additional
  generated trials once provider policy exists.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add queue controller behavior to sweep dispatch | The approved phase keeps queue service/controller ownership outside sweep. |
| Treat coordination state as run lifecycle truth | Coordination records are cross-run indexes; run stores remain authoritative for ordinary run lifecycle. |
| Store raw `RunRequest` objects in queue records | Queue records require plain data and should remain durable, versioned records. |
| Add a `QUEUED` coordination state | `TrialState` is already public; queue status can be presented by the sweep status read model without schema churn. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Queue run request snapshot is intentionally plain and limited | Phase 4 submits queue intent but does not own queued execution | Phase 5 CLI or a future queue controller needs richer durable launch inputs |
| Coordination revisions for local status projections use external tokens | Current coordination protocol requires a revision object but run/queue read models may not expose a backend revision | Authority snapshots expose reusable revision tokens for sweep trial projection |

## Reviewability

- Expected PR size and shape: medium, with one coordination module, queue
  dispatch extensions, one status module, and focused tests.
- Files and areas to inspect:
  - `src/loom/pipeline/sweep/coordination.py`
  - `src/loom/pipeline/sweep/dispatch.py`
  - `src/loom/pipeline/sweep/status.py`
  - `src/loom/pipeline/sweep/__init__.py`
  - queue and coordination tests under `tests/unit`, `tests/contracts`, and
    `tests/integration`
- Review focus:
  - queue remains submit-only;
  - status aggregation is read-only;
  - early-stop derivation uses structured reason metadata;
  - coordination writes are optional and idempotent enough for repeated calls.

## Suite Obligations

| Suite | Status | Phase obligation |
| --- | --- | --- |
| Package/import-boundary | required | Update sweep public exports and verify queue does not import sweep internals. |
| Unit | required | Cover coordination helpers, queue enqueue shape, status aggregation, and failure continuation. |
| Contract | required | Cover new queue dispatch/status record serialization and coordination state mapping. |
| Integration | required | Cover SQLite coordination projection and queue service enqueue/readback. |
| E2E | deferred | Phase 5 owns user-facing `loom sweep` CLI workflow. |
| Config-extra | unchanged | Run via final `make validate-pr` and `make test-summary`. |

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/sweep tests/contracts/test_sweep_dispatch_contract.py tests/contracts/test_workspace_coordination_contract.py tests/integration/pipeline/sweep
uv run pytest tests/unit/loom/queue tests/integration/queue
uv run ruff check src/loom/pipeline/sweep tests/unit/loom/pipeline/sweep tests/contracts/test_sweep_dispatch_contract.py tests/integration/pipeline/sweep
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For Implementation

- Safe implementation slices: coordination helpers first, queue dispatch second,
  status aggregation third, public exports and tests last.
- Decisions not to revisit: no queue draining, no CLI, no new lifecycle states,
  no metric/artifact extraction, no broad queue model changes.
- Conditions that require stopping for the manager: queue whole-run intent
  cannot carry stable sweep/trial metadata without queue schema changes;
  coordination stores cannot represent trial references for planned trials.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted validation and final
  PR gates passed after the implementation slice.
- PR review: used by the managing agent before merge. The review found that
  queued trial config snapshots could still carry nested frozen mappings when
  assembled from structured run requests.
- Blocker resolution: 1/3 used for the scoped queue snapshot thawing fix; final
  PR gates passed after the fix.

## Completion Notes

- Draft plan: completed locally on 2026-05-14.
- Final phase execution plan: completed locally on 2026-05-14.
- Implementation summary: Added sweep coordination projection helpers, optional
  direct/queue dispatch coordination updates, queue-backed finite-trial
  submission records and enqueue helpers, read-only sweep status aggregation,
  and public sweep exports. Queue service enqueue now thaws nested structured
  request fields before building durable queue records so whole-run trial
  intents can carry structured metadata.
- Implementation validation: Targeted sweep/queue/contract/integration/package
  tests passed (`42 passed`); broader queue and coordination suites passed
  (`74 passed`); targeted Ruff passed; Pyright passed; after the scoped queue
  snapshot thawing fix, `make validate-pr` passed with default harness `1527
  passed, 26 skipped, 18 deselected`, config-extra `438 passed, 1564
  deselected`, and build success; `make test-summary` passed and wrote
  `build/test-summary.md`.
- Refinement summary: Not needed; the post-review code change used the
  blocker-resolution budget instead of the optional implementation refinement
  pass.
- PR review summary: Managing-agent review completed before merge; the only
  blocking finding was nested frozen mapping leakage in queued config snapshots,
  fixed by thawing queue dispatch config and metadata snapshots before durable
  queue records are built.
- Blocker-resolution summary: 1/3 used for the queue snapshot thawing fix.
- PR preparation: PR body drafted in
  `docs/roadmap/stage-13/phases/coordination-queue-status-pr-body.md`;
  [#154](https://github.com/samcantrill/loom/pull/154) merged into `develop`.
  Pre-merge verification confirmed `baseRefName=develop`,
  `headRefName=codex/coordination-queue-status`, `state=OPEN`, clean merge
  state, head `dab78594d6269a830be1de344559e48022071728`, and GitHub CI
  `checks` success.
- Merge record: squash merged through the GitHub API on 2026-05-14 as
  `b00675dc319282973345a5915e99c2256f72e21e`.
- Stack maintenance: no successor branch depended on
  `codex/coordination-queue-status`; the remote phase branch was deleted after
  merge. Phase 5 should branch from updated `develop`.
- Remaining blockers: none.
