# Phase 7 Execution Plan: Authority Server Mutation API

## Metadata

- Status: refined phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 7: Authority Server Mutation API`
- Branch: `codex/authority-mutation-api`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-mutation-api`
- Phase execution plan path: `docs/phases/authority-mutation-api.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 7 - Authority Server Mutation API
- Stack predecessor: none; Phase 6 is merged in PR #124 and recorded in the plan
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 8 adds workspace registry records; Phase 9 adds supervisor lifecycle; Phases 10-13 migrate runtime callers onto the client API.
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Plan quality gate loop budget: consumed; do not reopen unless the v10 implementation plan changes materially
- Draft pass: completed by managing agent on 2026-05-11
- Refine pass: completed by managing agent on 2026-05-11
- Setup limitations: branch and worktree were created from local `develop` at `bdad7f6`, after Phase 6 merge metadata was pushed
- Blockers: none; implementation may begin from this refined phase execution plan.

## Objective

Expose the private authority repository through structured FastAPI mutation routes and a transport adapter client so run and stage lifecycle mutations can be exercised through the service boundary without direct DB access or runtime caller migration.

## Full-Plan Context

Phase 6 completed private durable run and stage lifecycle behavior. Phase 7 wraps that behavior in protocol-compatible service routes and a client adapter. Supervisor startup, registry discovery, strict factory adoption, runner migration, coordination, resource leases, and offline import remain future phases.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 6 merged to `develop` in PR #124
- Why this base branch is correct: the implementation plan records Phase 6 merged, the control checkout was fast-forwarded to `develop`, and no unmerged predecessor branch exists
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete the phase branch and worktree after merge if no successor phase branch depends on it

## Source Phase Summary

- Goal: wire the private repository into FastAPI authority routes and client protocol behavior.
- Required scope: run and stage lifecycle mutation routes, client transport adapter, repository-to-protocol response mapping, timeout/connection error mapping, service-boundary conformance tests, and readiness/capability behavior for repository-backed services.
- Required checkpoints: structured acknowledgements and rejections, no SQL path exposure, stale generation/fencing/conflict/internal error envelopes, in-process FastAPI plus temp SQLite flows, and client modules that do not import private repository code.
- Acceptance criteria: representative run and stage lifecycle mutations work against a temp repository-backed FastAPI app, failures map to protocol envelopes, and existing runtime callers remain unchanged.

## Current Source And Harness Findings

- `src/loom/authority/routes/mutations.py` currently exposes only a non-mutating route group manifest. This phase should replace the manifest's `mutation_routes_implemented` flag and add explicit mutation endpoints under `/v1/authority`.
- `src/loom/authority/services.py` already has injected service facts plus `repository` and `mutation_service` placeholders. This phase can add a repository-backed mutation service without importing FastAPI into core protocol modules.
- `src/loom/authority/_repository.py` is private and provides the needed run, stage, lease, submitted-operation, output, audit, cleanup, and recovery methods.
- `src/loom/pipeline/stores/authority_protocol.py` already provides generic request/response envelopes and result/rejection shapes. This phase should use those models rather than creating route-specific public DTOs.
- `httpx` is dev-only for FastAPI `TestClient`; runtime client code should avoid depending on `httpx` unless packaging is deliberately changed. A stdlib `urllib` transport is sufficient for the first client adapter.
- Existing FastAPI tests use in-process `TestClient`, which is stable enough for route and service-boundary coverage without a long-running external server.

## In-Scope Work

- Add a server-side authority mutation service that accepts `AuthorityProtocolRequest` envelopes, invokes the private repository, and returns `AuthorityProtocolResponse` envelopes.
- Add FastAPI endpoints for representative run lifecycle, snapshot, controller lease, submitted-operation, stage lifecycle, stage attempt, stage lease, terminal attempt, and output commit operations.
- Add a public client adapter module that posts protocol envelopes to the FastAPI route surface, parses structured responses, and maps timeout/connection/HTTP/invalid-payload failures into protocol rejections.
- Map repository compatibility failures, validation failures, conflicts, stale revision, stale generation, stale fencing, unavailable service, and internal failures into protocol categories.
- Update capability/readiness facts for repository-backed mutation services and keep the default app constructable without a repository.
- Add package, unit, contract, and integration tests for route shapes, client behavior, service-boundary flows, and private import boundaries.

## Out-of-Scope Work

- Supervisor process lifecycle commands, workspace registry records, runtime factory adoption, `loom run` migration, worker/SLURM migration, workspace coordination, resource admission, and offline evidence/import behavior.
- Exposing private repository classes from `loom.authority` or requiring clients to know SQLite paths.
- Adding a global scheduler, hosted deployment semantics, authentication, TLS, or user-global discovery.

## Assumptions

- The route surface can use generic protocol request/response envelopes in v10 Phase 7; typed route-specific DTOs can be added later only if public API stability requires them.
- Client transport can use the Python standard library for runtime HTTP and accept an injectable transport callable for tests.
- Repository error messages are stable enough inside this phase to classify known stale/conflict/validation cases, with unknown errors mapped to internal-error envelopes.

## Scope Contract

FastAPI routes must be adapters: they parse a protocol request, call a mutation service, and return a protocol response dictionary. Repository calls stay behind `loom.authority` server code. Public client code may import protocol/read-model values but must not import `loom.authority._repository`.

Protocol rejections are data, not raw framework tracebacks. Validation and repository failures return `AuthorityProtocolResponse(accepted=False, rejection=...)` with a category and stable code. Transport failures in the client also return rejected protocol responses tied to the original request metadata.

The default skeleton app remains constructable, but its mutation manifest must indicate unsupported mutation behavior unless a mutation service is configured. Repository-backed tests should configure the app with an initialized temp repository and service generation.

## Design Impact

- Maintainability: isolates route wiring, repository mapping, and client transport behavior in narrow modules.
- Extensibility: keeps a replaceable protocol-envelope client that future hosted or alternate transports can implement.
- Domain neutrality: operations remain generic run/stage/lease/artifact facts.
- Source-tree boundaries: FastAPI remains under `loom.authority`; public protocol/client code stays repository-free.

## Future Compatibility

The route names and client methods should leave room for later registry, supervisor, coordination, resource, and import APIs without changing the generic envelope contract. Rejection categories should align with resolver and future runtime diagnostics.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Let runtime callers invoke repository methods during migration | Phase 7 is specifically the service boundary; direct DB access would undermine later strict resolver adoption. |
| Make HTTP status codes the only error contract | Clients and diagnostics need structured protocol categories independent of transport details. |
| Add `httpx` as a runtime dependency for the client | A stdlib transport satisfies this phase without expanding runtime dependencies. |
| Start supervisor process behavior in route tests | Phase 9 owns lifecycle commands; in-process FastAPI tests are deterministic and sufficient here. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Generic envelope endpoints precede route-specific public DTOs | The protocol model already exists and keeps the first service adapter compact. | External API stability or documentation requires narrower DTO schemas. |
| Client transport is basic stdlib HTTP | Avoids a runtime dependency while supervisor process work is still pending. | Hosted/async/streaming client behavior becomes required. |
| Runtime callers still use older paths | Dedicated migration phases own factories, runner, worker, and SLURM adoption. | Phase 10 begins strict resolver and factory adoption. |

## Reviewability

- Expected PR size and shape: medium server/client adapter implementation with focused unit, contract, integration, and package tests.
- Files and areas to inspect: `src/loom/authority/services.py`, `src/loom/authority/routes/mutations.py`, the new client adapter module, protocol exports if needed, FastAPI contract/integration tests, client tests, and import-boundary tests.
- Scope-control checks: no supervisor lifecycle, registry persistence, runtime caller migration, workspace coordination, resource leases, offline evidence/import, public repository exports, or SQLite path exposure in client APIs.

## Implementation Steps

1. Add server-side mutation service helpers for request parsing, repository invocation, result construction, and rejection mapping.
2. Add FastAPI route endpoints under `/v1/authority` for run/stage lifecycle, leases, submitted operations, snapshots, and output commits.
3. Add a repository-free client adapter that posts protocol envelopes and maps transport failures to structured rejections.
4. Update capabilities/readiness/manifest behavior for repository-backed versus unsupported default mutation services.
5. Add package, unit, contract, and integration coverage for service boundary behavior and representative success/failure flows.
6. Run targeted validation, then final `make validate-pr` and `make test-summary` before PR preparation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: client/protocol imports do not import FastAPI or private repository modules; `loom.authority` root remains lightweight and repository-private.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/authority/test_app.py`, `tests/unit/loom/pipeline/stores/test_authority_client.py`, and public export coverage in `tests/unit/loom/pipeline/stores/test_store_errors.py`
- Required assertions or deferral reason: service result/rejection mapping, manifest capability flags, client URL construction, response parsing, timeout/connection/invalid-payload rejection mapping, and no SQL path exposure.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authority_fastapi_skeleton_contract.py`
- Required assertions or deferral reason: route response shapes use protocol envelopes for success, conflict, stale generation, stale fencing, stale revision, unsupported capability, and internal/unavailable errors.

### Integration Suite

- Status: required
- Expected paths: new `tests/integration/authority/test_mutation_api.py`
- Required assertions or deferral reason: in-process FastAPI app backed by a temp SQLite repository can admit a run, transition it, allocate a stage attempt, commit output artifacts, read snapshots, and reject stale generation/fencing through structured envelopes.

### E2E Suite

- Status: deferred
- Expected paths: not required for this phase
- Required assertions or deferral reason: no CLI supervisor, external process, runtime runner, or user workflow is introduced.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: external server-process tests wait for supervisor lifecycle.

## Risks

- Error mapping could become message-fragile if repository errors change.
- Route proliferation could grow beyond representative lifecycle coverage and drift into future runtime migration.
- Client code could accidentally depend on FastAPI/TestClient or private repository internals.
- Readiness/capabilities could overclaim mutation support when no mutation service is configured.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/authority src/loom/pipeline/stores/authority_client.py tests/package/test_import_boundaries.py tests/unit/loom/authority tests/unit/loom/pipeline/stores/test_authority_client.py tests/contracts/test_authority_fastapi_skeleton_contract.py tests/integration/authority/test_fastapi_skeleton.py tests/integration/authority/test_mutation_api.py
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/authority src/loom/pipeline/stores/authority_client.py tests/unit/loom/authority tests/unit/loom/pipeline/stores/test_authority_client.py tests/contracts/test_authority_fastapi_skeleton_contract.py tests/integration/authority/test_mutation_api.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py tests/unit/loom/authority tests/unit/loom/pipeline/stores/test_authority_client.py tests/contracts/test_authority_fastapi_skeleton_contract.py tests/integration/authority/test_fastapi_skeleton.py tests/integration/authority/test_mutation_api.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: service/rejection mapping, route endpoints, client adapter, capability/readiness updates, then tests.
- Tests to run with each slice: unit service tests after mapping, contract route tests after endpoints, client unit tests after transport adapter, integration tests after repository-backed flows.
- Decisions the executor must not revisit: no runtime caller migration, no supervisor/registry work, no public repository exports, no runtime `httpx` dependency, and no offline/import/resource behavior.
- Conditions that require stopping for the manager: need to change protocol model compatibility shape, need a runtime dependency addition, inability to map stale generation/fencing without changing repository semantics, or route behavior requiring supervisor process management.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed after targeted validation and
  full PR validation passed
- PR review: used on 2026-05-11 by managing agent; approved with no blocking
  or non-blocking findings
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-11.
- Final phase execution plan: completed by managing agent on 2026-05-11.
- Implementation summary: added a repository-backed authority mutation service
  that maps generic protocol envelopes to private repository run, stage,
  lease, submitted-operation, and output-commit methods; added FastAPI
  mutation routes under `/v1/authority`; added a repository-free stdlib HTTP
  `AuthorityClient`; updated repository-backed service capabilities and
  manifest behavior; and added package, unit, contract, and integration
  coverage for route responses, client transport errors, public exports,
  private import boundaries, in-process mutation flows, stale generation,
  stale fencing, conflict, and validation rejections.
- Implementation validation: targeted Ruff and Pyright passed for the changed
  source and tests. Targeted pytest passed with 63 package/unit/contract/
  integration tests. Initial `make validate-pr` found only stale public export
  expectations; after updating those tests, `UV_CACHE_DIR=/tmp/uv-cache make
  validate-pr` passed with Ruff, Pyright, default pytest at 1248 passed, 18
  skipped, 14 deselected, config-extra pytest at 420 passed and 1277
  deselected, and package build. `UV_CACHE_DIR=/tmp/uv-cache make
  test-summary` passed with overall 1694 passed, 12 skipped, and 1288
  deselected.
- Refinement summary: not needed; the only validation blocker was expected
  public export test coverage for the new client surface and was fixed in the
  implementation pass.
- Blocker-resolution summary: not needed; 0/3 blocker-resolution passes used.
- PR preparation: PR #125 opened at
  https://github.com/samcantrill/loom/pull/125 against `develop` with
  `codex/authority-mutation-api` as the head branch; target branch was
  verified immediately after creation.
- PR review: automated manager review verified the PR target, phase scope,
  route/service/client separation, private repository boundary, protocol
  acknowledgement and rejection mapping, timeout/unavailable-client behavior,
  repository-backed readiness and capability facts, public export updates,
  PR body/test evidence, domain neutrality, and absence of future registry,
  supervisor, runtime migration, coordination, resource, or offline-import
  behavior. No blockers remain.
- Stack maintenance: root phase branch targets `develop`; no successor branch
  depends on `codex/authority-mutation-api` yet.
- Remaining blockers: none known.
