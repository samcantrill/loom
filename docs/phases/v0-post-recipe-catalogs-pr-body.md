## Phase

- Phase: Phase 6 - Explicit Recipe Catalogs And Fresh Composition
- Branch: `codex/v0-post-recipe-catalogs`
- Target branch: `develop`
- PR: https://github.com/samcantrill/loom/pull/20
- Stack predecessor: none
- Merge eligibility: serial human merge gate. This PR must target `develop`,
  request review from `samcantrill` or mention `@samcantrill` if GitHub rejects
  the reviewer request, and must be approved and merged by a human. Codex must
  not approve or merge.
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-recipe-catalogs`
- Plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Phase execution plan: `docs/phases/v0-post-recipe-catalogs.md`
- Phase execution plan draft pass: complete in commit `b824f6e`
- Phase execution plan refine pass: complete in commit `be8b06d`
- Implementation commits: `c535c01`, `ac255fd`, `c661181`
- Phase implementation refinement: complete in commit `b712ad6`
- PR-prep validation note: `make validate-pr` post-refinement evidence was
  manager-provided; `make test-summary` was run during PR preparation.
- PR body draft pass: complete in this artifact
- PR body refine pass: complete in this artifact

## Summary

@samcantrill, this PR implements Phase 6 of the v0-post hardening plan. It
makes caller-owned `RecipeCatalog` instances the reproducible config
composition path while preserving the process-global `register_recipe()` path
for scripts, notebooks, and interactive Python use.

The diff adds `compose_config_with_catalog()` as the explicit public helper,
keeps `compose_config()` as the global-convenience wrapper when no catalog is
provided, makes the lower-level composition path require a concrete
`RecipeCatalog`, lazily exports the new config symbol, and adds focused tests
proving globally registered recipes do not leak into fresh explicit-catalog
composition. The docs now describe explicit catalog ownership without claiming
plugin discovery or CLI loading exists in this phase.

## Acceptance Criteria

- [x] `RecipeCatalog()` is the documented reproducible recipe registration
  path.
- [x] `register_recipe()` remains available and documented as
  convenience-only for scripts, notebooks, and interactive sessions.
- [x] `compose_config_with_catalog()` requires a caller-owned explicit catalog
  and never reads process-global recipe registrations.
- [x] `compose_config(..., recipe_catalog=None)` preserves the Python
  convenience path backed by the process-global default catalog.
- [x] `src/loom/config/compose.py` no longer imports or calls
  `_get_default_recipe_catalog()`.
- [x] Unit, integration, pipeline, package, and import-boundary tests cover the
  new explicit-catalog behavior and global-state isolation.
- [x] Affected structure, config, and plugin docs are aligned with catalog
  ownership and global-state policy.
- [x] Package, unit, contract, integration, e2e, config-extra, static analysis,
  and build evidence is recorded for PR review.

## Implementation Notes

- Added `compose_config_with_catalog()` in `loom.config.api` with a
  keyword-only `recipe_catalog` parameter, shared overlay/override validation,
  and the same `ConfigValidationError` style used by existing config APIs.
- Kept `compose_config()` source-compatible while making catalog selection
  explicit in the public API wrapper: caller-provided catalogs are used
  directly, otherwise `_get_default_recipe_catalog()` is used only for the
  documented convenience path.
- Updated `loom.config.compose.compose_config()` so lower-level orchestration
  accepts a required concrete `RecipeCatalog` and does not import API global
  registry state.
- Added lazy `loom.config` resolution and package API coverage for
  `compose_config_with_catalog()` without weakening no-extra import boundaries.
- Added focused tests showing global `register_recipe()` still works through
  `compose_config()` and that fresh explicit catalogs reject recipes that exist
  only in the global convenience catalog.
- Updated config, plugin, and structure docs to show future CLI/plugin code
  composing from caller-owned catalogs while keeping plugin discovery deferred.

## Tests And Validation

```text
command: git diff --check develop...HEAD
result: passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed
details: Manager-provided latest post-refinement validation passed with Ruff
clean, Pyright with 0 errors, the default harness with 401 passed and 9
skipped, the config-extra harness with 108 passed and 402 deselected, and
build.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; wrote build/test-summary.md
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 2.80s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run package` |
| unit | passed | 2.54s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run unit` |
| contract | passed | 1.04s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run contract` |
| integration | passed | 1.38s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run integration` |
| e2e | passed | 1.54s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run e2e` |
| config-extra | passed | 4.95s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run config-extra` |

Suite counts from `make test-summary`:

- package: 34 passed, 1 skipped
- unit: 344 passed, 1 skipped
- contract: 14 passed, 1 skipped
- integration: 9 passed, 5 skipped
- e2e: 1 passed
- config-extra: 108 passed, 402 deselected

Focused implementation and refinement evidence is recorded in
`docs/phases/v0-post-recipe-catalogs.md`.

## Scope Control

- [x] Implements only the assigned Phase 6 work.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

Scope check:

- No plugin discovery, entry-point loading, plugin metadata validation, or
  plugin error policy.
- No CLI command implementation, CLI config loader, sweep driver, or project
  recipe loading behavior.
- No runner lifecycle decomposition, event emission integration, lock
  acquire/release integration, failed-run blocked descendant persistence, or
  status model changes.
- No recipe expansion semantic changes beyond catalog ownership and routing.
- No run catalog, bundle, remote store, non-local executor, subprocess, SLURM,
  container, retry, timeout, cleanup, retention, or migration closeout work.
- No compatibility bridge that lets plugin import side effects populate the
  process-global recipe catalog.

## Budget Status

- Plan quality gate: passed; initial review used, automated plan refinement
  pass used, confirmation review used.
- Phase execution plan draft pass: complete.
- Phase execution plan refine pass: complete.
- Phase implementation refinement: used in commit `b712ad6`; no blockers
  reported.
- PR review: unused.
- PR body draft pass: complete in this artifact.
- PR body refine pass: complete in this artifact.

## Assumptions

- Serial human merge gate mode is active.
- Phase 5 is already merged into `develop`; this branch starts from `develop`
  at `b93d82eeb506bdb6297c229c8a2a3a4d395917dd`.
- Global `register_recipe()` remains accepted debt for script, notebook, and
  interactive Python convenience only.
- Future CLI, plugin, and sweep code will create fresh `RecipeCatalog()`
  instances, load explicit recipes into them when those features exist, and
  call `compose_config_with_catalog()`.
- Phase 7 and later phases remain unstarted until this PR is human-approved and
  human-merged into `develop`.

## Risks / Follow-Ups

- The process-global default catalog intentionally remains available for
  Python convenience; future work should continue using explicit catalogs for
  reproducible, long-lived, CLI, plugin, and sweep paths.
- Plugin discovery remains deferred. Later plugin work must load recipes into a
  caller-owned catalog rather than relying on import side effects.
- CLI config loading remains deferred. The new helper provides the fresh
  composition path for that later work but does not implement CLI behavior.
- Runner lifecycle decomposition, non-local executors, remote stores, catalogs,
  bundles, sweeps, cleanup, and final migration notes remain later-phase work.

## PR Creation Status

- PR opened: yes.
- PR URL: https://github.com/samcantrill/loom/pull/20
- Command run:

```sh
gh pr create --base develop --head codex/v0-post-recipe-catalogs --title "Phase 6: Explicit Recipe Catalogs and Fresh Composition" --body-file docs/phases/v0-post-recipe-catalogs-pr-body.md
```

- Verification:

```json
{"baseRefName":"develop","headRefName":"codex/v0-post-recipe-catalogs","mergedAt":null,"state":"OPEN","statusCheckRollup":[{"__typename":"CheckRun","completedAt":"0001-01-01T00:00:00Z","conclusion":"","detailsUrl":"https://github.com/samcantrill/loom/actions/runs/25319766762/job/74225610616","name":"checks","startedAt":"2026-05-04T12:46:00Z","status":"IN_PROGRESS","workflowName":"CI"}],"url":"https://github.com/samcantrill/loom/pull/20"}
```

- Target verification result: base is `develop`, matching the recorded target
  branch.
- CI status at PR verification: GitHub `checks` workflow was in progress.
- Merge eligibility: root serial-gate PR targeting `develop`; human review and
  human merge are required. Codex must not approve or merge.
- Current blocker: none.

## Review Notification

- Reviewer requested: `samcantrill`.
- Command attempted: `gh pr edit 20 --add-reviewer samcantrill`.
- Command result: failed with GitHub GraphQL project-card deprecation output
  and no review request was recorded; `gh pr view 20 --json
  reviewRequests,author,url` showed PR author `samcantrill` and an empty
  `reviewRequests` list.
- Fallback used: added a PR comment mentioning `@samcantrill`.
- Fallback comment: https://github.com/samcantrill/loom/pull/20#issuecomment-4371151613
- Notification result: fallback comment posted; PR body records the fallback.

## Stack Maintenance

- Current predecessor branch: none.
- Current target branch: `develop`.
- Retarget/rebase needed after predecessor merge: none; this is a root serial
  phase with no predecessor.
- Successor branches depending on this phase: none should start until this PR
  is human-approved and human-merged into `develop`.
- Branch cleanup constraints: keep `codex/v0-post-recipe-catalogs` until the
  human-owned PR has merged into `develop` and no successor branch depends on
  it.
