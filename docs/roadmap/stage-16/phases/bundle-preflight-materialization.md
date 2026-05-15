# Phase 4 Execution Plan: Bundle, Import, Catalog, And Preflight Integration

## Metadata

- Status: implemented and validated; PR ready
- Feature focus: Artifact Payload Materialization
- PR title: `Artifact Payload Materialization - Phase 4: Bundle And Preflight Materialization`
- Branch: `codex/bundle-preflight-materialization`
- Worktree: `/home/samcantrill/work/loom-worktrees/bundle-preflight-materialization`
- Phase execution plan path: `docs/roadmap/stage-16/phases/bundle-preflight-materialization.md`
- Full plan: `docs/roadmap/stage-16/implementation-plan.md`
- Source phase: `Phase 4: Bundle, Import, Catalog, And Preflight Integration`
- Stack predecessor: none; Phase 3 merged in PR [#168](https://github.com/samcantrill/loom/pull/168)
- Base branch: `develop`
- Target branch: `develop`
- Workflow path: expanded path
- Plan quality gate: passed in the implementation plan on 2026-05-15
- Draft/refine status: single scope-complete pass; no unresolved design blockers
- Blockers: none

## Objective

Wire explicit artifact payload materialization into local bundle export and
artifact backend preflight while preserving metadata-only defaults. The phase
must not add real backends, provider SDKs, broad CLI flags, catalog payload
movement, or implicit downloads.

## Scope Decisions

- Bundle schema: use existing manifest extensions and payload-reference
  extensions for operation evidence; do not revise the manifest schema.
- Bundle export: add API-level opt-in materialization for selected non-local
  artifact payload refs using `ArtifactStoreBackendPayloadHandler`.
- Bundle import: preserve existing metadata-only and complete local-bundle
  behavior; no new remote import backend behavior is added.
- Bundle inspect: preserve no-extraction behavior and expose materialization
  operation evidence through manifest extensions.
- Run catalog: unchanged. Catalog scan/list remains metadata-only and
  credential-free; no catalog modules are in write scope.
- CLI: unchanged. Existing `runs export --include-artifacts` remains local-file
  payload selection; no CLI backend/materialization handler surface is added in
  this phase.
- Preflight: add a cheap readiness check for payload-operation targets that
  verifies the companion payload protocol is configured. It must not call
  payload operations or perform network/file transfer probes by default.

## In Scope

- `src/loom/runs/models.py`: add a plain `RunBundleExportOptions` opt-in flag
  for backend materialization.
- `src/loom/runs/bundles.py`: materialize selected non-local payload refs into
  staging files through a supplied payload handler before writing the archive;
  preserve operation evidence in manifest extensions.
- `src/loom/diagnostics/models.py` and `src/loom/diagnostics/preflight.py`:
  add a stable artifact backend materialization readiness check.
- Tests for metadata-only defaults, explicit fake materialization, unsupported
  materialization failure, inspect evidence, and cheap preflight behavior.

## Out Of Scope

- Real backend adapters, optional SDK dependencies, credential lifecycle,
  retries/timeouts, cleanup, provider-specific bundle schemas, catalog
  projection changes, and new CLI materialization flags.

## Validation

- Targeted runs/bundle/diagnostics/CLI contract tests:
  `uv run pytest tests/unit/loom/runs tests/unit/loom/diagnostics tests/contracts/test_run_exchange_contract.py tests/contracts/test_run_bundle_export_contract.py tests/contracts/test_run_bundle_import_contract.py tests/contracts/test_cli_runs_contract.py`
- Integration checks:
  `uv run pytest tests/integration/pipeline/test_run_bundle_export_inspect.py tests/integration/pipeline/test_run_bundle_import.py tests/integration/diagnostics/test_cli_preflight.py`
- Catalog unchanged check: no catalog code changes planned, so catalog-specific
  phase validation is deferred by design.
- Final PR gate: `make validate-pr`
- Suite evidence: `make test-summary`

## Budget Status

- Planning draft/refine: used in this artifact
- Phase implementation refinement: unused; one pass remains if validation finds
  a bounded blocker
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Implementation summary: complete. Added API-level bundle export materialization through a supplied payload handler, preserved metadata-only defaults, projected operation evidence through manifest/ref extensions, and added cheap artifact-backend materialization readiness preflight.
- Implementation validation: targeted Phase 4 suites passed; `make validate-pr` passed; `make test-summary` passed with package, unit, contract, integration, e2e, and config-extra suites green.
- PR preparation: PR body prepared in `docs/roadmap/stage-16/phases/bundle-preflight-materialization-pr-body.md`; PR open pending.
- Stack maintenance: replayed from `codex/fake-backend-payload-operations` onto updated `develop` after Phase 3 merged.
- Remaining blockers: none
