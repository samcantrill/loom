# Phase 9 Execution Plan: Recipe Catalog And Expansion

## Metadata

- Status: refined phase execution plan
- Feature focus: Configuration
- PR title: `Configuration - Phase 9: Recipe Catalog And Expansion`
- Branch: `codex/config-recipes-catalog`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-recipes-catalog`
- Phase execution plan path: `docs/phases/config-recipes-catalog.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 9 - Recipe Catalog And Expansion
- Stack predecessor: none; Phases 1-8 are merged
- Base branch: `develop`
- Base commit: `4ed4f347834d1f3871fb5f65fef600c95b61e2c6`
- Target branch: `develop`
- Merge eligibility: root phase; eligible to merge into `develop` only after implementation, phase-scoped validation, PR preparation, and review pass against `develop`.
- Workflow path: expanded path
- Workflow path rationale: recipe ordering, explicit catalog behavior, artifact-safe recipe records, and resolver-dependent recipe shape failures affect durable composition order and future manifest/fingerprint behavior.
- Successor dependency notes: Phase 10 validation boundaries must see recipes already expanded into concrete plain config; Phases 12-14 depend on recipe records that preserve authored resolver expressions and artifact-safe output hashes without depending on resolver execution.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact; draft budget used.
- Refine pass: completed by `loom_phase_planner` in this artifact; refine budget used.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid; approved outside-sandbox `gh auth status` succeeded. `gh auth setup-git` and `git fetch origin` succeeded with approved access. Local `develop` and `origin/develop` both resolved to the assigned base commit. `git worktree add` required approved access because writing the phase branch ref was blocked by the sandbox.
- Blockers: none.

## Objective

Harden recipe composition so v1 uses explicit `RecipeCatalog` inputs for deterministic recipe lookup, treats recipes as file-defined behavior expanded before ordinary user value overrides, and records artifact-safe recipe facts without persisting resolver outputs or letting recipe output shape depend on resolver execution.

## Full-Plan Context

Phases 1-8 established config/pipeline boundaries, artifact skeletons, strict loading, merge and override primitives, source-aware overlays, recursive includes, user composition overrides, and runtime-only resolver security. Phase 9 must now fix recipe ordering and records before Phase 10 validation sees the expanded config, Phase 12 exposes public orchestration and inspection, and Phases 13-14 populate manifest, redaction, source records, and artifact-safe fingerprints. This phase must not implement CLI behavior, public inspection APIs, validation-boundary redesign, persistence, raw source snapshots, `_copy_`, or pipeline dependence on config.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-8 and the Phase 8 follow-up PR #35 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`; the implementation plan records Phases 1-8 as merged; local and fetched `origin/develop` both resolve to the assigned base commit.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after the Phase 9 PR is merged and no successor branch depends on `codex/config-recipes-catalog`.

## Source Phase Summary

- Goal: harden recipe expansion around explicit catalogs and artifact-safe behavior.
- Required scope: explicit `RecipeCatalog` composition paths; recipes as file-defined behavior; recipe expansion before ordinary user value overrides; artifact-safe recipe records; rejection of pre-expansion recipe argument override syntax; rejection of resolver-dependent recipe output shape.
- Required checkpoints: keep explicit catalog APIs deterministic; adjust compose ordering so user composition overrides run before recipes and ordinary value overrides run after recipes; preserve authored resolver expressions in recipe arguments and records; reject recipes or recipe arguments that require resolver outputs for output shape; keep recipe output plain mappings.
- Acceptance criteria: recipes expand before ordinary value overrides; ordinary overrides target expanded concrete paths; recipe records preserve unresolved resolver expressions as authored text; recipes that require resolver outputs for output shape fail.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/api.py` exposes `compose_config(...)`, `compose_config_with_catalog(...)`, `register_recipe(...)`, and a mutable process-global default catalog. `src/loom/config/compose.py` currently executes includes -> user composition overrides -> ordinary overrides -> recipe argument interpolation -> recipe expansion -> resolver scan/runtime interpolation -> validation/redaction/provenance/fingerprint. Phase 9 must move recipe expansion before ordinary overrides without disrupting include/user-composition ordering or Phase 8 runtime-only resolver handling. `src/loom/config/recipes/catalog.py` already provides explicit `RecipeCatalog` registration and lookup. `src/loom/config/recipes/expansion.py` currently resolves recipe argument interpolation before expansion and rejects resolver-style tokens; this needs review against the v1 requirement to preserve authored resolver expressions in records and fail when resolver values would be needed for recipe output shape. `src/loom/config/recipes/manifest.py` records path, name, target, arguments, expanded hash, expanded path, and Loom version using plain data. `src/loom/config/interpolation.py` provides Phase 8 no-execution resolver scanning and runtime-only `oc.env` handling that Phase 9 should reuse rather than duplicating resolver parsing.
- Existing tests or harness behavior: recipe unit coverage lives in `tests/unit/loom/config/recipes/test_catalog.py`, `tests/unit/loom/config/recipes/test_expansion.py`, and `tests/unit/loom/config/recipes/test_manifest.py`. Recipe contracts live in `tests/contracts/test_recipe_contract.py`; config artifact plain-data checks live in `tests/contracts/test_config_artifact_contract.py`; compose recipe integration lives in `tests/integration/config/test_compose_recipes.py`. `tests/integration/config/test_compose_config.py::test_public_compose_expands_recipes_and_nested_interpolation` currently encodes the old ordinary-before-recipe behavior by adding `+paths.cli=/cli` before the recipe consumes `${paths.cli}`; Phase 9 should intentionally update or replace that assertion rather than preserve the old ordering. Compose order coverage also touches `tests/integration/config/test_compose_overrides.py`, `tests/integration/config/test_compose_includes.py`, and `tests/integration/config/test_compose_resolvers.py`. Package/API coverage for public exports and import boundaries lives in `tests/package/test_config_api.py` and `tests/package/test_import_boundaries.py`.
- Import-boundary or dependency constraints: keep implementation inside `src/loom/config/` and config tests unless a package/API test needs adjustment. Do not import `loom.pipeline`, stores, CLI modules, plugin discovery, project packages, network clients, or add new runtime dependencies. Recipes remain trusted project code; this phase does not sandbox recipe execution.

## In-Scope Work

- Preserve and tighten explicit `RecipeCatalog` composition paths so `compose_config_with_catalog(...)` and explicit `recipe_catalog=` calls are the deterministic v1 path.
- Keep legacy/global `register_recipe(...)` and default-catalog compatibility API where it already exists. Do not remove or deprecate it in Phase 9 unless a truly blocking local constraint is discovered and recorded for the manager.
- Reorder compose internals so file-defined includes and user composition overrides complete first, recipe expansion runs next, and ordinary user value overrides apply only to the expanded concrete config.
- Reject ordinary overrides that try to address pre-expansion recipe arguments instead of concrete expanded paths; this should fall out of strict override application after expansion, but add explicit tests for the intended failure mode.
- Rework recipe argument handling so resolver-style expressions are preserved as authored text in artifact-safe recipe records and are not resolved for artifact records or output hashing.
- Add explicit structured failure for recipe blocks or recipe outputs that would require resolver execution to determine output shape. Prefer a recipe-domain `ConfigError` subclass or existing recipe error path with structured context if the implementation can do so without broad error refactoring.
- Ensure recipe manifest records remain plain data and artifact-safe: target identity, unresolved arguments, output hash of unresolved expanded mapping, path, expanded path, and Loom version. No resolved resolver values or raw source bytes should enter records.
- Keep nested recipe expansion support only as already implemented, with deterministic manifest ordering and plain mapping outputs.

## Out-of-Scope Work

- Ambient process-global recipe reliance as the recommended deterministic rebuildability path.
- New pre-expansion recipe argument override syntax.
- Sandboxing trusted recipe code or adding import allow-lists for recipe execution.
- CLI behavior, CLI-only override syntax, or CLI recipe commands.
- Pipeline dependency on config, manifests, recipe catalogs, or recipe records.
- `_copy_`, Hydra defaults lists, plugin/remote/global search include resolvers, custom resolver execution, raw source byte persistence, resolver-output persistence, public inspection APIs, or final manifest/source/fingerprint population.

## Assumptions

- Existing global recipe registration remains as a compatibility convenience unless the executor finds a truly blocking local constraint; do not remove public API in this phase.
- Recipes are trusted project code and may execute normal Python when explicitly registered, but v1 artifacts must not depend on resolver execution or resolved runtime values.
- Resolver-bearing recipe arguments are authored data for records and artifact hashes. They must not be resolved during recipe artifact handling. If the recipe output mapping shape cannot be produced without resolver execution, composition must fail before returning successful artifacts.
- Ordinary user overrides are already parsed before include/user-composition partitioning. The implementation may keep parsing early, but application of ordinary value overrides must occur after recipe expansion.
- Full public `ComposedConfig.unresolved`, `manifest`, `source_artifacts`, `fingerprint_records`, and inspection stage records are later-phase work. Phase 9 should not expose new public fields unless required to preserve an existing recipe contract.

## Scope Contract

Recipes remain a `loom.config` composition concern and must not become pipeline APIs. The public behavior changed in this phase is composition ordering and artifact-safe recipe record semantics: include expansion and user include swaps happen before recipe expansion; recipe expansion happens before ordinary overrides; ordinary overrides update or add concrete paths in the recipe-expanded config; pre-expansion recipe argument overrides are unsupported. Tests that encode ordinary-before-recipe behavior should be intentionally updated or replaced. Explicit catalogs are the deterministic path for v1 composition, while the default catalog remains compatibility API. Recipe records must be plain serializable and must preserve resolver-style expressions as authored text; hashes must be computed from artifact-safe unresolved recipe output, not from runtime-resolved resolver values. If resolver execution would be necessary to know recipe output mapping shape, fail with a recipe/config error before producing a misleading artifact record.

## Design Impact

- Maintainability: isolates the recipe ordering change inside composition orchestration and recipe helpers instead of spreading recipe logic into include, validation, pipeline, or artifact modules.
- Extensibility: leaves a later explicit recipe argument override language possible because v1 rejects ambiguous pre-expansion overrides rather than silently interpreting ordinary overrides as recipe inputs.
- Domain neutrality: recipes are named trusted config transformations over plain data with no model, dataset, stage, or project-schema assumptions.
- Source-tree boundaries: keeps work under `loom.config` and tests, reusing existing serialization, fingerprint, error, and resolver-scanning helpers without pipeline, store, CLI, plugin, remote IO, or project imports.

## Future Compatibility

- Phase 10 can validate only Loom-owned boundaries after recipe expansion, while project-owned recipe output remains plain data.
- Phase 12 can expose recipe expansion as an inspection stage using the records and order established here.
- Phase 13 can embed artifact-safe recipe records into provenance and manifest population without back-editing recipe manifest shape.
- Phase 14 can include recipe declarations, unresolved arguments, and unresolved output hashes in default artifact-safe fingerprints.
- Future CLI and sweeps can generate ordinary overrides that target concrete recipe-expanded paths through the same `compose_config` path.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep ordinary overrides before recipe expansion | Conflicts with v1 ordering and makes ordinary overrides able to mutate recipe arguments before expansion. |
| Add recipe argument override syntax now | Explicitly out of scope for v1 Phase 9 and would need a separate public design for ambiguity, provenance, and future CLI behavior. |
| Prefer the process-global default catalog for v1 deterministic composition | Mutable ambient registration is not rebuildable enough for artifact-safe records; explicit `RecipeCatalog` inputs are reviewable and testable. |
| Resolve resolver expressions before recipe expansion or hashing | Would leak runtime values into recipe behavior, records, and fingerprints by default. |
| Persist raw recipe source bytes or resolver outputs in recipe records | Violates accepted security-first artifact defaults and belongs to later source-artifact or opt-in persistence policy. |
| Sandbox recipe code | Recipes are trusted project code in v1, and sandboxing is explicitly out of scope. |
| Remove `register_recipe(...)` or the default catalog in Phase 9 | Existing compatibility API can remain while deterministic v1 paths prefer explicit catalogs. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Legacy global recipe registration remains available | Preserves existing public API compatibility while v1 documents explicit catalogs as deterministic path. | Revisit when a public deprecation or stricter v2 API is planned. |
| Detecting resolver-dependent recipe shape may be conservative | Trusted Python recipes are opaque; a safe v1 check may reject resolver-bearing arguments for shape-sensitive recipes rather than infer intent. | Revisit if real recipe workflows need a declared artifact-safe recipe contract or shape-stability annotation. |
| Recipe manifest remains narrower than the future composition manifest | Phase 13 owns full manifest/provenance population; Phase 9 should not freeze unrelated manifest fields early. | Revisit in Phase 13 when recipe records are embedded in composition manifest records. |

## Reviewability

- Expected PR size and shape: focused changes to compose ordering, recipe argument/manifest handling, recipe error behavior, and phase-scoped unit/contract/integration tests. No broad public API, CLI, pipeline, persistence, validation-boundary, manifest, source-artifact, or fingerprint redesign.
- Files and areas to inspect: likely `src/loom/config/compose.py`, `src/loom/config/recipes/expansion.py`, `src/loom/config/recipes/manifest.py`, `src/loom/config/recipes/catalog.py`, `src/loom/config/errors.py` or `src/loom/config/recipes/errors.py` if structured recipe errors are added, `tests/unit/loom/config/recipes/test_catalog.py`, `tests/unit/loom/config/recipes/test_expansion.py`, `tests/unit/loom/config/recipes/test_manifest.py`, `tests/contracts/test_recipe_contract.py`, `tests/contracts/test_config_artifact_contract.py` if recipe manifest artifact normalization changes, `tests/integration/config/test_compose_config.py`, `tests/integration/config/test_compose_recipes.py`, `tests/integration/config/test_compose_overrides.py`, `tests/integration/config/test_compose_resolvers.py`, and package/import-boundary tests if exports change.
- Scope-control checks: no CLI commands; no root package exports unless existing package API tests demand them; no pipeline, run-store, store, plugin, remote, or project imports; no `_copy_`; no public inspection or new `ComposedConfig` fields; no manifest/source-artifact/fingerprint population beyond current recipe manifest records; no resolved resolver values, environment values, raw source bytes, or non-plain objects in recipe records.

## Implementation Steps

1. Confirm explicit catalog behavior in public API tests and keep deterministic paths centered on `recipe_catalog=` / `compose_config_with_catalog(...)`; retain `register_recipe(...)` and default-catalog compatibility unless a blocking local constraint is documented.
2. Split parsed overrides in compose so include-composition overrides still apply before recipe expansion, while ordinary overrides are applied after recipe expansion against the concrete expanded config. Intentionally update tests that assume ordinary overrides feed recipe arguments.
3. Adjust recipe argument handling to avoid resolver execution for artifact records and preserve resolver-style expressions as authored strings in `RecipeManifestRecord.arguments`.
4. Harden recipe expansion and manifest hashing so expanded output is a plain mapping, nested recipe ordering remains deterministic, and output hashes are computed from unresolved artifact-safe recipe output.
5. Add or refine recipe-domain errors for unsupported pre-expansion argument override behavior and resolver-dependent output shape. Keep structured context plain and free of resolved resolver values.
6. Add focused unit, contract, and integration tests for explicit catalog use, expansion-before-ordinary-override ordering, pre-expansion argument override rejection, authored resolver-expression preservation, resolver-dependent shape failure, and artifact-safe manifest records.

## Test Plan

### Package Suite

- Status: required if public exports, signatures, lazy imports, or default catalog behavior change; otherwise deferred for targeted implementation and covered by final PR validation.
- Expected paths: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py`, possibly `tests/package/test_public_api.py` if exports change.
- Required assertions or deferral reason: if touched, prove `compose_config`, `compose_config_with_catalog`, `RecipeCatalog`, and `register_recipe` remain importable through existing lazy config API patterns without importing pipeline, stores, CLI, plugin discovery, project modules, network clients, or heavyweight optional dependencies eagerly. If no API/export changes are made, package suite can remain unchanged until `make validate-pr`.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/recipes/test_catalog.py`, `tests/unit/loom/config/recipes/test_expansion.py`, `tests/unit/loom/config/recipes/test_manifest.py`, and `tests/unit/loom/config/test_compose.py` if compose collaborator behavior is unit-tested there.
- Required assertions or deferral reason: explicit catalog lookup remains ordered and isolated from global registration; default-catalog registration remains compatible where existing public API tests cover it; recipe expansion preserves nested recipe manifest order; recipe records preserve resolver-style argument strings such as `${oc.env:KEY}` without resolving them; manifest output hashes are computed from unresolved plain output; non-mapping and non-plain outputs still fail; nested `_recipe_` in arguments remains rejected; resolver-dependent shape/output cases fail with a recipe/config error; ordinary override classification after recipe expansion is covered without adding recipe-argument override syntax.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_recipe_contract.py`, `tests/contracts/test_config_error_contract.py` if a structured resolver-dependent recipe error is added, and `tests/contracts/test_config_artifact_contract.py` if `CompositionManifest.recipe_manifest` or recipe record normalization changes.
- Required assertions or deferral reason: recipe manifest records remain plain serializable data with stable keys and artifact-safe values; structured recipe errors, if added, are `ConfigError` subclasses with plain context that includes config path, recipe name, directive, source or override details where available, and remediation without resolved resolver outputs or raw source bytes. Existing pipeline/store recipe manifest contracts must not require pipeline to import `loom.config`.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_config.py`, `tests/integration/config/test_compose_recipes.py`, `tests/integration/config/test_compose_overrides.py`, and `tests/integration/config/test_compose_resolvers.py`; additions to `tests/integration/config/test_compose_includes.py` are acceptable for include plus recipe order.
- Required assertions or deferral reason: public `compose_config` with an explicit catalog expands recipes before ordinary overrides; strict update overrides can target recipe-produced paths; pre-expansion recipe argument paths fail as missing after expansion unless they also happen to be concrete output paths; current tests that use `+paths.cli` as a recipe argument input are intentionally updated or replaced; user include swaps still happen before recipe expansion; recipe records preserve authored resolver expressions and do not contain resolved environment values; resolver-dependent recipe shape fails before producing a successful composed config or misleading artifact record; global registration does not affect explicit catalog composition, while default-catalog compatibility remains covered where existing API expects it.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 9 does not complete public v1 inspection APIs, final artifact manifest population, artifact-safe fingerprints, CLI behavior, run-store writes, validation-boundary redesign, or full v1 documentation. Representative end-to-end public composition coverage belongs to Phase 16 after orchestration and artifact phases are complete.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: raw source snapshots, secret-aware runtime fingerprints, resolved-value persistence, recipe sandboxing, plugin/remote recipe discovery, and CLI behavior are out of scope.

## Risks

- Moving ordinary overrides after recipe expansion will break tests that intentionally or accidentally encode v0 pre-expansion recipe argument mutation, including `tests/integration/config/test_compose_config.py::test_public_compose_expands_recipes_and_nested_interpolation`; Phase 9 should update those tests to the new contract rather than preserving compatibility.
- Resolver-style values are safe to preserve as strings, but recipe implementations are opaque trusted Python code. Tests should focus on the public contract: no resolver execution, no resolved values in records, and explicit failure for unsupported resolver-dependent shape.
- Recipe manifest hashes can accidentally include runtime-resolved values if hashing happens after interpolation. Keep hashing on unresolved plain output before runtime resolution.
- Sharing resolver scanning with recipe helpers can regress Phase 8 error contracts if unsupported resolver names are raised as interpolation errors instead of recipe-shape errors in recipe-specific contexts.
- Nested recipe expansion can make manifest ordering easy to disturb. Preserve the current deterministic parent-before-nested order unless a test proves a different order is already public.
- Broad validation or public orchestration cleanup is tempting here because compose order is touched; keep those changes for Phases 10 and 12.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/recipes/test_catalog.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/recipes/test_expansion.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/recipes/test_manifest.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_compose.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_recipe_contract.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_error_contract.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_artifact_contract.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_config.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_recipes.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_overrides.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_resolvers.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_config_api.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr
UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: start with compose ordering and tests proving ordinary overrides target recipe-expanded paths, including intentional updates to old ordinary-before-recipe integration tests; then adjust resolver-preserving recipe argument and manifest behavior; then add resolver-dependent recipe shape failure handling; finish with explicit catalog/global isolation tests and artifact-safe record assertions.
- Tests to run with each slice: recipe expansion and manifest unit tests after recipe helper changes; compose unit/integration tests after order changes; recipe/error contract tests after adding structured failures; resolver integration tests after touching resolver-expression handling; package/import-boundary tests if public exports or imports change.
- Decisions the executor must not revisit: recipes expand before ordinary overrides; tests encoding the old order should change; no recipe argument override syntax; explicit catalogs are the deterministic v1 path; `register_recipe(...)` and default catalog compatibility stay unless truly blocked; no resolver execution for recipe records or output shape; no resolved resolver outputs or raw source bytes in records; no recipe sandboxing; no CLI, pipeline, plugin, remote, `_copy_`, public inspection, or artifact/fingerprint population beyond existing recipe manifest behavior.
- Conditions that require stopping for the manager: implementing Phase 9 appears to require a new public recipe argument override language, removing existing public API compatibility, exposing Phase 12 public inspection fields early, executing resolvers to run recipes, importing pipeline/store/CLI/plugin/project modules, adding dependencies, persisting resolver outputs or raw source bytes, or making validation-boundary decisions reserved for Phase 10.
- Expanded-path refinement notes: completed. The refined contract records the current compose order, makes the recipe-before-ordinary-override change explicit, calls out old-order tests that should be intentionally updated, preserves default catalog compatibility, tightens resolver-bearing argument behavior, and updates validation commands to use the config extra and shared UV cache.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed as `plan: add phase execution plan`.
- Final phase execution plan: completed by `loom_phase_planner`; committed as `plan: refine phase execution plan`.
- Implementation summary:
  - Reordered compose flow so include expansion and composition overrides are applied first, then recipe arguments are resolved and recipe expansion runs, and only then ordinary overrides are applied to the expanded concrete config.
  - Restored resolver-safe argument resolution behavior for recipe args in `resolve_recipe_argument_interpolation` so `${...}` interpolation still resolves non-resolver tokens while preserving resolver-style `${...:...}` tokens in stored recipe arguments.
  - Added output-shape validation in recipe expansion to reject resolver-shaped mapping keys in expanded recipe output via `InvalidRecipeOutputError` before manifest generation.
  - Added/updated phase-scoped unit, contract, and integration tests for compose ordering, ordinary-overrides targeting expanded paths, resolver expression preservation in manifest arguments, and resolver-shaped recipe output key failure behavior.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/recipes/test_expansion.py tests/integration/config/test_compose_config.py tests/integration/config/test_compose_recipes.py tests/contracts/test_recipe_contract.py tests/integration/config/test_compose_overrides.py tests/integration/config/test_compose_resolvers.py tests/unit/loom/config/test_compose.py tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_error_contract.py tests/package/test_config_api.py tests/package/test_import_boundaries.py tests/unit/loom/config/recipes/test_manifest.py tests/unit/loom/config/recipes/test_catalog.py`
    - Result: 95 passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr`
    - Result: passed (ruff/pyright + default + config-extra harness + build).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary`
    - Result: wrote `build/test-summary.md`; summary passed across package/unit/contract/integration/e2e/config-extra.
- Refinement summary: recorded current compose order and intentional test updates for the Phase 9 ordering change; tightened explicit catalog/default catalog compatibility guidance; clarified resolver-bearing recipe argument and resolver-dependent shape behavior; updated targeted and final validation commands to use `UV_CACHE_DIR=/tmp/loom_uv_cache` and `uv run --extra config` where applicable.
- PR preparation:
  - Not started. No PR was opened or prepared in this phase by request.
- Stack maintenance:
  - No phase stack actions executed yet in this worktree phase pass.
- Remaining blockers:
  - None blocking; no further implementation changes required to satisfy the finalized phase scope.
