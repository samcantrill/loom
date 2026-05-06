# Phase 5 Execution Plan: Run Command

## Metadata

- Status: implementation complete; PR preparation pending
- Feature focus: CLI Core
- PR title: `CLI Core - Phase 5: Run Command`
- Branch: `codex/add-cli-run`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-cli-run`
- Phase execution plan path: `docs/phases/add-cli-run.md`
- Full plan: `docs/implementation-plans/implementation-plan-v2.md`
- Source phase: Phase 5 - Run Command
- Stack predecessor: none; Phases 1 through 4 are merged.
- Base branch: `develop` at `27d10bb` (`docs: record v2 phase 4 merged`)
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after local review, validation, and CI because the target is `develop`.
- Workflow path: fast path; the v2 plan resolves command behavior, and this phase should be a command adapter over existing execution/store APIs.
- Successor dependency notes: Phase 6 owns final docs and broad e2e hardening. Do not absorb Phase 6 documentation work beyond tests needed for this command.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v2.md`; no blocking findings remain.
- Plan quality gate loop budget: initial review used, plan refinement completed through v2 discussion, confirmation review not needed because no blocking findings remained.
- Draft pass: completed by the managing agent in this artifact.
- Refine pass: not needed on the fast path.
- Setup limitations: `git worktree add` required approved git metadata access after the sandbox could not create the branch ref. `origin/develop` was verified before branch creation.
- Blockers: none known.

## Objective

Add `loom run` for local v0 execution. The CLI should compose config, map selector/resume/run URI options into public execution objects, reject unsupported executors, delegate `--dry-run` to the Phase 4 plan path, call `PipelineRunner` for real execution, and format final text/JSON results without writing run state directly.

## Full-Plan Context

Phase 4 added read-only planning. Phase 5 is the first mutating CLI command and must preserve the boundary that runtime/store APIs own run creation, default URI allocation, locks, status, plan persistence, artifact indexes, and stage execution. Phase 6 will document and harden the full CLI surface after run behavior exists.

Future-phase work that remains out of scope includes progress streaming, status/log/artifact commands, subprocess workers, remote stores, executor registries, scheduler/container support, and docs/e2e expansion beyond phase-scoped coverage.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: all earlier v2 phases are merged and local `develop` includes the Phase 4 metadata commit.
- Retarget/rebase plan after predecessor merge: none expected.
- Branch cleanup constraints: delete this worktree and branch after merge if no successor branch depends on it.

## Source Phase Summary

- Goal: add `loom run` for v0 local execution.
- Required scope: add `src/loom/cli/run.py`, wire parser registration, map config/selectors/run URI/resume/default URI/local executor into `RunRequest`/`PipelineRunner`, implement `--dry-run` via the plan path, reject unsupported executors with exit code 7, and format final result JSON.
- Required checkpoints: successful synthetic run, default store-owned run URI allocation, exact explicit run URI use, existing target failure, strict resume, failed-run exit code/output, dry-run no execution, executor rejection in command handling, and final JSON envelope.
- Acceptance criteria: CLI run executes through public local runtime APIs, prints resolved run URI and status, does not compute paths/fingerprints/resume decisions in CLI modules, and returns stable text/JSON output.

## Current Source And Harness Findings

- `src/loom/cli/main.py` still registers `run` as an unsupported placeholder.
- `src/loom/cli/options.py` already has `RunCliOptions`, `SelectorCliOptions`, and `ConfigCliOptions`.
- `src/loom/cli/plan.py` exposes `build_plan_result()` and can be reused for `loom run --dry-run`.
- `LocalRunStore(root="runs")` and `allocate_run_uri()` now provide the store-owned default run URI behavior.
- `PipelineRunner(run_store=...).run(RunRequest(...))` already creates/opens runs, locks, plans, executes, persists state, handles failures, and returns `RunResult`.
- `RunResult` exposes `run_uri`, final `status`, `plan`, `stage_results`, `failure`, and `artifact_index`, which is enough for CLI result formatting.
- Existing integration support stages include successful JSON/text stages and an intentionally failing stage.

## In-Scope Work

- Add `src/loom/cli/run.py` and register it from `main.py`.
- Compose config through `loom.config.compose_config` for execution inputs.
- Convert CLI selectors into `PlanSelectors`, preserving graph-dependent validation in planner/runtime APIs.
- Validate explicit `--run-uri` through `LocalRunStore`; allocate default run URI through `LocalRunStore.allocate_run_uri()` only for real execution when omitted.
- For non-resume execution, fail if the target URI already exists.
- For resume execution, require an existing valid run URI and pass `open_existing=True` to the runner.
- Reject non-`local` executor names in the handler with exit code 7.
- Implement `--dry-run` by delegating to Phase 4 planning behavior and using plan JSON for `--format json`.
- Build `RunCliResult` from `RunResult`, including run URI, final status, stage summaries, failure summary, and plan summary.

## Out-of-Scope Work

- No streaming progress, JSON event stream, live logs, rich terminal UI, status/log/artifact commands, or report files.
- No optional executor imports or executor registry.
- No remote run URI/store support.
- No CLI-local run path derivation, fingerprinting, resume decisions, artifact validation, locks, or status writes.
- No broad docs/e2e completion beyond phase-scoped command tests.

## Assumptions

- The CLI default run store is `LocalRunStore()` and the store owns the default root `runs`.
- `--executor` accepts arbitrary strings at parse time and only `local` is accepted in command handling.
- Failed pipeline runs return exit code 5 even when the runner returns a structured `RunResult` rather than raising.
- `--dry-run --format json` must use `loom.cli.plan.v2`, not a run result schema.

## Scope Contract

User-facing behavior:

- `loom run CONFIG` allocates a store-owned default absolute `file:///...` run URI, prints it, and executes locally.
- `loom run CONFIG --run-uri URI` uses the exact resolved target URI and fails before execution if that URI already exists without `--resume`.
- `loom run CONFIG --run-uri URI --resume` opens the run and performs strict resume execution through the runner.
- `loom run CONFIG --dry-run` returns a plan and does not allocate a default run URI or execute stages.
- `loom run CONFIG --executor NAME` returns exit code 7 for any non-`local` name.

JSON behavior:

- Real execution uses schema version `loom.cli.run.v2`.
- Dry-run JSON uses schema version `loom.cli.plan.v2`.
- Real run results include resolved run URI, final status, plan summary, ordered stage summaries, failure summary when present, and artifact count.

Error behavior:

- Unsupported executor uses a CLI-owned error with exit code 7.
- Config errors map to 3, pipeline/store planning errors to 4, and failed executions to 5.
- JSON errors use the shared CLI error envelope after parsing succeeds.

## Design Impact

- Maintainability: `loom run` remains a thin adapter over `RunRequest` and `PipelineRunner`.
- Extensibility: command flags align with future runtime option/executor models without implementing them early.
- Domain neutrality: summaries report generic stages, statuses, actions, and failures only.
- Source-tree boundaries: CLI imports public config/planning/execution/store APIs and avoids project target imports outside runner execution.

## Future Compatibility

- V4 can replace CLI option dataclasses with runtime option constructors.
- V5+ can add subprocess/stage-worker behavior behind executor APIs.
- V3 diagnostics can inspect the run URI emitted by this command.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Treat unsupported executors as argparse choices | It would return usage exit code 2 and make future executor names parser-level failures. |
| Emit streaming JSON progress | V2 requires a single final JSON envelope; progress is deferred. |
| Implement dry-run separately from plan | It would duplicate planning behavior and risk drift from `loom plan`. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Only `local` executor is supported | V2 is the local CLI core and executor registry work is deferred | V4/V5 runtime option and stage-worker phases |

## Reviewability

- Expected PR size and shape: one command module, small registration/result/formatting updates, focused unit/integration tests, and phase artifacts.
- Files and areas to inspect: `src/loom/cli/run.py`, `src/loom/cli/main.py`, `src/loom/cli/results.py`, `src/loom/cli/formatting.py`, and command tests.
- Scope-control checks: no direct status/store writes in CLI, no optional executor imports, no path splitting, no raw execution-plan JSON for run output, and dry-run delegates to Phase 4 plan behavior.

## Implementation Steps

1. Add the phase plan commit.
2. Implement run parser registration, unsupported executor error, and real execution orchestration.
3. Extend run result formatting/text/JSON helpers.
4. Implement dry-run delegation to the Phase 4 planning path.
5. Add unit and integration coverage for success, failure, default/explicit URI, resume, dry-run, JSON, and executor rejection.
6. Run targeted suites, then `make validate-pr` and `make test-summary`.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: importing/helping CLI must not load optional executor backends or project targets; run command import should remain bounded until execution.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/cli/test_run.py`, `tests/unit/loom/cli/test_formatting.py`, `tests/unit/loom/cli/test_main.py`, `tests/unit/loom/cli/test_options.py`.
- Required assertions or deferral reason: parser behavior, default URI allocation only for real execution, explicit URI forwarding, existing-target failure, dry-run plan delegation, executor rejection exit code 7, text/JSON formatting, and failed run exit code 5.

### Contract Suite

- Status: deferred.
- Expected paths: none expected.
- Required assertions or deferral reason: Phase 5 should use existing execution/store protocols rather than adding new structural contracts.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_cli_run.py`.
- Required assertions or deferral reason: real command execution for successful run, failed run, resume, dry-run, explicit URI, default URI, JSON output, and unsupported executor behavior.

### E2E Suite

- Status: deferred.
- Expected paths: Phase 6 e2e suite.
- Required assertions or deferral reason: broad CLI e2e coverage is assigned to final hardening, though integration tests may exercise `main(argv)` end to end.

### Opt-In Suites

- Status: not affected beyond existing config-extra integration tests.
- Markers affected: `optional_dependency` for config composition integration tests.
- Required assertions or deferral reason: no external services or optional executor backends are involved.

## Risks

- Dry-run must not accidentally allocate a default run URI through run command setup.
- Non-resume existing URI checks must happen before runner mutation.
- Import-boundary tests should catch accidental executor/project-target imports during help/import.
- Failure results must map to exit code 5 without hiding the structured failure summary.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/cli tests/package/test_import_boundaries.py -q
uv run --extra config pytest tests/integration/config/test_cli_run.py -q
uv run ruff check .
uv run --extra config pyright
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: command parser/errors first, run execution path second, dry-run path third, formatting/tests last.
- Tests to run with each slice: start with `tests/unit/loom/cli/test_run.py`, then config integration tests, then the targeted command list above.
- Decisions the executor must not revisit: local-only executor, dry-run uses plan schema, default URI allocation only for real run, strict resume, and no CLI-local store mutation.
- Conditions that require stopping for the manager: a need to change runner lifecycle behavior, a need for executor registry design, or inability to avoid default URI allocation in dry-run.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed in this commit.
- Final phase execution plan: completed in this commit; fast-path refine pass not needed.
- Implementation summary: completed in `4bd72bf` (`feat: implement run command`). The phase adds `loom run`, local-only executor handling, default URI delegation to `PipelineRunner`/`LocalRunStore`, explicit URI existence checks, strict resume setup, dry-run delegation to Phase 4 plan output, final run JSON/text formatting, failure summaries, and import-boundary/unit/integration coverage.
- Implementation validation: targeted `uv run pytest tests/unit/loom/cli tests/package/test_import_boundaries.py -q` passed with 56 tests; targeted `uv run --extra config pytest tests/integration/config/test_cli_run.py -q` passed with 7 tests; `uv run ruff check .` passed; `uv run --extra config pyright` passed with 0 errors; `make validate-pr` passed with default 505 passed / 11 skipped and config-extra 380 passed / 512 deselected plus build success; `make test-summary` passed with package 43 passed / 1 skipped, unit 417 passed / 1 skipped, contract 36 passed / 2 skipped, integration 9 passed / 5 skipped, e2e 7 passed, and config-extra 380 passed / 512 deselected.
- Refinement summary: not needed; targeted and full validation passed without a phase-refiner pass.
- PR preparation: pending.
- Stack maintenance: not needed yet.
- Remaining blockers: none known.
