# Phase 1 Execution Plan: Contract And Documentation Cleanup

## Metadata

- Status: draft phase execution plan
- Feature focus: V1 Post Configuration
- PR title: `V1 Post Configuration - Phase 1: Contract And Documentation Cleanup`
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
- Refine pass: pending after draft because the manager selected the expanded path
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
- Existing tests or harness behavior: package import-boundary tests live in `tests/package/test_import_boundaries.py`, including existing parse-only pipeline coverage. Full runner integration coverage lives in `tests/integration/pipeline/test_local_execution.py` and uses optional config dependencies today.
- Import-boundary or dependency constraints: `loom.pipeline` must remain usable without `loom.config`, YAML, OmegaConf, Pydantic, CLI, or project config composition imports. The new full-run regression should execute in a fresh Python process so `sys.modules` assertions are meaningful.

## In-Scope Work

- Remove the source-level `TYPE_CHECKING` reference from `loom.pipeline` to `loom.config` while preserving accepted `RunRequest.config` validation and duck-typed composed-config support.
- Add a package or integration-level subprocess regression that constructs a direct `PipelineSpec`, runs it through `PipelineRunner.run(...)`, and fails if `loom.config` is imported before or during the direct pipeline run.
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
- Direct `PipelineSpec` execution can be tested without importing config extras by using existing pipeline support test stages and local run stores from a fresh subprocess.
- Roadmap metadata cleanup should be narrow and factual; older planning notes may be marked superseded instead of rewritten extensively when they are historical records.
- Documentation updates should stay domain-neutral and describe the Python API surface only.

## Scope Contract

No new public runtime contract is introduced. The existing public contract is clarified: `loom.pipeline` can construct and run direct Python `PipelineSpec` inputs without importing `loom.config`; `loom.config` composition and inspection APIs are optional Python APIs; authored configs are trusted project code, not an untrusted parsing sandbox; `inspect_config_composition` is an inspection/debugging/testing API and not a construction path for pipeline execution; dot-path overrides do not provide an escape syntax for literal dots in key names; `_target_` values must be strict dotted or colon import paths.

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
- Files and areas to inspect: `src/loom/pipeline/execution/models.py`, `tests/package/test_import_boundaries.py` or a narrowly chosen pipeline integration test file, `docs/features/config.md`, `docs/implementation-plans/implementation-roadmap.md`, and `docs/implementation-plans/roadmap-v1-planning-notes.md`.
- Scope-control checks: diff must not add config imports to pipeline runtime modules, change composed-config artifact behavior, add CLI/persistence paths, implement `_copy_`, broaden resolver support, or alter strict override semantics beyond documentation.

## Implementation Steps

1. Remove the type-only config import boundary leak while preserving current runtime duck-typing and validation messages.
2. Add the full direct `PipelineSpec` runner regression in a fresh subprocess and assert `loom.config` plus config-only dependencies are not imported before or after `PipelineRunner.run(...)`.
3. Update public config docs for trusted project code, `inspect_config_composition` usage boundaries, dot-path no-escape behavior, and strict `_target_` syntax.
4. Apply the narrow roadmap cleanup for stale `_copy_` v1 wording and resolved `change-needed` metadata, preferring superseded notes where broad rewrites would obscure historical context.
5. Run targeted package/docs/config-extra checks, then let PR preparation run the final repository gates.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py` and any existing package API test touched by import cleanup.
- Required assertions or deferral reason: fresh subprocess imports direct pipeline APIs, constructs a direct `PipelineSpec`, runs `PipelineRunner.run(...)` through a local run store, and confirms `loom.config`, YAML, OmegaConf, Pydantic, CLI, and project config composition modules are not imported by the direct pipeline path.

### Unit Suite

- Status: required if practical.
- Expected paths: `tests/unit/loom/pipeline/execution/test_runner.py` or `tests/unit/loom/pipeline` if the import cleanup needs model-level validation.
- Required assertions or deferral reason: focused assertion that `RunRequest` still accepts direct `PipelineSpec` inputs and mapping/composed-like config inputs without a concrete `ComposedConfig` import. If package subprocess coverage fully exercises the removed import and no unit hook adds value, record the unit deferral in the PR body.

### Contract Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: no extension protocol, manifest, provenance, fingerprint, or config artifact contract changes are in scope.

### Integration Suite

- Status: required.
- Expected paths: package subprocess coverage may satisfy this by running the full local runner; otherwise add a focused row under `tests/integration/pipeline/`.
- Required assertions or deferral reason: `PipelineRunner.run(...)` succeeds with direct `PipelineSpec` and does not import `loom.config` during the full run.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: this phase has no user workflow behavior change beyond documentation and an import-boundary cleanup; direct-run behavior is covered by package/integration tests.

### Opt-In Suites

- Status: required for touched docs/examples, otherwise deferred.
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
uv run pytest tests/unit/loom/pipeline/execution/test_runner.py
uv run pytest tests/integration/pipeline/test_local_execution.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: source boundary cleanup first, full-run subprocess regression second, public config docs third, roadmap metadata cleanup fourth.
- Tests to run with each slice: run `uv run pytest tests/package/test_import_boundaries.py` after import/test changes; run the narrow unit or integration target if a separate test file is touched; run docs/example checks only if executable snippets are edited.
- Decisions the executor must not revisit: no new runtime config behavior, no CLI, no `_copy_`, no plugin/remote resolvers, no persistence changes, no provenance/fingerprint schema changes, no strict YAML or override behavior changes beyond docs, and no pipeline dependency on config classes.
- Conditions that require stopping for the manager: direct full runner coverage cannot be added without importing `loom.config`; Pyright requires a concrete config import in pipeline source; roadmap cleanup conflicts with historical artifact policy; or docs correction requires deciding future-phase semantics not already accepted in the source plan.
- Expanded-path refinement notes: the refine pass should verify this plan names the exact test home, documentation anchors, and roadmap metadata rows after draft review, but should not add product-code recipes or broaden Phase 1.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on `codex/v1-post-contract-docs`.
- Final phase execution plan: pending expanded-path refinement.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- PR preparation: pending.
- Stack maintenance: pending.
- Remaining blockers: none at draft time.
