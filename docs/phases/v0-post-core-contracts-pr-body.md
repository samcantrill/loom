## Phase

- Phase: Phase 1 - Core Contracts, Schemas, And Packaging
- Branch: `codex/v0-post-core-contracts`
- Target branch: `develop`
- Stack predecessor: none
- Merge eligibility: serial human merge gate. This PR targets `develop`, must request review from `samcantrill` or mention `@samcantrill` if GitHub rejects the reviewer request, and must be approved and merged by a human. Codex must not approve or merge.
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-core-contracts`
- Plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Phase execution plan: `docs/phases/v0-post-core-contracts.md`
- Draft pass: complete, 2026-05-04
- Refine pass: pending

## Summary

This PR implements Phase 1 of the v0-post hardening plan. It makes the lowest-level frozen value objects recursively immutable, keeps public serialization output as ordinary mutable plain data, adds shared strict helpers for persisted schema documents, and moves config-only dependencies behind the `config` optional extra.

The diff also updates validation harnesses so default no-extra and config-extra behavior are both visible in PR evidence, then updates Phase 1 documentation for the new immutability, schema, optional dependency, and test-suite contracts.

## Acceptance Criteria

- [x] Nested metadata/config mappings on core frozen objects cannot be mutated after construction.
- [x] Existing serialization round trips still return ordinary mutable `dict` and `list` structures.
- [x] Selected persisted readers reject unsupported schema versions and unknown fields by default.
- [x] Older schema versions can route through explicit document-owned migrations in the shared schema-helper tests.
- [x] `import loom` and core primitive/store/serialization/inspection imports work without config extras.
- [x] Phase 1 suite evidence includes default no-extra package/unit/contract/integration rows and config-extra/e2e rows.
- [x] Final `make validate-pr` passes.

## Implementation Notes

- Added `freeze_plain_data()` and `thaw_plain_data()` in `loom.serialization` and applied them to resource refs, artifact refs, records, manifests, manifest views, output specs, stage specs, and pipeline specs.
- Preserved public `to_dict()` and serialization helpers as mutable plain-data output so internal `MappingProxyType` and tuple storage do not leak into persisted/user-facing data.
- Added `require_mapping()`, `validate_document_fields()`, and `load_versioned_document()` in `loom.serialization.schema`.
- Migrated only the selected Phase 1 persisted readers to the shared schema helper path: `InMemoryManifest.from_dict()`, `RunStatusRecord.from_dict()`, `StageStatusRecord.from_dict()`, and `ExecutionFailure.from_dict()`.
- Moved OmegaConf, Pydantic, and PyYAML to `loom[config]`; `import loom.config` remains no-extra-safe, and accessing config behavior without the extra raises a config-owned missing-extra error.
- Added isolated `test-no-extra` and `test-config-extra` targets and made `make test-summary` run suite rows through isolated install surfaces.
- Updated docs for structure, serialization, config, and test-suite evidence.

## Tests And Validation

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed
details: Ruff passed; Pyright passed with 0 errors; isolated no-extra default suite passed with 304 passed and 9 skipped; isolated config-extra suite passed with 102 passed and 305 deselected; source distribution and wheel built successfully.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; wrote build/test-summary.md
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 2.65s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run package` |
| unit | passed | 2.32s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run unit` |
| contract | passed | 1.04s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run contract` |
| integration | passed | 1.38s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run integration` |
| e2e | passed | 1.85s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run e2e` |
| config-extra | passed | 5.00s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run config-extra` |

Suite counts from `make test-summary`:

- package: 32 passed, 1 skipped
- unit: 252 passed, 1 skipped
- contract: 12 passed, 1 skipped
- integration: 8 passed, 5 skipped
- e2e: 1 passed
- config-extra: 102 passed, 305 deselected

## Scope Control

- [x] Implements only the assigned Phase 1 work.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

Scope check:

- No store/context capability rewrite, run-scoped artifact-store change, `ArtifactAddress`, run metadata API rename, or local path contract break.
- No stage factory block, stage constructor/fingerprint policy change, or target import redesign beyond optional dependency import safety.
- No runtime/resource/event/lock foundations or durable blocked-outcome work.
- No planner decomposition or explanation surface.
- No explicit recipe catalog policy change beyond preserving existing config-extra behavior under optional dependencies.
- No runner lifecycle decomposition, executor expansion, catalogs, bundles, sweeps, retry, timeout, cleanup, plugin discovery, or non-local execution.

## Budget Status

- Phase implementation refinement: used in commit `0fd6618`.
- PR review before this PR: unused.

## Risks / Follow-Ups

- Selected schema-helper migration remains intentionally limited to manifest, status, and execution failure readers. Planning, provenance, local-store wrapper, and artifact-index readers remain documented debt for later edits to those document families.
- Config package lazy-import behavior is transitional until later stage factory/import work; current intent is no-extra-safe package import plus clear missing-extra errors for config behavior.

## PR Creation Status

- PR opened: no.
- Command attempted: none. The draft pass explicitly must not open the PR.
- Planned command after refine/blocker resolution:

```sh
gh pr create --base develop --head codex/v0-post-core-contracts --body-file docs/phases/v0-post-core-contracts-pr-body.md
```

- Current blocker: none. PR body refine pass is pending.

## Review Notification

- Reviewer requested: `samcantrill`
- Command or fallback used: not attempted in draft pass.
- Notification result: pending. After PR creation, request review with `gh pr edit <PR> --add-reviewer samcantrill`; if GitHub rejects the request because the authenticated account or PR author is `samcantrill`, add a PR comment mentioning `@samcantrill` and record that fallback.

## Stack Maintenance

- Current base branch: `develop` at `d40b532a741bd80383da5ea83020aa77aec57315`.
- Retarget/rebase needed after predecessor merge: none; this is a root serial phase with no predecessor.
- Successor branches depending on this phase: none should start until this PR is human-merged into `develop`.
- Branch cleanup constraints: keep `codex/v0-post-core-contracts` until the human-owned PR has merged into `develop` and no successor branch depends on it.
