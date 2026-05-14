# Phase 3 Execution Plan: Import, Offline Alignment, And Resume Readiness

## Metadata

- Status: final phase execution plan
- Feature focus: Portable Run Exchange
- PR title: `Portable Run Exchange - Phase 3: Import And Offline Readiness`
- Branch: `codex/run-bundle-import-offline-readiness`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-bundle-import-offline-readiness`
- Phase execution plan path: `docs/roadmap/stage-12/phases/run-bundle-import-offline-readiness.md`
- Full plan: `docs/roadmap/stage-12/implementation-plan.md`
- Source phase: Phase 3, Import, Offline Alignment, And Resume Readiness
- Stack predecessor: none; Phase 2 merged to `develop`
- Base branch: `develop` via `origin/develop` at `b03d77855b783448274e03d4ec31267bb8189e6e`
- Target branch: `develop`
- Merge eligibility: merge-eligible after PR validation, automated review, CI, and target-branch verification
- Workflow path: expanded path
- Successor dependency notes: Phase 4 transfer evidence must consume shared import/export result records without parsing local bundle archives or offline evidence manifests.
- Plan quality gate: passed on 2026-05-14 in the implementation plan
- Plan quality gate loop budget: review used, refinement used, confirmation used
- Draft pass: completed by managing Codex
- Refine pass: included in this scope-complete expanded-path plan; no separate refinement pass needed unless implementation discovers a target identity or offline-import compatibility blocker
- Setup limitations: none; branch/worktree created from updated `origin/develop`
- Blockers: none

## Objective

Implement safe local bundle import and align v10 offline-evidence import with the Phase 1 portable importer/result contracts. Imported bundle runs must use target-local identity, preserve source identity and provenance, reject collisions, remain historical-only, and report resume-readiness blockers.

## Full-Plan Context

Phase 2 added local bundle export and inspect helpers. This phase is the import counterpart and the compatibility bridge for v10 offline evidence. It must reuse the Phase 2 archive safety decisions, keep offline evidence as an authority adapter rather than converting it into a bundle, and avoid adding CLI or queue behavior.

## Stack Context

- Root or stacked phase: root phase after Phase 2 merge
- Current predecessor branch or PR: none
- Why this base branch is correct: Phase 2 PR #147 is merged and post-merge metadata is pushed to `develop`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: branch can be deleted after merge only when no successor branch depends on it

## Source Phase Summary

- Goal: safe import, offline-evidence alignment, source provenance, target-local identity, collision rejection, and historical-only readiness blockers.
- Required scope: local bundle import adapter, offline evidence result adapter/wrapper, importer protocol conformance, readiness records, collision/checksum diagnostics, and catalog refresh after successful local import.
- Required checkpoints: unsafe bundles and checksum mismatches reject before target writes; target collision rejects; offline evidence keeps v10 strict behavior while returning shared import result semantics; imported runs are historical-only with blocker records.
- Acceptance criteria: bundle and offline-evidence import paths conform to `RunImporter`; offline evidence is not serialized through bundles; import results report target URI, provenance, imported counts, diagnostics, and readiness blockers.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/runs/bundles.py` owns local bundle archive constants and safety helpers; `src/loom/runs/models.py` owns import records, policies, results, and readiness blockers; `src/loom/pipeline/stores/local_runs.py` can write local historical run documents; `src/loom/authority/offline_import.py` owns v10 offline import validation and authority mutation.
- Existing tests or harness behavior: Phase 2 bundle tests cover safe inspect and export; offline-import unit/integration/contract tests cover strict v10 behavior; run-catalog integration tests cover local collection refresh and sidecar rebuilding.
- Import-boundary constraints: new public `loom.runs` import helpers must avoid top-level authority, CLI, queue, plugin, optional-client, and execution imports. Authority/offline import must not import local bundle archive internals.

## In-Scope Work

- Add import helpers and local bundle importer APIs under `loom.runs`, with lazy imports for store and authority modules.
- Build `PortableRunImportRecord` values from inspected local bundle manifests.
- Implement a local bundle importer conforming to `RunImporter`.
- Import bundle metadata into a target local run collection using target-local run URI allocation derived from source identity with collision rejection.
- Materialize selected bundle payload members as regular target-local files only after manifest/member/checksum validation succeeds.
- Record source identity, bundle identity, target identity, and historical-only import provenance in local run metadata/runtime facts.
- Refresh or rebuild the local run catalog after successful local bundle import.
- Add readiness blockers for historical-only policy, source collision, missing payloads, checksum mismatch, unsupported schema, and unrebaseable artifact URI where applicable.
- Add offline-evidence adapter/wrapper functions that preserve existing strict validation and authority mutation while returning `RunBundleImportResult` semantics.

## Out-of-Scope Work

- Live migrated resume.
- Merge, fork, overwrite, reuse, or sync import policies.
- CLI commands or formatting.
- Queue transfer evidence.
- Remote payload materialization, credentials, provider plugins, network transfers, signing, encryption, dedupe, or synchronization.
- Moving authority mutation into local bundle code.
- Changing the Phase 1 `RunImporter` protocol shape.

## Assumptions

- Target-local identity can derive a deterministic safe directory name from the source run URI basename for v12, and collision policy remains strict reject.
- Local bundle import can reconstruct enough local run-store documents from `manifest.extensions["completed_run"]` to support catalog inspection without claiming executable resume.
- Payload rebasing is limited to selected local bundle entries in this phase; unresolved or external source refs remain provenance/readiness facts rather than executable artifact refs.
- Offline evidence remains imported through `loom.authority.offline_import`; `loom.runs` only adapts result shapes and diagnostics.

## Scope Contract

Bundle import must validate before commit, write through a temporary staging directory, and atomically promote only when the full import is accepted. Inspection and checksum diagnostics must be structured in `RunExchangeDiagnostic` records. Target writes must not preserve the source run URI as active target identity. Offline-evidence alignment must call existing authority-owned validation/mutation paths and must not make offline evidence a local bundle format.

## Design Impact

- Maintainability: import path stays separate from export while reusing Phase 2 archive safety and Phase 1 result contracts.
- Extensibility: readiness blockers describe why imported history is non-resumable without introducing live resume behavior.
- Domain neutrality: imported metadata and payload refs stay generic run/stage/artifact facts.
- Source-tree boundaries: local bundle import lives in `loom.runs`; authority offline import stays in `loom.authority`; queue and CLI remain untouched.

## Future Compatibility

Later live migration can consume readiness blockers only after target equivalence, artifact URI rebasing, and planner reuse policy are designed. Later provider adapters can implement the same `RunImporter` protocol without depending on local bundle archives or offline-evidence manifests.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Preserve source `run_uri` as active target identity | It creates collisions and confuses source audit identity with target executable identity. |
| Convert offline evidence into bundle archives | It weakens v10 authority validation and violates the adapter separation in the plan. |
| Best-effort import with partial target state | Import safety requires fail-closed behavior and no partial committed target run. |
| Overwrite or merge collisions | Only strict rejection was accepted for v12. |
| Mark imported runs resumable | Live migrated resume is explicitly deferred. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Target-local naming is conservative and deterministic | It enables collision rejection without designing fork/merge policies. | A later stage adds fork, reuse, or workspace mapping policy. |
| Artifact URI rebasing remains limited | v12 cannot prove remote/external payload equivalence or live continuation. | Target-store equivalence and artifact rebasing policy are designed. |
| Offline evidence keeps compatibility wrapper code | Existing v10 behavior must remain stable while shared result semantics land. | Offline import can natively emit shared import results without compatibility risk. |

## Reviewability

- Expected PR size and shape: import helpers, offline result adapter, public exports, and focused unit/contract/integration tests.
- Files and areas to inspect: `src/loom/runs`, `src/loom/authority/offline_import.py` only if result adapters need tiny compatibility helpers, `tests/unit/loom/runs`, `tests/contracts`, `tests/integration/pipeline`, `tests/unit/loom/authority`, and package boundary tests.
- Scope-control checks: no CLI, no queue evidence, no live resume, no remote providers, no plugin loading, no protocol widening, no overwrite/merge import policy.

## Implementation Steps

1. Add local bundle import record builders, readiness helpers, diagnostics mapping, and target-local run URI derivation.
2. Add safe bundle payload/member validation and temporary staging/promotion for local target collection imports.
3. Implement local bundle importer protocol conformance and public `loom.runs` import helpers.
4. Add offline-evidence import adapter/wrapper that maps existing accepted/rejected v10 results to `RunBundleImportResult` without importing archive helpers into authority.
5. Add catalog refresh after successful local import and regression tests for collision, checksum, unsafe member, readiness, and v10 offline evidence compatibility.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_runs_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: `loom.runs` stays lightweight; authority/offline import does not import bundle archive helpers; queue/CLI/plugins remain decoupled.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/runs/test_bundle_import.py`, `tests/unit/loom/authority/test_offline_import.py` if wrapper helpers touch authority result mapping
- Required assertions or deferral reason: import policy rejection, target URI derivation, readiness blocker construction, diagnostic mapping, no partial staging promotion on failure.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_run_bundle_import_contract.py`, existing run exchange contract updates
- Required assertions or deferral reason: local bundle and offline evidence importers conform to `RunImporter`; result envelopes remain plain-data compatible; unsupported/unsafe diagnostics are structured.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_run_bundle_import.py`, `tests/integration/authority/test_offline_import_api.py` if needed
- Required assertions or deferral reason: export/import round trip into a temporary collection, collision rejection, checksum mismatch rejection before commit, catalog refresh, and offline evidence regression behavior.

### E2E Suite

- Status: deferred
- Expected paths: none
- Required assertions or deferral reason: CLI workflow starts in Phase 5.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no network, cluster, plugin, or external provider behavior is in scope.

## Risks

- Local bundle import could accidentally claim executable resume support by writing too much active state.
- Offline-evidence alignment could introduce import cycles or weaken v10 rejection behavior.
- Payload rebasing could make copied artifact files look more authoritative than the imported historical provenance supports.
- Staging cleanup bugs could leave partial target directories after failed imports.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/runs/test_bundle_import.py tests/contracts/test_run_bundle_import_contract.py tests/integration/pipeline/test_run_bundle_import.py tests/package/test_runs_api.py tests/package/test_import_boundaries.py tests/unit/loom/authority/test_offline_import.py tests/integration/authority/test_offline_import_api.py
uv run ruff check src/loom/runs src/loom/authority/offline_import.py tests/unit/loom/runs/test_bundle_import.py tests/contracts/test_run_bundle_import_contract.py tests/integration/pipeline/test_run_bundle_import.py
uv run --extra config pyright src/loom/runs src/loom/authority/offline_import.py tests/unit/loom/runs/test_bundle_import.py tests/contracts/test_run_bundle_import_contract.py tests/integration/pipeline/test_run_bundle_import.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For Implementation

- Safe implementation slices: import record/readiness helpers first, local target staging/import second, offline result adapter third, package/integration tests alongside each slice.
- Tests to run with each slice: unit helper tests after record/readiness helpers, contract tests after importer conformance, integration tests after local collection import, offline-import regressions after adapter wrapping.
- Decisions implementation must not revisit: no live resume, no source identity as active target identity, no overwrite/merge/fork policies, no offline-evidence-to-bundle conversion, no protocol widening, no CLI.
- Conditions that require stopping for the manager: inability to import without partial target writes, a necessary change to v10 offline-import public behavior, or an import boundary that would force authority to import bundle archive helpers.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in the Phase 3 worktree.
- Final phase execution plan: completed; no separate refinement pass used.
- Implementation summary:
- Implementation validation:
- Refinement summary:
- Blocker-resolution summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers:
