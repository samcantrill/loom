# Phase 10 Execution Plan: Strict Resolver And Factory Adoption

## Metadata

- Status: refined phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 10: Strict Resolver And Factory Adoption`
- Branch: `codex/authority-resolver-adoption`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-resolver-adoption`
- Phase execution plan path: `docs/phases/authority-resolver-adoption.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 10 - Strict Resolver And Factory Adoption
- Stack predecessor: none; Phase 9 merged in PR #127 and is recorded in the plan
- Base branch: `develop` at `ccd7cff`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 11 migrates `PipelineRunner` and `loom run`; Phases 12 and 13 migrate continuation, worker, and SLURM paths.
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Plan quality gate loop budget: consumed; do not reopen unless the v10 implementation plan changes materially
- Draft pass: completed by managing agent on 2026-05-11
- Refine pass: completed by managing agent on 2026-05-11
- Setup limitations: branch and worktree were created from local `develop` at `ccd7cff`, after Phase 9 merge metadata was pushed
- Blockers: none; implementation may begin from this refined phase execution plan.

## Objective

Adopt the strict authority resolver in central authority factory paths so mutation-capable online factories fail closed without hidden co-located service startup, validate explicit endpoint or registry facts before returning clients/stores, reject direct-database runtime mutation, and preserve explicitly non-authoritative offline selection without migrating the runner, workers, SLURM, workspace coordination, or offline evidence writer.

## Full-Plan Context

Phases 1, 8, and 9 created the resolver contracts, workspace registry records, and explicit supervisor lifecycle. Phase 10 is the first behavior change that removes old implicit authority convenience from shared factories. Later runtime phases own user-facing `loom run`, worker, continuation, and SLURM migrations, so this phase must keep adoption at the factory/resolver plumbing layer.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 9 merged to `develop` in PR #127
- Why this base branch is correct: the implementation plan records Phase 9 merged, the control checkout was fast-forwarded to `develop`, and no unmerged predecessor branch exists
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete the phase branch and worktree after merge if no successor phase branch depends on it

## Source Phase Summary

- Goal: adopt strict authority resolver outcomes in shared Python factories and CLI factory paths without migrating every runtime entrypoint yet.
- Required scope: central authority/run-store factory resolution, explicit endpoint and registry validation, direct-database rejection, offline-first outcomes where supported, CLI/diagnostic plumbing for resolver guidance, and test fixture updates.
- Required checkpoints: no hidden co-located service startup, no direct private DB mutation through runtime factories, stale or unavailable registry records fail closed, and remaining runtime entrypoints that bypass these factories are inventoried.
- Acceptance criteria: central factories fail closed for missing/invalid online authority, endpoint/registry references are validated before clients/stores are returned, direct-database selections reject with migration guidance, offline-first selection is explicit and non-authoritative where supported, and diagnostics point to concrete `loom authority` commands.

## Current Source And Harness Findings

- `src/loom/pipeline/stores/authority_resolution.py` already defines the side-effect-free resolver result, failure kinds, service-health facts, registry hints, direct-database rejection, and next-step wording.
- `src/loom/pipeline/stores/authority_registry.py` can validate `.loom/authority/current.json` records and return resolver hints and service-health facts. It does not perform live network readiness checks.
- `src/loom/authority/supervisor.py` writes HTTP FastAPI registry records after readiness and exposes private `_fetch_readiness` logic that should not be imported by store factories.
- `src/loom/pipeline/stores/authority_client.py` provides a repository-free HTTP protocol client, but it does not yet expose readiness probing or a strict resolver-backed construction helper.
- `src/loom/pipeline/stores/factory.py:create_run_store()` currently defaults to `AuthorityConfig()` and can indirectly start the shared co-located manager service through `create_service_authority_store()`.
- `src/loom/pipeline/execution/authority_adapter.py:create_authority_backed_serial_run_store()` also defaults to `AuthorityConfig()` and can start the shared co-located service when no explicit authority store or endpoint is supplied.
- `src/loom/pipeline/stores/service_authority.py:create_service_authority_store()` starts a shared co-located manager service when `co_located_service` has no endpoint. Phase 10 must stop factory paths from relying on that hidden startup; explicit test/service configs may still use `LocalAuthorityService.start().config()`.
- `src/loom/cli/authority.py` has hidden parser support for `--authority-mode` and `--offline-first`, but most current commands call `add_authority_options()` without enabling those options.

## In-Scope Work

- Add a small strict authority factory/resolution adapter in `loom.pipeline.stores` that composes `AuthorityConfig`, optional workspace registry validation, optional live HTTP readiness or manager-service health facts, and `resolve_authority()`.
- Add an explicit HTTP authority client factory that returns `AuthorityClient` only after strict resolver success and readiness/health validation.
- Update `create_run_store()` and `create_authority_backed_serial_run_store()` to use strict resolver outcomes before constructing mutation-capable stores, preserving explicit `authority_store=` injection for tests/custom integrations.
- Prevent hidden shared co-located service startup from default factory paths; missing endpoints or missing valid registry records must fail closed with resolver diagnostics.
- Reject `direct_database`, `transitional_sqlite`, and unsupported runtime mutation selections with explicit v10 guidance.
- Preserve explicit offline-first resolution as a non-authoritative outcome. Where an existing factory cannot yet return an offline evidence store, fail with a structured unsupported-offline diagnostic rather than silently mutating local authority state.
- Enable only the CLI/config plumbing needed for central factory consumers to pass resolver mode and authority options; do not convert `loom run`, worker, continuation, or SLURM behavior beyond the shared factory calls they already make.
- Update package, unit, contract, and integration tests and fixtures to select explicit in-memory/test authority stores or explicit service endpoints where they need mutation-capable authority.
- Inventory remaining runtime entrypoints that still bypass strict resolver migration for Phases 11-13.

## Out-of-Scope Work

- Full `PipelineRunner`, `run_pipeline`, and `loom run` online migration.
- Subprocess worker, stage, stage-job, prepared-run continuation, and SLURM live path migration.
- Workspace coordination service API or resource lease/admission behavior.
- Offline evidence writer, offline import, or local evidence store implementation.
- User-global discovery or hosted authority process manager behavior.
- Making HTTP `AuthorityClient` satisfy every current `PerRunAuthorityStore` call needed by runner execution.

## Assumptions

- Strict factory adoption may add an explicit `workspace_root` or resolver-options keyword to factory helpers without changing runner behavior yet; existing callers that need old test behavior should pass `authority_store=` or an explicit service config.
- HTTP readiness probing can use the existing `/ready` protocol endpoint with stdlib HTTP and protocol model parsing, keeping FastAPI imports out of store factories.
- The legacy `LocalAuthorityService` manager remains a deterministic test/helper service when explicitly started and passed by config; the hidden global shared instance should no longer be reached by default factory resolution.
- Offline-first store construction is not broadly supported until Phase 17, so unsupported offline outcomes must be honest and non-mutating.

## Scope Contract

Factory code may resolve, validate, and construct authority clients/stores; it must not start a supervisor, create a hidden state directory, mutate the private repository directly, or treat registry records as sufficient without resolver validation. Missing or invalid online authority must raise an `AuthorityStoreError`-family error carrying resolver diagnostics and actionable next steps.

Explicit `authority_store=` injection remains a trusted test/custom integration escape hatch because authored tests and integrations can supply their own authority implementation. That injection must not weaken strict resolution for config/env/registry-driven runtime factory paths.

HTTP authority client construction may validate readiness and return an `AuthorityClient`, but runner/store migration onto that client is future-phase work. If a run-store factory sees an otherwise valid HTTP authority reference that it cannot yet adapt to the `PerRunAuthorityStore` surface, it should fail explicitly with future-phase guidance rather than falling back to local mutation.

## Design Impact

- Maintainability: centralizes resolver-to-factory glue so later runner and worker phases do not reimplement registry, health, direct-database, and offline checks.
- Extensibility: explicit resolver options and client construction leave room for hosted discovery, future transports, and HTTP client-backed stores without changing call sites again.
- Domain neutrality: diagnostics describe authority service state and offline evidence policy without pipeline-domain assumptions.
- Source-tree boundaries: store factories may depend on resolver, registry, config, protocol, and stdlib HTTP client code, but not FastAPI route modules or the private authority repository.

## Future Compatibility

Phase 10 should make the strict resolver the single entrypoint that Phase 11 can call when moving `PipelineRunner` and `loom run` onto service-backed authority. It should also leave clear unsupported/offline result shapes for Phase 17 instead of inventing a temporary local-authoritative fallback.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep default co-located service startup for compatibility | The v10 plan explicitly removes hidden endpoint-less startup from online mutation paths. |
| Read registry records and trust them without readiness or resolver validation | Stale registry files are hints, not authority truth. |
| Treat direct-database runtime mutation as a compatibility fallback | v10 reserves/rejects direct database mutation through public runtime factories. |
| Migrate `PipelineRunner` and `loom run` in the same PR | Phase 11 owns primary runner/user-path migration and needs a separate review surface. |
| Return local authoritative stores for offline-first mode | Offline-first evidence is non-authoritative and is not implemented until Phase 17. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Some runtime entrypoints may still pass explicit legacy stores after central factories change | Later phases own runner, worker, continuation, and SLURM migrations. | Phase 11-13 execution begins. |
| HTTP `AuthorityClient` readiness validation exists before full run-store adaptation | Phase 10 needs endpoint validation, while Phase 11 owns runner/client mutation flow. | Phase 11 starts service-backed runner mutation. |
| Offline-first selection may be unsupported in existing factories | True offline evidence writer arrives in Phase 17. | Phase 17 adds non-authoritative evidence store/writer behavior. |

## Reviewability

- Expected PR size and shape: one strict factory/resolution adapter, targeted updates to store/execution factories and CLI resolver plumbing, focused fixture updates, tests, phase docs, and PR body.
- Files and areas to inspect: `src/loom/pipeline/stores/authority_resolution.py`, `authority_registry.py` interactions, a new or updated factory helper module, `src/loom/pipeline/stores/factory.py`, `src/loom/pipeline/execution/authority_adapter.py`, `src/loom/cli/authority.py`, and affected factory tests.
- Scope-control checks: no runner orchestration migration, no worker/SLURM handoff changes, no private repository imports in public factories, no supervisor process startup, no user-global discovery, and no offline evidence writer.

## Implementation Steps

1. Add resolver-backed factory options/results and HTTP readiness/registry validation helpers without importing FastAPI or private repository modules.
2. Wire `create_run_store()` and `create_authority_backed_serial_run_store()` through strict resolution while keeping explicit `authority_store=` injection.
3. Add explicit HTTP `AuthorityClient` construction and clear unsupported-adapter diagnostics for run-store factories that cannot yet use HTTP endpoints.
4. Update CLI authority option plumbing only where central factory callers need to pass resolver mode and authority settings.
5. Update tests and fixtures to use explicit authority injection/service endpoints, add coverage for fail-closed missing authority, stale registry, direct-database rejection, offline-first handling, and no hidden startup.
6. Record remaining runtime bypass inventory and run targeted plus full PR validation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_store_api.py`
- Required assertions or deferral reason: public factory helpers do not import FastAPI route modules or private repository modules; exported strict factory/client helpers are intentional.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_authority_resolution.py`, `tests/unit/loom/pipeline/stores/test_service_authority.py`, new or updated strict factory tests, `tests/unit/loom/cli/test_authority.py`
- Required assertions or deferral reason: missing authority fails closed without startup, direct-database rejection uses resolver diagnostics, stale/unavailable registry handling maps correctly, explicit service configs still work, offline-first is non-authoritative/unsupported where no evidence store exists, and CLI namespace parsing can carry resolver mode.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authority_resolution_contract.py`, `tests/contracts/test_run_store_authority_contract.py`
- Required assertions or deferral reason: factory outcomes match Phase 1 resolver categories and public run-store contract remains valid with explicit authority fixtures.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_authority_factory.py`, `tests/integration/authority/test_registry_records.py`, and any integration tests that previously depended on implicit factory startup
- Required assertions or deferral reason: explicit service endpoint configs work, default/missing authority fails closed, registry-derived references are validated, unavailable services fail closed, and tests that need mutation authority use explicit fixtures.

### E2E Suite

- Status: deferred
- Expected paths: not required for this phase
- Required assertions or deferral reason: user-facing `loom run` online migration is Phase 11; Phase 10 only changes central factory behavior.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: no external service, scheduler, hosted manager, or long-running process coverage is required beyond deterministic local endpoint checks.

## Risks

- Removing hidden default startup can break broad tests that accidentally relied on it; fixture changes must be explicit and narrow.
- Mixing HTTP FastAPI endpoints with legacy manager-service stores can create confusing partial support; unsupported paths must be explicit.
- Registry validation must not accidentally accept a stale/unhealthy record because it contains a plausible endpoint.
- Factory errors must preserve resolver diagnostics so CLI/diagnostics phases can reuse them instead of parsing strings.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores src/loom/pipeline/execution/authority_adapter.py src/loom/cli/authority.py tests/unit/loom/pipeline/stores/test_authority_resolution.py tests/unit/loom/pipeline/stores/test_service_authority.py tests/unit/loom/cli/test_authority.py tests/contracts/test_authority_resolution_contract.py tests/contracts/test_run_store_authority_contract.py tests/integration/pipeline/test_authority_factory.py
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/stores src/loom/pipeline/execution/authority_adapter.py src/loom/cli/authority.py tests/unit/loom/pipeline/stores/test_authority_resolution.py tests/unit/loom/pipeline/stores/test_service_authority.py tests/unit/loom/cli/test_authority.py tests/contracts/test_authority_resolution_contract.py tests/contracts/test_run_store_authority_contract.py tests/integration/pipeline/test_authority_factory.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_authority_resolution.py tests/unit/loom/pipeline/stores/test_service_authority.py tests/unit/loom/cli/test_authority.py tests/contracts/test_authority_resolution_contract.py tests/contracts/test_run_store_authority_contract.py tests/integration/pipeline/test_authority_factory.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: strict factory resolution helpers, HTTP readiness/client factory, run-store factory adoption, authority-backed serial factory adoption, CLI parsing/tests, then broad fixture updates.
- Tests to run with each slice: unit resolver/factory tests after helper work, service authority tests after hidden-startup removal, contract run-store tests after fixture updates, integration authority factory tests after registry/endpoint adoption.
- Decisions the executor must not revisit: no hidden startup, no direct-database runtime mutation, no runner/worker/SLURM migration, no private repository imports in public factories, no user-global discovery, and no offline evidence writer.
- Conditions that require stopping for the manager: need to change public resolver failure enums, need to make HTTP `AuthorityClient` implement the full run-store adapter in this phase, or inability to preserve explicit test authority injection without restoring hidden startup.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-11.
- Final phase execution plan: completed by managing agent on 2026-05-11.
- Implementation summary:
  - Added `loom.pipeline.stores.authority_factory` as the strict resolver-to-factory adapter with structured `AuthorityFactoryError`, registry validation, HTTP `/ready` probing, and resolver-backed `AuthorityClient` construction.
  - Routed `create_run_store()` and `create_authority_backed_serial_run_store()` through strict online authority resolution unless a trusted `authority_store=` is injected.
  - Removed endpoint-less hidden co-located service startup from public factory paths; explicit `LocalAuthorityService.start().config()` remains available for tests and custom integrations.
  - Preserved read-only `loom plan` behavior by avoiding mutation-store construction for fresh/non-resume planning, while keeping resume planning on explicit authority resolution.
  - Kept continuation recursive-executor errors ahead of authority construction so invalid executor diagnostics remain stable.
  - Updated run-catalog scanning to avoid hidden service startup for read-only local catalog scans when no explicit authority endpoint is selected.
  - Migrated tests and fixtures that need mutation authority to explicit injected SQLite stores or explicit service configs.
  - Remaining runtime bypass inventory for later phases: `PipelineRunner`, `loom run`, stage worker, prepared-run, stage-job, subprocess, and SLURM paths still use the legacy `AuthorityBackedSerialRunStore` surface and require explicit service configs where they cross process boundaries; HTTP `AuthorityClient` is validated but not yet adapted to the runner mutation surface.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pyright` passed with 0 errors.
  - Targeted non-socket pytest passed: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_authority_factory.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py tests/integration/pipeline/test_run_catalog_compare.py tests/integration/pipeline/test_run_catalog_direct_scan.py tests/integration/pipeline/test_run_catalog_sqlite.py tests/integration/pipeline/test_run_catalog_current_list.py tests/support/slurm_status_fixtures.py tests/integration/pipeline/test_cli_runs.py tests/unit/loom/cli/test_plan.py` produced 78 passed.
  - Targeted config-extra/no-service CLI pytest passed: `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config pytest tests/e2e/test_cli_core.py::test_cli_validate_plan_and_json_outputs tests/e2e/test_cli_core.py::test_cli_continuation_commands_reject_recursive_executors_as_json tests/e2e/test_cli_core.py::test_cli_run_dry_run_does_not_execute_or_allocate tests/e2e/test_cli_core.py::test_cli_rejects_deferred_executor_and_plain_run_uri tests/integration/config/test_cli_plan.py::test_plan_fresh_without_run_uri_does_not_create_default_run_root tests/integration/config/test_cli_plan.py::test_plan_explicit_new_run_uri_is_read_only tests/integration/config/test_cli_plan.py::test_plan_existing_run_uri_without_resume_fails` produced 7 passed.
  - Socket/process-manager tests could not be rerun in this sandbox after implementation because local socket creation requires escalation and escalation was rejected by the platform usage limit. Earlier focused service tests for the first implementation slice passed under escalation before the limit was hit.
  - `make validate-pr` and `make test-summary` have not run for this phase in the current session because the required socket-capable escalation is unavailable.
- Refinement summary:
  - Not run as a separate refinement pass yet. Current local fixes were made by the managing agent before the implementation commit/PR checkpoint.
- Blocker-resolution summary:
  - 0/3 phase blocker-resolution passes used. Current blocker is environmental: git metadata and socket-capable validation require escalation, but the platform rejected escalation because the session hit the usage limit.
- PR preparation:
  - Not started. Local git staging failed because the worktree git metadata is read-only in the sandbox (`index.lock` could not be created), and the required escalation for `git add` was rejected by the platform usage limit.
- Stack maintenance:
  - None performed. This is a root phase branch targeting `develop`; no successor branch has been created.
- Remaining blockers:
  - Commit, full validation, PR body preparation, push, PR creation, CI, automated review, merge, metadata update, and cleanup are blocked until escalation/local git metadata writes and network operations are available again.
