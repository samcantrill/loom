# Phase 1 Execution Plan: Boundary And Artifact Contracts

## Metadata

- Status: refined phase execution plan
- Feature focus: Configuration
- PR title: `Configuration - Phase 1: Boundary and Artifact Contracts`
- Branch: `codex/config-boundary-artifact-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-boundary-artifact-contracts`
- Phase execution plan path: `docs/phases/config-boundary-artifact-contracts.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Source phase: Phase 1 - Boundary And Artifact Contracts
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: merge-eligible after PR review approval because this is the root phase targeting `develop`
- Workflow path: expanded path
- Successor dependency notes: Phase 2 and later configuration phases may build on the artifact model skeletons and import-boundary tests once this phase PR is open or prepared; no stacked predecessor is required for this root phase.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used; initial review used, automated plan refinement used, confirmation review used. Do not reopen.
- Draft pass: completed by `loom_phase_planner`
- Refine pass: completed by `loom_phase_planner`; expanded-path refinement sharpened module placement, export boundaries, artifact skeleton names, suite obligations, and executor stop conditions.
- Setup limitations: `gh auth status` required approved network access because sandboxed status reported the token as invalid; `gh auth setup-git`, `git fetch origin`, and `git worktree add` required escalated filesystem access for Git metadata. `origin/develop` and local `develop` both resolve to `6f2956d7d9360a8ac3190ac7359372d32af8ff78`.
- Blockers: none recorded.

## Objective

Establish configuration/pipeline import boundaries and plain, persistence-free configuration artifact contract skeletons before later phases add composition behavior.

## Full-Plan Context

This is the first v1 configuration phase. It creates the contract surface that later loading, include, resolver, provenance, source-record, manifest, and fingerprint phases can populate without each phase inventing incompatible shapes. It must keep `loom.pipeline` independent from `loom.config` and treat manifests as artifact contracts for future run-store, resume, CLI, and inspection work, not as pipeline construction APIs.

Future behavior remains out of scope: strict loading in Phase 2, overrides and merge primitives in Phase 3, include resolution and recursive composition in Phases 5-7, public compose orchestration and inspection APIs in Phase 12, populated provenance/manifest/source/redaction records in Phase 13, and artifact-safe fingerprint comparison in Phase 14.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: the plan-quality gate commit is already on `develop`, and all earlier prerequisite work is merged.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after this phase PR is merged and no successor branches depend on `codex/config-boundary-artifact-contracts`.

## Source Phase Summary

- Goal: establish config/pipeline boundaries and plain artifact contract skeletons.
- Required scope: add config/pipeline import-boundary tests; define persistence-free config artifact return contracts; add versioned manifest, source artifact, provenance, and fingerprint model skeletons as plain serializable data; document no v1 CLI and no pipeline dependence on manifests.
- Required checkpoints: artifact models are minimal and versioned; import-boundary tests prove `loom.pipeline` remains independent from `loom.config`; package exports remain explicit and cheap to import.
- Acceptance criteria: `loom.pipeline` remains importable and constructible without `loom.config`; minimal artifact records serialize as plain data with schema/version fields; manifest records are documented as artifact contracts, not pipeline APIs.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/api.py`, `src/loom/config/provenance.py`, `src/loom/config/recipes/manifest.py`, `src/loom/artifacts.py`, `src/loom/records/base.py`, `src/loom/records/manifest.py`, `src/loom/provenance/models.py`, `src/loom/fingerprints.py`, and `src/loom/serialization/plain.py`.
- Intended module placement: add new v1 config artifact skeletons in `src/loom/config/artifacts.py`; keep existing `ConfigProvenance`, `ConfigSource`, and `ParsedOverride` ownership in `src/loom/config/provenance.py`; do not create a second provenance module.
- Existing tests or harness behavior: import-boundary tests live in `tests/package/test_import_boundaries.py`; package config API tests live in `tests/package/test_config_api.py`; root public exports are guarded by `tests/package/test_public_api.py`; pipeline-facing package API tests live in `tests/package/test_pipeline_api.py` and adjacent pipeline package tests; unit config tests live under `tests/unit/loom/config/`; contract tests live under `tests/contracts/`.
- Import-boundary or dependency constraints: cheap imports must not pull `yaml`, `omegaconf`, or `pydantic` into `loom`, `loom.pipeline`, artifact contract modules, or plain serialization. Prefer leaf-module exports with `__all__`; avoid root-level public exports unless the plan explicitly requires them.

## In-Scope Work

- Add or strengthen package/import tests proving `loom.pipeline` can be imported and directly constructed without importing `loom.config` or optional config dependencies.
- Define minimal plain-data config artifact skeletons in `src/loom/config/artifacts.py` for the stable Phase 1 names `CompositionManifest`, `SourceArtifactRecord`, and `ConfigFingerprintRecord`.
- Preserve `ConfigProvenance` as the provenance contract name in `src/loom/config/provenance.py`; only extend it additively if the artifact skeleton tests require a v1-compatible placeholder, and do not break existing v0 `to_dict()`/`from_dict()` round trips.
- Keep artifact records frozen, serializable data with explicit `schema_version` or equivalent version fields and `to_dict()`/`from_dict()` round trips.
- Reuse existing plain-data normalization and validation helpers from `loom.serialization` where practical.
- Add contract tests for empty or minimal artifact records and their serialized shapes.
- Document in module docstrings or focused docs/tests that manifest records are artifact contracts for future persistence/inspection and are not pipeline APIs.

## Out-of-Scope Work

- Behavior-changing composition.
- `_include_`, `_replace_`, `_copy_`, or include resolution behavior.
- Resolver scanning or resolver execution.
- Override parsing, merge semantics, overlays, or recipe ordering changes.
- Run-store writes, source snapshot persistence, or CLI commands.
- Phase 12 compose orchestration or inspection API implementation.
- Phase 13+ manifest, source, provenance, redaction, or fingerprint population behavior.
- Pipeline changes that make pipeline construction depend on manifests or `ComposedConfig`.

## Assumptions

- Existing frozen dataclass record style is the preferred local pattern for these skeletons.
- The first implementation should expose artifact skeletons from explicit leaf modules under `loom.config` rather than from `loom` root or package-level `loom.config` lazy symbols.
- Minimal records may start empty or metadata-only where later phases need behavior-specific population.
- `ConfigProvenance` may be extended additively or accompanied by v1-specific artifact records, but existing v0 callers must not lose current fields.

## Scope Contract

The executor must preserve this public contract boundary:

- `loom.pipeline` must not import `loom.config`, `ComposedConfig`, composition manifests, or optional config dependencies.
- Pipeline construction must continue to work from Python objects or plain data; manifests are not construction inputs for `PipelineSpec`, `StageSpec`, runners, stores, or graph helpers.
- Artifact skeletons are plain serializable contracts only. They may validate shape and schema version, but they must not read files, execute resolvers, inspect runtime state, write run directories, or depend on pipeline modules.
- Minimal serialized forms must include stable version fields so later phases can add fields additively. Use `schema_version` for record schema and avoid a separate version field name unless an existing local helper requires it.
- Phase 1 artifact names are bounded to `CompositionManifest`, `SourceArtifactRecord`, and `ConfigFingerprintRecord` in `loom.config.artifacts`, plus the existing `ConfigProvenance` name in `loom.config.provenance`. Do not introduce public alternate names such as `PipelineManifest`, `RunManifest`, `ConfigArtifactProvenance`, or root-level aliases.
- `CompositionManifest` is the top-level manifest contract only. It may contain empty/default record collections and metadata, but it must not encode execution, run-store, CLI, or pipeline graph behavior.
- `SourceArtifactRecord` is a metadata/hash source record skeleton only. It must not store raw source bytes, resolved resolver values, or rebuild policy decisions.
- `ConfigFingerprintRecord` is a fingerprint detail skeleton only. It must not compute final artifact-safe fingerprints or resume comparisons in this phase.
- `ComposedConfig` additive v1 fields (`unresolved`, `manifest`, `source_artifacts`, `fingerprint_records`) are out of scope until Phase 12 public compose orchestration unless a zero-behavior type-only change is strictly required; if required, stop for the manager before changing that public return object.
- Unknown-field and missing-field behavior should follow existing local record conventions closely enough that contract tests can lock it without inventing a new serialization framework.
- Leaf-module import contract: `import loom.config.artifacts` must not import `yaml`, `omegaconf`, `pydantic`, `loom.pipeline`, `loom.cli`, run stores, or execution modules.

## Design Impact

- Maintainability: establishes shared artifact shapes early so later phases populate stable records instead of creating phase-local payloads.
- Extensibility: versioned skeletons leave room for future run-store, resume, CLI, remote-source, and plugin records through additive fields.
- Domain neutrality: records describe configuration composition artifacts only and must not encode project-specific model, dataset, experiment, or stage semantics.
- Source-tree boundaries: config artifact modules may use serialization, fingerprints, errors, and config provenance helpers; they must not import pipeline execution, stores, CLI, plugin discovery, or project code.

## Future Compatibility

- Phase 12 can add public composition inspection APIs and `ComposedConfig` fields around these records without making them pipeline requirements.
- Phase 13 can populate manifest, provenance, source, and redaction records without changing the skeleton contract.
- Phase 14 can compute artifact-safe fingerprints from these records before resolver execution.
- Future CLI and run-store work can persist these contracts, but this phase must leave persistence ownership outside `loom.config`.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Treat composition manifests as pipeline construction APIs | Violates the v1 boundary that config composition is optional and `loom.pipeline` remains usable from Python objects or plain data. |
| Delay artifact skeleton design until public compose orchestration | Increases drift risk across provenance, manifest, source, and fingerprint phases. |
| Export new records from `loom` root immediately | Expands root public API before later phases prove which names need root-level convenience. |
| Add `loom.config` package-level lazy exports immediately | Risks optional-dependency behavior and package API churn before Phase 12 finalizes the public compose surface. |
| Implement artifact population while defining skeletons | Blurs Phase 1 with Phase 13+ behavior and makes review less focused. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Artifact skeletons may contain fields that remain unpopulated until later phases | Phase 1 intentionally defines contracts before behavior to control drift. | Revisit during Phase 13 if a field cannot be populated without changing the contract. |
| Leaf-module exports may be less convenient than root exports | Keeps the first contract PR small and avoids premature public API expansion. | Revisit in Phase 12 when public compose and inspection API exports are finalized. |

## Reviewability

- Expected PR size and shape: small model/import/test diff with no composition behavior changes.
- Files and areas to inspect: new `src/loom/config/artifacts.py`, any additive `src/loom/config/provenance.py` changes, leaf-module `__all__` definitions, `tests/package/test_import_boundaries.py`, `tests/unit/loom/config/`, and `tests/contracts/`.
- Scope-control checks: no run-store writes; no CLI additions; no include, resolver, override, recipe-order, or compose-order behavior; no pipeline imports from config; no root-level exports; no `ComposedConfig` return-shape change without a manager stop.

## Implementation Steps

1. Add `src/loom/config/artifacts.py` with frozen dataclass skeletons for `CompositionManifest`, `SourceArtifactRecord`, and `ConfigFingerprintRecord`, plus explicit leaf-module `__all__`.
2. Reuse `src/loom/config/provenance.py` for the existing `ConfigProvenance` contract; make only additive compatibility changes there if contract tests expose a necessary Phase 1 gap.
3. Extend or add package/import tests proving `loom.pipeline` import and direct pipeline spec construction remain independent of `loom.config`, config artifacts, and optional config dependencies.
4. Add unit and contract serialization tests for empty or minimal composition manifest, source artifact, `ConfigProvenance`, and config fingerprint record shapes.
5. Add focused documentation in module docstrings or tests that manifests are config artifact contracts, not pipeline APIs, and keep any export adjustments to leaf-module exports.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`; update `tests/package/test_config_api.py` only if the implementation intentionally changes config package exports, which is not the preferred path; `tests/package/test_public_api.py` should change only if a root export is explicitly justified, which this plan does not expect.
- Required assertions or deferral reason: importing `loom.pipeline` in a fresh interpreter does not load `loom.config`, `loom.config.artifacts`, `yaml`, `omegaconf`, or `pydantic`; directly constructing or parsing a minimal pipeline spec from plain data does not require config artifacts; importing `loom.config.artifacts` does not load pipeline, CLI, execution, store, or optional config dependency modules.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/config/test_config_artifacts.py` for new artifact skeletons, plus `tests/unit/loom/config/test_config_provenance.py` only for additive provenance compatibility changes.
- Required assertions or deferral reason: minimal model construction validates positive integer `schema_version`, normalizes nested plain data, preserves immutable tuple-style collections where local patterns use tuples, rejects invalid non-plain data, and leaves raw source bytes/resolved runtime values out of default source/fingerprint records.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_config_artifact_contract.py` or a similarly named focused contract test module under `tests/contracts/`.
- Required assertions or deferral reason: empty/minimal `CompositionManifest`, `SourceArtifactRecord`, existing `ConfigProvenance`, and `ConfigFingerprintRecord` values serialize to plain dictionaries with stable `schema_version` fields and round-trip through `from_dict()`; unknown or malformed fields fail with the local config/schema validation error type rather than string parsing by callers; manifest serialization is documented/asserted as a config artifact contract, not a pipeline API.

### Integration Suite

- Status: deferred
- Expected paths: none for this phase.
- Required assertions or deferral reason: no composition stages interact yet. Integration coverage starts when later phases wire loading, includes, recipes, resolver handling, or public `compose_config` orchestration.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase.
- Required assertions or deferral reason: no user-visible composition behavior is available through public `compose_config` beyond existing v0 behavior, and no CLI exists in v1.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected.
- Required assertions or deferral reason: raw source snapshots and opt-in runtime-value artifact policies are out of scope until later phases.

## Risks

- Artifact names or fields can become too broad before later phases prove population needs; keep skeletons minimal and additive.
- Adding exports through `loom.config` can accidentally trigger optional dependencies; preserve the existing lazy import pattern.
- Contract tests can over-specify fields that later phases need to evolve; lock schema/version and minimal required fields while leaving documented additive room.
- Pipeline-boundary tests can miss construction paths; include at least one direct construction/import check near existing pipeline package tests.
- `ConfigProvenance` already exists and is used by v0 `ComposedConfig`; treat changes there as compatibility-sensitive and prefer adding new skeletons beside it over reshaping its existing payload.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import_boundaries.py
uv run pytest tests/package/test_config_api.py
uv run pytest tests/package/test_pipeline_api.py
uv run pytest tests/unit/loom/config/test_config_artifacts.py tests/unit/loom/config/test_config_provenance.py
uv run pytest tests/contracts/test_config_artifact_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: `src/loom/config/artifacts.py` skeletons first, provenance compatibility only if necessary second, unit/contract tests third, package/import-boundary tests fourth, docstring and `__all__` cleanup last.
- Tests to run with each slice: run `uv run pytest tests/unit/loom/config/test_config_artifacts.py` after artifact skeletons; add `tests/unit/loom/config/test_config_provenance.py` only if `ConfigProvenance` changes; run `uv run pytest tests/contracts/test_config_artifact_contract.py` after serialization contracts; run package import-boundary tests after any export/import changes.
- Decisions the executor must not revisit: manifests are artifact contracts rather than pipeline APIs; no v1 CLI; no run-store writes; no behavior-changing composition; new skeletons live in `loom.config.artifacts`; `ConfigProvenance` stays in `loom.config.provenance`; no root exports; no package-level `loom.config` lazy exports unless the manager approves a public API reason.
- Conditions that require stopping for the manager: implementation needs to change `ComposedConfig` fields before Phase 12; artifact skeleton names need to differ from `CompositionManifest`, `SourceArtifactRecord`, or `ConfigFingerprintRecord`; `loom.pipeline` cannot stay independent from `loom.config`; optional config dependencies become necessary for artifact skeleton imports; or a necessary test/decision requires reopening the fully used plan quality gate.
- Expanded-path refinement notes: completed; exact module placement, exported names, suite obligations, and stop conditions are now recorded for implementation.

## Refinement And Review Budget Status

- Phase implementation refinement: used
- PR review: unused

## Completion Notes

- Draft plan: completed in this artifact by `loom_phase_planner`; committed with `plan: add phase execution plan`.
- Final phase execution plan: refined by `loom_phase_planner`; committed with `plan: refine phase execution plan`.
- Implementation summary:
  - Added `src/loom/config/artifacts.py` with `CompositionManifest`, `SourceArtifactRecord`, and `ConfigFingerprintRecord` contracts, each with strict `schema_version` validation, plain-data normalization, and round-trip serialization.
  - Added `tests/unit/loom/config/test_config_artifacts.py` for round-trip and malformed-data coverage of source/fingerprint/manifests and tuple-shaped collection preservation.
  - Added `tests/contracts/test_config_artifact_contract.py` to lock stable manifest/fingerprint/source/provenance contract expectations at Phase 1.
  - Extended `tests/package/test_import_boundaries.py` with checks that `loom.config.artifacts` imports without pulling pipeline/CLI/config-only modules and that pipeline parsing can be built from plain data without importing `loom.config`.
- Implementation validation:
  - `uv run pytest tests/unit/loom/config/test_config_artifacts.py tests/unit/loom/config/test_config_provenance.py` ✅ 11 passed
  - `uv run pytest tests/contracts/test_config_artifact_contract.py` ✅ 5 passed
  - `uv run pytest tests/package/test_import_boundaries.py` ✅ 14 passed
  - `uv run pytest tests/package/test_config_api.py` ✅ skipped (optional dependency profile)
  - `uv run pytest tests/package/test_pipeline_api.py` ✅ 2 passed
  - `make validate-pr` ✅ passed (ruff, pyright, targeted harness targets, build)
  - `make test-summary` ✅ `build/test-summary.md` written with all suite tiers passing
- Refinement summary: expanded-path refinement completed; sharpened module placement, export boundaries, artifact skeleton naming, package/unit/contract suite obligations, and implementation stop conditions.
- Implementation refinement validation review:
  - Scope review: confirmed new artifact skeletons stay in `src/loom/config/artifacts.py`; no root exports, package-level `loom.config` exports, `ComposedConfig` changes, or compose/include/override/resolver/recipe/run-store/CLI behavior changes were introduced.
  - Contract risk reviewed: `SourceArtifactRecord.kind` limited to only `base` and `overlay` was too narrow for the Phase 13 requirement to populate source metadata/hash records for includes and recipe source references. The refinement widened the accepted source roles to `base`, `overlay`, `include`, and `recipe`, while preserving rejection of unknown roles.
  - Import-boundary review: local import probe confirmed `import loom.config.artifacts` does not load `yaml`, `omegaconf`, `pydantic`, `loom.pipeline`, `loom.cli`, execution, or store modules.
  - Suite coverage review: package, unit, and contract obligations from the finalized phase plan remain satisfied; integration, e2e, and opt-in suites remain deferred for this phase because no composed behavior is wired yet.
- Implementation refinement fixes:
  - Widened `SourceArtifactRecord.kind` to include future Phase 13 source roles for include files and recipe source references.
  - Added unit and contract round-trip coverage for `include` and `recipe` source artifact records, plus an unknown-kind rejection test.
- Implementation refinement validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/config/test_config_artifacts.py tests/unit/loom/config/test_config_provenance.py` ✅ 13 passed
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_config_artifact_contract.py` ✅ 6 passed
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py` ✅ 14 passed
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python - <<'PY' ...` import probe ✅ forbidden modules absent after `import loom.config.artifacts`
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` ✅ passed (Ruff, Pyright 0 errors, default harness 419 passed / 9 skipped, config-extra 116 passed / 424 deselected, build)
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` ✅ wrote `build/test-summary.md` with package 36 passed / 1 skipped, unit 354 passed / 1 skipped, contract 20 passed / 1 skipped, integration 9 passed / 5 skipped, e2e 5 passed, config-extra 116 passed / 424 deselected
- PR preparation:
  - PR body draft pass: completed by `loom_pr_preparer` using
    `.codex/prompts/pr-body-draft.md`; artifact written to
    `docs/phases/config-boundary-artifact-contracts-pr-body.md`.
  - PR body refine pass: pending because this phase is on the expanded path.
  - PR open status: not opened in this draft pass by instruction; expected
    refine/open pass should use title
    `Configuration - Phase 1: Boundary and Artifact Contracts`, target
    `develop`, and head `codex/config-boundary-artifact-contracts`.
  - PR facts confirmed: root phase, stack predecessor none, base branch
    `develop`, target branch `develop`, merge eligibility after PR review
    approval because the PR targets `develop`.
  - PR preparation validation evidence: used recorded final validation from the
    executor/refiner (`UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed and
    `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with
    `build/test-summary.md` generated); no implementation refinements or new
    tests were created during PR preparation.
- Stack maintenance: none yet.
- Remaining blockers: none recorded.
