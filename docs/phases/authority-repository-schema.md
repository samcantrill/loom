# Phase 4 Execution Plan: Private Repository Schema And Versioning

## Metadata

- Status: refined phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 4: Private Repository Schema And Versioning`
- Branch: `codex/authority-repository-schema`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-repository-schema`
- Phase execution plan path: `docs/phases/authority-repository-schema.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 4 - Private Repository Schema And Versioning
- Stack predecessor: none; Phase 3 is merged in PR #121 and recorded in the plan
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 5 adds run lifecycle repository behavior; Phase 6 adds stage lifecycle and attempts; Phase 7 wires repository behavior to FastAPI mutation routes.
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Plan quality gate loop budget: consumed; do not reopen unless the v10 implementation plan changes materially
- Draft pass: completed by managing agent on 2026-05-11
- Refine pass: completed by managing agent on 2026-05-11
- Setup limitations: none unresolved. Branch and worktree were created from local `develop` at `73cc68f`, after Phase 3 merge metadata was pushed.
- Blockers: none; implementation may begin from this refined phase execution plan.

## Objective

Create the private, service-owned SQLite repository foundation for the authority server: explicit state-directory initialization, schema versioning, service generation metadata, repository identity facts, compatibility failures, and transaction boundaries without implementing run/stage lifecycle mutation behavior or FastAPI route wiring.

## Full-Plan Context

Phase 3 introduced the FastAPI app and dependency boundary. Phase 4 creates the private durable repository foundation that later phases inject behind that boundary. It must make the DB a service implementation detail, not a public runtime or client API, while still exposing enough private typed facts for later readiness, diagnostics, mutation, and supervisor phases.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 3 merged to `develop` in PR #121
- Why this base branch is correct: the implementation plan records Phase 3 merged, the control checkout was fast-forwarded to `develop`, and no unmerged predecessor branch exists
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete the phase branch and worktree after merge if no successor phase branch depends on it

## Source Phase Summary

- Goal: create service-owned durable repository foundation with private SQLite schema versioning and transactions.
- Required scope: private repository module, SQLite connection handling, schema bootstrap/checks, explicit transactions, service generation metadata, repository identity metadata, and compatibility errors.
- Required checkpoints: explicit state directory, schema version persistence, transaction commit/rollback coverage, repository privacy tests, and compatibility failures for missing, older, newer, and corrupt schemas.
- Acceptance criteria: repository initializes under an explicit state directory, persists schema/generation facts, transactions are testable, compatibility errors are cleanly mappable later, and public clients have no direct DB mutation path.

## Current Source And Harness Findings

- `src/loom/authority` is the Phase 3 private service package root. Its `__init__.py` is intentionally lightweight and does not import FastAPI or core store modules; Phase 4 should keep repository internals out of this root.
- `src/loom/pipeline/stores/sqlite_authority.py` and `sqlite_coordination.py` use private SQLite schemas, `sqlite3.Row`, `PRAGMA foreign_keys = ON`, explicit `BEGIN IMMEDIATE` transactions, and loud-fail schema checks. Phase 4 should reuse these patterns rather than copy full lifecycle schema.
- Existing `src/loom/pipeline/stores/schema_policy.py` owns public active-state schema checks for existing store backends. The new service repository can define private repository-specific compatibility failures, but it should not publish SQL schema as a public compatibility contract.
- Package import tests already protect `loom.pipeline.stores` from importing SQLite implementation modules. Phase 4 should add privacy coverage proving `loom.authority` import remains lightweight and does not import `sqlite3` or the private repository.

## In-Scope Work

- Add a private repository module under `src/loom/authority/`, preferably `_repository.py`, that is not imported by `loom.authority.__init__`.
- Define repository constants for schema version and database filename, plus value records for repository identity and compatibility failures.
- Implement explicit state-directory initialization, SQLite connection setup, schema bootstrap, metadata persistence, compatibility checks, and transaction context management.
- Persist at least schema version and service generation metadata in a private metadata table.
- Add package, unit, contract, and integration tests for privacy, initialization, version checks, corrupt/missing schema handling, generation identity, and transaction commit/rollback.

## Out-of-Scope Work

- Run lifecycle tables beyond metadata/schema foundation.
- Stage lifecycle, attempts, leases, output commits, artifact facts, workspace coordination, resource admission, or offline import tables.
- FastAPI route mutation wiring, readiness route repository probing, HTTP status mapping, or client transport behavior.
- Supervisor process commands, registry files, runtime factory adoption, direct-database runtime support, or public exports from `loom.pipeline.stores`.

## Assumptions

- The repository database file can be named `authority.sqlite3` inside an explicit service state directory.
- Service generation can be generated locally with UUID entropy unless an explicit generation is supplied by a later supervisor phase.
- Tests may import the private `_repository` module directly because the module is private but still unit-testable.
- Compatibility failures should be structured enough for later server/protocol mapping without importing FastAPI or route code into the repository module.

## Scope Contract

The repository module is a private implementation detail of the authority service. It may import `sqlite3`, `Path`, and stable lower-level Loom value helpers, but it must not be re-exported from `loom.authority`, `loom.pipeline.stores`, or CLI packages. Importing `loom.authority` must not import `sqlite3`.

The repository must initialize only from an explicit state directory supplied by the caller. Schema bootstrap creates a private metadata table, persists `schema_version`, `service_generation`, and creation/update timestamps, and verifies that existing metadata is compatible before returning identity facts.

Compatibility failures must distinguish:

- missing repository database or metadata;
- unsupported older schema version;
- unsupported newer schema version;
- corrupt or invalid schema metadata/shape.

Transactions must be explicit and testable. A committed transaction must persist its writes, and an exception inside a transaction must roll back its writes.

## Design Impact

- Maintainability: keeps durable state ownership in one private repository module rather than spreading ad hoc SQLite connections across future routes.
- Extensibility: identity and compatibility records let later readiness, diagnostics, and mutation phases adapt repository state without exposing SQL details.
- Domain neutrality: schema metadata describes Loom authority service state only, with no research-domain semantics.
- Source-tree boundaries: FastAPI app code can inject this repository later, but Phase 4 does not make route modules open databases.

## Future Compatibility

The schema foundation should support additive tables in Phases 5 and 6, service-generation/fencing checks in supervisor phases, and repository diagnostics in later readiness/status flows. It should avoid a large backend abstraction before the SQLite service repository has concrete lifecycle behavior.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Reuse `SQLitePerRunAuthorityStore` as the service runtime DB | The v10 plan requires a service-owned private repository rather than public/direct per-run DB access. |
| Put repository code under `loom.pipeline.stores` | Store protocols are public-ish runtime contracts; the service DB is a private implementation detail. |
| Publish SQL schema through public exports | The schema must remain private and migratable. |
| Let route handlers open SQLite connections directly | Later route phases should depend on injected repository/service objects, not ad hoc connection code. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Repository initially stores only metadata and schema identity | Phase 4 is the foundation; lifecycle tables are owned by later repository phases. | Phase 5 starts run lifecycle repository behavior. |
| Compatibility-to-protocol mapping is represented by structured failures, not HTTP responses | Server route mapping belongs to Phase 7. | FastAPI mutation/readiness routes begin handling repository failures. |
| SQLite is the only concrete private repository backend | The roadmap chooses local DB-backed authority first; alternate backends are future work. | Hosted or non-SQLite authority backend is planned. |

## Reviewability

- Expected PR size and shape: moderate private repository module plus focused package, unit, contract, and integration tests.
- Files and areas to inspect: `src/loom/authority/_repository.py`, `src/loom/authority/__init__.py`, package import-boundary tests, repository unit tests, contract compatibility tests, and tempdir-backed integration tests.
- Scope-control checks: no public exports, no FastAPI route wiring, no run/stage lifecycle implementation, no runtime factory adoption, no registry writes, and no direct-database supported profile.

## Implementation Steps

1. Add the private repository module with schema/version constants, compatibility failure records, repository identity, state-dir path resolution, and service-generation helper.
2. Implement SQLite connection setup, schema bootstrap, metadata reads/writes, compatibility checks, and explicit transaction context management.
3. Add package import-boundary tests that keep `loom.authority` lightweight and repository internals private.
4. Add unit and contract tests for identity records, compatibility failures, version classifications, and protocol-mappable failure codes.
5. Add integration tests using temporary directories for initialization, reopen, missing/corrupt/newer/older schema errors, and transaction commit/rollback.
6. Run targeted validation, then final `make validate-pr` and `make test-summary` before PR preparation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py` and a package/private-boundary assertion if useful
- Required assertions or deferral reason: importing `loom.authority` does not import `sqlite3`, FastAPI, the private repository module, or pipeline store implementations; repository symbols are not re-exported from public package roots.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/authority/test_repository.py`
- Required assertions or deferral reason: path derivation, service-generation validation, identity values, metadata serialization, compatibility failure categories, invalid version handling, and transaction rollback behavior that can be tested without public APIs.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authority_repository_contract.py`
- Required assertions or deferral reason: compatibility failure categories and codes are stable enough for later protocol/server error mapping, without importing FastAPI.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/authority/test_repository.py`
- Required assertions or deferral reason: file-backed initialization under explicit state directories, reopen preserves identity, missing DB fails loudly, older/newer/corrupt schemas classify correctly, and transactions commit/rollback.

### E2E Suite

- Status: deferred
- Expected paths: not required for this phase
- Required assertions or deferral reason: no CLI, supervisor process, route mutation, runtime caller, or user workflow behavior changes.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: no network, scheduler, external service, or long-running process is required.

## Risks

- Accidentally exposing the private repository through public package roots would make direct DB access look supported.
- Under-modeling compatibility failures would make later readiness and route error mapping ambiguous.
- Overbuilding lifecycle tables in this phase would make review harder and duplicate Phase 5/6 work.
- Weak transaction tests could miss rollback bugs that later mutation routes would rely on.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/authority/_repository.py tests/unit/loom/authority/test_repository.py tests/contracts/test_authority_repository_contract.py tests/integration/authority/test_repository.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/authority/_repository.py tests/unit/loom/authority/test_repository.py tests/contracts/test_authority_repository_contract.py tests/integration/authority/test_repository.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py tests/unit/loom/authority/test_repository.py tests/contracts/test_authority_repository_contract.py tests/integration/authority/test_repository.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: private repository values/constants, connection/bootstrap, compatibility checks, transaction tests, then privacy/import-boundary tests.
- Tests to run with each slice: unit repository tests after values/bootstrap, integration tempdir tests after connection/transaction code, contract tests after compatibility records, package tests after import-boundary changes.
- Decisions the executor must not revisit: repository stays private under `loom.authority`, no public exports, no FastAPI wiring, no lifecycle mutation behavior, and no direct-database runtime support in this phase.
- Conditions that require stopping for the manager: need to expose repository symbols publicly, need to alter Phase 3 app route contracts, need to add a heavy dependency beyond stdlib SQLite, or inability to classify schema compatibility failures without broad schema redesign.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-11 by managing agent after
  implementation and validation; no code changes were required
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-11.
- Final phase execution plan: completed by managing agent on 2026-05-11.
- Implementation summary: added the private `loom.authority._repository`
  SQLite foundation with explicit state-directory initialization, schema
  version metadata, service generation identity, compatibility failures for
  missing/older/newer/corrupt repositories, and explicit write transaction
  commit/rollback handling. Added package privacy, unit, contract, and
  file-backed integration coverage without exporting repository symbols from
  `loom.authority`.
- Implementation validation: targeted `ruff`, `pyright`, and focused package,
  unit, contract, and integration pytest passed for the repository changes.
  Final `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed, including Ruff,
  Pyright, default pytest with 1218 passed, 18 skipped, 14 deselected,
  config-extra pytest with 420 passed and 1247 deselected, and package build.
  Final `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with overall
  1664 passed, 12 skipped, and 1258 deselected.
- Refinement summary: bounded implementation review inspected repository
  privacy, schema/version handling, compatibility classifications, transaction
  behavior, and test coverage. No scope or correctness blockers were found, and
  no code changes were required after the validation pass.
- Blocker-resolution summary: not needed; 0/3 blocker-resolution passes used.
- PR preparation: PR body prepared in
  `docs/phases/authority-repository-schema-pr-body.md`; PR opening pending.
- Stack maintenance: root phase targets `develop`; no successor branch depends
  on `codex/authority-repository-schema` yet.
- Remaining blockers: none known.
