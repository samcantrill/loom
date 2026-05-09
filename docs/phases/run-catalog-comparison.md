# Phase 5 Execution Plan: Metadata Comparison API

## Metadata

- Status: implemented; PR pending
- Feature focus: Run Catalog And Comparison
- PR title: `Run Catalog And Comparison - Phase 5: Metadata Comparison API`
- Branch: `codex/run-catalog-comparison`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-catalog-comparison`
- Phase execution plan path: `docs/phases/run-catalog-comparison.md`
- Full plan: `docs/implementation-plans/implementation-plan-v8.md`
- Source phase: Phase 5 - Metadata Comparison API
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- PR: pending creation
- Merge eligibility: merge-eligible after implementation, implementation refinement, automated PR review, local validation, and GitHub checks because Phases 1 through 4 are merged and this is a root phase targeting `develop`
- Workflow path: expanded path because this phase introduces public comparison behavior and durable comparison semantics
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v8.md` on 2026-05-09; the plan records initial review, refinement, and confirmation review as complete.
- Plan quality gate loop budget: initial review used; gate refinement used; confirmation review used.
- Draft pass: completed by `loom_phase_planner`
- Refine pass: completed in this planning artifact for the expanded path; no unresolved blockers remain.
- Phase implementation refinement budget: not needed; no refiner pass used because focused validation, `make validate-pr`, and `make test-summary` passed.
- Phase PR review budget: unused; one automated `loom_phase_reviewer` or equivalent manager review remains required before merge.
- Blocker-resolution budget: unused, 0 of 3 scoped passes consumed.
- Setup notes: branch and worktree were created from local `develop` at commit `62174a0` (`docs: record v8 phase 4 merge`). Creating the branch/worktree required approved local Git metadata writes after sandboxed Git ref creation failed.
- Blockers: none

## Objective

Implement the public Python metadata comparison API for two runs in a local collection. `RunCatalog.compare(left, right)` must return a structured `RunComparison` built from persisted Loom metadata only, using stable comparison sections and entry statuses without importing project code, loading artifact payloads, or adding CLI behavior.

## Full-Plan Context

V8 treats run-store metadata as authoritative and the SQLite catalog as a private derived sidecar. Phase 1 delivered the public `loom.runs` models, including `RunComparison`, `ComparisonSection`, `ComparisonEntry`, and `ComparisonStatus`. Phase 2 delivered direct current summary extraction from authoritative run-store metadata. Phase 3 delivered private SQLite rebuild storage. Phase 4 delivered current `RunCatalog.list()` behavior backed by refresh-on-read catalog reconciliation.

This phase connects those existing pieces into comparison behavior. It may add private comparison helpers and narrowly extend public model validation if required for stable JSON output, but it must not expand Loom into a domain comparison engine.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phases 1 through 4 are merged into `develop`
- Why this base branch is correct: the assignment requires current `develop`, and `develop` contains the public models, current list API, direct extraction helpers, and sidecar storage needed by comparison.
- Retarget/rebase plan after predecessor merge: none; PR targets `develop` directly.
- Branch cleanup constraints: branch may be deleted after merge if no successor branch is stacked on it.

## Source Phase Summary

- Goal: implement metadata-only run comparison through the public Python API.
- Required scope: `RunCatalog.compare(left, right)` or equivalent facade behavior; comparison of persisted metadata for run status/timestamps, config and pipeline fingerprints, stage status and fingerprints, artifact identities/checksums, executor/backend identity, and selected provenance facts such as git commit and command/runtime summaries; current summaries and targeted direct extraction where needed; structured sections and entries using `same`, `different`, `left_only`, `right_only`, and `unknown`; warnings for missing, unsupported, or unreadable comparison inputs.
- Required exclusions: no artifact payload diffs, domain metric interpretation, binary/report/notebook diffs, plugin comparison hooks, or CLI diff command.
- Acceptance criteria:
  - `RunCatalog.compare(left, right)` returns a structured metadata comparison.
  - Missing or unsupported metadata becomes explicit comparison output or warnings rather than domain-specific failures.
  - Comparison does not import project code or load artifact payloads.
  - Comparison output serializes cleanly for future CLI JSON presentation.

## Current Source And Harness Findings

- `src/loom/runs/catalog.py` exposes `RunCatalog.compare()` as a deferred method raising `CatalogFeatureUnavailableError`.
- `src/loom/runs/models.py` already defines immutable public comparison models and the stable status vocabulary: `same`, `different`, `left_only`, `right_only`, and `unknown`.
- `RunSummary` already contains the metadata this phase should compare: status and timestamps; config, pipeline, and git fingerprints; executor and backend; stage summaries; artifact summaries; submitted-operation summaries; tags and plain user metadata when intentionally selected.
- `RunCatalog.list()` returns current summaries with warnings and deterministic `run_uri` ordering. Comparison can use this current API or direct extraction for target resolution, but it must preserve current-read semantics for both sides.
- `src/loom/runs/_extract.py` reads selected provenance documents and runtime metadata into summaries without project-code imports or artifact payload reads.
- `docs/features/run-catalog.md` defines comparison as metadata, fingerprints, checksums, artifact logical names, and stage status records, while excluding payload, domain metric, binary diff, and notebook rendering behavior.
- Existing package and unit tests assert comparison model exports and deferred compare behavior; implementation should replace the deferred-method expectation with real behavior and contract coverage.

## In-Scope Work

- Implement `RunCatalog.compare(left, right) -> RunComparison`.
- Accept run selectors that are already valid public run identities for v8 comparison. Prefer canonical `run_uri` strings. If implementation supports local path-like selectors, normalize them to `run_uri` before populating `RunComparison`; do not add a broad selector language.
- Resolve both sides through current catalog behavior or targeted direct extraction so comparison does not use stale sidecar rows. Warnings from resolution must be preserved in the comparison result.
- Add a private comparison module, expected as `src/loom/runs/_compare.py`, to keep facade code small and comparison semantics isolated from SQLite storage.
- Produce stable sections in this order unless implementation discovers a stronger existing convention:
  - `run`: status, created/updated/started/finished timestamps, display names only if useful as presentation metadata.
  - `fingerprints`: config fingerprint, pipeline fingerprint, and any run-level fingerprint-like values already exposed in `RunSummary`.
  - `stages`: stage presence by stage name, stage status, stage attempt when useful, stage fingerprint, and stage timestamps.
  - `artifacts`: artifact presence by logical name or artifact id, artifact URI only as metadata, artifact type, checksum, fingerprint, and producer stage.
  - `execution`: executor, backend, and submitted-operation summaries that are already persisted as metadata.
  - `provenance`: selected generic facts already surfaced in summaries, especially git commit and command/runtime summaries if available without raw metadata dumps.
- Use `ComparisonEntry.key` as a compact dotted path such as `run.status`, `stages.train.status`, `artifacts.metrics.checksum`, or `provenance.git.commit`. Do not expose raw persisted document paths as the public contract.
- Status semantics:
  - `same`: both sides have comparable known values and they are equal.
  - `different`: both sides have comparable known values and they differ.
  - `left_only`: the field or keyed child exists only for the left run.
  - `right_only`: the field or keyed child exists only for the right run.
  - `unknown`: one or both values cannot be known from supported metadata, or a value is present but intentionally unsupported for comparison.
- Treat missing optional scalar metadata as `unknown` only when the field is expected but not available on one or both sides. Treat keyed child presence, such as a stage or artifact that exists on only one side, as `left_only` or `right_only`.
- Preserve `run_uri` as canonical identity in `RunComparison.left_run_uri` and `right_run_uri`.
- Populate `checked_at` with the comparison evaluation timestamp or the freshest timestamp from current-summary resolution according to existing timestamp conventions.
- Surface ordinary missing, unreadable, disappeared, actively-changing, partial, unsupported-schema, stale/corrupt-catalog, and unrecoverable-catalog conditions through existing `CatalogWarning` codes where possible. Do not invent a second warning taxonomy.
- Add narrowly focused helpers for deterministic ordering and duplicate-key handling for stages, artifacts, and submitted operations. If duplicate logical artifact names are possible, prefer stable identity keys that avoid collapsing distinct records.
- Update package, unit, contract, and integration tests for public compare behavior and serialization.

## Out-of-Scope Work

- CLI `loom runs diff`, `loom diff`, command output formatting, exit-code behavior, or docs for command usage.
- Artifact payload reads, checksum recomputation from payloads, binary diffs, report diffs, notebook rendering, or domain metric interpretation.
- Plugin or project-owned comparison hooks.
- Public SQL schema changes, public storage helpers, or external SQL query support.
- New catalog read modes, selector languages, filter semantics, pagination, sorting controls, or remote catalog behavior.
- Runner, executor, or run-store writes to the collection catalog database.
- Broad changes to public value models beyond what is strictly required to make existing comparison models useful and serializable.

## Assumptions

- The comparison inputs for Phase 5 are run URI strings. Supporting path-like inputs is optional and must not weaken canonical `run_uri` output.
- `RunCatalog.list()` can be used to obtain current summaries for both sides when efficient enough. A targeted direct extraction helper is acceptable if it avoids a full collection scan without bypassing freshness validation.
- The first comparison API does not need to expose a public section-selection option. Section extensibility is handled by adding sections later.
- Generic user metadata is not compared wholesale. Only stable, intentionally selected facts should become comparison entries.
- Submitted-operation comparison can start with stable persisted summary fields and avoid attempting scheduler-specific interpretation.
- Existing `ComparisonEntry.details` is sufficient for small metadata annotations such as artifact id, logical name, stage name, or unsupported reason.

## Scope Contract

`RunCatalog.open(path).compare(left, right)` must compare two current run summaries from the catalog collection and return a `RunComparison` whose entries explain generic Loom metadata differences without reading artifact payloads or project code.

The comparison contract is:

- both run identities are resolved to canonical `run_uri` values;
- each side is validated through current catalog/list behavior or the same freshness-validated direct extraction used by catalog reads;
- ordinary invalid or uncertain inputs are represented by warnings and/or `unknown` entries where a partial comparison is still meaningful;
- unrecoverable catalog or store errors may raise existing catalog errors, but must not mutate run-store truth;
- section and entry ordering is deterministic for stable contract and future CLI JSON tests;
- comparison semantics are bounded to metadata available at evaluation time and do not claim continuous freshness after the result is returned.

## Risky Decisions

- Public selector semantics: keep inputs narrow and canonical. A broad selector language would be hard to keep stable and belongs in a later user-facing CLI/API design.
- Missing metadata semantics: distinguish keyed child absence (`left_only`/`right_only`) from unavailable optional scalar facts (`unknown`) so output does not overstate differences.
- Artifact comparison keys: use stable artifact identity when logical names are absent or duplicated; do not collapse multiple artifacts into one human-friendly label.
- Provenance scope: compare selected generic facts only. Avoid raw provenance dumps because they would freeze internal document structure and blur domain boundaries.
- Currentness source: comparison must not read stale SQLite rows directly. If full `list()` is too expensive for targeted comparison, implementation should reuse freshness-validated extraction rather than introducing a stale fast path.
- Public JSON shape: preserve existing `RunComparison.to_dict()` and `ComparisonEntry` fields. Additive details are allowed, but avoid model churn that would force Phase 6 CLI to special-case comparison.

## Design Impact

- Maintainability: comparison semantics live behind `RunCatalog.compare()` and private helpers, avoiding duplicated logic in future CLI code.
- Extensibility: future plugin or project-owned comparison hooks can add sections without changing core status meanings or existing metadata sections.
- Domain neutrality: core comparison remains limited to Loom metadata, fingerprints, checksums, statuses, and selected generic provenance.
- Source-tree boundaries: `loom.runs` may consume run-store inspection and existing summary models, but must not import project packages, CLI presentation code, runner implementation details, or executor-specific domain behavior.
- Public compatibility: this phase turns previously placeholder comparison models into an API contract, so section names, entry keys, status semantics, and serialization need focused review.

## Future Compatibility

The initial comparison result should be compact and stable enough for Phase 6 CLI JSON output while remaining additive for v9 bundles, v10 sweeps, and future plugin/project comparison sections. New sections, entry keys, and details may be added later, but the five comparison statuses and canonical `run_uri` identity should remain compatible.

If future remote catalogs or imported bundles provide equivalent summaries, comparison should be able to reuse the same `RunSummary`-to-`RunComparison` helper without depending on local SQLite internals.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Raw metadata dump comparison | Freezes internal persisted document shapes, creates noisy output, and makes future CLI formatting brittle. |
| Artifact payload or binary comparison | Violates v8 non-goals and can be expensive or domain-specific. |
| Domain metric comparison in core Loom | Breaks the project-code boundary; project or plugin hooks can own this later. |
| CLI-first diff behavior | Python API is the v8 compatibility center; CLI wrappers arrive in Phase 6. |
| Public SQL-based comparison | Bypasses current-read and warning semantics while exposing private sidecar schema. |
| Treating all missing values as differences | Overstates optional unsupported metadata; `unknown` is required for incomplete persisted facts. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Comparison is limited to persisted metadata and selected generic provenance. | Keeps Loom domain-neutral and safe without project imports or payload reads. | Users need domain-specific comparisons; add plugin or project-owned sections. |
| Section and key names become a public-ish JSON contract before CLI text design exists. | Phase 6 needs stable API output to wrap. | CLI or consumers find keys too verbose/ambiguous; adjust only additively after review. |
| Input selector support remains narrow. | Canonical `run_uri` identity is the stable v8 contract. | Users need ergonomic non-CLI API selectors for paths, display names, or filters. |
| Duplicate artifact/stage identity handling may produce less friendly keys. | Correctness and non-collapsing behavior matter more than display polish in the first API. | CLI UX needs aliases while preserving stable machine keys. |

## Reviewability

- Expected PR size and shape: focused facade change, private comparison helper, and tests. No CLI, payload comparison, plugin hook, public SQL, runner, executor, or broad model rewrite.
- Files and areas to inspect:
  - `src/loom/runs/catalog.py`
  - new `src/loom/runs/_compare.py`
  - `src/loom/runs/models.py` only for narrowly justified validation or export adjustments
  - `src/loom/runs/_extract.py` or `_sqlite.py` only if targeted current-summary resolution needs small reusable hooks
  - `tests/package/test_runs_api.py`
  - `tests/unit/loom/runs/test_run_catalog_models.py`
  - new or updated `tests/unit/loom/runs/test_comparison.py`
  - contract coverage for comparison `to_dict()` shape
  - integration coverage over temporary local collections
- Scope-control checks: no CLI modules, no artifact payload reads, no project imports, no plugin hook framework, no public SQL exports, no direct stale-row comparison, and no runner/executor writes to `.loom_catalog`.

## Implementation Steps

1. Replace the deferred `RunCatalog.compare()` facade with a typed method that delegates to private comparison logic and returns `RunComparison`.
2. Add private comparison helpers that resolve each side to current summaries and aggregate warnings without bypassing freshness validation.
3. Implement deterministic scalar, keyed-stage, keyed-artifact, execution, and selected-provenance comparison entry builders.
4. Define stable section and entry ordering with focused unit tests before broad integration fixtures.
5. Add integration fixtures for identical runs, different fingerprints, left-only/right-only stages, left-only/right-only artifacts, unsupported or partial records, and warning propagation.
6. Update package and deferred-method tests to assert real compare behavior and cheap public imports.

These are implementation checkpoints, not a file-by-file recipe. The executor should follow existing local patterns if source shape changes before implementation begins.

## Implementation Summary

- Replaced the deferred `RunCatalog.compare()` placeholder with a typed public method that refreshes through current `RunCatalog.list()` behavior and delegates comparison semantics to private helpers.
- Added `src/loom/runs/_compare.py` to build deterministic metadata-only `RunComparison` sections for run facts, fingerprints, keyed stages, keyed artifacts, execution/submitted-operation summaries, and selected provenance.
- Preserved current-read warnings in comparison results and added missing-side `DISAPPEARED_RUN` warnings when requested run URIs are absent from current summaries.
- Kept comparison scoped to persisted summary metadata. The implementation does not read artifact payloads, import project code, add CLI behavior, expose SQL, or add plugin hooks.
- Added package-adjacent unit coverage, a public serialization contract test, and integration coverage for identical runs, metadata differences, one-sided stages/artifacts, missing inputs, and partial-run warning propagation.

## Validation Evidence

Focused validation:

- `uv run ruff check src/loom/runs tests/unit/loom/runs tests/contracts/test_run_catalog_comparison_contract.py tests/integration/pipeline/test_run_catalog_compare.py` passed.
- `uv run pyright src/loom/runs tests/unit/loom/runs tests/contracts/test_run_catalog_comparison_contract.py tests/integration/pipeline/test_run_catalog_compare.py` passed with 0 errors, 0 warnings, 0 informations.
- `uv run pytest tests/package/test_runs_api.py tests/package/test_import_boundaries.py tests/unit/loom/runs tests/contracts/test_run_catalog_comparison_contract.py tests/integration/pipeline/test_run_catalog_compare.py tests/integration/pipeline/test_run_catalog_current_list.py` passed: 58 passed in 41.76s.
- `uv run pytest tests/unit/loom/runs/test_comparison.py tests/unit/loom/runs/test_run_catalog_models.py` passed: 9 passed in 0.14s.

Final PR validation:

- `make validate-pr` passed:
  - Ruff: passed.
  - Pyright with config extra: passed with 0 errors, 0 warnings, 0 informations.
  - Default harness: 957 passed, 17 skipped, 14 deselected in 67.45s.
  - Config-extra harness: 413 passed, 985 deselected in 23.72s.
  - Build: source distribution and wheel built successfully.
- `make test-summary` passed and wrote `build/test-summary.md`.

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 55 | 0 | 0 | 1 | 0 | 7.41s |
| unit | passed | 755 | 0 | 0 | 1 | 0 | 16.58s |
| contract | passed | 75 | 0 | 0 | 2 | 0 | 3.25s |
| integration | passed | 61 | 0 | 0 | 7 | 10 | 53.17s |
| e2e | passed | 36 | 0 | 0 | 0 | 1 | 15.63s |
| config-extra | passed | 413 | 0 | 0 | 0 | 985 | 32.36s |
| Overall | passed | 1395 | 0 | 0 | 11 | 996 | 128.39s |

## Suite Obligations

- Package: update import/API tests to confirm comparison models remain exported from `loom.runs`, `RunCatalog.compare` is available, and `import loom.runs` stays cheap without eager SQLite or local-store imports.
- Unit: cover status computation, scalar comparison, section ordering, entry key formation, missing optional metadata, keyed left-only/right-only stages and artifacts, duplicate artifact identity handling, provenance selection, warning aggregation, and serialization helpers.
- Contract: cover `RunComparison.to_dict()` JSON shape, stable status values, canonical `left_run_uri`/`right_run_uri`, warnings, `checked_at`, deterministic section/entry order, and no raw internal document dumps.
- Integration: use local temporary run collections to compare identical runs, changed config/pipeline fingerprints, differing status/timestamps, left-only/right-only stages, left-only/right-only artifacts/checksums, executor/backend/submitted-operation differences, unsupported or partial runs, unreadable/disappearing inputs where deterministic, and stale sidecar recovery through current resolution.
- E2E: intentionally deferred to Phase 6 CLI integration; no CLI command exists in Phase 5.
- Opt-in suites: none required; no network service, real scheduler, hosted tracker, or large external fixture is needed.
- Final validation expected before PR preparation: `make validate-pr` and `make test-summary`, with any unavailable suite recorded in the PR body and phase notes.

## Stop Conditions

- Stop and mark blocked if the existing public comparison models cannot represent required semantics without a breaking public shape change.
- Stop before implementation if `develop` no longer contains merged Phase 4 current-list behavior.
- Stop if comparison requires artifact payload loading, project-code imports, or scheduler/domain-specific interpretation to satisfy acceptance criteria.
- Stop if run identity cannot be resolved canonically to `run_uri` without inventing a broad selector contract.
- Stop if targeted validation shows stale sidecar rows can be compared as current and the remedy requires changing Phase 4 read semantics beyond this phase.
- Stop if ordinary warning conditions would require a new public warning taxonomy not covered by existing `CatalogWarningCode` values.

## Completion Handoff Expectations

- The implementation PR must include only Phase 5 comparison API behavior and phase-scoped tests.
- The PR body should summarize comparison semantics, section/status choices, warning behavior, suite evidence, assumptions, accepted debt, and remaining CLI deferral.
- The implementation plan should remain `pending` until the PR is opened or prepared by the managing agent, then move to `pr_open` in the control checkout.
- Phase 6 may consume this API for CLI output but must not need to reinterpret comparison semantics.
