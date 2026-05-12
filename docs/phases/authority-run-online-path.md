# Phase 11 Execution Plan: Python Runner And `loom run` Online Path

## Metadata

- Status: phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 11: Python Runner And loom run Online Path`
- Branch: `codex/authority-run-online-path`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-run-online-path`
- Phase execution plan path: `docs/phases/authority-run-online-path.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 11 - Python Runner And `loom run` Online Path
- Stack predecessor: none; Phase 10 merged in PR #128 and is recorded in the plan
- Base branch: `develop` at `89ca3c3`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Draft pass: completed by managing agent on 2026-05-12
- Refine pass: not needed before implementation; scope is bounded by the v10 phase and current source review
- Blockers: none; implementation may begin from this phase execution plan.

## Objective

Move the primary Python runner and `loom run` online execution path from the legacy service-manager authority adapter onto strict resolver-backed HTTP authority mutation, while preserving local DAG orchestration, local artifact/materialization files, and the existing phase boundary that leaves worker continuation and SLURM-specific migration to later phases.

## Source Findings

- `create_authority_backed_serial_run_store()` now resolves HTTP authority references, but still rejects them with `authority_factory.http_store_adapter_deferred`.
- `AuthorityClient` already sends run admission/open/transition, stage transition, attempt allocation, and output commit requests to FastAPI mutation routes.
- The FastAPI mutation service also has routes for controller/stage lease renew/release/fail and submitted-operation read/write/list, but `AuthorityClient` does not expose those calls yet.
- `AuthorityBackedSerialRunStore` is the runner-facing local-plus-authority adapter. It can be reused if an HTTP-backed `PerRunAuthorityStore` supplies the same authoritative methods.
- `PipelineRunner` must keep local path helpers for artifacts, logs, worker request files, config snapshots, and provenance, so this phase should not replace local materialization with remote storage.
- `append_event()` currently writes audit events through the per-run authority store before writing local events, but the HTTP mutation protocol does not yet expose audit-event routes. Runner lifecycle authority mutation should not be blocked on adding a broad audit API in this phase.

## In Scope

- Add an HTTP client-backed per-run authority adapter that satisfies the runner methods used by `AuthorityBackedSerialRunStore`.
- Extend `AuthorityClient` for existing mutation routes needed by primary local runner execution: controller/stage lease renew, release, fail, and submitted-operation helpers where required by the adapter surface.
- Reuse strict resolver/readiness checks from Phase 10 before constructing HTTP-backed runner stores.
- Wire HTTP authority references in `create_authority_backed_serial_run_store()` instead of rejecting them.
- Keep `loom run` online mode on the same central factory so missing authority still fails closed and ready HTTP authority endpoints execute through service-owned mutation.
- Surface authority config/source facts in persisted runtime metadata or run metadata where already available without inventing a new diagnostics subsystem.
- Add unit, contract, integration, and e2e coverage for fail-closed missing authority, HTTP-backed mutation call sequencing, and a deterministic online `loom run` smoke against a repository-backed authority.

## Out Of Scope

- `loom stage run`, `loom stage-job run`, prepared-run continuation, and subprocess worker migration.
- SLURM live submission or submitted worker migration.
- Workspace coordination service API, counters, sweeps, resource leases, or admission policy changes.
- Offline evidence writing or import.
- A general audit-event HTTP API, except for documenting any temporary local-only event behavior.
- Remote artifact storage or remote payload transfer.

## Assumptions

- The current FastAPI mutation routes are the intended service boundary for Phase 11 runner lifecycle mutation.
- Local run directories remain the materialization and artifact/log store for this phase.
- HTTP authority readiness can provide capability facts; if a ready endpoint does not expose enough capabilities, runner preflight should reject it before executing stages.
- Audit events may remain local-only during this phase because the source plan calls out lifecycle mutations, and no HTTP audit route exists yet.
- Explicit `authority_store=` injection remains the test/custom integration escape hatch and should not be routed through HTTP resolution.

## Scope Contract

This phase may add a client-backed authority adapter and extend repository-free HTTP client calls. It must not import FastAPI, uvicorn, or the private authority repository from runner/store client code. It must not restore hidden endpoint-less service startup, add direct database runtime mutation, or change scheduler/worker semantics.

## Design Impact

- Maintainability: keeps the existing runner adapter boundary and swaps the authority implementation behind it instead of rewriting DAG orchestration.
- Extensibility: creates the HTTP-backed `PerRunAuthorityStore` surface later phases can reuse for continuation and scheduler paths.
- Reviewability: separates client/adapter behavior from CLI plumbing and test fixture updates.
- Boundary safety: public runtime code should depend on protocol/client/store ports only, not server repository modules.

## Future Compatibility

The adapter should leave room for Phase 12/13 worker and SLURM migration to use the same HTTP authority mutation calls and for later phases to add coordination/resource/offline APIs without altering the local runner orchestration model.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Rewrite `PipelineRunner` to call `AuthorityClient` directly everywhere | Higher risk and duplicates the existing `AuthorityBackedSerialRunStore` lifecycle mapping. |
| Keep HTTP endpoints rejected until every worker path can migrate together | Blocks the Phase 11 acceptance criteria for online `loom run`. |
| Route runner mutations through private repository objects in process | Violates the v10 service-boundary goal and import-boundary requirements. |
| Add broad audit-event protocol routes now | Useful later, but not necessary for lifecycle mutation ownership and would broaden phase scope. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Audit events may remain local-only for HTTP-backed runner stores | No HTTP audit route exists and lifecycle mutation is the Phase 11 target. | A later authority audit/read-model phase or Phase 13 worker migration needs service audit history. |
| Worker and SLURM paths still use legacy local/service-manager assumptions | Dedicated later phases own continuation and scheduler migration. | Phase 12 or Phase 13 starts. |
| HTTP adapter initially covers the runner-required `PerRunAuthorityStore` subset | Keeps the PR reviewable while satisfying local online execution. | A later phase requires additional read-model or recovery endpoints. |

## Reviewability

- Files to inspect: `src/loom/pipeline/stores/authority_client.py`, any new client-backed store module, `src/loom/pipeline/execution/authority_adapter.py`, `src/loom/cli/run.py`, runner tests, and authority FastAPI integration tests.
- Scope-control checks: no private repository imports outside authority server code, no FastAPI imports in pipeline store/execution modules, no subprocess/SLURM behavior migration, no hidden service startup, and no offline evidence implementation.

## Implementation Steps

1. Extend the repository-free `AuthorityClient` for existing lease and submitted-operation mutation routes needed by the runner adapter.
2. Add an HTTP client-backed `PerRunAuthorityStore` adapter that translates accepted protocol responses into authority store models and rejected protocol responses into `AuthorityStoreError`-family failures.
3. Use readiness/capability facts from strict HTTP resolution when constructing the adapter, and keep explicit `authority_store=` injection unchanged.
4. Wire HTTP authority references in `create_authority_backed_serial_run_store()` for the primary local runner and `loom run` online path.
5. Persist compact authority source/config facts in existing run/runtime metadata where they are already written.
6. Add focused tests for client method payloads, adapter response mapping, `loom run` fail-closed behavior, and a deterministic repository-backed HTTP online run.
7. Run targeted tests while developing, then `make validate-pr` and `make test-summary` before PR preparation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_store_api.py`
- Required assertions or deferral reason: runner/store client modules do not import FastAPI or private repository modules; new public exports, if any, are intentional.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_authority_client.py`, new or updated HTTP adapter tests, `tests/unit/loom/pipeline/execution/test_authority_adapter.py`, `tests/unit/loom/cli/test_run.py`
- Required assertions or deferral reason: client method paths and payloads, accepted/rejected response mapping, missing authority fail-closed behavior, and no hidden startup.

### Contract Suite

- Status: required
- Expected paths: authority protocol/client contract tests where available
- Required assertions or deferral reason: lifecycle call ordering and protocol rejection handling match the existing authority contract.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/authority/test_mutation_api.py`, `tests/integration/pipeline/test_local_execution.py`, `tests/integration/config/test_cli_run.py`
- Required assertions or deferral reason: repository-backed FastAPI authority accepts primary online `loom run` lifecycle mutation and local DAG execution still produces artifacts/logs/provenance.

### E2E Suite

- Status: required
- Expected paths: one small deterministic CLI online smoke, likely in `tests/e2e/test_cli_core.py` or `tests/e2e/test_local_pipeline_run.py`
- Required assertions or deferral reason: online `loom run` succeeds with an explicit ready authority endpoint and fails closed without one.

### Opt-In Suites

- Status: deferred
- Markers affected: external scheduler/supervisor process tests
- Required assertions or deferral reason: a live supervisor process smoke may be useful but should remain opt-in unless the deterministic in-process/stdlib HTTP coverage cannot prove the runner path.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores src/loom/pipeline/execution/authority_adapter.py src/loom/cli/run.py tests/unit/loom/pipeline/stores/test_authority_client.py tests/unit/loom/pipeline/execution/test_authority_adapter.py tests/unit/loom/cli/test_run.py tests/integration/authority/test_mutation_api.py tests/integration/pipeline/test_local_execution.py tests/integration/config/test_cli_run.py
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/stores src/loom/pipeline/execution/authority_adapter.py src/loom/cli/run.py tests/unit/loom/pipeline/stores/test_authority_client.py tests/unit/loom/pipeline/execution/test_authority_adapter.py tests/unit/loom/cli/test_run.py tests/integration/authority/test_mutation_api.py tests/integration/pipeline/test_local_execution.py tests/integration/config/test_cli_run.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_authority_client.py tests/unit/loom/pipeline/execution/test_authority_adapter.py tests/unit/loom/cli/test_run.py tests/integration/authority/test_mutation_api.py tests/integration/pipeline/test_local_execution.py tests/integration/config/test_cli_run.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Refinement And Review Budget Status

- Phase implementation refinement: used by managing agent on 2026-05-12 for the targeted audit-event payload normalization exposed by the HTTP-backed runner test
- PR review: completed by managing agent on 2026-05-12 with no blocking findings; PR target verified as `develop` and CI `checks` passed
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-12.
- Implementation summary: added HTTP authority lease/submitted-operation client methods, captured HTTP readiness facts during authority resolution, added an `AuthorityClientBackedPerRunAuthorityStore`, wired HTTP authority references into `create_authority_backed_serial_run_store()`, kept HTTP-backed audit events local-only pending a service route, and aligned the supervisor CLI smoke with the existing optional-config test policy.
- Validation:
  - Targeted Ruff and Pyright passed for changed source and tests.
  - Targeted pytest passed: `tests/unit/loom/pipeline/stores/test_authority_client.py`, `tests/unit/loom/pipeline/execution/test_authority_adapter.py`, `tests/integration/authority/test_mutation_api.py`, `tests/integration/pipeline/test_local_execution.py`, and `tests/e2e/test_authority_supervisor_cli.py` reported 26 passed and 2 skipped in the no-extra environment.
  - `tests/package/test_pipeline_store_api.py` passed with 11 tests.
  - `make validate-pr` passed outside the restricted sandbox: Ruff, Pyright, default harness with 1297 passed / 19 skipped / 14 deselected, config-extra harness with 422 passed / 1326 deselected, and `uv build`.
  - `make test-summary` passed outside the restricted sandbox and wrote `build/test-summary.md`: package 69 passed / 1 skipped; unit 942 passed / 1 skipped; contract 146 passed / 2 skipped; integration 127 passed / 8 skipped / 10 deselected; e2e 39 passed / 2 deselected; config-extra 422 passed / 1326 deselected.
  - Restricted sandbox note: FastAPI `TestClient` paths hang under the sandbox thread/network isolation, so suite gates that exercise those paths were run with approved escalation.
- Review and CI: automated manager review found no blocking scope, import-boundary, or validation issues; PR #129 targets `develop` from `codex/authority-run-online-path`; GitHub CI `checks` passed before merge evaluation.
- Stack maintenance: none yet; this is a root phase branch targeting `develop`.
