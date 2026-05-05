# Phase 12 Execution Plan: Public Compose Orchestration And Inspection APIs

## Metadata

- Status: refined phase execution plan; ready for implementation
- Feature focus: Configuration
- PR title: `Configuration - Phase 12: Public Compose Orchestration And Inspection APIs`
- Branch: `codex/config-compose-orchestration`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-compose-orchestration`
- Phase execution plan path: `docs/phases/config-compose-orchestration.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 12 - Public Compose Orchestration And Inspection APIs
- Stack predecessor: none; Phases 1-11 are merged.
- Base branch: `develop`
- Base commit: `c75504bfa6b0026e9334316488979520500031f2`
- Target branch: `develop`
- Merge eligibility: root phase; eligible to merge into `develop` only after implementation, phase-scoped validation, pre-submit blocker gate, PR preparation/submission, and passing review/CI against `develop`.
- Workflow path: expanded path
- Workflow path rationale: public API/data-shape changes and the complete composition order affect compatibility, inspection contracts, and later artifact population phases.
- Successor dependency notes: Phase 13 may populate provenance, manifest, source records, and redaction using the public field/stage shape introduced here. Phase 14 may populate artifact-safe fingerprints from those records. Phase 15 may add raw source snapshot opt-in. Phase 16 may broaden docs/e2e coverage.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact; draft budget used.
- Refine pass: completed by `loom_phase_planner`; refine budget used.
- Phase implementation refinement budget: used by expanded-path implementation refinement on 2026-05-06.
- Pre-submit blocker gate budget: unused. `loom_pr_preparer` must run one blocker gate before opening or preparing the PR, covering the implementation diff, PR body draft, suite evidence, scope boundary, import boundary, inspection public contract, artifact placeholder semantics, and known review risks. Known blockers must be fixed or the phase marked blocked before any PR is opened.
- PR review budget: unused. Do not consume the PR review budget during implementation; a later manager-assigned review may consume it after PR preparation.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid; approved outside-sandbox `gh auth status` succeeded. Sandboxed `gh auth setup-git` failed because `/home/samcantrill/.gitconfig` was read-only; approved `gh auth setup-git` succeeded. Sandboxed `git fetch origin` failed when writing `.git/FETCH_HEAD`; approved `git fetch origin` succeeded. Local `develop` and `origin/develop` both resolved to the assigned base commit. Initial sandboxed `git worktree add` could not create the branch ref; approved `git worktree add` created the branch and worktree successfully.
- Blockers: none known after refinement.

## Objective

Wire the public v1 composition entrypoints over the already-implemented staging helpers so `compose_config(...)` follows the current accepted full order, `inspect_config_composition(...)` exposes stable additive stage records for that same path, and `ComposedConfig` gains the v1 artifact fields without breaking existing callers or coupling pipeline code to config artifacts.

## Full-Plan Context

Phases 1-11 established config/pipeline boundaries, artifact skeletons, strict loading, merge/override behavior, source overlays, recursive includes, user include overrides, resolver security, recipe expansion, scoped validation, and runtime instantiation. Phase 12 is the public orchestration and inspection layer over those behaviors. It must preserve accepted v1 decisions: `loom.config` is persistence-free; `loom.pipeline` must not depend on `loom.config` or manifests; `_copy_` remains unsupported; default artifacts are security-first and artifact-safe; resolver outputs and raw source bytes are not persisted by default; v1 is Python-API-only with no CLI; and there are no plugin, remote, or global-search include resolvers.

Future phases remain out of scope: Phase 13 finalizes provenance/manifest/source-record/redaction population, Phase 14 computes artifact-safe fingerprints and resume comparison, Phase 15 adds raw source snapshot opt-in and source hardening, and Phase 16 handles documentation and broader e2e hardening.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-11 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`, Phase 11 merge metadata is recorded, and local/fetched `develop` matches the assigned base commit.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after the Phase 12 PR is merged and no successor branch depends on `codex/config-compose-orchestration`.

## Source Phase Summary

- Goal: wire the complete public `compose_config` order using prior phases.
- Required scope: full staged order; simple public `compose_config`; public `inspect_config_composition`; additive v1 `ComposedConfig` fields `unresolved`, `manifest`, `source_artifacts`, and `fingerprint_records`; compatibility for `resolved`, `redacted`, `provenance`, `recipe_manifest`, and `fingerprint`; config/pipeline independence; persistence-free config artifact return shape.
- Required checkpoints: orchestration collaborator tests, `ComposedConfig` compatibility tests, inspection API shape tests, full-order integration through recipes/runtime resolution, package/API tests, and import-boundary tests.
- Acceptance criteria: full order works through includes, user composition overrides, recipes, ordinary value overrides, validation, runtime interpolation, and optional explicit instantiation; inspection exposes stable additive stage records without unstable internals; compatibility tests prove old fields still work and new v1 fields are present; pipeline remains independent.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/api.py` is still v0-shaped and owns `ComposedConfig` with only `resolved`, `redacted`, `provenance`, `recipe_manifest`, and `fingerprint`; it has no `inspect_config_composition(...)` or inspection type yet. `src/loom/config/__init__.py` lazy-exports the public config surface. `src/loom/config/compose.py` currently owns the full orchestration and its order is: load base and overlays, source-aware merge, file include expansion, user include overrides/recomposition, recipe-argument interpolation, recipe expansion, ordinary overrides, resolver scan, runtime interpolation, validation, redaction, provenance, and fingerprint. Existing stage building blocks include include/recomposition records in `includes.py`, resolver expression records in `interpolation.py`, recipe manifest records in `recipes/manifest.py`, provenance/source/fingerprint skeleton contracts in `provenance.py` and `artifacts.py`, and source maps in `source_maps.py`.
- Existing tests or harness behavior: `tests/unit/loom/config/test_compose.py` and `tests/integration/config/test_compose_config.py` cover the current public compose path and compatibility fields. `tests/integration/config/test_compose_includes.py`, `test_compose_overrides.py`, `test_compose_recipes.py`, and `test_compose_resolvers.py` cover individual composition interactions. `tests/contracts/test_config_artifact_contract.py` covers artifact model round trips. `tests/package/test_config_api.py` checks public exports/signatures, and `tests/package/test_import_boundaries.py` checks config/pipeline import independence. Current gaps are no public API test for `inspect_config_composition(...)`, no inspection-shape contract tests, no additive `ComposedConfig` compatibility tests, no comparison test that inspection final stage records match public `compose_config(...)`, and no import-boundary test for the new inspection surface.
- Import-boundary or dependency constraints: keep implementation inside `loom.config` and tests. Do not import `loom.pipeline`, stores, CLI modules, plugin discovery, project code, or add runtime dependencies. `src/loom/pipeline/execution/models.py` type-check imports `ComposedConfig`, but no runtime `loom.config` imports were found in pipeline; keep any new inspection type out of pipeline runtime imports and out of pipeline annotations unless the manager explicitly assigns a pipeline boundary phase.

## In-Scope Work

- Refactor or wrap `src/loom/config/compose.py` so the public orchestration has named, inspectable stages matching the accepted v1 order without duplicating composition logic.
- Add public `inspect_config_composition(...)` through `loom.config.api` and package lazy exports. It accepts the same composition inputs as `compose_config(...)` and returns a public inspection object.
- Define public inspection data classes with stable additive field names and plain-data-compatible stage records. Keep stage identifiers stable; keep internal helper object identities, private class names, and filesystem implementation details out of the public contract except where already represented as artifact-safe/source-aware records.
- Extend `ComposedConfig` additively with `unresolved`, `manifest`, `source_artifacts`, and `fingerprint_records`, while preserving existing field names and compatibility behavior for current callers.
- Populate Phase 12 placeholders only where later phases own final data: `manifest` should be a valid `CompositionManifest` carrying the current recipe manifest and empty source/fingerprint records unless already available as artifact-safe skeletons; `source_artifacts` and `fingerprint_records` may be empty tuples until Phases 13-14 populate them.
- Make `unresolved` the expanded plain config after includes, user composition overrides, recipe expansion, ordinary value overrides, and resolver-expression scanning, before runtime resolver execution. Phase 12 must not reorder current runtime validation by inventing new pre-runtime validation semantics.
- Preserve `resolved` as the in-memory runtime-resolved config for Python callers and keep `redacted`, `provenance`, `recipe_manifest`, and `fingerprint` available under their existing names.
- Demonstrate optional instantiation compatibility by keeping `_target_` inert during composition and proving the final `resolved` value can be passed explicitly to the public `instantiate(...)` path where applicable. Do not put constructed runtime objects into artifact fields.
- Keep inspection records tied to the same stage outputs that build `compose_config(...)`; do not run a second divergent composition path for inspection.
- Keep config artifacts as returned Python data only; do not write run directories, stores, raw snapshots, manifests, or resolved configs.

## Out-of-Scope Work

- Final manifest population beyond a valid placeholder shape and current recipe-manifest handoff.
- Final provenance enrichment, source artifact metadata/hash population, redaction policy population, artifact-safe fingerprint population, or resume comparison.
- Raw source snapshot opt-in, raw source byte persistence, source byte serialization, or rebuild-from-missing-source behavior.
- Runtime object fingerprinting, constructed-object serialization, target registries, import allow-lists, project schema inference from `_target_`, or making instantiation default in `compose_config(...)`.
- Any implicit construction of `_target_` values during composition or inspection. Runtime object construction is explicit caller use of `instantiate(...)` after composition and is never part of `unresolved`, `manifest`, `source_artifacts`, `fingerprint_records`, stage artifact payloads, or persisted artifacts.
- Pipeline ownership changes, `loom.pipeline` imports from config, pipeline/store/runner/CLI behavior, run-store writes, or any config artifact persistence.
- CLI commands, docs alignment for older feature docs, plugin include resolvers, remote URI resolvers beyond existing local/file behavior, global include search paths, Hydra defaults lists, `_copy_`, or broader include/override/recipe semantics.

## Assumptions

- The existing staged helpers are the preferred implementation substrate; Phase 12 should expose and organize them rather than rewrite include, override, recipe, resolver, validation, or instantiation semantics.
- Public inspection is for debugging/tests and is not a persistence contract. The persistence contracts remain `CompositionManifest`, `SourceArtifactRecord`, `ConfigProvenance`, and `ConfigFingerprintRecord`.
- Current compatibility fields may retain their current population semantics until the assigned later phases replace them with final artifact-safe population. Phase 12 must avoid making those current semantics a new persistence guarantee.
- The package-level public API can grow additively, but existing positional `compose_config(config_path, overlays=(), overrides=(), recipe_catalog=None)` usage must keep working.
- Optional instantiation in Phase 12 means explicit caller-controlled use of `instantiate(...)` after runtime resolution, not default composition-time construction and not persistence of runtime objects.
- Phase 12 may define the inspection public type in `loom.config.api` or a config-local module re-exported by `loom.config.api`; whichever choice is made, pipeline runtime modules must not import it.

## Scope Contract

`compose_config(...)` remains the simple public composition entrypoint. It should delegate to the same staged path as `inspect_config_composition(...)`, return `ComposedConfig`, and keep existing fields source-compatible while adding `unresolved`, `manifest`, `source_artifacts`, and `fingerprint_records`. Existing callers that access `resolved`, `redacted`, `provenance`, `recipe_manifest`, or `fingerprint` must continue to pass.

`inspect_config_composition(...)` is public under `loom.config` and `loom.config.api`. It accepts the same composition inputs and validation rules as `compose_config(...)`: `config_path`, optional `overlays`, optional `overrides`, and optional `recipe_catalog`. It returns `ConfigCompositionInspection`, a plain-data-friendly object with stable additive stage records for at least these stage identifiers in this order: `source_load`, `overlay_merge`, `file_include_expansion`, `user_composition_overrides`, `recipe_argument_interpolation`, `recipe_expansion`, `ordinary_overrides`, `resolver_scan`, `runtime_interpolation`, `validation`, `redaction`, `provenance`, `fingerprint`, `artifact_placeholders`, and `composed_config`. The executor may split source loading into base/overlay subrecords inside `source_load`, but public stage names and their relative order must stay stable and additive.

Stage records should expose stable names, order, status, artifact-safe snapshots or summaries, and existing public record payloads where useful. Include records, recomposition records, resolver expression records, recipe manifest records, source-map summaries, provenance/source/fingerprint skeleton records, and placeholder manifest records are acceptable when represented as plain data or public dataclasses with plain-data conversion. Stage records must not expose private callables, mutable internal state, raw source bytes, constructed runtime objects, resolved resolver outputs as artifact facts, or unstable helper class names.

The full order must be observable and preserved: load base, load overlays in order, merge overlays with source authorship, expand file includes, apply user composition overrides, resolve recipe-argument interpolation, expand recipes, apply ordinary value overrides, scan resolver expressions without artifact-time execution, resolve runtime interpolation in memory for `resolved`, validate Loom-owned boundaries, redact, build provenance, compute the existing compatibility fingerprint, assemble Phase 12 placeholder artifact fields, and return `ComposedConfig`. `compose_config(...)` should be built from the inspection result or the exact same stage outputs, and tests must compare the public `compose_config(...)` fields with the final inspection/composed-result records.

`ComposedConfig.unresolved` is the artifact-safe expanded mapping after ordinary overrides and resolver-expression scanning, before runtime interpolation. `ComposedConfig.resolved` remains the in-memory runtime-resolved and validated config. `_target_` mappings remain inert during composition and inspection; optional instantiation means callers may explicitly pass composed values to `instantiate(...)` after composition. Constructed objects must not appear in `ComposedConfig` artifact fields, inspection artifact payloads, manifests, fingerprints, or source records.

Phase 12 placeholder artifact shape is precise but intentionally not final population: `manifest` must be a valid `CompositionManifest` with the current recipe manifest and empty or currently available skeleton `source_artifacts` and `fingerprint_records`; `source_artifacts` and `fingerprint_records` on `ComposedConfig` may be empty tuples; final manifest, source metadata/hash, redaction, and artifact-safe fingerprint population remains assigned to later phases.

## Design Impact

- Maintainability: one staged orchestration path should feed both public compose and inspection, reducing duplicate stage ordering and making later artifact population phases local to stage outputs.
- Extensibility: additive `ComposedConfig` fields and additive inspection records leave room for Phases 13-15 to populate artifacts without breaking the public shape.
- Domain neutrality: examples and tests should use project-owned generic mappings and synthetic targets/recipes, not model, dataset, experiment, or pipeline semantics.
- Source-tree boundaries: all production changes stay under `loom.config`; `loom.pipeline`, stores, CLI, plugin discovery, and project code remain independent.

## Future Compatibility

- Phase 13 can populate manifest/source/redaction/provenance from the staged inspection data without changing the public entrypoint names.
- Phase 14 can add artifact-safe fingerprint records and update `fingerprint` semantics without changing the `ComposedConfig` field list.
- Phase 15 can add explicit raw source snapshot opt-in without changing default Phase 12 behavior or persisting raw bytes by default.
- Future CLI commands can wrap `compose_config(...)` and `inspect_config_composition(...)` instead of reimplementing composition.
- Future sweeps can generate ordinary or composition overrides that flow through the same public staged path.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep inspection private and test only `compose_config(...)` output | The v1 plan explicitly names public `inspect_config_composition(...)` so later CLI/debug tooling has a stable Python API. |
| Make `ConfigCompositionInspection` a persistence artifact | The plan separates inspection/debug records from manifest/source/fingerprint persistence contracts. |
| Populate final manifest/source/fingerprint records in Phase 12 | Later phases own final artifact population; doing it here would expand scope and blur review boundaries. |
| Instantiate `_target_` objects by default during `compose_config(...)` | Phase 10 and Phase 11 keep `_target_` inert during composition; runtime construction remains explicit and must not enter artifact fields. |
| Use pipeline schemas or `PipelineSpec` to validate public composed configs | Generic config composition is domain-neutral and `loom.pipeline` must remain independent from `loom.config`. |
| Add CLI commands or run-store writes with the public API work | V1 is Python-API-only and `loom.config` is persistence-free. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Phase 12 may return empty `source_artifacts` and `fingerprint_records` placeholder tuples | Phase 13 and Phase 14 own final source/fingerprint population; this phase stabilizes the public field shape first. | Phase 13 or Phase 14 implementation begins and needs to populate the already-added fields. |
| `manifest` may be structurally valid but not fully populated | Keeps public data shape reviewable without pulling manifest/source/fingerprint semantics forward. | Phase 13 provenance/manifest population starts. |
| Existing `redacted`/`fingerprint` compatibility fields may retain current population semantics until later phases | Compatibility fields must keep working while artifact-safe population is phased in. | Phase 13 redaction/provenance or Phase 14 fingerprint phases update their semantics. |

## Reviewability

- Expected PR size and shape: focused public API/data-shape and orchestration-stage refactor under `loom.config`, plus package, contract, unit, integration, and limited public e2e tests. No pipeline, store, CLI, persistence, raw snapshot, or final artifact-population diff.
- Files and areas to inspect: `src/loom/config/api.py`, `src/loom/config/__init__.py`, `src/loom/config/compose.py`, any new config-local inspection/stage module if introduced, `src/loom/config/artifacts.py` only if placeholder construction or type imports require it, and existing stage collaborators only for small return-shape plumbing. Test areas: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py`, `tests/contracts/test_config_artifact_contract.py` or a new config inspection contract test, `tests/unit/loom/config/test_compose.py`, `tests/integration/config/test_compose_config.py`, `test_compose_includes.py`, `test_compose_overrides.py`, `test_compose_recipes.py`, `test_compose_resolvers.py`, and a limited public e2e test if the existing e2e harness can cover domain-neutral config composition without CLI or pipeline execution changes.
- Scope-control checks: no `loom.pipeline` imports from config; no manifest/source/fingerprint final population; no raw source bytes; no CLI/run-store writes; no default instantiation; no `_copy_`; no plugin/remote/global include resolution; no resolved resolver values in artifact placeholder fields.

## Implementation Steps

1. Introduce the public inspection data shape and export path, then add package/API tests for `inspect_config_composition`, `ConfigCompositionInspection`, and the additive `ComposedConfig` fields while preserving existing import behavior.
2. Refactor the existing `compose.py` flow into one staged orchestration path that records the current full order and can return inspection data and build `ComposedConfig`; keep stage helpers private unless the public contract requires otherwise.
3. Add `ComposedConfig.unresolved`, `manifest`, `source_artifacts`, and `fingerprint_records` construction with Phase 12 placeholder semantics and compatibility tests for the existing field names.
4. Add inspection contract tests for stable stage names/order and artifact-safe plain-data records, including absence of raw source bytes, private helper objects, resolved resolver values as artifact facts, and constructed runtime objects.
5. Add or extend integration coverage for the full order through file includes, user composition overrides, recipe-argument interpolation, recipe expansion, ordinary value overrides, resolver scan/runtime resolution, validation, and explicit post-compose `instantiate(...)` compatibility.
6. Run import-boundary/package checks, targeted config suites, then final PR-preparation validation after the pre-submit blocker gate has a PR body draft and suite evidence to review.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: `loom.config` and `loom.config.api` export `inspect_config_composition`, `ConfigCompositionInspection`, and the updated `ComposedConfig` without eager optional dependency or pipeline imports; existing `compose_config`, `compose_config_with_catalog`, `instantiate`, `Recipe`, and `RecipeCatalog` exports still work; public signatures remain source-compatible; `loom.pipeline` import still does not import `loom.config`; the new inspection type is not imported by pipeline runtime modules.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_compose.py` plus new focused unit tests if inspection/stage helpers live in a separate module.
- Required assertions or deferral reason: `compose_config(...)` delegates to the staged path; `ComposedConfig` exposes old and new fields with expected placeholder values; `unresolved` is before runtime interpolation while `resolved` is after runtime interpolation and validation; invalid public arguments still raise existing validation errors; inspection stage records have stable names/order and plain-data-compatible payloads; the inspection final/composed-result record matches the public `compose_config(...)` output for shared fields; optional instantiation remains explicit and `_target_` mappings stay inert in composed artifacts.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_config_artifact_contract.py` and either a new `tests/contracts/test_config_composition_inspection_contract.py` or equivalent focused contract coverage.
- Required assertions or deferral reason: `CompositionManifest` placeholder round-trips with current recipe manifest and empty source/fingerprint records; `ConfigCompositionInspection` and stage records expose additive, stable, plain-data-compatible fields and the required stage identifiers/order; contract tests reject unstable payloads such as private helper objects, raw bytes, constructed runtime objects, resolved resolver values as artifact facts, or non-plain metadata if serialization helpers are provided.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_config.py`, `tests/integration/config/test_compose_includes.py`, `tests/integration/config/test_compose_overrides.py`, `tests/integration/config/test_compose_recipes.py`, `tests/integration/config/test_compose_resolvers.py`, and `tests/integration/pipeline/test_pipeline_config.py` only as an existing boundary consumer if no pipeline production code changes are made.
- Required assertions or deferral reason: a full public flow covers base plus overlays, recursive includes, user include replacement, recipe-argument interpolation, recipe expansion, ordinary overrides targeting recipe/include-produced values, generic validation pass-through after runtime resolution, resolver scan/runtime resolution, artifact placeholder fields, inspection-vs-compose comparison, and explicit `instantiate(...)` after composition where applicable. Existing pipeline-config integration should continue proving pipeline-facing code consumes plain composed data without importing config into pipeline modules.

### E2E Suite

- Status: required but limited.
- Expected paths: a small domain-neutral public composition e2e test under `tests/e2e/` only if it can avoid CLI, runner, store, and pipeline execution behavior.
- Required assertions or deferral reason: use public `compose_config(...)` and `inspect_config_composition(...)` on a synthetic config tree and assert the returned unresolved/artifact-safe shape contains no `_include_`, `_replace_`, or `_copy_` markers, new fields are present, inspection stages are stable, inspection final records match compose output, `_target_` remains inert until explicit `instantiate(...)`, and no persistence or CLI behavior is invoked. If the existing e2e harness is pipeline-runner-specific, record that broader e2e is deferred to Phase 16 and cover this phase through integration tests.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: Phase 12 does not implement raw source snapshot opt-in, secret-aware runtime fingerprints, plugin/remote resolvers, network behavior, or CLI behavior.

## Risks

- Stage refactoring can subtly reorder includes, user composition overrides, recipes, ordinary overrides, validation, or runtime resolution. Full-order integration tests must lock the accepted order.
- Moving validation before runtime interpolation would change current behavior and risks rejecting values that are only valid after runtime resolution. Preserve the current resolver-scan, runtime-interpolation, validation order unless a failing test proves an already-existing helper requires otherwise.
- Public inspection can accidentally expose private helper objects or unstable class names. Contract tests should assert stable names and plain-data-compatible payloads.
- Adding `ComposedConfig` fields can break dataclass construction or tests that assume the old positional shape. Prefer keyword construction and compatibility tests.
- Placeholder manifest/source/fingerprint fields can be mistaken for final artifact population. Names and tests should make empty/deferred population explicit.
- Resolver outputs can leak into artifact fields if `unresolved`, `manifest`, stage records, or placeholder fingerprints are built after runtime resolution. Tests should distinguish `unresolved` from `resolved`.
- Importing the new inspection type from pipeline runtime code would weaken the config/pipeline boundary. Keep runtime imports one-way and prove the boundary in package tests.
- The pre-submit blocker gate may find missing suite evidence, public API ambiguity, or scope drift. Known blockers must be resolved before PR submission or the phase must be marked blocked; do not submit a PR expecting GitHub review or CI to rediscover known local blockers.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_config_api.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_compose.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_artifact_contract.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_config.py tests/integration/config/test_compose_includes.py tests/integration/config/test_compose_overrides.py tests/integration/config/test_compose_recipes.py tests/integration/config/test_compose_resolvers.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/pipeline/test_pipeline_config.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/e2e -k config
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr
UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: start with public API and data-shape tests; add inspection/stage data classes; refactor orchestration into a single staged path that preserves the current full order; add `ComposedConfig` field construction; then fill integration/contract coverage around full order, inspection-vs-compose comparison, and artifact-safety.
- Tests to run with each slice: package/API/import-boundary tests after export changes; unit/contract tests after inspection and `ComposedConfig` shape changes; integration config tests after orchestration changes; import-boundary tests after any package import edits; limited e2e only after integration passes.
- Decisions the executor must not revisit: v1 remains Python-API-only; `loom.config` writes nothing; `loom.pipeline` does not depend on config or manifests; `_copy_` stays unsupported; no raw source bytes by default; no final manifest/fingerprint/source population; resolver scan stays before runtime interpolation and current validation stays after runtime interpolation; `_target_` stays inert during composition/inspection; no default instantiation; no plugin/remote/global include resolvers; no CLI/store behavior.
- Conditions that require stopping for the manager: satisfying the phase appears to require changing pipeline ownership, importing `loom.pipeline` from config, adding persistence/CLI/storage behavior, populating final fingerprints/manifests/source hashes, persisting raw source bytes, serializing runtime objects, broadening resolver/include/target semantics, or reopening the already-used plan quality gate.
- Expanded-path refinement notes: completed. The public inspection shape, full-order contract, placeholder artifact limits, optional-instantiation interpretation, suite decisions, and blocker-gate budgets are precise enough for implementation; no blocker is recorded.

## Refinement And Review Budget Status

- Phase implementation refinement: used by expanded-path implementation refinement on 2026-05-06.
- Pre-submit blocker gate: unused; required before PR submission under the revised workflow and separate from the later PR review budget.
- PR review: unused; may be consumed only by a later manager-assigned review after PR preparation.

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed as `plan: add phase execution plan`.
- Final phase execution plan: completed by `loom_phase_planner`; refined scope contract covers public compose orchestration, public inspection, additive `ComposedConfig` fields, placeholder artifact limits, explicit-only instantiation, suite obligations, and budget status.
- Implementation summary:
  - Added public `inspect_config_composition(...)`, `ConfigCompositionInspection`, and `ConfigCompositionStageRecord` in `src/loom/config/api.py`.
  - Extended `ComposedConfig` additively with `unresolved`, `manifest`, `source_artifacts`, and `fingerprint_records` while preserving existing behavior fields.
  - Refactored orchestration so `compose_config(...)` and inspection share the same staged full-order flow and artifact-safe stage payloads.
  - Added/updated package, unit, contract, and integration coverage for inspection shape, import boundaries, stage ordering, and post-compose explicit instantiation semantics.
- Implementation validation:
  - Refinement validation reviewed: clean worktree at implementation baseline `b26dd6c`, final Phase 12 diff, relevant package/unit/contract/integration tests, prior `build/test-summary.md`, and the regenerated validation evidence below.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_compose.py tests/contracts/test_config_composition_inspection_contract.py tests/package/test_config_api.py tests/package/test_import_boundaries.py` passed after refinement with 31 passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_config.py tests/integration/config/test_compose_includes.py tests/integration/config/test_compose_overrides.py tests/integration/config/test_compose_recipes.py tests/integration/config/test_compose_resolvers.py tests/integration/pipeline/test_pipeline_config.py` passed after refinement with 42 passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` (lint/typecheck + full targeted default + `config-extra` test runs) passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` completed successfully after refinement and wrote `build/test-summary.md`; summary: package 36 passed/1 skipped, unit 354 passed/1 skipped, contract 28 passed/2 skipped, integration 9 passed/5 skipped, e2e 5 passed, config-extra 270 passed/433 deselected.
  - Required phase target suites run:
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_config_api.py tests/package/test_import_boundaries.py`
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_compose.py`
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_composition_inspection_contract.py`
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_config.py tests/integration/config/test_compose_includes.py tests/integration/config/test_compose_overrides.py tests/integration/config/test_compose_recipes.py tests/integration/config/test_compose_resolvers.py tests/integration/pipeline/test_pipeline_config.py`
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/e2e -k config` (existing e2e only; no new phase-12-specific e2e added due harness scope).
- Refinement summary: expanded-path implementation refinement complete and budget consumed. Fixed the Phase 12 placeholder manifest to use the artifact schema constant explicitly while preserving provenance schema usage for `ConfigProvenance`; restored the config-local `compose.compose_config(...)` helper to return `ComposedConfig` so its name does not conflict with its behavior; added regression coverage for artifact schema placeholder semantics and the internal helper return type. No PR preparation, PR opening, approval, merge, persistence, CLI, pipeline, or workflow-file changes performed.
- PR preparation:
  - Expanded-path PR body draft pass completed on 2026-05-06 by `loom_pr_preparer`; refine pass remains pending and PR creation is intentionally deferred to the refine pass.
  - Confirmed current worktree `/home/samcantrill/work/loom-worktrees/config-compose-orchestration`, branch `codex/config-compose-orchestration`, target branch `develop`, stack predecessor `none`, and HEAD `3fd564978e5d1091d491fb9d22f20307f38ce73f` match the phase handoff and execution-plan metadata.
  - Confirmed `develop` is an ancestor of the phase branch; Phase 12 remains a root PR candidate targeting `develop`.
  - Inspected the final diff vs `develop`, `.github/PULL_REQUEST_TEMPLATE.md`, `.codex/templates/phase-pr-body.md`, `build/test-summary.md`, implementation-plan Phase 12 scope, and completion validation evidence before drafting.
  - Created reviewer-facing PR body artifact at `docs/phases/config-compose-orchestration-pr-body.md` using the public PR template shape and suite-level evidence from `build/test-summary.md`.
  - Public PR body draft includes `@samcantrill` near the top, acceptance criteria, implementation notes, new tests, validation evidence, suite summary, and risks/follow-ups; workflow internals remain in this phase execution plan.
  - PR title remains `Configuration - Phase 12: Public Compose Orchestration And Inspection APIs`.
  - PR status: not opened in this pass because Phase 12 is expanded path and the user explicitly deferred PR creation to a later pass.
  - Budget status preserved: phase implementation refinement used; pre-submit blocker gate remains unused until the manager runs the revised pre-submit blocker gate; PR review budget remains unused until consumed by the manager-assigned gate/review.
  - Under `.codex/prompts/phase-loop-management.md`, a full pre-submit gate reviewing the implementation diff, PR body, and suite evidence consumes the Phase 12 PR-review budget unless the submitted diff changes.
- Stack maintenance: none.
- Remaining blockers: none known.
