# Phase 7 Execution Plan: Unified Sweeps

## Metadata

- Status: in_progress
- Roadmap stage and phase: 41 / 7
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p7-unified-sweeps
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: `2e3050badb987863b02cf0bef19439cda35b6ef0` (published Phase 6 completion metadata after PR 313)
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 7: Unified Sweeps
- Dependencies: Phase 6 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: none; no named refinement is required

## Objective And Context

Sweep trials use the unified run lifecycle with unchanged experiment meaning and stable retry identities.

All supported execution backends are available through Phases 2–6. This phase converts the sweep consumer and removes its direct/queue split; MCP and remaining shared public removal are later owners.

Requirements: FR-41-01/13/14. Design: DQ-41-01/06.
Validation ownership: VAL-41-12 (sweeps).

## Current Source And Harness

- `src/loom/pipeline/sweep/dispatch.py` owns `run_sweep_direct`,
  `enqueue_sweep_trials`, direct/queue dispatch records and request translation.
  `src/loom/cli/sweep.py` selects those engines and composes trial config locally.
- `src/loom/pipeline/sweep/{runner,manifest,trials,coordination,status}.py`
  own deterministic expansion, existing sweep/trial state and outcome projection.
  Existing manifest metadata and workspace trial references are current durable
  reuse candidates; choose one authoritative request/reference owner, not a new
  job database. Planning must remain side-effect-free.
- `src/loom/_run.py::run`, `src/loom/deployment.py::ensure_available`,
  `src/loom/coordinator.py`, `src/loom/queue/run.py::RunRequest` and
  `src/loom/queue/_coordinator_client.py` provide current startup, native run
  acceptance, observation and cancellation. Explicit failed-admission retry
  remains `LocalDaemonSubmissionRequest.retry_failed_revision`; ordinary replay
  does not carry that authorization.
- Published predecessor includes PR 314's opt-in local preparation policy.
  Preserve selected source/profile and local binding meaning; default portable
  preparation remains unchanged. No automatic placement or configuration-policy
  substitution belongs to the sweep adapter.
- Existing tests: `tests/contracts/test_sweep_dispatch_contract.py`,
  `tests/{unit/loom,integration}/pipeline/sweep`, `tests/e2e/test_sweep_cli.py`,
  and sweep public API/CLI/example consumers. Current runnable example:
  `examples/experiments/deterministic-sweep/`; current feature doc:
  `docs/features/sweeps.md`. Resolve exact dynamic references before removal.

## Scope

Convert sweep execution and status linkage, preserving expansion, parameters, provenance, failure/early-stop semantics and request replay. Remove obsolete sweep dispatch APIs/modes/records in the same PR. Do not change scientific choices or introduce a new sweep scheduler.

Assume the predecessor's accepted contracts and existing qualified installations.
Each phase includes its code, owner-level tests, current docs and replaced-code
removal. Preserve unrelated work and current scientific/resource meaning.

## Implementation Walkthrough And Examples

### Keep trial planning; replace trial execution

A sweep still decides which experiments exist: expand the same parameters in
the same order, assign stable trial identities and retain their provenance.
The implementation change is how a selected trial becomes accepted work. The
sweep dispatcher builds a native request and records its operation/admission
references instead of choosing a direct runner or whole-run queue engine.

The following is an implementation sketch, not a new public sweep API. Service
availability has already been established through
[Phase 3](service-startup-lifetime.md#implementation-walkthrough-and-examples),
and the client uses [Phase 2's native operation](durable-run-operation.md#implementation-walkthrough-and-examples):

```python
for trial in selected_trials:
    request = sweep_state.get_or_create_request(trial)
    operation = client.start_run(request)
    sweep_state.record_operation(
        trial_id=trial.id,
        operation_id=operation.operation_id,
    )
```

Here `get_or_create_request` must durably preserve the exact trial request and
its preparation/admission IDs **before** calling `start_run`. Its helper name
and record layout are private choices. If the coordinator accepts the request
but the response is lost before `record_operation`, retry loads that same
request and recovers the existing operation. Generating new IDs on retry would
create a second experiment. Reuse existing sweep state for these references;
this does not require a second job database.

### Separate accepted trials from trials still awaiting dispatch

The coordinator owns execution readiness and placement for accepted trials.
The sweep planner retains trial selection, ordering and existing early-stop
policy. A waiting sweep client can observe native operations without owning
their workers or recomputing pipeline readiness.

For example, if a caller has submitted trials A and B but exits before
submitting C, accepted A and B continue under their native operations. C remains
an unsent trial in sweep state; client exit does not make it accepted coordinator
work. Resuming the sweep reuses A and B's references and dispatches C according
to the existing sweep policy. Preserve failed-trial, cancellation, early-stop
and aggregate-result meanings when changing that progress projection.

### Remove the old dispatcher with its consumer

Convert the sweep API, CLI and examples in this phase, then remove
`run_sweep_direct`, whole-run enqueue dispatch and the direct/queue selector.
Delete obsolete sweep-only result/count/queue plumbing once its useful meaning
is represented through native references. Retain a shared primitive only when
an actual remaining consumer needs it and record that consumer for Phase 9.

VAL-41-12 compares trial inputs, order and provenance before and after the
conversion, exercises lost-response replay, and preserves failed/early-stopped
trial assertions against the new path. Removing an execution engine does not
justify dropping the scientific or control behavior its tests protected.

## Fixed Contracts And Private Discretion

Sweeps retain deterministic expansion, trial identity, parameter/provenance
meaning and existing reliability/resource policies. Each selected trial uses the
native run request or submission of its exact prepared receipt. Eliminate
direct-versus-queue dispatcher selection and parallel whole-run records; use native
operation/admission references for execution progress. A sweep waiting client
does not own workers or replace coordinator readiness. Persist/reuse each trial's
IDs through existing sweep state; interruption/retry cannot duplicate admitted
trials. Do not add a general sweep job database.

Trial operation replay observes its current admission, including terminal
failure, without requesting a new attempt. Preserve an explicitly requested
failed-admission retry through the native `retry_failed_revision` contract and
its supported authority capability; sweep resume/observer reconnect alone does
not supply that authorization. Retain the same trial scientific intent and the
native retry reference in existing sweep state when such a retry is requested.

### Delivery boundary

A selected sweep can prepare/admit/observe trials through the delivered native path. Pure sweep planning remains side-effect-free. Removed execution inputs fail explicitly; importable/serializable project definitions replace unsupported in-process factories without silently changing trials.

### Cross-phase handoff

Phase 9 audits any shared queue/runner owners left after this consumer is converted. Keep a concise removal disposition in this card so remaining consumers are explicit. Public operation identities and trial semantics remain owned by native operations and sweep planning respectively.

### Removal owned here

Delete run_sweep_direct, enqueue-only whole-run dispatch and direct/queue selector plumbing once their scientific/control assertions run against native admissions. Remove sweep-only obsolete result/count/queue records, imports and generated commands; keep shared helpers only with a named current consumer.

Private helper names, local wiring and intermediate representations remain
implementation discretion. Public behavior, durable identity, trust, failure and
cross-phase meanings above are fixed. No compatibility aliases or state resets.

## Proportionality

Reuse existing sweep state for trial-to-native-operation references. No new job database, planner redesign or compatibility dispatcher. Scope tests to sweep behavior and changed native boundaries.

## Invariant Ownership

| Invariant | Owner | Reachable boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Same experiment expansion | Sweep planner and trial builder | Conversion of direct factories/options to serialized requests | Changed scientific experiment | VAL-41-12 identical trial parameters/order/provenance |
| No duplicate admitted trial | Sweep state and native admission | Interruption or lost response | Trial runs twice | VAL-41-12 persisted same IDs/replay |
| Truthful sweep outcome | Sweep result projection | Failed/early-stopped trial or waiting admission | Wrong aggregate result | Existing sweep assertions moved to native consumer |
| No sweep execution bypass | Sweep public API/config/CLI | Old selector/import/generated command | Independent runner persists | Removal audit and expected public rejection |

## Implementation Slices

1. Map exact planned trials and accepted controls to native preparation/run requests and persist their stable references.
2. Convert submission, replay/wait/status/cancel integration and preserve failure/early-stop/aggregation behavior.
3. Delete replaced sweep engines/records/selectors, move meaningful tests to the native path and update sweep examples.

## Test And Validation Plan

| Suite | Obligation | Minimal evidence |
| --- | --- | --- |
| Package/contract | Required | New intentional API and removed modes; deterministic expansion/identity and result meanings. |
| Unit/integration | Required | Same trial inputs/options/provenance; lost-response/interruption replay; failed and early-stopped trials. |
| E2E | Required | Synthetic sweep uses native operations and inspection; no duplicate admissions or direct runner invocation. |
| Backend live matrices | Reuse unchanged evidence | Phases 4/6 own backend qualification; expand only if sweep changes a relevant contract. |

Target existing source-mirrored tests and add focused assertions where the new
contract requires them. Resolve predecessor-renamed test paths at preparation.
Run optional-runtime commands only with their qualified environment. A local
fixture is not live-site evidence; record missing qualification explicitly.

    uv run --extra config pytest tests/contracts/test_sweep_dispatch_contract.py tests/integration/pipeline/sweep tests/e2e/test_sweep_cli.py

Final implementation gate; reuse a fresh receipt only while relevant code,
tests, dependency/build and validation configuration remain unchanged:

    make validate-pr
    make test-summary

Do not repeat complete backend/fault matrices in consumer phases. Expand tests
only for changed shared contracts, new failures or a remaining accepted concern.

## Risks, Review, And Stops

Stop for lost accepted trial/control semantics or inability to persist a stable native reference. Historical factory compatibility is not required; scientific meaning is. Preserve meaningful assertions when deleting old dispatch tests.

## Executor Handoff

Read planning.md Behavior Baseline, the requirement/design/validation IDs above,
this whole card and the actual published predecessor contracts. Implement the
listed slices within the stated ownership. Do not reopen agreed lifecycle,
grant-before-start, sole submission/finalization ownership or hard cutover.
Manager action is for a demonstrated public/durable or accepted-behavior conflict,
not private helper choices. You are not alone in the codebase; preserve others' edits.

## Workflow State

- Manager preparation: passed in the manifest's persistent stage worktree at
  the Base revision above, on the canonical Phase 7 branch. Phase 6 PR 313
  merged as `5eeb021742a271339a2583cd2ac0ccb8a6e125fa`; completion metadata is
  published, synchronization verified matching stage/local/fetched/advertised
  develop, and exact local/remote predecessor branches are retired. Predecessor
  agents and phase-owned processes are terminal. Successor start/preflight passed.
- Source reconciliation: native prepare/run acceptance, exact admission replay,
  explicit failed-admission retry, per-role startup/lifetime, agent backends and
  authority finalization are delivered. Convert the existing sweep consumer while
  keeping scientific expansion, parameters/order, provenance, resource/reliability
  controls, failure continuation and early-stopped outcome assertions.
- Validation selection: begin with sweep unit/contract/integration, CLI/E2E and
  deterministic-sweep example consumers. Add causal interruption/lost-response
  assertions at durable request-before-send and native operation/admission readback.
  Cover public removals and cheap imports. Expand for changed native boundaries,
  shared store/serialization consumers or observed failures; preserve both final
  make gates and reuse predecessor backend qualification without a new matrix.
- Named refinement: none; accepted observable/durable contracts are sufficient.
  Private request storage/wiring remains implementation discretion.
- Execution delegation: one executor is justified by the coupled dispatch,
  persisted trial references, CLI/status/aggregation and removal conversion.
  The manager owns manifest, PR preparation, independent review and delivery.
  No children or extra implementation branches are permitted.
- Planning review: original accepted contracts retained; 2026-09-12 published-source amendments and current readiness receipt are owned by the manifest Quality Gate
- Implementation: native request-before-send persistence, replay/observation and
  explicit controls are implemented in existing sweep state; scientific planning
  remains unchanged. Targeted checks passed (68 tests); both required full gates passed. Local implementation is ready for the manager's pre-submit and independent review gates.
- Scoped correction 1: the real EarlyStopStage native sweep initially reported
  `cancelled` instead of `early_stopped` (causal integration failure). Existing
  managed/remote/Slurm authority finalizers replaced its verified worker reason;
  native inspection also omitted authority stage reasons. Preserve the verified
  `early_stop` reason and project it through the existing inspection stage code.
  Ordinary cancellation is unchanged. The corrected real native early-stop and
  failure-continuation assertions pass; no backend ownership changes are involved.
- Scoped correction 2: native CLI collection initially returned zero refs despite
  an authority-committed output (E2E receipt `/tmp/sweep-targeted.txt`, 42 passed
  before the failing collection assertion). The CLI now reads committed artifact
  facts from the retained deployment's native admission authority view, including
  outputs retained through retry/reuse. Legacy `artifacts.json` is not required.
- Refiner: not used
- Pre-submit gate: not run
- Independent implementation review: required for sweep scientific/control preservation and public removal
- Blocker corrections: 2/3
- PR and merge: not started

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Native sweep request-before-send persistence, exact replay/observation, explicit cancel/retry and status/collection; CLI/public cutover; current sweep/CLI/structure docs and deterministic example. Narrow native authority finalizer/inspection changes retain early-stop meaning and expose existing committed artifact facts. |
| Tests added, updated or intentionally removed | Native input/order/provenance and stable-ID checks; lost-response/interruption, failed/early-stopped/cancelled trials, failed-admission retry with successful predecessor outputs retained, CLI/E2E/example and public removals. Obsolete direct/queue engines and record serialization fixtures removed; meaningful planner/coordination/collection assertions preserved. Targeted sweep and inspection selection: 68 passed (`/tmp/sweep-targeted-final.txt`). |
| Validated revision/tree and evidence | `make validate-pr` passed at `d158bec08e7ba9aa3989c17c180472e3921d9dd6`, tree `a45db5383bdd589a7926e82c09ed05b5add0019d`: lint/typecheck, default 3352 passed/2 skipped, config-extra 267 passed/18 skipped, MCP 36 passed, wheel/sdist built (`/tmp/loom-stage41-p7-validate-pr.log`). `make test-summary` passed at `9e45fd6ed92349a0439c5df3ad93a051d338a8af`, tree `5055302bab0507920d5830fd486eb3863b20838b`: 3657 passed, 18 skipped, no failures/errors (`build/test-summary.md`, per-suite JUnit/coverage under `build/test-summary/`, `/tmp/loom-stage41-p7-test-summary.log`). |
| Validation-relevant changes after evidence | No production/test/example/build/dependency changes after successful validate-pr; only the manager-requested current sweep sections of docs/structure.md and docs/features/cli.md changed before test-summary, with links/diff checked. Only this completion receipt changes after summary. The first candidate's gate stopped at test-fixture typing, corrected before the successful gate (`/tmp/loom-stage41-p7-validate-pr-initial.log`). |
| Replaced-code removal / retained primitive consumers | Removed run_sweep_direct, enqueue_sweep_trials, sweep-only direct/queue request/results/counts, generated enqueue requests, queue selectors and queue-state mapper. No remaining source/example references to the removed dispatch APIs. PipelineRunner remains behind pipeline.execution.run_pipeline/public exports; QueueService remains used by queue.controller and queue.status for the later shared-owner audit. |
| PR, review and merge | Manager-owned; not started by executor. |
| Residual risk and cleanup | No unresolved implementation blocker; 2/3 semantic corrections used. Synthetic native acceptance and inspection/collection evidence only; no new physical container/fleet/Slurm qualification. The 18 summary skips are opt-in Docker/Apptainer smoke/build/resource/scheduling/namespace-lifecycle cases; predecessor backend qualification is reused for unchanged execution boundaries. Both gate terminals and all executor-owned test processes are terminal; process inspection found no remaining Loom service runtime or worktree test process. Durable test/build receipts are retained; no external workload/provisioning, push, PR or branch transition occurred. |
