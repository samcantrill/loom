# Stage 15 Phase 6 Execution Plan: Examples, Docs, And Validation Hardening

## Metadata

- Status: pr_ready
- Roadmap stage: `v15`
- Phase: 6
- Slug: `external-artifact-docs-validation`
- Branch: `codex/external-artifact-docs-validation`
- Worktree: `/home/samcantrill/work/loom-worktrees/external-artifact-docs-validation`
- Stack predecessor: none; Phases 1-5 are merged
- Base branch: `develop`
- Base commit: `5a2a871768dd01aa523fa1a86c73898cc52ee464`
- PR target branch: `develop`
- PR feature focus: `External Artifact Interface`
- Intended PR title:
  `External Artifact Interface - Phase 6: Docs and Validation Hardening`
- Workflow path: expanded path because this phase hardens public contracts and
  final documentation before Stage 16 builds on Stage 15.

## Source Recheck

- Public Stage 15 records and helpers are implemented in `loom.artifacts`,
  `loom.pipeline.stores`, `loom.plugins`, `loom.diagnostics`, and `loom.runs`.
- Feature docs mention Stage 15 in scattered places but do not yet provide a
  consolidated adapter-author and user boundary across artifacts, remote
  stores, plugins, preflight, and run-catalog behavior.
- Existing tests include fake backend handlers and import-boundary coverage,
  but they do not yet name the MLflow-like tracking-system and object-store
  examples as cross-contract fixtures.
- Import-boundary tests cover the main package layers; Phase 6 should harden
  Stage 15-specific boundaries against plugin discovery and optional SDK import
  on default imports, default preflight, and bundle inspection.

## Scope

- Update `docs/features/artifacts.md`, `remote-stores.md`, `plugins.md`,
  `preflight.md`, and `run-catalog.md` with final Stage 15 contracts and Stage
  16 handoff notes.
- Add cross-contract fake examples for a tracking-system style adapter and an
  object-store style adapter using only generic Stage 15 records and backend
  contracts.
- Add or update package/import-boundary tests proving default imports,
  diagnostics/preflight, and bundle inspect do not discover plugins, import
  optional service SDKs, or contact networks.
- Run final validation and record suite-level evidence in this phase artifact
  and the PR body.

## Out Of Scope

- Real MLflow, object-store, cloud, HTTP, DVC, or tracking adapters.
- Optional service-backed integration tests or new runtime dependencies.
- Stage 16 payload materialization, upload/download, staging, cleanup, retry,
  or credential behavior.

## Acceptance Criteria

- Docs clearly distinguish metadata records, backend descriptors/handlers,
  plugin listing/loading, configured backend readiness, and payload
  materialization.
- Docs label MLflow-like and object-store-style mappings as fake contract
  examples, not supported first-party adapters.
- Fake examples demonstrate redaction, capability admission, lookup or
  unsupported-operation results, and run-exchange metadata preservation using
  only generic Stage 15 contracts.
- Import-boundary tests fail if Stage 15 defaults import plugin targets,
  optional SDKs, backend services, or network/client packages.
- Final `make validate-pr` and `make test-summary` pass.

## Validation Obligations

| Command/check | Purpose | Required |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package tests/contracts tests/unit/loom` | Target package exports, import boundaries, contract fixtures, and unit behavior | yes |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Full PR gate for phase | yes |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Suite-level PR evidence | yes |

## Design Impact

This phase does not introduce new runtime behavior beyond test fixtures. It
stabilizes the public explanation of Stage 15 so future adapter and
materialization work can rely on the documented boundary.

## Future Compatibility

Stage 16 can add explicit materialization/import policy on top of the preserved
records. Later container, HPC staging, retry, and cleanup stages can extend
diagnostics and policy without revisiting Stage 15 metadata shape.

## Alternatives Rejected

- Documenting fake examples as supported first-party adapters.
- Adding optional SDK imports or service-backed integration tests.
- Leaving adapter-author guidance implicit in tests only.

## Debt Introduced

Fake examples may need adjustment when the first real optional backend family
enters the roadmap. Revisit docs when Stage 16 selects concrete
materialization policy.

## Reviewability

Keep the diff focused on docs, test fixtures, import-boundary assertions, phase
artifacts, and PR evidence. Do not change public Stage 15 behavior unless a
test exposes a concrete boundary issue.

## Budget Status

- Phase execution plan draft: used
- Phase execution plan refine: not needed; source recheck found a docs/tests
  hardening phase with no unresolved design choice
- Phase implementation refinement: unused
- Phase PR review: unused
- Blocker-resolution passes: 0 of 3 used

## Implementation Summary

- Updated artifact, remote-store, plugin, preflight, and run-catalog feature
  docs to describe the final Stage 15 metadata-first boundary, backend
  registry/handler readiness split, fake adapter examples, and Stage 16
  materialization handoff.
- Extended the artifact-store backend contract fixtures so tracking-system and
  object-store shapes demonstrate redaction, capability admission, explicit
  lookup or unsupported-operation results, and run-exchange metadata
  preservation through public Stage 15 contracts.
- Added Stage 15 import-boundary tests proving public defaults, default
  artifact-backend preflight, and bundle inspection avoid plugin discovery,
  optional service SDK imports, and backend client packages.

## Validation Evidence

| Command/check | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check tests/contracts/test_artifact_store_backend_contract.py tests/package/test_import_boundaries.py` | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pyright tests/contracts/test_artifact_store_backend_contract.py tests/package/test_import_boundaries.py` | passed: 0 errors |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_artifact_store_backend_contract.py tests/package/test_import_boundaries.py` | passed: 54 passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package tests/contracts tests/unit/loom` | passed outside sandbox: 1481 passed / 11 skipped |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | passed outside sandbox: Ruff passed, Pyright passed with 0 errors, default harness passed with 1657 passed / 26 skipped / 18 deselected, config-extra passed with 440 passed / 1694 deselected, and build passed |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | passed: package 93 passed / 1 skipped; unit 1165 passed / 7 skipped / 1 deselected; contract 228 passed / 2 skipped; integration 156 passed / 8 skipped / 13 deselected; e2e 43 passed / 2 deselected; config-extra 440 passed / 1694 deselected |

## PR Preparation

- PR body:
  `docs/roadmap/stage-15/phases/external-artifact-docs-validation-pr-body.md`
- Target branch: `develop`
- Local automated review: pending after PR creation
