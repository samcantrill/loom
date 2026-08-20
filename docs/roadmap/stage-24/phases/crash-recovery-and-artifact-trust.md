# Phase 2 Execution Plan: Crash Recovery And Artifact Trust

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 24, Phase 2
- Manifest: `docs/roadmap/stage-24/implementation-plan.md`
- Branch: `agent/stage-24-p2-crash-recovery-and-artifact-trust`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-24-p2-crash-recovery-and-artifact-trust`
- Base revision: current `origin/develop` after Phase 1 is remotely merged
- PR target: `develop`
- PR title: `Operational Lifecycle Validation - Phase 2: Crash Recovery And Artifact Trust`
- Dependencies: Stage 24 Phase 1 remotely merged with its cancellation,
  subprocess cleanup, and process-test support contracts intact
- Workflow path: fast; refine only for a qualified authority/recovery or durable-
  commit blocker
- Blockers: Phase 1 not yet merged

## Objective And Context

- Vertical outcome: after Loom or its authority becomes unavailable, incomplete
  work cannot become reusable success; live ownership is respected, abandoned
  work is explicitly classified, resume creates a distinct safe attempt, and
  corrupted artifact bytes invalidate only the dependency branch they affect.
- Earlier dependency: Phase 1 settles graceful interruption and supplies safe,
  bounded test-owned process-tree orchestration. Existing authority recovery
  transitions, run locking, planner invalidation, checksums, output commit, and
  service authority provide the production seams.
- Later work explicitly out of scope: process reattachment, automatic service
  restart, public repair commands, generic scheduling, external runtime
  acceptance, notification/telemetry, and a broad network/partition matrix.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/pipeline/transition_policy.py` already permits recovery from run
    `RUNNING`/`SUBMITTED` to `INTERRUPTED` and active stage to `STALE` or
    `PENDING`.
  - `src/loom/pipeline/execution/runner.py` and
    `authority_adapter.py` own locked run startup, attempt allocation, active
    stage mutation, output commit, finalization, and resume orchestration.
  - Authority repositories/services own active leases, guarded transitions,
    snapshots, recovery scans, and fail-closed mutation behavior.
  - SQLite authority rejects a second active controller lease and permits a new
    one after expiry. The local service authority currently allocates a second
    live controller, so cross-backend ownership parity is a demonstrated gap.
  - `AuthorityBackedSerialRunStore` acquires a fixed 24-hour controller lease
    but does not renew it, although `PerRunAuthorityStore.renew_lease` exists;
    stage-attempt leases already have private renewal during execution.
  - Resume planning already rejects reuse of old `RUNNING` stages and uses
    checksum mismatch to produce an explanatory rerun action.
  - Artifact stores and run-store output/index writers already own payload,
    checksum, outputs, and commit consistency.
- Existing tests and seams:
  - Runner/store tests cover deterministic recovery transitions, old active
    state, commit failure, fake authority loss, checksum mismatch, downstream
    invalidation, and valid public resume separately.
  - `LocalAuthorityService` supplies a real local service process boundary.
  - Phase 1 supplies safe process-tree start/synchronize/terminate/inspect
    helpers and a blocking stage marker.
  - Current public e2e resume has a small two-stage pipeline; a branch-shaped
    domain-neutral fixture may be added or composed from existing counter and
    consumer stages.
- Import, dependency, or harness constraints: no production crash hook,
  `psutil`, network dependency, mutable global process registry, or new public
  recovery command. Use authority/lock facts—not PID liveness guesses—to
  authorize recovery.

## Scope

In scope:

- Add a real hard-loss scenario that launches a Loom coordinator and worker in
  a fixture-owned containment boundary, waits until the stage is durably active,
  then kills all test-owned processes without allowing Loom cleanup code to run.
- Inspect the run before recovery and prove it is not successful, has no
  committed/indexed output, starts no downstream stage, and cannot be resumed or
  stolen while authoritative ownership remains live.
- Make the local service authority enforce the existing controller-lease
  contract: reject a second unexpired controller and permit a new controller
  only after deterministic expiry, while retaining the expired lease for scan.
- Add private controller-lease renewal for the lifetime of an authority-backed
  runner lock. Renewal stops on release, stale/foreign renewal cannot restore
  ownership, and a renewal error is surfaced before later authoritative work or
  output commit. Do not extend the public run-lock protocol.
- On explicit resume, acquire the new exclusive controller lease, scan under
  that authority, and require recovery facts for the old controller and every
  incomplete active attempt. Then write the run `INTERRUPTED` and active stages
  `STALE` with recovery intent and append matching events through the existing
  audit surface before planning or attempt 2. Retain them after later success.
- Prove attempt 2 reruns the interrupted stage, produces the only reusable
  output, allows downstream work afterward, and does not rewrite or silently
  erase the prior attempt's diagnostic facts.
- Stop the real local authority service after a blocking stage is active and
  before output commit. Prove failure is closed at the authority boundary: no
  authoritative success/output index, no dependent start, no valid-lease
  stealing, and useful failure/diagnostic evidence.
- Run a public branch-shaped pipeline successfully, mutate one checksummed
  artifact payload without changing valid metadata, resume, and assert checksum
  mismatch, producer/consumer rerun, independent-branch reuse, attempt counts,
  repaired payload, outputs, and run artifact index.
- Reconcile execution, state, reliability, resume, artifacts, run-store,
  testing, and roadmap documentation with the implemented behavior and the
  Stage 26 external-acceptance boundary.

Out of scope:

- Killing or adopting foreign processes by stored PID; proving cleanup after
  total machine loss; reattaching to a surviving child; daemon/service-manager
  implementation; automatic lease stealing; silent state repair; a new
  `loom recover`/`repair-state` command; new status, attempt, audit, or schema
  shape.
- Retrying ambiguous authority writes, simulating every network fault, testing
  database corruption, changing automatic retry policy, or treating malformed
  serialized state like a checksum mismatch.
- Real Docker, Apptainer, SLURM, GPU, scheduler accounting, notification, remote
  storage, or production deployment tests. Stage 26 retains those profiles.

Assumptions:

- SQLite already distinguishes a live controller from an expired one; Phase 2
  brings the local service backend to that contract and tests both. Recovery
  still stops if an incomplete stage retains a live/ambiguous lease.
- Controller renewal can use a private runner/adapter helper and test-only
  timing controls. If safe renewal requires a public protocol or schema, stop.
- Existing transition/audit surfaces can retain the interruption/stale fact
  before resume advances the same run. If a new durable schema is unavoidable,
  stop rather than silently adding it.
- The public resume path already treats a locally readable checksum mismatch as
  rerunnable stale work. Structurally corrupt JSON continues to fail clearly and
  is not broadened into automatic repair.
- The service-loss test may use an explicit barrier or controlled blocking stage
  to place loss before commit; arbitrary sleeps are not an acceptable boundary.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - An uncatchable kill cannot create immediate fictional cancellation,
    interruption, or failure. Before recovery, old active state is inspectable
    but non-reusable and protected by live authority.
  - While the old owner is authoritatively live or unknown, conflicting resume
    fails closed. Process/PID absence alone never permits mutation.
  - A healthy controller remains live beyond its initial TTL through renewal;
    renewal stops at release/crash and a renewal failure cannot be ignored.
  - Successful exclusive controller acquisition is necessary but not sufficient:
    recovery scan facts must also cover the expired old controller and each
    incomplete active attempt.
  - The prior run then records `INTERRUPTED`, incomplete active stages record
    `STALE`, and matching audit events precede planning, attempt allocation, and
    return to `RUNNING`.
  - The prior attempt never contributes a successful output/index entry. A new
    attempt must execute, validate, and commit normally before success.
  - Authority loss before commit cannot be represented as authoritative success
    even if the project stage returned or wrote local scratch bytes.
  - Valid metadata plus payload checksum mismatch reruns the affected branch and
    preserves reusable independent work; malformed durable state still errors.
- Public or durable shapes: no new shape. Use current statuses, recovery
  transitions, attempts, audit/events, failure/diagnostic facts, output records,
  checksums, artifact index, and planner reason codes.
- Trust and failure boundaries: authority/lock owns recovery permission;
  coordinator cannot infer ownership from PID; output commit owns success;
  artifact store owns byte validation; planner owns dependency invalidation.
- Cross-phase contracts: completion establishes the Stage 24 lifecycle outcome
  table and hermetic operational tests for Stage 25 to preserve. Stage 26 may
  reuse the acceptance principles but owns external environment profiles.
- Reproducibility and compatibility: successful resume remains reusable;
  ordinary failed/cancelled resume behavior remains; unaffected artifact
  branches retain exact reuse; no additional process or network requirement is
  introduced to default user execution.
- Private choices the executor may simplify: exact containment mechanism,
  recovery helper nesting, transition evidence query, marker names, branch
  fixture topology, authority-loss synchronization, and test file placement.

## Proportionality

- Existing seam reused: run lock, authority active lease/recovery transitions,
  attempt history, planner old-`RUNNING`/checksum handling, output transaction,
  local authority service, CLI resume, and Phase 1 process fixture.
- Material additions and current justification: private controller renewal
  preserves live ownership; local-service exclusion gives backend parity; a
  small runner/adapter recovery path connects existing transitions/scans to
  resume; real process/service orchestration and one branch e2e connect owners.
- Optional hardening and future capability deferred: public recovery command,
  auto-repair, crash hook, daemon, reattachment, orphan scan, network-partition
  matrix, database corruption recovery, external-runtime execution, and
  artifact corruption combinations beyond one checksum/dependency case.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Hard loss cannot publish success or output. | Output commit plus authority | Coordinator/worker dies between active write and return/commit. | False reusable research result. | Kill after durable start; inspect status/output/index/downstream. |
| Live/unknown ownership prevents conflicting recovery. | Authority and run lock | Local service permits a conflict; runner controller TTL is not renewed. | Duplicate execution and split-brain mutation. | Renewal across initial TTL; SQLite/service reject before expiry and permit after loss/expiry. |
| Abandoned active work is explicitly classified before rerun. | Runner/authority recovery | Resume sees old `RUNNING`. | Silent history rewrite and ambiguous status. | Exclusive new lease plus matching scan facts; recovery events/transitions before attempt 2. |
| Attempt 2 cannot reuse attempt 1's incomplete artifacts. | Planner, attempt allocation, output commit | Scratch/output files survive crash. | Corrupt or partial data accepted. | Attempt/output/index assertions after resume. |
| Authority loss fails closed at commit. | Service authority mutation boundary | Service stops after stage return/start. | Local files imply success without authority. | Real service-loss barrier and no dependent start/index commit. |
| Checksum mismatch invalidates exactly the affected dependency branch. | Artifact store plus planner | Payload bytes changed behind valid ref/index. | Corrupt reuse or unnecessary whole-run recomputation. | Producer/consumer rerun, independent reuse, reason/payload/index proof. |
| Hard-loss fixture affects only owned processes. | Test support | Broad group/PID cleanup. | Host/CI process damage. | Validated ownership and `finally` cleanup inherited from Phase 1. |

## Implementation Slices

1. Add private controller renewal and close/contract-test local-service lease
   parity. Prove a healthy controller remains exclusive across its initial TTL,
   then add hard-loss pre-recovery assertions and live-owner conflict.
2. Wire explicit-resume recovery through exclusive acquisition, matching scan
   facts, existing transitions/events, planning, and attempts; prove durable
   `INTERRUPTED`/`STALE` evidence before attempt-2 success.
3. Add the real local authority service-loss barrier at the output-commit
   boundary and preserve fail-closed diagnostics/compatibility.
4. Add the public corrupt-artifact branch workflow with planner reason, attempt,
   dependency, payload, outputs, and artifact-index assertions.
5. Update canonical lifecycle/testing/resume/artifact documentation, run the
   targeted suites, then complete the full repository validation and summary.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required if imports change; otherwise existing gate | Recovery helpers stay private and imports cheap. | No new public surface or optional dependency. |
| Unit | required | Controller renewal/failure, live-owner refusal, recovery ordering, existing transition/attempt behavior. | Deterministic lease timing and exact status/event order without duplicating e2e. |
| Contract | required | SQLite and local-service controller lease exclusion/expiry agree. | Second live controller rejected; expired controller remains recoverable and replacement is fenced. |
| Integration | required | Hard loss and recovery; real local service-authority loss. | Ownership, transitions, attempts, output/index absence, diagnostics, dependent blocking. |
| E2E / opt-in | required default local e2e | Public corrupt-artifact resume and, if most coherent, the process-tree resume path. | Reason/action/attempt/payload/index/branch assertions. External runtimes deferred. |

Targeted commands:

    uv run pytest tests/unit/loom/pipeline/execution tests/unit/loom/pipeline/planning/test_resume.py
    uv run pytest tests/unit/loom/pipeline/stores/test_service_authority.py
    uv run pytest tests/contracts/test_authority_store_contract.py
    uv run pytest tests/integration/pipeline/test_subprocess_executor_integration.py
    uv run pytest tests/integration/pipeline/test_service_authority_backend.py
    uv run pytest tests/integration/pipeline/test_local_execution_resume.py
    uv run pytest tests/e2e/test_execution_lifecycle.py tests/e2e/test_local_pipeline_run.py

If the implementation places the scenarios in narrower new files, run those
paths explicitly in addition to the affected existing suites.

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: renewal thread lifecycle/error loss; treating dead PID or new
  lease alone as recovery proof; backend divergence; losing recovery events;
  allocating attempt 2 early; late output indexing; flaky service loss;
  corrupting metadata; broadening structural-corruption behavior.
- Review focus: renewal lifetime/fail-closed propagation, service/SQLite parity,
  matching recovery facts under the new controller, event ordering, attempt and
  output commit, live-owner refusal, PID containment, service loss, branch
  invalidation, and no new public/durable machinery.
- Stop if: renewal needs a public protocol or cannot surface loss before commit;
  recovery requires PID guessing/lease stealing; stores cannot retain recovery
  evidence without migration; resume overwrites attempt facts; service loss is
  not deterministic; or checksum semantics conflict across supported stores.
- Accepted debt and revisit trigger: no reattachment, automatic repair,
  machine-loss cleanup, database corruption recovery, or external runtime
  execution. Revisit only with an accepted owner/consumer in Stage 26 or later.

## Executor Handoff

- Read section range: this document in full, then planning `FR-6` through
  `FR-12`, behavior baseline, and `DQ-4` through `DQ-7`.
- Safe implementation slices: the five slices above in order after refreshing
  Phase 1's merged process-test helpers and lifecycle behavior.
- Decisions not to revisit: exclusive authority plus matching scan facts—not PID
  or lease acquisition alone—permit recovery; recovery events/transitions
  precede attempt 2; checksum corruption reruns one branch; malformed state
  fails; no new public recovery surface or external profile.
- Conditions requiring manager action: any stop condition, unavoidable schema
  or public API, inability to preserve prior attempt evidence, or a demonstrated
  backend-specific semantic conflict.

## Workflow State

- Manager preparation: complete; refresh after Phase 1 merge
- Expanded planning: not needed on current accepted design; reassess only if a
  stop condition exposes a novel durable or trust-boundary decision
- Implementation: pending one `loom_phase_executor`
- Refiner: not needed unless the executor returns a qualified blocker
- Pre-submit gate: pending
- Independent review: not needed on current fast path; require the optional
  reviewer if a material residual authority/recovery risk remains
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
