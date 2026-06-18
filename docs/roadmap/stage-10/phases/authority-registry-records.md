# Phase 8 Execution Plan: Workspace Registry Records

## Metadata

- Status: refined phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 8: Workspace Registry Records`
- Branch: `codex/authority-registry-records`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-registry-records`
- Phase execution plan path: `docs/roadmap/stage-10/phases/authority-registry-records.md`
- Full plan: `docs/roadmap/stage-10/implementation-plan.md`
- Source phase: Phase 8 - Workspace Registry Records
- Stack predecessor: none; Phase 7 is merged in PR #125 and recorded in the plan
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 9 writes these records from supervisor lifecycle commands; Phase 10 adopts resolver/factory use.
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/roadmap/stage-10/implementation-plan.md`
- Plan quality gate loop budget: consumed; do not reopen unless the v10 implementation plan changes materially
- Draft pass: completed by managing agent on 2026-05-11
- Refine pass: completed by managing agent on 2026-05-11
- Setup limitations: branch and worktree were created from local `develop` at `b0c18f9`, after Phase 7 merge metadata was pushed
- Blockers: none; implementation may begin from this refined phase execution plan.

## Objective

Add deterministic workspace-local authority registry records under `.loom/authority/` so later supervisor and resolver phases can discover allocation-scoped authority facts without trusting stale files or leaking sensitive metadata.

## Full-Plan Context

Phase 7 made the FastAPI mutation API usable in process. Phase 8 creates the local registry artifact that supervisor commands will write in Phase 9 and strict resolver/factory paths will consume in Phase 10. This phase only creates helpers and validation contracts; it must not start processes, perform network checks, or migrate runtime callers.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 7 merged to `develop` in PR #125
- Why this base branch is correct: the implementation plan records Phase 7 merged, the control checkout was fast-forwarded to `develop`, and no unmerged predecessor branch exists
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete the phase branch and worktree after merge if no successor phase branch depends on it

## Source Phase Summary

- Goal: add workspace-local registry records that describe authority allocation without making stale records safe to use.
- Required scope: `.loom/authority/` read/write helpers, endpoint/state-dir/workspace/generation/capability/version/allocation/timestamp facts, atomic file updates, validation categories, resolver hint conversion, and allocation-scoped hooks.
- Required checkpoints: no secrets in persisted records, deterministic parsing, wrong-workspace/stale-generation/incompatible-version/unavailable/stale/missing distinctions, no FastAPI route imports, and fail-closed behavior when no record exists.
- Acceptance criteria: registry records can be written/read atomically, validated deterministically, and converted to Phase 1 resolver inputs without runtime adoption.

## Current Source And Harness Findings

- `src/loom/pipeline/stores/authority_resolution.py` already defines `AuthorityRegistryHint`, `AuthorityServiceHealth`, resolver failure kinds, and fail-closed missing/stale/wrong-workspace/incompatible-generation/version behavior.
- `src/loom/pipeline/stores/config.py` defines `AuthorityReference` and redacted reference helpers. The registry must preserve usable endpoint/state-dir facts while redacting metadata keys that may contain credentials.
- `src/loom/pipeline/stores/atomic.py` provides `atomic_write_json` and directory creation helpers for same-directory atomic replacement.
- No current `.loom/authority/` helper exists. Exact filenames can be introduced here without conflicting with existing run-catalog `.loom_catalog` behavior.

## In-Scope Work

- Add a registry helper module under `loom.pipeline.stores` with a versioned `AuthorityRegistryRecord`, allocation scope values, validation result values, path helpers, read/write helpers, and resolver-hint conversion.
- Store default workspace records at `.loom/authority/current.json` and allocation-scoped records at `.loom/authority/allocations/<allocation-id>.json`.
- Persist redacted authority reference metadata, supervisor state directory reference, workspace ID, service generation, protocol/schema/version facts, capability facts, allocation scope, allocation ID, timestamps, optional expiry, service health state, and redacted diagnostics metadata.
- Validate missing files, malformed files, stale/expired records, wrong workspace, incompatible generation, incompatible protocol/schema versions, and unavailable/unhealthy health states as distinct fail-closed outcomes.
- Add package, unit, contract, and integration tests for serialization, redaction, atomic write/read behavior, resolver mapping, and temp workspace paths.

## Out-of-Scope Work

- Supervisor lifecycle commands, process management, health polling, and registry writes from CLI commands.
- Runtime resolver/factory adoption or automatic reading from workspaces.
- User-global discovery, hosted service discovery, network calls, service DB mutation, resource leases, and offline import.

## Assumptions

- Registry schema version `1` is sufficient for the first v10 record shape.
- Endpoint strings are not redacted because clients need them; sensitive metadata keys such as token, secret, credential, authkey, password, and authorization are redacted recursively.
- Expiry-based staleness is enough for Phase 8. Later lifecycle commands can update records after status/doctor checks.

## Scope Contract

Registry helpers are pure filesystem/protocol adapters. They may read and write JSON under the supplied workspace root and return resolver-compatible records, but they must not import FastAPI, route modules, the private authority repository, or runtime execution layers.

Missing or invalid registry records must not silently produce online authority. Validation should produce structured resolver diagnostics/failure kinds so Phase 10 can fail closed without inventing new categories.

## Design Impact

- Maintainability: keeps registry record shape and validation in one small store module rather than scattering file parsing through CLI, supervisor, and factories.
- Extensibility: allocation-scoped paths leave room for later per-allocation supervisor records and user-global references.
- Domain neutrality: records describe authority service facts only.
- Source-tree boundaries: registry helpers stay in stores and depend on protocol/config/resolution values, not server routes.

## Future Compatibility

The record shape should allow later supervisor lifecycle commands to add status metadata and later resolver adoption to consume hints without changing file locations. User-global discovery can layer references above this workspace-local file rather than replacing it.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Store registry records in a user-global directory first | v10 requires workspace-local allocation records and fail-closed local behavior. |
| Let stale records trigger implicit restart | Phase 8 and the plan reject hidden service startup. |
| Persist raw authority metadata unredacted | Registry files are workspace artifacts and must not leak credentials. |
| Adopt registry lookup in factories now | Phase 10 owns strict resolver/factory adoption. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Registry health is recorded, not actively polled | Phase 9 owns supervisor/status checks and Phase 10 owns resolver adoption. | Lifecycle commands need live readiness validation. |
| Filename shape is simple current/allocation JSON | It is enough for local workspace records and leaves room for user-global discovery later. | Multiple simultaneous authorities per workspace need a richer index. |

## Reviewability

- Expected PR size and shape: one new registry helper module plus focused package, unit, contract, and integration tests and public export updates.
- Files and areas to inspect: `authority_registry.py`, `authority_resolution.py` interactions, store exports, import-boundary tests, resolver contract tests, and temp workspace integration tests.
- Scope-control checks: no FastAPI route imports, no private repository imports, no supervisor commands, no factory/runtime adoption, no network checks, no global registry, and no offline import behavior.

## Implementation Steps

1. Add registry path helpers, record/value models, schema validation, and redaction helpers.
2. Add atomic write/read helpers for current and allocation-scoped files.
3. Add validation and resolver-hint conversion for missing, stale, wrong workspace, generation, version, and service-health cases.
4. Export the public helper surface and add/update package public API tests.
5. Add unit, contract, and integration coverage, then run targeted validation and final PR gates.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_store_api.py`
- Required assertions or deferral reason: registry helper imports stay free of FastAPI/server/private repository layers; public store exports include the intended registry helper surface.

### Unit Suite

- Status: required
- Expected paths: new `tests/unit/loom/pipeline/stores/test_authority_registry.py`, `tests/unit/loom/pipeline/stores/test_store_errors.py`
- Required assertions or deferral reason: serialization, unknown-field rejection, recursive metadata redaction, path validation, stale expiry, wrong workspace, generation mismatch, incompatible version, unavailable health, and public export order.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authority_resolution_contract.py`
- Required assertions or deferral reason: registry validation maps cleanly to existing resolver failure kinds and diagnostics without adding ad hoc categories.

### Integration Suite

- Status: required
- Expected paths: new `tests/integration/authority/test_registry_records.py`
- Required assertions or deferral reason: temp workspace `.loom/authority/current.json` and allocation record writes are atomic, parse deterministically, and missing records fail closed.

### E2E Suite

- Status: deferred
- Expected paths: not required for this phase
- Required assertions or deferral reason: no CLI lifecycle or runtime resolver adoption occurs in Phase 8.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: no external service, network, scheduler, or process lifecycle coverage is required.

## Risks

- Redacting too aggressively could make registry records unusable; redacting too weakly could leak secrets.
- Version/generation validation must align with Phase 1 resolver categories to avoid later resolver special cases.
- Public export growth must remain minimal and stable.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores/authority_registry.py src/loom/pipeline/stores/__init__.py tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_authority_registry.py tests/unit/loom/pipeline/stores/test_store_errors.py tests/contracts/test_authority_resolution_contract.py tests/integration/authority/test_registry_records.py
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/stores/authority_registry.py tests/unit/loom/pipeline/stores/test_authority_registry.py tests/contracts/test_authority_resolution_contract.py tests/integration/authority/test_registry_records.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_authority_registry.py tests/unit/loom/pipeline/stores/test_store_errors.py tests/contracts/test_authority_resolution_contract.py tests/integration/authority/test_registry_records.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: record/path models, redaction and serialization, read/write helpers, validation/resolver conversion, then tests.
- Tests to run with each slice: unit serialization after models, integration paths after write helpers, contract resolver tests after validation mapping, package tests after exports/import boundaries.
- Decisions the executor must not revisit: no supervisor CLI, no runtime factory adoption, no network health polling, no FastAPI/private repository imports, and no user-global registry.
- Conditions that require stopping for the manager: need to change resolver failure enums, need to store unredacted sensitive metadata, or need runtime adoption to prove behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted validation and full PR gates passed without a separate refiner pass
- PR review: used by managing agent on 2026-05-11; registry parsing and endpoint query preservation findings were fixed before merge
- Blocker resolution: 1/3 used for a bounded registry parsing/query preservation fix

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-11.
- Final phase execution plan: completed by managing agent on 2026-05-11.
- Implementation summary: added `loom.pipeline.stores.authority_registry` with versioned workspace and allocation-scoped registry records, safe path helpers, atomic JSON write/read helpers, recursive sensitive metadata redaction, endpoint safety checks that preserve non-sensitive query strings, fail-closed validation statuses, resolver-hint conversion, and service-health fact conversion. Exported the registry surface through `loom.pipeline.stores` and added package, unit, contract, and integration coverage.
- Implementation validation: targeted Ruff passed; targeted Pyright passed; targeted pytest passed with 18 registry tests after the review fix. `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed with Ruff clean, Pyright clean, default pytest 1271 passed / 18 skipped / 14 deselected, config-extra 420 passed / 1300 deselected, and build success. `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package 67 passed / 1 skipped, unit 921 passed / 1 skipped, contract 145 passed / 2 skipped, integration 125 passed / 8 skipped / 10 deselected, e2e 39 passed / 1 deselected, and config-extra 420 passed / 1300 deselected.
- Refinement summary: no separate refiner pass was needed; implementation typing fixes stayed in the implementation pass before commit, and the automated review fix was bounded to registry parsing/query preservation.
- Blocker-resolution summary: one bounded pass fixed malformed JSON validation and safe endpoint query preservation before merge.
- PR preparation: PR body drafted in `docs/roadmap/stage-10/phases/authority-registry-records-pr-body.md`; PR not yet opened.
- Stack maintenance:
- Remaining blockers: none.
