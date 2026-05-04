## Phase

- Phase: Phase 8 - Hardening, Docs, And Migration Notes
- Branch: `codex/v0-post-hardening-docs`
- Target branch: `develop`
- Stack predecessor: none
- Merge eligibility: serial human merge gate; human review and merge only
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-hardening-docs`
- Plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Phase execution plan: `docs/phases/v0-post-hardening-docs.md`

## Summary

Closes the v0-post hardening sequence with migration notes, documentation
consistency updates, downstream roadmap alignment, and focused e2e coverage for
the local Python API closeout behavior.

## Acceptance Criteria

- [x] Docs describe supported pre-v1 behavior and defer future CLI, remote store,
  executor, plugin, sweep, cleanup, retention, retry, and timeout work.
- [x] Migration notes identify breaking API changes and replacement APIs.
- [x] Focused e2e coverage exercises local success/resume, failure with blocked
  outcomes, explicit recipe catalogs, stage factory construction, and
  event/lock behavior.
- [x] `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passes.
- [x] `UV_CACHE_DIR=/tmp/uv-cache make test-summary` records suite-level
  evidence.

## Implementation Notes

- Added `docs/briefs/v0_public_api_migration_notes.md` and linked it from the
  README and main docs.
- Updated docs and roadmap references so v1 starts after this closeout baseline
  and deferred behavior remains explicitly future work.
- Added e2e coverage in `tests/e2e/test_local_pipeline_run.py` using public
  Python APIs and supported store/context surfaces.
- No runtime features, CLI behavior, remote stores, plugins, sweeps, retry,
  timeout, cleanup, or retention behavior are introduced.

## Tests And Validation

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright reported 0 errors, default harness passed
        with 406 passed / 9 skipped, config-extra harness passed with
        108 passed / 411 deselected, and uv build produced sdist and wheel.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; wrote build/test-summary.md.
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 2.99s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run package` |
| unit | passed | 2.66s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run unit` |
| contract | passed | 1.03s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run contract` |
| integration | passed | 1.44s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run integration` |
| e2e | passed | 2.58s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run e2e` |
| config-extra | passed | 5.54s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run config-extra` |

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

## Risks / Follow-Ups

- Migration support is documentation-first; compatibility shims remain out of
  scope unless a future downstream user needs a temporary bridge.
- V1 implementation must not start until this serial-gate PR is human-reviewed,
  human-merged into `develop`, and the phase metadata is updated to `merged`.

## Stack Maintenance

This is a root serial-gate PR targeting `develop` with no stack predecessor.
No successor work should start while this PR is `pr_open` or `approved`.

Reviewer notification: GitHub reviewer assignment could not be completed because
the PR author and authenticated account are `samcantrill`. The serial-gate
fallback comment mentioning `@samcantrill` was posted:
https://github.com/samcantrill/loom/pull/22#issuecomment-4375429754
