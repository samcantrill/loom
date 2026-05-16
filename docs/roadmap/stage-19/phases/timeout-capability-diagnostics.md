# Phase 4 Execution Plan: Timeout Capability And Reliability Diagnostics

## Metadata

- Status: scope-complete phase execution plan
- Feature focus: Reliability Policies And Transactions
- PR title: `Reliability Policies And Transactions - Phase 4: Timeout Capability And Diagnostics`
- PR: pending
- Branch: `codex/timeout-capability-diagnostics`
- Worktree: `/home/samcantrill/work/loom-worktrees/timeout-capability-diagnostics`
- Phase execution plan path: `docs/roadmap/stage-19/phases/timeout-capability-diagnostics.md`
- Full plan: `docs/roadmap/stage-19/implementation-plan.md`
- Source phase: Phase 4, `timeout-capability-diagnostics`
- Stack predecessor: none; Phases 1 through 3 are merged into `develop`
- Base branch: `develop` at `7b77186` after Phase 3 merge metadata
- Target branch: `develop`
- Merge eligibility: root PR is eligible to merge into `develop` only after implementation, targeted validation, `make validate-pr`, `make test-summary`, automated review, and CI pass with no blockers
- Workflow path: expanded path
- Successor dependency notes: Phase 5 may start only after Phase 4 is open or prepared, validated, and recorded by the manager; no successor branch exists at plan time
- Plan quality gate: passed on 2026-05-16 in the selected implementation plan
- Draft pass: completed by manager-local planning in this assignment
- Refine pass: completed by manager-local planning after reading runtime capability, preflight, executor, execution reliability, and coordination lease contracts
- Blockers: none

## Objective

Add capability-aware timeout support and cheap reliability diagnostics without changing resource admission, authority operational timeouts, or lease model shape. This phase must make enforced, delegated, observed, unsupported, and timed-out timeout outcomes representable and persisted where execution reaches a stage attempt. It must also warn about unsupported reliability policies through existing runtime capability and preflight surfaces.

## Full-Plan Context

Stage 19 implements reliability policies and transactions in six phases. Phase 1 added import-light reliability contracts and runtime policy parsing. Phase 2 added persistence and read-model facets. Phase 3 records lifecycle transactions and classification facts. Phase 4 owns timeout capability/outcome facts and diagnostics. Phase 5 owns retry decisions and runner-owned retry automation. Phase 6 owns final read-only inspection and docs.

## Source Phase Summary

- Goal: add capability-aware timeout outcomes and cheap reliability diagnostics.
- Required scope: timeout support/outcome records for enforced, delegated, observed, unsupported, and timed-out behavior; fake executor and subprocess-style timeout behavior where feasible; preflight/runtime diagnostics for unsupported retry, timeout, transaction, and lease policies; lease compatibility diagnostics using existing lease records/protocols first; documentation separating reliability timeout from resource admission wait time and authority service operational timeouts.
- Acceptance criteria: distinct timeout outcomes are persisted/readable; no timeout field is added to `ResourceRequest`; generic capability metadata can support future containers and Stage 20 event projection; lease gaps surface as diagnostics, not a new lease model.

## Current Source And Harness Findings

- `loom.pipeline.reliability.TimeoutOutcomeRecord` already persists `timed_out`, `duration_seconds`, `reason_code`, `status`, `transaction_id`, and optional causal decision ID, but it lacks a first-class support/outcome vocabulary for enforced, delegated, observed, and unsupported outcomes.
- `loom.pipeline.runtime.capabilities.ExecutorDescriptor` currently models resource capabilities only. Descriptor `details` already carry executor facts such as process isolation, containerization, and scheduler command support.
- `validate_executor_capabilities` feeds both runtime capability checks and preflight executor/resource checks. It can produce generic capability diagnostics without importing executors or diagnostics.
- `ResolvedStageRuntimeOptions` includes resolved reliability policy, and `StageExecutionRequest` carries that resolved runtime into executors.
- `SubprocessExecutor` owns a narrow `subprocess.run(...)` boundary that can enforce a Python timeout without changing stage code or resource admission.
- `LocalExecutor` runs arbitrary Python in-process and cannot safely interrupt user code without broad concurrency/signal behavior; this phase should report unsupported local timeout enforcement instead of adding unsafe cancellation.
- Phase 3 execution reliability helpers already build status details, transaction IDs, and transaction-chain parent links. Phase 4 can add timeout outcome helpers there and call them from executor result commit/failure paths.
- `WorkspaceCoordinationStore`, `LeaseRecord`, `TrialLeaseRecord`, `ResourceLeaseRecord`, and `coordination_requirement_diagnostics` already cover lease identity, amount, TTL, renewal, release/failure, recovery, and unsupported safety diagnostics. No new lease record fields are needed for Phase 4.

## In-Scope Work

- Add import-light timeout capability/outcome vocabulary to `loom.pipeline.reliability` and `TimeoutOutcomeRecord` serialization in a backward-compatible way.
- Extend executor descriptors with timeout capability metadata and runtime capability diagnostics for selected timeout policy.
- Implement actual subprocess reliability timeout enforcement using `TimeoutPolicy.duration_seconds` when present and supported.
- Record timeout outcomes for supported, timed-out, unsupported, delegated, and observed cases through existing reliability store facets.
- Add cheap preflight reporting for reliability timeout, retry, transaction, and lease policy support using existing capability validation and coordination diagnostics.
- Add tests proving `ResourceRequest` still rejects timeout fields and authority/resource operational timeout arguments remain distinct from reliability timeout policy.
- Update docs/phase artifacts to document the subprocess timeout decision and timeout-domain separation.

## Out-of-Scope Work

- Automatic retry, retry decisions, next-attempt scheduling, or retry denial behavior.
- Scheduler-health orchestration, executor migration, worker-daemon behavior, or resource-aware retry escalation.
- Real cluster, container, cloud, network, or optional-SDK dependency in default tests.
- Event grammar, event sinks, callback policy, notifications, or telemetry.
- Cleanup execution, deletion, retention enforcement, or run-collection GC.
- A new global lease model or broad coordination schema changes.

## Timeout Capability And Outcome Vocabulary

Final Phase 4 timeout support names:

| Support | Meaning |
| --- | --- |
| `enforced` | Loom or the selected executor can actively stop the stage attempt at the configured duration. |
| `delegated` | Loom passes timeout intent to an external backend or scheduler, but this process does not enforce it directly. |
| `observed` | Loom can observe timeout-like backend facts after execution but cannot enforce the timeout. |
| `unsupported` | The selected executor cannot enforce or observe reliability timeout policy. |

Final Phase 4 timeout outcome names:

| Outcome | Timed out | Meaning |
| --- | --- | --- |
| `enforced` | false | Timeout policy was enforced and the attempt completed before the deadline. |
| `timed_out` | true | Timeout policy was enforced or observed and the attempt exceeded the configured duration. |
| `delegated` | false | Timeout policy was delegated to an external backend; no timeout was observed in this attempt. |
| `observed` | false | Backend facts were observed but this attempt did not time out. |
| `unsupported` | false | Policy was present but the selected executor could not apply it. |

`TimeoutOutcomeRecord.reason_code` remains the compact stable reason field. A new optional `support_level` or `outcome` field may be added only if tests show reason codes alone are too ambiguous for Phase 4 acceptance. Existing Phase 2 records must still round trip.

## Subprocess Timeout Decision

This phase implements actual timeout enforcement for `SubprocessExecutor`. The subprocess boundary already maps to `subprocess.run`, so passing `timeout=duration_seconds` is narrow, dependency-free, and testable with fake process runners. The timeout path should:

- mark the attempt `FAILED`;
- create an `ExecutionFailure` with generic executor infrastructure failure data and timeout metadata;
- persist a `TimeoutOutcomeRecord` with reason `timed_out`;
- preserve existing worker-result validation behavior for non-timeout process failures.

`LocalExecutor` will not enforce timeouts in this phase. It should emit an unsupported timeout outcome or capability diagnostic when policy is selected. Future executors can report `delegated` or `observed` through the same vocabulary without changing resource request schemas.

## Scope Contract

Public behavior:

- Reliability timeout lives under `runtime.reliability.timeout` and resolved stage runtime. No `ResourceRequest.timeout`, admission-wait timeout, or authority-client operational timeout field is added or repurposed.
- Timeout outcome facts are optional for older runs and present when timeout policy is selected and execution reaches a recordable stage-attempt path.
- Preflight stays cheap. It may inspect parsed config, runtime options, executor descriptors, and supplied/local capability records, but it must not require real cluster/container/network probes beyond existing cheap command checks.
- Lease compatibility diagnostics reuse `BackendCapabilitySet`, `WorkspaceCoordinationStore`, `LeaseRecord`, `ResourceLeaseRecord`, and `coordination_requirement_diagnostics`.

Module boundaries:

- `loom.pipeline.reliability` remains import-light and does not import execution, concrete executors, stores, diagnostics, CLI, plugins, or optional backends.
- `loom.pipeline.runtime.capabilities` may import reliability contracts but must not import diagnostics or concrete executors.
- `loom.pipeline.executors` may consume resolved runtime policy and report executor metadata/failures.
- `loom.pipeline.execution` owns persistence of timeout outcome records because it has run-store, status detail, and transaction context.
- `loom.diagnostics` presents capability/readiness facts only.

## Design Impact

- Maintainability: timeout support is expressed through descriptor facts and a single outcome record shape rather than special-casing backends in retry or CLI code.
- Extensibility: future containers, schedulers, and remote execution adapters can report delegated or observed timeout outcomes through the same vocabulary.
- Future compatibility: Stage 20 can project timeout outcomes as events, and Phase 5 can classify timeout failures for retry without parsing executor logs.
- Domain neutrality: timeout diagnostics use generic executor/capability language and do not encode project- or scheduler-specific policy keys.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add `timeout` to `ResourceRequest` | The planning agreement explicitly keeps reliability timeout separate from resource admission and operational timeouts. |
| Enforce local in-process timeouts | Interrupting arbitrary Python safely would require broad concurrency/signal behavior and would not be fake/local-test-first. |
| Treat timeout facts as executor log metadata only | Stage 19 requires persisted reliability facts as source of truth, not log parsing. |
| Create new lease records for reliability policy | Existing coordination and authority lease records already cover named keys, amounts, TTL, renewal, failure, and recovery. |
| Require real container or scheduler tests | Stage 18 specifics are unavailable and default Stage 19 validation must avoid heavy external environments. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Local executor timeout enforcement remains unsupported | Safe in-process interruption is outside this phase and would risk broad behavioral change | A future executor/control model provides a safe interruptible local boundary. |
| Delegated and observed timeout outcomes are descriptor/fake-path facts first | Stage 18 container specifics are unavailable in this checkout | Stage 18 introduces concrete delegated/observed timeout contracts that need stronger public fields. |
| Lease diagnostics stay capability-based, not policy-language-based | No authored lease reliability policy exists yet; existing lease capabilities are sufficient for Phase 4 | Phase 5 or later policy parsing introduces explicit lease policy knobs. |

## Reviewability

- Expected PR size and shape: reliability enum/record extension, runtime capability diagnostics, subprocess timeout handling, execution timeout outcome persistence, preflight diagnostics, and focused tests.
- Files and areas to inspect: `src/loom/pipeline/reliability/_models.py`, `src/loom/pipeline/runtime/capabilities.py`, `src/loom/pipeline/executors/subprocess.py`, `src/loom/pipeline/execution/reliability.py`, `src/loom/pipeline/execution/lifecycle.py`, `src/loom/diagnostics/preflight.py`, and targeted capability/diagnostics/executor tests.
- Scope-control checks: no retry loop, no resource timeout field, no broad lease model, no real cluster/container dependencies, no CLI mutation, no event sink behavior.

## Implementation Steps

1. Add timeout support/outcome vocabulary and backward-compatible serialization updates where needed.
2. Extend executor descriptors and capability validation to emit reliability timeout diagnostics from resolved run/stage reliability policy.
3. Implement subprocess timeout enforcement through a narrow process-runner contract update and structured timeout failure metadata.
4. Add execution helpers and lifecycle wiring to persist timeout outcomes when policy is selected, including unsupported local and fake delegated/observed paths.
5. Add or harden preflight checks for reliability policy support and lease capability diagnostics using existing capability/readiness models.
6. Add targeted tests, update phase artifacts, then run targeted validation, `make validate-pr`, and `make test-summary`.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_reliability_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: new timeout vocabulary remains import-light and public exports do not import executors, diagnostics, stores, CLI, plugins, or optional backends.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/reliability/test_reliability_models.py`, `tests/unit/loom/pipeline/test_executor_capabilities.py`, `tests/unit/loom/pipeline/executors/test_subprocess_executor.py`, `tests/unit/loom/pipeline/execution/test_lifecycle.py`, `tests/unit/loom/diagnostics/test_diagnostics_preflight.py`, `tests/unit/loom/pipeline/stores/test_sqlite_coordination.py`
- Required assertions or deferral reason: timeout enum/record round trips; descriptors report timeout support; subprocess timeout produces structured failure metadata; lifecycle persists timeout outcomes; preflight reports unsupported/partial reliability policy; coordination diagnostics prove existing lease records cover Phase 4 needs.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_reliability_contract.py`, `tests/contracts/test_executor_capabilities_contract.py`, `tests/contracts/test_diagnostics_preflight_contract.py`, `tests/contracts/test_cli_preflight_contract.py`, `tests/contracts/test_workspace_coordination_contract.py`
- Required assertions or deferral reason: public capability/preflight IDs and schemas remain stable while adding reliability diagnostics; no resource schema timeout field; lease compatibility diagnostics remain existing-store based.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/diagnostics/test_diagnostics_preflight_integration.py`, `tests/integration/diagnostics/test_cli_preflight.py`, `tests/integration/pipeline/test_runtime_capabilities_integration.py`, `tests/integration/pipeline/test_subprocess_executor_integration.py`
- Required assertions or deferral reason: preflight/runtime capability integration reports timeout policy support cheaply; subprocess-style timeout facts can be observed without real external services.

### E2E Suite

- Status: deferred
- Expected paths: none specific for Phase 4
- Required assertions or deferral reason: Phase 4 adds persisted facts and preflight diagnostics, not a new user workflow beyond existing preflight surfaces. Final inspection belongs to Phase 6.

### Opt-In Suites

- Status: deferred
- Markers affected: no real cluster, container, cloud, network, service, telemetry, or optional-SDK markers
- Required assertions or deferral reason: fake/local/subprocess default tests satisfy timeout and diagnostics behavior until backend-specific Stage 18 contracts exist.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_reliability_api.py tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/pipeline/reliability/test_reliability_models.py tests/unit/loom/pipeline/test_executor_capabilities.py tests/unit/loom/pipeline/executors/test_subprocess_executor.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/unit/loom/pipeline/stores/test_sqlite_coordination.py
uv run pytest tests/contracts/test_reliability_contract.py tests/contracts/test_executor_capabilities_contract.py tests/contracts/test_diagnostics_preflight_contract.py tests/contracts/test_cli_preflight_contract.py tests/contracts/test_workspace_coordination_contract.py
uv run pytest tests/integration/diagnostics/test_diagnostics_preflight_integration.py tests/integration/diagnostics/test_cli_preflight.py tests/integration/pipeline/test_runtime_capabilities_integration.py tests/integration/pipeline/test_subprocess_executor_integration.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted validation and the PR gate passed without a refinement blocker
- PR review: unused; one automated review pass available
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this artifact
- Final phase execution plan: completed in this artifact
- Implementation summary: completed. Added timeout support/outcome vocabulary,
  backward-compatible timeout outcome serialization, descriptor-level timeout
  support diagnostics, subprocess timeout enforcement, local unsupported-timeout
  metadata, lifecycle timeout outcome persistence, lease capability diagnostics,
  and docs clarifying reliability timeout boundaries.
- Implementation validation: completed. Focused Phase 4 package/unit/contract/
  integration pytest batch passed with `189 passed`; `make validate-pr` passed
  Ruff, Pyright, default/config test harnesses, and build; `make test-summary`
  wrote suite evidence with overall `passed`.
- Refinement summary: not needed; no targeted-validation, coverage, lint, type,
  or build blocker remained after implementation.
- Blocker-resolution summary: not needed; 0/3 passes used.
- PR preparation: pending
- Merge summary: pending
- Stack maintenance: pending
- Remaining blockers: none
