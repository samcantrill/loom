# Phase 3 Execution Plan: Status And Logs Inspection

## Metadata

- Status: refined phase execution plan
- Feature focus: `Local Diagnostics`
- PR title: `Local Diagnostics - Phase 3: Status and Logs Inspection`
- Branch: `codex/add-status-logs-diagnostics`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-status-logs-diagnostics`
- Phase execution plan path: `docs/phases/add-status-logs-diagnostics.md`
- Full plan: `docs/implementation-plans/implementation-plan-v3.md`
- Source phase: Phase 3 - Status And Logs Inspection
- Stack predecessor: none
- Base branch: `develop` at `3856cae docs: record v3 phase 2 merge`
- Target branch: `develop`
- Merge eligibility: root phase PR, merge-eligible only when it targets
  `develop` and validation, review, and CI gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 4 depends on the status/logs command surface
  after this phase is merged; no successor branch exists at planning time.
- Plan quality gate: passed on 2026-05-07 by `loom_plan_reviewer`
  confirmation review
- Plan quality gate loop budget: initial review used, plan refinement used,
  confirmation review used
- Draft pass: completed by managing agent on 2026-05-07
- Refine pass: completed by managing agent on 2026-05-07; concrete store
  facade names, log path/content behavior, missing-stage handling, and suite
  obligations were checked before implementation
- Setup limitations: none known
- Blockers: none known

## Objective

Add reusable local run-status and stage-log inspection APIs plus `loom status`
and `loom logs` commands that read persisted local run state without importing
project stage modules or traversing private store paths from diagnostics/CLI
code.

## Full-Plan Context

Phase 1 added local diagnostics models and preflight APIs. Phase 2 exposed
preflight through the CLI and reused minimal preflight in `loom run`. Phase 3
adds post-run inspection: status summaries and bounded logs. Phase 4 remains out
of scope and will add artifact diagnostics and end-to-end workflow evidence.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 1 and Phase 2 are merged into
  `develop`
- Why this base branch is correct: all earlier v3 phases are merged and their
  implementation-plan metadata is on `develop`
- Retarget/rebase plan after predecessor merge: none
- Branch cleanup constraints: delete the branch after squash merge only if no
  successor branch depends on it

## Source Phase Summary

- Goal: let users inspect local run status and stage logs through CLI commands
  backed by reusable diagnostics inspection facades.
- Required scope: a narrow store-owned stage-discovery/run-state facade;
  diagnostics result models/facades for run status, stage status, failures,
  artifact counts, log path hints, provenance availability, and bounded stage
  log content; `loom status RUN_URI`; `loom logs RUN_URI STAGE`.
- Required checkpoints: diagnostics and CLI must use public store inspection
  APIs, not private local path traversal; missing/corrupt run and stage
  documents must produce clear behavior; log display must be bounded.
- Acceptance criteria: successful and failed local runs summarize without
  project imports; status output includes run status, stage table, failures, log
  hints, and artifact counts; logs show resolved stdout/stderr paths and
  bounded content; missing logs/stages fail clearly; JSON uses stable CLI
  envelopes and plain-data diagnostics payloads.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  `LocalRunStore` already exposes typed readers for run documents, run status,
  artifact indexes, events, stage status, stage failure, stage provenance, and
  stage logs. It exposes local path helpers such as `local_stage_log_path()`,
  but there is no stage discovery facade yet.
- Existing tests or harness behavior: store unit tests cover local run
  read/write behavior; CLI integration/e2e tests already create successful and
  failed synthetic local runs; package import-boundary tests guard CLI,
  diagnostics, stores, and project imports.
- Import-boundary or dependency constraints: status/log diagnostics may import
  public store/status/artifact models, but store modules must not import
  diagnostics or CLI. CLI command modules should remain import-light and defer
  store/diagnostics execution imports until handler/helper calls.

## In-Scope Work

- Add narrow read-only store inspection models and protocols, likely under
  `loom.pipeline.stores`, for stage discovery and run-state scanning. Use
  concrete names such as `RunStageInspection`, `RunStateInspection`,
  `list_run_stages()`, and `inspect_run_state()` unless implementation uncovers
  a clearer local pattern.
- Implement the local store facade on `LocalRunStore`, including deterministic
  stage ordering, run existence validation, stage document reads, artifact
  counts, failure/provenance availability, and log path hints.
- Add diagnostics models and facade functions for run status summaries and
  bounded stage log summaries.
- Add `loom status RUN_URI` with `--format text|json`.
- Add `loom logs RUN_URI STAGE` with `--stream stdout|stderr|both`,
  `--tail N`, `--paths`, and `--format text|json`.
- Add text formatting helpers and JSON result-envelope constants for status and
  logs.
- Add package, unit, contract, integration, and e2e coverage for successful
  runs, failed runs, missing runs, missing stages, missing logs, corrupt
  documents where practical, bounded tails, and import boundaries.

## Out-of-Scope Work

- Scheduler/job status, live process state, or queue inspection.
- Live log following or unbounded log output.
- Artifact list/show commands or payload inspection.
- Attempt-aware stage-worker commands.
- Run catalogs, cross-run comparisons, cleanup, or retention policies.
- Remote stores or non-local URI schemes beyond existing validation behavior.
- Persisting new diagnostics documents.

## Assumptions

- Phase 3 targets local persisted run state written by existing v0-v2 execution
  paths.
- Stage discovery can be store-owned and local-store-specific in this phase,
  while exposed through a public store protocol/facade that future store
  implementations can satisfy.
- `loom status` is read-only and may fail if the run has no required run
  metadata.
- `loom logs` defaults to both stdout and stderr, with a bounded tail default of
  100 lines.
- `--tail N` must be a positive integer; invalid values are CLI usage errors.
- `--paths` returns log path availability without content and should succeed for
  known stages even when log files are absent.
- Missing stages and missing log content without `--paths` are operational run
  state errors.
- A known stage is any stage returned by the store-owned stage discovery
  facade, even if one of its optional documents is absent.

## Scope Contract

The store-owned facade must expose stage discovery and a run-state scan without
requiring diagnostics or CLI code to traverse `stages/*` directly. The expected
public surface is additive, read-only, and store-owned, for example:

```text
list_run_stages(run_uri) -> tuple[str, ...]
inspect_run_state(run_uri) -> RunStateInspection
```

or equivalent names/types in `loom.pipeline.stores`. The local implementation
may inspect local directories internally because the store owns that layout.
Diagnostics and CLI code must consume this public facade plus existing public
readers such as `read_stage_log()` and `local_stage_log_path()`.

The preferred concrete store model shape is:

```text
RunStageInspection(
    stage_name,
    status,
    failure,
    input_count,
    output_count,
    provenance_available,
    stdout_path,
    stderr_path,
    stdout_available,
    stderr_available,
)

RunStateInspection(
    run_uri,
    run_status,
    stage_inspections,
    artifact_count,
)
```

Field names may vary to match local style, but the model must remain plain-data
friendly and read-only. Corrupt required documents should raise existing store
errors; missing optional stage documents should surface as absent fields rather
than hiding the stage.

`loom status RUN_URI` emits a result payload with run URI, run status when
available, stage summaries in deterministic order, artifact count, failure
summary fields, log path hints, and provenance availability. JSON uses a
command-owned schema version and `payload_name="result"`. Text output is compact
and includes the run status plus one line per known stage.

`loom logs RUN_URI STAGE` emits a result payload with run URI, stage name,
selected streams, path strings, existence flags, and bounded content unless
`--paths` is set. Text output prints paths and bounded stream content. Missing
stage errors and missing requested log content without `--paths` use existing
CLI error-envelope behavior and a run-state exit code.

`--stream both` must preserve deterministic stdout-then-stderr ordering. `--tail
N` applies per stream, not across combined streams. `--paths` must not read log
file content.

## Design Impact

- Maintainability: moves local run layout inspection into the store layer and
  keeps diagnostics/CLI consumers on public read APIs.
- Extensibility: run-state and log result models can grow additively for later
  retries, attempts, remote stores, catalogs, or cleanup workflows.
- Domain neutrality: status/log output describes generic pipeline run state and
  stage logs without project-specific stage imports.
- Source-tree boundaries: `loom.pipeline.stores` remains below diagnostics and
  CLI; diagnostics may import public store APIs; CLI may import diagnostics
  helpers lazily from command handlers.

## Future Compatibility

- Keep facade names and payloads generic enough for future remote store or
  catalog-backed implementations.
- Keep log summaries attempt-agnostic in Phase 3 but leave space for attempt
  fields once stage-worker attempts exist.
- Keep status summaries additive so Phase 4 artifact metadata can link to them
  without changing Phase 3 JSON contracts.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Let `loom status` glob local `stages/*` directly. | It would leak local-store layout into CLI and block future store implementations. |
| Put stage discovery in `loom.diagnostics` by reading store paths. | Store layout ownership belongs to `loom.pipeline.stores`; diagnostics should orchestrate public APIs. |
| Add `--follow` for logs now. | V3 has no subprocess/scheduler live-log contract, and unbounded output is out of scope. |
| Combine status/logs/artifacts into one broad command PR. | Phase 4 owns artifact inspection and full workflow evidence; Phase 3 should remain reviewable. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Log display is bounded and attempt-agnostic. | Existing execution does not expose stage-worker attempts or live log streams. | Revisit when retry/attempt-aware execution lands. |
| Status summaries are local persisted-state views, not scheduler state. | V3 targets local debugging over completed or partially written run stores. | Revisit when scheduler or external executor status surfaces exist. |

## Reviewability

- Expected PR size and shape: one store-facade addition, one diagnostics status
  and logs facade, two CLI commands, and focused tests.
- Files and areas to inspect: `src/loom/pipeline/stores/`,
  `src/loom/diagnostics/`, `src/loom/cli/`, store contract tests,
  diagnostics/unit tests, CLI unit tests, integration fixtures, and e2e CLI
  tests.
- Scope-control checks: confirm no artifact commands, no live following, no
  scheduler state, no direct diagnostics/CLI globbing of private stage paths,
  no project stage imports, and no persisted diagnostics documents.

## Implementation Steps

1. Add store-owned inspection models/protocols and implement deterministic
   stage discovery/run-state scanning in `LocalRunStore`.
2. Add diagnostics status/log models and facade functions that consume the
   store inspection API and existing public log readers/path helpers.
3. Add CLI options, handlers, text formatting, JSON envelopes, and error mapping
   for `loom status` and `loom logs`.
4. Add package, unit, contract, and integration tests for store inspection,
   diagnostics summaries, CLI formatting/options, missing/corrupt state, and
   bounded log tails.
5. Add e2e coverage over synthetic successful and failed local runs, then run
   final validation and update phase/PR artifacts.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`,
  `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: CLI status/log command modules remain
  import-light; store modules do not import diagnostics or CLI; diagnostics root
  remains lightweight.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_local_runs.py`,
  `tests/unit/loom/diagnostics/`, `tests/unit/loom/cli/`
- Required assertions or deferral reason: stage discovery order, run-state
  inspection models, missing/corrupt document behavior, status/log diagnostics
  payload shape, stream selection, tail bounds, `--paths`, text formatting, JSON
  ok/error behavior, and CLI error mapping.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_store_contract.py` and a focused
  diagnostics status/log contract module if needed
- Required assertions or deferral reason: public store inspection facade shape,
  deterministic stage ordering, diagnostics payload fields, and no private path
  traversal from diagnostics.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/diagnostics/` and
  `tests/integration/config/test_cli_run.py` or focused local run fixtures
- Required assertions or deferral reason: successful run status, failed run
  status/failure/log hints, missing run, missing stage, missing log, corrupt
  stage status, bounded stdout/stderr content, and path-only log output.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_core.py` or focused diagnostics e2e module
- Required assertions or deferral reason: `loom status` and `loom logs` through
  `main(argv)` over synthetic successful and failed local runs.

### Opt-In Suites

- Status: deferred
- Markers affected: `optional_dependency` for config-backed local run fixtures
- Required assertions or deferral reason: no external service, scheduler,
  container, plugin, network, or remote-store behavior is introduced.

## Risks

- Stage discovery can accidentally leak local path layout above the store layer.
- Corrupt partial run state can make status unusable unless diagnostics surfaces
  clear store errors.
- Log commands can accidentally print unbounded content or ambiguous mixed
  streams.
- Import-light CLI help can regress if status/log command modules import stores
  or diagnostics execution eagerly.
- Status summaries may grow too broad and drift into Phase 4 artifact
  inspection.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py -m package
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py tests/unit/loom/diagnostics tests/unit/loom/cli
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_store_contract.py
UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/diagnostics tests/e2e/test_cli_core.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: store inspection facade first; diagnostics status
  and logs facades second; CLI commands third; tests and docs evidence last.
- Tests to run with each slice: store unit/contract tests after facade work;
  diagnostics unit tests after models/facades; CLI unit tests after command
  handlers; config-backed integration/e2e after commands work.
- Decisions the executor must not revisit: no artifact commands, no live
  following, no scheduler state, no direct private path traversal outside the
  store layer, default log tail is 100 lines, and `--paths` suppresses content.
- Conditions that require stopping for the manager: status/log summaries need a
  broad persistence schema migration, corrupt document handling requires
  changing existing store error contracts, or implementing logs requires
  future attempt/live-follow semantics.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-07 by managing agent after
  full validation exposed public export contract expectations for the new store
  inspection API; the contract tests were updated and validation passed.
- PR review: used on 2026-05-07 by managing agent; no blocking findings.
- Blocker resolution: not used; no Phase 3 blocker-resolution pass has been
  authorized

## Completion Notes

- Draft plan: completed on 2026-05-07 by managing agent; committed as
  `plan: add phase 3 execution plan`.
- Final phase execution plan: refined on 2026-05-07 by managing agent; store
  facade names, plain-data inspection shape, missing optional documents,
  missing-stage behavior, and bounded log semantics were made
  implementation-ready.
- Implementation summary: completed Phase 3 status/log inspection. Added
  read-only store inspection models and `LocalRunStore` stage discovery/run-state
  scanning, diagnostics status/log summary facades, `loom status`, `loom logs`,
  bounded tail handling, path-only log mode, text formatting, and JSON result
  envelopes.
- Implementation validation: targeted package, unit, contract, integration,
  e2e, Ruff, and Pyright checks passed. Final `UV_CACHE_DIR=/tmp/uv-cache make
  validate-pr` passed with Ruff clean, Pyright 0 errors, default isolated suite
  542 passed/13 skipped/9 deselected, config-extra 393 passed/557 deselected,
  and build artifacts produced. Final `UV_CACHE_DIR=/tmp/uv-cache make
  test-summary` passed with package 48 passed/1 skipped, unit 445 passed/1
  skipped, contract 40 passed/2 skipped, integration 9 passed/6 skipped/9
  deselected, e2e 15 passed, and config-extra 393 passed/557 deselected.
- Refinement summary: expanded-path implementation refinement completed on
  2026-05-07. Full validation found store public-export expectation updates
  needed for `RunInspectionStore`, `RunStageInspection`, and
  `RunStateInspection`; tests were updated, and final validation passed.
- Blocker-resolution summary:
- PR preparation: complete on 2026-05-07 by managing agent. PR body drafted at
  `docs/phases/add-status-logs-diagnostics-pr-body.md`; PR opened as
  https://github.com/samcantrill/loom/pull/68 and verified with
  `baseRefName=develop`, `headRefName=codex/add-status-logs-diagnostics`, and
  `state=OPEN`.
- Stack maintenance: root phase; no predecessor maintenance pending. PR #68 is
  merge-eligible only after review and CI pass while targeting `develop`.
- Remaining blockers: none known.
