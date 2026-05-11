# Phase 3 Execution Plan: FastAPI Transport Skeleton

## Metadata

- Status: refined phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 3: FastAPI Transport Skeleton`
- Branch: `codex/authority-fastapi-skeleton`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-fastapi-skeleton`
- Phase execution plan path: `docs/phases/authority-fastapi-skeleton.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 3 - FastAPI Transport Skeleton
- Stack predecessor: none; Phase 2 is merged in PR #120 and recorded in the plan
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 4 adds private repository schema/versioning behind the dependency boundary; Phase 7 adds durable mutation routes and client transport behavior; Phase 9 adds supervisor process lifecycle commands.
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Plan quality gate loop budget: consumed; do not reopen unless the v10 implementation plan changes materially
- Draft pass: completed by managing agent on 2026-05-11
- Refine pass: completed by managing agent on 2026-05-11
- Setup limitations: none unresolved. Branch and worktree were created from local `develop` at `8c8fbd8`, after Phase 2 merge metadata was pushed.
- Blockers: none; implementation may begin from this refined phase execution plan.

## Objective

Introduce a FastAPI-backed authority app boundary with deterministic in-process tests, operational health/readiness/version/capability routes, explicit future mutation-route ownership, and dependency injection seams for later repository and service objects without implementing durable authority mutation.

## Full-Plan Context

Phase 1 defined strict online/offline authority resolution. Phase 2 defined the transport-independent protocol value models. Phase 3 binds those protocol values to a concrete FastAPI server adapter while keeping persistence, mutation dispatch, supervisor process management, workspace registry writes, runtime caller migration, resource coordination, and offline import in later phases.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 2 merged to `develop` in PR #120
- Why this base branch is correct: the implementation plan records Phase 2 merged, the control checkout was fast-forwarded to `develop`, and no unmerged predecessor branch exists
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete the phase branch and worktree after merge if no successor phase branch depends on it

## Source Phase Summary

- Goal: add the FastAPI server adapter and deterministic local test harness without durable mutation behavior.
- Required scope: runtime FastAPI dependency, authority app boundary, route ownership split, health/liveness/readiness/version/capability stubs, and dependency injection points.
- Required checkpoints: dependency/lock updates with rationale, app construction without an external process, protocol-compatible response payloads, transport-only FastAPI imports, and in-process test-client coverage.
- Acceptance criteria: tests can construct the app locally, operational endpoints return structured protocol-compatible data, route modules contain no repository implementation, core runtime modules do not import FastAPI, and dependency changes are documented.

## Current Source And Harness Findings

- `pyproject.toml` currently has no runtime dependencies. Phase 3 must add FastAPI as a runtime dependency and update `uv.lock`; deterministic TestClient coverage will also require a dev-only HTTP client dependency.
- `src/loom/pipeline/stores/authority_protocol.py` provides `AuthorityProtocolReadiness`, `AuthorityProtocolVersion`, `AUTHORITY_PROTOCOL_VERSION`, and related plain-data helpers that should own readiness/version payload shapes.
- `src/loom/pipeline/stores/capabilities.py` provides `BackendCapabilitySet` and diagnostics that can be returned by capability and readiness stubs without repository coupling.
- `tests/package/test_pipeline_store_api.py` already asserts importing `loom.pipeline.stores` does not import `fastapi`; Phase 3 should extend import-boundary coverage to prove framework imports stay in transport modules.
- Existing package roots prefer lightweight `__init__.py` files. The new authority package root should avoid eager FastAPI imports, while app/route modules may import FastAPI directly.

## In-Scope Work

- Add a transport package for the authority service, using a lightweight root package and FastAPI-importing app/route modules.
- Add `create_authority_app(...)` and a small dependency container for future repository/service injection, service generation, workspace id, capabilities, readiness state, and diagnostics.
- Add operational supervisor routes for health, liveness, readiness, version, and capabilities using protocol-compatible plain-data response shapes.
- Add an explicit mutation-route router placeholder or route-group boundary for later Phase 7 mutation APIs without implementing mutation dispatch or repository writes.
- Add FastAPI runtime dependency and dev-only TestClient support, with lockfile changes and documentation in this phase plan and PR body.
- Add package, unit, contract, and integration tests for app construction, dependency overrides, response shapes, route grouping, and import boundaries.

## Out-of-Scope Work

- Durable SQLite repository, schema, migration, transaction, or repository conformance behavior.
- Real mutation route semantics, request dispatch, status-code mapping for authority mutations, idempotency, locking, fencing, or client transport behavior.
- Supervisor process commands, subprocess management, PID files, registry writes, stale registry handling, status/doctor/restart CLI behavior, or external server smoke tests unless trivial and stable.
- Runtime caller migration, store factory adoption, runner adoption, SLURM worker handoff, workspace coordination APIs, generic resource leasing, offline evidence manifests, or offline import.

## Assumptions

- FastAPI is the intended runtime service framework for v10 authority, and Pydantic/Starlette are accepted transitive dependencies of that explicit design choice.
- The phase can use FastAPI's in-process `TestClient` for deterministic integration coverage; any extra HTTP client package needed by that harness belongs in the dev dependency group, not runtime dependencies.
- The skeleton's default capabilities may be conservative and mostly empty because durable repository and mutation support arrive in later phases.
- Operational endpoints may return plain dictionaries produced by protocol value objects; generated OpenAPI schema precision is not a phase goal.

## Scope Contract

FastAPI imports must be isolated to the authority transport package and tests. Importing `loom`, `loom.pipeline`, `loom.pipeline.stores`, existing store modules, execution modules, diagnostics modules, or CLI helper modules must not import FastAPI. The lightweight authority package root may exist for discoverability, but the concrete `create_authority_app` symbol may live in an app module that intentionally imports FastAPI.

Operational responses must be plain-data compatible and parseable by existing protocol model helpers where applicable:

- `/health` and `/live` report process/app liveness without probing persistence.
- `/ready` returns an `AuthorityProtocolReadiness` dictionary including protocol version, schema version, readiness state, capability facts, service generation, workspace id, and diagnostics.
- `/version` returns an `AuthorityProtocolVersion` dictionary.
- `/capabilities` returns a `BackendCapabilitySet` dictionary.

The mutation route boundary must make future ownership clear but must not accept, persist, or mutate authoritative state in this phase. Dependency injection should be explicit enough for later repository/service phases to replace default skeleton services without changing route module ownership.

## Design Impact

- Maintainability: framework code is contained in a dedicated transport layer with small route modules and dependency accessors.
- Extensibility: later repository, supervisor, and mutation phases can replace injected services while preserving app construction and route grouping.
- Domain neutrality: endpoint payloads describe Loom authority, readiness, capabilities, schema, and diagnostics without research-domain semantics.
- Source-tree boundaries: protocol models stay under `loom.pipeline.stores`; FastAPI app and routes adapt those models without pushing framework imports back into core runtime modules.

## Future Compatibility

Route prefixes and dependency names should leave room for hosted service deployment, explicit supervisor lifecycle routes, real mutation APIs, repository-backed readiness checks, capability growth, and alternate clients. The skeleton should not freeze mutation request routing beyond clear ownership boundaries for operational supervisor routes versus authority mutation routes.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Use ad hoc HTTP handlers instead of FastAPI | The v10 plan explicitly selects FastAPI, and route dependency injection plus TestClient coverage are useful for later phases. |
| Put FastAPI app construction under `loom.pipeline.stores` | Stores owns protocol and backend contracts; framework imports there would weaken package import boundaries. |
| Start an external server for tests | The phase requires deterministic tests that do not rely on a long-running process. |
| Implement placeholder durable mutation behavior | Mutation semantics, repository errors, and client transport behavior belong to later phases and would broaden the PR. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Readiness and capability endpoints initially use injected skeleton state rather than repository-backed facts | Repository schema and services are Phase 4 and Phase 7 work. | Repository-backed readiness or mutation routes are implemented. |
| Mutation route ownership exists before mutation routes do real work | The phase needs a clear route split while keeping durable mutation out of scope. | Phase 7 starts server mutation API implementation. |
| OpenAPI response models may be plain dictionaries rather than precise Pydantic schemas | Protocol dataclasses already own plain-data compatibility; schema polish is not needed for skeleton validation. | Public client generation or hosted API documentation becomes a requirement. |

## Reviewability

- Expected PR size and shape: moderate dependency, app skeleton, route module, and tests PR with no repository or runner changes.
- Files and areas to inspect: `pyproject.toml`, `uv.lock`, new `src/loom/authority/*` package, package import-boundary tests, unit app-construction tests, contract response-shape tests, and in-process integration tests.
- Scope-control checks: no FastAPI imports from core runtime modules, no SQLite/repository implementation in route modules, no CLI supervisor commands, no client transport behavior, no runtime caller migration, and no external server dependency in tests.

## Implementation Steps

1. Add FastAPI runtime and dev test-client dependencies with lockfile updates.
2. Add the authority transport package with lightweight root import, dependency container, app factory, supervisor routes, and mutation route-group boundary.
3. Return protocol-compatible readiness/version/capability payloads from operational routes and keep defaults conservative.
4. Add package import-boundary tests proving FastAPI stays isolated to transport modules.
5. Add unit, contract, and integration tests for app construction, dependency overrides, route ownership, and in-process response shapes.
6. Run targeted validation, then final `make validate-pr` and `make test-summary` before PR preparation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_store_api.py`, and a package test for the authority transport root if needed
- Required assertions or deferral reason: importing core packages and `loom.pipeline.stores` does not import `fastapi`; importing the lightweight authority package root does not eagerly import FastAPI unless the app module is imported.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/authority/test_app.py` and route/dependency unit tests as needed
- Required assertions or deferral reason: app factory construction, dependency container defaults, override/custom readiness state, route registration, and no repository object requirement.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authority_fastapi_skeleton_contract.py`
- Required assertions or deferral reason: readiness endpoint payload parses as `AuthorityProtocolReadiness`, version payload parses as `AuthorityProtocolVersion`, capability payload parses as `BackendCapabilitySet`, and operational payload fields remain stable.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/authority/test_fastapi_skeleton.py`
- Required assertions or deferral reason: FastAPI `TestClient` can exercise health, live, ready, version, and capabilities endpoints in-process without external service startup.

### E2E Suite

- Status: deferred
- Expected paths: not required for this phase
- Required assertions or deferral reason: no CLI command, runtime caller, supervisor process, repository, or user workflow behavior changes.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: no network, external process, scheduler, or service smoke test should be required for this skeleton.

## Risks

- Adding FastAPI pulls in Pydantic and Starlette at runtime, so import-boundary tests must prevent framework imports from spreading through core modules.
- Route names and prefixes can become sticky, so this phase should choose ordinary operational endpoints without over-designing mutation routing.
- A readiness endpoint that claims too much support would mislead later diagnostics; default skeleton capabilities should remain conservative.
- TestClient support may require dev dependency maintenance separate from runtime dependency rationale.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check pyproject.toml src/loom/authority tests/package tests/unit/loom/authority tests/contracts/test_authority_fastapi_skeleton_contract.py tests/integration/authority
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/authority tests/unit/loom/authority tests/contracts/test_authority_fastapi_skeleton_contract.py tests/integration/authority
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py tests/unit/loom/authority tests/contracts/test_authority_fastapi_skeleton_contract.py tests/integration/authority
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: dependency/lock update, transport package skeleton, operational route payloads, package import-boundary tests, then unit/contract/integration tests.
- Tests to run with each slice: import-boundary package tests after adding the package, unit route tests after app factory, contract response tests after endpoint payloads, integration TestClient tests before full validation.
- Decisions the executor must not revisit: FastAPI imports stay in the authority transport package, protocol dataclasses own readiness/version shapes, no repository/mutation/client/supervisor lifecycle behavior in this phase, and no external server process for required tests.
- Conditions that require stopping for the manager: inability to update dependencies/lockfile, need to move FastAPI into core runtime modules, need for repository-backed readiness to satisfy tests, or a dependency conflict that cannot be resolved locally.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-11.
- Final phase execution plan: completed by managing agent on 2026-05-11.
- Implementation summary:
- Implementation validation:
- Refinement summary:
- Blocker-resolution summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers:
