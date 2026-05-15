# Phase 5 Execution Plan: No-Backend Finalization And User-Facing Handles

## Metadata

- Status: scope-complete plan - ready for implementation
- Feature focus: Artifact Payload Materialization
- PR title: `Artifact Payload Materialization - Phase 5: No-Backend User-Facing Handles`
- Branch: `codex/no-backend-user-facing-handles`
- Worktree: `/home/samcantrill/work/loom-worktrees/no-backend-user-facing-handles`
- Phase execution plan path: `docs/roadmap/stage-16/phases/no-backend-user-facing-handles.md`
- Full plan: `docs/roadmap/stage-16/implementation-plan.md`
- Source phase: `Phase 5: No-Backend Finalization And User-Facing Handles`
- Stack predecessor: `codex/bundle-preflight-materialization` / PR [#169](https://github.com/samcantrill/loom/pull/169)
- Base branch: `codex/bundle-preflight-materialization`
- Target branch: `codex/bundle-preflight-materialization` until Phase 4 merges; retarget to `develop` after replaying onto merged Phase 4
- Workflow path: expanded path
- Plan quality gate: passed in the implementation plan on 2026-05-15
- Draft/refine status: single scope-complete pass; no unresolved design blockers
- Blockers: none

## Objective

Close Stage 16 by making the no-real-backend decision explicit in public docs,
examples, package import boundaries, and unsupported-handle contracts. This
phase must not add provider SDKs, real backend adapters, broad CLI commands, or
catalog payload movement.

## Scope Decisions

- Real backends: remain unselected. Public handles expose unsupported or
  not-implemented results for future backend paths.
- Examples: use documentation examples and synthetic tests rather than adding a
  runnable provider-backed example.
- CLI: unchanged. Explicit remote/fake payload materialization remains an API
  path because there is no first-party backend registry or credential surface.
- Run catalog: unchanged. Catalog and inspect stay metadata-only by default and
  never infer provider reachability from preserved URIs.
- Docs: update feature docs for artifacts, remote stores, run catalog,
  preflight, and testing with Stage 16 behavior and revisit triggers.

## In Scope

- `docs/features/artifacts.md`: Stage 16 materialization boundary, copy-only
  local policy, and unsupported future-policy handles.
- `docs/features/remote-stores.md`: no first-party backend family, fake backend
  semantics, adapter extension point, and future real-backend revisit triggers.
- `docs/features/run-catalog.md`: bundle/export/import materialization
  examples, metadata-only defaults, and catalog non-movement.
- `docs/features/preflight.md`: cheap materialization readiness check and
  stable check ID.
- `docs/features/testing.md`: fake-backend-first and no optional SDK testing
  expectations.
- Package/import-boundary tests proving Stage 16 public defaults do not import
  backend SDKs or plugins.
- Contract tests for structured unsupported/not-implemented handles for future
  real-backend payload paths and local future policies.

## Out Of Scope

- Real S3/GCS/Azure/HTTP/MLflow/DVC/W&B adapters, provider extras, credentials,
  retries/timeouts, cleanup, remote catalogs, new CLI materialization flags, and
  catalog summary schema changes.

## Validation

- Targeted package/contract/doc checks:
  `uv run pytest tests/package tests/contracts/test_artifact_materialization_contract.py tests/contracts/test_artifact_store_payload_operations_contract.py`
- Broad phase check:
  `uv run pytest tests/package tests/contracts tests/unit/loom tests/integration`
- Final PR gate: `make validate-pr`
- Suite evidence: `make test-summary`

## Budget Status

- Planning draft/refine: used in this artifact
- Phase implementation refinement: unused; one pass remains if validation finds
  a bounded blocker
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Implementation summary: pending
- Implementation validation: pending
- PR preparation: pending
- Stack maintenance: stacked on Phase 4 until Phase 4 merges
- Remaining blockers: none
