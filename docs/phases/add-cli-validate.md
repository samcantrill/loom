# Phase 3 Execution Plan: Validate Command

## Metadata

- Status: implemented; PR preparation pending
- Feature focus: CLI Core
- PR title: `CLI Core - Phase 3: Validate Command`
- Branch: `codex/add-cli-validate`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-cli-validate`
- Phase execution plan path: `docs/phases/add-cli-validate.md`
- Full plan: `docs/implementation-plans/implementation-plan-v2.md`
- Source phase: Phase 3 - Validate Command
- Stack predecessor: none; Phase 2 is merged.
- Base branch: local `develop` at `1ed4902` (`docs: record v2 phase 2 merged`)
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after automated review and CI because the target is `develop`.
- Workflow path: expanded path, selected because this phase is the first behavior-bearing CLI command and adds narrow public validation/target-check facades.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v2.md`; no blocking plan-review findings remain.
- Draft/refine status: scope-complete plan drafted in this artifact; no separate refinement pass needed unless validation or review exposes a blocker.
- Phase implementation refinement budget: not needed; targeted validation and the PR gate passed without a refinement pass.
- PR review budget: unused.
- Blockers: none known.

## Objective

Implement `loom validate CONFIG` as a static-by-default command that composes trusted config, validates the pipeline through owning package APIs, optionally constructs targets under `--check-targets`, and renders stable text/JSON output without writing run state.

## Scope

- Add `src/loom/cli/validate.py` and wire it into `src/loom/cli/main.py`.
- Add a narrow `loom.pipeline.validate_pipeline_config(...)` facade that parses the resolved top-level config, validates pipeline spec and graph consistency, and returns structured validation facts.
- Add a pipeline-owned stage target check facade that constructs stage factory targets with `StageFactorySpec.init` semantics.
- Add a config-owned target check facade that instantiates generic `_target_` blocks outside caller-specified owning-package target paths.
- Preserve repeated `--overlay` and `--set` values in order when calling `compose_config`.
- Render compact text output and JSON success envelopes with top-level warnings.
- Emit an explicit warning for `--check-targets` because trusted project constructors may run.

## Out Of Scope

- Stage execution, run URI allocation, run-state writes, validation report files, preflight diagnostics, shell completion, or interactive confirmation.
- Plan/run command behavior.
- Rich terminal rendering or persistent validation artifacts.

## Acceptance Criteria

- `loom validate CONFIG` succeeds for a valid synthetic pipeline config.
- Invalid config composition exits with config error code `3`; invalid pipeline shape/graph exits with pipeline error code `4`.
- Default validate performs config composition and static pipeline validation only; it does not construct `_target_` objects.
- `loom validate CONFIG --check-targets` runs static validation first, warns, constructs stage factory targets through the pipeline facade, constructs remaining generic `_target_` blocks through the config facade, and discards constructed objects.
- Text output is one success line by default, with warnings on stderr only when warnings exist.
- JSON output uses a final success/error envelope with top-level `warnings`.
- CLI help and `import loom.cli.validate` remain import-light and do not import config, pipeline, stores, project modules, plugins, or optional backends.
- Validate does not execute stages or create run/store state.

## Design Notes

- The CLI command should import `loom.config` and `loom.pipeline` lazily inside handler/facade call sites, not at module import or help time.
- The pipeline facade owns stage spec, graph, and stage target construction behavior. The CLI must not call `parse_pipeline_config`, graph helpers, or `construct_stage` directly.
- The config facade owns generic `_target_` traversal/instantiation. The CLI may pass pipeline-owned factory target paths to exclude because those targets are checked by the pipeline facade with different constructor semantics.
- `--check-targets` is the consent boundary. No prompt is added in v2.
- If target construction fails after the target warning has been produced, JSON error output should keep that warning at the envelope top level.

## Test Plan

- Package:
  - validate module import remains bounded;
  - CLI help remains import-light;
  - new public config/pipeline facade exports are stable.
- Unit:
  - validate handler preserves overlay/override order;
  - static success text and JSON output;
  - config and pipeline error exit-code paths through `main(argv)`;
  - `--check-targets` warning behavior and facade invocation order;
  - target-check warning is retained in JSON error envelopes.
- Integration:
  - real config composition plus static pipeline validation with optional config dependencies;
  - `--check-targets` constructs synthetic safe stage and generic target blocks.
- Contract/e2e/opt-in:
  - none required beyond the package, unit, and config-extra integration coverage for this phase.

## Validation Commands

Targeted:

```sh
uv run pytest tests/unit/loom/cli tests/unit/loom/config tests/unit/loom/pipeline tests/package/test_import_boundaries.py tests/package/test_config_api.py tests/package/test_pipeline_api.py -q
uv run --extra config pytest tests/integration/config/test_cli_validate.py -q
```

Final gate:

```sh
make validate-pr
make test-summary
```

## Reviewability

- Review `src/loom/cli/validate.py`, the narrow config/pipeline facades, `main.py` parser wiring, facade export tests, and validate command tests.
- Confirm the CLI remains orchestration only and does not implement config traversal, target import, graph validation, stage construction, or run/store behavior directly.
- Confirm `--check-targets` is explicit, warned, and opt-in.

## Completion Notes

- Draft plan: completed in this commit.
- Implementation summary: added `loom validate`, static pipeline validation through a pipeline facade, opt-in stage/generic target construction checks through owning-package facades, stable text/JSON validate output, target-constructor warnings, JSON error warning propagation, and package/unit/integration coverage.
- Implementation validation:
  - `uv run pytest tests/unit/loom/cli tests/unit/loom/config/test_target_checks.py tests/unit/loom/pipeline/test_pipeline_validation.py tests/package/test_import_boundaries.py tests/package/test_config_api.py tests/package/test_pipeline_api.py -q`: passed, 52 passed, 1 skipped.
  - `uv run --extra config pytest tests/integration/config/test_cli_validate.py -q`: passed, 3 passed.
  - `uv run ruff check .`: passed.
  - `uv run --extra config pyright`: passed, 0 errors.
  - `make validate-pr`: passed; Ruff, Pyright, default no-extra suite, config-extra suite, and build passed.
  - `make test-summary`: passed; overall 865 passed, 9 skipped, 497 deselected.
- PR preparation:
- Merge notes:
- Remaining blockers: none known.
