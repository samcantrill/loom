# Phase 6 Execution Plan: CLI Integration, Docs, And End-To-End Coverage

## Metadata

- Status: implemented; PR pending
- Feature focus: Run Catalog And Comparison
- PR title: `Run Catalog And Comparison - Phase 6: CLI Integration, Docs, And E2E`
- Branch: `codex/run-catalog-cli`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-catalog-cli`
- Phase execution plan path: `docs/phases/run-catalog-cli.md`
- Full plan: `docs/implementation-plans/implementation-plan-v8.md`
- Source phase: Phase 6 - CLI Integration, Docs, And End-To-End Coverage
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- PR: pending
- Merge eligibility: merge-eligible after implementation, automated review, local validation, and GitHub checks because Phases 1 through 5 are merged.
- Workflow path: expanded path because this phase defines user-facing CLI commands, JSON envelopes, and documentation for the completed v8 feature.
- Successor dependency notes: none; this is the final v8 phase.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v8.md` on 2026-05-09; the plan records initial review, refinement, and confirmation review as complete.
- Plan quality gate loop budget: initial review used; gate refinement used; confirmation review used.
- Draft pass: completed by managing agent in this artifact.
- Refine pass: completed in this artifact for the expanded path; no unresolved blockers remain.
- Phase implementation refinement budget: not needed; no refiner pass used because targeted validation, `make validate-pr`, and `make test-summary` passed.
- Phase PR review budget: unused; one automated review remains required before merge.
- Blocker-resolution budget: unused, 0 of 3 scoped passes consumed.
- Setup notes: branch and worktree were created from local `develop` at commit `0251fa7` (`docs: record v8 phase 5 merge`).
- Blockers: none

## Objective

Expose the completed v8 run catalog and metadata comparison APIs through thin `loom runs` CLI commands, add user-facing documentation, and cover the commands with unit, contract, integration, and end-to-end tests over local synthetic run collections.

## Full-Plan Context

Phases 1 through 5 delivered the public `loom.runs` facade and models, direct current scanning, private SQLite rebuild storage, current list/filter behavior, and metadata-only comparison. Phase 6 must not redesign those APIs. It should register CLI presentation wrappers that parse arguments, call `RunCatalog`, format text or JSON, map warnings and catalog errors through existing CLI conventions, and document the resulting command surface.

This is the final v8 phase. No future-phase implementation should be pulled in.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phases 1 through 5 are merged into `develop`
- Why this base branch is correct: `develop` contains the complete Python catalog API needed by the CLI.
- Retarget/rebase plan after predecessor merge: none; PR targets `develop` directly.
- Branch cleanup constraints: branch may be deleted after merge because no successor phase depends on it.

## Source Phase Summary

- Goal: expose catalog indexing, listing/filtering, and metadata comparison through CLI commands and docs.
- Required scope: `loom runs` command group with `index`, `list`, and `diff`; text and JSON output using public API result models; catalog warning and error mapping; v8 filter parsing; user-facing docs; E2E tests over temporary collections.
- Required exclusions: no CLI-specific catalog logic, daemon/watcher commands, export/import bundles, sweep commands, or CLI behavior bypassing `loom.runs`.
- Acceptance criteria:
  - CLI commands call `loom.runs` APIs and do not duplicate scan/filter/diff behavior.
  - Human output is concise and includes warnings.
  - JSON output preserves API result and warning data.
  - CLI errors follow existing formatting and exit-code conventions.
  - Existing validation commands continue to pass.

## Current Source And Harness Findings

- `src/loom/cli/main.py` registers import-light command modules inside `build_parser()`.
- Existing command groups such as `artifacts`, `logs`, `status`, and `cancel` use `argparse`, local `--format text|json`, `format_json_envelope()`, and `CliError` for domain errors.
- `src/loom/cli/formatting.py` owns shared text and JSON formatting helpers.
- `src/loom/cli/results.py` contains generic CLI plain-data conversion and warning payload helpers.
- `RunCatalog.open(path).rebuild()`, `list(filters=...)`, and `compare(left, right)` are the public APIs this phase should call.
- `RunFilterKind` supports exact-match filters for run status, tag, config fingerprint, pipeline fingerprint, git commit, stage status, artifact identity, artifact checksum, executor, and backend.
- Existing tests include CLI parser/unit coverage, JSON envelope assertions, package import-boundary checks, and E2E CLI tests through `main()`.

## In-Scope Work

- Add an import-light `src/loom/cli/runs.py` command group registered by `build_parser()`.
- Add `loom runs index COLLECTION` to call `RunCatalog.open(COLLECTION).rebuild()`.
- Add `loom runs list COLLECTION` to call `RunCatalog.open(COLLECTION).list(filters=...)`.
- Add `loom runs diff COLLECTION LEFT_RUN_URI RIGHT_RUN_URI` to call `RunCatalog.open(COLLECTION).compare(LEFT_RUN_URI, RIGHT_RUN_URI)`.
- Support `--format text|json` and `--traceback` consistently with existing command groups.
- Support exact-match list filter options for every Phase 4 filter kind:
  - `--status STATUS`
  - `--tag KEY=VALUE`
  - `--config-fingerprint VALUE`
  - `--pipeline-fingerprint VALUE`
  - `--commit VALUE`
  - `--stage-status STATUS`
  - `--artifact VALUE`
  - `--artifact-checksum VALUE`
  - `--executor VALUE`
  - `--backend VALUE`
- Preserve catalog warning details in JSON warning envelopes. Text output should include warning counts and machine-readable warning codes/messages.
- Add concise text formatters for index, list, and diff output. Text should be useful for scanning, not a full tabular UI.
- Use stable schema versions for JSON envelopes, expected as `loom.cli.runs.index.v1`, `loom.cli.runs.list.v1`, and `loom.cli.runs.diff.v1`.
- Map `CatalogError` subclasses to `CliError` with `ExitCode.RUN_STATE`.
- Update user-facing docs in `docs/features/run-catalog.md` and `docs/features/cli.md`; update README only if there is an existing catalog command section that should mention the commands.
- Add phase-scoped unit, contract, integration, and E2E tests.

## Out-of-Scope Work

- No catalog scan, filter, sidecar, or comparison logic inside CLI modules.
- No payload diffs, artifact content loading, project-code imports, plugin hooks, or scheduler/domain-specific comparison.
- No top-level `loom diff` alias.
- No non-current read modes, pagination, sorting options, time-range filters, or broad selector language.
- No export/import bundle commands, sweep commands, daemon, filesystem watcher, cleanup, or garbage collection.
- No public SQL or sidecar schema exposure.

## Assumptions

- CLI command spelling for this phase is `loom runs index`, `loom runs list`, and `loom runs diff`.
- `diff` needs an explicit collection path because the public comparison API is collection-scoped and v8 does not define run-uri-to-collection inference.
- `--artifact` maps to `RunFilterKind.ARTIFACT_IDENTITY`.
- `--commit` maps to `RunFilterKind.GIT_COMMIT`.
- Tag filters use `KEY=VALUE`; malformed values are argparse usage errors.
- Text output may be intentionally compact as long as it includes result counts, key identities, and warnings.

## Scope Contract

The CLI is a presentation layer over public `loom.runs` APIs:

- command handlers may parse arguments, construct `RunFilter` instances, call `RunCatalog`, convert catalog warnings to CLI warnings, and format result models;
- command handlers must not read run directories directly, query SQLite directly, interpret artifact payloads, or duplicate comparison semantics;
- JSON output uses the existing CLI envelope with top-level `schema_version`, `ok`, `warnings`, and `result`;
- the JSON `result` payload should be the public API model `to_dict()` output plus small presentation metadata only when needed;
- catalog warnings must remain machine-readable in JSON, including run URI, path, and details when present;
- text output should return success for ordinary warning-bearing catalog results because warnings are part of the API contract;
- catalog errors that prevent a command from producing a result should use existing CLI error formatting and `RUN_STATE` exit code.

## Design Impact

- Maintainability: keeps CLI command modules as thin wrappers and avoids a second implementation of catalog behavior.
- Extensibility: future bundle, sweep, and richer selector commands can reuse the same command group and formatting conventions.
- Domain neutrality: output reports generic Loom metadata, statuses, fingerprints, checksums, and warnings only.
- Source-tree boundaries: CLI may import `loom.runs` inside command handlers, but runtime catalog code does not import CLI modules or project packages.

## Future Compatibility

The command group and JSON envelope versions establish the first CLI contract for v8 catalog output. Future additions should be additive: new filters, fields, sections, or commands may be added without changing existing schema version behavior unexpectedly.

The explicit collection path for `diff` can coexist with future convenience selectors or a top-level alias because it is unambiguous and maps directly to the public API.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Top-level `loom diff LEFT RIGHT` in Phase 6 | The implementation plan calls for grouped `loom runs` wrappers, and collection inference is not defined. |
| CLI-specific scan/filter/diff implementation | Would duplicate public API behavior and risk drift from `loom.runs`. |
| Reusing generic `loom.cli.result.v2` for all catalog JSON | Dedicated schema versions make command output easier to test and evolve. |
| Time-range or sort CLI filters now | The public catalog API only supports Phase 4 exact-match filters in v8. |
| Hiding warning details in JSON | Warnings are part of the v8 API contract and need machine-readable details for automation. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| `runs diff` requires an explicit collection path. | It avoids inventing selector inference in the final v8 phase. | Users need ergonomic diffing from two run paths or URIs without specifying a collection. |
| Text output is compact rather than table-rich. | Keeps Phase 6 focused on API exposure and stable JSON. | Users need richer terminal scanning once command behavior settles. |
| JSON schema versions are command-specific v1 values. | Makes catalog CLI output testable without changing existing generic result schema. | A broader CLI schema versioning policy is adopted. |

## Reviewability

- Expected PR size and shape: one CLI command module, small main/formatting updates, docs, and phase-scoped tests.
- Files and areas to inspect:
  - `src/loom/cli/main.py`
  - new `src/loom/cli/runs.py`
  - `src/loom/cli/formatting.py`
  - `src/loom/cli/results.py` only if warning conversion needs a reusable helper
  - `docs/features/run-catalog.md`
  - `docs/features/cli.md`
  - unit, contract, integration, and E2E tests for `loom runs`
- Scope-control checks: no direct run-directory scanning, no direct SQLite queries, no artifact payload reads, no project imports, no top-level diff alias, no bundle/sweep/export commands, and no changes to catalog semantics.

## Implementation Steps

1. Add the `loom runs` parser group and command handlers with index/list/diff API calls and catalog-error mapping.
2. Add filter parsing and warning conversion helpers with unit tests for argument behavior and malformed tags.
3. Add text and JSON formatting tests for index, list, diff, warnings, and comparison entries.
4. Add integration and E2E tests over temporary local run collections for indexing, listing, filtered listing, and diff.
5. Update run-catalog and CLI feature docs to describe implemented command usage and boundaries.
6. Run focused validation, then final `make validate-pr` and `make test-summary`.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_runs_api.py` if needed
- Required assertions: adding the command module must not make `import loom.runs` or public package imports heavy; CLI command registration remains import-light.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/cli/test_main.py`, new `tests/unit/loom/cli/test_runs.py`, and formatting tests if local convention prefers them.
- Required assertions: parser includes `runs`; missing action is a usage error; handlers call `RunCatalog` APIs; filters map to `RunFilter` kinds; malformed tag filters fail as usage errors; text/JSON helpers preserve warnings.

### Contract Suite

- Status: required
- Expected paths: new `tests/contracts/test_cli_runs_contract.py`
- Required assertions: JSON envelopes for index/list/diff use stable schema versions, include `ok`, `warnings`, and public result payloads, and preserve warning metadata.

### Integration Suite

- Status: required
- Expected paths: new `tests/integration/pipeline/test_cli_runs.py`
- Required assertions: command handlers operate over temporary `LocalRunStore` collections; index writes/rebuilds the catalog; list returns current summaries with exact-match filters; diff returns comparison statuses and warnings through CLI output.

### E2E Suite

- Status: required
- Expected paths: new `tests/e2e/test_cli_runs_e2e.py`
- Required assertions: `main()` or `uv run loom` covers `loom runs index`, `loom runs list`, filtered list, and `loom runs diff` over synthetic run collections with JSON and representative text output.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no network service, real scheduler, optional dependency, or slow external fixture is required.

## Risks

- JSON warning preservation could be lost if raw `CatalogWarning.to_dict()` mappings are passed through existing warning normalization without adapting run URI/path fields.
- Text output can become noisy if it tries to show every comparison entry; keep it concise and prioritize changed/unknown entries.
- CLI filter flags must stay aligned with public `RunFilterKind` names without creating unsupported query semantics.
- E2E fixtures should create valid run metadata through `LocalRunStore` rather than hand-written partial documents except when testing warning propagation.

## Validation Commands

Targeted development commands:

```sh
uv run ruff check src/loom/cli tests/unit/loom/cli tests/contracts/test_cli_runs_contract.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py
uv run pyright src/loom/cli tests/unit/loom/cli tests/contracts/test_cli_runs_contract.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py
uv run pytest tests/unit/loom/cli/test_main.py tests/unit/loom/cli/test_runs.py tests/contracts/test_cli_runs_contract.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: parser/handler skeleton, filters/warnings, formatters, integration/E2E tests, docs.
- Tests to run with each slice: use the targeted development commands above, narrowed to the files touched during the slice.
- Decisions the executor must not revisit: command group is `loom runs`; `diff` takes explicit `COLLECTION LEFT_RUN_URI RIGHT_RUN_URI`; CLI delegates to `RunCatalog`; no direct scanning or direct SQLite.
- Conditions that require stopping for the manager: public API cannot support a required command without changing catalog semantics; JSON warning preservation needs a broad CLI envelope change; validation exposes import-boundary regression that cannot be fixed inside CLI registration.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed
- PR review: unused
- Blocker resolution: 0/3 used

## Implementation And Validation Summary

- Added `src/loom/cli/runs.py` with `loom runs index`, `loom runs list`, and `loom runs diff` commands that delegate to `RunCatalog.rebuild()`, `RunCatalog.list()`, and `RunCatalog.compare()`.
- Registered the `runs` command group in the import-light CLI parser.
- Added exact-match CLI filter parsing for run status, tags, config and pipeline fingerprints, git commit, stage status, artifact identity, artifact checksum, executor, and backend.
- Added text formatters and command-specific JSON envelopes for run catalog index/list/diff output.
- Preserved catalog warning metadata in top-level CLI JSON warnings while leaving public API result payloads intact.
- Updated run-catalog and CLI feature docs for the implemented command surface and boundaries.
- Added unit, contract, integration, e2e, and package import-boundary coverage for the command group.

Focused validation:

- `uv run ruff check src/loom/cli tests/unit/loom/cli tests/contracts/test_cli_runs_contract.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py tests/package/test_import_boundaries.py` passed.
- `uv run pyright src/loom/cli tests/unit/loom/cli tests/contracts/test_cli_runs_contract.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py tests/package/test_import_boundaries.py` passed with 0 errors, 0 warnings, 0 informations.
- `uv run pytest tests/unit/loom/cli/test_main.py tests/unit/loom/cli/test_runs.py tests/contracts/test_cli_runs_contract.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py tests/package/test_import_boundaries.py` passed: 47 passed in 6.54s.

Final PR validation:

- `make validate-pr` passed:
  - Ruff: passed.
  - Pyright with config extra: passed with 0 errors, 0 warnings, 0 informations.
  - Default harness: 969 passed, 17 skipped, 14 deselected in 73.84s.
  - Config-extra harness: 413 passed, 997 deselected in 26.56s.
  - Build: source distribution and wheel built successfully.
- `make test-summary` passed and wrote `build/test-summary.md`.

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 55 | 0 | 0 | 1 | 0 | 7.63s |
| unit | passed | 760 | 0 | 0 | 1 | 0 | 22.68s |
| contract | passed | 78 | 0 | 0 | 2 | 0 | 4.68s |
| integration | passed | 64 | 0 | 0 | 7 | 10 | 78.04s |
| e2e | passed | 37 | 0 | 0 | 0 | 1 | 20.66s |
| config-extra | passed | 413 | 0 | 0 | 0 | 997 | 39.88s |
| Overall | passed | 1407 | 0 | 0 | 11 | 1008 | 173.56s |

## Completion Notes

- Draft plan: completed on 2026-05-09.
- Final phase execution plan: this artifact.
- Implementation summary: completed; see implementation summary above.
- Implementation validation: completed; focused validation, `make validate-pr`, and `make test-summary` passed.
- Refinement summary: not needed.
- Blocker-resolution summary: none
- PR preparation: pending
- Stack maintenance: no predecessor or successor branch
- Remaining blockers: none
