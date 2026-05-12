# Phase 13 Execution Plan: SLURM Live Operation Paths

## Metadata

- Status: phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 13: SLURM Live Operation Paths`
- Branch: `codex/authority-slurm-live-paths`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-slurm-live-paths`
- Phase execution plan path: `docs/phases/authority-slurm-live-paths.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 13 - SLURM Live Operation Paths
- Stack predecessor: none; Phase 12 merged in PR #130 and is recorded in the plan
- Base branch: `develop` at `6474830`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Draft pass: completed by managing agent on 2026-05-12
- Refine pass: not needed before implementation; source inventory identifies concrete fail-closed gaps
- Blockers: none; implementation may begin from this phase execution plan.

## Objective

Move SLURM live submission, scheduler status snapshot persistence, and submitted-job cancellation onto explicit authority-backed mutation boundaries while preserving deterministic local/fake-SLURM tests and keeping deferred finalization separate from true offline import.

## Source Findings

- `loom run --executor slurm-*` already creates an authority-backed run store and calls `_require_slurm_live_authority()` before writing run state or submitting with `sbatch`.
- `submit_single_job_slurm()` and `submit_afterok_slurm()` still accept any local `RunStore`, so direct API callers can silently mutate only local submitted-operation and lifecycle state.
- `inspect_slurm_job_status()` and `cancel_slurm_jobs()` default to authority-backed stores from environment, but explicit `run_store=` callers can still pass local stores while the helpers persist status snapshots, submitted-operation updates, and cancellation lifecycle changes.
- SLURM dry-run planning already forwards the selected authority config into `prepared-run continue` and `stage-job run` generated commands.
- Phase 12 made `stage-job run` create authority-backed stores, materialize submitted worker requests, and validate/renew authority fencing before worker execution when the selected store supports validation.
- `RequiredAuthorityCapability.SLURM_LIVE_WORKER` currently allows the `direct_database` deployment profile; the v10 plan requires this profile to be reserved/rejected for runtime mutation.
- The local service fixture and repository-backed FastAPI service do not claim hosted multi-host semantics, so Phase 13 should keep CLI live admission strict and test lower-level service-owned mutation with deterministic authority-backed stores rather than pretending default local service is a production SLURM authority.

## In Scope

- Require authority-backed run-store mutation for live SLURM submission, status snapshot persistence, and cancellation helpers.
- Reject direct-database deployment profile admission for `SLURM_LIVE_WORKER`.
- Preserve deferred-finalization as a separate weaker profile and keep it out of live-worker admission.
- Keep generated SLURM command handoffs carrying authority config and ensure tests cover the expected command shape for single-job and afterok paths.
- Update unit/integration/e2e tests to use authority-backed stores for live mutation helpers and to assert fail-closed behavior when local stores are passed.
- Keep status/cancel/read-model wording changes narrowly limited to Phase 13 authority-source facts needed for correctness.

## Out Of Scope

- Offline evidence manifest writer and offline import transaction.
- Global scheduler, queueing, fairness, or resource admission leases.
- Workspace coordination service migration.
- Real-cluster default validation or environment-dependent SLURM tests.
- Implementing prepared whole-run replay for single-job SLURM jobs.
- Broad diagnostics/source-label UX beyond live SLURM authority facts.

## Assumptions

- Authority-backed store shape is the enforcement boundary; tests may use `SQLitePerRunAuthorityStore` behind `AuthorityBackedSerialRunStore` for deterministic local authority semantics while CLI live admission remains stricter.
- Remote SLURM workers can receive authority config through generated command arguments and rely on submitted-stage metadata plus service state to materialize/renew per-attempt fencing at execution time.
- Single-job live submission remains a submitted-operation path with fail-closed prepared-run continuation until a later safe replay design exists.
- Local manifests, scripts, logs, and worker result files remain materialization artifacts; service-backed authority owns lifecycle and submitted-operation truth.

## Scope Contract

This phase may edit SLURM live submission/status/cancellation helpers, authority capability admission, SLURM command-generation tests, CLI live admission tests, and related fixtures. It must not implement offline import, resource admission, workspace coordination, real-cluster-only behavior, or server-private repository imports in runtime clients.

## Design Impact

- Maintainability: enforces one explicit authority-backed boundary for all live SLURM mutation helpers instead of relying only on CLI callers.
- Extensibility: keeps command handoff authority config reusable for future scheduler adapters and remote worker transports.
- Reviewability: changes are concentrated in SLURM live modules, authority admission, and deterministic tests.
- Safety: local-only stores fail before scheduler submission, status-snapshot persistence, or cancellation mutation.

## Future Compatibility

The fail-closed helper boundary should remain compatible with future hosted authorities and resource admission because it validates authority-backed mutation before any scheduler-side side effect is recorded.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep direct API helpers permissive and rely on CLI admission only | Library callers could still produce local-only live mutation state. |
| Mark the local FastAPI service as multi-host capable for tests | That would weaken the meaning of live-worker admission and overstate deployment safety. |
| Put lease/fencing facts directly into generated SLURM command lines | Stage-job continuation can derive and validate fencing from submitted-stage metadata and backend authority state without exposing tokens earlier than needed. |
| Fold prepared-run replay into Phase 13 | Safe whole-run replay is broader than SLURM live authority migration and remains intentionally fail-closed. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Single-job SLURM submitted commands still target fail-closed prepared-run continuation | Whole-run replay requires a dedicated authoritative replay design. | A later continuation/replay phase defines safe payloads. |
| Local service fixture remains unsuitable for production-style live-worker admission | It proves endpoint semantics but not hosted multi-host reachability. | A hosted or allocation-scoped service fixture is introduced. |
| Status/cancel source labels remain compact | Phase 14 owns broader diagnostics/read-only source-label UX. | Phase 14 starts. |

## Reviewability

- Files to inspect: `src/loom/pipeline/executors/slurm/submission.py`, `src/loom/pipeline/executors/slurm/status.py`, `src/loom/pipeline/executors/slurm/cancellation.py`, `src/loom/pipeline/stores/admission.py`, SLURM tests, and CLI live-flow tests.
- Scope-control checks: no private authority repository imports in SLURM runtime modules, no offline import writer, no resource admission lease implementation, no weakening of strict CLI live authority admission.

## Implementation Steps

1. Add a small SLURM live authority guard and call it before live submission, status snapshot persistence, and cancellation mutation.
2. Tighten `SLURM_LIVE_WORKER` profile admission to reject `direct_database` and update admission/deployment tests.
3. Update live submission unit/integration helpers to use authority-backed stores and add explicit local-store fail-closed tests.
4. Add or update status/cancellation tests proving explicit local stores fail closed while authority-backed fixtures still mutate through the authority boundary.
5. Add generated-command assertions for authority config propagation in single-job and afterok SLURM scripts if current coverage is insufficient.
6. Run targeted Ruff, Pyright, and pytest suites, then `make validate-pr` and `make test-summary` before PR preparation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: SLURM runtime modules do not import FastAPI, uvicorn, or private authority repository modules.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_authority_config_admission.py`, `tests/unit/loom/pipeline/stores/test_authority_deployment.py`, `tests/unit/loom/pipeline/executors/slurm/test_slurm_submission.py`, `tests/unit/loom/pipeline/executors/slurm/test_slurm_status.py`, `tests/unit/loom/pipeline/executors/slurm/test_slurm_cancellation.py`, `tests/unit/loom/pipeline/executors/slurm/test_slurm_scripts.py`
- Required assertions or deferral reason: direct-database live-worker rejection, authority-backed live mutation requirement, generated command authority args, status/cancel guard behavior, and preserved deferred-finalization separation.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_cli_run_slurm_contract.py`, `tests/contracts/test_cli_status_slurm_contract.py`, `tests/contracts/test_cli_cancel_slurm_contract.py`, `tests/contracts/test_slurm_manifest_contract.py`
- Required assertions or deferral reason: public CLI result schemas and manifest contracts stay stable while backend metadata gains only additive authority facts.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_slurm_live_single_job.py`, `tests/integration/pipeline/test_slurm_live_afterok.py`, `tests/integration/pipeline/test_slurm_scheduler_status.py`, `tests/integration/pipeline/test_slurm_cancellation_integration.py`, `tests/integration/pipeline/test_slurm_dry_run_planning.py`
- Required assertions or deferral reason: deterministic fake-SLURM live operations use authority-backed stores and preserve manifest/local artifact behavior.

### E2E Suite

- Status: required when practical
- Expected paths: `tests/e2e/test_cli_slurm_dry_run.py`, `tests/e2e/test_cli_slurm_live_operations_flow.py`, `tests/e2e/test_cli_slurm_scheduler_status.py`, `tests/e2e/test_cli_slurm_cancellation.py`
- Required assertions or deferral reason: CLI dry-run command handoffs preserve authority args; CLI live flow remains fail-closed for the local service fixture unless a true live-worker authority is selected.

### Opt-In Suites

- Status: deferred
- Markers affected: real SLURM cluster/live scheduler tests
- Required assertions or deferral reason: default validation must remain deterministic and not require a real cluster.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/executors/slurm src/loom/pipeline/stores/admission.py tests/unit/loom/pipeline/stores/test_authority_config_admission.py tests/unit/loom/pipeline/stores/test_authority_deployment.py tests/unit/loom/pipeline/executors/slurm tests/integration/pipeline/test_slurm_live_single_job.py tests/integration/pipeline/test_slurm_live_afterok.py tests/integration/pipeline/test_slurm_scheduler_status.py tests/integration/pipeline/test_slurm_cancellation_integration.py tests/e2e/test_cli_slurm_live_operations_flow.py tests/e2e/test_cli_slurm_dry_run.py
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/executors/slurm src/loom/pipeline/stores/admission.py tests/unit/loom/pipeline/stores/test_authority_config_admission.py tests/unit/loom/pipeline/stores/test_authority_deployment.py tests/unit/loom/pipeline/executors/slurm tests/integration/pipeline/test_slurm_live_single_job.py tests/integration/pipeline/test_slurm_live_afterok.py tests/integration/pipeline/test_slurm_scheduler_status.py tests/integration/pipeline/test_slurm_cancellation_integration.py tests/e2e/test_cli_slurm_live_operations_flow.py tests/e2e/test_cli_slurm_dry_run.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_authority_config_admission.py tests/unit/loom/pipeline/stores/test_authority_deployment.py tests/unit/loom/pipeline/executors/slurm tests/integration/pipeline/test_slurm_live_single_job.py tests/integration/pipeline/test_slurm_live_afterok.py tests/integration/pipeline/test_slurm_scheduler_status.py tests/integration/pipeline/test_slurm_cancellation_integration.py
UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/e2e/test_cli_slurm_live_operations_flow.py tests/e2e/test_cli_slurm_dry_run.py tests/e2e/test_cli_slurm_scheduler_status.py tests/e2e/test_cli_slurm_cancellation.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted validation passed after local fixes in the managing pass
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-12.
- Implementation summary: added a shared SLURM live authority fact helper, required service-profile authority-backed stores before live submission/status/cancellation mutation, recorded authority mutation-source metadata for status and cancellation snapshots, rejected `direct_database` for live-worker admission, and updated SLURM unit/integration/e2e fixtures to prove fail-closed local-store behavior plus authority argument propagation.
- Validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/executors/slurm src/loom/pipeline/stores/admission.py tests/unit/loom/pipeline/stores/test_authority_config_admission.py tests/unit/loom/pipeline/stores/test_authority_deployment.py tests/unit/loom/pipeline/executors/slurm tests/integration/pipeline/test_slurm_dry_run_planning.py tests/integration/pipeline/test_slurm_live_single_job.py tests/integration/pipeline/test_slurm_live_afterok.py tests/integration/pipeline/test_slurm_scheduler_status.py tests/integration/pipeline/test_slurm_cancellation_integration.py tests/e2e/test_cli_slurm_live_operations_flow.py tests/e2e/test_cli_slurm_dry_run.py tests/e2e/test_cli_slurm_scheduler_status.py tests/e2e/test_cli_slurm_cancellation.py` - passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/executors/slurm src/loom/pipeline/stores/admission.py tests/unit/loom/pipeline/stores/test_authority_config_admission.py tests/unit/loom/pipeline/stores/test_authority_deployment.py tests/unit/loom/pipeline/executors/slurm tests/integration/pipeline/test_slurm_live_single_job.py tests/integration/pipeline/test_slurm_live_afterok.py tests/integration/pipeline/test_slurm_scheduler_status.py tests/integration/pipeline/test_slurm_cancellation_integration.py tests/e2e/test_cli_slurm_live_operations_flow.py tests/e2e/test_cli_slurm_dry_run.py` - passed after replacing a direct capability attribute access with a typed `getattr`.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_authority_config_admission.py tests/unit/loom/pipeline/stores/test_authority_deployment.py tests/unit/loom/pipeline/executors/slurm tests/integration/pipeline/test_slurm_live_single_job.py tests/integration/pipeline/test_slurm_live_afterok.py tests/integration/pipeline/test_slurm_scheduler_status.py tests/integration/pipeline/test_slurm_cancellation_integration.py tests/integration/pipeline/test_slurm_dry_run_planning.py` - 100 passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/e2e/test_cli_slurm_live_operations_flow.py tests/e2e/test_cli_slurm_dry_run.py tests/e2e/test_cli_slurm_scheduler_status.py tests/e2e/test_cli_slurm_cancellation.py` - passed outside the restricted sandbox, 14 passed. The in-sandbox run failed because `LocalAuthorityService` could not open multiprocessing sockets.
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` - passed; Ruff, Pyright, default suite, config-extra suite, and build completed successfully.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` - passed; `build/test-summary.md` reports package 69 passed/1 skipped, unit 954 passed/1 skipped, contract 146 passed/2 skipped, integration 127 passed/8 skipped/10 deselected, e2e 39 passed/2 deselected, and config-extra 422 passed/1338 deselected.
- Stack maintenance: none yet; this is a root phase branch targeting `develop`.
