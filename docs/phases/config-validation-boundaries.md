# Phase 10 Execution Plan: Loom Validation Boundaries

## Metadata

- Status: merged
- Feature focus: Configuration
- PR title: `Configuration - Phase 10: Loom Validation Boundaries`
- Branch: `codex/config-validation-boundaries`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-validation-boundaries`
- Phase execution plan path: `docs/phases/config-validation-boundaries.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 10 - Loom Validation Boundaries
- Stack predecessor: none; Phases 1-9 are merged.
- Base branch: `develop`
- Base commit: `80c1efba3918052a1673e962ecc023d2516852da`
- Target branch: `develop`
- Merge eligibility: root phase; eligible to merge into `develop` only after implementation, phase-scoped validation, pre-submit blocker gate, PR preparation/submission, and passing review/CI against `develop`.
- Workflow path: expanded path
- Workflow path rationale: validation boundaries affect public `compose_config` behavior, domain neutrality, structured error contracts, and future public orchestration.
- Successor dependency notes: Phase 11 instantiation must continue treating `_target_` as runtime construction only. Phase 12 public orchestration must inherit generic project-config pass-through rather than reintroducing top-level pipeline validation.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact; draft budget used.
- Refine pass: completed by `loom_phase_planner` in this artifact; refine budget used.
- Phase implementation refinement budget: used by `loom_phase_refiner` on 2026-05-05; this was the single allowed implementation refinement pass.
- Pre-submit/PR review budget: unused. The revised workflow requires a pre-submit blocker gate before PR submission; if that gate reviews the implementation diff, PR body, suite evidence, scope boundary, and known review risks, it consumes the Phase 10 PR-review budget unless the submitted diff changes afterward.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid; approved outside-sandbox `gh auth status` succeeded. `gh auth setup-git` and `git fetch origin` succeeded with approved access. Local `develop`, `origin/develop`, and `HEAD` resolved to the assigned base commit. Initial sandboxed `git worktree add` could not create the branch ref; approved `git worktree add` created the branch and worktree successfully.
- Blockers: none.

## Objective

Narrow configuration validation so generic `compose_config(...)` composes trusted project-owned mappings without Loom claiming schema ownership, while still rejecting reserved Loom schema-authoring directives and validating only explicit Loom-owned envelopes, directive blocks, recipe contracts, and artifact record contracts with source-aware structured errors.

## Full-Plan Context

Phases 1-9 established config/pipeline boundaries, artifact skeletons, strict loading, merge and override primitives, source-authored overlays, recursive includes, user composition overrides, resolver security, and recipe expansion. Phase 10 fixes the validation ownership boundary before Phase 11 tightens instantiation and Phase 12 exposes the public composition/inspection order. This phase must preserve accepted v1 decisions: `loom.config` remains persistence-free, `loom.pipeline` must not depend on `loom.config`, `_copy_` remains unsupported, resolver outputs and raw source bytes are not persisted by default, v1 stays Python-API-only, and plugin/remote/global search include resolvers remain out of scope.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-9 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`, the implementation plan records Phase 9 merged, and local/fetched `develop` matches the assigned base commit.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after the Phase 10 PR is merged and no successor branch depends on `codex/config-validation-boundaries`.

## Source Phase Summary

- Goal: validate only Loom-owned boundaries and preserve project-owned pass-through data.
- Required scope: explicit Loom-owned envelope/contract validation only when such an envelope or artifact record is present; removal, narrowing, or replacement of generic top-level `name` plus `pipeline` validation from public `compose_config`; project/stage config pass-through; rejection of YAML `_schema_`, project schema registries, and automatic `_target_` schema inference; structured validation errors with source context.
- Required checkpoints: generic project configs compose without top-level `name`, `pipeline`, or `schema_version`; unknown keys fail only inside documented Loom-owned boundaries; project-owned mappings pass through unless they contain reserved Loom directive keys; exact authored `_schema_` fails as an unsupported schema-authoring directive; `_target_` does not trigger composition-time schema validation.
- Acceptance criteria: the above behavior is covered by phase-scoped unit/integration/contract tests and final PR validation.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/compose.py` currently performs include expansion, user composition overrides, recipe argument interpolation, recipe expansion, ordinary override application, resolver scanning/runtime interpolation, and then calls `validate_top_level_fields(resolved)` before redaction, provenance, and fingerprints. That top-level validator is the only validation gate in the public compose path today. `src/loom/config/validation.py` currently requires top-level `name`, requires top-level `pipeline` to be a mapping, defaults `schema_version` to `1`, and has stale `validate_no_recipe_keys` messaging. `src/loom/config/load.py` already rejects `_copy_` with structured source context during authored loading; `_schema_` currently has no code or test coverage. Phase 10 should add source-aware `_schema_` rejection for base, overlays, and included files without persisting raw source bytes. `src/loom/config/errors.py` has structured `ConfigErrorContext`, but `ConfigValidationError` is currently unstructured. Artifact contracts in `src/loom/config/artifacts.py` already reject unknown fields in `from_dict` and validate their own schema/version fields.
- Existing tests or harness behavior: `tests/unit/loom/config/test_validation.py` currently encodes the obsolete unconditional top-level validation and should be intentionally updated to boundary-focused tests. Public compose tests under `tests/integration/config/` mostly author `name` and `pipeline` because old validation required them; Phase 10 needs explicit pass-through integration coverage for generic configs without those keys, `_target_` inertness, and `_schema_` rejection in base, overlay, and included-file cases. Structured error contracts live in `tests/contracts/test_config_error_contract.py`; package/import-boundary coverage lives in `tests/package/test_import_boundaries.py`.
- Import-boundary or dependency constraints: keep implementation inside `src/loom/config/` and config tests unless package tests need updates. Do not import `loom.pipeline`, stores, CLI modules, plugin discovery, project packages, network clients, or add runtime dependencies. `loom.pipeline.specs` owns explicit pipeline/stage/artifact validation today; Phase 10 must not pull those validators into generic config composition. Any config-local Loom-owned validation retained or added in this phase must be opt-in/narrow and must not make `loom.config` depend on pipeline schemas.

## In-Scope Work

- Replace or narrow `validate_top_level_fields(...)` so public `compose_config(...)` no longer requires top-level `name`, top-level `pipeline`, or top-level `schema_version` for generic project-owned configs.
- Preserve project-owned mappings and scalar/list values after composition, interpolation, redaction, provenance, recipe expansion, and fingerprinting. Generic composition should not inject `schema_version` into project configs merely because Loom artifact records have schema versions.
- Add recursive authored-config rejection for the exact key `_schema_` with a structured, source-aware unsupported schema-authoring error. This must apply to authored YAML from base, overlays, and included files before project schema import or registry behavior could be inferred, and it must not require raw source persistence.
- Keep `_target_` as pass-through composition data. Composition must not import targets, inspect constructors, infer schemas, or reject unknown project fields because `_target_` is present.
- Validate unknown keys only inside explicit Loom-owned boundaries already owned by config phases: composition directives (`_include_`, `_replace_`, `_copy_`), recipe blocks, override operation records, instantiation directive blocks when `instantiate(...)` is called, config-local Loom-owned validation helpers when explicitly invoked, and artifact record `from_dict` contracts.
- If an explicit Loom pipeline envelope validation helper is retained or introduced in `loom.config`, keep it config-local and opt-in. Do not call pipeline parsers from `compose_config(...)`, do not import `loom.pipeline`, and do not make generic config composition depend on pipeline schema parsing.
- Add or refine `ConfigValidationError` structured context for validation-boundary failures, including config path, source kind/order/path when available, directive or boundary name, expected/actual shape, and remediation.
- Update tests that assumed top-level `name`/`pipeline` were mandatory so they now assert the v1 ownership boundary.

## Out-of-Scope Work

- Project-specific validation systems, YAML schema registries, project schema imports, or user-defined schema extension APIs.
- CLI UX, CLI commands, CLI-only schema behavior, or CLI-specific error presentation.
- Pipeline dependence on config, config dependence on pipeline parsing, or using `PipelineSpec.from_config(...)` inside public `compose_config(...)`.
- `_copy_` support, `_target_` strict import changes, `_inject_` behavior, and instantiation recursion changes.
- Persistence of resolver outputs or raw source bytes, public inspection APIs, final manifest/source/fingerprint population, plugin/remote/global search include resolvers, or run-store writes.

## Assumptions

- The existing public `compose_config(...)` is the generic composition entrypoint. It should compose trusted project configs whether or not they describe a Loom pipeline.
- Existing `ComposedConfig.resolved`, `redacted`, `provenance`, `recipe_manifest`, and `fingerprint` fields remain the public return shape until Phase 12 adds v1 fields.
- Top-level `schema_version` can remain ordinary project data in generic configs. Loom artifact record schema versions remain validated by their artifact contract classes, not by generic config validation.
- The exact key `_schema_` is reserved everywhere in authored YAML for v1, even inside project-owned mappings, because the plan explicitly rejects schema-authoring directives.
- Existing recipe, include, override, artifact, and instantiate validators own their own reserved directive semantics. Phase 10 should coordinate with them, not duplicate all directive validation.
- If `_schema_` is discovered through final composed-tree scanning because that is the smallest local implementation, the implementation must still carry source context from the authored source maps for base/overlay values and include expansion context for included values. A final-tree-only error with no authored source context is not sufficient.

## Scope Contract

Generic `compose_config(...)` must be domain-neutral pass-through composition plus Loom-owned directive/artifact validation. A config like `model: {...}` or `stages: {...}` must compose without `name`, `pipeline`, or `schema_version`, and the returned `resolved`/`redacted` config must not gain a Loom schema key solely from generic validation. Unknown keys are accepted in project-owned mappings. Unknown-key failures are valid only in explicit Loom-owned contracts: include/replace/copy directive shapes, recipe blocks, override operation records, instantiation directive blocks during `instantiate(...)`, explicit config-local opt-in pipeline-envelope validation if kept, and artifact record `from_dict` schemas. `_schema_` is the one reserved schema-authoring directive that must fail anywhere it is authored. `_target_` remains inert during composition and must not trigger imports, constructor signature checks, or project schema inference. Top-level `pipeline` is just a project key in generic composition unless an explicit Loom-owned validation path is invoked outside the public compose default.

## Design Impact

- Maintainability: removes the misleading single top-level validation gate and replaces it with owned-boundary validation that aligns with the staged composition model.
- Extensibility: leaves room for a deliberate future project schema-extension API because v1 fails `_schema_` explicitly instead of accepting ad hoc registries or automatic target inference.
- Domain neutrality: lets projects compose model, dataset, experiment, and stage payloads as plain data without Loom pipeline schema ownership.
- Source-tree boundaries: keeps validation in `loom.config` and artifact classes, with no imports from pipeline, stores, CLI, plugin discovery, remote IO, or project modules.

## Future Compatibility

- Phase 11 can tighten `_target_` and `_inject_` only in instantiation paths without back-editing generic compose behavior.
- Phase 12 can expose `inspect_config_composition(...)` with a validation stage that records which Loom-owned boundaries were checked and which project mappings passed through.
- Phases 13-14 can include validation-boundary facts in provenance/manifests/fingerprints without treating project config keys as Loom schemas.
- Future CLI and sweeps can wrap `compose_config(...)` for arbitrary project configs without requiring pipeline-shaped roots.
- A later project schema API can be designed explicitly because v1 rejects `_schema_` and schema registries now.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep unconditional top-level `name` plus `pipeline` validation | Conflicts with v1 domain neutrality and prevents generic project configs from using public composition. |
| Keep injecting `schema_version: 1` into generic composed configs | Mutates project-owned pass-through data and confuses Loom artifact schema versions with project payload schema. |
| Import `loom.pipeline` and reuse `PipelineSpec` validation in `compose_config(...)` | Violates the config/pipeline boundary and makes generic composition depend on pipeline semantics. |
| Add YAML `_schema_` or a project schema registry in v1 | Explicitly rejected by the implementation plan; it would define a public extension API before ownership and import rules are designed. |
| Infer schema from `_target_` constructors during composition | Would import trusted project code too early, couple composition to instantiation, and blur Phase 11's runtime boundary. |
| Reject unknown keys globally | Would make Loom own arbitrary project configs and block domain-neutral pass-through behavior. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Explicit Loom pipeline-envelope validation may remain narrow or opt-in only | Preserves generic composition and avoids importing pipeline parsers in config. | Phase 12 public inspection or a future CLI needs a documented pipeline-config validation API. |
| Project schema validation is entirely external to v1 | Keeps validation ownership clear and avoids premature schema registries. | A future roadmap explicitly designs project schema extension points. |
| Existing integration fixtures may still use `pipeline` as a conventional key | Rewriting every fixture is unnecessary for Phase 10 if behavior is covered by dedicated generic pass-through tests. | Later docs/e2e hardening needs clearer domain-neutral examples. |

## Reviewability

- Expected PR size and shape: focused validation helper changes, compose wiring to remove/narrow unconditional top-level validation, structured validation error context, `_schema_` rejection, and phase-scoped tests. No public orchestration API, artifact population, pipeline schema import, CLI, persistence, or instantiation behavior changes.
- Files and areas to inspect: likely `src/loom/config/compose.py`, `src/loom/config/validation.py`, `src/loom/config/load.py` if `_schema_` rejection belongs with authored directive scanning, `src/loom/config/includes.py` if included-file `_schema_` source context must be detected during include loading/expansion, `src/loom/config/errors.py` if `ConfigValidationError` gains structured context, `tests/unit/loom/config/test_validation.py`, `tests/unit/loom/config/test_config_errors.py`, `tests/contracts/test_config_error_contract.py`, `tests/integration/config/test_compose_config.py`, `tests/integration/config/test_compose_includes.py`, `tests/integration/config/test_compose_overrides.py`, `tests/integration/config/test_compose_recipes.py`, `tests/integration/config/test_compose_resolvers.py`, `tests/package/test_import_boundaries.py`, and artifact contract tests only if touched.
- Scope-control checks: no pipeline imports from `loom.config`; no project imports; no automatic `_target_` import or constructor inspection; no schema registry; no CLI commands; no `_copy_`; no raw-source or resolver-output persistence; no public `ComposedConfig` v1 field additions; no manifest/source/fingerprint population beyond existing skeleton behavior.

## Implementation Steps

1. Replace the unconditional top-level validator with boundary-aware validation that returns the composed project payload unchanged for generic configs.
2. Update compose wiring so redaction, provenance, and fingerprints operate on the boundary-validated project payload without adding `schema_version` to generic configs.
3. Add structured `_schema_` reserved-directive rejection for authored YAML across base, overlays, and included files, preserving source path and config path context without persisting raw source bytes.
4. Add focused validation helpers for any explicit Loom-owned config boundaries that already exist in `loom.config`, keeping them opt-in or internally scoped and avoiding `loom.pipeline` imports.
5. Refactor validation tests away from required top-level `name`/`pipeline` and add project pass-through, `_target_` inertness, unknown-key scoping, `_schema_` failure, and structured context coverage.
6. Run targeted package/unit/contract/integration checks and fix only Phase 10 regressions.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_config_api.py` if exports or signatures change.
- Required assertions or deferral reason: prove `loom.config` still does not import `loom.pipeline`, stores, execution, CLI, plugin discovery, project modules, network clients, or heavyweight optional dependencies eagerly. If `ConfigValidationError` export behavior changes, package API tests must show it follows existing config error patterns. No root exports are expected.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_validation.py`, `tests/unit/loom/config/test_config_errors.py`, and `tests/unit/loom/config/test_compose.py` if compose collaborator behavior is unit-tested there.
- Required assertions or deferral reason: generic mappings without `name`, `pipeline`, or `schema_version` validate/pass through unchanged; top-level `schema_version` is not injected into generic project configs; unknown keys are accepted in project-owned mappings; unknown keys fail only in explicit Loom-owned boundary helpers; `_schema_` fails anywhere authored with a validation/schema-authoring error; `_target_` mappings are left as data during validation and do not import or inspect targets; `ConfigValidationError` structured context is plain-data serializable and includes source/config path where available. Existing tests that require `name`/`pipeline` or assert schema-version defaulting should be intentionally rewritten rather than preserved.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_config_error_contract.py`; `tests/contracts/test_config_artifact_contract.py` only if artifact contract validation is touched.
- Required assertions or deferral reason: structured validation errors serialize context with code, source kind/order/path, config path, directive or boundary name, expected/actual shape, remediation, and plain details without raw source bytes or resolved resolver values. Artifact record schemas must continue rejecting unknown fields and invalid schema versions through their existing contract classes; generic compose validation must not duplicate or weaken those contracts.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_config.py`, `tests/integration/config/test_compose_includes.py`, `tests/integration/config/test_compose_overrides.py`, `tests/integration/config/test_compose_recipes.py`, and `tests/integration/config/test_compose_resolvers.py`.
- Required assertions or deferral reason: public `compose_config(...)` composes domain-neutral project configs without top-level `name`, `pipeline`, or `schema_version`; includes, overlays, user composition overrides, recipes, ordinary overrides, resolver scanning/runtime interpolation, redaction, provenance, recipe manifest, and fingerprints still work for generic keys; project-owned unknown keys pass through; `_schema_` in base, overlay, or included file fails with source-aware context; `_target_` nodes remain dictionaries in composed output and are not used for schema inference. At least one integration test should use no `pipeline` key at all, and at least one should use `_target_` under a project-owned mapping that would fail if composition tried to import or infer schema.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 10 does not complete public v1 inspection APIs, final manifest/source/fingerprint population, CLI behavior, run-store writes, or docs/e2e hardening. Representative end-to-end public v1 config trees belong to Phase 16 after orchestration and artifact phases are complete.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: project schema registries, raw source snapshots, secret-aware runtime fingerprints, resolved-value persistence, plugin/remote resolvers, and CLI behavior are out of scope.

## Risks

- Removing `schema_version` injection changes resolved/redacted/fingerprint output for existing tests that relied on v0 top-level validation defaults. Update those tests only where they encode obsolete validation ownership.
- `_schema_` rejection can be implemented too late if it only checks the final composed tree. It must still identify authored source context from base, overlays, and included files.
- Reusing pipeline spec validators would be tempting for Loom-owned envelopes, but it would violate import boundaries and make generic config composition pipeline-shaped.
- Treating `_target_` as a globally reserved validation key during composition would break project pass-through and Phase 11 separation. Only instantiation owns `_target_` validation.
- Structured error context can leak authored secret-like strings. Tests should assert plain context and no resolved resolver outputs or raw source bytes; full redaction policy population remains later-phase work.
- The pre-submit blocker gate may find scope drift if validation changes touch public compose orchestration too broadly. Such blockers must be resolved before PR submission or the phase must be marked blocked; do not submit a PR expecting GitHub review to rediscover known local blockers.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_validation.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_config_errors.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_compose.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_error_contract.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_artifact_contract.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_config.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_includes.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_overrides.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_recipes.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_resolvers.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_config_api.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr
UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: start by replacing the top-level validator and updating unit tests; adjust compose to keep the composed project payload unchanged through redaction/provenance/fingerprints; add `_schema_` authored-source rejection and structured context; update compose integration tests for generic pass-through and `_target_` inertness; then run package/import-boundary checks.
- Tests to run with each slice: validation unit tests after helper changes; config error contract tests after structured context changes; compose integration tests after wiring changes; package import-boundary tests after any validation import changes.
- Decisions the executor must not revisit: generic `compose_config` is domain-neutral; no required top-level `name`/`pipeline`; no `schema_version` injection for generic project configs; `_schema_` is unsupported; `_target_` does not imply composition-time schema inference; no project schema registry; no pipeline imports; no CLI, persistence, plugin/remote resolver, `_copy_`, public inspection, or artifact/fingerprint population work.
- Conditions that require stopping for the manager: satisfying acceptance criteria appears to require importing `loom.pipeline` from config, adding a project schema API, changing public `ComposedConfig` fields early, implementing Phase 11 instantiation behavior, persisting resolver outputs/raw source bytes, or weakening existing structured include/recipe/override contracts.
- Expanded-path refinement notes: completed. The refined plan incorporates the current compose order, confirms `validate_top_level_fields(...)` is the only public compose validation gate today, requires source-aware `_schema_` rejection for base/overlay/included files, keeps `loom.pipeline.specs` ownership out of `loom.config`, and records the revised pre-submit blocker gate without consuming implementation or PR-review budgets.

## Refinement And Review Budget Status

- Phase implementation refinement: used by `loom_phase_refiner` on 2026-05-05; no further automated implementation refinement pass remains.
- Pre-submit blocker gate: used by `loom_phase_reviewer` on 2026-05-05; no
  blockers found for the unchanged diff.
- PR review: consumed by the pre-submit blocker gate for the current diff,
  draft PR body, suite evidence, scope boundary, and known review risks. Run a
  post-submit PR review only if the submitted diff changes.

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed as `plan: add phase execution plan`.
- Final phase execution plan: completed by `loom_phase_planner`; committed as `plan: refine phase execution plan`.
- Implementation summary:
  - Removed implicit top-level `name`/`pipeline`/schema defaulting from `validate_top_level_fields(...)`; public composition now treats top-level mappings as pass-through project payload by default.
  - Reworked `ConfigValidationError` to reuse structured-context plumbing (`_ConfigError`) so validation failures can carry `ConfigErrorContext`.
  - Added load-time `_schema_` rejection in `load.py` alongside existing `_copy_` checks, producing source-aware `ConfigLoadError` context for base, overlay, and included file boundaries.
  - Updated composition-related tests to cover domain-neutral inputs (`compose_config` without `name`/`pipeline`), `_schema_` rejection in base/overlay/included YAML, and project-scoped `_target_` inertness.
  - Updated validation-contract coverage to verify structured context for `ConfigValidationError`.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_validation.py tests/unit/loom/config/test_config_errors.py tests/unit/loom/config/test_load.py tests/contracts/test_config_error_contract.py tests/integration/config/test_compose_config.py tests/integration/config/test_compose_includes.py` → `46 passed`.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_overrides.py tests/integration/config/test_compose_recipes.py tests/integration/config/test_compose_resolvers.py tests/package/test_import_boundaries.py tests/package/test_config_api.py` → `38 passed`.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` → passed (`ruff`, `pyright`, all default tests, build).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` → full evidence written to `build/test-summary.md` with all suites passing.
- Implementation refinement pass:
  - `loom_phase_refiner` performed the single allowed expanded-path implementation refinement pass on 2026-05-05.
  - Diff inspection found no production blocker: public `compose_config(...)` no longer requires top-level `name`, `pipeline`, or `schema_version`; generic payloads remain pass-through; `_schema_` rejection is source-aware for base, overlay, and included file loads; `_target_` remains inert during composition; no `loom.pipeline` import or future-phase behavior is introduced; structured validation context remains plain data and does not include raw source text or resolved resolver values.
  - Added focused integration coverage that generic, non-pipeline payloads feed redaction, provenance resolved fingerprints, and public config fingerprints without injecting `schema_version`.
  - Refinement validation:
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_config.py` → `10 passed`.
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_validation.py tests/unit/loom/config/test_config_errors.py tests/unit/loom/config/test_load.py tests/contracts/test_config_error_contract.py tests/integration/config/test_compose_config.py tests/integration/config/test_compose_includes.py` → `47 passed`.
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_overrides.py tests/integration/config/test_compose_recipes.py tests/integration/config/test_compose_resolvers.py tests/package/test_import_boundaries.py tests/package/test_config_api.py` → `38 passed`.
    - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` → passed (`ruff`, `pyright`, default tests, config-extra tests, build).
    - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` → passed; `build/test-summary.md` records package `36 passed, 1 skipped`, unit `354 passed, 1 skipped`, contract `28 passed, 1 skipped`, integration `9 passed, 5 skipped`, e2e `5 passed`, config-extra `253 passed, 432 deselected`.
- Refinement summary: expanded-path refine pass incorporated manager and architecture findings about current compose order, obsolete top-level validation, `_schema_` coverage gaps, config/pipeline validation ownership, required generic pass-through integration coverage, and the revised pre-submit blocker gate.
- Assumptions:
  - The `_schema_` directive is unsupported in v1 authored YAML; compose must reject it before any schema interpretation or import.
  - Generic compose payloads should remain unvalidated except for explicitly owned boundaries already implemented by existing include/override/recipe/validation helpers.
- Blockers:
  - None.
- PR preparation:
- PR facts:
  - Draft pass: completed by `loom_pr_preparer` on 2026-05-05.
  - Refine pass: completed by `loom_pr_preparer` on 2026-05-05. The PR body
    was checked against the phase plan, implementation diff, acceptance
    criteria, validation evidence, scope boundaries, assumptions, risks, and
    recorded pre-submit blocker gate; no public PR-body correction was needed.
  - PR body artifact: `docs/phases/config-validation-boundaries-pr-body.md`.
  - Intended PR title: `Configuration - Phase 10: Loom Validation Boundaries`.
  - Head branch: `codex/config-validation-boundaries`.
  - Target branch: `develop`.
  - Stack predecessor: none; this is a root phase PR.
  - Merge eligibility: root phase targeting `develop`; eligible only after
    GitHub CI and allowed review/merge checks pass. Do not approve or merge
    during PR preparation.
  - PR submission: opened as https://github.com/samcantrill/loom/pull/37.
  - PR verification: `gh pr view 37 --json baseRefName,headRefName,state,url`
    returned `baseRefName=develop`,
    `headRefName=codex/config-validation-boundaries`, `state=OPEN`, and
    `url=https://github.com/samcantrill/loom/pull/37`.
  - PR CI: GitHub check `checks` passed on 2026-05-05T13:17:05Z.
  - PR merge: PR #37 merged into `develop` at 2026-05-05T13:18:49Z with merge
    commit `66ef93b71e831d658942479b6e6e12aabe624423`.
- PR validation summary:
  - Targeted Phase 10 refinement group: `47 passed`.
  - Remaining targeted group: `38 passed`.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed; suite evidence
    in `build/test-summary.md` records package `36 passed, 1 skipped`, unit
    `354 passed, 1 skipped`, contract `28 passed, 1 skipped`, integration
    `9 passed, 5 skipped`, e2e `5 passed`, config-extra
    `253 passed, 432 deselected`.
- Pre-submit blocker gate:
  - Status: passed before PR submission.
  - Required review scope: final diff, PR body draft, suite evidence, phase
    scope boundary, and known review risks.
  - Reviewer: `loom_phase_reviewer`.
  - Findings: none. The reviewer found no blocking correctness, scope,
    import-boundary, test-evidence, or PR-body accuracy issues.
  - Evidence checked: branch `codex/config-validation-boundaries` uses merge
    base `80c1efb` against `develop`; `validation.py` removes required
    top-level `name`/`pipeline`/`schema_version` validation; `load.py` rejects
    authored `_schema_` and `_copy_` with structured source context;
    `ConfigValidationError` carries structured context; no `loom.pipeline`
    imports, CLI/public inspection APIs, persistence, `_copy_` support, schema
    registries, raw source persistence, resolver-output persistence,
    plugin/remote behavior, or Phase 11 instantiation behavior leaked in.
  - Budget note: this pre-submit gate consumes the Phase 10 PR-review budget
    for the implementation diff, draft PR body, suite evidence, scope boundary,
    and known review risks. A post-submit PR review should run only if the
    implementation or PR-body scope changes; PR-preparation metadata recorded
    here does not change implementation scope.
- GitHub/auth notes:
  - Sandboxed `gh auth status` reported the stored token as invalid; approved
    outside-sandbox `gh auth status` succeeded for account `samcantrill`.
  - `gh auth setup-git` and `git ls-remote --heads origin develop` succeeded
    before push; `origin/develop` resolved to
    `80c1efba3918052a1673e962ecc023d2516852da`.
  - `git push -u origin codex/config-validation-boundaries` succeeded before
    PR creation.
  - After the PR body artifact changed from "PR not opened yet" to "PR
    submitted", `gh pr edit 37 --body-file ...` failed with an unrelated
    GitHub CLI GraphQL `repository.pullRequest.projectCards` deprecation error.
    The PR body was updated successfully with `gh api --method PATCH
    repos/{owner}/{repo}/pulls/37 -F
    body=@docs/phases/config-validation-boundaries-pr-body.md`.
- Stack maintenance:
  - Root PR; no stack predecessor and no retarget/rebase action required before
    submission.
  - No successor phase branch depended on `codex/config-validation-boundaries`
    when PR #37 merged.
  - `gh pr merge 37 --squash --delete-branch` merged the PR, but local branch
    deletion failed because the branch was still attached to
    `/home/samcantrill/work/loom-worktrees/config-validation-boundaries`.
    Worktree and branch cleanup are safe after this metadata update.
