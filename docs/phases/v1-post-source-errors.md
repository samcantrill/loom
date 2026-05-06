# Phase 3 Execution Plan: Source Authorship And Structured Error Completion

## Metadata

- Status: draft phase execution plan
- Feature focus: V1 Post Configuration
- PR title: `V1 Post Configuration - Phase 3: Source Authorship And Structured Errors`
- Branch: `codex/v1-post-source-errors`
- Worktree: `/home/samcantrill/work/loom-worktrees/v1-post-source-errors`
- Phase execution plan path: `docs/phases/v1-post-source-errors.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1-post.md`
- Source phase: Phase 3. Source Authorship And Structured Error Completion
- Stack predecessor: none; Phase 1 PR #44 and Phase 2 PR #46 have merged into `develop`, with metadata PRs #45 and #47 also merged.
- Base branch: `develop` / `origin/develop` at `fdb64c8` (`docs: record v1-post phase 2 merged (#47)`)
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after review/checks because target is `develop`
- Workflow path: expanded path
- Successor dependency notes: Phase 4 should start from this branch only after this phase PR is opened or prepared, validated, and recorded as `pr_open`; no current successor depends on this draft.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v1-post.md`; no blockers remain.
- Plan quality gate loop budget: initial `loom_plan_reviewer` review used, automated plan refinement pass used, confirmation review used.
- Draft pass: completed by `loom_phase_planner`
- Refine pass: pending; expanded path selected because this phase affects structured errors and source authorship across composition and instantiation behavior.
- Setup limitations: `gh auth status` initially reported an invalid token inside the sandbox, then succeeded with approved network access; `gh auth setup-git` succeeded with approved access. `git fetch origin` and `git worktree add` required approved access after sandbox attempts could not write git metadata.
- Blockers: none

## Objective

Make strict composition and instantiation failures consistently source-aware, path-aware, and machine-readable while preserving secret redaction and avoiding broad public error hierarchy churn.

## Full-Plan Context

Phases 1 and 2 have merged the import-boundary/docs cleanup and strict authoring changes. This phase completes the diagnostic and authorship layer needed before Phase 4 changes artifact-safe ordering and provenance schema defaults. Later phases still own artifact-before-resolver ordering, provenance schema-version-2 writes, default resolved persistence removal, run-store composition manifest APIs, recipe residual-risk documentation, final docs, CLI, `_copy_`, plugin or remote resolvers, and default resolved persistence.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 1, Phase 2, and their metadata PRs are merged to `develop`.
- Why this base branch is correct: the manager recorded `develop` and `origin/develop` at `fdb64c8` as the continuation base after Phase 2 metadata landed; there is no unmerged stack predecessor.
- Retarget/rebase plan after predecessor merge: not applicable; the PR target remains `develop`.
- Branch cleanup constraints: after merge, delete `codex/v1-post-source-errors` only when no successor phase branch depends on it.

## Source Phase Summary

- Goal: make strict composition errors consistently source-aware, path-aware, and machine-readable without leaking secret values.
- Required scope: carry authorship through ordinary overrides; attribute interpolation and unsupported resolver failures to the authored value source; expose final-value authorship metadata at path/fact level; add structured context for merge, ordinary override, include, recipe, target, interpolation, provenance, and artifact failures where useful; add remediation and active include-stack details for nested include failures.
- Required checkpoints: ordinary override values have authorship after recipe expansion; interpolation diagnostics use the final value's author when known; structured error payloads round-trip; errors and metadata never persist raw secret-like override values.
- Acceptance criteria: public composition APIs expose richer diagnostics without requiring callers to learn a new error hierarchy, and suite evidence covers package, unit, contract, integration, e2e deferral, and opt-in redaction obligations.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/errors.py` has `ConfigErrorContext` and `_ConfigError`, but many subclasses still inherit directly from `ConfigError`. `src/loom/config/source_maps.py` tracks base/overlay source maps before includes and ordinary overrides. `src/loom/config/compose.py` applies ordinary overrides after recipe expansion, then resolves interpolation with only base-source context. `src/loom/config/includes.py` already creates structured include resolution/expansion errors and include-stack frames for cycles. `src/loom/config/overrides.py`, `merge.py`, `interpolation.py`, `recipes/expansion.py`, `instantiate/targets.py`, `instantiate/recursive.py`, `provenance.py`, and `artifacts.py` still have useful failures with mixed structured context.
- Existing tests or harness behavior: error contract coverage lives in `tests/contracts/test_config_error_contract.py`; unit error/source-map coverage lives in `tests/unit/loom/config/test_config_errors.py`, `test_source_maps.py`, `test_merge.py`, `test_overrides.py`, `test_interpolation.py`, `test_config_provenance.py`, `test_config_artifacts.py`, recipe tests, and instantiate tests. Public API regressions live under `tests/integration/config/`, especially compose config, includes, overrides, resolvers, recipes, target handoff, provenance, source snapshots, and redaction matrix.
- Import-boundary or dependency constraints: changes must stay inside `loom.config` and tests unless package export tests are required. `loom.pipeline` and stores must remain out of scope. Config tests depend on optional config dependencies, so opt-in/config-extra evidence is required.

## In-Scope Work

- Carry metadata-only authorship for ordinary value overrides through the final composed config, including override path, operation, order, and redacted source facts without storing raw secret-like values.
- Preserve and extend file-authored value source metadata from base, overlays, include expansion, local include customizations, and recipe expansion enough to attribute final values and diagnostics.
- Attribute interpolation and unsupported resolver failures to the final value's authored source when available, including overlay-authored values, ordinary overrides, and include/user-composition outputs.
- Expose final-value authorship in provenance or composition manifest metadata as path/fact records that omit actual values and raw secret-like override strings.
- Convert merge and ordinary override failures to `ConfigError` subclasses with `ConfigErrorContext`, or add equivalent structured context to existing subclasses without unnecessary new public classes.
- Add remediation strings to include/composition errors where there is a concrete user action, such as fixing an include target, using explicit relative targets for new include sites, adding `_replace_: true`, or using `oc.env` instead of unsupported resolvers.
- Include active include-stack context for nested include failures, not only detected cycles.
- Extend structured coverage to recipe argument interpolation, recipe expansion, target import, target instantiation, provenance construction, and artifact serialization failures when source/path/stage facts would help callers debug.

## Out-of-Scope Work

- New public error hierarchy churn beyond what is needed for structured context.
- Persisting raw secret values or raw secret-like override strings in error details, provenance metadata, manifest metadata, snapshots, or tests.
- Phase 4 artifact-safe ordering, provenance schema-version-2 writes, resolved fingerprint removal, or artifact-safe resolver ordering changes.
- Phase 5 pipeline persistence, run-store composition manifest APIs, and runner behavior.
- Phase 6 recipe residual-risk coverage and accepted debt wording.
- Duplicate-key and override scalar semantics already completed in Phase 2.
- CLI, `_copy_` implementation, plugin or remote resolvers, broadened resolver allow-list, default resolved persistence, schema registries, or pipeline/store import-boundary changes.

## Assumptions

- Existing `ConfigErrorContext` can carry most new context through `details` plus existing fields; adding top-level fields should be a last resort and must include contract coverage.
- It is acceptable for final-value authorship metadata to be additive under existing provenance or manifest `metadata` rather than a Phase 4 top-level schema change.
- Override-origin records may use a metadata-specific source kind such as `override` even though `ConfigSource` remains limited to file sources.
- Recipe output attribution can point to the `_recipe_` block and recipe manifest record rather than to internal recipe implementation lines.
- Include-stack context should be metadata about include frames, authored targets, source paths, and resolved paths; it must not include raw included file text.
- Secret-like detection should reuse the existing redaction policy helpers rather than adding a new secret-classification system.

## Scope Contract

The public behavior change is diagnostic and metadata additive. Existing exception classes should remain import-compatible; where a class currently lacks `to_dict()`, the preferred change is to make it carry `ConfigErrorContext` through the existing config error base behavior rather than renaming it. `to_dict()` payloads must stay plain-data, round-trip where contract tests already require it, and avoid raw source bytes, raw secret values, and raw secret-like override strings.

Final-value authorship metadata must be path-indexed facts, not a resolved-value snapshot. A record may include config path, source kind, source order, source path, content digest or source artifact reference, composition stage, override order/path/operation, recipe name/path, or include-site path. It must not include the authored value itself. This phase may add metadata keys under provenance or manifest metadata, but must not perform Phase 4's provenance schema-version-2 transition or move artifact creation before runtime interpolation.

Structured context should identify the most useful source and path available at the failure point. When no source map entry exists, use a stable fallback context that explains the missing source metadata instead of raising an unrelated unstructured error. Errors that wrap underlying exceptions should preserve exception chaining.

## Design Impact

- Maintainability: centralizes diagnostic facts in the existing config error/context model and value-authorship metadata instead of spreading ad hoc strings across composition stages.
- Extensibility: metadata-only authorship records can later feed Phase 4 artifact-safe schema changes and Phase 5 persistence without storing values or binding pipeline code to config classes.
- Domain neutrality: diagnostics should describe config paths, sources, directives, and composition stages only; no research-domain assumptions should appear in errors or tests.
- Source-tree boundaries: work stays in `loom.config` and config tests, with package tests only if public exports are touched.

## Future Compatibility

This phase should make Phase 4 safer by ensuring the authored source of each final value is already known before artifact-safe ordering changes are attempted. Structured contexts should be stable enough for downstream callers to inspect by code/path/source facts, but additive enough that later provenance schema work can move or normalize metadata without changing exception class names. Redaction choices should anticipate future CLI and persistence surfaces by treating override raw strings as potentially sensitive whenever the path or value is secret-like.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add a broad new public config error hierarchy | The source plan explicitly limits hierarchy churn, and existing subclasses can carry structured context. |
| Persist final resolved values with authorship metadata | This would leak values and conflict with Phase 4 artifact-safe and Phase 5 persistence goals. |
| Attribute all interpolation failures to the base config | Current behavior loses overlay and override authorship, which is the core gap this phase closes. |
| Record only include cycles in include-stack details | Nested include failures need the active stack even when the failure is missing target, invalid root, or unsupported target form. |
| Defer recipe and target structured errors entirely | The source phase requires structured coverage where the context helps callers, and these failures are common public composition/instantiation debugging points. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| None expected. | This phase should add diagnostic metadata without knowingly deferring required behavior. | If implementation must leave a failure path unstructured because source context is unavailable, record the exact path and revisit during Phase 7 hardening. |

## Reviewability

- Expected PR size and shape: medium config-only PR with focused helper changes for authorship tracking and structured errors, plus targeted unit/contract/integration tests. Avoid broad rewrites of compose orchestration.
- Files and areas to inspect: `src/loom/config/errors.py`, `source_maps.py`, `compose.py`, `overrides.py`, `merge.py`, `includes.py`, `interpolation.py`, `recipes/expansion.py`, `instantiate/targets.py`, `instantiate/recursive.py`, `provenance.py`, `artifacts.py`, `api.py`, and package exports only if touched. Tests should focus on `tests/contracts/test_config_error_contract.py`, `tests/unit/loom/config/`, and `tests/integration/config/`.
- Scope-control checks: diff must not include Phase 4 provenance schema changes, resolved-fingerprint removal, artifact ordering changes, pipeline/store changes, CLI behavior, `_copy_`, plugin/remote resolvers, or new override semantics.

## Implementation Steps

1. Define or extend an internal value-authorship representation and update source-map flow so base, overlay, include, local customization, recipe output, include override, and ordinary override authorship can be queried by final config path without storing values.
2. Add metadata-only final-value authorship records to provenance or manifest metadata, reusing redaction helpers for override-origin facts and keeping records path/fact based.
3. Convert merge and ordinary override failure paths to structured `ConfigErrorContext` payloads with config path, operation, expected/actual facts, remediation when actionable, and no secret values.
4. Thread authorship lookup into interpolation/resolver handling so unsupported resolver and interpolation failures use the authored value source when available and include safe expression/path facts.
5. Extend include diagnostics with remediation and active include-stack details for nested non-cycle failures while preserving existing cycle context.
6. Add structured wrapping for useful recipe, target import/instantiation, provenance, and artifact serialization failures, then fill contract, unit, integration, and opt-in redaction coverage.

## Test Plan

### Package Suite

- Status: required if public exports or import behavior are touched; otherwise deferred.
- Expected paths: `tests/package/test_config_api.py` and possibly import-boundary tests if `loom.config` exports new error/context symbols.
- Required assertions or deferral reason: if any error class, context class, or authorship record becomes public through `loom.config`, assert stable package import/export behavior. If all new helpers remain internal and existing public exports stay unchanged, record the deferral in PR evidence.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_source_maps.py`, `test_overrides.py`, `test_merge.py`, `test_interpolation.py`, `test_config_errors.py`, `test_config_provenance.py`, `test_config_artifacts.py`, `recipes/test_expansion.py`, and `instantiate/test_targets.py` or `instantiate/test_recursive.py`.
- Required assertions or deferral reason: authorship propagation through base/overlay/included/local customization/recipe/ordinary override paths; structured error construction for merge and ordinary override failures; interpolation attribution from authored source lookup; include-stack detail construction; provenance/manifest authorship metadata excludes values; target/recipe/artifact/provenance structured wrappers preserve exception chaining and context.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_config_error_contract.py` and, if metadata shape is asserted as public artifact contract, `tests/contracts/test_config_artifact_contract.py` or `test_config_composition_inspection_contract.py`.
- Required assertions or deferral reason: `ConfigErrorContext.to_dict()` and `from_dict()` shape for new details remain plain-data and round-trip; structured error `to_dict()` includes code/source/path/remediation/details; no raw source bytes or raw secret-like values appear. If final-value authorship metadata is added to manifest/provenance metadata, assert the stable path/fact shape and value omission.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_config.py`, `test_compose_overrides.py`, `test_compose_includes.py`, `test_compose_resolvers.py`, `test_compose_recipes.py`, `test_compose_target_handoff.py`, `test_compose_provenance.py`, `test_compose_source_snapshots.py`, `test_compose_redaction_public_matrix.py`, and focused new files if clearer.
- Required assertions or deferral reason: public `compose_config(...)` failures for merge, override, include, nested include, unsupported resolver, interpolation, recipe, target import/instantiation, provenance, and artifact/manifest serialization include structured source/path/stage context. Overlay-authored and override-authored resolver failures must attribute to the overlay or override path rather than the base source. Provenance or manifest metadata must expose final-value authorship facts without exposing values.

### E2E Suite

- Status: deferred unless implementation changes public runner behavior.
- Expected paths: none expected for this phase.
- Required assertions or deferral reason: the phase is confined to config composition and instantiation diagnostics. If the executor touches runner behavior or pipeline persistence to surface structured errors, stop for the manager because that enters Phase 5 scope.

### Opt-In Suites

- Status: required.
- Markers affected: `optional_dependency` and config-extra rows.
- Required assertions or deferral reason: add redaction tests proving secret-like override values and raw override strings are not exposed in error details, provenance metadata, manifest metadata, authorship records, or serialized error payloads. Targeted development should run config-extra marked tests for changed config unit and integration paths; PR preparation must report `make test-summary` config-extra evidence or explain why unavailable.

## Risks

- Authorship tracking can expand into a broad compose rewrite; keep the implementation metadata-focused and avoid changing merge semantics.
- Structured contexts can accidentally include raw override strings such as `+auth.token=...`; secret-like paths and values must be redacted before entering details or metadata.
- Adding top-level fields to `ConfigErrorContext` could break contract expectations; prefer `details` unless a stable field is clearly necessary and tested.
- Include-stack propagation for nested failures must avoid retaining stack frames after exceptions or success paths.
- Recipe output authorship may be approximate because trusted Python recipes can transform values internally; attribute to recipe block/record, not internal implementation choices.
- Provenance/artifact failure tests may require constructing invalid objects directly; keep them focused on useful caller context and avoid Phase 4 schema decisions.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run --locked --group dev --extra config pytest -m optional_dependency tests/unit/loom/config/test_config_errors.py tests/unit/loom/config/test_source_maps.py tests/unit/loom/config/test_merge.py tests/unit/loom/config/test_overrides.py tests/unit/loom/config/test_interpolation.py tests/unit/loom/config/test_config_provenance.py tests/unit/loom/config/test_config_artifacts.py
UV_CACHE_DIR=/tmp/uv-cache uv run --locked --group dev --extra config pytest -m optional_dependency tests/contracts/test_config_error_contract.py tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_composition_inspection_contract.py
UV_CACHE_DIR=/tmp/uv-cache uv run --locked --group dev --extra config pytest -m optional_dependency tests/integration/config/test_compose_config.py tests/integration/config/test_compose_overrides.py tests/integration/config/test_compose_includes.py tests/integration/config/test_compose_resolvers.py tests/integration/config/test_compose_recipes.py tests/integration/config/test_compose_target_handoff.py tests/integration/config/test_compose_provenance.py tests/integration/config/test_compose_redaction_public_matrix.py
make test-config-extra
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: value authorship representation and metadata first; merge/ordinary override structured errors second; interpolation/resolver attribution third; include-stack/remediation diagnostics fourth; recipe/target/provenance/artifact structured wrappers fifth; redaction and contract coverage throughout.
- Tests to run with each slice: run the related unit file after each helper change, then contract error tests after changing payload shape, then targeted integration config tests after public compose behavior changes. Run `make test-config-extra` before handing off to PR preparation.
- Decisions the executor must not revisit: no Phase 4 artifact-safe ordering or provenance schema-version-2 work, no Phase 5 runner/store persistence, no new resolver allow-list entries, no `_copy_`, no CLI, no new override path/value semantics, and no broad public error hierarchy redesign.
- Conditions that require stopping for the manager: source authorship cannot be carried without changing public artifact/provenance schema top-level fields; a secret-like value must be stored to satisfy a test; interpolation attribution requires changing resolver execution order; package exports need a breaking change; or meaningful target/recipe structured context requires pipeline or CLI changes.
- Expanded-path refinement notes: pending. The refine pass should check that authorship metadata shape is sufficiently stable for implementation, suite obligations remain explicit, and no Phase 4/5 scope has leaked into this plan.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on `codex/v1-post-source-errors`.
- Final phase execution plan: pending expanded-path refinement.
- Implementation summary:
- Implementation validation:
- Refinement summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers:
