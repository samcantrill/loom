# Phase 5 Execution Plan: Pipeline Persistence And Runtime Fingerprints

## Metadata

- Status: refined phase execution plan; ready for implementation
- Feature focus: V1 Post Configuration
- PR title: `V1 Post Configuration - Phase 5: Pipeline Persistence And Runtime Fingerprints`
- Branch: `codex/v1-post-pipeline-persistence`
- Worktree: `/home/samcantrill/work/loom-worktrees/v1-post-pipeline-persistence`
- Phase execution plan path: `docs/phases/v1-post-pipeline-persistence.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1-post.md`
- Source phase: Phase 5. Pipeline Persistence And Runtime Fingerprints
- Stack predecessor: none; Phases 1-4 have merged into `develop`.
- Base branch: `develop` / `origin/develop` at `aa9287a` (`docs: record v1-post phase 4 merged (#52)`)
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after review and checks because the target is `develop`.
- Workflow path: expanded planning path
- Successor dependency notes: Phase 6 may start from this branch only after this phase PR is opened or prepared, validated, and recorded as `pr_open`; Phase 6 still owns recipe residual-risk coverage and must not be pulled into this phase.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v1-post.md`; no blocking plan-review findings remain.
- Plan quality gate loop budget: initial review used, automated refinement used, confirmation review used.
- Draft pass: completed by `loom_phase_planner` in draft commit `9122e75`.
- Refine pass: completed by `loom_phase_planner`; expanded path was selected because this phase changes run-store protocol/persistence, `PipelineRunner` behavior, and runtime fingerprint policy.
- Setup limitations: `git worktree add` needed approved Git metadata access after the sandbox could not create the nested `refs/heads/codex/...` directory. No product-code setup blocker remains.
- Blockers: none for implementation.

## Objective

Align pipeline and run-store persistence with v1 artifact-safe config boundaries without making `loom.pipeline` depend on `loom.config`, and document/test that runtime object fingerprinting is explicit pipeline/runtime input rather than config fingerprint behavior.

## Full-Plan Context

V1-post closes contract gaps found after the v1 Phase 16 merge. Phases 1-4 have already merged the source boundary cleanup, strict authoring changes, structured source diagnostics, and artifact-safe config provenance/fingerprint ordering. This phase is the bridge from config artifacts to runtime persistence: it must stop default resolved-config replay artifacts for composed configs, persist the full composition manifest as plain data through run-store APIs, and clarify how output-affecting runtime objects participate in stage fingerprints without entering `loom.config` fingerprints.

Phase 6 still owns recipe residual-risk coverage. Phase 7 still owns final docs/evidence sweeps. Those later cleanup tasks must remain out of this PR.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: the manager selected `develop`; Phases 1-4 and their metadata are merged, and the control checkout is clean at `aa9287a`.
- Retarget/rebase plan after predecessor merge: none needed because there is no predecessor.
- Branch cleanup constraints: this branch may be deleted after merge only if no successor branch has been created from it.

## Source Phase Summary

- Goal: align pipeline/run-store persistence with v1 artifact-safe config boundaries without making `loom.pipeline` depend on `loom.config`.
- Required scope: stop `PipelineRunner` from writing full resolved config snapshots by default for composed configs; persist artifact-safe config provenance/manifest records and the full composition manifest through plain-data run-store APIs; add `read_composition_manifest(run_id)` and `write_composition_manifest(run_id, manifest)`; add local-store `config/composition_manifest.json` wrapper; keep plain mapping config snapshot behavior conservative; keep pipeline usable without importing `loom.config`; define explicit runtime object fingerprinting outside `loom.config`; prove explicit runtime fingerprint inputs can change stage fingerprints while config fingerprints remain runtime-free.
- Required checkpoints: no default `config/resolved.yaml` or `config/resolved.redacted.yaml` for composed config runs; composition manifest persists under `config/composition_manifest.json`; store and pipeline code handle the manifest as plain data; runtime object fingerprints appear only when a caller explicitly supplies them through stage or fingerprint context inputs.

## Current Source And Harness Findings

- `src/loom/pipeline/execution/runner.py` currently uses `_is_composed_config(...)` duck typing for `resolved`, `redacted`, `provenance`, and `recipe_manifest`, and `_write_config_and_provenance(...)` writes `write_config_snapshot(run_id, "resolved", json_dumps_pretty(request.config.resolved))` plus `write_config_snapshot(run_id, "resolved_redacted", json_dumps_pretty(request.config.redacted))` for composed configs. Phase 5 must remove those composed-config default writes.
- `src/loom/pipeline/execution/runner.py` may continue using `request.config.resolved` in `_resolve_config_and_spec(...)` as the in-memory source for `parse_pipeline_config(...)`; the boundary to change is persistence, not runtime config parsing.
- `src/loom/pipeline/execution/models.py` has `_ComposedConfigLike` with `resolved`, `redacted`, `provenance`, and `recipe_manifest`; it does not expose the Phase 4 `manifest` plain-data boundary yet. `src/loom/config/api.py` exposes `ComposedConfig.manifest`, and `src/loom/config/artifacts.py` exposes `CompositionManifest.to_dict()`.
- `src/loom/pipeline/stores/run_store.py` defines `RunConfigStore` with `read_config_snapshot`, `write_config_snapshot`, `read_recipe_manifest`, and `write_recipe_manifest`, but no composition manifest protocol methods.
- `src/loom/pipeline/stores/local_runs.py` already wraps `recipe_manifest.json` and other run documents with exact schema/run/timestamp fields. The new composition manifest wrapper should follow that local-store pattern and validate exact wrapper fields.
- `src/loom/pipeline/stores/_paths.py` restricts snapshot names to `raw`, `overlays`, `cli_overrides`, `resolved`, and `resolved_redacted`; changes must not accidentally keep describing composed-config artifacts as resolved replay.
- `src/loom/pipeline/planning/fingerprints.py` already includes `StageSpec.fingerprint_fields` and `FingerprintContext.extra` in the stage fingerprint payload. `loom.protocols.Fingerprintable` provides an explicit object contract outside `loom.config`.
- Existing tests to extend include `tests/contracts/test_store_contract.py`, `tests/package/test_pipeline_store_api.py`, `tests/package/test_import_boundaries.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/unit/loom/pipeline/execution/test_runner.py`, `tests/unit/loom/pipeline/execution/test_execution_models.py`, `tests/unit/loom/pipeline/planning/test_planning_fingerprints.py`, `tests/integration/pipeline/test_local_stores.py`, `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_planning_resume.py`, and `tests/e2e/test_local_pipeline_run.py`.

## In-Scope Work

- Extend the run-store protocol with:
  - `read_composition_manifest(run_id) -> dict[str, PlainData] | None`
  - `write_composition_manifest(run_id, manifest: Mapping[str, PlainData]) -> None`
- Implement local-store persistence at `config/composition_manifest.json` with exactly these wrapper fields for schema version 1: `schema_version`, `run_id`, `created_at`, and `composition_manifest`.
- Validate the wrapper using the existing local-store document validation style: exact fields, schema version, matching run id, timestamp, and plain mapping manifest payload. Return a thawed dict copy, not a config artifact object.
- Update `PipelineRunner` composed-config handling so default runs persist `config/composition_manifest.json`, existing `config/recipe_manifest.json`, and plain `config_provenance` run metadata, without writing full resolved config snapshots. The runner may continue to use `resolved` in memory to parse/build the `PipelineSpec`; the persistence boundary must not write that resolved mapping by default.
- Pin the redacted/artifact-safe config persistence choice for this phase: do not add a new full redacted config file, do not add new config snapshot names such as `redacted`, `artifact_safe`, or `unresolved`, and do not use `resolved_redacted` as a composed-config default. The artifact-safe persisted config facts for composed configs are the plain `ComposedConfig.manifest.to_dict()` payload, existing `recipe_manifest` records, and `ComposedConfig.provenance.to_dict()` in run user metadata.
- Keep composed-config handling duck-typed/plain-data: `loom.pipeline` may look for plain attributes such as `resolved`, `redacted`, `manifest`, `provenance`, and `recipe_manifest`, and may call `to_dict()` on `manifest` or `provenance` when present, but it must not import `loom.config` or config manifest/provenance classes.
- Keep `loom.config` persistence-free. Do not add run-store imports, persistence helpers, CLI helpers, or pipeline-specific APIs to `loom.config`.
- Preserve conservative plain mapping behavior. If a caller passes a plain mapping config, current snapshot behavior may remain because it is caller-provided runtime data, but tests/docs must not label that path as v1 resolved-config replay or composition replay.
- Preserve explicit user-provided snapshot behavior through `ConfigSnapshotInputs`; it currently exposes only `raw`, `overlays`, and `cli_overrides`, and those remain explicit/user-provided legacy snapshots. Do not add `resolved` or `resolved_redacted` to `ConfigSnapshotInputs` in this phase.
- Define runtime object fingerprint policy outside `loom.config`: output-affecting runtime objects must be represented explicitly through `StageSpec.fingerprint_fields`, `FingerprintContext.extra`, or a caller-supplied `Fingerprintable.fingerprint()` value converted to plain data before fingerprint construction.
- Add tests proving that changing an injected/output-affecting runtime object fingerprint changes the stage fingerprint when explicitly accounted for, and that config artifact fingerprints remain unchanged because runtime object identity never enters `loom.config`.

## Out-of-Scope Work

- Automatic arbitrary runtime object fingerprinting or reflection.
- Remote stores, bundle formats, catalogs, or migration machinery.
- CLI inspection commands or any v2 CLI surface.
- Resolved-runtime replay guarantees.
- Persisting resolver outputs or raw source bytes by default.
- `_copy_` support.
- Broadening resolver support.
- Future Phase 6 recipe residual-risk coverage.
- Requiring `loom.pipeline` to import `loom.config`, `CompositionManifest`, or other config classes.

## Accepted Decisions To Preserve

- `loom.config` remains persistence-free.
- `loom.pipeline` must not depend on `loom.config` or config manifest classes.
- `_copy_` remains unsupported in v1.
- Default artifacts are security-first and artifact-safe.
- Resolver outputs and raw source bytes are not persisted by default.
- V1 is Python-API-only; no CLI commands are added.
- Plain mapping configs are caller-provided data, not v1 composed-config artifacts.

## Assumptions

- `ComposedConfig.manifest.to_dict()` is the intended plain serialized composition manifest payload; runner/store code should treat the returned mapping as opaque plain data.
- `ComposedConfig.redacted` is artifact-safe after Phase 4 and remains available for in-memory use, but Phase 5 does not persist it as a default full config snapshot because no accepted non-`resolved_redacted` path/name exists in the v1-post plan. If implementation appears to require a new full redacted config artifact path, stop for the manager instead of inventing one.
- It is acceptable for run user metadata to continue storing config provenance as plain data if it remains artifact-safe and does not force a config import.
- Store protocol changes are local and public enough to require contract/package coverage, but no remote store compatibility layer exists in v1.
- Runtime object fingerprints should be digest strings or other plain-data facts supplied by callers; the runner should not inspect arbitrary injected object internals.

## Scope Contract

For composed config inputs, `PipelineRunner` must use resolved config only as in-memory input to build or validate the runtime `PipelineSpec`. Default persistence must not write `config/resolved.yaml` or `config/resolved.redacted.yaml` from composed config inputs, and must not write equivalent full resolved/redacted mappings by another route. Default composed-config persistence in this phase is exactly:

- `LocalRunStore.write_composition_manifest(run_id, manifest_payload)` to `config/composition_manifest.json`, where `manifest_payload` is a plain mapping from `request.config.manifest.to_dict()` or an already-plain mapping supplied by a duck-typed test double.
- Existing `LocalRunStore.write_recipe_manifest(run_id, request.config.recipe_manifest)` to `config/recipe_manifest.json`.
- Existing `LocalRunStore.write_run_user_metadata(...)` with `config_provenance` from `request.config.provenance.to_dict()` merged with caller metadata, after plain-data normalization.
- Explicit `ConfigSnapshotInputs.raw`, `ConfigSnapshotInputs.overlays`, and `ConfigSnapshotInputs.cli_overrides` writes only when the caller supplied those strings.

No new default full redacted config artifact path is introduced in this phase. The executor must not add new entries to `VALID_CONFIG_SNAPSHOTS` for composed-config defaults or for the composition manifest; use direct `config/composition_manifest.json` path handling in `LocalRunStore`.

The run-store composition manifest document contract is:

```text
{
  "schema_version": 1,
  "run_id": "<run id>",
  "created_at": "<UTC timestamp>",
  "composition_manifest": { ... plain serialized composition manifest ... }
}
```

The `composition_manifest` field is opaque plain data to store and pipeline code. Only `loom.config` owns manifest object validation and schema semantics. Store validation should reject malformed wrappers and non-mapping manifest payloads, but it must not import or reconstruct config classes.

Stage runtime fingerprints are pipeline planning facts, not config facts. The accepted mechanisms are existing explicit inputs: `StageSpec.fingerprint_fields`, `FingerprintContext.extra`, and caller use of `Fingerprintable.fingerprint()` to produce plain data. `loom.config` fingerprints must remain artifact-safe and runtime-free; changing a runtime object fingerprint should not change `ComposedConfig.fingerprint` unless the authored config itself changes.

## Design Impact

- Maintainability: moves run persistence toward explicit store documents instead of overloading resolved-config snapshots with multiple meanings.
- Extensibility: the plain-data composition manifest API can later be implemented by remote stores or bundles without binding store implementations to config classes.
- Security: default persistence no longer writes full runtime-resolved composed config snapshots, reducing accidental resolver output or secret leakage.
- Source-tree boundaries: keeps `loom.config` artifact construction separate from `loom.pipeline` persistence and keeps runtime object fingerprinting in pipeline planning.
- Public contract impact: `RunConfigStore` gains two protocol methods; local-store wrappers and contract tests define the schema-versioned persistence shape.

## Future Compatibility

- Future remote stores can implement the same `read_composition_manifest` and `write_composition_manifest` methods as plain-data operations.
- Future bundle/catalog work can consume `config/composition_manifest.json` without needing resolved-runtime replay guarantees.
- Future explicit runtime fingerprint policies can build on `FingerprintContext.extra` or named stage fingerprint fields without changing config fingerprint semantics.
- If a future CLI is added, it should inspect these plain-data run-store records rather than resurrecting default resolved snapshots.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep writing `resolved.yaml` or `resolved.redacted.yaml` for composed configs and document it as unsafe | Conflicts with the accepted artifact-safe default and continues to imply resolved-runtime replay by default. |
| Invent a new full redacted config snapshot path in Phase 5 | The v1-post plan only selects the composition manifest store API/path; adding a new redacted config file name would be a public persistence contract decision outside this phase. |
| Import `CompositionManifest` in the pipeline/store layer to validate manifests | Violates the source boundary; the store only needs a plain-data wrapper contract. |
| Store only config provenance and omit the full composition manifest | D32 explicitly requires full composition manifest persistence through the run store. |
| Automatically fingerprint arbitrary runtime objects passed to stages | Unsafe and under-specified; callers must explicitly decide which runtime object facts affect outputs. |
| Put runtime object fingerprints into `loom.config` fingerprints | Violates the runtime-free config fingerprint contract from Phase 4. |
| Add CLI inspection commands for the new manifest | V1-post remains Python-API-only; CLI work is deferred. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Plain mapping configs may still write conservative config snapshots with legacy names. | They are caller-provided runtime mappings, not composed config artifacts, and preserving behavior avoids a broader compatibility break. | A v2 persistence model defines neutral names or explicit snapshot policies for all config inputs. |
| Runtime object fingerprint policy remains explicit and caller-managed. | Automatic object identity/content fingerprinting is unsafe without a broader injection/runtime policy. | Users need first-class runtime injection APIs with declared fingerprint contracts. |
| Local store is the only implemented backend for the new manifest API. | Remote stores are out of scope for v1-post Phase 5. | A remote store or bundle backend is added. |

## Reviewability

- Expected PR size and shape: moderate pipeline/store PR with protocol additions, local-store wrapper read/write, runner persistence changes, focused tests, and small docs/test wording for runtime fingerprint policy.
- Files and areas to inspect: `src/loom/pipeline/stores/run_store.py`, `src/loom/pipeline/stores/local_runs.py`, `src/loom/pipeline/execution/models.py`, `src/loom/pipeline/execution/runner.py`, `src/loom/pipeline/planning/fingerprints.py` only if explicit policy helpers are needed, `src/loom/pipeline/planning/models.py` if fingerprint serialization tests need fixtures, and package exports if store protocols change. `src/loom/pipeline/stores/_paths.py` should not need new snapshot names for composed-config persistence.
- Test areas to inspect: `tests/contracts/test_store_contract.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/unit/loom/pipeline/execution/test_runner.py`, `tests/unit/loom/pipeline/execution/test_execution_models.py`, `tests/unit/loom/pipeline/planning/`, `tests/integration/pipeline/`, `tests/e2e/test_local_pipeline_run.py`, and config-extra tests that combine composed config with runner persistence.
- Scope-control checks: no config imports from pipeline/store modules, no changes under `src/loom/config` except tests proving runtime-free fingerprints if absolutely necessary, no new config snapshot names for composed-config defaults, no CLI, no `_copy_`, no remote-store/bundle/catalog work, no resolver expansion, no automatic runtime-object fingerprinting.

## Implementation Steps

1. Add the plain-data composition manifest methods to `RunConfigStore` and any dummy stores or test fixtures that structurally implement the protocol.
2. Implement `LocalRunStore.read_composition_manifest` and `write_composition_manifest` with the schema-version-1 wrapper at `config/composition_manifest.json`, following existing wrapper validation and atomic-write patterns rather than routing through `write_config_snapshot`.
3. Extend the composed-config duck type in execution models and `_is_composed_config(...)` in `runner.py` to include `manifest` access without importing config classes; normalize manifest payloads by calling `to_dict()` when present or accepting a mapping when supplied by a test double.
4. Update `PipelineRunner._write_config_and_provenance(...)` so composed configs write the composition manifest, existing recipe manifest, and config provenance metadata, and stop writing `write_config_snapshot(..., "resolved", ...)` or `write_config_snapshot(..., "resolved_redacted", ...)` for composed configs.
5. Preserve plain mapping config behavior as caller-provided snapshot behavior and ensure tests make that distinction explicit.
6. Add explicit runtime fingerprint tests using `StageSpec.fingerprint_fields`, `FingerprintContext.extra`, and/or a `Fingerprintable` object whose `fingerprint()` result is converted to plain data by the caller before constructing the `StageSpec` or `FingerprintContext`. Prove stage fingerprints change only when the explicit runtime fingerprint input changes, while config fingerprints remain stable.
7. Add import-boundary and package/contract coverage for the new protocol surface, then run targeted validation before PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_store_api.py`, `tests/package/test_pipeline_planning_api.py`, and `tests/package/test_import_boundaries.py` or another focused import-boundary package test.
- Required assertions or deferral reason: public store protocol exports remain importable; `RunConfigStore` includes the new methods; pipeline/store imports do not import `loom.config`; stage fingerprint public APIs remain available. If no existing import-boundary package test fits, add a focused package test rather than broadening unrelated package checks.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/unit/loom/pipeline/execution/test_execution_models.py`, `tests/unit/loom/pipeline/execution/test_runner.py`, and `tests/unit/loom/pipeline/planning/test_planning_fingerprints.py`.
- Required assertions or deferral reason: local store writes and reads `config/composition_manifest.json` wrapper with exact fields; wrapper rejects wrong run id, schema version, missing fields, unknown fields, and non-mapping manifest payload; composed-config duck typing accepts plain manifest payloads without config class imports; runner does not call `write_config_snapshot(..., "resolved", ...)` or `write_config_snapshot(..., "resolved_redacted", ...)` for composed configs; runner does call `write_composition_manifest(...)` with the plain `manifest.to_dict()` payload; `ConfigSnapshotInputs` remains explicit/user-provided for `raw`, `overlays`, and `cli_overrides` only; explicit `fingerprint_fields` or `FingerprintContext.extra` changes alter stage fingerprints.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_store_contract.py`.
- Required assertions or deferral reason: `RunConfigStore` structural dummy implements `read_composition_manifest` and `write_composition_manifest`; the methods accept/return plain mappings; no config classes are needed. Add local-store contract checks if that file already houses wrapper-shape expectations.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/pipeline/test_local_stores.py`, `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_planning_resume.py`, and config-marked integration coverage where a real `ComposedConfig` is passed to `PipelineRunner`.
- Required assertions or deferral reason: a public Python composed-config run persists `config/composition_manifest.json`, existing `config/recipe_manifest.json`, and config provenance metadata, does not persist default resolved snapshots or invent a new full redacted snapshot, still builds/executes the pipeline from in-memory resolved config, and plain mapping config runs retain conservative caller-provided snapshot behavior. Runtime fingerprint integration should prove resume/planning sees a changed stage fingerprint only when the explicit runtime fingerprint input changes.

### E2E Suite

- Status: required if practical; otherwise explicitly justified in the PR body.
- Expected paths: `tests/e2e/test_local_pipeline_run.py` or a focused public Python e2e.
- Required assertions or deferral reason: local public Python runner workflow using composed config writes the composition manifest and omits default `config/resolved.yaml` and `config/resolved.redacted.yaml`. If existing e2e fixtures make composed-config setup too large, integration coverage may satisfy behavior, but the deferral must explain why.

### Opt-In Suites

- Status: required for config-extra rows because real composed config inputs require optional config dependencies.
- Markers affected: config optional dependency markers plus pipeline integration rows touched by composed-config runner coverage.
- Required assertions or deferral reason: config-extra evidence must include a composed-config runner persistence case proving config fingerprints stay runtime-free and no resolver outputs/raw source bytes are persisted by default. Runtime fingerprint tests should not require config extras unless they deliberately combine compose output with pipeline planning.

## Risks

- Runner code can accidentally keep writing resolved snapshots through legacy snapshot names while also adding the manifest. Tests must assert missing files/calls, not just presence of the new file.
- Runner code can accidentally introduce a new redacted snapshot path to replace `resolved_redacted`; this is out of scope unless the implementation plan is reopened.
- Adding `manifest` to composed-config duck typing can drift into a config import if implementation reaches for concrete classes. Import-boundary tests must catch this.
- Local-store wrapper validation could be too permissive and silently accept malformed manifest documents; exact-field tests are required.
- Plain mapping behavior can be misrepresented as v1 resolved replay. Tests and docs should call it caller-provided data only.
- Runtime fingerprint tests can accidentally test config changes rather than runtime object facts. The fixtures must keep authored config identical while changing only the explicit runtime fingerprint input.
- Adding automatic `Fingerprintable` discovery inside the runner or planner would exceed scope. Callers may use `Fingerprintable.fingerprint()` before passing plain data, but Loom should not inspect arbitrary runtime objects in this phase.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/contracts/test_store_contract.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/pipeline/execution/test_execution_models.py tests/unit/loom/pipeline/execution/test_runner.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/pipeline/planning/test_planning_fingerprints.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/integration/pipeline/test_local_stores.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_planning_resume.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest -m optional_dependency tests/integration/config tests/e2e/test_local_pipeline_run.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: store protocol and dummy fixtures first; local-store wrapper second; composed-config duck type and runner persistence third; runtime fingerprint policy tests fourth; integration/e2e coverage last.
- Tests to run with each slice: run store contract/local-store unit tests after API and wrapper changes; runner unit tests after persistence changes; planning fingerprint tests after explicit runtime fingerprint coverage; integration/e2e composed-config runner tests before handoff.
- Decisions the executor must not revisit: no `loom.config` persistence helpers, no pipeline import of config classes, no default `resolved` or `resolved_redacted` snapshot for composed configs, no invented replacement redacted snapshot path, no automatic runtime object fingerprinting, no resolver output/raw source default persistence, no CLI, no `_copy_`, no remote stores, and no Phase 6 recipe residual-risk work.
- Conditions that require stopping for the manager: satisfying manifest persistence appears to require importing `loom.config` in pipeline/store code; tests can pass only by continuing to write composed-config `resolved.yaml` or `resolved.redacted.yaml`; satisfying artifact-safe/redacted persistence appears to require a new full config artifact path; local store needs a migration for existing run directories; runtime object fingerprints require a new injection API or arbitrary object introspection; or any implementation needs CLI/remote-store/bundle behavior.
- Expanded-path refinement notes: complete. The refined boundary pins composed-config default persistence to composition manifest, recipe manifest, and provenance metadata; redacted full-config snapshot persistence is not added in Phase 5.

## Refinement And Review Budget Status

- Phase implementation refinement: used; expanded-path implementation/test refinement pass completed after executor work.
- PR review: unused.

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed with `plan: add phase execution plan` at `9122e75`.
- Final phase execution plan: completed by expanded-path refinement.
- Implementation summary: completed by workflow-authorized fallback executor. Added plain-data `RunConfigStore.read_composition_manifest(...)` and `write_composition_manifest(...)`; implemented strict local `config/composition_manifest.json` wrapper persistence; updated composed-config duck typing and `PipelineRunner` persistence to write composition manifest, recipe manifest, and config provenance metadata without default composed-config `resolved.yaml` or `resolved.redacted.yaml`; preserved plain mapping snapshot behavior as caller-provided config data; added explicit runtime fingerprint coverage through `StageSpec.fingerprint_fields`, `FingerprintContext.extra`, and caller-converted `Fingerprintable.fingerprint()` values while keeping config fingerprints runtime-free.
- Implementation commits:
  - `9bb8dfb` `feat: persist composition manifests`
  - `e992932` `test: cover pipeline manifest persistence`
- Scope control: no `loom.config` persistence helpers were added; no pipeline/store imports of `loom.config`, `CompositionManifest`, `ConfigProvenance`, or config classes were introduced; no new config snapshot names or full redacted config artifact paths were added; CLI, `_copy_`, remote stores, bundles, catalogs, resolver support, runtime replay guarantees, automatic runtime object fingerprinting, and Phase 6 recipe residual-risk scope were not touched.
- Tests added or updated:
  - Package: `tests/package/test_pipeline_store_api.py`, `tests/package/test_import_boundaries.py`
  - Unit: `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/unit/loom/pipeline/execution/test_execution_models.py`, `tests/unit/loom/pipeline/execution/test_runner.py`, `tests/unit/loom/pipeline/planning/test_planning_fingerprints.py`
  - Contract: `tests/contracts/test_store_contract.py`
  - Integration: `tests/integration/pipeline/test_local_stores.py`, `tests/integration/pipeline/test_local_execution.py`, `tests/integration/config/test_compose_fingerprints.py`
  - E2E: `tests/e2e/test_local_pipeline_run.py`
  - Opt-in/config-extra: composed-config runner persistence and runtime-free config fingerprint coverage in config-extra rows.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/contracts/test_store_contract.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py`: passed, 25 passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py`: passed, 20 passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/pipeline/execution/test_execution_models.py tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/planning/test_planning_fingerprints.py`: passed, 22 passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/integration/pipeline/test_local_stores.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_planning_resume.py`: passed, 9 passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest -m optional_dependency tests/integration/config/test_compose_fingerprints.py tests/e2e/test_local_pipeline_run.py`: passed, 5 selected config fingerprint tests passed; e2e file was deselected by marker expression.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/e2e/test_local_pipeline_run.py`: passed, 6 passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run ruff check <touched files>`: passed.
  - `make validate-pr`: passed with Ruff, Pyright, default harness `447 passed, 11 skipped`, config-extra harness `362 passed, 454 deselected`, and `uv build`.
  - `make test-summary`: passed; suite summary written to `build/test-summary.md` with package `38 passed, 1 skipped`, unit `364 passed, 1 skipped`, contract `36 passed, 2 skipped`, integration `9 passed, 5 skipped`, e2e `7 passed`, and config-extra `362 passed, 454 deselected`.
- Known issues or blockers: none.
- Phase implementation refinement: used. The refinement pass confirmed the Phase 5 store/pipeline/import-boundary/runtime-fingerprint scope controls, tightened local-store unit coverage so `config/composition_manifest.json` read validation rejects each missing exact wrapper field and boolean schema versions, and reran focused validation for the touched store tests.
- Refinement validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py`: passed, 20 passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run ruff check tests/unit/loom/pipeline/stores/test_local_runs.py docs/phases/v1-post-pipeline-persistence.md`: passed.
- PR preparation: in progress by `loom_pr_preparer`.
- PR body artifact: `docs/phases/v1-post-pipeline-persistence-pr-body.md`.
- PR body draft/refine status: completed in this PR-preparation pass for the expanded path; body checked against the phase execution plan, final diff, validation evidence, and `.github/PULL_REQUEST_TEMPLATE.md`.
- PR preparation scope inspection:
  - Branch/worktree confirmed: `codex/v1-post-pipeline-persistence` in `/home/samcantrill/work/loom-worktrees/v1-post-pipeline-persistence`.
  - Target branch confirmed from phase metadata: `develop`; stack predecessor: none; merge eligibility: root phase PR is merge-eligible after review and checks.
  - Final diff is limited to the Phase 5 phase artifact, run-store protocol/local-store composition manifest persistence, runner composed-config persistence, package/contract/unit/integration/e2e/config-extra tests, and the PR body artifact.
  - `rg` inspection found no `loom.config` imports, `CompositionManifest`, `ConfigProvenance`, or concrete config-class imports in `src/loom/pipeline` or `src/loom/pipeline/stores`.
  - Composed-config persistence no longer writes default `resolved` or `resolved_redacted` snapshots; the only remaining `resolved_redacted` write in `PipelineRunner` is the pre-existing plain-mapping config path for caller-provided runtime mappings.
  - No new config snapshot names or full redacted config artifact paths were added; `src/loom/pipeline/stores/_paths.py` remains unchanged for snapshot names.
  - No Phase 6/CLI/`_copy_`/remote-store/runtime-replay/automatic runtime-object fingerprinting scope was added.
- PR preparation validation:
  - `git diff --check develop...HEAD`: passed.
  - `make validate-pr`: passed with Ruff, Pyright, default harness `447 passed, 11 skipped`, config-extra harness `362 passed, 454 deselected`, and `uv build`.
  - `make test-summary`: passed; suite summary written to `build/test-summary.md` with package `38 passed, 1 skipped`, unit `364 passed, 1 skipped`, contract `36 passed, 2 skipped`, integration `9 passed, 5 skipped`, e2e `7 passed`, config-extra `362 passed, 454 deselected`, and overall `816 passed, 9 skipped, 454 deselected`.
- PR facts:
  - Title: `V1 Post Configuration - Phase 5: Pipeline Persistence And Runtime Fingerprints`
  - Base: `develop`
  - Head: `codex/v1-post-pipeline-persistence`
  - URL: pending GitHub PR creation.
  - Verification: pending `gh pr view <PR> --json baseRefName,headRefName,state,url`.
- PR blockers: none at local validation/body preparation stage.
