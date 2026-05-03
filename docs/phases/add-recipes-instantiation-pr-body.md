## Phase

- Phase: `Phase 5 - Recipes And Instantiation`
- Branch: `codex/add-recipes-instantiation`
- Target: `develop`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-recipes-instantiation`
- Plan: `docs/implementation-plans/implementation-plan-v0.md`
- Expanded phase plan: `docs/phases/add-recipes-instantiation.md`

## Summary

Implements the trusted config recipe and object-instantiation mechanisms for
Phase 5. This adds explicit recipe catalogs, typed and structural recipe
contracts, recursive `_recipe_` expansion with deterministic manifest records,
recipe-aware config provenance/fingerprints, target import helpers, and an
explicit `instantiate()` API for recursive `_target_` construction.

Composition remains side-effect-free: `_target_` blocks stay plain data during
`compose_config()`, recipe expansion writes no files, and later pipeline
parsing, stores, runners, plugin discovery, and stage construction policy remain
out of scope.

## Acceptance Criteria

- [x] Recipe registration, lookup, duplicate detection, replacement, and
  unknown-recipe failures work through explicit `RecipeCatalog` instances and
  the public default `register_recipe()` path.
- [x] Nested recipes expand deterministically and emit manifest records with
  path, recipe name, target, arguments, expanded hash, expanded path, and loom
  version.
- [x] Recipe argument pre-resolution can reference base, overlay, and override
  values, while recipe output participates in the final interpolation pass.
- [x] Target imports support documented dotted and colon forms with path-aware
  errors.
- [x] Recursive instantiation handles mappings, sequences, `_args_`,
  `_partial_=true`, and `_inject_` runtime dependencies.
- [x] Reserved `_target_`, `_args_`, `_partial_`, `_inject_`, and `_recipe_`
  misuse fails loudly in recipe and instantiation contexts.
- [x] Trusted config behavior is scoped to v0; no sandbox, allow-list,
  entry-point discovery, plugin loading, pipeline parsing, stores, runners, or
  domain recipes/stages are implemented.

## Implementation Notes

Recipe code is isolated under `src/loom/config/recipes/` and exposes
`ConfigRecipe`, `Recipe`, `RecipeCatalog`, deterministic catalog iteration,
recipe expansion, and manifest helpers. `compose_config()` now resolves only
recipe arguments before expansion, expands recipes through an explicit or
default catalog, performs final interpolation, validates/redacts, records the
manifest count, and includes recipe manifest records in the top-level config
fingerprint.

Instantiation code is isolated under `src/loom/config/instantiate/` and exposes
`import_target` plus the recursive construction implementation used by the
public `loom.config.instantiate()` API. Runtime injection values are trusted
in-process objects and are not serialized, redacted, manifested, or
fingerprinted.

The package-level `loom.config.instantiate` callable is preserved even after
the same-named subpackage is imported, so the public API remains stable across
import order.

## Tests And Validation

```text
command: make validate-pr
result: passed after rerunning with approved access to the existing uv cache outside the workspace; Ruff passed, Pyright reported 0 errors, default pytest passed with 221 tests, and uv build produced source and wheel distributions
```

```text
command: make test-summary
result: passed after rerunning with approved access to the existing uv cache outside the workspace; wrote build/test-summary.md with package, unit, contract, and integration suites passing; e2e not present
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 0.79s | `uv run pytest tests/package -m "not slow and not slurm and not network and not optional_dependency"` |
| unit | passed | 0.72s | `uv run pytest tests/unit -m "not slow and not slurm and not network and not optional_dependency"` |
| contract | passed | 0.38s | `uv run pytest tests/contracts -m "not slow and not slurm and not network and not optional_dependency"` |
| integration | passed | 0.47s | `uv run pytest tests/integration -m "not slow and not slurm and not network and not optional_dependency"` |
| e2e | not present | 0.00s | `uv run pytest tests/e2e -m "not slow and not slurm and not network and not optional_dependency"` |

Package collected 14 tests, unit collected 189 tests, contract collected 9
tests, and integration collected 9 tests.

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

## Budget Status

- Phase implementation refinement: used by the single bounded refiner pass in
  commit `f88d16a`.
- PR review before this PR: unused.

## Risks / Follow-Ups

- The public default recipe registry remains a v0 convenience; explicit
  catalogs are preferred for deterministic tests and future plugin loading.
- Recipe expansion returns mappings only; static sequence fan-out remains
  deferred until a later phase defines splicing, generated names, and graph
  provenance.
- Target imports remain trusted project-code imports with no sandbox or
  allow-list mode in v0.
- Generic `instantiate()` is available for explicit object graphs, but Phase 6
  and Phase 9 still own pipeline parsing and stage construction policy.
- Runtime injection values are intentionally excluded from resolved config,
  recipe manifests, provenance, and fingerprints.

## PR Creation Status

PR opened successfully:

```text
command: git push -u origin codex/add-recipes-instantiation
result: pushed new branch and set upstream to origin/codex/add-recipes-instantiation
```

```text
command: gh pr create --base develop --head codex/add-recipes-instantiation --title "Phase 5: Recipes And Instantiation" --body-file docs/phases/add-recipes-instantiation-pr-body.md
result: https://github.com/samcantrill/loom/pull/8
```

```text
command: gh pr view 8 --json baseRefName,headRefName,state,url
result: {"baseRefName":"develop","headRefName":"codex/add-recipes-instantiation","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/8"}
```
