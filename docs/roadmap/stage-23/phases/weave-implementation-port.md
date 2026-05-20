# Phase 3 Execution Plan: Config Implementation Port To `weave`

## Metadata

- Status: draft phase execution plan; refinement pending
- Feature focus: Config Extraction
- PR title: `Config Extraction - Phase 3: Implementation Port Into Weave`
- Branch: `codex/weave-implementation-port`
- Worktree: `/home/samcantrill/work/loom-worktrees/weave-implementation-port`
- Phase execution plan path: `docs/roadmap/stage-23/phases/weave-implementation-port.md`
- Full plan: `docs/roadmap/stage-23/implementation-plan.md`
- Planning artifact: `docs/roadmap/stage-23/planning.md`
- Source phase: Stage 23 Phase 3, Config Implementation Port To `weave`
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible only after automated review, required validation, and CI pass while targeting `develop`; phase agents must not merge.
- Workflow path: expanded path
- Successor dependency notes: Phase 4 should branch from updated `develop` after this phase merges. If GitHub-side blockers leave this PR open, Phase 4 may stack on `codex/weave-implementation-port` only after this phase is opened or prepared, validated, and recorded as `pr_open`.
- Plan quality gate: passed on 2026-05-20 in the implementation plan, with no blocking findings after confirmation review.
- Plan quality gate loop budget: consumed and passed before this phase plan; do not rerun unless the manager explicitly reopens the stage plan.
- Draft pass: completed in this artifact.
- Refine pass: pending; expanded-path planning budget remains open for one refinement commit.
- Setup limitations: branch was created from local `develop` at `d5f7e39`; no network fetch was performed. Initial worktree creation needed sandbox escalation because git refs in the control checkout metadata were read-only to the sandbox.
- Blockers: none; implementation must stop if `weave` cannot preserve golden config artifacts without importing Loom, if recipe loading requires importing `loom.plugins`, or if package-owned helper behavior must become a shared runtime utility surface.

## Objective

Port the current trusted config implementation into `packages/weave` so direct config users can exercise the public config APIs through `weave`, while keeping Loom's current in-tree `src/loom/config` implementation as the temporary baseline until Phase 4 performs the hard switch.

## Full-Plan Context

Stage 23 extracts config authoring from Loom into a standalone `weave` distribution. Phase 1 pinned golden artifact behavior and current import-boundary facts. Phase 2 created the package scaffold and config-owned helper foundations. This phase moves the implementation into the package, proves package-local config behavior, and preserves golden output compatibility. It must not rewire Loom adapters, delete `src/loom/config`, add a `loom.config` shim, or move the full config example and test ownership that Phase 5 owns.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 1 and Phase 2 are recorded as merged, and local `develop` includes the Phase 2 metadata commit `d5f7e39`.
- Why this base branch is correct: the user assigned Phase 3 from current `develop` with no stack predecessor after Phase 2 merged.
- Retarget/rebase plan after predecessor merge: not applicable for this root phase.
- Branch cleanup constraints: branch may be deleted after the phase PR is merged and no successor branch depends on it; keep it if a stacked successor is created before merge.

## Source Phase Summary

- Goal: port config composition, recipes, instantiation, provenance, source artifacts, redaction, overrides, includes, interpolation, source maps, target checks, and artifact-safe fingerprints into `weave`.
- Required scope: package-local implementation modules under `packages/weave/src/weave`, package-local tests under `packages/weave/tests`, package-local public API exports, recipe loading owned by `weave` while retaining the `loom.recipes` entry-point group, and golden parity checks against the Phase 1 baseline.
- Required checkpoints: `weave` imports no `loom`; package implementation imports package-owned helpers and errors; public config APIs work through `weave`; root Loom behavior remains on the old implementation until Phase 4; golden artifacts remain stable.
- Acceptance criteria: package-local config tests, golden parity, import-boundary tests, package validation, and root validation pass or any inability to run them is recorded by the executor and PR preparer.

## Current Source And Harness Findings

- Existing Loom config implementation lives under `src/loom/config`, including `api.py`, `compose.py`, `load.py`, `merge.py`, `overrides.py`, `includes.py`, `interpolation.py`, `redaction.py`, `provenance.py`, `artifacts.py`, `fingerprints.py`, `source_maps.py`, `target_checks.py`, `instantiate/`, and `recipes/`.
- Current Loom config modules import Loom-owned helpers from `loom.serialization`, `loom.fingerprints`, `loom.errors`, and `loom.__version__`; these imports must be replaced with package-owned `weave.plain`, `weave.json`, `weave.digests`, `weave.errors`, and `weave.__version__` or package-owned equivalents.
- Phase 2 already added `packages/weave` with normal dependencies on OmegaConf, Pydantic, and PyYAML, `py.typed`, `weave.__version__`, and helper modules for plain data, stable JSON, digests, and config-owned errors.
- Existing config tests are still root-owned across `tests/package/test_config_api.py`, `tests/contracts/test_config_*`, `tests/contracts/test_recipe_contract.py`, `tests/integration/config/**`, `tests/e2e/test_config_composition_public_api.py`, and Phase 1 golden fixtures under `tests/fixtures/config/golden_project/` plus `tests/golden/config/extraction-v23/`.
- Existing root import-boundary tests assert `import weave` does not import Loom and core Loom imports do not import `weave` before Phase 4.
- Existing Make targets include `make test-weave`, `make build-weave`, and `make validate-weave`; final summary integration remains later-phase work.

## In-Scope Work

- Add real public config APIs to `packages/weave/src/weave/__init__.py` and package modules, including `compose_config`, `compose_config_with_catalog`, `inspect_config_composition`, `register_recipe`, `Recipe`, `RecipeCatalog`, `instantiate`, `check_config_targets`, `TargetCheckResult`, `compare_config_artifact_fingerprints`, config artifact record types, raw source snapshot types, and structured config errors.
- Port implementation modules from `src/loom/config` into `packages/weave/src/weave`, rewriting package-internal imports to `weave` modules and package-owned helper surfaces.
- Replace Loom-owned helper usage with package-owned equivalents and add small package-owned helper additions only where the port needs equivalent config artifact behavior.
- Move recipe catalog and recipe entry-point loading ownership into `weave`, keeping the Stage 23 `loom.recipes` entry-point group string and avoiding imports from `loom.plugins`.
- Add package-local tests that prove config composition, overlays, includes, replacement, overrides, recipes, `_target_` instantiation, target checks, redaction, provenance, source artifacts, raw source snapshots, config fingerprints, structured config errors, and import boundaries through `weave`.
- Add or adapt package-local golden parity coverage that compares `weave` output to the Phase 1 expected artifacts.
- Keep `src/loom/config` and root Loom adapter paths unchanged except for truly mechanical test or tooling accommodations required to keep both implementations coexisting.
- Keep package validation targets working for the port; add only narrow tooling configuration needed by package-local tests.

## Out-of-Scope Work

- Removing, renaming, or shimming `src/loom/config`.
- Rewriting Loom CLI, queue, diagnostics, plugin diagnostics, or sweep adapter imports to `weave`.
- Making root `loom` package metadata depend on `weave` for adapter workflows.
- Updating root config API tests from `loom.config` to `weave` except where a package-local copy or counterpart is created under `packages/weave/tests`.
- Moving all config tests or examples into the package-local tree.
- Updating user-facing docs, roadmap docs, or PR body artifacts beyond this phase execution plan.
- Changing config language semantics, artifact schema, redaction policy, include resolution, override behavior, fingerprint policy, recipe semantics, or structured error payloads.
- Adding a final `loom.config` compatibility shim or any future-phase transition API.

## Assumptions

- Temporary duplicate implementation between `src/loom/config` and `packages/weave/src/weave` is accepted only until Phase 4 removes the old path.
- Phase 2 helper modules are close enough to the Loom helper behavior for the port, with small package-owned adjustments allowed when package tests prove a concrete config need.
- Package-local tests may duplicate root config tests during the transition; Phase 5 owns final relocation and de-duplication.
- Golden artifact parity can be checked against the existing Phase 1 fixtures and expected JSON without changing fixture schema.
- `weave` can own recipe entry-point loading by duplicating the minimal entry-point loader behavior it needs, without importing Loom plugin modules.

## Scope Contract

This phase creates the real config package implementation. It does not change how Loom currently consumes config. Root Loom modules must continue using `loom.config` until Phase 4, and `weave` must not import any `loom` module to satisfy its package-local APIs.

Public behavior in scope is the confirmed config surface under the `weave` import package. The `weave` public API should mirror the current config user surface where that surface is config-owned: composition, inspection, recipe catalog registration, target instantiation, target checking, artifact records, fingerprint comparison, raw source snapshots, and structured config errors. Loom-owned runtime helpers, runtime error roots, pipeline specs, sweep records, CLI diagnostics, queues, stores, provenance outside config composition, and plugin metadata listing remain Loom-owned.

Golden artifact behavior is a hard compatibility contract. The executor may update expected golden files only if a deliberate break is approved and recorded with rationale and migration notes; otherwise any mismatch is a stop condition.

## Acceptance Criteria

- `weave` public config APIs are real implementations, not stubs, and are exported from package-local modules without importing Loom.
- Package-local tests prove the new implementation covers current config behavior needed before adapter cutover.
- `weave` golden parity coverage matches the Phase 1 baseline for resolved config, redacted config, composition manifest, recipe manifest, source artifact records, raw source snapshots, config fingerprint record, and structured config errors.
- Package implementation uses package-owned plain-data, JSON, digest, fingerprint, version, and error helpers rather than Loom helper modules.
- Recipe loading is owned by `weave` while keeping the `loom.recipes` entry-point group name.
- Root `src/loom/config` remains available for current Loom tests and adapters until Phase 4.
- Import-boundary tests prove `weave` imports no `loom` after accessing public composition and recipe APIs, not only after bare `import weave`.
- `make validate-weave`, targeted package-local tests, Phase 1 golden contract, root import-boundary tests, and `make validate-pr` pass or blocked commands are recorded with exact reasons.
- No future-phase adapter rewiring, `src/loom/config` removal, docs hardening, or full test/example relocation is included.

## Design Impact

- Maintainability: the package implementation becomes reviewable before the old in-tree implementation is removed, reducing hard-switch risk.
- Extensibility: package-local source and tests move `weave` closer to a future standalone repository without dragging Loom runtime modules with it.
- Domain neutrality: ported tests and fixtures must stay synthetic and use generic config values, not domain-specific records, datasets, models, metrics, or reports.
- Source-tree boundaries: `packages/weave` owns config composition and artifacts; Loom runtime source remains the temporary consumer baseline until Phase 4.

## Future Compatibility

- Phase 4 can rewire Loom adapters to import `weave`, delete `src/loom/config`, and enforce final runtime import boundaries.
- Phase 5 can relocate and de-duplicate package-owned tests and examples once the old implementation is gone.
- Phase 6 can update documentation and roadmap metadata against a package boundary that has already been validated.
- A future standalone `weave` repository should be able to lift the package implementation without resolving Loom runtime imports.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Rewire Loom adapters while porting the package | That combines implementation movement with the highest-risk hard switch, which Phase 4 owns. |
| Keep `weave` as wrappers around `loom.config` | Violates the no-Loom-import package boundary and would not support future standalone extraction. |
| Import Loom helper modules from `weave` to reduce duplication | Violates the helper ownership split and would make config package behavior depend on Loom runtime modules. |
| Move all config tests and examples now | Phase 5 owns relocation and validation summary integration; this phase needs enough package-local coverage to prove the port. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Temporary duplicate config implementation in `src/loom/config` and `packages/weave/src/weave` | Allows package behavior to be validated before root adapter cutover. | Phase 4 must remove `src/loom/config`; if it cannot, mark Phase 4 blocked. |
| Package-local tests may duplicate root tests | Needed to prove `weave` before root test ownership is relocated. | Phase 5 relocates and de-duplicates config tests. |
| Recipe entry-point loader behavior may duplicate Loom plugin loader primitives | `weave` cannot import `loom.plugins`, but recipe loading is config-owned. | Future standalone plugin strategy changes the entry-point group or introduces a shared external plugin contract. |

## Reviewability

- Expected PR size and shape: implementation-port PR with package-local config modules, package-local tests, narrow package helper adjustments, and narrow Make/tooling updates if needed.
- Files and areas to inspect: `packages/weave/src/weave/**`, `packages/weave/tests/**`, `packages/weave/pyproject.toml`, package Make/tooling wiring, and root import-boundary tests only if they need stronger `weave` assertions.
- Scope-control checks: no `src/loom/config` deletion, no Loom adapter import rewrites, no root package dependency on `weave`, no `loom.config` shim, no full example relocation, no docs rewrite, and no artifact schema changes.

## Implementation Steps

1. Port package modules and public exports into `packages/weave/src/weave`, preserving the current config surface under `weave`.
2. Rewrite imports to package-owned helpers and errors, adding only concrete helper behavior required by config artifacts.
3. Add package-owned recipe entry-point loading without importing Loom plugin modules.
4. Add package-local tests for the ported public API, core config semantics, recipe behavior, instantiation, artifact records, fingerprints, structured errors, and import boundaries.
5. Add package-local golden parity coverage against Phase 1 fixtures and expected artifacts.
6. Run targeted package and root validation, stopping on golden drift, Loom imports from `weave`, broad helper expansion, or future-phase adapter requirements.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `packages/weave/tests/` and root `tests/package/test_import_boundaries.py` if import-boundary assertions need strengthening.
- Required assertions or deferral reason: verify `weave` import behavior, public API exports, no Loom imports after resolving public config symbols, package metadata, typing marker, and package-local public config API coverage.

### Unit Suite

- Status: required
- Expected paths: package-local tests under `packages/weave/tests/` for helpers, loading, merge, overrides, includes, interpolation, redaction, provenance, artifacts, fingerprints, recipes, instantiation, and target checks.
- Required assertions or deferral reason: cover the ported config-owned behavior needed before Loom adapter cutover. Root config unit tests remain in place until Phase 5.

### Contract Suite

- Status: required
- Expected paths: package-local contract-style tests under `packages/weave/tests/`, Phase 1 root golden contract at `tests/contracts/test_config_extraction_golden_artifacts_contract.py`, root recipe/config contracts as needed for baseline stability, and import-boundary contracts.
- Required assertions or deferral reason: compare package output with Phase 1 golden artifacts, verify structured error payload stability, verify recipe plugin loading through `weave`, and keep the old root contract green while the duplicate implementation exists.

### Integration Suite

- Status: required for package config behavior; deferred for Loom adapter rewiring
- Expected paths: package-local integration-style tests under `packages/weave/tests/` adapted from `tests/integration/config/**`; existing root `tests/integration/config/**` remains baseline coverage for `loom.config`.
- Required assertions or deferral reason: package tests must exercise composition flows through `weave`; root Loom adapter integration changes are deferred to Phase 4.

### E2E Suite

- Status: deferred for new Loom workflows
- Expected paths: existing root `tests/e2e/**` remains unchanged; package-local API smoke may be added under `packages/weave/tests/` if needed.
- Required assertions or deferral reason: no CLI hard switch or end-to-end Loom workflow behavior changes are in scope; e2e coverage remains indirect through final `make validate-pr`.

### Opt-In Suites

- Status: required
- Markers affected: package-local config dependency coverage, root `optional_dependency`, root `contract`, root `package`, and existing `config-extra` coverage.
- Required assertions or deferral reason: package tests require OmegaConf, Pydantic, and PyYAML as normal `weave` dependencies; root optional config suites remain the temporary Loom baseline until Phase 4 and Phase 5.

## Risks

- Copying implementation before deleting the old path can hide drift if package-local tests are too thin.
- Golden parity can fail because of package version fields, digest helper differences, or changed module names leaking into public payloads.
- Recipe plugin loading can accidentally import Loom plugin modules unless the package owns its minimal loader.
- Package helper additions can become broad runtime utilities rather than config-owned behavior.
- Test duplication can make Phase 5 relocation harder if package tests are copied without clear ownership.

## Stop Conditions

- `weave` imports any `loom` module during import, public symbol resolution, composition, recipe loading, instantiation, or golden parity tests.
- Golden artifacts differ from the Phase 1 baseline without an approved and recorded intentional break.
- Porting requires Loom adapters to consume `weave` before Phase 4.
- The old `src/loom/config` path must be removed, shimmed, or behaviorally changed to make package tests pass.
- Recipe loading cannot be implemented without importing `loom.plugins`.
- Package-owned helper behavior expands into a generic shared runtime utility layer.
- Package validation requires heavyweight tooling or dependencies beyond the stage plan.

## Validation Commands

Targeted development commands:

```sh
make validate-weave
uv run pytest packages/weave/tests
uv run pytest tests/contracts/test_config_extraction_golden_artifacts_contract.py
uv run pytest tests/package/test_import_boundaries.py
```

Additional targeted commands when touched areas require them:

```sh
uv run pytest tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_error_contract.py tests/contracts/test_config_composition_inspection_contract.py tests/contracts/test_recipe_contract.py
uv run pytest tests/integration/config
uv run pytest tests/package/test_config_api.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: package module port; helper replacement and package-owned error/version cleanup; recipe loader ownership; package-local tests; golden parity coverage; targeted import-boundary strengthening.
- Tests to run with each slice: package tests after module port, import-boundary tests after public export and loader work, golden parity after artifact/fingerprint/provenance work, and root golden/import-boundary tests before final handoff.
- Decisions the executor must not revisit: no `loom.config` shim, no adapter rewiring, no `src/loom/config` deletion, no shared core package, no Loom imports from `weave`, no config semantic changes, no broad docs or example relocation.
- Conditions that require stopping for the manager: any stop condition above, inability to preserve package-local golden parity, or any need to alter future Phase 4/5 scope to make Phase 3 pass.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: unused, 0/3 used

## Completion Notes

- Draft plan: completed in this artifact.
- Refine plan: pending.
- Final phase execution plan: pending refinement.
- Implementation summary: pending.
- Implementation validation: pending.
