# Phase 1 Execution Plan: Contract And Documentation Cleanup

## Metadata

- Status: refined phase execution plan
- Feature focus: V1 Post Configuration
- PR title: `V1 Post Configuration - Phase 1: Contract And Documentation Cleanup`
- PR URL: `https://github.com/samcantrill/loom/pull/44`
- PR state: `OPEN`
- Branch: `codex/v1-post-contract-docs`
- Worktree: `/home/samcantrill/work/loom-worktrees/v1-post-contract-docs`
- Phase execution plan path: `docs/phases/v1-post-contract-docs.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1-post.md`
- Source phase: Phase 1. Contract And Documentation Cleanup
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after review/checks because target is `develop`
- Workflow path: expanded path
- Successor dependency notes: later v1-post phases may stack on this branch only after the Phase 1 PR is opened or prepared, validated, and recorded as `pr_open`.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v1-post.md`; no blockers remain.
- Plan quality gate loop budget: initial `loom_plan_reviewer` review used, automated plan refinement pass used, confirmation review used.
- Draft pass: completed by `loom_phase_planner`
- Refine pass: completed by `loom_phase_planner`; this is the single expanded-path refinement pass
- Setup limitations: `gh auth status` initially reported an invalid token inside the sandbox, then succeeded with approved network access; `gh auth setup-git` and `git fetch origin` succeeded with approved access before branch creation.
- Blockers: none

## Objective

Align the source import boundary and user-facing configuration documentation with the accepted v1-post decisions, without changing runtime behavior beyond removing the source-level pipeline-to-config type import and adding regression coverage for direct Python pipeline execution without importing `loom.config`.

## Full-Plan Context

This is the root v1-post remediation phase. It cleans contract wording and one source boundary before later phases change stricter authoring semantics, artifact-safe ordering, provenance/fingerprint defaults, run-store manifest persistence, broader structured errors, and final hardening. Future phases must keep ownership of JSON-quoted scalar override parsing, duplicate YAML key rejection, artifact/provenance ordering, default resolved snapshot removal, provenance schema changes, run-store composition manifests, and recipe/resolver debt.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: all earlier v1-post phases are absent, and the manager recorded `develop` as clean, pushed, and at the plan-gate commit.
- Retarget/rebase plan after predecessor merge: not applicable for this root phase; PR target remains `develop`.
- Branch cleanup constraints: after merge, delete `codex/v1-post-contract-docs` only when no successor phase branch depends on it.

## Source Phase Summary

- Goal: align source boundaries and user-facing docs with accepted v1 decisions.
- Required scope: remove source-level `TYPE_CHECKING` import from `loom.pipeline` to `loom.config`; add full `PipelineRunner.run(...)` import-boundary coverage; document trusted-config policy, `inspect_config_composition`, dot-path override no-escape behavior, strict `_target_` syntax, stale `_copy_` roadmap language, and resolved `change-needed` roadmap metadata.
- Required checkpoints: pipeline can run a direct `PipelineSpec` without importing `loom.config`; docs point users to inspection APIs without encouraging pipeline construction from inspection internals; older roadmap language is either corrected or clearly superseded.
- Acceptance criteria: behavior remains unchanged except the import-boundary cleanup, tests prove the boundary, docs no longer contradict the accepted v1-post decisions, and no future-phase runtime semantics are implemented early.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/execution/models.py` uses a `TYPE_CHECKING` import of `loom.config.api.ComposedConfig`, while runtime composed-config handling is already duck-typed through required attributes. `src/loom/pipeline/execution/runner.py` also uses duck-typed composed-config checks and should not gain a real config dependency.
- Existing tests or harness behavior: package import-boundary tests live in `tests/package/test_import_boundaries.py`, including existing import-only pipeline coverage. Execution model unit coverage lives in `tests/unit/loom/pipeline/execution/test_execution_models.py`. Full runner integration coverage lives in `tests/integration/pipeline/test_local_execution.py`, but that module currently imports optional config dependencies at module import time and should not be the only home for the no-config direct-run regression.
- Import-boundary or dependency constraints: `loom.pipeline` must remain usable without `loom.config`, YAML, OmegaConf, Pydantic, CLI, or project config composition imports. The new full-run regression should execute in a fresh Python process so `sys.modules` assertions are meaningful.

## In-Scope Work

- Remove the source-level `TYPE_CHECKING` reference from `loom.pipeline` to `loom.config` while preserving accepted `RunRequest.config` validation and duck-typed composed-config support.
- Add a package-level subprocess regression and, if clearer for suite accounting, a non-optional focused integration test that constructs a direct `PipelineSpec`, runs it through `PipelineRunner.run(...)`, and fails if `loom.config` is imported before or during the direct pipeline run.
- Document authored configs as trusted project code and explicitly state untrusted configs are unsupported.
- Add public config feature docs for `inspect_config_composition`, including that it is for inspection, debugging, and tests, not pipeline construction.
- Document dot-path override no-escape behavior and strict `_target_` dotted or colon import syntax.
- Clean stale `_copy_` v1-scope language in older roadmap docs, or mark the older roadmap docs as superseded by `docs/implementation-plans/implementation-plan-v1.md`.
- Correct stale `change-needed` roadmap metadata where implementation and tests already resolved the decision.

## Out-of-Scope Work

- Runtime behavior changes except the import-boundary cleanup.
- CLI commands or CLI docs that imply implemented v1 behavior.
- Implementing `_copy_`, plugin or remote resolvers, global include search, persistence changes, provenance schema changes, run-store composition manifests, default resolved snapshot removal, structured-error expansion, strict YAML duplicate-key rejection, JSON-quoted scalar override parsing, or broad strict override semantics.
- Reworking public `ComposedConfig`, manifest, provenance, fingerprint, recipe, or resolver behavior.
- Opening a PR, running broad validation, or changing phase metadata in the source implementation plan during this planning pass.

## Assumptions

- The source plan's plan quality gate status is authoritative: review, refinement, and confirmation review budgets are already consumed with no blocking findings remaining.
- Direct `PipelineSpec` execution can be tested without importing config extras by building the `PipelineSpec` from plain Python data, using existing pipeline support stages, and using `LocalRunStore` from a fresh subprocess.
- Roadmap metadata cleanup should be narrow and factual; older planning notes may be marked superseded instead of rewritten extensively when they are historical records.
- Documentation updates should stay domain-neutral and describe the Python API surface only.

## Scope Contract

No new public runtime contract is introduced. The existing public contract is clarified: `loom.pipeline` can construct and run direct Python `PipelineSpec` inputs without importing `loom.config`; `loom.config` composition and inspection APIs are optional Python APIs; authored configs are trusted project code, not an untrusted parsing sandbox; `inspect_config_composition` is an inspection/debugging/testing API and not a construction path for pipeline execution; dot-path overrides split on literal dots and do not provide an escape syntax for literal dots in key names; `_target_` values must be strict dotted or colon import paths.

The executor must not redesign config parsing, `_target_` import resolution, override value parsing, or pipeline/config persistence behavior in this phase.

## Design Impact

- Maintainability: removes a misleading cross-package type-only dependency and makes the boundary executable through a full-run regression, reducing future accidental coupling.
- Extensibility: preserves duck-typed plain-data boundaries so later artifact and manifest phases can add pipeline persistence without importing config classes.
- Domain neutrality: documentation frames configs and recipes as trusted project code and avoids domain-specific workflow assumptions.
- Source-tree boundaries: `loom.pipeline` remains independent of `loom.config`; docs describe `loom.config` as optional composition tooling rather than a required runtime layer.

## Future Compatibility

This phase should make later v1-post changes easier to review by removing stale contract ambiguity before behavior changes land. Documentation should leave room for future `_copy_`, CLI, plugin/remote resolver, and persistence work by naming them deferred or superseded rather than implying permanent rejection outside v1-post scope.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep the `TYPE_CHECKING` import and rely on runtime laziness | The source contract explicitly forbids pipeline-to-config dependency, and type-only imports still encode the wrong source boundary. |
| Replace `RunRequest.config` support with concrete `ComposedConfig` imports | That would invert the accepted boundary and make direct pipeline use depend on optional config APIs. |
| Document `inspect_config_composition` as a pipeline construction helper | The accepted API is for inspection/debugging/tests; construction belongs to direct config composition plus explicit instantiation or direct `PipelineSpec` data. |
| Rewrite all historical roadmap notes in detail | Historical artifacts should remain recognizable; narrow correction or superseded markers are safer and more reviewable. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| None expected. | This phase should remove stale debt rather than introduce new behavior debt. | If implementation discovers unavoidable residual stale wording, record the exact doc path and defer it to Phase 7 final hardening. |

## Reviewability

- Expected PR size and shape: small source import-boundary cleanup, one focused full-run regression test, and targeted documentation/metadata edits.
- Files and areas to inspect: `src/loom/pipeline/execution/models.py`, `tests/package/test_import_boundaries.py`, `tests/unit/loom/pipeline/execution/test_execution_models.py`, a narrowly chosen non-optional pipeline integration test file if needed, `docs/features/config.md`, `docs/implementation-plans/implementation-roadmap.md`, and `docs/implementation-plans/roadmap-v1-planning-notes.md`.
- Scope-control checks: diff must not add config imports to pipeline runtime modules, change composed-config artifact behavior, add CLI/persistence paths, implement `_copy_`, broaden resolver support, or alter strict override semantics beyond documentation.

## Implementation Steps

1. Remove the type-only config import boundary leak while preserving current runtime duck-typing and validation messages.
2. Add the full direct `PipelineSpec` runner regression in a fresh subprocess and assert `loom.config` plus config-only dependencies are not imported before or after `PipelineRunner.run(...)`.
3. Add or update focused execution model unit coverage for `RunRequest` direct-pipeline and plain-mapping config acceptance without a concrete config class dependency.
4. Update public config docs for trusted project code, `inspect_config_composition` usage boundaries, dot-path no-escape behavior, and strict `_target_` syntax.
5. Apply the narrow roadmap cleanup for stale `_copy_` v1 wording and resolved `change-needed` metadata, preferring superseded notes where broad rewrites would obscure historical context.
6. Run targeted package/docs/config-extra checks, then let PR preparation run the final repository gates.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py` and any existing package API test touched by import cleanup.
- Required assertions or deferral reason: fresh subprocess imports only direct pipeline APIs and local store/runtime helpers needed for execution, constructs a direct `PipelineSpec` from plain Python data, runs `PipelineRunner.run(...)` through a local run store, verifies the run succeeds and writes expected artifacts, and confirms `loom.config`, YAML, OmegaConf, Pydantic, CLI, and project config composition modules are not imported before or after the direct pipeline path.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/execution/test_execution_models.py`.
- Required assertions or deferral reason: focused assertions that `RunRequest` accepts direct `PipelineSpec` inputs and plain mapping config inputs without importing or requiring a concrete `ComposedConfig` class. If annotations are changed through a local protocol or alias, unit coverage must also assert current validation messages remain stable for invalid `config` and `pipeline` inputs.

### Contract Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: no extension protocol, manifest, provenance, fingerprint, or config artifact contract changes are in scope.

### Integration Suite

- Status: required.
- Expected paths: prefer a new focused non-optional integration test under `tests/integration/pipeline/` if the package subprocess test would become too large; avoid depending on `tests/integration/pipeline/test_local_execution.py` unless its module-level optional config imports are isolated first.
- Required assertions or deferral reason: `PipelineRunner.run(...)` succeeds with direct `PipelineSpec`, persists normal local-run state and artifacts, and does not import `loom.config` during the full run. The same subprocess test may satisfy package and integration intent only if the PR evidence explicitly records that it executes the full local runner path without config extras.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: this phase has no user workflow behavior change beyond documentation and an import-boundary cleanup; direct-run behavior is covered by package/integration tests.

### Opt-In Suites

- Status: deferred unless executable docs/examples or optional config-extra snippets are changed.
- Markers affected: `optional_dependency`, config-extra/docs-example markers if existing example-check tests cover edited snippets.
- Required assertions or deferral reason: run relevant docs/example or config-extra checks if edited docs include executable snippets; if edits are prose-only, record that no opt-in runtime behavior was touched and rely on `make test-summary` during PR preparation for suite evidence.

## Risks

- A full runner subprocess test may accidentally import optional config dependencies through test support utilities; use direct pipeline support stages and avoid config fixtures.
- Removing the type-only import may require careful annotations so Pyright remains satisfied without widening runtime imports.
- Roadmap cleanup can over-edit historical planning records; prefer precise metadata correction or superseded labels.
- Docs may imply future-phase behavior if they mention artifact-safe persistence, `_copy_`, CLI, or resolver support too broadly; keep wording anchored to current v1-post decisions.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/pipeline/execution/test_execution_models.py
uv run pytest tests/integration/pipeline/test_direct_execution_import_boundary.py
```

Run the focused integration command only if the executor adds that separate
non-optional integration file; otherwise record in PR evidence that the package
subprocess test executed the full local runner path.

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: source boundary cleanup first, direct-run subprocess and unit regressions second, public config docs third, roadmap metadata cleanup fourth.
- Tests to run with each slice: run `uv run pytest tests/package/test_import_boundaries.py` and `uv run pytest tests/unit/loom/pipeline/execution/test_execution_models.py` after import/test changes; run the narrow non-optional integration target if a separate test file is added or touched; run docs/example checks only if executable snippets are edited.
- Decisions the executor must not revisit: no new runtime config behavior, no CLI, no `_copy_`, no plugin/remote resolvers, no persistence changes, no provenance/fingerprint schema changes, no strict YAML or override behavior changes beyond docs, and no pipeline dependency on config classes.
- Conditions that require stopping for the manager: direct full runner coverage cannot be added without importing `loom.config`; Pyright requires a concrete config import in pipeline source; roadmap cleanup conflicts with historical artifact policy; or docs correction requires deciding future-phase semantics not already accepted in the source plan.
- Expanded-path refinement notes: completed. This refinement names the exact required package and unit test homes, constrains any integration addition to a non-optional direct-run test, keeps executable docs checks conditional on snippet edits, and does not add product-code recipes or broaden Phase 1.

## Refinement And Review Budget Status

- Phase implementation refinement: used
- PR body draft pass: completed
- PR body refine pass: completed
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on `codex/v1-post-contract-docs`.
- Final phase execution plan: completed by expanded-path refinement.
- Implementation summary: removed the `loom.pipeline.execution.models` type-only import from `loom.config` by replacing the concrete `ComposedConfig` annotation with a private duck-typed protocol; preserved runtime mapping and composed-config validation behavior; added package subprocess coverage that constructs a direct `PipelineSpec`, runs it through `PipelineRunner.run(...)` with `LocalRunStore`, verifies the expected artifact index, and asserts `loom.config`, `loom.cli`, `project`, `yaml`, `omegaconf`, and `pydantic` stay unloaded before and after the run; added unit coverage for direct `PipelineSpec`, plain mapping config, and duck-typed composed config acceptance; updated config docs for trusted project-code policy, `inspect_config_composition` inspection-only boundaries, dot-path override no-escape behavior, and strict dotted/colon `_target_` syntax; cleaned stale `_copy_` implementation-scope wording from the active roadmap and corrected D01, D03, and D23 planning-note statuses to `confirmed`.
- Implementation validation: `uv --cache-dir /tmp/loom-uv-cache run pytest tests/package/test_import_boundaries.py tests/unit/loom/pipeline/execution/test_execution_models.py` passed with 25 tests; `uv --cache-dir /tmp/loom-uv-cache run pyright src/loom/pipeline/execution/models.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/execution/test_execution_models.py` passed with 0 errors, 0 warnings, and 0 informations. Initial unqualified `uv run pytest ...` attempts could not write to `~/.cache/uv` in the sandbox; rerun used a writable `/tmp` uv cache, with approved network access to fetch missing dev dependencies.
- Integration evidence: no separate integration file was added because the package subprocess regression executes the full local runner path with a direct `PipelineSpec` and local run store while proving the config import boundary.
- Refinement summary: expanded-path implementation/test refinement pass completed on 2026-05-06 by `loom_phase_refiner`; reviewed the dedicated worktree, current diff against `develop`, implementation plan, phase execution plan, refinement template, and executor validation notes; found no phase-caused blocking test, type, lint, build, runtime, suite-coverage, or docs-scope issues requiring code/test/doc fixes; kept the existing implementation unchanged and consumed the phase implementation refinement budget.
- Refinement scope: validation output reviewed was `uv --cache-dir /tmp/loom-uv-cache run pytest tests/package/test_import_boundaries.py tests/unit/loom/pipeline/execution/test_execution_models.py` and `uv --cache-dir /tmp/loom-uv-cache run pyright src/loom/pipeline/execution/models.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/execution/test_execution_models.py`; blocking issues caused by this phase were none; out-of-scope issues remained CLI, `_copy_`, persistence/provenance/schema changes, strict YAML or override runtime semantics, and Phase 2+ behavior.
- Refinement fixes made: none beyond this completion-note update because the implementation, tests, and docs already satisfied the Phase 1 scope and suite obligations.
- Refinement validation re-run: `uv --cache-dir /tmp/loom-uv-cache run pytest tests/package/test_import_boundaries.py tests/unit/loom/pipeline/execution/test_execution_models.py` passed with 25 tests; `uv --cache-dir /tmp/loom-uv-cache run pyright src/loom/pipeline/execution/models.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/execution/test_execution_models.py` passed with 0 errors, 0 warnings, and 0 informations.
- PR preparation handoff: completion notes and budget status are updated; final `make validate-pr` and `make test-summary` have been run for the draft pass; the refine/open pass should re-check only if it changes the PR body or branch state in a way that invalidates this evidence.
- PR preparation draft validation: initial `UV_CACHE_DIR=/tmp/loom-uv-cache make validate-pr` passed Ruff but failed during Pyright environment setup because sandboxed DNS could not fetch `pyyaml==6.0.3`; rerunning the same command with approved network access succeeded. Final `make validate-pr` evidence: Ruff passed; Pyright passed with 0 errors, 0 warnings, and 0 informations; default suite passed 435 tests with 11 skipped; config-extra suite passed 314 tests with 441 deselected; `uv build` produced the source distribution and wheel. Final `make test-summary` evidence: `build/test-summary.md` written with package 38 passed/1 skipped, unit 357 passed/1 skipped, contract 31 passed/2 skipped, integration 9 passed/5 skipped, e2e 6 passed, config-extra 314 passed/441 deselected, overall 755 passed/9 skipped in 24.01s.
- PR preparation draft scope gate: passed. The diff matches Phase 1 by limiting runtime code changes to the pipeline/config type-import boundary, adding package/unit regression coverage, and updating docs/roadmap metadata. No future-phase implementation was found for strict YAML duplicate-key rejection, JSON-quoted scalar override parsing, artifact-safe provenance/fingerprint ordering, default resolved snapshot persistence changes, run-store composition manifests, structured-error expansion, or recipe/resolver hardening.
- PR facts for refine/open pass: title `V1 Post Configuration - Phase 1: Contract And Documentation Cleanup`; body path `docs/phases/v1-post-contract-docs-pr-body.md`; PR URL `https://github.com/samcantrill/loom/pull/44`; head `codex/v1-post-contract-docs`; target `develop`; stack predecessor none; merge eligibility root PR is merge-eligible after review/checks because target is `develop`; GitHub checks pending after PR creation.
- PR body draft: completed using `.codex/templates/phase-pr-body.md`; body mentions `@samcantrill` near the top; public body keeps workflow internals in this phase plan and uses compact validation/suite tables.
- PR body refine: completed on 2026-05-06 using `.codex/prompts/pr-body-refine.md`; verified the dedicated worktree, branch, target branch, implementation diff, acceptance criteria, suite evidence, scope boundaries, assumptions, and risks against the draft PR body. The only public-body refine change updated the GitHub checks row from draft-pass deferral to post-PR pending status. No implementation or test files were changed.
- PR opening: completed on 2026-05-06 with explicit `gh pr create --base develop --head codex/v1-post-contract-docs --title "V1 Post Configuration - Phase 1: Contract And Documentation Cleanup" --body-file docs/phases/v1-post-contract-docs-pr-body.md`.
- PR verification: `gh pr view 44 --json baseRefName,headRefName,state,url` returned base `develop`, head `codex/v1-post-contract-docs`, state `OPEN`, URL `https://github.com/samcantrill/loom/pull/44`; verified target/head match the phase plan.
- GitHub checks: `gh pr checks 44 --watch=false` reported the workflow check pending at `https://github.com/samcantrill/loom/actions/runs/25410865051/job/74532104991`.
- PR preparation: draft completed; refine completed; PR opened and verified.
- Stack state: root phase PR with no predecessor; target is `develop`; merge-eligible only after review and checks pass; later v1-post phases may stack on `codex/v1-post-contract-docs` after the manager records this phase as `pr_open`.
- Stack maintenance: pending; no retarget or rebase performed by PR preparation.
- Remaining blockers: none after implementation and refinement validation.
