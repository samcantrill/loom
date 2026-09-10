# Phase 7 Execution Plan: Unified Sweeps

## Metadata

- Status: pending
- Roadmap stage and phase: 41 / 7
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p7-unified-sweeps
- Worktree: manifest root, suffix `stage-41-p7-unified-sweeps`
- Base revision: published develop after Phase 6 merges; record exact SHA at execution preparation
- PR target: develop
- PR title: Dispatch sweep trials through native run operations
- Dependencies: Phase 6 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: source predecessor pending; no unresolved planning blocker

## Objective And Context

Sweep trials use the unified run lifecycle with unchanged experiment meaning and stable retry identities.

All supported execution backends are available through Phases 2–6. This phase converts the sweep consumer and removes its direct/queue split; MCP and remaining shared public removal are later owners.

Requirements: FR-41-01/13/14. Design: DQ-41-01/06.
Validation ownership: VAL-41-12 (sweeps).

## Current Source And Harness

- `src/loom/pipeline/sweep/dispatch.py::run_sweep_direct`, enqueue_sweep_trials, dispatch records and `cli/sweep.py`.
- Sweep planner/coordination/runner records: deterministic expansion, trial identity and persisted progress.
- Phase 2 RunRequest/start_run and Phase 3 public deployment/run composition; exact prepared receipts remain usable.
- `tests/contracts/test_sweep_dispatch_contract.py`, `tests/integration/pipeline/sweep` and `tests/e2e/test_sweep_cli.py`.

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

- Manager preparation: approved card; execution revision/worktree pending
- Planning review: original design review and corrected run/cancel contracts retained; nine-phase mapping checked locally
- Implementation: not started
- Refiner: not used
- Pre-submit gate: not run
- Independent implementation review: required for sweep scientific/control preservation and public removal
- Blocker corrections: 0/3
- PR and merge: not started

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Not started |
| Tests added, updated or intentionally removed | None; planning only |
| Validated revision/tree and evidence | Pending implementation |
| Validation-relevant changes after evidence | None |
| Replaced-code removal / retained primitive consumers | Pending this phase's removal audit |
| PR, review and merge | Pending |
| Residual risk and cleanup | Sweep semantic/replay evidence and shared-owner disposition pending |
