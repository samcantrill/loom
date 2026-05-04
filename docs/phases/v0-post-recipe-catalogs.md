# Phase 6 Execution Plan: Explicit Recipe Catalogs And Fresh Composition

## Metadata

- Status: in_progress
- Branch: `codex/v0-post-recipe-catalogs`
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-recipe-catalogs`
- Phase execution plan path: `docs/phases/v0-post-recipe-catalogs.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Source phase: `Phase 6 - Explicit Recipe Catalogs And Fresh Composition`
- PR: pending
- Stack predecessor: none
- Base branch: `develop` at `b93d82eeb506bdb6297c229c8a2a3a4d395917dd`
- Target branch: `develop`
- Serial human merge gate: active. The Phase 6 implementation PR must target
  `develop`, request review from `samcantrill` when GitHub allows it, and
  mention `@samcantrill` in the PR body or an immediate fallback PR comment.
  Codex must not approve or merge the PR. No successor phase may start until
  the Phase 6 PR is human-merged into `develop` and verified as `MERGED`.
- Merge eligibility: root serial phase. The PR is merge-eligible only after
  human review and human merge into `develop`; there is no stack predecessor
  to retarget from.
- Successor dependency notes: Phase 7 must not start while Phase 6 is only
  `pr_open` or `approved`; Phase 7 may start only after the Phase 6 PR is
  verified as `MERGED` into `develop` and this implementation plan records
  Phase 6 as `merged`.
- Plan quality gate: passed in
  `docs/implementation-plans/implementation-plan-v0-post.md`; no blocking
  plan-review findings remain.
- Plan quality gate loop budget: initial plan review used, automated plan
  refinement pass used, confirmation review used. Do not consume another
  plan-quality review loop without explicit manager instruction.
- Draft pass: completed by `loom_phase_planner` in commit `b824f6e`.
- Refine pass: completed by `loom_phase_planner` in this planning pass. This
  document is decision-complete for executor handoff.
- Phase implementation refinement budget: unused.
- PR review budget: unused.
- Setup limitations: local `develop` matched the manager-provided Phase 6 base
  commit `b93d82e`. No remote synchronization was attempted during planning
  because the assignment provided the updated base. Creating the slash-namespaced
  branch and worktree required approved Git worktree permissions after the
  sandbox could not create the branch ref directory.
- Blockers: none.

## Objective

Make reproducible recipe expansion depend on explicit `RecipeCatalog` instances
instead of process-global registration history. Keep global `register_recipe()`
as a Python convenience for scripts, notebooks, and interactive sessions, but
give future CLI and plugin code a fresh-catalog composition path that starts
from a caller-owned catalog and ignores earlier global registration.

## Full-Plan Context

Phase 1 is merged and established recursive immutability, shared strict schema
helpers, and no-extra/config-extra validation evidence. Phase 2 is merged and
established capability-oriented stores, run-scoped artifact stores,
`ArtifactAddress`, and the narrower stage-author `StageContext` facade. Phase 3
is merged and established explicit stage factories plus semantic fingerprint
policy v2. Phase 4 is merged and established runtime/resource/event/lock
foundations plus durable blocked status vocabulary. Phase 5 is merged and
established planner policy helpers and `PlanExplanation`.

Phase 6 resolves finding 7 from the implementation plan: global recipe registry
state. This phase may change config composition APIs and docs around recipe
catalog ownership, but it must not implement plugin discovery, CLI commands,
sweeps, run catalogs, bundles, runner lifecycle decomposition, remote stores, or
non-local executors.

## Stack Context

- Root or stacked phase: root serial phase.
- Current predecessor branch or PR: none; Phase 5 was human-merged into
  `develop`.
- Why this base branch is correct: serial human-merge-gate mode starts each
  phase from updated `develop`; Phase 5 merge notes say Phase 6 must continue
  from updated `develop`, and this worktree records `develop` at
  `b93d82eeb506bdb6297c229c8a2a3a4d395917dd`.
- Retarget/rebase plan after predecessor merge: not applicable because there is
  no unmerged predecessor and the PR target is already `develop`.
- Branch cleanup constraints: keep the phase branch and worktree until the
  human-owned PR has merged into `develop` and no successor branch depends on
  it.

## Source Phase Summary

- Goal: make reproducible config composition explicit and remove
  process-history surprises before CLI, plugins, and sweeps build on composition
  behavior.
- Required scope:
  - Make explicit `RecipeCatalog` construction the reproducible path in public
    docs and code used by run/config composition.
  - Keep process-global `register_recipe()` only as a Python convenience for
    scripts and interactive use.
  - Add a fresh-catalog composition path suitable for future CLI and plugin
    workflows so process-global registry history is ignored there.
  - Keep plugin discovery itself deferred.
  - Update `docs/structure.md`, `docs/features/config.md`, and
    `docs/features/plugins.md` for catalog ownership and global-state policy.
- Acceptance criteria:
  - Reproducible composition tests pass with explicit catalogs and do not
    observe prior global registration.
  - Interactive/script registration remains available where explicitly
    documented.
  - CLI/plugin-oriented composition helpers construct fresh explicit catalogs
    and do not depend on global registry history.

## Current Source And Harness Findings

- `src/loom/config/api.py` owns the public lazy config API, the process-global
  `__default_recipe_catalog`, `compose_config()`, `register_recipe()`, and
  `_get_default_recipe_catalog()`.
- `src/loom/config/compose.py` currently imports `_get_default_recipe_catalog`
  and falls back to it when `recipe_catalog is None`. That means callers using
  the lower-level composition module also observe global process history.
- `src/loom/config/recipes/catalog.py` already provides explicit
  `RecipeCatalog` construction, registration, lookup, ordered names/items, and
  target normalization. It intentionally does not deserialize callable recipes
  from plain data.
- `src/loom/config/recipes/expansion.py` already requires a `RecipeCatalog`
  when expanding `_recipe_` blocks. Expansion semantics can remain unchanged if
  composition hands it the right catalog.
- `tests/unit/loom/config/test_compose.py`,
  `tests/integration/config/test_compose_recipes.py`, and
  `tests/integration/pipeline/test_pipeline_config.py` already cover explicit
  catalog composition. They do not yet prove that a fresh composition path
  ignores globally registered recipes.
- `tests/unit/loom/test_deferred_stubs.py` currently verifies that
  `register_recipe()` populates the default catalog and remains a live
  convenience API.
- `tests/package/test_config_api.py` asserts the public config exports and the
  current `compose_config()` signature. Package tests must be updated if this
  phase adds new public symbols.
- `docs/features/config.md` still presents `register_recipe()` as the main
  recipe catalog example and contains older v0 text around stage target parsing.
  Phase 6 should update only the recipe catalog/global-state portions needed
  for this phase unless adjacent text would otherwise contradict the new public
  contract.
- `docs/features/plugins.md` already recommends explicit catalogs for future
  plugin loading and warns against hidden global mutation. Phase 6 should align
  this with the new fresh composition API without claiming entry-point loading
  exists now.

## Decision-Complete Contract

### Public Composition APIs

Keep the existing `compose_config()` public signature and behavior for Python
convenience:

```python
def compose_config(
    config_path: str | Path,
    overlays: list[str | Path] | tuple[str | Path, ...] = (),
    overrides: list[str] | tuple[str, ...] = (),
    recipe_catalog: RecipeCatalog | None = None,
) -> ComposedConfig: ...
```

If `recipe_catalog is None`, `compose_config()` may use the process-global
default catalog populated by `register_recipe()`. That is explicitly the
interactive/script convenience path, not the reproducible CLI/plugin path.

Add a public explicit-catalog helper:

```python
def compose_config_with_catalog(
    config_path: str | Path,
    *,
    recipe_catalog: RecipeCatalog,
    overlays: list[str | Path] | tuple[str | Path, ...] = (),
    overrides: list[str] | tuple[str, ...] = (),
) -> ComposedConfig: ...
```

`compose_config_with_catalog()` must require a concrete `RecipeCatalog`,
validate `overlays` and `overrides` the same way as `compose_config()`, and
must never call `_get_default_recipe_catalog()`. A future CLI, plugin loader, or
sweep driver can create a fresh `RecipeCatalog()`, load explicit project/plugin
recipes into it when those features exist, and call this helper without seeing
global process history.

Do not add a separate `compose_config_fresh()` helper in this phase. The fresh
path is:

```python
catalog = RecipeCatalog()
cfg = compose_config_with_catalog("experiment.yaml", recipe_catalog=catalog)
```

This keeps one explicit reproducible API while leaving the global convenience
API intact.

### Catalog Ownership

`RecipeCatalog()` remains the caller-owned mutable recipe registry. This phase
does not make catalogs immutable, serializable, thread-local, context-local, or
plugin-aware. The catalog records in `recipe_manifest` remain expansion
provenance, not a way to rehydrate recipe implementations.

`register_recipe()` remains a module-level convenience:

```python
register_recipe("demo", DemoRecipe)
compose_config("experiment.yaml")
```

Documentation must describe this as suitable for scripts, notebooks, and
interactive sessions only. Reproducible project code should prefer:

```python
catalog = RecipeCatalog()
catalog.register("demo", DemoRecipe)
compose_config_with_catalog("experiment.yaml", recipe_catalog=catalog)
```

### Fresh Composition Semantics

If a recipe named `demo` is registered globally and a caller uses
`compose_config_with_catalog(..., recipe_catalog=RecipeCatalog())`, a config
containing `_recipe_: demo` must fail with `UnknownRecipeError`. If the caller
registers `demo` on the explicit catalog, the same config must expand normally
and produce the existing recipe manifest shape.

Recipe expansion order, nested recipe behavior, argument interpolation, manifest
records, config fingerprint inputs, and config validation rules remain
unchanged.

## In-Scope Work

- Keep `RecipeCatalog()` as the explicit reproducible catalog construction API.
- Keep `register_recipe()` and the default global recipe catalog available only
  for the existing Python convenience path.
- Move global fallback out of `src/loom/config/compose.py` so the lower-level
  orchestration function receives a concrete `RecipeCatalog`.
- Add `compose_config_with_catalog()` in `src/loom/config/api.py`, export it
  from `loom.config`, and add it to `api.__all__`.
- Update lazy config package resolution in `src/loom/config/__init__.py` for
  the new optional public symbol without importing optional dependencies during
  `import loom` or `import loom.config`.
- Preserve `compose_config(..., recipe_catalog=None)` as the convenience path
  that uses globally registered recipes.
- Add tests where a recipe registered globally is not visible through
  `compose_config_with_catalog(..., recipe_catalog=RecipeCatalog())`.
- Add tests where an explicit catalog passed through `compose_config()` or
  `compose_config_with_catalog()` expands recipes exactly as before.
- Update docs that own the changed public contracts:
  `docs/structure.md`, `docs/features/config.md`, and
  `docs/features/plugins.md`.

## Planned Module Boundaries

- `src/loom/config/api.py`
  owns public API routing, global convenience state, optional argument
  validation for public helpers, and the new `compose_config_with_catalog()`
  helper.
- `src/loom/config/compose.py`
  owns composition orchestration after catalog selection. It should accept only
  a concrete `RecipeCatalog`; it must not import `_get_default_recipe_catalog`
  or otherwise read global registration state.
- `src/loom/config/recipes/catalog.py`
  remains the explicit catalog implementation. Only add methods here if tests
  prove they are directly needed for explicit catalog ownership; do not add
  plugin loading, serialization, cloning, context variables, or global helpers.
- `src/loom/config/recipes/expansion.py`
  remains the recipe expansion engine. It already receives a catalog explicitly;
  avoid changing expansion semantics.
- `src/loom/config/__init__.py`
  remains the lazy optional-dependency package facade. Add
  `compose_config_with_catalog` to the optional symbol set and resolver.

## Detailed Implementation Slices

### Slice 1: Characterize Global Leakage

- Add a focused unit test that resets `loom.config.api.__default_recipe_catalog`
  with `monkeypatch`, globally registers a recipe, and proves
  `compose_config()` still expands it when no explicit catalog is passed.
- Add a focused unit test that globally registers the same recipe but calls
  `compose_config_with_catalog(..., recipe_catalog=RecipeCatalog())` and gets
  `UnknownRecipeError`.
- Add a paired positive assertion where the explicit catalog registers the
  recipe and `compose_config_with_catalog()` expands it with the existing
  manifest fields.
- Keep tests independent of global cleanup order by resetting the private
  default catalog with `monkeypatch` inside each global-state test.

### Slice 2: Split Catalog Selection From Composition

- In `src/loom/config/compose.py`, change the internal composition function so
  `recipe_catalog` is required and validated as a `RecipeCatalog`.
- Remove `from .api import _get_default_recipe_catalog` from `compose.py`.
- Keep `overlays is None` and `overrides is None` validation either in both
  public wrappers or in a shared private normalizer in `api.py`; avoid letting
  a `None` sequence fail later with an incidental `TypeError`.
- Preserve all existing composition order:
  load base, load/merge overlays, parse/apply overrides, resolve recipe
  argument interpolation, expand recipes, resolve final interpolation, validate,
  redact, build provenance, build fingerprint, return `ComposedConfig`.

### Slice 3: Add Explicit Public Helper

- Implement `compose_config_with_catalog()` in `src/loom/config/api.py` with a
  keyword-only `recipe_catalog` parameter.
- Implement `compose_config()` as a convenience wrapper that chooses
  `recipe_catalog` if supplied, otherwise `_get_default_recipe_catalog()`, then
  delegates to the same lower-level composition function as
  `compose_config_with_catalog()`.
- Reject non-`RecipeCatalog` values with the existing `ConfigValidationError`
  message style. Keep the user-facing error stable enough for current tests,
  or update tests only when the message becomes more precise.
- Export `compose_config_with_catalog` through `src/loom/config/api.py`,
  `src/loom/config/__init__.py`, and package tests.

### Slice 4: Documentation Alignment

- Update `docs/features/config.md` recipe catalog and public API sections so
  explicit catalogs are the reproducible path and global registration is
  convenience-only.
- Update stale config doc prose that would directly contradict Phase 3 factory
  behavior only if touched nearby; do not perform a broad config docs cleanup.
- Update `docs/features/plugins.md` so future plugin examples populate a
  caller-owned `RecipeCatalog` and call `compose_config_with_catalog()`. Keep
  entry-point loading explicitly deferred.
- Update `docs/structure.md` so `api.py` owns the global convenience facade and
  `compose.py` owns explicit-catalog orchestration.

### Slice 5: Focused Validation

- Run focused unit/package/integration tests for config APIs and recipe
  composition before PR preparation.
- Run `make validate-pr` before opening/preparing the PR.
- Run `make test-summary` during PR preparation so package, unit, contract,
  integration, e2e, and config-extra evidence is available.

## Out-of-Scope Work

- No plugin discovery, entry-point loading implementation, plugin metadata
  validation, or plugin error policy.
- No CLI command implementation or CLI-specific config loading.
- No runner lifecycle decomposition, stage execution change, run-store change,
  event emission, lock integration, blocked-outcome persistence, or planner
  policy change.
- No recipe expansion semantic changes beyond catalog ownership.
- No run catalog, bundle, sweep, remote store, non-local executor, retry,
  timeout, cleanup, retention, or migration closeout work.
- No compatibility bridge that makes plugin import side effects populate the
  process-global recipe catalog.

## Assumptions

- Existing `compose_config()` behavior may remain the script/interactive
  convenience path as long as reproducible callers have a documented API that
  bypasses global state.
- Future CLI/plugin code should create a fresh `RecipeCatalog`, load explicit
  project or plugin recipes into it when those features exist, and pass that
  catalog into `compose_config_with_catalog()`.
- A fresh empty catalog should reject `_recipe_` blocks whose names exist only
  in the process-global catalog.
- Recipe implementations remain trusted project code; this phase does not add
  sandboxing or import isolation.

## Implementation Commit Guidance

- Commit 1: characterization tests for global convenience and explicit/fresh
  catalog isolation.
- Commit 2: API and composition routing changes, including package exports and
  import-boundary updates.
- Commit 3: integration coverage and documentation updates.
- Commit 4: validation-driven cleanup only if focused checks reveal issues.

This grouping is guidance, not a mandate. Keep commits coherent and avoid
mixing docs-only cleanup with API behavior changes when that would make review
harder.

## Suite-Level Test Obligations

- Package: update config API/export tests for any new public composition helper
  while preserving lazy optional-dependency behavior and no-extra import
  boundaries. `compose_config_with_catalog` must be lazy-resolved like
  `compose_config`, and `import loom` must remain safe without config extras.
- Unit: add tests for default global registration convenience, explicit/fresh
  catalog composition ignoring global state, invalid catalog validation, and any
  catalog helper added by this phase.
- Contract: no store, artifact, executor, stage, or planner contracts are
  intentionally changed. Existing contract suites must remain green; add
  contract tests only if implementation unexpectedly changes a public boundary.
- Integration: add or update config and pipeline integration tests proving
  explicit catalogs drive recipe expansion and fresh composition fails when a
  recipe is only globally registered.
- E2E: no new end-to-end workflow is expected because no CLI or runner behavior
  changes are in scope. Run the existing e2e suite through the PR validation
  gate; add e2e coverage only if implementation changes user-visible local-run
  behavior.
- Opt-in suites: config composition requires optional config dependencies.
  Preserve `test-no-extra` import behavior and config-extra validation evidence
  through `make validate-pr` and `make test-summary`.
- Narrow implementation checks:
  - `uv run pytest tests/unit/loom/config/test_compose.py`
  - `uv run pytest tests/integration/config/test_compose_recipes.py`
  - `uv run pytest tests/integration/pipeline/test_pipeline_config.py`
  - `uv run pytest tests/package/test_config_api.py`
  - `uv run pytest tests/package/test_import_boundaries.py`
  - `uv run pytest tests/unit/loom/test_deferred_stubs.py`
- PR preparation: run `make validate-pr` before opening/preparing the Phase 6
  PR and run `make test-summary` so the PR body can report package, unit,
  contract, integration, e2e, and config-extra evidence.

## Acceptance Checklist

- `RecipeCatalog()` is documented as the reproducible recipe registration
  path.
- `register_recipe()` remains available and documented as convenience-only.
- `compose_config_with_catalog()` receives a caller-owned explicit catalog and
  never reads process-global recipe registrations.
- `src/loom/config/compose.py` no longer imports or calls
  `_get_default_recipe_catalog()`.
- Tests prove global recipe registration does not leak into the fresh/explicit
  composition path.
- Existing recipe expansion manifest behavior and config fingerprints remain
  stable except for any deliberate test fixture changes around catalog source.
- Docs do not imply plugin entry-point discovery or CLI behavior is implemented
  in this phase.

## Design Impact

This phase narrows the reproducibility boundary around recipe expansion. Config
composition can still be ergonomic for Python scripts, but future command-line,
plugin, sweep, and worker entrypoints get a catalog-owned path that is stable
under long-lived processes and test-order variation.

## Future Compatibility

Future plugin discovery can populate explicit catalogs and pass them into
composition without relying on import side effects. Future CLI and sweep code
can compose many configs in one process without accidentally seeing recipes
registered by earlier operations.

## Alternatives Rejected

- Removing `register_recipe()` entirely: rejected because the implementation
  plan explicitly keeps it as a Python convenience for scripts and interactive
  use.
- Making plugin discovery populate the global catalog: rejected because this
  would preserve the hidden process-history problem this phase is meant to
  remove.
- Implementing plugin entry-point loading now: rejected because plugin
  discovery is a later roadmap phase and this phase only prepares explicit
  catalog ownership.

## Debt Introduced

- The process-global default catalog remains accepted debt for interactive
  convenience. Revisit if future tests, notebooks, or plugin workflows still
  observe process-history surprises after adopting the explicit/fresh path.

## Reviewability

Review should focus on API boundaries and tests around global state leakage.
The implementation should be small: public API routing, composition catalog
ownership, focused unit/integration tests, and docs. Diffs that implement
plugin discovery, CLI commands, runner lifecycle work, or recipe expansion
semantic changes should be treated as out of scope.
