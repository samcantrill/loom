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
- Draft pass: completed by `loom_phase_planner` in this planning pass.
- Refine pass: pending. This draft records phase scope and intended execution
  boundaries; the refinement pass must make this document decision-complete
  before executor handoff.
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

## In-Scope Work

- Keep `RecipeCatalog()` as the explicit reproducible catalog construction API.
- Keep `register_recipe()` and the default global recipe catalog available only
  for the existing Python convenience path.
- Remove global fallback from the lower-level composition implementation so
  shared composition orchestration receives a concrete `RecipeCatalog`.
- Add a public fresh/explicit composition helper for future CLI and plugin
  callers. The helper must require or create a caller-owned `RecipeCatalog` and
  must not read `_get_default_recipe_catalog()`.
- Keep `compose_config(..., recipe_catalog=None)` available as the
  convenience path that uses globally registered recipes, unless refinement
  identifies a smaller compatible API shape.
- Add tests where a recipe registered globally is not visible through the
  fresh/explicit composition path.
- Update docs that own the changed public contracts:
  `docs/structure.md`, `docs/features/config.md`, and
  `docs/features/plugins.md`.

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
  catalog into composition.
- A fresh empty catalog should reject `_recipe_` blocks whose names exist only
  in the process-global catalog.
- Recipe implementations remain trusted project code; this phase does not add
  sandboxing or import isolation.

## Suite-Level Test Obligations

- Package: update config API/export tests for any new public composition helper
  while preserving lazy optional-dependency behavior and no-extra import
  boundaries.
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
- PR preparation: run `make validate-pr` before opening/preparing the Phase 6
  PR and run `make test-summary` so the PR body can report package, unit,
  contract, integration, e2e, and config-extra evidence.

## Acceptance Checklist

- `RecipeCatalog()` is documented as the reproducible recipe registration
  path.
- `register_recipe()` remains available and documented as convenience-only.
- A CLI/plugin-suitable composition path creates or receives a fresh explicit
  catalog and never reads process-global recipe registrations.
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

