# Phase 12 Execution Plan: Local/Subprocess Worker Continuation Paths

## Metadata

- Status: pr_open; automated manager review complete
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 12: Local/Subprocess Worker Continuation Paths`
- Branch: `codex/authority-worker-continuations`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-worker-continuations`
- Phase execution plan path: `docs/phases/authority-worker-continuations.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 12 - Local/Subprocess Worker Continuation Paths
- Stack predecessor: none; Phase 11 merged in PR #129 and is recorded in the plan
- Base branch: `develop` at `7c4ed9d`
- Target branch: `develop`
- PR: <https://github.com/samcantrill/loom/pull/130>
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Draft pass: completed by managing agent on 2026-05-12
- Refine pass: not needed before implementation; source inventory gives clear boundaries
- Blockers: none; implementation may begin from this phase execution plan.

## Objective

Move local split-process continuation paths onto explicit authority handoffs and service-backed mutation so stage workers, stage-job continuations, subprocess execution, and prepared-run continuation fail closed instead of silently mutating local authority state.

## Source Findings

- `AuthorityBackedSerialRunStore` already stamps prepared worker requests with `authority_attempt` lease/fencing facts and compact authority config metadata.
- `run_stage_worker()` validates authority fencing through `validate_stage_job_authority()` when the selected run store supports that hook.
- `run_stage_job()` accepts optional authority fencing CLI values, falls back to worker-request fencing metadata when omitted, validates the active backend lease, renews the lease before running, and prevents whole-run finalization for authority-backed stage jobs.
- The subprocess executor already forwards `authority_config_to_cli_args()` into generated `loom stage run` commands.
- `loom stage run`, `loom stage-job run`, and `loom prepared-run continue` already construct stores through `create_authority_backed_serial_run_store()`, so missing or invalid online authority fails closed after Phase 11.
- `continue_prepared_run()` is currently a validation-only guard that always raises `InsufficientPreparedStateError` before replaying whole-run state; this satisfies the no-silent-local-mutation boundary but still needs explicit coverage with online authority.
- SLURM command builders also pass authority config, but live SLURM behavior and generated scheduler jobs belong to Phase 13.

## In Scope

- Tighten local and subprocess worker handoff behavior around authority config and lease/fencing facts.
- Add or update tests proving `loom stage run`, subprocess execution, `loom stage-job run`, and `loom prepared-run continue` use explicit authority-backed stores and reject stale or missing authority state.
- Ensure direct stage workers and stage-job continuations renew or revalidate stage leases before terminal output/status mutation.
- Keep prepared-run continuation fail-closed with authority-backed stores and no local-authority mutation replay.
- Improve diagnostic assertions where existing errors already expose continuation codes and context.
- Inventory generated local command paths in the phase artifact and tests.

## Out Of Scope

- SLURM live submission, scheduler observation, cancellation, generated scheduler job migration, and live SLURM worker semantics.
- Workspace coordination service APIs, counters, resource leases, and admission policy changes.
- Offline evidence writer/import behavior.
- Remote artifact storage or remote payload transfer.
- Adding broad new authority service routes beyond those already available for runner/worker lifecycle mutation.

## Assumptions

- Phase 11's HTTP-backed per-run authority adapter is the canonical online store for Phase 12 command paths.
- Local artifacts, worker request files, worker result files, logs, plan documents, and runtime metadata remain local materialization state.
- Stage workers may read fencing facts from durable worker-request metadata; generated command lines do not need to repeat secrets when the worker request is the trusted handoff artifact.
- Prepared whole-run continuation remains intentionally non-replayable in this phase.
- SLURM command builders can be covered only for handoff shape; live scheduler behavior is reserved for Phase 13.

## Scope Contract

This phase may edit CLI continuation commands, local/subprocess executor handoffs, continuation validation, authority-backed run-store worker hooks, and their tests. It must not implement SLURM live migration, resource coordination, offline import, or server-private repository access in pipeline/CLI runtime modules.

## Design Impact

- Maintainability: uses the existing store hook boundary rather than duplicating authority mutation logic in CLI commands.
- Extensibility: authority handoff metadata stays reusable for Phase 13 SLURM workers and later remote worker transports.
- Reviewability: changes are bounded to continuation/worker entrypoints and tests, with generated command shape visible in assertions.
- Safety: stale lease/generation cases should fail before output commit or terminal status mutation.

## Future Compatibility

The handoff shape should remain compatible with Phase 13 by keeping authority config and per-attempt fencing facts separate: authority config selects the service, while `authority_attempt` metadata fences the exact stage attempt.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Let split-process workers re-resolve authority only from workspace registry | A stale registry or wrong workspace could allow ambiguous mutation ownership. |
| Put all fencing facts only on CLI arguments | Durable worker requests are already trusted handoff artifacts and avoid unnecessary command-line exposure. |
| Migrate SLURM live jobs together with local/subprocess workers | Phase 13 owns scheduler-specific status, cancellation, and generated job semantics. |
| Allow prepared-run continuation to replay local state for compatibility | The v10 plan requires fail-closed behavior until a safe authoritative replay design exists. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| SLURM generated commands may still have transitional behavior beyond authority config propagation | Dedicated Phase 13 owns live scheduler migration. | Phase 13 starts. |
| Prepared whole-run continuation remains validation-only | Safe replay needs broader design than this phase. | A later continuation/replay phase adds authoritative replay payloads. |
| Stage worker command lines rely on worker-request metadata for fencing facts | Keeps secrets out of generated commands while preserving trusted durable state. | A remote worker transport cannot access the worker request file securely. |

## Reviewability

- Files to inspect: `src/loom/pipeline/execution/continuation.py`, `src/loom/pipeline/execution/stage_worker.py`, `src/loom/pipeline/execution/authority_adapter.py`, `src/loom/pipeline/executors/subprocess.py`, `src/loom/cli/stage.py`, `src/loom/cli/stage_job.py`, `src/loom/cli/prepared_run.py`, and related tests.
- Scope-control checks: no private authority repository imports in runtime clients, no SLURM live behavior migration, no offline evidence writer, and no weakening of Phase 11 strict online authority resolution.

## Implementation Steps

1. Inventory generated local command paths and confirm which commands carry authority config versus per-attempt fencing metadata.
2. Add focused tests for authority-backed direct stage worker validation and stale/missing fencing behavior.
3. Add subprocess execution tests proving generated `loom stage run` commands carry authority config and final mutations remain authority-backed.
4. Add command-level tests for `loom stage-job run` and `loom prepared-run continue` with service-backed authority configs and fail-closed diagnostics.
5. Tighten implementation only where tests expose a concrete continuation gap.
6. Run targeted checks while developing, then `make validate-pr` and `make test-summary` before PR preparation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_execution_api.py`
- Required assertions or deferral reason: continuation/runtime modules do not import FastAPI, uvicorn, or private authority repository modules.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/execution/test_authority_adapter.py`, `tests/unit/loom/pipeline/execution/test_stage_worker.py`, `tests/unit/loom/pipeline/execution/test_prepared_run_continue.py`, `tests/unit/loom/pipeline/executors/test_subprocess_executor.py`, `tests/unit/loom/cli/test_stage_cli.py`, `tests/unit/loom/cli/test_stage_job_cli.py`, `tests/unit/loom/cli/test_prepared_run_cli.py`
- Required assertions or deferral reason: handoff metadata, stale/missing fencing rejection, subprocess command authority args, and CLI continuation error mapping.

### Contract Suite

- Status: required
- Expected paths: continuation/stage worker contract coverage where available
- Required assertions or deferral reason: command handoff shape and fenced terminal mutation behavior remain compatible with public extension contracts.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_subprocess_executor_integration.py`, `tests/integration/pipeline/test_stage_worker_integration.py`, `tests/integration/pipeline/test_stage_job_continuation.py`, `tests/integration/config/test_cli_run.py`
- Required assertions or deferral reason: local/subprocess split-process runs use explicit service authority and produce expected local artifacts while authority truth owns lifecycle/output mutation.

### E2E Suite

- Status: required when practical
- Expected paths: `tests/e2e/test_cli_core.py`
- Required assertions or deferral reason: existing subprocess CLI smoke should remain green with explicit authority args; add focused assertions only if needed.

### Opt-In Suites

- Status: deferred
- Markers affected: SLURM live and scheduler process tests
- Required assertions or deferral reason: Phase 13 owns live scheduler migration.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/execution src/loom/pipeline/executors/subprocess.py src/loom/cli/stage.py src/loom/cli/stage_job.py src/loom/cli/prepared_run.py tests/unit/loom/pipeline/execution/test_authority_adapter.py tests/unit/loom/pipeline/execution/test_stage_worker.py tests/unit/loom/pipeline/executors/test_subprocess_executor.py tests/unit/loom/cli/test_stage_cli.py tests/unit/loom/cli/test_stage_job_cli.py tests/unit/loom/cli/test_prepared_run_cli.py tests/integration/pipeline/test_stage_worker_integration.py tests/integration/pipeline/test_subprocess_executor_integration.py tests/integration/pipeline/test_stage_job_continuation.py
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/execution src/loom/pipeline/executors/subprocess.py src/loom/cli/stage.py src/loom/cli/stage_job.py src/loom/cli/prepared_run.py tests/unit/loom/pipeline/execution/test_authority_adapter.py tests/unit/loom/pipeline/execution/test_stage_worker.py tests/unit/loom/pipeline/executors/test_subprocess_executor.py tests/unit/loom/cli/test_stage_cli.py tests/unit/loom/cli/test_stage_job_cli.py tests/unit/loom/cli/test_prepared_run_cli.py tests/integration/pipeline/test_stage_worker_integration.py tests/integration/pipeline/test_subprocess_executor_integration.py tests/integration/pipeline/test_stage_job_continuation.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/execution/test_authority_adapter.py tests/unit/loom/pipeline/execution/test_stage_worker.py tests/unit/loom/pipeline/executors/test_subprocess_executor.py tests/unit/loom/cli/test_stage_cli.py tests/unit/loom/cli/test_stage_job_cli.py tests/unit/loom/cli/test_prepared_run_cli.py tests/integration/pipeline/test_stage_worker_integration.py tests/integration/pipeline/test_subprocess_executor_integration.py tests/integration/pipeline/test_stage_job_continuation.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Implementation Summary

- Confirmed the local/subprocess authority continuation behavior is already implemented through the Phase 11 runtime hooks: worker requests persist `authority_attempt` fencing metadata, stage workers validate that metadata before execution, stage jobs renew authority-backed leases before terminal mutation, subprocess commands propagate authority configuration, and prepared-run continuation creates authority-backed stores before failing closed.
- Added focused stage-worker coverage for valid fencing, missing `authority_attempt` metadata, and stale/foreign fencing-token rejection before executor invocation.
- Tightened subprocess command coverage to assert managed-service authority config propagation, including backend/profile/endpoint/workspace/reference arguments.
- Added CLI tests proving `loom stage run`, `loom stage-job run`, and `loom prepared-run continue` route explicit authority config and fencing data through their continuation entrypoints.
- Extended the supervisor-backed e2e smoke with a subprocess run against an online authority endpoint and verified the local worker result materialization remains available after authority-owned lifecycle mutation.
- No production code changes were required in this phase; the smallest maintainable diff was to lock down the existing local/subprocess continuation paths with regression coverage.

## Validation Results

Targeted validation:

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check ...` | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pyright ...` | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/execution/test_stage_worker.py tests/unit/loom/pipeline/executors/test_subprocess_executor.py tests/unit/loom/cli/test_stage_cli.py tests/unit/loom/cli/test_stage_job_cli.py tests/unit/loom/cli/test_prepared_run_cli.py tests/unit/loom/pipeline/execution/test_authority_adapter.py` | passed, 49 tests in 6.78s |
| `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/e2e/test_authority_supervisor_cli.py` | passed, 1 test in 2.97s |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_subprocess_executor_integration.py tests/integration/pipeline/test_stage_worker_integration.py tests/integration/pipeline/test_stage_job_continuation.py` | passed, 11 tests in 7.75s |

PR gate validation:

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | passed; Ruff, Pyright, config-extra harness, and package build completed successfully |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | passed; package 69 passed/1 skipped, unit 948 passed/1 skipped, contract 146 passed/2 skipped, integration 127 passed/8 skipped/10 deselected, e2e 39 passed/2 deselected, config-extra 422 passed/1332 deselected |

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted validation and full PR gates passed without exposing implementation or coverage gaps
- PR review: used; managing-agent automated review on 2026-05-12 found no blocking findings, confirmed the PR targets `develop`, and confirmed the diff is limited to Phase 12 docs/tests
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-12.
- Implementation summary: completed; Phase 12 adds regression coverage around existing authority-backed local/subprocess continuation behavior and intentionally avoids unnecessary production rewrites.
- Validation: targeted checks, `make validate-pr`, and `make test-summary` passed on 2026-05-12.
- PR: opened as <https://github.com/samcantrill/loom/pull/130> targeting
  `develop` from `codex/authority-worker-continuations`; target verified after
  creation.
- Automated review: completed by managing agent on 2026-05-12 with no blocking
  findings; `git diff --check origin/develop...HEAD` passed, and review
  confirmed no production runtime files changed.
- CI: pending at time of this artifact update.
- Stack maintenance: none yet; this is a root phase branch targeting `develop`.
