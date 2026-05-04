# Phase 1 Execution Plan: Core Contracts, Schemas, And Packaging

## Metadata

- Status: refined phase execution plan, ready for implementation handoff
- Branch: `codex/v0-post-core-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-core-contracts`
- Phase execution plan path: `docs/phases/v0-post-core-contracts.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Source phase: `Phase 1 - Core Contracts, Schemas, And Packaging`
- Stack predecessor: none
- Base branch: `develop` at `d40b532a741bd80383da5ea83020aa77aec57315`
- Target branch: `develop`
- Merge eligibility: human-owned serial merge gate. The PR targets `develop`, must request review from `samcantrill`, must mention `@samcantrill` in the PR body or an immediate PR comment, and is merge-eligible only after human approval and human merge into `develop`. Codex must not approve or merge.
- Successor dependency notes: no successor phase may start while this PR is only `pr_open` or `approved`; Phase 2 starts only after this phase is verified as merged into `develop`.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v0-post.md`; no blocking plan-review findings remain.
- Plan quality gate loop budget: initial plan review used, automated plan refinement pass used, confirmation review used. Do not consume another plan-quality review loop without explicit manager instruction.
- Draft pass: completed by `loom_phase_planner` in draft commit `f0a9fdf258645960b78128e14accb40c3a86dcde`.
- Refine pass: completed by `loom_phase_planner` in this pass.
- Setup limitations: none for local planning. The assigned branch/worktree already existed at the requested `develop` base commit; no remote synchronization was needed for this refinement.
- Blockers: none.

## Objective

Make the lowest-level post-v0 contracts safe before higher layers build on them. This phase makes frozen core refs, records, manifests, views, and pipeline specs recursively immutable at construction time while preserving ordinary mutable plain-data output from `to_dict()` and serialization helpers.

It also introduces strict shared persisted-document helpers for version envelopes, unknown-field rejection, migration dispatch, and compatibility tests, then moves config-only dependencies behind a `config` optional extra with reviewable no-extra and config-extra validation evidence.

## Full-Plan Context

This is the first phase in the v0-post hardening sequence. It must land before store/context capabilities, stage factory and fingerprint policy, runtime/event/lock foundations, planner decomposition, explicit recipe catalog work, runner lifecycle decomposition, and final hardening docs.

The phase fixes findings 5, 6, and 10 from the source plan: shallow immutability, persisted schema boilerplate, and hard config dependencies. It must not implement store/context capability rewrites, `ArtifactAddress`, run-scoped artifact-store changes, lock/event/runtime foundations, stage factory blocks, semantic fingerprint changes, planner decomposition or explanations, recipe catalog policy, runner lifecycle decomposition, run catalogs, bundles, sweeps, non-local executors, retry, timeout, cleanup, or plugin behavior.

## Stack Context

- Root or stacked phase: root serial phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: serial human-merge-gate mode starts each phase from updated `develop`; there are no earlier phases in this plan.
- Retarget/rebase plan after predecessor merge: not applicable because there is no predecessor.
- Branch cleanup constraints: keep the phase branch until the human-owned PR has merged into `develop` and no successor branch depends on it.

## Source Phase Summary

- Goal: fix foundational immutability, schema, and packaging contracts before higher layers depend on mutable values, one-off persisted readers, or hard config imports.
- Required scope:
  - Make frozen core refs, records, manifests/views, and specs recursively immutable.
  - Preserve mutable `to_dict()` and serialization output.
  - Add shared persisted-document helpers for envelopes, strict fields, supported versions, migration dispatch, and compatibility tests.
  - Keep migrations owned by each document family rather than a global migration registry.
  - Move OmegaConf, Pydantic, and PyYAML behind a `config` optional extra.
  - Add no-extra and config-extra validation evidence through packaging, Makefile, test harness, markers, and `make test-summary`.
  - Update `docs/structure.md` and affected serialization/config docs.
- Required checkpoints:
  - Recursive immutable construction is introduced before applying it across core objects.
  - Existing round trips continue returning plain `dict` and `list` values.
  - Schema helpers replace duplicated persisted-document boilerplate where reviewable in this phase.
  - Default validation proves no-extra import boundaries; config-extra validation proves config behavior with optional dependencies installed.
- Acceptance criteria:
  - Nested metadata/config mappings on frozen core objects cannot be mutated after construction.
  - Serialization round trips return ordinary mutable plain-data structures.
  - Persisted readers reject unsupported schema versions and unknown fields by default, while explicit older versions can route through document-owned migrations.
  - `import loom` and core primitive, store, serialization, and inspection imports work without config extras.
  - Phase 1 evidence includes default no-extra validation, config-extra validation, and `make test-summary` visibility for skipped versus executed optional suites.

## Current Source And Harness Findings

- `src/loom/refs.py`, `src/loom/artifacts.py`, `src/loom/records/base.py`, `src/loom/records/manifest.py`, `src/loom/records/views.py`, and `src/loom/pipeline/specs.py` use frozen dataclasses but normalize nested plain data to mutable `dict` and `list` values.
- Current `to_dict()` implementations often make only shallow `dict(...)` copies. They must be changed to thaw recursively so internal immutable mappings or sequences never leak while returned plain data remains mutable.
- `src/loom/serialization/plain.py` owns `PlainData`, `ensure_plain_data()`, and `to_plain_data()`. It already imports `MappingProxyType` only to reject it as plain data; this phase should add explicit freeze/thaw helpers without weakening plain-data validation.
- `src/loom/serialization/schema.py` currently exposes only `get_schema_version()`, `require_schema_version()`, and `check_supported_schema()`.
- Persisted models in provenance, status, planning, manifests, local stores, and execution currently duplicate required-field, unknown-field, schema-version, and plain-mapping validation. The first implementation pass should target a small reviewable shared helper API and migrate representative persisted readers in scope rather than rewriting every persisted model blindly.
- `pyproject.toml` currently lists `omegaconf>=2.3`, `pydantic>=2`, and `pyyaml>=6` as hard project dependencies.
- Config-only imports are direct in `src/loom/config/load.py` (`yaml`), `src/loom/config/interpolation.py` (`omegaconf`), and `src/loom/config/recipes/base.py` (`pydantic`).
- `src/loom/config/__init__.py` eagerly exports recipe/config APIs. The no-extra install path should still fail clearly for config-only behavior rather than accidentally importing optional dependency modules through root or package imports.
- `tests/package/test_import_boundaries.py` already protects cheap root, serialization, I/O, pipeline, store, execution, executor, and CLI imports, but it runs in an environment where config dependencies are currently hard-installed.
- `tests/package/test_config_api.py`, `tests/unit/loom/config/`, `tests/integration/config/`, and `tests/integration/docs/test_v0_python_examples.py` exercise config behavior and should become config-extra evidence rather than default no-extra evidence.
- `tools/test_harness/cli.py` currently records package, unit, contract, integration, and e2e suites only. It excludes `optional_dependency` tests from default and all local runs, so Phase 1 must make optional dependency execution visible in summary evidence.
- `uv run --isolated` is available and must be used by the new no-extra and config-extra validation targets to avoid a shared `.venv` retaining optional dependencies between runs.
- Phase 1 migrates only `InMemoryManifest.from_dict()`, `RunStatusRecord.from_dict()`, `StageStatusRecord.from_dict()`, and `ExecutionFailure.from_dict()` to the new schema helpers. Planning models, provenance models, artifact indexes, local-store wrapper documents, and primitive `ResourceRef`/`ArtifactRef` schema-like fields are intentionally deferred unless the executor finds a direct Phase 1 bug in the selected subset.

## In-Scope Work

- Add recursive immutable plain-data helpers in the serialization layer, with an explicit thaw path for public plain-data output.
- Apply immutable normalization to:
  - `ResourceRef.metadata`
  - `ArtifactRef.metadata`
  - `Record.resources`, `Record.metadata`, `Record.annotations`, and `Record.provenance`
  - `InMemoryManifest.metadata`
  - `ManifestView.metadata`
  - `OutputSpec.metadata`
  - `StageSpec.outputs`, `StageSpec.stage_config`, `StageSpec.inputs`, and `StageSpec.resources`
  - `PipelineSpec.stages` and `PipelineSpec.metadata`
- Preserve stable public imports from `loom`, `loom.refs`, `loom.artifacts`, `loom.records`, `loom.serialization`, and `loom.pipeline`.
- Add shared schema helpers for persisted documents: mapping checks, required and optional fields, unknown-field rejection, supported-version checks, versioned document envelope handling, and document-owned migration dispatch.
- Migrate only the selected persisted readers to the shared schema helpers: `InMemoryManifest.from_dict()`, `RunStatusRecord.from_dict()`, `StageStatusRecord.from_dict()`, and `ExecutionFailure.from_dict()`. Leave provenance, planning, local-store wrapper, and artifact-index migrations explicit debt for later phases or future edits to those document families.
- Move config dependencies from hard project dependencies into a `config` optional extra and update lock/install metadata as needed.
- Add no-extra validation coverage for root/core imports, serialization, records, artifacts, refs, pipeline stores, and inspection-friendly modules.
- Add config-extra validation coverage for config composition, recipes, interpolation, YAML loading, config docs/examples that parse YAML, and any package API tests that require the optional dependencies.
- Update the Makefile and test harness so `make test-summary` records both default no-extra suite evidence and config-extra evidence rather than hiding optional dependency behavior behind skipped tests.
- Update `docs/structure.md`, `docs/features/serialization.md`, and `docs/features/config.md` to reflect recursive immutability, schema-layer ownership, and optional config dependencies.

## Out-of-Scope Work

- No store/context capability rewrite, run-scoped artifact-store contract change, `ArtifactAddress`, run-document/user-metadata API rename, or local path contract break. Phase 1 does not need `ArtifactAddress`; adding it would be future Phase 2 work.
- No stage factory block, no stage constructor kwargs, no semantic fingerprint policy change, and no target import policy redesign beyond what is strictly required to keep optional dependency imports from leaking.
- No runtime/resource/event/lock foundations, event JSONL, blocked descendant outcome persistence, or runner lifecycle decomposition.
- No planner policy extraction, `PlanExplanation`, or planning behavior change.
- No recipe catalog policy change beyond packaging optional dependencies correctly.
- No CLI feature expansion, run catalog, bundle, sweep, remote store, subprocess, SLURM, container, retry, timeout, cleanup, or plugin behavior.
- No broad persisted-model rewrite if a smaller migration proves the schema helper contract and leaves deferrals explicit for later phases.
- No product-code implementation in this planning pass.

## Assumptions

- The source plan's quality gate has passed and its loop budget is consumed, so Phase 1 can be planned but not reopened for plan-quality review unless explicitly directed.
- Recursive immutability should cover plain-data mappings and sequences deeply. Primitive scalar values stay as-is.
- Returned `to_dict()` values must be independent mutable `dict`/`list` trees. Mutating those returned trees must not mutate the original object.
- Immutable internals may use standard-library wrappers and tuples, but those implementation details must not appear in serialized public data.
- Config extras may be required to execute config behavior, but no-extra installs must still support cheap root/core imports and clear errors for config-only behavior.
- `import loom.config` should succeed without optional dependencies and should not import YAML, OmegaConf, Pydantic, pipeline execution, stores, or CLI modules. Accessing or invoking config-only exports without the extra may fail with a config-owned missing-extra error that tells users to install `loom[config]`; with the extra installed, existing config exports and signatures remain available.
- The implementation must add a new config-extra suite target rather than forcing config tests into the default no-extra suite.
- Updating `uv.lock` may require dependency resolution. If resolution is unavailable during implementation, the executor or PR preparer must record the exact limitation rather than hand-editing lock data.

## Decision-Complete Contract

The executor must not redesign these decisions:

- Frozen public value objects must be recursively immutable after construction.
- `src/loom/serialization/plain.py` must add `freeze_plain_data(value, *, path="$")` and `thaw_plain_data(value, *, path="$")`. `freeze_plain_data()` validates through the existing plain-data rules, recursively copies input, converts mappings to `MappingProxyType`, converts sequences to tuples, and preserves scalar primitives. `thaw_plain_data()` recursively returns independent mutable `dict` and `list` trees and accepts both frozen internals and ordinary plain data.
- `freeze_plain_data()` and `thaw_plain_data()` are exported from `loom.serialization` for internal package consumers and low-level serialization users. Any `FrozenPlainData` type alias can remain private to `plain.py`; public dataclass field annotations should not be churned solely to expose the internal storage shape.
- Object-valued maps that are not plain data, specifically `Record.resources` and `StageSpec.outputs`, must be normalized to immutable mappings with copied dictionaries and `MappingProxyType`. `PipelineSpec.stages` remains a tuple. Plain-data maps and sequences use `freeze_plain_data()`.
- `to_dict()`, `ManifestView.filter()`, `ManifestView.materialize()`, and related public serialization helpers must call `thaw_plain_data()` or equivalent recursive copies so callers receive ordinary mutable `dict`/`list` output that does not share mutable children with the object.
- Unknown fields in known `loom` persisted documents are rejected by default.
- Unsupported schema versions are rejected by default.
- `src/loom/serialization/schema.py` must keep `get_schema_version()`, `require_schema_version()`, and `check_supported_schema()`, then add a small public helper API with these names and behavior:
  - `require_mapping(data, *, path="$")` returns a string-key mapping or raises `SchemaVersionError`.
  - `validate_document_fields(data, *, required, optional=(), path="$")` rejects missing required fields and unknown fields.
  - `load_versioned_document(data, *, current_version, required, optional=(), migrations=None, field="schema_version", path="$")` validates the mapping, routes older versions through document-owned migrations keyed by source version, requires each migration to return a mapping with the next schema version, rejects unsupported or future versions, validates fields after migration, and returns a copied `dict[str, object]`.
- Known older document versions migrate through explicit document-owned migration tables passed to `load_versioned_document()`. There is no global process-wide migration registry.
- Schema helpers raise `SchemaVersionError`; selected persisted readers should catch it and re-raise their existing domain error type where that error type is already part of the reader contract.
- Config dependencies are optional under a `config` extra, not hard runtime dependencies.
- Default validation must prove no-extra behavior in an isolated environment, and config-extra validation must run config behavior with the optional dependencies installed in a separate isolated environment.
- `pyproject.toml` must move `omegaconf>=2.3`, `pydantic>=2`, and `pyyaml>=6` from `[project].dependencies` into `[project.optional-dependencies].config`. Do not add replacement heavyweight runtime dependencies.
- Makefile and harness changes must add `test-no-extra` and `test-config-extra` targets. `test-no-extra` runs the default suite through `uv run --isolated --locked --group dev`; `test-config-extra` runs config-marked tests through `uv run --isolated --locked --group dev --extra config`. `make test-summary` records package, unit, contract, integration, e2e, and config-extra rows.

## Design Impact

- Maintainability: central freeze/thaw and schema helpers reduce repeated defensive-copy and persisted-reader boilerplate. Migrating only focused call sites in Phase 1 keeps the PR reviewable.
- Extensibility: run bundles, catalogs, event records, and future cleanup policies can reuse shared version and migration mechanics rather than adding new one-off readers.
- Domain neutrality: the phase affects generic plain-data, reference, record, pipeline spec, schema, and packaging boundaries only. It does not introduce domain-specific metadata semantics.
- Source-tree boundaries: recursive plain-data helpers belong in `loom.serialization`; refs, records, artifacts, and specs retain ownership of their public fields; config dependencies remain under `loom.config` and optional dependency metadata.

## Future Compatibility

- Catalog and bundle work can rely on immutable refs/specs when computing fingerprints or comparing persisted data.
- Runtime events and blocked outcomes can use the shared persisted-document API when their versioned JSONL/document shapes are added later.
- Optional config dependencies keep primitive/store/serialization consumers lightweight and leave future plugin/CLI workflows room to choose explicit install shapes.
- The no-extra/config-extra harness split should remain visible in later PR evidence whenever packaging or import boundaries are touched.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep frozen dataclasses with mutable nested dictionaries | It contradicts the public immutability signal and allows validated or fingerprinted objects to change after construction. |
| Return immutable mappings from `to_dict()` | Persisted and user-inspection APIs are documented as ordinary plain data; callers should not receive `MappingProxyType` or tuple/list surprises. |
| Add a heavyweight schema framework | The plan explicitly keeps strict plain-data persisted schemas and avoids new heavy runtime dependencies. |
| Use a global migration registry | The source plan requires migrations to be owned by each document family to avoid process-global state and hidden registration behavior. |
| Keep config dependencies hard-installed for one tested shape | The v0-post gate selected an optional `config` extra so primitive and inspection consumers can install `loom` lightly. |
| Skip optional dependency tests by default without separate evidence | Phase 1 must make skipped versus executed optional suites visible in `make test-summary`. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Not every existing persisted model may be migrated to the new schema helpers in Phase 1. | A focused migration keeps the first hardening PR reviewable while proving the shared API. | Revisit when a persisted model changes or before Phase 4 event/outcome documents add new schema shapes. |
| Config tests may move into a separate config-extra target instead of default validation. | The optional install split requires no-extra validation to remain clean while still preserving config evidence. | Revisit if `make test-summary` stops showing both no-extra and config-extra results. |
| Config package lazy-import behavior may be transitional. | `import loom.config` should stay cheap and no-extra-safe, but full config symbols require optional dependencies. This avoids a stage factory or target-resolution redesign in Phase 1. | Revisit in Phase 3 when stage factory and import-safe construction are implemented. |
| Provenance, planning, local-store wrapper, and artifact-index readers keep some local validation helpers. | Migrating every persisted reader would turn the schema-helper proof into a broad refactor. | Revisit when each document family changes, before Phase 4 adds event/outcome documents, and before Phase 5 edits planning model serialization. |

## Reviewability

- Expected PR size and shape: moderate foundational PR touching serialization helpers, core value-object normalization, schema helper tests, packaging metadata, harness/Makefile evidence, and targeted docs. Avoid mixing in future store, runner, planner, or recipe behavior.
- Files and areas to inspect:
  - `src/loom/serialization/plain.py`
  - `src/loom/serialization/schema.py`
  - `src/loom/serialization/__init__.py`
  - `src/loom/refs.py`
  - `src/loom/artifacts.py`
  - `src/loom/records/`
  - `src/loom/pipeline/specs.py`
  - `src/loom/pipeline/status.py`
  - `src/loom/pipeline/execution/models.py`
  - `src/loom/config/`
  - `pyproject.toml`, `uv.lock`, `Makefile`, and `tools/test_harness/cli.py`
  - `tests/package/test_import_boundaries.py`, `tests/unit/loom/serialization/test_schema.py`, core value-object unit tests, and config optional-dependency tests
  - `docs/structure.md`, `docs/features/serialization.md`, and `docs/features/config.md`
- Scope-control checks: no new public store/context/factory/runtime/planner APIs; no changed runner behavior except import-boundary safety that is directly required by optional packaging; no config feature expansion.

## Implementation Steps

1. Add failing immutability and thaw tests in `tests/unit/loom/serialization/test_plain.py`, `tests/unit/loom/test_refs.py`, `tests/unit/loom/test_artifacts.py`, `tests/unit/loom/test_records.py`, and `tests/unit/loom/pipeline/test_specs.py`. Cover constructor-input mutation, attribute-level mutation attempts, nested list/dict mutation attempts, and independent mutable `to_dict()` output.
2. Implement `freeze_plain_data()` and `thaw_plain_data()` in `src/loom/serialization/plain.py`, export them from `src/loom/serialization/__init__.py`, and keep `ensure_plain_data()` and `to_plain_data()` returning mutable plain data.
3. Apply immutable normalization to in-scope value objects. Use `freeze_plain_data()` for plain-data fields, `MappingProxyType` for `Record.resources` and `StageSpec.outputs`, tuple normalization for `PipelineSpec.stages`, and recursive thawing for every public serialization or copy path that currently does `dict(...)` shallow copies.
4. Expand `src/loom/serialization/schema.py` with `require_mapping()`, `validate_document_fields()`, `load_versioned_document()`, and unit tests for unknown fields, missing fields, non-mapping inputs, invalid schema versions, future/unsupported versions, valid sequential migrations, missing migrations, and invalid migration output.
5. Migrate `InMemoryManifest.from_dict()`, `RunStatusRecord.from_dict()`, `StageStatusRecord.from_dict()`, and `ExecutionFailure.from_dict()` to `load_versioned_document()`. Preserve existing domain-specific error types by wrapping `SchemaVersionError`, add unknown-field tests for `ExecutionFailure`, and do not migrate planning/provenance/local-store wrapper readers in this phase.
6. Move OmegaConf, Pydantic, and PyYAML into `[project.optional-dependencies].config`, update `uv.lock`, and adjust `src/loom/config/__init__.py` so no-extra `import loom.config` stays import-safe while config-only symbol access or behavior fails clearly with a `loom[config]` message when extras are absent.
7. Mark config-dependent package, unit, integration, and docs tests with `optional_dependency`; route `tests/package/test_config_api.py`, `tests/unit/loom/config/`, `tests/integration/config/`, `tests/integration/pipeline/test_pipeline_config.py`, and `tests/integration/docs/test_v0_python_examples.py` through config-extra evidence.
8. Update `tools/test_harness/cli.py` and `Makefile` with isolated `test-no-extra` and `test-config-extra` targets. Keep `make test` as the default no-extra suite, make `make validate-pr` include no-extra default validation and config-extra validation, and make `make test-summary` include rows for package, unit, contract, integration, e2e, and config-extra.
9. Update `docs/structure.md`, `docs/features/serialization.md`, `docs/features/config.md`, and `tests/README.md` for recursive immutability, schema helper ownership, optional config dependencies, and the no-extra/config-extra harness split.
10. Run targeted package/unit/no-extra/config-extra checks during implementation, then leave final `make validate-pr` and `make test-summary` evidence for PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths:
  - `tests/package/test_import.py`
  - `tests/package/test_public_api.py`
  - `tests/package/test_import_boundaries.py`
  - `tests/package/test_config_api.py`, marked or routed as config-extra evidence.
- Required assertions:
  - `import loom` does not import `loom.config`, `loom.pipeline`, `loom.cli`, OmegaConf, PyYAML, or Pydantic.
  - Core primitive, record, artifact, serialization, store, and inspection imports succeed without `config` extras.
  - `import loom.config` succeeds without optional dependencies and does not import pipeline, execution, stores, CLI, YAML, OmegaConf, or Pydantic.
  - Config public API behavior is covered in the config-extra path; no-extra config-only symbol access or behavior fails with a clear config-owned missing-extra error.
  - `make test-summary` records no-extra package evidence and config-extra evidence separately.

### Unit Suite

- Status: required.
- Expected paths:
  - `tests/unit/loom/test_refs.py`
  - `tests/unit/loom/test_artifacts.py`
  - `tests/unit/loom/test_records.py`
  - `tests/unit/loom/pipeline/test_specs.py`
  - `tests/unit/loom/serialization/test_plain.py`
  - `tests/unit/loom/serialization/test_schema.py`
  - `tests/unit/loom/pipeline/test_status.py`
  - `tests/unit/loom/pipeline/execution/test_execution_models.py`
  - config unit tests under `tests/unit/loom/config/`, marked or routed as config-extra evidence.
- Required assertions:
  - Nested mappings and sequences on frozen objects cannot be mutated through object attributes.
  - Mutating constructor input after construction does not affect the object.
  - Mutating `to_dict()` output does not affect the object and output consists of ordinary `dict` and `list` values.
  - Schema helpers reject non-mapping input, missing required fields, unknown fields, missing/invalid/unsupported versions, and invalid migration outputs.
  - Known older-version examples dispatch through explicit document-owned migrations in schema-helper tests.
  - `InMemoryManifest`, run status, stage status, and execution failure readers reject unknown fields and unsupported versions through the shared helper path.

### Contract Suite

- Status: deferred for new extension contracts; existing contract suite still runs in final summary.
- Expected paths:
  - Existing `tests/contracts/` suite.
- Required assertions or deferral reason:
  - Phase 1 adds shared helper behavior rather than a new extension protocol. Do not add new contract tests unless implementation unexpectedly exposes a reusable persisted-document extension protocol; otherwise record existing contract suite evidence through `make test-summary`.

### Integration Suite

- Status: required for config-extra validation; default no-extra integration coverage may exclude optional config tests.
- Expected paths:
  - `tests/integration/config/`
  - `tests/integration/docs/test_v0_python_examples.py`
  - `tests/integration/pipeline/test_pipeline_config.py`
  - any integration test that imports YAML/config dependencies.
- Required assertions:
  - Config composition and recipe behavior still pass when run with the `config` extra installed.
  - Tests that require YAML/OmegaConf/Pydantic are marked or routed so default no-extra validation does not silently depend on those packages.
  - Docs/example YAML parsing is visible in config-extra evidence or explicitly separated from no-extra evidence.

### E2E Suite

- Status: required to run in final PR evidence, but no new e2e behavior is required by this phase.
- Expected paths:
  - `tests/e2e/test_local_pipeline_run.py`
- Required assertions or deferral reason:
  - Existing local pipeline e2e must continue to pass under the install shape selected by the refined harness. Add new e2e coverage only if optional dependency packaging changes would otherwise make the local public workflow untested.

### Opt-In Suites

- Status: required for config optional dependency evidence; other opt-in suites deferred.
- Markers affected:
  - `optional_dependency`
  - existing `slow`, `slurm`, and `network` remain excluded unless already part of future explicit workflows.
- Required assertions:
  - Add `make test-config-extra`, backed by `uv run --isolated --locked --group dev --extra config`, to run config-marked package/unit/integration/docs tests.
  - Add `make test-no-extra`, backed by `uv run --isolated --locked --group dev`, to prove default imports and default non-optional suites without the config extra.
  - `make test-summary` must show which optional config tests were executed versus skipped.

## Risks

- Recursive immutable wrappers can accidentally leak into `to_dict()` output and break serialization callers.
- A shallow thaw can leave nested immutable or shared mutable values in public output.
- Moving config dependencies to extras can expose hidden imports through package `__init__` files or pipeline runtime paths.
- Optional dependency evidence can be contaminated if no-extra and config-extra runs share a synchronized environment that retains optional packages.
- Over-migrating persisted readers to the new schema API could turn Phase 1 into a broad refactor. The selected migration set is intentionally limited to manifest, status, and execution failure documents.
- Documentation currently says config dependencies are hard for v0; this must be corrected with the phase-local contract updates.

## Validation Commands

Targeted development commands:

```sh
make test-no-extra
make test-package
make test-unit
make test-config-extra
```

The executor may run narrower direct commands while implementing a slice, but the named targets above are the phase-level targeted gates. `make test-no-extra` and `make test-config-extra` must use isolated `uv run` environments so optional dependencies installed for config validation cannot contaminate no-extra evidence.

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

`make validate-pr` must include Ruff, Pyright, the default no-extra test path, config-extra validation, and build. `make test-summary` must record package, unit, contract, integration, e2e, and config-extra suite rows.

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - Slice 1: serialization helper tests plus `freeze_plain_data()` and `thaw_plain_data()` in `src/loom/serialization/plain.py` and `src/loom/serialization/__init__.py`.
  - Slice 2: recursive immutability for refs, artifacts, records/manifests/views, output specs, stage specs, and pipeline specs.
  - Slice 3: schema helper API plus migrations for `InMemoryManifest`, run status, stage status, and execution failure readers.
  - Slice 4: optional `config` extra packaging, lazy no-extra-safe `loom.config` import behavior, and import-boundary tests.
  - Slice 5: isolated no-extra/config-extra Makefile and harness summary evidence.
  - Slice 6: documentation updates for structure, serialization, config, and testing.
- Tests to run with each slice:
  - Slice 1: `uv run pytest tests/unit/loom/serialization/test_plain.py`.
  - Slice 2: `uv run pytest tests/unit/loom/test_refs.py tests/unit/loom/test_artifacts.py tests/unit/loom/test_records.py tests/unit/loom/pipeline/test_specs.py`.
  - Slice 3: `uv run pytest tests/unit/loom/serialization/test_schema.py tests/unit/loom/test_records.py tests/unit/loom/pipeline/test_status.py tests/unit/loom/pipeline/execution/test_execution_models.py`.
  - Slice 4: `make test-no-extra` and `make test-config-extra`.
  - Slice 5: `make test-summary`.
  - Slice 6: docs do not require a separate broad check beyond the final PR-preparation gates unless examples or docs tests are edited.
- Decisions the executor must not revisit:
  - Recursive immutability is required.
  - `to_dict()` output remains mutable plain data.
  - Strict unknown-field and unsupported-version rejection remains the default.
  - Migrations are document-owned, not globally registered.
  - Config dependencies move behind the `config` extra.
  - The selected persisted-reader migration set is manifest, run status, stage status, and execution failure only.
  - `ArtifactAddress`, store/context capability APIs, lock/event/runtime foundations, stage factory/fingerprint policy, planner decomposition, recipe catalog policy, and runner lifecycle changes are out of scope.
  - Serial human merge gate remains active; Codex must not approve or merge.
- Conditions that require stopping for the manager:
  - The no-extra/config-extra split cannot be proven without broad runner or stage factory redesign.
  - Dependency lock resolution is unavailable and cannot be reproduced from the existing lock/cache.
  - A required import-boundary fix would implement future store, context, factory, planner, runtime, or recipe behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed in draft commit `f0a9fdf258645960b78128e14accb40c3a86dcde`.
- Final phase execution plan: completed in this artifact.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- PR preparation: pending.
- Stack maintenance: pending.
- Remaining blockers: none.
