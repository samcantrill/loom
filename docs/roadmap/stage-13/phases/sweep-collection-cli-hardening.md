# Phase 5 Execution Plan: Collection, CLI, Docs, And Hardening

## Metadata

- Status: pr_open
- Feature focus: Deterministic Sweeps
- PR title:
  `Deterministic Sweeps - Phase 5: Collection, CLI, Docs, And Hardening`
- Branch: `codex/sweep-collection-cli-hardening`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/sweep-collection-cli-hardening`
- Phase execution plan path:
  `docs/roadmap/stage-13/phases/sweep-collection-cli-hardening.md`
- Full plan: `docs/roadmap/stage-13/implementation-plan.md`
- Source phase: Phase 5, `sweep-collection-cli-hardening`
- Stack predecessor: none; Phases 1 through 4 are merged into `develop`.
- Base branch: `origin/develop` at
  `959201973861353d016a6818b45f429d941483e4`
- Target branch: `develop`
- PR: [#155](https://github.com/samcantrill/loom/pull/155)
- Merge eligibility: root phase PR targets `develop`; merge-eligible only after
  implementation, validation, automated review, CI or justified unavailable
  checks, and target-branch verification pass.
- Workflow path: expanded path
- Successor dependency notes: this is the final Stage 13 phase; no successor
  phase branch should depend on it.
- Plan quality gate: passed in the implementation plan on 2026-05-14.
- Plan quality gate loop budget: implementation-plan review, refinement, and
  confirmation were used before Phase 1; no blocking findings remain.
- Draft pass: complete for this phase execution plan.
- Refine pass: complete for this expanded-path phase; the artifact is final for
  implementation.
- Setup limitations: the original control checkout has unrelated dirty and
  untracked files; phase work is isolated in the worktree above.
- Blockers: none.

## Objective

Complete the user-facing deterministic sweep surface by adding metadata-first
collection APIs, exposing existing unsupported extraction diagnostics through
collection, wiring `loom sweep plan/run/status/collect` as thin CLI wrappers,
and documenting the supported v13 workflow without adding metric parsing,
artifact payload loading, rerun policy, or scheduler/controller behavior.

## Full-Plan Context

Phases 1 and 2 established provider contracts, deterministic grid/manual
planning, trial manifests, and stable run URI mapping. Phase 3 added cooperative
early stop and direct sequential dispatch. Phase 4 added coordination
projection, queue submission, and status aggregation. Phase 5 is the final
integration layer: public collection records, CLI command registration,
text/JSON presentation, docs, and import-boundary hardening.

Future roadmap work remains out of scope: concrete extraction adapters,
optimizer providers, adaptive control loops, retry/rerun/filter commands,
sweep-specific bundle/export formats, scheduled-trial cancellation, and
scheduler-specific per-trial policy.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 4 PR
  [#154](https://github.com/samcantrill/loom/pull/154) was squash-merged into
  `develop` and recorded by `9592019`.
- Why this base branch is correct: Phase 5 depends on all v13 sweep planning,
  dispatch, status, queue, coordination, and merge metadata now present on
  `develop`.
- Retarget/rebase plan after predecessor merge: none for this root phase.
- Branch cleanup constraints: the phase branch can be deleted after merge
  because no later Stage 13 phase depends on it.

## Source Phase Summary

- Goal: implement collection models/API, unsupported extraction request
  handling, `loom sweep` CLI commands, docs, and final validation hardening.
- Required scope: metadata/artifact-ref collection, text/JSON command output,
  CLI exit-code behavior, docs/examples, v12 ordinary-run compatibility check,
  and package/import-boundary coverage.
- Required checkpoints: collection reads trial facts and run/artifact metadata
  without loading payloads; CLI calls public sweep APIs; extraction remains
  explicit unsupported diagnostics; docs cover supported behavior and
  deferrals.
- Acceptance criteria: focused unit, contract, integration/e2e, package, and
  docs evidence proves users can plan, run or enqueue, inspect status, and
  collect metadata/artifact refs without domain metric semantics.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/pipeline/sweep/runner.py` owns `plan_sweep_from_file`,
    `write_sweep_plan`, `read_sweep_plan`, and manifest compatibility checks.
  - `src/loom/pipeline/sweep/dispatch.py` owns direct and queue dispatch entry
    points and trial run request construction.
  - `src/loom/pipeline/sweep/status.py` already builds read-only summaries
    from a `SweepPlan` plus supplied run, queue, and coordination snapshots.
  - `src/loom/pipeline/sweep/extraction.py` already owns unsupported
    extraction request/result diagnostics and should be reused, not redesigned.
  - `src/loom/cli/main.py` registers CLI modules through import-light command
    files; existing command modules own output schemas and wrap errors with
    `CliError`.
  - `src/loom/cli/formatting.py` owns text formatting helpers and JSON envelope
    formatting.
  - `loom.diagnostics.inspection.inspect_run_status` and
    `inspect_run_artifacts` expose run status and artifact refs without payload
    loading, using local stores or authoritative facts when available.
- Existing tests or harness behavior:
  - Sweep unit/contract tests cover planning, manifests, dispatch, extraction,
    status, queue, and coordination surfaces.
  - CLI unit/integration tests use `loom.cli.main.main(...)` with captured
    stdout/stderr and JSON envelope assertions.
  - Package tests already check `loom.pipeline.sweep` and CLI import
    boundaries.
- Import-boundary or dependency constraints:
  - `loom.pipeline.sweep` must remain domain-neutral and dependency-light.
  - CLI can import sweep APIs lazily inside handlers where that follows
    existing CLI patterns.
  - No optional optimizer, config-extra-only, artifact payload, or project-code
    imports may be required for collection or CLI import.

## In-Scope Work

- Add `src/loom/pipeline/sweep/collection.py` with versioned collection records
  for sweep summaries, per-trial facts, statuses, artifact refs, and extraction
  diagnostics.
- Add collection helpers that consume a `SweepPlan` plus optional run status
  reader and artifact reader callables. Default behavior may read existing run
  status/artifact metadata through diagnostics/local store helpers from CLI
  outer layers, but the core API must also support injected readers for tests
  and future backends.
- Reuse `SweepExtractionRequest`, `SweepExtractionResult`, and
  `unsupported_extraction(...)` to represent requested extraction without
  implementing payload extraction.
- Export collection records/helpers through `loom.pipeline.sweep`.
- Add `src/loom/cli/sweep.py` and register it in `src/loom/cli/main.py`.
- Implement `loom sweep plan`, `loom sweep run`, `loom sweep status`, and
  `loom sweep collect` with text and JSON output. The CLI must delegate to
  public sweep APIs and avoid duplicating manifest parsing, dispatch, status,
  or collection business logic.
- Use this initial CLI contract: `loom sweep plan SPEC --sweep-dir DIR`,
  `loom sweep run SPEC --config CONFIG --sweep-dir DIR [--queue-config CONFIG]`,
  `loom sweep status DIR [--queue-config CONFIG]`, and `loom sweep collect DIR
  [--include-unsupported-extraction]`. The `--config` argument is required for
  run/queue submission because sweep specs intentionally only describe trial
  overrides and identities, not the base pipeline.
- Add docs and examples for grid/manual specs, planning, direct run, queue
  submit, status outcomes, collection, early stop, unsupported extraction, and
  deferred roadmap behavior.
- Add final package/import-boundary hardening for sweep CLI and optional
  dependency behavior.

## Out-of-Scope Work

- Concrete metric, payload, dataframe, or artifact materialization extraction.
- New optimizer providers or plugin discovery.
- Retry, rerun, filter, or failed-only CLI commands.
- Queue draining, queue controller loops, cancellation policy, or SLURM
  per-trial submission.
- New run bundle/export formats or sweep-specific exchange files.
- Changes to core run/stage lifecycle status enums.

## Assumptions

- CLI commands can require an explicit sweep directory for status/collect and
  can create or reuse that directory for plan/run.
- `loom sweep run` may default to direct sequential dispatch and provide a
  queue submission mode that expects an existing queue service path/config
  rather than starting or draining a controller.
- The collection API can treat missing run status or artifacts as explicit
  per-trial diagnostics instead of failing the whole collection.
- V12 compatibility remains ordinary-run compatibility in this phase; no
  landed v12 API requires a sweep-specific export surface.

## Scope Contract

- Collection records must be versioned, plain-data-compatible, and serialize
  without artifact payload bytes.
- Collection must report trial facts, overrides, status summaries, artifact
  refs/metadata, and unsupported extraction diagnostics; it must not parse
  project metrics or impose objective semantics.
- CLI text output is presentation only. JSON output must expose structured
  result payloads using existing CLI envelope conventions.
- CLI error behavior must use existing `CliError`/`ExitCode` patterns for
  validation, run failures, unsupported extraction, and unavailable run state.
- Queue CLI behavior must be submit-only: `--queue-config` may start the queue
  service long enough to enqueue items through existing queue APIs, but it must
  not drain, cancel, or poll workers.
- Status and collection must treat run lifecycle/read-model state as truth and
  avoid mutating run stores, queue services, or coordination stores.

## Design Impact

- Maintainability: public collection logic lives in sweep core, while CLI code
  stays a thin adapter over public planning, dispatch, status, and collection
  APIs.
- Extensibility: unsupported extraction diagnostics leave a stable attachment
  point for later artifact/materialization work without committing to payload
  semantics now.
- Domain neutrality: collection only carries generic trial, lifecycle, override,
  and artifact-reference facts.
- Source-tree boundaries: config composition, run lifecycle truth, queue
  scheduling, artifact payload loading, and CLI presentation remain in their
  owning modules.

## Future Compatibility

- Future v14 provider plugins can reuse the same CLI and collection surfaces
  because collection depends on manifests and provider metadata, not
  grid/manual internals.
- Future v15/v16 artifact materialization can add concrete extraction adapters
  behind the existing request/result diagnostics.
- Future v19 retry/rerun policy can observe collected trial facts without this
  phase claiming retry behavior.
- Future bundle/export tooling can inspect ordinary trial runs because this
  phase does not introduce a sweep-specific exchange format.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Put collection logic only in `loom.cli.sweep` | The implementation plan requires public Python APIs and thin CLI wrappers. |
| Load artifact payloads during collection | v13 collection is metadata-first; payload/materialization belongs to later roadmap stages. |
| Add metric/objective fields to collection records | Loom remains domain-neutral and must not parse project metrics in sweep core. |
| Make `loom sweep run --queue` start or drain a controller | Queue service/controller ownership remains outside sweep dispatch. |
| Add sweep-specific bundle/export commands | v12 compatibility is ordinary-run compatibility, not a new sweep exchange format. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Default extraction remains unsupported | Concrete extraction semantics are explicitly deferred, but users need machine-readable diagnostics now | A later artifact/materialization stage chooses concrete safe extraction behavior |
| CLI queue mode may require an existing queue service instead of managing one | Phase 4 kept queue dispatch enqueue-only and Phase 5 must not become a controller | Users need managed sweep queue lifecycle or distributed controller behavior |
| Collection readers are adapter-shaped callables rather than a new store protocol | Keeps the final v13 phase small and backend-neutral while existing diagnostics APIs remain usable | Multiple backends need richer collection read contracts or performance-sensitive batched reads |

## Reviewability

- Expected PR size and shape: medium-to-large final integration PR with one new
  collection module, one CLI module, formatting additions, docs, and focused
  tests.
- Files and areas to inspect:
  - `src/loom/pipeline/sweep/collection.py`
  - `src/loom/pipeline/sweep/extraction.py`
  - `src/loom/pipeline/sweep/status.py`
  - `src/loom/pipeline/sweep/__init__.py`
  - `src/loom/cli/sweep.py`
  - `src/loom/cli/main.py`
  - `src/loom/cli/formatting.py`
  - `docs/features/sweeps.md`
  - sweep, CLI, integration, e2e, and package tests
- Scope-control checks:
  - no metric parsing or artifact payload loading;
  - no queue draining/controller behavior;
  - no concrete optimizer provider;
  - no sweep-specific bundle/export behavior;
  - CLI handlers call public sweep APIs instead of reimplementing core logic.

## Implementation Steps

1. Implement collection records and injected-reader collection API, reusing
   status and unsupported extraction records.
2. Add collection/extraction contract and unit coverage, then export public
   collection APIs.
3. Add `loom sweep` CLI registration and handlers for plan, run, status, and
   collect with text/JSON formatting.
4. Add CLI/integration/e2e tests for synthetic plan/run/status/collect and
   queue submit/status behavior where practical.
5. Update sweep docs/examples and final import-boundary/package tests.
6. Run targeted validation, then `make validate-pr` and `make test-summary`.

## Test Plan

### Package Suite

- Status: required
- Expected paths:
  - `tests/package/test_pipeline_api.py`
  - `tests/package/test_import_boundaries.py`
- Required assertions: public sweep exports include collection records/helpers;
  importing sweep and CLI modules does not import optional optimizer,
  payload/materialization, or scheduler-heavy layers.

### Unit Suite

- Status: required
- Expected paths:
  - `tests/unit/loom/pipeline/sweep/test_collection.py`
  - `tests/unit/loom/pipeline/sweep/test_status.py`
  - `tests/unit/loom/cli/test_sweep.py`
  - `tests/unit/loom/cli/test_main.py`
- Required assertions: collection records round-trip to plain data, missing run
  state becomes diagnostics, artifact refs are reported without payloads,
  unsupported extraction is included on request, CLI parsing/handlers produce
  text and JSON output with correct exit codes.

### Contract Suite

- Status: required
- Expected paths:
  - `tests/contracts/test_sweep_collection_contract.py`
  - `tests/contracts/test_sweep_extraction_contract.py`
- Required assertions: collection payload schema is stable, unsupported
  extraction diagnostics remain machine-readable, no metric/objective fields
  are required.

### Integration Suite

- Status: required
- Expected paths:
  - `tests/integration/pipeline/sweep/test_collection_cli_integration.py`
  - `tests/integration/pipeline/sweep/test_direct_dispatch_integration.py`
- Required assertions: synthetic sweep plan/run/status/collect works with
  ordinary local run state and artifact refs; queue submission path reports
  submitted trials without draining the queue.

### E2E Suite

- Status: required
- Expected paths:
  - `tests/e2e/test_sweep_cli.py`
- Required assertions: `loom sweep plan`, `loom sweep status`, and
  `loom sweep collect` provide stable text/JSON output for a small synthetic
  sweep; direct run happy path is covered where practical.

### Opt-In Suites

- Status: deferred
- Markers affected: real SLURM and network/remote-service acceptance suites
- Required assertions or deferral reason: Phase 5 does not introduce real
  scheduler, remote service, or network behavior.

## Risks

- CLI command scope could expand into retry/rerun/filter behavior.
- Collection could accidentally privilege one backend or become a second source
  of lifecycle truth.
- Artifact collection could drift into payload loading or metric semantics.
- Queue mode could become controller-like if command ergonomics are not kept
  submit-only.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/sweep tests/contracts/test_sweep_collection_contract.py tests/contracts/test_sweep_extraction_contract.py tests/integration/pipeline/sweep tests/package/test_pipeline_api.py tests/package/test_import_boundaries.py::test_import_sweep_contract_package_is_lightweight
uv run pytest tests/unit/loom/cli/test_sweep.py tests/unit/loom/cli/test_main.py tests/e2e/test_sweep_cli.py
uv run ruff check src/loom/pipeline/sweep src/loom/cli/sweep.py tests/unit/loom/pipeline/sweep tests/unit/loom/cli/test_sweep.py tests/contracts/test_sweep_collection_contract.py tests/integration/pipeline/sweep tests/e2e/test_sweep_cli.py
uv run --extra config pyright
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For Implementation

- Safe implementation slices: collection records/API first, exports/contracts
  second, CLI plan/run/status/collect third, docs/import-boundary hardening
  last.
- Tests to run with each slice: collection unit/contracts after API work; CLI
  unit tests after parser/handler work; integration/e2e after CLI and docs
  examples stabilize.
- Decisions not to revisit: no metric parsing, no payload extraction, no queue
  draining, no retry/rerun/filter commands, no sweep-specific export format.
- Conditions that require stopping for the manager: CLI cannot invoke public
  sweep APIs without duplicating business logic; collection requires artifact
  payload loading or project-code imports for baseline behavior; queue enqueue
  cannot be exposed without starting or controlling a queue service.

## Refinement And Review Budget Status

- Phase implementation refinement: unused; not needed after targeted and full
  validation passed without requiring a separate refiner pass.
- PR review: used by manager-local automated review on 2026-05-14; the review
  found one malformed artifact metadata diagnostic edge case, fixed before
  merge.
- Blocker resolution: 1/3 used for the malformed artifact metadata diagnostic
  fix.

## Completion Notes

- Draft plan: completed locally on 2026-05-14.
- Final phase execution plan: completed locally on 2026-05-14 after refining
  the CLI argument contract and queue submit-only scope.
- Implementation summary: added versioned metadata-first sweep collection
  records and injected-reader collection helpers; exported collection from
  `loom.pipeline.sweep`; added `loom sweep plan/run/status/collect` as thin
  wrappers over public sweep APIs; preserved submit-only queue behavior; added
  JSON config/queue fallbacks for dependency-light CLI tests; documented the
  supported v13 workflow and deferred extraction behavior.
- Implementation validation: targeted Ruff and targeted pytest passed for the
  new sweep collection, CLI, integration/e2e, package, and import-boundary
  coverage (`50 passed`). `make validate-pr` passed, including Ruff, Pyright,
  default (`1538 passed, 26 skipped, 18 deselected`) and config-extra
  (`438 passed, 1575 deselected`) harnesses, and package build. `make
  test-summary` passed with package `80 passed, 1 skipped`; unit `1089 passed,
  7 skipped, 1 deselected`; contract `199 passed, 2 skipped`; integration `155
  passed, 8 skipped, 13 deselected`; e2e `43 passed, 2 deselected`;
  config-extra `438 passed, 1575 deselected`.
- Refinement summary: no separate implementation refinement pass was needed;
  manager-local fixes before final validation included type/import and
  dependency-light CLI behavior plus the automated-review malformed artifact
  metadata diagnostic fix.
- Blocker-resolution summary: used 1/3 passes for malformed artifact metadata
  diagnostic handling; the fix converts non-plain artifact payload errors into
  per-trial `artifact_collection_malformed` diagnostics and adds unit coverage.
- PR preparation: complete; PR
  [#155](https://github.com/samcantrill/loom/pull/155) opened from
  `codex/sweep-collection-cli-hardening` to `develop` after verification
  confirmed `baseRefName=develop`, `headRefName=codex/sweep-collection-cli-hardening`,
  and `state=OPEN`.
- Stack maintenance: root phase from updated `develop`; no successor branch is
  expected for Stage 13.
- Remaining blockers: none.
