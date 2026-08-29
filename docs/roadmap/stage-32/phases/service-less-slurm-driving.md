# Phase 2 Execution Plan: Service-Less SLURM Driving

## Metadata

- Status: planned
- Roadmap stage and phase: Stage 32, Phase 2
- Manifest: docs/roadmap/stage-32/implementation-plan.md
- Branch: agent/stage-32-p2-service-less-slurm-driving
- Worktree root and path: use the manifest-recorded root;
  `<root>/stage-32-p2-service-less-slurm-driving`
- Base revision: current `origin/develop` after Phase 1 is remotely merged
- PR target: develop
- PR title: `Stage 32 phase 2: add service-less SLURM driving`
- Dependencies: Stage 32 Phase 1 remotely merged; existing whole-run Slurm planning/live submission/status and delegated queue controller
- Requirements and decisions: FR-6 through FR-11; FQ-3 through FQ-5; DQ-4 through DQ-7
- Workflow path: expanded; external-call uncertainty and multi-owner terminal joins are fixed by the stage plan
- Blockers: Phase 1 merge

## Objective And Context

- Vertical outcome: an operator runs one bounded foreground command to submit
  many prepared ordinary runs to Slurm, exits without waiting for completion,
  and later reruns it to reconcile completed/active/unknown work and submit the
  remaining queue without duplicate scheduler jobs or false scientific success.
- Earlier dependency: Phase 1 supplies canonical ordinary admissions and
  bounded queue reads. Existing Slurm code supplies single-job and `afterok`
  scripts, manifests, job status, cancellation, and command fakes.
- Later work explicitly out of scope: persistent Stage 29 managed scheduling,
  dynamic intermittent stage driving, remote queries/stores/logs, arrays,
  allocation-fed agents, and webhook delivery durability.

## Current Source And Harness

- Relevant files and symbols: `QueueController.run_cycle`/`drain_foreground`,
  delegated pool mode, `SlurmQueueDispatchAdapter`, Slurm dry/live planning,
  `submit_single_job_slurm`, `submit_afterok_slurm`, live manifests/status,
  `operation_marker`, discovery command-runner methods, run authority/status,
  and queue CLI formatting.
- Existing tests and seams: delegated foreground handoff/restart, fake
  `sbatch`/`squeue`/`sacct`/`scancel`, single/afterok partial submission, Stage 29
  ambiguous-operation discovery, prepared-run continuation/stage-job workers,
  and fake shared-filesystem examples.
- Import, dependency, or harness constraints: optional Slurm remains CLI-command
  based; no Python scheduler dependency, network requirement, root dependency,
  or queue import into pipeline/core modules.

## Scope

In scope:

- Define one closed prepared-run delegated launch contract referencing an exact
  run-local planned submission and selecting existing `single_job` or `afterok`
  mode. Validate the run URI, mode, submission identity/digest, manifest/scripts,
  authority/store capability, and compute-visible paths before any scheduler
  call.
- Reuse the existing whole-run Slurm submitters and manifests. The queue dispatch
  handle references the retained submitted operation/manifest and does not copy
  the logical job list into a second durable inventory.
- Persist exact per-scheduler-call operation identity/digest and include its
  bounded marker in scheduler-visible comment metadata. Reuse discovery over
  live and retained accounting rows when a call remains `SUBMITTING`/unknown or
  when process loss occurs before the returned handle is durably retained.
- For `afterok`, retain each accepted logical job before the next call. On
  restart, preserve known handles and dependencies; submit a later logical job
  only when its own call was proven absent and every scheduler dependency has an
  exact handle. Unknown/multiple matches block that submission branch.
- Add a bounded delegated-driver operation and foreground CLI. Each cycle
  reconciles a configured bounded window of active/unknown items and dispatches
  at most the existing protected per-cycle submission bound. A durable delegated
  handoff does not consume Loom-managed resource capacity or stop independent
  queued handoffs.
- Support one-cycle and until-quiescent behavior. Quiescent means no immediately
  reconcilable or submit-ready local transition; the command does not remain
  alive to await Slurm completion. Return counts and stable safe diagnostics in
  text/JSON.
- Reconcile queue outcome from distinct facts. Authority terminal success/fail/
  cancellation wins scientific lifecycle. Scheduler terminal failure may close
  dispatch as failed with its own reason. Scheduler `COMPLETED` with nonterminal
  or missing Loom result remains settling/unknown and never becomes success.
  Missing current scheduler facts fall back to retained snapshots; no terminal
  Loom fact plus no retained scheduler fact is `UNKNOWN`.
- Keep all artifacts, logs, worker results, and run state in project-selected
  stores. Require shared/compute-visible local paths for the built-in route and
  expose locations/references only. Do not upload, materialize, copy, or proxy
  their contents.
- Add one project-code example generating several ordinary runs with a mix of
  single-job and `afterok`, running a fake foreground cycle, simulating driver
  loss and old completion, and reopening. Add manual HPC setup covering login
  policy, shared paths, environment availability, submission bounds, `sacct`
  retention, process exit, resume, cancellation, and limitations.
- Update Stage 29/queue/Slurm/reporting guidance: Stage 29 service roles are for
  hosts that permit them; this path requires none. Managed reporters/webhooks
  stay coordinator-side; service-less compute work has no promised real-time
  external reporting.

Out of scope:

- Arbitrary raw-script recovery beyond the prepared-run contract, a new generic
  external-scheduler protocol, or importing Stage 29 bootstrap/assignment state.
- Dynamic stage readiness after inspecting outputs, cross-run dependencies,
  job arrays, automatic mode choice/fallback, scheduler retry policy, or
  auto-resubmission of unknown operations.
- Treating scheduler completion as artifact/result validation, force-closing
  unknown work, or deleting old manifests/job metadata.
- Long-running login-node services, self-resubmitting controller jobs, SSH,
  remote operator endpoints, coordinator HA, or service-manager packaging.
- Remote artifact stores, log aggregation/content retrieval, reporter outbox,
  or compute-node Internet access.

Assumptions:

- The submission host exposes `sbatch`, `squeue`, `sacct`, and `scancel`; compute
  nodes can run the prepared Loom environment and see every configured path.
- Static `afterok` dependencies are known at planning time. Output-dependent
  dynamic logic runs inside one whole-run job or uses a separately deployed
  persistent coordinator.
- Slurm accounting may be delayed, unavailable, or eventually pruned; durable
  Loom result state is therefore primary for old successful runs.

## Fixed Contracts And Private Discretion

- Observable behavior: foreground submission continues across independent
  delegated handoffs, exits when locally quiescent, resumes from the same queue
  and run manifests, and does not resubmit ambiguous operations. Both Slurm modes
  remain explicit project choices.
- Public or durable shapes: prepared-run launch contract tag/mode/reference,
  scheduler operation marker/state where missing, queue dispatch-handle
  reference, bounded driver request/result and CLI JSON. Existing run/manifest
  schemas remain owners and change only where exact marker recovery requires it.
- Trust and failure boundaries: authored configuration cannot inject raw
  scheduler commands/credentials through the new contract; protected
  preparation supplies scripts/options; scheduler output is bounded and parsed;
  authority state cannot be fabricated from Slurm.
- Cross-phase contracts: consumes Phase 1 submission identity/digest and returns
  canonical queue item IDs. A later Stage 34 query may join these typed facts but
  cannot reinterpret them.
- Reproducibility and compatibility: exact planned submission/operation digests,
  stable markers, retained partial manifests, no blind call replay, and no
  change to direct local or Stage 29 managed execution.
- Private choices the executor may simplify: adapter/helper names, driver CLI
  spelling below documented behavior, page/window sizes within protected bounds,
  internal manifest-reference representation, and safe summary wording.

## Proportionality

- Existing seam reused: delegated pool/controller, prepared-run Slurm planning,
  live manifests, fakeable command runner, operation comments/discovery, run
  authority, and worker-written results.
- Material additions and current justification: prepared-run queue composition
  connects existing owners; bounded continue-after-handoff enables throughput;
  marker recovery closes the scheduler atomicity gap; authority join prevents
  false success.
- Optional hardening and future capability deferred: generic external scheduler,
  dynamic controller, arrays, remote data/query, retries, HA, and durable
  notifications.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| One scheduler call has one stable operation identity | run-local Slurm submission owner | crash/timeout around `sbatch` | duplicate job | causal call-boundary and discovery tests |
| One logical job inventory exists | existing Slurm live manifest/submitted operation | queue handoff persistence | divergent job status/cancel | queue handle contains only manifest reference |
| Scheduler dependencies use exact retained handles | `afterok` submitter/manifest | partial submission and restart | wrong dependency or duplicate downstream job | diamond partial-restart test |
| Driver work is bounded and delegated handoff does not consume managed capacity | queue controller/repository | thousands of active Slurm jobs | one job per invocation or unbounded scan | many-active/many-queued cycle test |
| Scientific success comes only from run authority | per-run authority | Slurm `COMPLETED` with missing result | false success | conflicting-axis status matrix |
| Old work remains inspectable without live accounting when Loom terminal state exists | run store/authority | `sacct` retention expiry | completed experiments become unknown | terminal-run/no-accounting test |
| Bytes remain project-owned | configured run/artifact stores | inaccessible compute path | missing result or invented transfer | preflight and path/reference assertions |

## Implementation Slices

1. Add and validate the closed prepared-run delegated launch composition for
   single-job and `afterok`, referencing existing run-local plans/manifests.
2. Add stable markers and restart reconciliation to the whole-run Slurm call
   boundaries, including partial `afterok` continuation without blind replay.
3. Compose the queue adapter/dispatch-handle reference and truthful
   authority/scheduler inspection outcomes.
4. Add bounded foreground driver cycles/CLI that continue after delegated
   handoff and exit at local quiescence.
5. Add the fake mixed-mode crash/old-job journey, manual HPC instructions, and
   deployment/reporting/current-versus-deferred documentation.
6. Run targeted queue/Slurm/authority/e2e checks and full repository gates.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Optional Slurm imports and queue public values stay intentional | Existing package/public import gates. |
| Unit | required | Contract validation, mode, marker, driver bounds, status mapping | Closed field sets and owner-axis matrix. |
| Contract | required | Manifest/dispatch references and fake command runner | No duplicate job inventory; exact command/comment shape. |
| Integration | required | Both modes, partial submission, crash discovery, restart | One/zero/multiple marker matches and old completed run. |
| E2E / opt-in | required fake/manual live | Actual foreground CLI and project paths | Fake subprocess journey by default; real cluster checklist opt-in. |

Targeted commands:

    uv run pytest tests/unit/loom/queue/test_controller.py tests/unit/loom/queue/test_slurm_adapter.py
    uv run pytest tests/integration/queue/test_delegated_slurm_controller.py tests/integration/queue/test_slurm_ready_stage.py
    uv run pytest tests/integration/pipeline/test_slurm_live_submission.py tests/e2e/test_queue_cli.py
    uv run ruff check src/loom/queue src/loom/pipeline/executors/slurm tests/unit/loom/queue tests/integration/queue
    uv run pyright src/loom/queue src/loom/pipeline/executors/slurm tests/unit/loom/queue tests/integration/queue

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: two job inventories, blind replay after handle loss, continuing an
  `afterok` graph without exact upstream handles, unbounded reconciliation,
  closing queue success from scheduler state, inaccessible shared paths, or
  accidentally requiring the Stage 29 endpoint.
- Review focus: persisted-before-call ordering, stable marker uniqueness and
  discovery bounds, manifest reference ownership, partial DAG causality,
  authority-first terminal join, delegated capacity semantics, and no network/
  credential/byte relay.
- Stop if: the adapter needs a generic job-group abstraction, Stage 29 bootstrap
  state, dynamic readiness, arbitrary commands, remote storage, automatic
  unknown recovery, or a new authority lifecycle. Reopen planning instead.
- Accepted debt and revisit trigger: shared filesystem, static DAG, fake default
  validation, and possibly unknown old incomplete work; revisit with a concrete
  non-shared, dynamic, or live-site failure.

## Executor Handoff

- Read section range: `Objective And Context` through `Risks, Review, And Stops`.
- Safe implementation slices: the six slices above, confined to delegated queue
  driving, existing whole-run Slurm submission/status seams, focused docs/tests,
  and phase metadata.
- Decisions not to revisit: no persistent service; explicit single-job/afterok;
  existing manifest owns jobs; persist/mark/discover, never blind retry;
  authority owns scientific outcome; shared project stores own bytes; no remote
  query/reporting protocol.
- Conditions requiring manager action: inability to reference existing manifests
  without copying inventory, scheduler lacking exact marker discovery, need for
  dynamic readiness or data transfer, or any public/durable behavior outside the
  fixed plan.

## Workflow State

- Manager preparation: pending Phase 1 merge and exact implementation base.
- Expanded planning: stage-level minimum design is complete; one phase-plan
  refinement is permitted only for a concrete external-call ownership ambiguity.
- Implementation: pending.
- Refiner: not needed.
- Pre-submit gate: pending.
- Independent review: expected because scheduler-call uncertainty and
  authority/scheduler terminal joins remain material external boundaries.
- Blocker corrections: 0/3.
- PR and merge: pending.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
