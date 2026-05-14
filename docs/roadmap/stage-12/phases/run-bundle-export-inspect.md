# Phase 2 Execution Plan: Export, Archive Safety, And Inspect

## Metadata

- Status: pr_open
- Feature focus: Portable Run Exchange
- PR title: `Portable Run Exchange - Phase 2: Export And Inspect Bundles`
- Branch: `codex/run-bundle-export-inspect`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-bundle-export-inspect`
- Phase execution plan path: `docs/roadmap/stage-12/phases/run-bundle-export-inspect.md`
- Full plan: `docs/roadmap/stage-12/implementation-plan.md`
- Source phase: Phase 2, Export, Archive Safety, And Inspect
- Stack predecessor: none; Phase 1 merged to `develop`
- Base branch: `develop` via `origin/develop` at `c1228f521e92f6f26aef4d90b70bd6498ed9f45c`
- Target branch: `develop`
- Merge eligibility: merge-eligible after PR validation, automated review, CI, and target-branch verification
- Workflow path: expanded path
- Successor dependency notes: Phase 3 import must reuse Phase 2 archive safety and inspect helpers without adding export-side protocol changes.
- Plan quality gate: passed on 2026-05-14 in the implementation plan
- Plan quality gate loop budget: review used, refinement used, confirmation used
- Draft pass: completed by managing Codex
- Refine pass: included in this scope-complete expanded-path plan; no separate refinement pass needed unless implementation discovers an archive-safety contract blocker
- Setup limitations: none; branch/worktree created from updated `origin/develop`
- PR: [#147](https://github.com/samcantrill/loom/pull/147)
- Blockers: none

## Objective

Implement local bundle export and inspection over the Phase 1 portable exchange contracts: build metadata-only portable export records from completed-run facts, materialize strict local bundle manifests and archives with safe member handling, and inspect bundles without extracting them.

## Full-Plan Context

Phase 1 established the model and protocol contracts. This phase provides the first concrete local bundle exporter and read-only inspector. Phase 3 will implement import using these archive-safety decisions, Phase 4 will add queue-consumable transfer evidence behavior, and Phase 5 will add CLI/docs. This phase must not import bundles into run collections, align offline evidence, add CLI commands, or widen the `RunExporter`/`RunImporter` protocol shapes.

## Stack Context

- Root or stacked phase: root phase after Phase 1 merge
- Current predecessor branch or PR: none
- Why this base branch is correct: Phase 1 PR #146 is merged and post-merge metadata is pushed to `develop`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: branch can be deleted after merge only when no successor branch depends on it

## Source Phase Summary

- Goal: implement metadata-only export by default, explicit payload/log inclusion, archive member safety, checksum/size reporting, and inspect without extraction.
- Required scope: portable export-record assembly from `CompletedRunBundleMetadata`, local bundle exporter adapter, manifest materialization, standard-library archive helpers, structured diagnostics, inspection API, and public `loom.runs` or `RunCatalog` convenience entrypoints.
- Required checkpoints: prove default export omits payload bytes, explicit payload/log options include only safe selected refs, unsafe archive members are diagnosed, and inspection reads manifests without extraction.
- Acceptance criteria: synthetic completed runs export through portable records into local bundles; inspect reports manifest/run/status/stage/artifact/payload/warning facts; archive safety failures return structured diagnostics.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/runs/models.py` owns Phase 1 exchange and manifest records; `src/loom/runs/catalog.py` is the public facade; `src/loom/pipeline/stores/materialization_read_models.py` provides `CompletedRunBundleMetadata`, `MaterializedRef`, and `read_completed_run_bundle_metadata`; `src/loom/runs/__init__.py` exports the public runs surface.
- Existing tests or harness behavior: Phase 1 contract/unit/package tests lock plain-data record shapes and lightweight `loom.runs` imports; materialization read-model tests prove completed-run metadata and local refs can be read without payload loading.
- Import-boundary or dependency constraints: archive/export helpers may import standard-library archive/path/hash modules and store read models where needed, but authority/offline import, queue control modules, CLI, plugins, and optional clients must not import local bundle archive internals.

## In-Scope Work

- Add local bundle archive/write/read helpers using the standard library.
- Add path normalization and archive member validation for traversal, absolute paths, unsafe symlink entries, duplicates, and member collisions.
- Build `PortableRunExportRecord` and `RunBundleManifest` values from `CompletedRunBundleMetadata`.
- Implement a local bundle exporter conforming to `RunExporter`.
- Implement public export and inspect APIs under `loom.runs`, plus `RunCatalog` convenience methods if they stay thin.
- Include checksum and size facts for selected local file refs without reading unselected payload bytes.
- Add structured diagnostics for missing payloads, checksum mismatch, unsafe members, unsupported manifests, unexpected payload selections, and active-run-change warnings.

## Out-of-Scope Work

- Importing bundles into run collections or authority.
- Offline evidence alignment.
- CLI commands or formatting.
- Remote payload download, credential handling, external ref validation, signing, encryption, compression dependencies, dedupe, or synchronization.
- Queue consumption or transfer-handler behavior.
- Any protocol widening beyond the Phase 1 exporter contract.

## Assumptions

- The first archive format can use a standard-library tar archive with a strict JSON manifest member at a stable path, as long as inspect does not extract.
- Metadata-only export can still write the manifest archive entry; payload/log bytes are included only when the caller explicitly selects them.
- Non-file or external refs remain opaque metadata in v12 and are not materialized into the archive.

## Scope Contract

Export must first assemble portable exchange records and then materialize the local bundle adapter. Manifest JSON remains the persisted contract; archive layout is adapter-specific and must not become the provider protocol. Inspect must open and validate the manifest/member table without extracting any archive member. Unsafe paths, symlink surprises, duplicates, unsupported manifest versions, checksum mismatches, missing selected files, and active-run-changed warnings must be represented as `RunExchangeDiagnostic` records or fail closed before claiming success.

## Design Impact

- Maintainability: separates portable record construction, manifest building, and archive safety helpers so Phase 3 import can reuse validation without duplicating export logic.
- Extensibility: keeps remote/external refs as opaque manifest data and leaves future materialization handlers outside this local adapter.
- Domain neutrality: records local run/stage/artifact/log payload facts only; no domain-specific artifact semantics.
- Source-tree boundaries: archive behavior lives with `loom.runs`; stores provide read models; CLI remains untouched.

## Future Compatibility

Later import can reuse the same member normalization and manifest reader. Later transfer handlers can populate transfer evidence without parsing queue-owned schemas. Future remote stores can attach behavior to opaque refs without changing local bundle manifest fundamentals.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Include all payloads by default | Violates the confirmed metadata-only default and can move large data unexpectedly. |
| Inspect by extracting to a temporary directory | Increases path/symlink risk and is unnecessary for manifest inspection. |
| Add compression or third-party archive dependencies | No concrete v12 need justifies more dependencies. |
| Accept unsafe archive members best-effort | Conflicts with fail-closed inspection/import safety. |
| Let the archive format become the provider protocol | Conflicts with the Phase 1 portable exchange boundary. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Local bundle remains the only concrete storage adapter | v12 defers remote stores, transfer handlers, signing, encryption, dedupe, and sync. | A later stage selects a concrete non-local transport or storage adapter. |
| Archive layout is intentionally minimal | The manifest is the stable contract; more archive conveniences would be speculative. | Import, CLI, or external adapter work proves a stable additional member is needed. |

## Reviewability

- Expected PR size and shape: focused export/inspect implementation plus archive-safety and integration tests.
- Files and areas to inspect: `src/loom/runs`, `tests/unit/loom/runs`, `tests/contracts`, `tests/integration/pipeline` or `tests/integration/runs`.
- Scope-control checks: no import commit behavior, no offline evidence changes, no CLI registration, no queue parsing, no provider-specific clients, and no new runtime dependencies.

## Implementation Steps

1. Add bundle archive constants, manifest JSON helpers, archive member normalization, checksum/size helpers, and diagnostics mapping.
2. Add portable export-record and manifest builders from `CompletedRunBundleMetadata` and selected `MaterializedRef` values.
3. Implement the local bundle exporter and public export/inspect APIs, keeping `RunCatalog` methods as thin convenience wrappers if added.
4. Add unit and contract tests for manifest building, path/member safety, payload selection, checksum/size diagnostics, and inspection result shape.
5. Add integration tests over temporary completed runs and unsafe bundle fixtures, then run package-boundary checks.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_runs_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: public exports remain intentional and lightweight; lower layers and queue/CLI modules do not import local bundle archive internals.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/runs/test_bundle_export.py` or equivalent
- Required assertions or deferral reason: path normalization, unsafe member rejection, manifest building, payload-selection defaults, checksum/size diagnostics, and inspect-without-extraction helpers.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_run_bundle_export_contract.py` or equivalent
- Required assertions or deferral reason: local exporter conforms to `RunExporter`; inspection result shape remains plain-data compatible; unsupported/unsafe diagnostics are structured.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_run_bundle_export_inspect.py` or nearest existing convention
- Required assertions or deferral reason: export/inspect over temporary completed runs, metadata-only default, explicit payload/log inclusion, and unsafe archive fixtures.

### E2E Suite

- Status: deferred
- Expected paths: none
- Required assertions or deferral reason: CLI workflow starts in Phase 5.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no network, cluster, plugin, or external provider behavior is in scope.

## Risks

- Archive helper bugs can become import data-loss risks in Phase 3.
- Export might accidentally treat local materialization as authority truth instead of projection evidence.
- Public API shape could grow too broad if convenience functions duplicate future CLI/import behavior.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/runs tests/contracts/test_run_bundle_export_contract.py tests/integration/pipeline/test_run_bundle_export_inspect.py tests/package/test_runs_api.py tests/package/test_import_boundaries.py
uv run ruff check src/loom/runs tests/unit/loom/runs tests/contracts/test_run_bundle_export_contract.py tests/integration/pipeline/test_run_bundle_export_inspect.py
uv run --extra config pyright src/loom/runs tests/unit/loom/runs tests/contracts/test_run_bundle_export_contract.py tests/integration/pipeline/test_run_bundle_export_inspect.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: archive safety helpers first, manifest/export-record builders second, local exporter/API third, tests alongside each slice.
- Tests to run with each slice: unit safety tests after helpers, contract tests after exporter conformance, integration tests after public API wiring.
- Decisions the executor must not revisit: no import behavior, no CLI, no offline evidence refactor, no queue behavior, no protocol widening, no non-standard archive dependency.
- Conditions that require stopping for the manager: need to change Phase 1 protocol signatures, inability to inspect safely without extraction, or an import-boundary failure requiring moving public model placement.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in the Phase 2 worktree.
- Final phase execution plan: completed; no separate refinement pass used.
- Implementation summary: added local bundle export/inspect helpers under
  `loom.runs`, metadata-backed portable export-record assembly, a
  `LocalRunBundleExporter` conforming to the Phase 1 `RunExporter` protocol,
  traversal-safe archive member validation, metadata-only default exports,
  explicit selected-payload materialization as regular archive members, and
  inspect-without-extraction checksum diagnostics.
- Implementation validation: targeted Phase 2 pytest set passed with 51 tests;
  targeted Ruff passed; targeted Pyright passed; `make validate-pr` passed
  outside the sandbox; `make test-summary` passed with overall 1918 passed, 0
  failed, 0 errors, 18 skipped, and 1505 deselected.
- Refinement summary: no `loom_phase_refiner` pass used; local implementation
  fixes addressed duplicate diagnostics, computed checksum algorithms, and
  plain-data manifest extension thawing before full validation.
- Blocker-resolution summary: 0/3 blocker-resolution passes used; no blockers
  remain.
- PR preparation: PR body drafted at
  `docs/roadmap/stage-12/phases/run-bundle-export-inspect-pr-body.md`; PR #147
  opened against `develop` and verified with base `develop`, head
  `codex/run-bundle-export-inspect`, state `OPEN`.
- Stack maintenance: root PR targets `develop`; no successor branch depends on
  this branch yet.
- Remaining blockers: none.
