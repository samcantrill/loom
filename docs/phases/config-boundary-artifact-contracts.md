# Phase 1 Execution Plan: Boundary And Artifact Contracts

## Metadata

- Status: draft phase execution plan
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
- Refine pass: pending because this phase establishes public-ish artifact contracts and import boundaries.
- Setup limitations: `gh auth status` required approved network access because sandboxed status reported the token as invalid; `gh auth setup-git`, `git fetch origin`, and `git worktree add` required escalated filesystem access for Git metadata. `origin/develop` and local `develop` both resolve to `6f2956d7d9360a8ac3190ac7359372d32af8ff78`.
- Blockers: none recorded for the draft plan.

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
- Existing tests or harness behavior: import-boundary tests live in `tests/package/test_import_boundaries.py`; package config API tests live in `tests/package/test_config_api.py`; root public exports are guarded by `tests/package/test_public_api.py`; pipeline-facing package API tests live in `tests/package/test_pipeline_api.py` and adjacent pipeline package tests.
- Import-boundary or dependency constraints: cheap imports must not pull `yaml`, `omegaconf`, or `pydantic` into `loom`, `loom.pipeline`, artifact contract modules, or plain serialization. Prefer leaf-module exports with `__all__`; avoid root-level public exports unless the plan explicitly requires them.

## In-Scope Work

- Add or strengthen package/import tests proving `loom.pipeline` can be imported and directly constructed without importing `loom.config` or optional config dependencies.
- Define minimal plain-data config artifact skeletons for the v1 composition manifest, source artifact records, provenance-compatible config artifact records, and config fingerprint records.
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
- The first implementation should expose artifact skeletons from explicit leaf modules under `loom.config` rather than from `loom` root.
- Minimal records may start empty or metadata-only where later phases need behavior-specific population.
- `ConfigProvenance` may be extended additively or accompanied by v1-specific artifact records, but existing v0 callers must not lose current fields.

## Scope Contract

The executor must preserve this public contract boundary:

- `loom.pipeline` must not import `loom.config`, `ComposedConfig`, composition manifests, or optional config dependencies.
- Pipeline construction must continue to work from Python objects or plain data; manifests are not construction inputs for `PipelineSpec`, `StageSpec`, runners, stores, or graph helpers.
- Artifact skeletons are plain serializable contracts only. They may validate shape and schema version, but they must not read files, execute resolvers, inspect runtime state, write run directories, or depend on pipeline modules.
- Minimal serialized forms must include stable version fields so later phases can add fields additively.
- Unknown-field and missing-field behavior should follow existing local record conventions closely enough that contract tests can lock it without inventing a new serialization framework.

## Design Impact

- Maintainability: establishes shared artifact shapes early so later phases populate stable records instead of creating phase-local payloads.
- Extensibility: versioned skeletons leave room for future run-store, resume, CLI, remote-source, and plugin records through additive fields.
- Domain neutrality: records describe configuration composition artifacts only and must not encode project-specific model, dataset, experiment, or stage semantics.
- Source-tree boundaries: config artifact modules may use serialization, fingerprints, errors, and config provenance helpers; they must not import pipeline execution, stores, CLI, plugin discovery, or project code.

## Future Compatibility

- Phase 12 can add public composition inspection APIs around these records without making them pipeline requirements.
- Phase 13 can populate manifest, provenance, source, and redaction records without changing the skeleton contract.
- Phase 14 can compute artifact-safe fingerprints from these records before resolver execution.
- Future CLI and run-store work can persist these contracts, but this phase must leave persistence ownership outside `loom.config`.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Treat composition manifests as pipeline construction APIs | Violates the v1 boundary that config composition is optional and `loom.pipeline` remains usable from Python objects or plain data. |
| Delay artifact skeleton design until public compose orchestration | Increases drift risk across provenance, manifest, source, and fingerprint phases. |
| Export new records from `loom` root immediately | Expands root public API before later phases prove which names need root-level convenience. |
| Implement artifact population while defining skeletons | Blurs Phase 1 with Phase 13+ behavior and makes review less focused. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Artifact skeletons may contain fields that remain unpopulated until later phases | Phase 1 intentionally defines contracts before behavior to control drift. | Revisit during Phase 13 if a field cannot be populated without changing the contract. |
| Leaf-module exports may be less convenient than root exports | Keeps the first contract PR small and avoids premature public API expansion. | Revisit in Phase 12 when public compose and inspection API exports are finalized. |

## Reviewability

- Expected PR size and shape: small model/import/test diff with no composition behavior changes.
- Files and areas to inspect: config artifact/provenance/fingerprint/source model modules, `src/loom/config/__init__.py` or leaf `__all__` updates, `tests/package/test_import_boundaries.py`, package API tests, and contract serialization tests.
- Scope-control checks: no run-store writes; no CLI additions; no include, resolver, override, or compose-order behavior; no pipeline imports from config; no root-level exports unless explicitly justified in the diff.

## Implementation Steps

1. Add the minimal artifact model module or modules using frozen dataclasses, schema/version fields, plain-data normalization, and explicit leaf-module `__all__`.
2. Extend or add package/import tests proving `loom.pipeline` import and direct construction remain independent of `loom.config`, manifests, and optional config dependencies.
3. Add contract serialization tests for empty or minimal composition manifest, source artifact, config provenance/artifact, and config fingerprint record shapes.
4. Adjust config package exports only where needed for explicit leaf-module access, preserving optional dependency laziness.
5. Add focused documentation in module docstrings or tests that manifests are config artifact contracts, not pipeline APIs.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_config_api.py`, and possibly `tests/package/test_public_api.py`.
- Required assertions or deferral reason: importing `loom.pipeline` in a fresh interpreter does not load `loom.config`, `yaml`, `omegaconf`, or `pydantic`; pipeline-facing constructors remain available from pipeline modules without config artifacts; any new config artifact exports are explicit and lazy enough to preserve existing optional dependency behavior.

### Unit Suite

- Status: required
- Expected paths: focused tests under the existing config test area, or a new narrow unit test module for config artifact models if that is the local pattern.
- Required assertions or deferral reason: minimal model construction validates schema/version fields, normalizes nested plain data, freezes or preserves immutable tuple fields where appropriate, and rejects invalid non-plain data.

### Contract Suite

- Status: required
- Expected paths: contract-style tests for config artifact model serialization, likely alongside existing config tests if no dedicated `tests/contract/` directory exists.
- Required assertions or deferral reason: empty/minimal `CompositionManifest`, `SourceArtifactRecord`, config provenance/artifact record, and `ConfigFingerprintRecord` values serialize to plain dictionaries with stable schema/version fields and round-trip through `from_dict()`.

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

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import_boundaries.py
uv run pytest tests/package/test_config_api.py
uv run pytest tests/package/test_pipeline_api.py
uv run pytest <new-or-updated-config-artifact-contract-tests>
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: artifact skeletons first, package/import tests second, serialization contract tests third, export/docstring cleanup last.
- Tests to run with each slice: run targeted contract tests after model changes, then import-boundary/package tests after export changes.
- Decisions the executor must not revisit: manifests are artifact contracts rather than pipeline APIs; no v1 CLI; no run-store writes; no behavior-changing composition in this phase; no root exports unless directly required by existing package patterns.
- Conditions that require stopping for the manager: artifact skeletons require a public API decision beyond leaf-module exports, `loom.pipeline` cannot stay independent from `loom.config`, or a necessary test requires reopening the fully used plan quality gate.
- Expanded-path refinement notes: the refine pass should confirm exact module placement and exported names are sufficient for later phases while preserving lazy optional dependency behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed in this artifact by `loom_phase_planner`; committed with `plan: add phase execution plan`.
- Final phase execution plan: pending expanded-path refine pass.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- PR preparation: pending.
- Stack maintenance: none yet.
- Remaining blockers: none recorded.
