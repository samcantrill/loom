# Stage 15 Phase 5 Execution Plan: Stage 12 Exchange Metadata Rework

## Metadata

- Status: pr_ready
- Roadmap stage: `v15`
- Phase: 5
- Slug: `stage-12-exchange-rework`
- Branch: `codex/stage-12-exchange-rework`
- Worktree: `/home/samcantrill/work/loom-worktrees/stage-12-exchange-rework`
- Stack predecessor: none; Phases 1-4 are merged
- Base branch: `develop`
- Base commit: `660627d7cc04598c3715c9e99cbfd590b917aead`
- PR target branch: `develop`
- PR feature focus: `External Artifact Interface`
- Intended PR title:
  `External Artifact Interface - Phase 5: Stage 12 Exchange Metadata Rework`
- Workflow path: expanded path because this phase changes durable run-exchange
  metadata semantics and import/export behavior.

## Source Recheck

- `src/loom/runs/models.py` has strict Stage 12 exchange records with
  `extensions` on source identity, target identity, payload selection,
  manifest, export record, import record, inspection, and exchange envelopes.
- `RunBundleManifest` is currently schema version 1 and already stores
  completed-run metadata under `manifest.extensions["completed_run"]`.
- `CompletedRunBundleMetadata.to_dict()` already includes artifact facts,
  stage lifecycle snapshots, materialized refs, warnings, and nested
  `ArtifactRef.metadata`, so Stage 15 summaries can be preserved without
  widening the manifest schema.
- Local bundle inspect reads only `manifest.json` by default and does not
  extract payload members unless checksum verification is requested.
- Local import writes historical runs and currently rebases artifact URIs only
  when local payloads are copied; metadata-only imports preserve the original
  artifact URI and metadata.

## Design Choice

Use an explicit extension-field mapping rather than a schema revision.

The extension mapping is narrow, plain-data, and versioned under a Stage
15-specific key. This keeps old Stage 12 bundles inspectable, avoids widening
`RunBundleManifest` while the exchange model is still adapter-neutral, and
lets Stage 16 consume preserved summaries later. A schema revision is not
needed because the required Stage 15 data already fits in strict extension
fields and does not change manifest identity, payload entry, checksum, or
archive-member semantics.

## Scope

- Add run-exchange helpers that project Stage 15 external, published, location,
  and unsupported-materialization summaries from completed-run artifact facts
  into manifest/export/import extension metadata.
- Preserve the existing `completed_run` extension for backwards compatibility.
- Add structured non-failing diagnostics for unsupported remote
  materialization/import payloads; diagnostics must not trigger downloads,
  credential checks, backend discovery, or optional SDK imports.
- Preserve Stage 15 summaries through local bundle export, inspect,
  import-record construction, import provenance, and historical local artifact
  indexes.
- Update unit, contract, and CLI coverage for metadata-only exchange behavior.

## Out Of Scope

- Remote payload materialization, credential checks, provider-specific schemas,
  authority continuation, overwrite/merge policy changes, and Stage 16 payload
  operations.
- Backend registry or preflight behavior changes beyond consuming public Stage
  15 summary helpers.
- Manifest schema-version increment unless implementation proves extension
  fields are insufficient.

## Acceptance Criteria

- Metadata-only bundle export records Stage 15 summaries under a stable
  extension key and keeps payload selection unchanged by default.
- Bundle inspect exposes the same summaries without payload extraction.
- Bundle import preserves Stage 15 summaries in import provenance and in the
  imported local artifact index when artifact facts are present.
- Unsupported-materialization evidence is surfaced as structured warning
  diagnostics and does not fail metadata-only export/import.
- Old bundles without the Stage 15 extension remain inspectable and importable.
- Imported runs remain historical-only; no resume or authority mutation policy
  changes are introduced.

## Validation Obligations

| Command/check | Purpose | Required |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/runs tests/unit/loom/cli tests/contracts/test_run_exchange_contract.py tests/contracts/test_run_bundle_export_contract.py tests/contracts/test_cli_runs_contract.py` | Target run exchange, bundle export/import, inspect output, and CLI contract behavior | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

## Design Impact

This phase makes the Stage 15 artifact summary contract visible in Stage 12
portable exchange artifacts while preserving the current manifest schema. The
durable contract is that consumers should read the versioned extension key when
available and continue to tolerate bundles that only contain `completed_run`.

## Future Compatibility

Stage 16 can consume the preserved summaries to implement explicit
materialization/import behavior. Stage 17/18 staging, Stage 19 retry, and Stage
20 cleanup can add new diagnostics or policy fields without rewriting existing
bundle manifests.

## Alternatives Rejected

- Schema revision: rejected for Phase 5 because strict extensions carry the
  required summaries without changing archive structure or identity semantics.
- Keeping external refs opaque: rejected because Stage 16 needs durable,
  documented summary placement.
- Adding remote downloads to import/export: rejected as future Stage 16 scope.

## Debt Introduced

The extension key becomes a public convention before a dedicated run-exchange
schema field exists. Revisit if consumers need strongly typed manifest fields
or if Stage 16 materialization needs richer policy than metadata summaries and
diagnostics.

## Reviewability

Keep changes confined to `loom.runs` exchange helpers, local bundle
export/inspect/import plumbing, docs/tests, and package exports. Do not modify
backend registry, diagnostics preflight, planner behavior, or authority
mutation policy.

## Budget Status

- Phase execution plan draft: used
- Phase execution plan refine: not needed; the source recheck resolved the
  extension-vs-schema decision before implementation
- Phase implementation refinement: not needed; targeted validation and full PR
  gate passed
- Phase PR review: unused
- Blocker-resolution passes: 0 of 3 used

## Implementation Summary

- Added the versioned `stage_15_artifact_summaries` run-exchange extension and
  public projection helper for Stage 15 artifact metadata summaries.
- Local bundle export now projects Stage 15 summaries into manifest/export
  extensions while preserving the existing `completed_run` extension and
  metadata-only default payload selection.
- Bundle inspect and import-record construction preserve the extension without
  extracting payloads.
- Local bundle import carries the extension into import provenance and preserves
  external artifact metadata in historical imported artifact indexes.
- Unsupported materialization evidence surfaces as warning diagnostics, not as
  failed metadata-only export/import or implicit remote materialization.
- `docs/features/run-catalog.md` now documents the extension-field mapping and
  metadata-only import/export boundary.

## Validation Evidence

| Command/check | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/runs/test_artifact_metadata.py tests/unit/loom/runs/test_bundle_export.py tests/unit/loom/runs/test_bundle_import.py tests/contracts/test_run_exchange_contract.py tests/contracts/test_run_bundle_export_contract.py tests/contracts/test_cli_runs_contract.py tests/package/test_runs_api.py` | passed: 26 passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/runs tests/unit/loom/cli tests/contracts/test_run_exchange_contract.py tests/contracts/test_run_bundle_export_contract.py tests/contracts/test_cli_runs_contract.py` | passed outside sandbox: 172 passed / 4 skipped |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | passed outside sandbox: Ruff passed, Pyright passed with 0 errors, default harness passed with 1653 passed / 26 skipped / 18 deselected, config-extra passed with 440 passed / 1690 deselected, and build passed |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | passed: package 90 passed / 1 skipped; unit 1165 passed / 7 skipped / 1 deselected; contract 227 passed / 2 skipped; integration 156 passed / 8 skipped / 13 deselected; e2e 43 passed / 2 deselected; config-extra 440 passed / 1690 deselected |

## PR Preparation

- PR body: `docs/roadmap/stage-15/phases/stage-12-exchange-rework-pr-body.md`
- Target branch: `develop`
- Local automated review: pending after PR creation
