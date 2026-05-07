# Phase 2 Execution Plan: Preflight CLI And Run Reuse

## Metadata

- Status: refined phase execution plan
- Feature focus: `Local Diagnostics`
- PR title: `Local Diagnostics - Phase 2: Preflight CLI and Run Reuse`
- Branch: `codex/add-preflight-cli`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-preflight-cli`
- Phase execution plan path: `docs/phases/add-preflight-cli.md`
- Full plan: `docs/implementation-plans/implementation-plan-v3.md`
- Source phase: Phase 2 - Preflight CLI And Run Reuse
- Stack predecessor: none
- Base branch: `develop` at `ff432fa docs: record v3 phase 1 merge`
- Target branch: `develop`
- Merge eligibility: root phase PR, merge-eligible only when it targets
  `develop` and validation, review, and CI gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 3 depends on Phase 2 CLI behavior after this
  phase is merged; no successor branch exists at planning time.
- Plan quality gate: passed on 2026-05-07 by `loom_plan_reviewer`
  confirmation review
- Plan quality gate loop budget: initial review used, plan refinement used,
  confirmation review used
- Draft pass: completed by managing agent on 2026-05-07
- Refine pass: completed by managing agent on 2026-05-07; clarified `loom run
  --resume` handling, default URI ordering, JSON `ok` semantics, and budget
  accounting before implementation
- Setup limitations: none known
- Blockers: none known

## Objective

Expose the Phase 1 local preflight runner through a thin `loom preflight`
command and reuse the same diagnostics path from `loom run` for a minimal
non-persistent readiness check before execution.

## Full-Plan Context

Phase 1 created the import-light `loom.diagnostics` public API and local
preflight runner. Phase 2 is the user-facing CLI bridge: it formats diagnostics
through existing text and JSON envelope conventions, pins exit-code behavior,
and changes `loom run` default URI allocation so the URI checked by preflight is
the URI passed to execution. Phase 3 and Phase 4 remain out of scope: no
status, log, artifact-inspection, persisted diagnostics report, or full
diagnostic workflow command is added here.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 1 PR #65 and follow-up PR #66
  are merged into `develop`
- Why this base branch is correct: all earlier v3 phases are merged and the
  implementation-plan metadata commit is on `develop`
- Retarget/rebase plan after predecessor merge: none
- Branch cleanup constraints: delete the branch after squash merge only if no
  successor branch depends on it

## Source Phase Summary

- Goal: expose preflight diagnostics through the CLI and reuse a minimal local
  preflight subset before `loom run` execution.
- Required scope: `loom preflight CONFIG`; `--format text|json`; `--strict`;
  optional `--run-uri`; repeatable `--check GROUP`; compact text output; stable
  JSON envelope; `loom run` minimal preflight reuse; deterministic default run
  URI allocation before preflight and execution.
- Required checkpoints: keep CLI code thin, reuse Phase 1 diagnostics rather
  than recomputing checks, do not persist preflight reports, and keep default
  `loom run` preflight path checks aligned with execution.
- Acceptance criteria: explicit local preflight works; strict warnings fail;
  selected groups work and reject unknown groups; omitted `RUN_URI` still runs
  general readiness checks; JSON uses v2 envelope conventions with a stable
  diagnostics payload; run preflight failures or warnings do not create
  run-store records.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/cli/main.py`
  registers command modules and keeps error formatting centralized;
  `src/loom/cli/formatting.py` owns shared text and JSON helpers;
  `src/loom/cli/options.py` owns typed option adapters; `src/loom/cli/run.py`
  currently resolves explicit `--run-uri` early but leaves default URI
  allocation to `PipelineRunner`; `src/loom/diagnostics/` exposes
  `PreflightRequest`, statuses, groups, result models, and `run_preflight()`.
- Existing tests or harness behavior: CLI unit tests patch command helper
  functions directly; config-backed CLI integration tests use
  `pytest.mark.optional_dependency`; e2e CLI tests drive `main(argv)` with
  synthetic YAML configs; package import-boundary tests already guard cheap CLI
  and diagnostics imports.
- Import-boundary or dependency constraints: adding `loom.cli.preflight` to
  `build_parser()` must not make CLI root import the heavy diagnostics runner,
  stores, executors, or project stage modules. The command module may import
  lightweight diagnostics models at module import, but runner execution should
  stay inside handler/helper calls.

## In-Scope Work

- Add a `loom preflight CONFIG` command module and register it with the top-level
  parser.
- Add typed preflight CLI options for `--strict`, `--run-uri`, and repeatable
  `--check GROUP`, reusing existing config and output-format options.
- Format preflight text output with one compact header plus one line per check
  containing status, check ID, and message.
- Emit JSON through `format_json_envelope()` with a preflight schema version and
  the Phase 1 `PreflightResult.to_dict()` payload.
- Map explicit preflight `FAIL` to a nonzero pipeline-style exit; map `WARN` to
  success unless `--strict` is set; treat `SKIP` as success.
- Reject unknown or empty `--check` selections as CLI usage errors that can be
  rendered as JSON when `--format json` is requested.
- Reuse `run_preflight()` from `loom run` for the minimal groups `config`,
  `pipeline`, `run`, and `executor` before fresh execution.
- Allocate an implicit local run URI once in `loom run` before preflight when
  `--run-uri` is omitted, pass that URI into the preflight request, and pass the
  same URI into `RunRequest`.
- Preserve `loom run --resume` behavior by relying on the existing
  `store.open_run()` validation for existing run state instead of applying the
  fresh-run `run_uri.resolve` diagnostics check to a directory that is expected
  to exist.
- Preserve existing `--resume`, explicit URI existence, unsupported executor,
  dry-run, selector, text, and JSON behavior except for the planned default URI
  allocation timing.

## Out-of-Scope Work

- `loom status`, `loom logs`, or `loom artifacts` commands.
- Persisted preflight report files or run-store diagnostics documents.
- External executor, scheduler, plugin, remote store, container, credential, or
  policy checks.
- Runtime/resource profile CLI options.
- Replacing execution-time validation with preflight.
- Adding selector flags to `loom preflight`; selected stages remain `loom plan`
  and `loom run` concerns in this phase.
- Live log/status behavior or artifact payload inspection.

## Assumptions

- `loom preflight` is best-effort and local-only; execution-time validation
  remains authoritative.
- `--check` accepts Phase 1 group names exactly: `config`, `pipeline`,
  `selectors`, `run`, `artifacts`, `codecs`, `executor`, and `filesystem`.
- `groups=None` remains the full default Phase 1 group set for explicit
  preflight; `loom run` intentionally passes its minimal group subset.
- A preflight aggregate status of `FAIL` is an operational pipeline readiness
  failure, not an internal CLI exception.
- A preflight aggregate status of `WARN` is successful unless `--strict` is set.
- An aggregate `SKIP` can only come from selected checks that need omitted
  context, such as run-path groups without `RUN_URI`; this is nonfatal.
- `LocalRunStore.allocate_run_uri()` is non-persistent and safe to call before
  run-store creation.
- The Phase 1 `run_uri.resolve` check is a fresh-run availability check. Resume
  validation is already owned by `LocalRunStore.open_run()` and should not be
  reinterpreted in Phase 2.

## Scope Contract

The public command is:

```text
loom preflight CONFIG [--overlay PATH ...] [--set KEY=VALUE ...]
    [--format text|json] [--strict] [--run-uri RUN_URI] [--check GROUP ...]
```

The command must build a `PreflightRequest` using the current working directory,
config path, overlays, overrides, optional run URI, and selected groups. It must
not expose selector flags in Phase 2. Unknown group names must produce a
`CliError` with `ExitCode.USAGE` and a stable code such as
`cli.preflight.invalid_check_group`; argparse choices should not be the only
validation path because JSON error output must remain available.

The JSON success/failure payload must use `format_json_envelope()` with
`payload_name="result"` and a schema version owned by the preflight command,
such as `loom.cli.preflight.v3`. `ok` is true for `PASS`, `WARN` without
strict, and `SKIP`; false for `FAIL` and strict `WARN`. The payload is the
plain-data diagnostics result with at least `status`, `groups`, and `checks`.
Warnings do not need to be duplicated into top-level CLI warnings in this phase;
the diagnostics checks are the command result.

Text output must include the aggregate status and every check line. It may use a
short prefix such as `OK`, `WARN`, `FAILED`, or `SKIP`, but the per-check lines
must include status, check ID, and message so failures are inspectable without
JSON.

`loom run` must call the diagnostics runner through a helper before
`PipelineRunner.run()`. The minimal group set is `config`, `pipeline`, `run`,
and `executor` for fresh runs. When the user supplies `--run-uri`, existing
explicit URI resolution and existence checks stay authoritative before the
diagnostics helper runs. When the user supplies `--resume`, existing
`store.open_run()` validation stays authoritative and the diagnostics helper
must not run the fresh-run `run` group against a directory that is expected to
exist; it may still run config, pipeline, and executor groups. When the user
omits `--run-uri`, the CLI allocates one URI once using the default
`LocalRunStore`, preflights that URI with the fresh-run minimal groups, and
builds `RunRequest` with the same string. Preflight must not create `run.json`,
status files, plan files, or run directories before execution. Dry-run remains
delegated to `loom plan` and does not run the `loom run` minimal preflight.

## Design Impact

- Maintainability: keeps diagnostics orchestration in `loom.diagnostics` while
  limiting CLI code to option parsing, formatting, and exit-code decisions.
- Extensibility: the command-level group and JSON envelope contracts leave room
  for later diagnostics groups without changing CLI envelope mechanics.
- Domain neutrality: the command reports generic runtime readiness and does not
  add project-specific checks.
- Source-tree boundaries: `loom.cli` may depend on `loom.diagnostics`, but
  diagnostics and lower pipeline/config/store layers must not import CLI code.

## Future Compatibility

- Keep the preflight schema additive so Phase 4 can include end-to-end
  diagnostic workflow evidence without breaking Phase 2 consumers.
- Keep explicit preflight group selection aligned with Phase 1 group names so
  future groups can be added without redesigning option parsing.
- Keep `loom run` preflight minimal so later runtime/resource or remote-store
  checks can be opt-in instead of silently blocking local execution.
- Keep default run URI allocation centralized through `LocalRunStore` so future
  store schemes can extend allocation behavior behind the store facade.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Recompute checks directly in `loom.cli.preflight` and `loom.cli.run`. | This would duplicate Phase 1 diagnostics logic and make later CLI/API behavior drift likely. |
| Use argparse `choices` as the only `--check` validation. | It would reject unknown groups before command-level JSON error formatting can apply. |
| Keep `loom run` default URI allocation inside `PipelineRunner`. | The implementation plan requires preflight path checks and execution to use the same implicit URI. |
| Make omitted `RUN_URI` fatal for explicit preflight. | Phase 1 explicitly supports omitted `RUN_URI` by skipping only run-path-dependent checks. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| `loom run` uses only a minimal preflight subset. | The phase is a local safety screen, not a durable audit or full diagnostic workflow. | Revisit when runtime/resource, remote-store, or policy checks are introduced. |
| Preflight CLI JSON is an output contract, not a persisted report schema. | V3 intentionally avoids diagnostics persistence. | Revisit if catalogs, bundles, dashboards, or audit reports need durable diagnostics records. |
| `loom run` may compose config once for preflight and again for execution. | Sharing composed objects through the diagnostics result would expand the Phase 1 public API and blur diagnostics with execution setup. | Revisit if config composition cost or trusted resolver side effects become a measured problem. |

## Reviewability

- Expected PR size and shape: one CLI command module plus focused updates to
  CLI formatting/options/run orchestration and phase-scoped tests.
- Files and areas to inspect: `src/loom/cli/main.py`,
  `src/loom/cli/preflight.py`, `src/loom/cli/options.py`,
  `src/loom/cli/formatting.py`, `src/loom/cli/run.py`,
  `tests/unit/loom/cli/`, `tests/contracts/`, `tests/integration/diagnostics/`,
  `tests/integration/config/`, `tests/e2e/`, and package import-boundary tests.
- Scope-control checks: confirm no status/log/artifact commands, no persisted
  reports, no external checks, no selector flags on explicit preflight, and no
  lower-layer imports from `loom.cli`.

## Implementation Steps

1. Add preflight CLI option/result formatting helpers and register the
   `preflight` subcommand without importing heavy diagnostics execution at CLI
   root import time.
2. Implement explicit preflight handling: request construction, group
   normalization errors as CLI usage errors, text/JSON output, strict handling,
   and exit-code mapping.
3. Add the `loom run` minimal preflight hook, including single implicit URI
   allocation before preflight and passing that same URI into `RunRequest`.
4. Update unit and contract tests for parser registration, preflight formatting,
   JSON envelope shape, strict/failed/selected-group behavior, and run hook
   ordering.
5. Add config-backed integration and e2e coverage for successful and failing
   preflight plus run preflight failure/no-store-write cases.
6. Update phase completion notes and PR body evidence after validation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`,
  `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: top-level CLI and command parser
  imports remain cheap; registering `loom preflight` does not import the heavy
  diagnostics runner, stores, executors, or project stage modules eagerly; lower
  layers still do not import `loom.cli` or `loom.diagnostics` in the wrong
  direction.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/cli/test_preflight.py`,
  `tests/unit/loom/cli/test_formatting.py`,
  `tests/unit/loom/cli/test_main.py`, and `tests/unit/loom/cli/test_run.py`
- Required assertions or deferral reason: parser includes `preflight`; option
  adapters preserve config/overlay/override/run-uri/check/strict values; text
  formatting includes aggregate status and check lines; JSON uses the stable
  schema; strict warnings fail; failures return the expected exit code; selected
  groups are passed through; unknown groups produce CLI usage errors; `loom run`
  calls minimal preflight before execution and uses one allocated default URI
  for both preflight and `RunRequest`; `loom run --resume` does not apply the
  fresh-run run-path diagnostics check to the existing run directory.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_cli_preflight_contract.py`
- Required assertions or deferral reason: preflight JSON envelope has stable
  top-level fields, schema version, `ok` behavior, and diagnostics payload shape
  compatible with Phase 1 `PreflightResult.to_dict()`.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/diagnostics/test_cli_preflight.py` and
  updates to `tests/integration/config/test_cli_run.py`
- Required assertions or deferral reason: explicit preflight succeeds for a
  synthetic valid config; invalid configs produce structured failed diagnostics;
  `--check` limits checks; `--run-uri` enables run-path checks; omitted
  `RUN_URI` still checks general readiness; strict warning behavior is covered
  by unit tests unless a real warning case exists; `loom run` preflight failure
  exits before creating run-store records; default `loom run` uses the same
  allocated URI in preflight and execution.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_core.py` or a focused new e2e module
- Required assertions or deferral reason: one successful local preflight and one
  failing local preflight through `main(argv)` with real config composition.

### Opt-In Suites

- Status: deferred
- Markers affected: `optional_dependency` for config-backed integration tests
- Required assertions or deferral reason: no external service, scheduler,
  container, plugin, network, or remote-store behavior is introduced; config
  extras are covered by the existing `config-extra` gate rather than a new
  opt-in suite.

## Risks

- CLI registration can accidentally make `loom.cli.main` import heavy
  diagnostics runner dependencies during parser construction.
- Default `loom run` URI allocation can accidentally create run-store records
  before execution if the store API is used incorrectly.
- `loom run` preflight and execution can drift if one path sees an implicit URI
  and the other still sees `None`.
- Resume can regress if the fresh-run preflight path treats an existing run
  directory as a failure before normal resume validation runs.
- Strict warning semantics can become confusing if JSON `ok`, process exit, and
  aggregate diagnostics status disagree.
- Group-selection errors can bypass JSON error formatting if implemented only
  as argparse choices.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py -m package
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/cli/test_preflight.py tests/unit/loom/cli/test_run.py tests/unit/loom/cli/test_main.py tests/unit/loom/cli/test_formatting.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_cli_preflight_contract.py
UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/diagnostics/test_cli_preflight.py tests/integration/config/test_cli_run.py
UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/e2e/test_cli_core.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: command registration and option adapter; explicit
  preflight formatting/exit behavior; run-command minimal preflight hook; tests
  by suite; phase/PR evidence updates.
- Tests to run with each slice: CLI unit tests after command and formatting
  changes; run unit tests after default URI changes; contract tests after JSON
  schema stabilizes; config-backed integration/e2e after command behavior works.
- Decisions the executor must not revisit: no status/log/artifact commands; no
  persisted preflight reports; no external or remote checks; no selector flags
  for explicit preflight; default `loom run` must allocate one implicit URI
  before preflight and reuse it for execution; resume must preserve existing
  `store.open_run()` behavior and not run the fresh-run path-availability check
  against the existing run directory.
- Conditions that require stopping for the manager: the existing diagnostics API
  cannot express the required minimal run checks; default URI preflight would
  require store writes; JSON envelope conventions conflict with diagnostics
  payload shape; or implementation requires changing Phase 3+ scope.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-07 by managing agent for the
  expanded-path implementation review; no code changes were needed.
- PR review: used on 2026-05-07 by managing agent; no blocking findings.
- Blocker resolution: not used; no Phase 2 blocker-resolution pass has been
  authorized

## Completion Notes

- Draft plan: completed on 2026-05-07 by managing agent; committed as
  `plan: add phase 2 execution plan`.
- Final phase execution plan: refined on 2026-05-07 by managing agent; resume
  handling, default URI ordering, diagnostics JSON semantics, and suite
  obligations were made implementation-ready.
- Implementation summary: completed Phase 2 CLI preflight and run reuse. Added
  `loom preflight`, preflight CLI options, compact text formatting, JSON result
  envelopes, strict warning exit behavior, selected-group handling, and
  command-level invalid group errors. Updated `loom run` to allocate an
  implicit local run URI before minimal preflight and pass the same URI into
  execution, while preserving explicit URI and resume behavior.
- Implementation validation: targeted unit, contract, integration, e2e, package,
  Ruff, and Pyright checks passed. Final `UV_CACHE_DIR=/tmp/uv-cache make
  validate-pr` passed with Ruff clean, Pyright 0 errors, default isolated suite
  532 passed/13 skipped/5 deselected, config-extra 389 passed/547 deselected,
  and build artifacts produced. Final `UV_CACHE_DIR=/tmp/uv-cache make
  test-summary` passed with package 47 passed/1 skipped, unit 436 passed/1
  skipped, contract 40 passed/2 skipped, integration 9 passed/6 skipped/5
  deselected, e2e 15 passed, and config-extra 389 passed/547 deselected.
- Refinement summary: expanded-path implementation review completed on
  2026-05-07. Scope, import boundaries, preflight JSON/text behavior,
  run-command URI reuse, resume handling, no-store-write behavior, and suite
  obligations were checked against the phase plan; no blocking defects were
  found.
- Blocker-resolution summary:
- PR preparation: complete on 2026-05-07 by managing agent. PR body drafted at
  `docs/phases/add-preflight-cli-pr-body.md`; PR opened as
  https://github.com/samcantrill/loom/pull/67 and verified with
  `baseRefName=develop`, `headRefName=codex/add-preflight-cli`, and
  `state=OPEN`.
- Stack maintenance: root phase; no predecessor maintenance pending. PR #67 is
  merge-eligible only after review and CI pass while targeting `develop`.
- Remaining blockers: none known.
