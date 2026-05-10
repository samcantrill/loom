# Phase 10 Execution Plan: Service Default And SQLite Authority Removal

## Metadata

- Status: final phase execution plan
- Feature focus: Authority Runtime Unification
- PR title: `Authority Runtime Unification - Phase 10: Service Default and SQLite Authority Removal`
- Branch: `codex/service-default-sqlite-removal`
- Worktree: `/home/samcantrill/work/loom-worktrees/service-default-sqlite-removal`
- Phase execution plan path: `docs/phases/service-default-sqlite-removal.md`
- Full plan: `docs/implementation-plans/implementation-plan-v9-post.md`
- Source phase: Phase 10 - Service Default And SQLite Authority Removal
- Stack predecessor: none; Phase 9 merged to `develop`
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR, mergeable after validation, automated review, CI, and scope gates pass
- Workflow path: expanded path because this changes the public runtime authority default and removes a transitional backend path
- Successor dependency notes: none recorded in this V9-post plan
- Plan quality gate: passed on 2026-05-10 in the selected implementation plan
- Plan quality gate loop budget: consumed; do not reopen unless the plan content changes materially
- Draft pass: completed locally on 2026-05-10
- Refine pass: completed in the same artifact on 2026-05-10; no separate planner pass needed because the scope is fully specified
- Setup limitations: no external authority service is available; the default path must use the stdlib co-located service backend
- Blockers: none

## Objective

Make service-backed authority the default runtime path and remove run-local SQLite authority from supported runtime configuration while retaining SQLite only for private, rebuildable projections or backend-specific implementation tests.

## Full-Plan Context

Phases 1-9 introduced authority contracts, service-backed adapters, lifecycle propagation, diagnostics, and CLI/backend adoption while keeping SQLite as transitional runtime machinery. This final phase completes that transition. It must not delete derived catalog SQLite sidecars or local workspace coordination when those stores are documented as non-authoritative projections or coordination helpers rather than runtime run authority.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 9 PR #117 was merged
- Why this base branch is correct: `develop` includes Phase 9 merge metadata and service backend adoption
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete the phase branch and worktree after merge if no successor branch depends on it

## Source Phase Summary

- Goal: complete the transition to service/database-backed runtime authority.
- Required scope: change default backend selection, reject transitional SQLite runtime configuration, update docs/diagnostics/tests/examples, and preserve derived SQLite projections as non-authoritative.
- Required checkpoints: runtime factory behavior, CLI/env backend selection, diagnostics, conformance matrix, docs, and validation.
- Acceptance criteria: new runtime authority no longer creates `SQLitePerRunAuthorityStore` by default, explicit transitional SQLite configuration fails clearly, docs/examples show service/database runtime authority, catalog SQLite remains projection-only, and contracts exclude run-local SQLite from supported runtime backends.

## Current Source And Harness Findings

- `AuthorityConfig()` and `AuthorityConfig.from_dict({})` currently default to `transitional_sqlite`.
- Runtime factories in `src/loom/pipeline/stores/factory.py` and `src/loom/pipeline/execution/authority_adapter.py` instantiate `SQLitePerRunAuthorityStore` for default or explicit transitional config.
- `create_service_authority_store()` currently requires service endpoint metadata, so default service selection needs a co-located service bootstrap path.
- Diagnostics and run catalog scanning still have fallback imports that treat run-local SQLite as a runtime authority.
- Contract tests currently include SQLite authority directly in the supported runtime matrix; backend-specific SQLite implementation tests may remain private.
- CLI options expose `transitional_sqlite`; keeping it parseable is acceptable only if it fails with a clear removal diagnostic at runtime.

## In-Scope Work

- Default `AuthorityConfig` and empty config mapping to co-located service authority.
- Add co-located service bootstrap for endpoint-less co-located service configs.
- Make factories and execution adapters reject `transitional_sqlite` runtime configuration with clear `AuthorityStoreError` diagnostics.
- Keep explicit injected `PerRunAuthorityStore` test hooks intact as internal seams where needed by targeted tests.
- Update diagnostics, catalog scan behavior, docs, examples, and conformance tests for the final backend matrix.

## Out-of-Scope Work

- Hosted service operations, external auth, tenancy, and managed-service provisioning.
- Historical migration of old local-only or SQLite-authority runs.
- Removing private SQLite catalog sidecars, workspace coordination stores, or backend-specific SQLite implementation tests.
- Adding heavyweight dependencies.

## Assumptions

- A stdlib co-located service process is the local default service/database authority path for this phase.
- Explicit `transitional_sqlite` remains a recognized enum value only to produce a clear removal diagnostic for stale env, CLI, or serialized config values.
- Directly injected authority stores are internal test and extension hooks, not public runtime backend configuration.

## Scope Contract

`AuthorityConfig()` represents a co-located service runtime by default. Runtime factory functions must not instantiate `SQLitePerRunAuthorityStore` from config or environment. `AuthorityBackendKind.TRANSITIONAL_SQLITE` is rejected as a removed runtime backend with actionable wording that points callers to service authority. Endpoint-less co-located service configs start a local stdlib service and propagate the concrete endpoint/authkey config into workers. Derived catalog SQLite sidecars remain separate from authority and must not be described as lifecycle authority.

## Design Impact

- Maintainability: removes the transitional default path and lets runtime code assume service authority semantics.
- Extensibility: keeps the backend enum and config record stable for stale config diagnostics while making future service/database backends the supported extension point.
- Domain neutrality: changes only generic authority runtime behavior; no research-domain concepts are introduced.
- Source-tree boundaries: runtime code remains under `src/loom/pipeline`, diagnostics under `src/loom/diagnostics`, catalog projections under `src/loom/runs`, and docs under `docs/`.

## Future Compatibility

Future runtime phases can assume lifecycle state is mediated by service/database authority and no longer need shared-filesystem SQLite authority compatibility. If hosted service provisioning lands later, it can replace the local service bootstrap behind the same config surface.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep SQLite authority as a permanent dev/test backend | Contradicts Phase 10 acceptance and preserves unsupported shared-filesystem assumptions. |
| Delete every SQLite module | Would remove useful private projections and backend-specific regression tests outside Phase 10 scope. |
| Make default service selection require an external endpoint | Would break local CLI defaults without providing a managed service in this phase. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Co-located service bootstrap remains stdlib and process-local | It preserves local default usability without external dependencies. | Managed service/database provisioning becomes available. |
| `transitional_sqlite` enum value remains for diagnostics | Stale env/serialized config should fail clearly rather than with unknown enum errors. | A future compatibility-breaking config cleanup removes stale values entirely. |

## Reviewability

- Expected PR size and shape: moderate runtime/default change with focused docs and tests.
- Files and areas to inspect: authority config/factory/adapter/service code, diagnostics fallback paths, catalog scan behavior, contract matrix tests, and run-store docs.
- Scope-control checks: no deletion of non-authoritative catalog SQLite sidecars, no future hosted-service behavior, and no new heavyweight dependency.

## Implementation Steps

1. Update authority config defaults, service bootstrap, and runtime factories so the default path is co-located service and removed SQLite config fails clearly.
2. Remove runtime SQLite fallback behavior from diagnostics and catalog scanning while preserving local-only and missing-authority warnings.
3. Update tests and conformance matrix to assert service defaults, stale SQLite config rejection, and projection separation.
4. Update docs/examples to describe service/database authority as the supported runtime backend and catalog SQLite as non-authoritative.
5. Run targeted tests, final validation, prepare the PR body, open the PR, review, merge, and record completion metadata.

## Test Plan

### Package Suite

- Status: required
- Expected paths: public import smoke tests and package validation through `make validate-pr`
- Required assertions or deferral reason: public runtime imports no longer rely on SQLite authority as the default backend.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/`, `tests/unit/loom/pipeline/execution/`, `tests/unit/loom/diagnostics/`, `tests/unit/loom/runs/`
- Required assertions or deferral reason: backend selection defaults to service, removed SQLite config errors are clear, and projection paths remain separate.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authority_store_contract.py`, `tests/contracts/test_run_store_authority_contract.py`, `tests/contracts/test_authoritative_read_model_contract.py`
- Required assertions or deferral reason: supported runtime conformance excludes run-local SQLite authority.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_authority_factory.py` and default local execution coverage
- Required assertions or deferral reason: default runtime path uses service authority and explicit transitional SQLite config is rejected.

### E2E Suite

- Status: required where practical
- Expected paths: default CLI run/backend tests
- Required assertions or deferral reason: CLI default path resolves service authority; stale explicit SQLite backend fails clearly.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: no external hosted authority or backend operations service is introduced.

## Risks

- Auto-starting co-located services could leak processes if stores are dropped without cleanup.
- Worker handoff must receive the concrete endpoint/authkey config, not the abstract endpoint-less default config.
- Removing SQLite fallback could change diagnostics for historical local-only runs; warnings must remain clear.
- Contract test updates must not accidentally delete backend-specific SQLite implementation coverage.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/integration/pipeline/test_authority_factory.py
uv run pytest tests/contracts/test_authority_store_contract.py tests/contracts/test_run_store_authority_contract.py tests/contracts/test_authoritative_read_model_contract.py
uv run pytest tests/unit/loom/pipeline/stores tests/unit/loom/pipeline/execution/test_authority_adapter.py tests/unit/loom/diagnostics tests/unit/loom/runs
uv run pytest tests/e2e/test_cli_backend.py tests/e2e/test_local_pipeline_run.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: runtime defaults/service bootstrap, diagnostics/catalog fallback removal, test matrix updates, docs.
- Tests to run with each slice: the targeted commands above, then final PR gates.
- Decisions the executor must not revisit: Phase 10 removes run-local SQLite as supported runtime authority; derived SQLite projections stay.
- Conditions that require stopping for the manager: inability to keep local default runs working through co-located service, validation failures that imply a broader public API redesign, or conflict with non-authoritative SQLite projection requirements.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally on 2026-05-10.
- Final phase execution plan: completed locally on 2026-05-10.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- Blocker-resolution summary: pending.
- PR preparation: pending.
- Stack maintenance: pending.
- Remaining blockers: none.
