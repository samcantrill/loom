# Phase 4 Execution Plan: Hard Switch Loom Adapters To `weave`

## Metadata

- Status: refined phase execution plan; ready for implementation
- Feature focus: Config Extraction
- PR title: `Config Extraction - Phase 4: Hard Switch Loom Adapters`
- Branch: `codex/weave-hard-switch-adapters`
- Worktree: `/home/samcantrill/work/loom-worktrees/weave-hard-switch-adapters`
- Phase execution plan path: `docs/roadmap/stage-23/phases/weave-hard-switch-adapters.md`
- Full plan: `docs/roadmap/stage-23/implementation-plan.md`
- Planning artifact: `docs/roadmap/stage-23/planning.md`
- Source phase: Stage 23 Phase 4, Hard Switch Loom Adapters And Import Boundaries
- Stack predecessor: none; Phases 1, 2, and 3 are merged
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible only after automated review, required validation, and CI pass while targeting `develop`; phase agents must not merge.
- Workflow path: expanded path
- Expanded-path reason: this phase changes package dependency metadata, removes a source-tree package, rewires public adapter paths, enforces import boundaries, and splits plugin diagnostics behavior.
- Successor dependency notes: Phase 5 should branch from updated `develop` after this phase merges. If a GitHub-side blocker leaves this PR open after validation and PR preparation, Phase 5 may stack on `codex/weave-hard-switch-adapters` only after this phase is recorded as `pr_open`.
- Plan quality gate: passed on 2026-05-20 in the implementation plan, with no blocking findings after confirmation review; verified before this phase plan was drafted.
- Plan quality gate loop budget: consumed and passed before this phase plan; do not rerun unless the manager explicitly reopens the stage plan.
- Draft pass: completed in this artifact and committed.
- Refine pass: completed in this artifact; expanded-path planning budget is consumed for this phase unless the manager explicitly reopens planning.
- Setup limitations: branch and worktree were created from local `develop` at `e39c974`; no network fetch was performed. Initial worktree creation needed sandbox escalation because git refs in the control checkout metadata were read-only to the sandbox.
- Blockers: none known. Implementation must stop if `src/loom/config` cannot be removed without a shim, if root Loom needs broad runtime imports from `weave`, if config errors cannot preserve CLI/config exit behavior through adapter translation, or if root package metadata cannot depend on the local `weave` package coherently.

## Refinement Summary

- Tightened the adapter handoff around error translation: config-owned `weave` errors should be caught or normalized in approved adapter paths, without eager `weave` imports from CLI roots or runtime internals.
- Made package metadata validation explicit: root Loom must resolve the local `packages/weave` package and must not accidentally depend on an unrelated external `weave` distribution.
- Clarified the reference sweep: remaining `loom.config` references after implementation must be historical documentation or deliberate absence assertions, not executable imports.
- Kept Phase 5 ownership intact: broad test and example relocation remains out of scope, while Phase 4 updates enough root tests to prove the hard switch and no-shim boundary.

## Objective

Hard-switch Loom's authored-config adapter paths to `weave`, delete the old `src/loom/config` implementation with no compatibility shim, and prove Loom runtime internals remain independent from config composition except through explicit adapter edges.

## Full-Plan Context

Stage 23 extracts trusted config authoring from Loom into the standalone `weave` distribution. Phases 1 through 3 pinned golden artifacts, created the package shell, and ported the implementation into `packages/weave`. Phase 4 performs the highest-risk cutover: Loom should now consume authored config through `weave`, runtime sweep specs must stop importing config override modules, recipe plugin loading must be config-owned, root package metadata must install `weave`, and import-boundary tests must enforce the final no-shim policy.

This phase must not relocate all config tests or examples into `packages/weave`; Phase 5 owns that cleanup. It must also avoid broad docs hardening, which remains Phase 6.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; all earlier Stage 23 phases are merged, and local `develop` is at `e39c974`.
- Why this base branch is correct: the user assigned Phase 4 from current `develop`, with stack predecessor `none`.
- Retarget or rebase plan after predecessor merge: not applicable for this root phase.
- Branch cleanup constraints: branch may be deleted after the phase PR is merged and no successor branch depends on it; keep it if a stacked successor is created before merge.

## Source Phase Summary

- Goal: make Loom adapter paths call `weave`, remove `src/loom/config`, and lock the final import boundary.
- Required scope: CLI config commands, diagnostics preflight config composition, queue config loading/composition, plugin diagnostics recipe loading, runtime sweep override validation ownership, root package dependency metadata, lock/workspace metadata, root tests that intentionally reference `loom.config`, and import-boundary tests.
- Required checkpoints: no `src/loom/config` remains, `import loom.config` fails by default, Loom runtime internals do not import `weave`, allowed adapter modules can import and call `weave`, recipe diagnostics remain metadata-only when `load=False`, and `load=True` delegates recipe catalog loading to `weave`.
- Acceptance criteria: package, unit, contract, integration, e2e, opt-in, package-local, build, lock, isolated install/import, and combined PR validation pass or blocked commands are recorded with exact reasons by the executor and PR preparer.

## Current Source And Harness Findings

- `src/loom/config/**` still exists as the pre-cutover implementation copy. It must be removed rather than retained as a wrapper or shim.
- `packages/weave/src/weave/**` now contains the ported config implementation, package-owned helpers, package-owned errors, and `weave.recipes.load` with the Stage 23 `loom.recipes` entry-point group.
- Loom adapter imports from `loom.config` currently appear in `src/loom/cli/validate.py`, `src/loom/cli/plan.py`, `src/loom/cli/run.py`, `src/loom/cli/sweep.py`, `src/loom/diagnostics/preflight.py`, `src/loom/queue/config.py`, `src/loom/plugins/diagnostics.py`, and `src/loom/pipeline/sweep/spec.py`.
- `src/loom/plugins/recipes.py` still exposes a Loom plugin adapter for recipe entry points. Phase 4 must either narrow it to metadata compatibility or redirect recipe loading to `weave` without making generic plugin code own config catalog semantics.
- Root `pyproject.toml` still keeps OmegaConf, Pydantic, and PyYAML under the `config` extra and does not yet depend on `weave`; package-local `packages/weave/pyproject.toml` owns those runtime dependencies.
- Root import-boundary tests still contain Phase 1 current-state `loom.config` assertions and Phase 3 `weave` assertions. They need to flip to final Phase 4 assertions.
- Root tests still reference `loom.config` heavily. This phase should update or replace the tests necessary to prove root adapter behavior and final no-shim boundaries, but it must not relocate every config-owned test or example into the package-local tree.

## In-Scope Work

- Replace Loom adapter imports from `loom.config` with lazy `weave` imports in approved adapter paths:
  - `src/loom/cli/validate.py`
  - `src/loom/cli/plan.py`
  - `src/loom/cli/run.py`
  - `src/loom/cli/sweep.py`
  - `src/loom/diagnostics/preflight.py`
  - `src/loom/queue/config.py`
  - `src/loom/plugins/diagnostics.py` only for recipe diagnostics with loading requested
- Introduce a small Loom-owned config adapter helper only if it reduces duplicated composition/error translation in allowed adapter paths. It must not live under `src/loom/config`, and runtime internals must not import it.
- Translate `weave.errors.ConfigError` and structured config-owned subclasses into existing Loom CLI/config diagnostics and exit categories at adapter boundaries. Do not make `loom.cli.errors` eagerly import `weave`.
- Delete `src/loom/config/**` after all root imports are rewired.
- Replace `src/loom/pipeline/sweep/spec.py` imports from config override modules with Loom-owned override path validation or adapter-normalized plain-data handling that preserves current sweep semantics.
- Split recipe plugin behavior so metadata discovery stays Loom-owned, recipe catalog loading is delegated to `weave`, and metadata-only plugin listing does not import config composition.
- Update `src/loom/plugins/diagnostics.py` so `load=False` remains metadata-only and `load=True` for `loom.recipes` delegates loading to `weave.recipes.load` using a `weave.RecipeCatalog`.
- Update root package metadata so installing `loom` installs or resolves the local `weave` package for supported config adapter workflows. Refresh `uv.lock` or workspace metadata as needed, and remove or reshape the old root `config` extra after its runtime dependencies are owned by `weave`.
- Update root tests that directly assert `loom.config` public API behavior into either `weave` package tests or root adapter/boundary tests. Keep the moves narrow enough that Phase 5 still owns full test/example relocation.
- Update import-boundary tests to forbid `loom.config`, prove `weave` imports no `loom`, prove core runtime imports do not import `weave`, and prove only approved adapter modules import `weave` when exercising config workflows.

## Out-of-Scope Work

- Moving all config tests into `packages/weave/tests`.
- Moving authoring examples into `packages/weave/examples`.
- Broad docs, README, roadmap, or structure-documentation hardening beyond narrow comments or phase notes needed for this cutover.
- New config language semantics, new artifact schema versions, or new recipe plugin entry-point groups.
- A `loom.config` compatibility shim, re-export package, lazy module proxy, or migration alias.
- Moving Loom runtime serialization, fingerprinting, sweep, pipeline, store, provenance, or queue record ownership into `weave`.
- Runtime-only Loom packaging without the config adapter dependency.
- Opening a PR or updating implementation-plan status from this planning task.

## Assumptions

- Root Loom may depend on `weave` as a normal local package dependency for this stage.
- `weave` package error payloads remain structured and can be converted or surfaced by Loom adapters without shared inheritance from `loom.errors.ConfigError`.
- Root tests may continue to live under root paths during Phase 4 when they prove Loom adapter behavior; Phase 5 owns final ownership cleanup.
- The Stage 23 `loom.recipes` entry-point group remains the group name, even though recipe catalog loading is config-owned.
- Any stale docs or example references to `loom.config` that are not needed for tests can wait for Phase 5 or Phase 6 unless they block import scans required by Phase 4.

## Scope Contract

The only allowed runtime relationship after this phase is explicit: Loom adapter paths may call `weave` to compose trusted authored config and hand plain resolved data or explicit config records to Loom runtime code. Loom runtime internals must not import `weave` composition modules or use `weave` helper modules as generic serialization, fingerprinting, error, or override utilities.

No `loom.config` module may remain. If a test, CLI command, or import path still requires `loom.config`, the executor should either update it to `weave` or mark the phase blocked. Do not satisfy that requirement with a shim.

CLI and adapter diagnostics must remain user-facing compatible. The Python module identity of config errors may change from `loom.config` to `weave`, but config-facing exit codes, text/JSON error shape, warning behavior, and structured context should remain stable unless an intentional break is recorded.

Root packaging must prove that a user installing Loom can still run supported authored-config workflows through `weave`. Do not leave root `loom` relying on an editable checkout path or a manually injected `PYTHONPATH` for adapter workflows.

## Acceptance Criteria

- Loom CLI config workflows (`validate`, `plan`, `run`, and config-consuming `sweep` paths) call `weave` through approved lazy adapter imports and preserve existing config diagnostics.
- Diagnostics preflight and queue config composition call `weave` only when config loading is requested.
- Plugin diagnostics with `load=False` remains metadata-only and does not import `weave`; recipe diagnostics with `load=True` delegates recipe catalog loading to `weave` and reports loaded, duplicate, and failure records correctly.
- `src/loom/config` is deleted and no `loom.config` shim, alias, or module proxy remains.
- Runtime sweep spec validation no longer imports `loom.config` or `weave`, while preserving accepted override path/value behavior.
- Root package metadata depends on local `weave` for supported config adapter workflows; lock or workspace metadata is current.
- Root package/build evidence proves the dependency resolves the local `packages/weave` project rather than an unrelated package with the same name.
- `import loom`, `import loom.pipeline`, `import loom.serialization`, `import loom.plugins`, `import loom.queue`, and other core runtime imports do not import `weave`.
- `weave` imports no `loom` after bare import, public config symbol resolution, recipe loading, and representative composition calls.
- Root tests that intentionally asserted `loom.config` behavior are updated to the `weave` surface or to Loom adapter boundaries, without broad Phase 5 relocation.
- `make validate-weave`, lock/build/package smoke checks, root package/contract/integration/e2e suites, `make validate-pr`, and final PR evidence commands pass or blocked commands are recorded with exact reasons.

## Design Impact

- Maintainability: removes the temporary duplicate implementation and makes config ownership explicit.
- Extensibility: makes `packages/weave` the only config implementation path, which supports future repository extraction.
- Source-tree boundaries: deletes the old config package and turns Loom into an adapter consumer of `weave`, not a second config owner.
- Public contract: applies the confirmed hard-switch policy and intentionally breaks `loom.config` imports without a compatibility shim.
- Dependency contract: moves config runtime dependency responsibility to `weave` while root Loom depends on `weave` for supported authored-config workflows.

## Future Compatibility

- Phase 5 can relocate tests and examples from a repository that no longer has two config implementations.
- Phase 6 can update docs against the final import path and source-tree boundary.
- A future standalone `weave` repository should be able to lift the package without discovering hidden Loom runtime imports.
- Future runtime-only Loom install work remains possible because the adapter edges are explicit, even though this stage keeps `weave` as a normal Loom dependency.
- A future plugin-group rename can build from the `weave` recipe loader while preserving the Stage 23 `loom.recipes` compatibility decision.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep `src/loom/config` as a re-export shim | The implementation plan and user decision require a hard switch with no default compatibility shim. |
| Leave root Loom adapters on `loom.config` until Phase 5 | This would keep two config implementations and violate Phase 4's removal goal. |
| Let runtime sweep specs import `weave.overrides` | Runtime sweep records are Loom-owned and must not depend on config composition internals or config helper modules. |
| Make `loom.cli.errors` import `weave.errors` eagerly | That would make CLI import-light behavior depend on config package imports. Adapter-local translation keeps the boundary explicit. |
| Move every config test and example now | Phase 5 owns ownership relocation and validation-summary integration; Phase 4 needs only enough root updates to prove the hard switch. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Adapter-local config error translation may duplicate catch/wrap logic | Keeps `weave` out of CLI/runtime import roots and avoids shared inheritance. | Translation grows beyond a small helper or diagnostics drift appears across CLI commands. |
| Root tests may still contain config-owned behavior under root paths | Phase 4 must prove the hard switch before broad relocation. | Phase 5 should move or de-duplicate remaining config-owned tests. |
| Root Loom depends on `weave` for config adapter workflows | Runtime-only install work is explicitly deferred. | A future runtime-only packaging phase begins or config dependency footprint becomes unacceptable. |
| Stage 23 keeps the `loom.recipes` entry-point group name | Preserves existing recipe plugin metadata while changing loader ownership. | A standalone `weave` repo needs an independently named group or dual-group migration. |

## Reviewability

- Expected PR size and shape: high-risk but bounded cutover PR with adapter import rewrites, old source deletion, package metadata and lock updates, import-boundary tests, and focused root adapter test updates.
- Primary files and areas to inspect: allowed adapter modules, `src/loom/pipeline/sweep/spec.py`, `src/loom/plugins/diagnostics.py`, `src/loom/plugins/recipes.py` if retained, root `pyproject.toml`, `uv.lock`, import-boundary tests, and focused CLI/queue/diagnostics/plugin/sweep tests.
- Scope-control checks: no `src/loom/config` remains, no `loom.config` shim, no broad docs rewrite, no wholesale test/example relocation, no new config semantics, no new plugin group, and no runtime internals importing `weave`.

## Implementation Steps

1. Rewire CLI, diagnostics, queue, and sweep adapter imports to `weave` with lazy imports and adapter-local config error translation.
2. Replace runtime sweep override validation with Loom-owned logic or adapter-normalized plain data, preserving current accepted override path behavior.
3. Split plugin diagnostics so recipe loading delegates to `weave.recipes.load` while metadata-only listing stays Loom-owned and import-light.
4. Update root package metadata and lock/workspace files so Loom resolves `weave` for config adapter workflows.
5. Delete `src/loom/config/**` and remove stale internal references to `loom.config`.
6. Update focused root tests and import-boundary tests for the final no-shim `weave` boundary.
7. Run a reference sweep for `loom.config`; any remaining source or test reference must be an intentional absence assertion or a documented historical note.
8. Run targeted package, root, packaging, and smoke validation; stop on import-boundary regressions, diagnostics drift, metadata incoherence, or inability to delete the old source path.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `packages/weave/tests/`, `tests/package/test_import_boundaries.py`, and root package/API tests that are updated from `loom.config` to `weave` or root adapters.
- Required assertions or deferral reason: prove `weave` remains importable and Loom-free; prove root package metadata resolves the local `packages/weave` project; prove `loom.config` is absent; prove core runtime imports do not import `weave`; prove allowed adapter modules can call `weave`.

### Unit Suite

- Status: required
- Expected paths: focused unit tests for CLI config helpers, queue config loading, plugin diagnostics, sweep spec override validation, and any adapter helper introduced in this phase.
- Required assertions or deferral reason: cover error translation to config exit categories, metadata-only plugin diagnostics without `weave`, recipe diagnostics with `load=True`, and runtime sweep override path validation without config imports. Full config-owned unit relocation is deferred to Phase 5.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_config_extraction_golden_artifacts_contract.py`, plugin discovery/recipe diagnostics contracts, import-boundary contracts, and existing CLI/config contracts updated to `weave` or adapter surfaces.
- Required assertions or deferral reason: golden config artifacts remain stable through `weave`; structured config error payloads remain user-facing compatible; recipe plugin metadata group remains `loom.recipes`; no shim is present.

### Integration Suite

- Status: required
- Expected paths: root config-consuming integration tests for pipeline config, queue config, diagnostics preflight, plugins, and sweeps, plus package-local integration-style coverage already under `packages/weave/tests`.
- Required assertions or deferral reason: representative Loom workflows compose authored config via `weave` and hand resolved plain data into runtime internals without importing config internals.

### E2E Suite

- Status: required
- Expected paths: existing CLI e2e tests that cover config composition public API, local pipeline run, validate/plan/run paths, and sweep paths as applicable.
- Required assertions or deferral reason: prove user-facing CLI hard-switch workflows run through `weave` and preserve config exit behavior. Full example relocation remains Phase 5.

### Opt-In Suites

- Status: required
- Markers affected: `config-extra`, `optional_dependency`, package-local `weave` checks, build/package smoke checks, and any existing opt-in CLI/config dependency tests.
- Required assertions or deferral reason: `make test-config-extra` must exercise Loom adapter workflows through `weave`; `make validate-weave` must continue to pass; no network, external plugin registry, SLURM, Docker, or remote-store opt-in evidence is required unless touched tests already require local simulation.

## Validation Commands

Targeted development commands:

```sh
make validate-weave
uv lock --check
uv build
uv run pytest tests/package/test_import_boundaries.py
rg "loom\\.config" src tests packages pyproject.toml
uv run pytest tests/unit/loom/cli/test_validate.py tests/unit/loom/cli/test_plan.py tests/unit/loom/cli/test_run.py tests/unit/loom/cli/test_sweep.py
uv run pytest tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/unit/loom/queue tests/unit/loom/plugins/test_diagnostics.py tests/unit/loom/pipeline/sweep
uv run pytest tests/contracts/test_config_extraction_golden_artifacts_contract.py tests/contracts/test_recipe_contract.py tests/contracts/test_cli_plugins_contract.py
uv run pytest tests/integration/config tests/integration/pipeline/test_pipeline_config.py tests/integration/diagnostics tests/integration/pipeline/test_local_execution.py
uv run pytest tests/e2e/test_config_composition_public_api.py tests/e2e/test_local_pipeline_run.py
```

Packaging and smoke checks:

```sh
uv build
isolated installed-package import and minimal config-facing CLI smoke using built root artifacts
```

Final PR-preparation commands:

```sh
make test-package
make test-contract
make test-integration
make test-e2e
make test-config-extra
make validate-pr
make test-summary
```

If a validation command cannot run because dependency downloads or isolated install setup is unavailable, record the exact blocker and the closest targeted evidence that did run. Do not silently replace the root packaging smoke with `PYTHONPATH`-only evidence.

## Risks

- Removing `src/loom/config` can expose hidden imports in tests, examples, CLI adapters, queue loading, preflight diagnostics, or plugin diagnostics.
- Config-owned errors no longer inherit from Loom error roots, so adapter translation must preserve exit codes and structured diagnostics.
- Root package metadata can accidentally resolve an external `weave` package or rely on editable checkout state instead of the local package.
- Import-boundary tests can become too loose if they only check bare imports and do not exercise allowed adapter calls.
- Runtime sweep override validation can drift from config override semantics if the duplicate validation is under-tested.
- Plugin diagnostics can accidentally import config composition during metadata-only listing.

## Stop Conditions

- `src/loom/config` cannot be deleted without keeping a shim or breaking required root adapter workflows.
- Any forbidden runtime area imports `weave`, including pipeline, stores, authority, records, serialization, provenance, or IO.
- `weave` imports any `loom` module during import, public symbol resolution, recipe loading, or representative composition.
- Config CLI errors map to operation-failed/internal categories instead of config diagnostics after the hard switch.
- Root package metadata cannot resolve local `weave` coherently for an installed-package smoke.
- Golden config artifacts drift without an accepted break, rationale, migration note, and fixture update review.
- Metadata-only plugin listing imports `weave` or loads recipe targets.
- Phase 4 implementation requires broad test/example relocation or docs hardening that belongs to Phase 5 or Phase 6.

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: adapter import/error translation; sweep override ownership; plugin diagnostics split; root metadata and lock updates; old source deletion; focused tests and import-boundary enforcement.
- Tests to run with each slice: adapter unit/CLI tests after import rewrites, sweep tests after override validation replacement, plugin diagnostics tests after recipe loading split, lock/build/package tests after metadata changes, import-boundary tests after deleting `src/loom/config`, and root integration/e2e validation before PR preparation.
- Decisions the executor must not revisit: no `loom.config` shim, no new config semantics, no new plugin group, no broad docs rewrite, no full test/example relocation, no runtime helper imports from `weave`, and no shared helper package.
- Conditions that require stopping for the manager: any stop condition above, inability to preserve config diagnostics through adapter translation, lock/build evidence that resolves the wrong package, or a need to keep two config implementations.

## Refinement And Review Budget Status

- Planning/refinement budget: used; expanded-path draft and refine completed.
- Phase implementation refinement: unused until a later workflow stage consumes it; expanded path permits one `loom_phase_refiner` pass after implementation if targeted validation fails, coverage is missing, or manager requests it.
- PR review: unused until a later workflow stage consumes it.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: completed in commit `0494c97`.
- Refine plan: completed in this artifact.
- Final phase execution plan: ready for implementation after this refinement commit.
