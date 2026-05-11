# Phase 1 Execution Plan: Authority Mode And Resolver Contracts

## Metadata

- Status: refined phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 1: Authority Mode And Resolver Contracts`
- Branch: `codex/authority-mode-resolution`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-mode-resolution`
- Phase execution plan path: `docs/phases/authority-mode-resolution.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 1 - Authority Mode And Resolver Contracts
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 2 will build protocol models on these resolver categories; Phase 8 and Phase 10 later provide registry persistence and runtime adoption.
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review
- Plan quality gate loop budget: consumed; do not reopen unless the v10 implementation plan changes materially
- Draft pass: completed by `loom_phase_planner` on 2026-05-11
- Refine pass: completed by `loom_phase_planner` on 2026-05-11 after manager review
- Setup limitations: none; `origin` was fetched and local `develop` matched `origin/develop` at worktree creation
- Blockers: none

## Objective

Define the stable, side-effect-free authority selection and resolver contract for v10 online and offline behavior, including explicit online mutation mode, explicit offline-first mode, resolver inputs, resolver outcomes, and actionable diagnostics.

## Full-Plan Context

This is the semantic root of v10. Later phases add transport-independent protocol models, FastAPI transport, durable private repository state, registry files, supervisor commands, runtime adoption, workspace coordination, resource leases, offline evidence, and import. This phase must not implement those later behaviors. It should make those phases possible by giving them shared vocabulary for online authority references, offline evidence intent, stale or incompatible registry hints, unhealthy or unavailable services, and reserved direct-database selections.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: this is the first v10 phase and the assignment records no unmerged predecessor
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete the phase branch and worktree after merge if no successor branch depends on it

## Source Phase Summary

- Goal: define the authority selection contract that all later online/offline behavior will use.
- Required scope: add explicit records for online authority mode, offline-first mode, resolver inputs, resolver outcomes, and failure diagnostics; cover minimal shared CLI/config/environment inputs needed to carry resolver intent; encode no implicit service start in new resolver semantics; classify `direct_database` as unsupported/reserved for v10 runtime mutation; distinguish unavailable, stale, incompatible, unhealthy, and explicit offline outcomes; preserve existing service APIs.
- Required checkpoints: stable importable contract types, side-effect-free resolver behavior, CLI/env/config normalization that does not imply offline execution support, direct-database diagnostics, explicit offline outcome, compatibility tests, and no runtime factory adoption.
- Acceptance criteria: resolver contract types are importable from stable non-transport modules under `src/loom/pipeline/stores/`; missing authority references fail closed for online mutation mode; direct-database inputs produce an unsupported/reserved diagnostic; explicit offline-first resolution succeeds as non-authoritative; diagnostics provide next steps without starting a service; existing authority store tests still pass or are adjusted only for contract clarity.

## Current Source And Harness Findings

- `src/loom/pipeline/stores/config.py` owns `AuthorityConfig`, `AuthorityReference`, backend/profile enums, env parsing, and CLI-argument serialization. `AuthorityConfig()` currently defaults to co-located service authority; Phase 1 must preserve that default-compatible construction until Phase 10 adopts strict resolver behavior in factories.
- `src/loom/pipeline/stores/deployment.py` owns deployment-profile diagnostics and preflight summaries. It already models co-located, managed, allocation-scoped, direct-database, and deferred-finalization profiles, but it is not a strict online/offline resolver.
- `src/loom/pipeline/stores/service_authority.py` provides the current stdlib local service fixture/client. `create_service_authority_store()` starts a shared co-located service when config has no endpoint, so Phase 1 must not route strict resolver checks through that factory.
- `src/loom/pipeline/stores/factory.py`, `src/loom/pipeline/execution/authority_adapter.py`, and CLI run/status/stage/stage-job/preflight/backend commands consume `AuthorityConfig` today. Full adoption of strict behavior is Phase 10 or later, not this phase.
- `src/loom/cli/authority.py` is the shared parser helper for authority options. It currently exposes backend/profile/endpoint/workspace/state/reference metadata, but no explicit authority mode or offline-first selection.
- Existing tests cover authority config parsing, deployment diagnostics, service authority behavior, public store contracts, backend diagnostics, and CLI backend behavior. New resolver coverage should fit beside these tests rather than replacing service/store conformance.
- Import-boundary constraint: resolver contracts must not import FastAPI, private SQLite implementation modules, or service process internals.

## In-Scope Work

- Add stable non-transport resolver records in a new module under `src/loom/pipeline/stores/`, preferably `authority_resolution.py`, rather than in CLI, service, factory, FastAPI, or SQLite modules.
- Treat resolver records, outcome categories, diagnostics, and the resolver entrypoint as intentional public package vocabulary for v10, exporting only that surface through `loom.pipeline.stores`; keep helper parsing/classification details private to the module.
- Define explicit mode/input/outcome/diagnostic records for online mutation resolution and offline-first resolution.
- Extend shared config/env/CLI normalization only enough for future commands to pass explicit online/offline resolver intent; parser additions must not advertise or enable offline execution before Phase 17.
- Implement a side-effect-free resolver that classifies missing authority, explicit endpoint references, registry-hint facts supplied by callers, stale generation, incompatible generation or version, unhealthy service, unavailable service, unsupported/reserved `direct_database`, and explicit offline selection.
- Keep current runtime factories and service APIs working during this phase unless a test adjustment is required to isolate the new contract.
- Add package, unit, contract, and minimal integration coverage for the resolver contract and shared option parsing.

## Out-of-Scope Work

- FastAPI server/client implementation.
- Durable SQLite repository or schema work.
- Workspace registry file persistence under `.loom/authority/`.
- Supervisor lifecycle commands or process management.
- Runtime factory adoption of the strict resolver.
- Runner, worker, SLURM, diagnostics, or preflight behavior changes beyond shared option/config parsing needed to carry resolver inputs.
- Offline execution CLI behavior, runtime support, or user-facing claims that `loom run` can execute offline before Phase 17.
- Offline evidence writing, offline import, or any claim that offline evidence is authority truth.
- Direct database access as a supported runtime mutation path.

## Assumptions

- `AuthorityConfig()` defaults remain backward-compatible for this phase; strict no-implicit-start behavior belongs to the new resolver API and is adopted by factories in Phase 10. New resolver intent must default compatibly when absent and must not add required constructor fields to `AuthorityConfig`.
- Offline-first mode can be represented as resolver intent/outcome now, even though execution support and evidence manifests are Phase 17 work.
- Registry and service health facts are inputs to the resolver in this phase. File IO, network probing, and supervisor health checks are later adapter responsibilities.
- `direct_database` remains parseable so stale env/CLI/config values can receive a precise unsupported/reserved diagnostic.

## Scope Contract

The resolver core must be deterministic and side-effect-free. Calling it must never start `LocalAuthorityService`, open SQLite files, read `.loom/authority/`, load registry files, call service endpoints, or perform network health checks. It accepts only supplied config, environment, CLI, registry-hint, health, generation, version, and capability facts, then normalizes those facts into typed outcomes.

Resolver records should live in a stable store-boundary module such as `src/loom/pipeline/stores/authority_resolution.py`. Because later phases and clients will depend on these names, public records, outcome enums, diagnostics, and the resolver entrypoint should be exported through `loom.pipeline.stores` deliberately and covered by package API tests. Transport-, repository-, service-process-, and CLI-specific adapters may feed facts into the resolver later, but they must not own or redefine the resolver vocabulary.

Online mutation mode requires a usable authority reference. Missing endpoint/registry facts, stale registry facts, incompatible generation/version facts, unhealthy service facts, unavailable service facts, and reserved direct-database selections produce non-success outcomes with actionable diagnostics. Offline-first mode is an explicit success outcome, but it is non-authoritative and must label later evidence/import requirements without implying that execution support exists in Phase 1. Existing runtime factories and `AuthorityConfig()` defaults must continue their current behavior until Phase 10 adopts this resolver.

## Design Impact

- Maintainability: separates authority-selection policy from service clients, repositories, CLI commands, and runtime factories.
- Extensibility: gives later FastAPI, registry, hosted, and supervisor phases stable outcome categories without assuming localhost, SQLite, or one transport.
- Domain neutrality: all records describe generic authority state, execution mode, diagnostics, and provenance requirements; no research-domain semantics are introduced.
- Source-tree boundaries: resolver contracts live under `src/loom/pipeline/stores/` in a stable non-transport module; CLI helpers may parse shared flags but must not own resolver semantics.

## Future Compatibility

Future phases should be able to add registry persistence, capability probing, FastAPI client checks, hosted authority references, and import provenance without changing the core online/offline outcome categories. If later source review proves additional failure classes are needed, they should be additive enum values with contract tests.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Continue inferring authority mode from missing endpoints | Missing endpoint currently triggers co-located service startup in some paths, which conflicts with v10 fail-closed semantics. |
| Treat offline mode as an exception or fallback after online failure | v10 requires explicit offline-first selection and evidence/import labeling. |
| Make the resolver call `create_service_authority_store()` for validation | That factory can start a co-located service, so it cannot be the strict resolver core. |
| Remove `direct_database` parsing immediately | Stale config should produce a clear reserved-profile diagnostic instead of an unknown-value error. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Existing factories still auto-bootstrap co-located service outside the new resolver | Phase 1 defines contracts while preserving current service APIs; Phase 10 owns adoption and behavior change. | Phase 10 strict resolver/factory adoption starts. |
| Registry and health checks are modeled as supplied facts, not live probes | Registry persistence and supervisor health checks do not exist yet. | Phase 8 registry records or Phase 9 supervisor lifecycle need real adapters. |
| Offline-first outcome exists before offline evidence writing | Later phases need shared vocabulary before execution support exists. | Phase 17 implements offline evidence writer. |

## Reviewability

- Expected PR size and shape: small to moderate contract PR with new resolver records, shared parsing additions, and focused tests.
- Files and areas to inspect: `src/loom/pipeline/stores/config.py`, new resolver module, `src/loom/pipeline/stores/__init__.py`, `src/loom/cli/authority.py`, authority config/deployment tests, new resolver contract tests, and any minimal CLI parser tests.
- Scope-control checks: no FastAPI imports, no SQLite repository work, no registry file IO, no supervisor commands, no runtime factory adoption, and no offline evidence files.

## Implementation Steps

1. Add resolver contract types and diagnostics in a stable non-transport store module, exporting only the public records/outcomes/entrypoint intended as v10 package vocabulary.
2. Extend shared authority config/env/CLI normalization to carry explicit resolver intent while leaving existing factory defaults and `AuthorityConfig()` construction intact.
3. Implement the side-effect-free resolver classification rules for missing references, supplied endpoint references, supplied registry/health/generation facts, direct-database reserved profile, and explicit offline mode.
4. Export the public contract surface and add package/import-boundary coverage to prove resolver modules do not import transport, service-process, or private SQLite implementation details.
5. Add unit, contract, and minimal integration tests for normalization, outcome classification, diagnostic rendering, and compatibility with existing authority store/service tests.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_store_api.py` and any package import-boundary test added for resolver contracts
- Required assertions or deferral reason: public exports from `loom.pipeline.stores` are stable, cheap to import, and do not pull in FastAPI, service process internals, or private SQLite implementation modules.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_authority_resolution.py`, `tests/unit/loom/pipeline/stores/test_authority_config_admission.py`, and `tests/unit/loom/cli/test_authority.py` if CLI parsing changes need a focused test file
- Required assertions or deferral reason: mode/env/CLI normalization, offline-first outcome, online missing-authority failure, direct-database reserved outcome, stale/incompatible/unhealthy/unavailable classifications, and diagnostic guidance.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authority_resolution_contract.py`
- Required assertions or deferral reason: future clients can distinguish online, offline, stale registry, incompatible generation/version, unavailable/unhealthy authority, and unsupported/reserved direct-database outcomes from typed data rather than message matching.

### Integration Suite

- Status: required but narrow
- Expected paths: focused CLI/config/env resolution coverage, plus existing `tests/integration/pipeline/test_authority_factory.py` and `tests/integration/pipeline/test_authority_deployment_profiles.py` as regression checks when touched
- Required assertions or deferral reason: shared CLI/config/env parsing can supply resolver inputs without starting a server or enabling offline execution, and existing public factories remain behaviorally unchanged in this phase.

### E2E Suite

- Status: deferred
- Expected paths: not required for this phase
- Required assertions or deferral reason: no user-facing runtime adoption or offline execution command is implemented in Phase 1.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: this phase must not require external authority services, real process supervisors, network health checks, or scheduler environments.

## Risks

- Resolver names may become long-lived public vocabulary, so ambiguous categories would be costly to unwind.
- Accidentally routing resolver checks through current service factories would start hidden services and violate the phase's core policy.
- Adding offline-first parsing without clear labeling could imply offline execution support exists before Phase 17.
- Changing `AuthorityConfig()` defaults or runtime factory behavior early would pull Phase 10 work into Phase 1.
- Direct-database diagnostics must be clear without making direct DB access look like a future-safe runtime option.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_store_api.py
uv run pytest tests/unit/loom/pipeline/stores/test_authority_resolution.py tests/unit/loom/pipeline/stores/test_authority_config_admission.py tests/unit/loom/cli/test_authority.py
uv run pytest tests/contracts/test_authority_resolution_contract.py
uv run pytest tests/integration/pipeline/test_authority_factory.py tests/integration/pipeline/test_authority_deployment_profiles.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: resolver contracts/exports, minimal shared parser normalization, resolver classification and diagnostics, then focused tests.
- Tests to run with each slice: resolver unit tests after contract implementation, package/contract tests after exports, integration regression tests only after parser/factory-adjacent edits.
- Decisions the executor must not revisit: resolver public vocabulary belongs in a stable non-transport store module and is exported intentionally from `loom.pipeline.stores`; the resolver core consumes supplied facts only and performs no probes or file reads; offline-first is explicit and non-authoritative; `direct_database` is reserved/unsupported for v10 runtime mutation; current factory adoption and `AuthorityConfig()` default changes are out of scope.
- Conditions that require stopping for the manager: inability to preserve existing service API behavior, need to change public runtime defaults, need for live registry/probe IO, or ambiguity that would affect later public protocol compatibility.
- Expanded-path refinement notes: completed; naming/export choices, supplied-facts-only resolver behavior, minimal CLI parsing scope, and `AuthorityConfig()` default compatibility are now explicit.

## Refinement And Review Budget Status

- Phase implementation refinement: used
- PR body draft: completed
- PR body refine: completed
- PR review: unused
- Blocker resolution: 1/3 used

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on 2026-05-11.
- Final phase execution plan: completed on 2026-05-11 by expanded-path refine pass.
- Implementation summary: completed locally by the managing agent on
  2026-05-11 after the `loom_phase_executor` Spark pass was unavailable due to
  model usage limits. Added `src/loom/pipeline/stores/authority_resolution.py`
  with side-effect-free resolver intent, supplied registry/health fact records,
  typed online/offline/failure outcomes, actionable diagnostics, and
  env/mapping mode helpers. Exported the public resolver vocabulary through
  `loom.pipeline.stores`. Added opt-in CLI namespace parsing for resolver mode
  without changing existing command defaults or runtime factory behavior.
- Implementation commits:
  - `054fd89 feat: add authority resolution contracts`
  - `73676fc test: add authority resolution coverage`
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_authority_resolution.py tests/unit/loom/pipeline/stores/test_authority_config_admission.py tests/unit/loom/cli/test_authority.py tests/contracts/test_authority_resolution_contract.py`
    passed with 37 tests.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores/authority_resolution.py src/loom/pipeline/stores/__init__.py src/loom/cli/authority.py tests/unit/loom/pipeline/stores/test_authority_resolution.py tests/unit/loom/cli/test_authority.py tests/contracts/test_authority_resolution_contract.py tests/package/test_pipeline_store_api.py`
    passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pyright` passed with 0
    errors.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_authority_factory.py tests/integration/pipeline/test_authority_deployment_profiles.py`
    failed in the sandbox because local service tests could not create sockets
    (`PermissionError: Operation not permitted`), then passed with escalation
    with 8 tests.
- Refinement summary: tightened public module/export choices, facts-only resolver constraints, minimal CLI parsing scope, and `AuthorityConfig()` compatibility boundaries.
- Implementation refinement pass:
  - Metadata: completed on 2026-05-11 in
    `/home/samcantrill/work/loom-worktrees/authority-mode-resolution` on
    branch `codex/authority-mode-resolution`; pass type was implementation
    refinement, consuming the phase implementation refinement budget.
  - Validation output reviewed: targeted package/unit/contract pytest, Ruff,
    Pyright, and integration authority factory/deployment validation recorded
    above.
  - Blocking issues caused by this phase: registry-supplied authority hints
    could be accepted as online references when the supplied hint had no
    endpoint, and registry hints pointing at `direct_database` could bypass the
    direct-database reserved diagnostic.
  - Issues confirmed out of scope: no runtime factory adoption, hidden service
    startup, registry file IO, FastAPI imports, private SQLite imports, or
    offline execution behavior changes were found in the Phase 1 diff.
  - Fixes made:
    | Issue | Change | Evidence |
    | --- | --- | --- |
    | Registry hint without endpoint could resolve as online authority. | Added fail-closed `MISSING_AUTHORITY` classification with registry endpoint diagnostic. | Unit and contract coverage added. |
    | Registry hint with `direct_database` backend could resolve as online authority. | Added `RESERVED_DIRECT_DATABASE` classification for registry hints before accepting the reference. | Unit and contract coverage added. |
    | Import-boundary package coverage did not name all Phase 1 forbidden imports. | Added package assertions for FastAPI, service authority, and private SQLite modules. | Package test coverage expanded. |
  - Tests or validation re-run:
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_authority_resolution.py tests/unit/loom/cli/test_authority.py tests/contracts/test_authority_resolution_contract.py`
      passed with 38 tests.
    - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores/authority_resolution.py tests/unit/loom/pipeline/stores/test_authority_resolution.py tests/contracts/test_authority_resolution_contract.py tests/package/test_pipeline_store_api.py src/loom/cli/authority.py tests/unit/loom/cli/test_authority.py`
      passed.
    - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pyright` passed with
      0 errors, 0 warnings, and 0 informations.
  - Remaining blockers: none.
  - PR preparation handoff: completion notes and budget status are updated;
    final PR preparation should still run `make validate-pr` and
    `make test-summary`.
- Blocker-resolution summary: 1/3 used.
  - Pass 1 addressed the pre-submit validation blocker found during PR body
    draft preparation: `tests/unit/loom/pipeline/stores/test_store_errors.py`
    asserted the exact `loom.pipeline.stores.__all__` list and had not been
    updated for the new public resolver exports. The scoped fix updated that
    expected export list only.
  - Validation after the fix:
    `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_store_errors.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_authority_resolution.py tests/contracts/test_authority_resolution_contract.py`
    passed with 37 tests, and
    `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check tests/unit/loom/pipeline/stores/test_store_errors.py`
    passed.
- PR preparation draft:
  - Metadata: completed on 2026-05-11 in
    `/home/samcantrill/work/loom-worktrees/authority-mode-resolution` on
    branch `codex/authority-mode-resolution`.
  - PR facts confirmed: title
    `DB-Backed Authority Supervisor And Offline Import - Phase 1: Authority Mode And Resolver Contracts`;
    PR body path `docs/phases/authority-mode-resolution-pr-body.md`; target
    branch `develop`; stack predecessor none; root phase merge-eligible only
    after PR targets `develop` and automated gates pass.
  - Draft-only status: PR body draft completed from
    `.codex/templates/phase-pr-body.md`; PR body refine pass remains pending
    because this phase is on the expanded path. PR creation was not attempted
    in this draft pass.
  - Final validation evidence:
    - Sandboxed `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed Ruff and
      Pyright, then failed in the default harness because local service tests
      could not create sockets (`PermissionError: Operation not permitted`).
      Escalated rerun passed: Ruff passed, Pyright reported 0 errors, default
      isolated harness passed with 1173 passed, 18 skipped, and 14 deselected;
      config-extra passed with 420 passed and 1202 deselected; `uv build`
      produced sdist and wheel artifacts.
    - Sandboxed `UV_CACHE_DIR=/tmp/uv-cache make test-summary` wrote a failed
      summary for the same socket-permission limitation. Escalated rerun
      passed and wrote `build/test-summary.md` at
      2026-05-11T05:01:24+00:00 with package 61 passed/1 skipped, unit 878
      passed/1 skipped, contract 120 passed/2 skipped, integration 101
      passed/8 skipped/10 deselected, e2e 39 passed/1 deselected,
      config-extra 420 passed/1202 deselected, and overall 1619 passed/12
      skipped/1213 deselected.
  - Pre-submit blocker gate: passed after reviewing the v10 implementation
    plan, phase execution plan, final diff against `develop`, PR body draft,
    validation evidence, scope boundary, and known risks. No additional
    blockers found; no implementation refinement was performed during PR
    preparation.
- PR body refine/open pass:
  - Metadata: completed on 2026-05-11 in
    `/home/samcantrill/work/loom-worktrees/authority-mode-resolution` on
    branch `codex/authority-mode-resolution`.
  - PR body verification: matched the v10 implementation plan, Phase 1
    execution plan, final diff against `develop`, acceptance criteria, scope
    boundaries, assumptions, risks, and final validation evidence. No future
    phase work, runtime factory adoption, FastAPI/server work, registry file IO,
    supervisor lifecycle behavior, durable repository work, offline evidence,
    or offline import behavior was found in the Phase 1 diff.
  - Corrections made: updated the public PR body's GitHub checks row so it no
    longer described the earlier draft-only state; no source or test changes
    were made.
  - PR opened: https://github.com/samcantrill/loom/pull/119.
  - PR verification: `gh pr view 119 --json baseRefName,headRefName,state,url`
    returned base `develop`, head `codex/authority-mode-resolution`, state
    `OPEN`, and URL `https://github.com/samcantrill/loom/pull/119`.
  - Merge eligibility: root phase PR targeting `develop`; merge-eligible only
    after automated review and GitHub/validation gates pass. Stack predecessor
    remains none.
- Stack maintenance: not applicable yet.
- Remaining blockers: none.
