# Phase 4 Execution Plan: Preflight, Diagnostics, And CLI UX

## Metadata

- Status: in_progress
- Feature focus: Stage Worker
- PR title: `Stage Worker - Phase 4: Preflight, Diagnostics, and CLI UX`
- Branch: `codex/subprocess-preflight-diagnostics`
- Worktree: `/home/samcantrill/work/loom-worktrees/subprocess-preflight-diagnostics`
- Phase execution plan path: `docs/phases/subprocess-preflight-diagnostics.md`
- Full plan: `docs/implementation-plans/implementation-plan-v5.md`
- Source phase: Phase 4 - Preflight, Diagnostics, And CLI UX
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR, merge-eligible when automated review, validation, CI, and scope gates pass
- Workflow path: expanded path, because this phase changes stable preflight check IDs and user-facing failure output across diagnostics, CLI formatting, and subprocess execution evidence
- Successor dependency notes: Phase 5 must harden examples and broader cross-component contracts without changing the Phase 4 preflight check identity or concise failure-summary shape unless a documented blocker requires it.
- Plan quality gate: passed on 2026-05-07 after initial review, one refinement pass, and confirmation review
- Plan quality gate loop budget: consumed as recorded in `docs/implementation-plans/implementation-plan-v5.md`
- Draft pass: completed by manager on 2026-05-07
- Refine pass: completed by manager on 2026-05-07 for expanded path
- Setup limitations: none; Phases 1, 2, and 3 are merged on `develop`, and this worktree was created from `develop`.
- Blockers: none known

## Objective

Make selected subprocess execution fail fast when its local Python worker command cannot be used, and make run failures expose the subprocess facts users need without requiring project-stage imports or verbose command dumps.

## Full-Plan Context

V5 Phase 1 created prepared attempts and worker result persistence. Phase 2 added direct durable worker execution through `loom stage run`. Phase 3 added serial subprocess execution through the parent runner. Phase 4 now adds selected-subprocess availability checks and concise failure summaries over the metadata Phase 3 already persists. Phase 5 remains responsible for broader examples, documentation, and contract hardening.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 3 PR #79 is merged
- Why this base branch is correct: all earlier v5 phases are merged into `develop`
- Retarget/rebase plan after predecessor merge: none
- Branch cleanup constraints: branch may be deleted after the Phase 4 PR is merged if no successor branch depends on it

## Source Phase Summary

- Goal: make subprocess execution diagnosable and validate selected executor availability before running user stage code.
- Required scope: subprocess preflight checks under the existing executor capability model, fail selected subprocess preflight when the worker command or Python executable is unavailable, avoid launching user stage code, add concise failure output with stage, attempt, exit code, signal, message, stdout/stderr paths, and traceback or failure path, and preserve existing JSON conventions.
- Required checkpoints: subprocess preflight distinguishes worker/Python availability failures from unknown-executor failures; normal local preflight output stays stable; CLI run JSON and text include subprocess failure facts; existing status/log/artifact inspection continues to read persisted subprocess metadata without importing project stage code.

## Current Source And Harness Findings

- Existing preflight check identity is centralized in `STABLE_CHECK_IDS`; executor checks currently include only `executor.local`, `executor.resolve`, and `executor.capabilities`.
- `run_preflight()` dispatches by group and computes selected runtime options lazily. `context.runtime_options().executor or "local"` is the selected executor source.
- `loom run` already performs a minimal pre-run preflight and passes resolved runtime options, so selected subprocess checks can run before `PipelineRunner` invokes any stage code.
- Phase 3 registered the subprocess descriptor and CLI executor factory, so normal `--executor subprocess` selection no longer appears as a generic unknown executor.
- `ExecutionFailure` already stores attempt, executor, stdout/stderr paths, traceback path, exit code, signal, and executor metadata. `_failure_summary()` and `format_run_text()` currently expose only a subset of those fields.
- Existing status/log/artifact commands read store inspection APIs and stage failure records; no new diagnostics command family is needed.

## In-Scope Work

- Add stable subprocess executor check IDs for Python executable and worker command availability.
- Run subprocess-specific availability checks only when the selected executor is `subprocess`.
- Check the selected Python executable deterministically without launching stage code.
- Check that the public worker module/command can be resolved without constructing configured stage targets.
- Return structured PASS/FAIL diagnostics for selected subprocess availability failures, with details suitable for JSON output.
- Extend CLI run failure summaries to include attempt, executor, exit code, signal, stdout path, stderr path, traceback path, and failure record path when available.
- Keep text output concise while pointing to persisted logs and failure metadata.
- Update focused docs for subprocess preflight and failure UX.

## Out-of-Scope Work

- New diagnostics command families.
- Scheduler, SLURM, container, or plugin executor checks.
- Full environment persistence or environment redaction policy changes.
- Launching user stage code during preflight.
- Changing subprocess execution semantics, retry behavior, timeouts, parallelism, or attempt archive layout.
- Broad redesign of CLI result schemas beyond adding optional failure-summary fields.

## Assumptions

- The subprocess worker command remains the Phase 3 command shape using `sys.executable`, a Python `-c` snippet, and `loom.cli.main:main()`.
- Import resolution for `loom.cli.main` is a sufficient worker-command availability check for Phase 4; executing the command is intentionally avoided.
- A missing selected Python executable or unresolved worker module is an executor availability failure, not a generic unknown-executor failure.
- Failure record paths can be reported from current run-store layout as `stages/<stage>/failure.json` without adding new model fields.

## Design Impact

- Maintainability: executor-specific preflight remains an extension of the existing preflight executor group instead of a separate command surface.
- Extensibility: future SLURM/container checks can follow the selected-executor-only pattern and add stable executor-specific check IDs.
- Domain neutrality: diagnostics report Loom runtime and process facts only.
- Source-tree boundaries: diagnostics may resolve CLI worker importability, while execution and stores continue to own running and persistence.

## Future Compatibility

- Stable check IDs should remain additive and selected-executor-specific so local preflight remains compact.
- Failure-summary fields should be optional to support local, subprocess, and future executor metadata without forcing every executor to synthesize unavailable values.
- Signal and exit-code fields must remain distinct because future reliability policies and scheduler backends need that distinction.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Always run subprocess checks in full preflight | Adds local-run noise and can fail environments that are not selecting subprocess execution. |
| Execute `loom stage run --help` or a dummy worker during preflight | Starts CLI code unnecessarily and risks side effects outside availability checks. |
| Keep subprocess availability as warnings | A selected executor that cannot launch its worker should fail before user stage execution. |
| Add a new diagnostics command family | Phase 4 only needs existing preflight and run output conventions. |
| Print full subprocess command/environment by default | Too verbose and risks leaking unnecessary environment details. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Worker command availability is import-resolution based | It avoids running code and matches the current command shape. | A future executor command adapter supports external worker binaries or plugin-discovered workers. |
| Failure record path is derived from the current local run-store layout | The store already exposes stable local stage directories for local URIs, and remote stores are out of scope. | Remote run stores or attempt archive directories are introduced. |
| CLI text remains intentionally compact | Phase 4 is UX hardening, not a rich diagnostics UI. | Users need multi-stage failure tables or configurable verbosity. |

## Reviewability

- Expected PR size and shape: small-to-medium diagnostics/CLI/test/docs PR.
- Files and areas to inspect: `diagnostics.models`, `diagnostics.preflight`, `cli.run`, `cli.formatting`, subprocess preflight and CLI run tests, focused docs.
- Scope-control checks: no user stage construction during preflight, no subprocess execution behavior changes, no new dependencies, no broad CLI schema redesign, and no Phase 5 examples/hardening work.

## Implementation Steps

1. Add selected-subprocess preflight checks and stable check IDs.
2. Extend run failure summary construction and text formatting to include persisted failure/log/process facts.
3. Add package/contract/unit/integration/e2e coverage for selected subprocess preflight and failure UX.
4. Update focused docs and phase completion notes.

## Test Plan

### Package Suite

- Status: required
- Expected paths: package/import-boundary coverage if public preflight IDs or exports change.
- Required assertions or deferral reason: public diagnostics imports remain stable and do not import project stage code.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/diagnostics/test_diagnostics_preflight.py`, `tests/unit/loom/cli/test_run.py`, and `tests/unit/loom/cli/test_formatting.py`.
- Required assertions or deferral reason: subprocess check result construction, selected-executor failure severity, missing Python/worker failure details, JSON failure-summary shape, concise text formatting with signal/log facts, and no-user-code preflight behavior.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_diagnostics_preflight_contract.py`.
- Required assertions or deferral reason: stable check ID additions are explicit and ordered.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/diagnostics/test_diagnostics_preflight_integration.py`.
- Required assertions or deferral reason: real selected-subprocess preflight passes without writing run documents and includes selected-subprocess availability checks only for subprocess selection.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_core.py`.
- Required assertions or deferral reason: subprocess failure smoke coverage verifies JSON and text failure UX includes stage, attempt, exit/signal/log/traceback facts.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected beyond existing optional dependency markers.
- Required assertions or deferral reason: Phase 4 uses local deterministic checks and subprocess smoke tests only; it does not require SLURM, containers, network, or remote stores.

## Risks

- Adding stable check IDs without selection gating could break local preflight expectations. Gate subprocess checks on selected executor.
- Importing CLI modules from diagnostics could create a dependency cycle. Use importlib resolution rather than importing `loom.cli.main`.
- New failure-summary fields could destabilize existing JSON consumers if added unconditionally with non-plain values. Use plain optional scalar/string fields.
- Text output can become noisy. Add only non-empty failure facts and keep one line per persisted path.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/contracts/test_diagnostics_preflight_contract.py tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/unit/loom/cli/test_run.py tests/unit/loom/cli/test_formatting.py tests/integration/diagnostics/test_diagnostics_preflight_integration.py tests/e2e/test_cli_core.py
uv run pyright src/loom/diagnostics src/loom/cli tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/unit/loom/cli/test_run.py tests/unit/loom/cli/test_formatting.py tests/integration/diagnostics/test_diagnostics_preflight_integration.py tests/e2e/test_cli_core.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by manager on 2026-05-07.
- Final phase execution plan: refined by manager on 2026-05-07 before implementation to clarify selected-executor gating, preflight no-user-code constraints, CLI failure-summary scope, and Phase 5 boundaries.
- Implementation summary: added selected-subprocess preflight checks for the
  current Python executable and `loom stage run` worker importability, gated so
  local executor preflight output remains unchanged. Extended run failure
  summaries and text output with optional attempt, executor, exit code, signal,
  failure record, stdout, stderr, and traceback paths. Updated focused
  preflight, CLI, and execution docs for the current subprocess diagnostics UX.
- Implementation validation:
  - Focused tests passed:
    `uv run pytest tests/contracts/test_diagnostics_preflight_contract.py tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/unit/loom/cli/test_run.py tests/unit/loom/cli/test_formatting.py tests/integration/diagnostics/test_diagnostics_preflight_integration.py tests/e2e/test_cli_core.py`
    with 31 passed and 2 skipped.
  - Focused Ruff passed for touched implementation and test files.
  - Focused Pyright passed for touched diagnostics, CLI, and test files.
  - `make validate-pr` passed: Ruff, Pyright with config extra, default test
    harness, config-extra test harness, and build.
  - `make test-summary` passed and wrote `build/test-summary.md`: package 50
    passed/1 skipped; unit 593 passed/1 skipped; contract 55 passed/2
    skipped; integration 20 passed/7 skipped/7 deselected; e2e 18 passed;
    config-extra 401 passed/736 deselected.
- Refinement summary: not needed after focused checks and full validation passed.
