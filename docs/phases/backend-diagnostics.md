# Phase 6 Execution Plan: Read-Only Backend Diagnostics CLI

## Metadata

- Status: final phase execution plan; ready for implementation.
- Feature focus: Persistence And Concurrency Foundation
- Final PR title: `Persistence And Concurrency Foundation - Phase 6: Read-Only Backend Diagnostics CLI`
- Branch: `codex/backend-diagnostics`
- Worktree: `/home/samcantrill/work/loom-worktrees/backend-diagnostics`
- Phase execution plan path: `docs/phases/backend-diagnostics.md`
- Full plan: `docs/implementation-plans/implementation-plan-v9.md`
- Source phase: Phase 6 - Read-Only Backend Diagnostics CLI
- Stack predecessor: none; Phases 1, 2, 3, 4, and 5 are merged into
  `develop`.
- Base branch: `develop`
- Base commit: `9e1fefa86e71b8d55077cce91a9e4d8fdc3a3a16`
  (`docs: record v9 phase 5 merge`)
- Target branch: `develop`
- Merge eligibility: root phase PR; merge eligible after the implementation
  stays in Phase 6 scope, required validation passes or unavailable checks are
  justified, automated review has no blocking findings, CI passes, and the PR
  still targets `develop`.
- Workflow path: expanded path because this phase creates a new public CLI/API
  diagnostic surface over authoritative backend state, schema/capability
  diagnostics, projection freshness, and materialization warnings.
- Successor dependency notes: Phase 7 can reuse capability diagnostics for
  loud parallel-execution preflight, and Phase 8 can reuse the same diagnostic
  model style for cross-run coordination. Neither successor should depend on
  SQLite table details or mutation behavior from this phase.
- Plan quality gate: passed on 2026-05-09 by `loom_plan_reviewer`; no
  blocking or non-blocking findings remained.
- Plan quality gate loop budget: initial review used; gate refinement and
  confirmation review were not needed.
- Draft pass: complete by `loom_phase_planner` in draft-plan commit
  `fe8c8c8`.
- Refine pass: complete on 2026-05-10 by `loom_phase_planner`; the expanded
  pass reread the draft plan, implementation-plan v9, phase prompt, template,
  and current CLI/diagnostics/store/read-model/test boundaries, then tightened
  command semantics, warning/failure behavior, no-mutation proof obligations,
  projection evidence, and stop conditions.
- Setup limitations: branch/worktree creation used local `develop` at the
  manager-provided current pushed Phase 5 metadata commit. No remote fetch,
  GitHub operation, broad validation, PR action, or implementation was run
  during planning. Worktree creation required approved sandbox escalation after
  the default sandbox could not write the namespaced `codex/` branch ref.
- Blockers: none.

## Objective

Add minimal read-only backend diagnostics APIs and `loom backend ...` CLI
commands so users and future tools can inspect authoritative backend facts,
capabilities, schema state, revisions, materialization diagnostics, and
consistency warnings without creating repair, mutation, export, SQL, snapshot,
or alternate-truth workflows.

## Full-Plan Context

V9 has already merged the backend authority contracts, run-local SQLite
backend, authoritative read/materialization helpers, serial write-path
integration, and public serial hard swap. New serial runs now use backend
truth, and status/catalog reads have been moved onto backend snapshots or
read models.

Phase 6 presents that authority for debugging and operational inspection. It
must stay diagnostic-only: Phase 7 owns bounded parallel execution, Phase 8
owns workspace/sweep coordination, V10 owns export/bundle workflows, and later
reliability work owns repair or cleanup mutation semantics.

## Stack Context

- Root or stacked phase: root phase based directly on `develop`.
- Current predecessor branch or PR: none; Phase 5 is merged.
- Why this base branch is correct: implementation-plan v9 records Phases 1-5
  as `merged`, and the manager assigned `develop` as the target with no stack
  predecessor.
- Retarget/rebase plan after predecessor merge: no predecessor retarget is
  needed. If `develop` advances before PR preparation, rebase this root branch
  onto updated `develop` and keep the PR target as `develop`.
- Branch cleanup constraints: branch can be deleted after merge if no successor
  branch depends on it.

## Source Phase Summary

- Goal: make the new authority inspectable and keep derived projections honest
  without creating mutation, repair, export, SQL, or snapshot workflows.
- Required scope: minimal read-only `loom backend ...` commands; Python API
  helpers used by the CLI; capability, schema, run fact, attempt, lease,
  submitted-operation, commit, revision, materialization, stale projection,
  actively-changing, shared-filesystem, and remote-store diagnostics.
- Required checkpoints: CLI/API inspection imports no project stage code, loads
  no artifact payloads, does not query private SQLite tables from CLI modules,
  emits machine-readable diagnostics for text and JSON, and proves inspection
  does not mutate backend state.
- Acceptance criteria: commands are read-only; enough lifecycle/backend detail
  is visible for debugging; unsupported shared-filesystem or remote assumptions
  are loud diagnostics; tests cover no-mutation behavior and import
  boundaries.

## Current Source And Harness Findings

- `src/loom/cli/main.py` registers top-level command modules lazily and expects
  each module to expose `register_subparser()` plus a handler. A new
  `src/loom/cli/backend.py` should follow that pattern and keep presentation
  thin.
- Existing CLI commands use `OutputFormat`, `format_json_envelope()`, and
  concise text formatters from `src/loom/cli/formatting.py`. Backend diagnostics
  should use the same JSON envelope style with a new schema version.
- `src/loom/diagnostics/inspection.py` already provides public-ish diagnostic
  facades for status, artifacts, and logs. Phase 6 should add backend-specific
  helpers in `loom.diagnostics` or a narrowly named diagnostics module instead
  of making CLI code parse store internals.
- `src/loom/pipeline/stores/authority.py` exposes the backend-neutral
  `PerRunAuthorityStore` contract: capabilities, schema checks, snapshots,
  attempts, leases, submitted operations, output commits, revisions, recovery
  scans, and cleanup candidates.
- `src/loom/pipeline/stores/materialization_read_models.py` provides
  `read_authoritative_run()`, `AuthoritativeReadOptions`,
  `LocalMaterializationRequest`, projection-revision warnings, active-run
  revision-change warnings, schema warnings, and materialized-ref diagnostics.
  Reuse this boundary rather than adding a second read-model interpreter.
- `src/loom/runs/_extract.py` and the v8/v9 catalog models still represent
  derived projection freshness separately from authoritative backend revision.
  Phase 6 can accept explicit projection revision evidence and report
  staleness, but it must not rebuild or mutate catalog sidecars to create that
  evidence.
- `src/loom/pipeline/stores/capabilities.py` already has capability records,
  diagnostic severities, and unsupported capability codes for missing
  capability, unsafe shared filesystem, and unsafe remote coordination. Phase 6
  should map those records to CLI/API diagnostics instead of inventing a
  parallel vocabulary.
- `src/loom/pipeline/stores/sqlite_authority.py` keeps database placement and
  schema private. Phase 6 may construct/open the SQLite backend through its
  public class or store factory, but only the SQLite module may know table
  names or execute SQL.
- Phase 5 made missing or unavailable authority for authority-marked runs a
  loud diagnostics/catalog condition. Backend diagnostics should preserve that
  no-fallback rule and not reinterpret legacy local files as current truth.
- Existing tests cover CLI parser registration, diagnostics status/artifacts,
  materialization read-model warnings, SQLite serial execution, and e2e CLI
  smoke behavior. Phase 6 should add focused backend diagnostics tests instead
  of broadening unrelated command assertions.

## In-Scope Work

- Add a small diagnostics API that opens the selected authoritative backend for
  a `run_uri`, checks schema, reads capabilities, assembles an authoritative
  read model, and returns serializable diagnostic result records.
- Add minimal `loom backend ...` CLI commands:
  - `loom backend inspect RUN_URI` for schema, backend name, revision,
    lifecycle facts, attempt/lease/submitted-operation/commit/artifact counts,
    warnings, and optional stage-level detail;
  - `loom backend capabilities RUN_URI` for capability records and loud
    diagnostics when explicit shared-filesystem or remote-store assumptions are
    requested;
  - allow materialization diagnostics through `inspect` flags rather than a
    separate export/snapshot workflow.
- Support text and JSON output. JSON must use stable schema-versioned envelope
  output and plain-data result records; text should be compact and focused on
  debugging.
- Surface machine-readable warnings for unsupported or missing schemas, stale
  projection evidence when a projection revision is provided, actively changing
  runs during verified reads, missing/corrupt materialized refs, partial
  commits, and unsupported capability assumptions.
- Provide explicit shared-filesystem and remote-store requirement flags whose
  unsupported diagnostics are loud. Default local inspection may report these
  as warnings or unsupported capability records without failing.
- Normalize CLI warning and failure behavior: nonfatal diagnostics should
  return success with warnings and `ok: true` JSON, while missing authority,
  unreadable/unsupported schema in a requested authoritative run, malformed
  projection revision input, or explicitly required unsupported shared/remote
  capabilities should return an existing nonzero CLI error category with
  machine-readable context.
- Keep all inspection read-only: use `check_schema()`, `capabilities()`,
  `snapshot()`, `scan_recovery()`, `list_cleanup_candidates()`, and
  `read_authoritative_run()`; do not call mutating backend methods.
- Verify materialized refs only by safe metadata/existence/checksum checks
  already supported by the read-model layer. Do not load artifact payloads or
  import project stage factories.
- Add package, unit, contract, integration, and e2e coverage scoped to the new
  diagnostics API/CLI and no-mutation guarantees.

## Out-of-Scope Work

- No backend mutation, repair, cleanup, lease release, recovery application,
  export, import, bundle, SQL, or snapshot command.
- No public SQLite schema, supported database path contract, table names, or
  direct SQL access from CLI/diagnostics modules.
- No remote authoritative backend, service backend, Postgres backend, hosted
  tracker, dashboard UI, or scheduler-backed authority.
- No bounded parallel execution, worker pool, multi-controller behavior, or
  workspace/sweep coordination.
- No old v0-v8 run migration or legacy local-file active-state fallback.
- No status enum widening and no reinterpretation of submitted-operation
  records as scheduler truth.
- No artifact payload loading, project-code import, domain-specific metric
  interpretation, or non-stdlib runtime dependency.

## Assumptions

- The executor may refine exact model names, but the CLI command group and
  read-only behavior are fixed scope.
- `RUN_URI` is the public run identity; filesystem paths should only be
  accepted if existing CLI utilities already normalize them safely for run
  inspection.
- Missing authority for an authority-marked run is an error diagnostic. A run
  with no authority marker is outside the v9 backend diagnostics target and
  should fail loudly rather than falling back to legacy state files.
- The diagnostics API may default to `SQLitePerRunAuthorityStore` for current
  local runs while keeping the result model backend-neutral for future
  backends.
- Projection freshness diagnostics can be driven by explicit projection
  revision input or helper-provided revision evidence. Do not add catalog
  rebuild or sidecar mutation to produce that evidence in this phase.
- Diagnostics may include recovery candidates and cleanup candidates, but they
  must present them as facts requiring later policy, not apply recovery or
  delete materialized files.

## Scope Contract

`loom backend ...` is an inspection surface, not an administration surface. It
may read authoritative facts and present diagnostics, but it must not change
backend state, materialized files, derived catalogs, or legacy documents.

Public behavior should be minimal and stable:

- `loom backend inspect RUN_URI [--stage STAGE] [--verify-materialization]
  [--projection-revision SEQUENCE:TOKEN] [--format text|json]`
- `loom backend capabilities RUN_URI [--require-shared-filesystem]
  [--require-remote] [--format text|json]`

The executor may adjust flag spelling only to fit existing CLI conventions, but
the semantics must stay intact: default inspection is read-only and local;
explicit shared-filesystem or remote requirements produce loud diagnostics when
the selected backend cannot prove those guarantees.

`--projection-revision` is read-only comparison evidence. It should parse the
same sequence/token shape used by `BackendRevision`; malformed input is a CLI
usage or run-state error, and valid stale evidence produces a stale-projection
diagnostic without updating any projection.

Exit semantics are part of the public contract for this phase. A successful
diagnostic read with warnings returns success and includes those warnings in
text/JSON. A request that cannot be answered from authoritative backend state,
or that explicitly requires unsupported shared-filesystem or remote guarantees,
returns a nonzero CLI result with the same diagnostic records preserved for
JSON callers.

The JSON result must be plain-data and schema-versioned. It should include
backend identity, run URI, schema status, current backend revision, capability
records or capability diagnostics, warning records, summary counts, and
selected detailed records for stages, attempts, leases, submitted operations,
commits, artifact facts, cleanup candidates, materialized refs, and recovery
candidates. Text output may summarize the same data but should not hide
warnings or errors.

CLI code must not parse SQLite internals. The allowed read boundaries are
backend-neutral contracts and read-model helpers. Any implementation that needs
SQLite table names, repair actions, or raw SQL outside `sqlite_authority.py`
must stop as a scope blocker.

Materialization verification is diagnostic only. Missing or corrupt payloads,
logs, config copies, provenance documents, or worker handoff files become
warnings or strict diagnostics; they do not alter lifecycle truth or attempt to
repair files.

Detailed record output is allowed, but it should remain bounded and
reviewable. `inspect` may include per-stage detail and counts by default; if a
run has many records, the executor may add narrow selectors such as
`--stage STAGE` rather than invent pagination, streaming, or export behavior.

## Acceptance Criteria

- `loom backend ...` appears in top-level CLI help and has text/JSON smoke
  coverage.
- Backend diagnostics API returns plain-data serializable records for
  capabilities, schema, revision, lifecycle, attempts, leases,
  submitted-operation, commit, artifact, materialization, and consistency
  diagnostics.
- CLI modules call diagnostics APIs and do not import or query private SQLite
  tables.
- Shared-filesystem and remote-store assumptions produce explicit unsupported
  capability diagnostics when the selected backend cannot prove them.
- Unsupported schema, missing authority, stale projection, actively changing
  run, missing/corrupt materialization, and partial-commit conditions map to
  stable warning or error records.
- Default warning-only reads preserve warnings in both text and JSON; explicit
  unsupported shared/remote requirements and unavailable authoritative state
  fail loudly without hiding diagnostic detail.
- Tests prove inspection does not mutate backend revision, lifecycle facts,
  submitted operations, attempts, leases, commits, cleanup candidates, or
  materialized files.
- Backend inspection imports no project stage code and does not load artifact
  payloads.

## Design Impact

- Maintainability: centralizes backend inspection in `loom.diagnostics` so CLI,
  future parallel preflight, and later coordination diagnostics do not each
  reinterpret backend state.
- Extensibility: keeps results backend-neutral so a future service or remote
  backend can satisfy the same diagnostics without exposing SQLite schema.
- Domain neutrality: reports generic runtime facts, capabilities, warnings,
  refs, and revisions only; it does not interpret artifact payload semantics.
- Source-tree boundaries: CLI remains presentation, diagnostics remains
  read-only facade, store contracts/read models remain the authority boundary,
  and SQLite internals stay private to the store implementation.

## Future Compatibility

- V10 bundle/export work can add explicit derived snapshot/export behavior
  separately without inheriting mutation or SQL expectations from
  `loom backend`.
- Phase 7 can reuse capability diagnostics to fail loudly when explicit
  parallel execution requires unsupported claim, lease, commit, revision, or
  recovery behavior.
- Phase 8 can present cross-run coordination diagnostics using the same
  capability and warning model while keeping per-run and workspace authorities
  separate.
- Future remote/service backends can add richer capability and materialization
  detail without changing the CLI into a SQLite-specific tool.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Adding repair, cleanup, or recovery mutation commands | V9 Phase 6 is read-only; mutation semantics belong to later reliability work with explicit safety rules. |
| Adding export/import or snapshot commands under `loom backend` | V10 owns user-facing bundle/export workflows, and this phase must not create an alternate export contract. |
| Exposing SQL or documented SQLite database paths | SQLite schema and placement are private implementation details, and future backends must be replaceable. |
| Letting CLI modules query SQLite directly | It would bypass the backend-neutral read model and hard-code the first backend into public presentation code. |
| Falling back to legacy status/artifact files when authority is missing | V9's hard swap requires backend truth for new runs and loud diagnostics for missing authority. |
| Creating many fine-grained subcommands for every record type | A small inspect/capabilities surface keeps the PR reviewable and avoids a premature administration UI. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Backend diagnostics are read-only and do not offer repair convenience | Prevents diagnostics from becoming unsafe mutation or alternate truth workflows. | A later reliability roadmap defines safe repair, recovery, or cleanup mutation semantics. |
| The first implementation defaults to local SQLite-backed authority | SQLite is the only v9 production backend so far, while result records remain backend-neutral. | A non-SQLite backend is added and needs adapter-specific diagnostic detail. |
| Projection freshness checks depend on provided or discoverable revision evidence | Phase 6 should not mutate or rebuild derived projections merely to inspect them. | Catalog/dashboard workflows need automatic projection reconciliation as a public operation. |

## Reviewability

- Expected PR size and shape: moderate diagnostics/CLI PR with new result
  models and formatters, one CLI command module, focused tests, and no runner,
  catalog mutation, schema, or SQLite table-query changes.
- Files and areas to inspect: `src/loom/diagnostics/`, `src/loom/cli/main.py`,
  new `src/loom/cli/backend.py`, `src/loom/cli/formatting.py`,
  `src/loom/pipeline/stores/materialization_read_models.py` only if a small
  read option is unavoidable, `src/loom/pipeline/stores/capabilities.py` only
  for strictly additive diagnostic mapping, and tests under `tests/package/`,
  `tests/unit/loom/diagnostics/`, `tests/unit/loom/cli/`,
  `tests/contracts/`, `tests/integration/pipeline/`, and `tests/e2e/`.
- Scope-control checks: no mutating authority methods in diagnostics/CLI; no
  SQL outside `sqlite_authority.py`; no export/snapshot/repair command; no
  legacy fallback; no artifact payload loads; no project-code imports; no
  status enum changes; no parallel execution or workspace coordination.

## Implementation Steps

1. Add backend diagnostics result models and helper functions that open the
   selected authority, collect schema/capability/read-model evidence, normalize
   warnings, and expose plain-data output.
2. Add the `loom backend` CLI module and register it in `cli.main`, with
   compact text formatting and schema-versioned JSON output.
3. Wire materialization and projection freshness options through
   `read_authoritative_run()` without adding projection mutation or SQLite
   direct reads.
4. Add shared-filesystem and remote requirement diagnostics by mapping existing
   capability records/unsupported capability codes into warning or failure
   records.
5. Add focused tests for serialization, CLI output, no-mutation guarantees,
   unsupported schema/missing authority handling, materialization warnings,
   capability assumptions, and import boundaries.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import.py`,
  `tests/package/test_import_boundaries.py`,
  `tests/package/test_pipeline_store_api.py`, and any exact package API tests
  touched by new diagnostics exports.
- Required assertions or deferral reason: importing public packages remains
  cheap; CLI import boundaries do not pull project code through diagnostics;
  store root imports still avoid `sqlite3` unless an existing approved boundary
  explicitly imports the SQLite implementation lazily.

### Unit Suite

- Status: required.
- Expected paths: new or updated
  `tests/unit/loom/diagnostics/test_backend_diagnostics.py`,
  `tests/unit/loom/cli/test_backend.py`,
  `tests/unit/loom/cli/test_main.py`, and formatter tests if text formatting
  is extended.
- Required assertions or deferral reason: diagnostic model validation and
  serialization; capability warning/error mapping; schema diagnostics;
  submitted-operation, attempt, lease, commit, revision, cleanup, and recovery
  summary extraction; materialization warning mapping; projection revision
  handling; read-only guard behavior using a spy/fake store that fails on
  mutating method calls; parser registration and JSON/text command output.

### Contract Suite

- Status: required.
- Expected paths: new or updated contract tests such as
  `tests/contracts/test_backend_diagnostics_contract.py`, plus existing
  authority/read-model contract tests when helper behavior changes.
- Required assertions or deferral reason: diagnostics consume only
  `PerRunAuthorityStore` and read-model contract methods; fake/in-memory and
  SQLite-backed authorities produce equivalent diagnostic shapes for schema,
  capabilities, revisions, attempts, leases, submitted operations, commits,
  artifact facts, cleanup candidates, recovery candidates, and warnings.

### Integration Suite

- Status: required.
- Expected paths: new or updated
  `tests/integration/pipeline/test_backend_diagnostics.py`,
  `tests/integration/pipeline/test_materialization_read_models.py` if read
  options change, and existing SQLite serial execution fixtures for realistic
  authoritative runs.
- Required assertions or deferral reason: CLI/API diagnostics over synthetic
  SQLite-backed runs with committed outputs, submitted operations, missing or
  corrupt materialized refs, stale projection evidence, unsupported schema,
  missing authority, active-run revision changes, and explicit shared/remote
  requirement failures; before/after backend revision and fact counts prove no
  mutation.

### E2E Suite

- Status: required.
- Expected paths: new `tests/e2e/test_cli_backend.py` or additions to
  `tests/e2e/test_cli_core.py`.
- Required assertions or deferral reason: smoke `loom backend inspect` and
  `loom backend capabilities` through `main(argv)` for text and JSON against a
  deterministic local run; assert the commands produce stable envelopes and do
  not require network, SLURM, project stage imports beyond trusted test config
  construction, or non-local services.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: Phase 6 diagnostics should be
  deterministic in package/unit/contract/integration/e2e suites. No network,
  real SLURM, remote store, stress, or timing-sensitive opt-in suite is
  required.

## Risks

- The CLI could accidentally imply a supported SQL/schema contract if it
  exposes SQLite paths, table names, or raw rows.
- Diagnostics could become mutation-adjacent if capability or recovery
  warnings suggest repair behavior without safe semantics.
- Materialization verification could accidentally read artifact payloads or
  import project code instead of checking metadata and local file properties.
- Text output could hide machine-readable warnings that JSON exposes, making
  shared-filesystem or remote limitations less loud.
- Projection freshness diagnostics could become confusing if they are mixed
  with catalog rebuild behavior; keep them read-only.
- No-mutation tests could be too weak if they only assert CLI exit codes; they
  should compare backend revision/fact evidence or use mutating-method spies.
- Record-heavy runs could pressure text output. Keep summaries compact and add
  targeted selectors before considering broad output-shaping features.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py
uv run pytest tests/unit/loom/diagnostics/test_backend_diagnostics.py tests/unit/loom/cli/test_backend.py tests/unit/loom/cli/test_main.py
uv run pytest tests/contracts/test_backend_diagnostics_contract.py tests/contracts/test_authority_store_contract.py
uv run pytest tests/integration/pipeline/test_backend_diagnostics.py tests/integration/pipeline/test_materialization_read_models.py
uv run pytest tests/e2e/test_cli_backend.py
make test-package
make test-unit
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: diagnostics result models/helpers first; CLI
  registration and formatting second; capability/materialization/projection
  options third; tests by suite as each behavior lands.
- Tests to run with each slice: model/unit tests after diagnostics helpers;
  parser/CLI unit tests after command registration; contract and SQLite
  integration tests after backend read wiring; e2e smoke after CLI behavior is
  stable.
- Decisions the executor must not revisit: `loom backend` remains read-only;
  CLI/diagnostics do not query SQLite tables; missing authority does not fall
  back to legacy files; materialization diagnostics do not load payloads or
  import project code; no repair/export/SQL/snapshot command is added.
- Conditions that require stopping for the manager: a required diagnostic
  needs a mutating backend method; direct SQLite table access seems necessary
  outside `sqlite_authority.py`; existing contracts cannot expose required
  read facts without broad public API changes; shared-filesystem or remote
  assumptions would need a new backend implementation; validation requires
  network, real SLURM, or non-local services.
- Expanded-path refinement notes: command grammar is intentionally small;
  default diagnostics are warning-preserving successes, explicit unsupported
  assumptions are failures, projection evidence is read-only input, recovery
  and cleanup records are report-only, and no-mutation tests must use backend
  revision/fact comparisons or mutating-method spies rather than CLI exit
  status alone.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-10 by
  `loom_phase_refiner`; bounded implementation/test refinement completed.
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this artifact.
- Final phase execution plan: completed by expanded-path refinement in this
  artifact.
- Implementation summary: added read-only `loom backend inspect` and
  `loom backend capabilities` commands plus backend-neutral diagnostics API
  helpers under `loom.diagnostics`; CLI presentation stays out of SQLite
  internals, exposes schema/revision/lifecycle/capability/materialization
  diagnostics in text and JSON, preserves missing-authority loud failures, and
  keeps recovery and cleanup records report-only.
- Implementation validation: executor-reported validation after commit
  `0c1938a` passed `make validate-pr` and `make test-summary`. Refinement
  reran targeted API/CLI tests, phase-scoped package/contract/integration/e2e
  tests, full `make validate-pr`, and refreshed `make test-summary`.
  Refreshed summary: package 57 passed, 1 skipped; unit 818 passed, 1 skipped;
  contract 93 passed, 2 skipped; integration 74 passed, 8 skipped,
  10 deselected; e2e 38 passed, 1 deselected; config-extra 420 passed,
  1083 deselected.
- Refinement summary: reviewed the Phase 6 implementation against read-only
  semantics, authority/schema failure behavior, capability requirements,
  projection/materialization diagnostics, import boundaries, export surface,
  and suite coverage. Applied one small correction so explicit shared-filesystem
  or remote capability failures preserve diagnostic codes/messages in text-mode
  errors and remote requirements reuse backend capability-record detail; added
  unsupported schema and text-error detail coverage. No mutation paths, direct
  SQLite CLI reads, project-code imports, export/snapshot/repair behavior, or
  future-phase functionality were added.
- Blocker-resolution summary: not used; no blocker-resolution pass consumed.
- PR preparation: prepared `docs/phases/backend-diagnostics-pr-body.md` with a
  concise review-facing summary, implementation notes, suite-level validation
  evidence, and risks/follow-ups. Final validation evidence used for PR
  preparation: `make validate-pr` passed after commit `d94789c` with Ruff,
  Pyright, default harness, config-extra harness, and build passing;
  `make test-summary` passed and generated `build/test-summary.md` at
  2026-05-09T21:41:12+00:00 with package 57 passed, 1 skipped; unit 818
  passed, 1 skipped; contract 93 passed, 2 skipped; integration 74 passed, 8
  skipped, 10 deselected; e2e 38 passed, 1 deselected; config-extra 420
  passed, 1083 deselected; overall 1500 passed, 12 skipped, 1094 deselected,
  0 failed, and 0 errors.
- PR opening: branch `codex/backend-diagnostics` pushed to `origin`; PR #106
  opened at https://github.com/samcantrill/loom/pull/106 with base `develop`,
  head `codex/backend-diagnostics`, and state `OPEN`. Immediate verification
  used `gh pr view 106 --json baseRefName,headRefName,state,url` and confirmed
  `baseRefName=develop`, `headRefName=codex/backend-diagnostics`,
  `state=OPEN`.
- Stack maintenance: none required; root branch still targets `develop`.
- Remaining blockers: none known.
