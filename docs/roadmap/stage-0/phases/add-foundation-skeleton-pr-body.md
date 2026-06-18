## Phase

- Phase: Phase 1 - Foundation
- Branch: `codex/add-foundation-skeleton`
- Target: `develop`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-foundation-skeleton`
- Plan: `docs/roadmap/stage-0/implementation-plan.md`
- Expanded phase plan: `docs/roadmap/stage-0/phases/add-foundation-skeleton.md`
- PR status: merged as https://github.com/samcantrill/loom/pull/1.

## Summary

This PR implements the Phase 1 foundation skeleton for `loom` v0. It adds import-safe package boundaries, shared string ID aliases, broad catchable errors, UTC timestamp helpers, and explicit unsupported config stubs while keeping `loom.__init__` metadata-only and dependency-light.

## Acceptance Criteria

- [x] `import loom` is cheap and succeeds.
- [x] Broad catchable error classes are available from `loom.errors`.
- [x] UTC timestamp helpers produce parseable UTC values and path-safe strings.
- [x] Deferred package imports succeed without performing runtime work.
- [x] Import-boundary tests prove top-level imports do not pull in config, pipeline, CLI, or domain packages.
- [x] Phase 1 package and unit tests cover public imports, deferred stubs, errors, IDs, and timestamps.

## Implementation Notes

Phase 1 adds `loom.ids`, `loom.errors`, and `loom.timestamps`, plus import-safe skeleton packages for records, provenance, serialization, I/O, config, pipeline subpackages, and CLI. `loom.config` exposes only `ConfigError`, `compose_config`, `instantiate`, and `register_recipe`; each callable raises `ConfigError` until its owning future phase implements behavior.

`loom.__init__` remains limited to `__version__` and `__all__ == ["__version__"]`. No runtime dependencies were added. `pyproject.toml` now points Pyright at the repository `.venv` so the existing uv-managed validation environment resolves consistently.

Implementation refinement budget is used. PR review budget was used by local
manager review before merge.

## Tests And Validation

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright reported 0 errors, default pytest passed with 24 passed, and uv build produced sdist and wheel.

command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; wrote build/test-summary.md.
```

All required PR-prep commands ran successfully.

### Test Suite Summary

`UV_CACHE_DIR=/tmp/uv-cache make test-summary` produced:

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 0.32s | `uv run pytest tests/package -m "not slow and not slurm and not network and not optional_dependency"` |
| unit | passed | 0.28s | `uv run pytest tests/unit -m "not slow and not slurm and not network and not optional_dependency"` |
| contract | not present | 0.00s | `uv run pytest tests/contracts -m "not slow and not slurm and not network and not optional_dependency"` |
| integration | not present | 0.00s | `uv run pytest tests/integration -m "not slow and not slurm and not network and not optional_dependency"` |
| e2e | not present | 0.00s | `uv run pytest tests/e2e -m "not slow and not slurm and not network and not optional_dependency"` |

Package suite output recorded 7 passed tests. Unit suite output recorded 17 passed tests. Contract, integration, and e2e suites are not present for this foundation-only phase.

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

## Risks / Follow-Ups

- Unsupported config stubs are accepted temporary debt until Phase 4 (`compose_config`, `instantiate`) and Phase 5 (`register_recipe`) replace them with real behavior.
- Empty skeleton packages are accepted temporary structure until each owning future phase adds behavior.
- Contract, integration, and e2e suites are intentionally absent because Phase 1 has no runtime contracts, cross-component behavior, or end-to-end workflow.
- The branch is based on local `develop` at `4878e95eda64c3d8d969fcfcc658d6b082a7f310`; earlier fetch attempts were unavailable because GitHub SSH authentication failed.
- GitHub PR #1 was squash-merged into `develop` as
  `c054908620022a81240c4928599c84b0ed24672f`.
