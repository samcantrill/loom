# Phase 8 Execution Plan: Resolver Security And Runtime Interpolation

## Metadata

- Status: refined phase execution plan
- Feature focus: Configuration
- PR title: `Configuration - Phase 8: Resolver Security And Runtime Interpolation`
- Branch: `codex/config-resolver-security`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-resolver-security`
- Phase execution plan path: `docs/phases/config-resolver-security.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 8 - Resolver Security And Runtime Interpolation
- Stack predecessor: none; Phases 1-7 are merged
- Base branch: `develop`
- Base commit: `0fb73178bf6ebc925be0216e96d3b2e6cdc2396c`
- Target branch: `develop`
- Merge eligibility: root phase; eligible to merge into `develop` only after implementation, phase-scoped validation, PR preparation, and review pass against `develop`.
- Workflow path: expanded path
- Workflow path rationale: resolver security and runtime interpolation affect artifact-safe behavior, structured public error contracts, and future artifact/fingerprint phases.
- Successor dependency notes: Phase 9 recipe expansion must inherit resolver scanning and no-execution helpers without relying on resolver outputs for recipe shape. Phases 12-14 will expose inspection, manifest, redaction, and fingerprint records that depend on Phase 8 preserving authored resolver expressions before runtime resolution.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact; draft budget used.
- Refine pass: completed by `loom_phase_planner` in this artifact; refine budget used.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid, but approved outside-sandbox `gh auth status` succeeded; `gh auth setup-git` and `git fetch origin` succeeded with approved access. Local `develop` and `origin/develop` both resolved to the assigned base commit. `git worktree add` required approved access because writing Git refs was blocked by the sandbox.
- Blockers: none.

## Objective

Separate artifact-safe resolver handling from runtime interpolation so `loom.config` can scan and preserve authored OmegaConf resolver expressions without executing them for private artifact-safe paths, execute only the explicitly allowed runtime resolver set during final runtime resolution, and fail custom resolver-style interpolation with a structured `ConfigUnsupportedResolverError` that is also catchable as `NotImplementedError`.

## Full-Plan Context

Phases 1-7 established config boundaries, artifact skeletons, structured errors, strict merge and overrides, source-aware overlays, deterministic include expansion, and user composition overrides. Phase 8 hardens the interpolation boundary before recipe ordering, public inspection, manifest population, source artifacts, redaction population, artifact-safe fingerprints, resume comparison, and CLI behavior arrive. This phase must not persist resolved config values, populate future manifest/source/fingerprint fields, implement recipe behavior that depends on resolver values, or introduce pipeline dependence on config.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-7 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`, the implementation plan records Phase 7 merged, and local `develop` matches the assigned base commit.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after the Phase 8 PR is merged and no successor phase branch depends on `codex/config-resolver-security`.

## Source Phase Summary

- Goal: separate artifact-safe resolver handling from runtime interpolation.
- Required scope: resolver-expression scanning; artifact-safe no-execution paths; runtime-only built-in OmegaConf resolver execution; `ConfigUnsupportedResolverError` as both `ConfigError` and `NotImplementedError`; failures for resolver-dependent composition control flow.
- Required checkpoints: add scanner metadata for resolver-style expressions; preserve authored resolver strings on private artifact-safe paths; allow only the Phase 8 resolver allow-list during the runtime resolution stage; reject custom or non-allow-listed resolver-style interpolation through the new structured error; ensure include and user-composition control flow cannot depend on resolver execution.
- Acceptance criteria: private artifact-safe helper paths do not execute resolvers; the Phase 8 allow-listed resolver can execute only in final runtime resolution; custom and non-allow-listed resolver-style interpolation fails with structured context; resolver-dependent include or composition decisions fail.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/interpolation.py` currently validates all interpolation before OmegaConf resolution and rejects every resolver-style token with `ConfigInterpolationError`. `src/loom/config/recipes/expansion.py` has its own recipe-argument interpolation helper that also rejects resolver-style tokens manually; Phase 8 must not turn recipe argument resolution into a resolver-executing path or bless resolver-dependent recipe shape behavior reserved for Phase 9. `src/loom/config/includes.py` already rejects interpolation-looking include targets with structured `ConfigIncludeResolutionError` code `resolver_dependent`; both file-defined includes and Phase 7 user include overrides reach `resolve_include_target(...)`. `src/loom/config/compose.py` currently runs include expansion, user composition overrides, ordinary overrides, `resolve_recipe_argument_interpolation()`, `expand_recipes()`, final `resolve_interpolation()`, validation, redaction, provenance, and fingerprint construction in one path. `src/loom/config/errors.py` has structured context support for load/include errors but `ConfigInterpolationError` is currently message-only and no `ConfigUnsupportedResolverError` exists. Artifact/provenance/fingerprint skeletons in `src/loom/config/artifacts.py`, `src/loom/config/provenance.py`, and `src/loom/fingerprints.py` are plain-data and resolver-output-free; full manifest/source/fingerprint population is later-phase work.
- Existing tests or harness behavior: `tests/unit/loom/config/test_interpolation.py` covers basic interpolation, rejects resolver-style interpolation, and rejects unresolved references. `tests/unit/loom/config/recipes/test_expansion.py` covers current recipe-argument interpolation and should continue to prove recipe argument handling does not execute resolvers in this phase. `tests/unit/loom/config/test_includes.py` already covers resolver-dependent include targets. Phase 7 user include override integration coverage lives in `tests/integration/config/test_compose_overrides.py` and needs resolver-expression cases. Contract tests for structured config errors live in `tests/contracts/test_config_error_contract.py`, unit error-shape tests live in `tests/unit/loom/config/test_config_errors.py`, and artifact skeleton contracts live in `tests/contracts/test_config_artifact_contract.py`.
- Import-boundary or dependency constraints: keep implementation under `src/loom/config/` and config tests. Do not import `loom.pipeline`, stores, CLI modules, plugin discovery, project packages, network clients, or heavyweight new runtime dependencies. OmegaConf is already the config optional dependency; do not add another resolver engine.

## In-Scope Work

- Add resolver-expression scanning helpers that walk plain config data, identify OmegaConf resolver-style interpolation tokens, retain config paths and authored token text, and classify resolver names without executing the expression.
- Add private artifact-safe no-execution helper paths that return or validate unresolved plain data plus resolver metadata for future artifact/redaction/fingerprint phases. These helpers must preserve authored resolver expressions as strings, must not write to artifact/provenance/fingerprint skeletons, and must not call `OmegaConf.to_container(..., resolve=True)` or equivalent resolution.
- Update runtime interpolation so resolver-style interpolation may execute only in the final runtime resolution stage and only for the Phase 8 allow-list. The Phase 8 allow-list is deliberately `oc.env` only. Although the environment currently exposes OmegaConf resolvers such as `oc.create`, `oc.decode`, `oc.select`, `oc.dict.keys`, and `oc.dict.values`, they remain unsupported in this phase because several can reinterpret or reshape values and need explicit later review.
- Add `ConfigUnsupportedResolverError` with structured context. It must inherit from `ConfigError` and `NotImplementedError`, serialize context consistently with existing config-domain structured errors, identify the config path, resolver name, authored expression, source context where available, and remediation.
- Reject custom and non-allow-listed resolver-style interpolation before runtime value resolution with `ConfigUnsupportedResolverError`; do not allow OmegaConf to discover or execute project custom resolvers implicitly.
- Preserve existing failures for resolver-dependent include targets and user-composition include targets, tightening tests where needed so composition control flow is decided from authored values only and existing include error codes remain compatible.
- Add narrow compose wiring only where needed to keep private unresolved/artifact-safe handling separate from final runtime resolution without moving resolver execution before include/user-composition decisions and without adding public v1 inspection fields or persisted artifacts early.

## Out-of-Scope Work

- Recipes that depend on resolver values, including resolver-dependent recipe output shape or recipe argument policy beyond avoiding new resolver leaks.
- Persisted resolved config, resolved resolver-output artifacts, secret-aware hashes, raw source snapshots, and opt-in runtime-value persistence.
- Public CLI commands, CLI-specific resolver syntax, or CLI-authored source-context behavior.
- Manifest, source artifact, redaction, fingerprint, inspection, or resume population beyond what current skeletons already expose and what Phase 8 needs to avoid resolver execution.
- Pipeline imports, pipeline dependence on config, run-store writes, plugin/remote resolver extension APIs, global search paths, Hydra compatibility, `_copy_`, or project schema imports.

## Assumptions

- Authored configs are trusted project code, but default config artifacts must still be security-first and must not persist resolver outputs such as environment values.
- V1 supports OmegaConf-style interpolation at runtime; the security boundary is when resolution happens, not a replacement of OmegaConf.
- Built-in resolver execution is allow-listed by resolver name. For Phase 8 the only allowed resolver is `oc.env`; `env` is not available in the current OmegaConf environment and remains unsupported, and all other `oc.*` resolvers fail through `ConfigUnsupportedResolverError` until a later phase explicitly admits them.
- Resolver scanning can operate on plain Python data after YAML loading, source-aware merging, includes, and user composition, because those stages should only need authored scalar strings and source context.
- Include target resolution already rejects strings containing `${...}`. Phase 8 may reuse or factor scanner logic, but must preserve structured include-resolution error behavior and codes.
- Full public `ComposedConfig.unresolved`, `manifest`, `source_artifacts`, and artifact-safe default fingerprint population are later plan phases. Phase 8 may keep intermediate unresolved data private until those public contracts are introduced.
- `ConfigUnsupportedResolverError` should be importable from `loom.config.errors`. Exporting it from `loom.config` package `__all__` is a deliberate package API choice only if the implementation follows existing config-error export patterns and package import tests stay cheap; root `loom` exports remain out of scope.

## Scope Contract

- Phase 8 changes resolver/interpolation behavior inside `loom.config`; it does not add root exports, CLI behavior, pipeline behavior, run-store persistence, public `ComposedConfig` fields, or future artifact fields.
- Artifact-safe paths are private no-execution paths in this phase. They may scan and report resolver expressions and return unresolved plain data plus resolver metadata to internal callers/tests, but they must leave source strings unchanged and must not resolve environment variables, custom resolver outputs, allow-listed resolver outputs, or cross-node interpolation values for public artifact generation. Do not claim final artifact generation or public unresolved output in Phase 8.
- Runtime resolution is the only place the Phase 8 allow-listed resolver may execute. Runtime resolution output remains in-memory for Python callers and may feed existing `ComposedConfig.resolved` behavior, but Phase 8 must not persist resolved resolver outputs by default.
- Custom resolver-style interpolation must fail before execution with `ConfigUnsupportedResolverError`. The error must satisfy `isinstance(error, ConfigError)` and `isinstance(error, NotImplementedError)`, carry structured `ConfigErrorContext`, and avoid including resolved secret values.
- Any resolver-style token outside `oc.env`, including currently available OmegaConf built-ins such as `oc.create`, `oc.decode`, `oc.select`, `oc.dict.keys`, and `oc.dict.values`, must fail with `ConfigUnsupportedResolverError` in Phase 8. Plain node interpolation such as `${paths.root}` remains runtime interpolation, not resolver-style execution.
- Resolver-dependent composition control flow fails closed. `_include_` targets or user-composition include targets that contain resolver/interpolation expressions must not be resolved to decide files or replacement behavior. Preserve `ConfigIncludeResolutionError` code `resolver_dependent` for these include paths unless implementation finds a strictly compatible context addition. Recipe-specific resolver-dependent shape failures are deferred to Phase 9; current recipe argument interpolation should continue rejecting resolver-style tokens without executing them.
- `loom.pipeline` and runtime modules must remain independent of `loom.config`, manifests, and config artifacts.

## Design Impact

- Maintainability: separates scanning, artifact-safe handling, and runtime resolution into explicit helpers so later artifact and fingerprint phases can reuse one no-execution boundary instead of duplicating ad hoc string checks.
- Extensibility: leaves future custom resolver policy, wider OmegaConf built-in allow-lists, secret-aware fingerprints, and opt-in resolved persistence possible by making v1 resolver admission explicit and structured.
- Domain neutrality: treats resolver names and config paths generically with no model, dataset, stage, or project-schema assumptions.
- Source-tree boundaries: keeps work in `loom.config` and tests, reusing OmegaConf as the existing optional config dependency and avoiding pipeline, stores, CLI, plugins, remote IO, or project imports.

## Future Compatibility

- Phase 9 can use the scanner to reject resolver-dependent recipe shape decisions without inventing a second resolver parser, but Phase 8 does not change recipe execution order or resolver policy for recipe output shape.
- Phase 12 can expose resolver-expression paths in public inspection records additively.
- Phase 13 can populate manifest/provenance/redaction records from unresolved config plus resolver metadata without leaking runtime values.
- Phase 14 can compute artifact-safe fingerprints before resolver execution and explicitly exclude resolver outputs.
- Future CLI, sweeps, plugins, and remote-store phases can build on the same fail-closed custom resolver and control-flow rules rather than depending on implicit OmegaConf resolver behavior.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Continue rejecting all resolver-style interpolation | Conflicts with v1 acceptance criteria that built-in OmegaConf resolvers, including `oc.env`, can execute at runtime. |
| Allow every currently registered OmegaConf `oc.*` built-in | Current availability includes `oc.create`, `oc.decode`, `oc.select`, `oc.dict.keys`, and `oc.dict.values`; some can reshape or reinterpret values and should not enter the runtime contract without explicit review. |
| Resolve all interpolation before artifact generation | Would leak environment values or other runtime resolver outputs into artifacts and fingerprints by default. |
| Let OmegaConf attempt custom resolver execution and wrap failures afterward | Custom resolver execution is explicitly unsupported in v1 and must fail closed before arbitrary resolver code can run. |
| Persist resolved config or resolver outputs as Phase 8 artifacts | Later phases own persistence contracts, and default persistence of resolver outputs is an accepted security risk to avoid. |
| Add project custom resolver registration or plugin resolver APIs | Custom resolvers and plugin/remote extension contracts are explicitly deferred beyond v1. |
| Make recipe resolver-dependent behavior part of Phase 8 | Phase 9 owns recipe catalog and expansion ordering; Phase 8 should only provide reusable resolver security primitives and avoid future-phase recipe semantics. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Resolver metadata may remain private until inspection/artifact phases | Keeps Phase 8 focused on security and runtime semantics without prematurely freezing public artifact fields. | Revisit in Phases 12-14 when inspection, manifest, redaction, and fingerprint records are populated. |
| Built-in resolver allow-list is intentionally `oc.env` only | Avoids silently permitting OmegaConf built-ins that can reshape values or expose runtime data in ways not reviewed by v1. | Revisit when a concrete v1 workflow needs another built-in and the phase plan or follow-up design records its artifact-safety implications. |
| Exact runtime resolver values are not replayable from default artifacts | Preserves security-first defaults by keeping runtime values out of persisted artifact paths. | Revisit only with explicit opt-in resolved persistence or secret-aware fingerprint policy. |

## Reviewability

- Expected PR size and shape: focused resolver/interpolation helper changes, one new structured error class, small compose-stage wiring for private unresolved versus runtime resolution, and targeted unit/contract/integration tests. No broad public API or artifact-population diff.
- Files and areas to inspect: likely `src/loom/config/interpolation.py`, `src/loom/config/errors.py`, `src/loom/config/compose.py`, `src/loom/config/recipes/expansion.py` only to preserve no-execution recipe-argument rejection if needed, possibly `src/loom/config/includes.py` if scanner logic is shared for include target rejection, `tests/unit/loom/config/test_interpolation.py`, `tests/unit/loom/config/test_includes.py`, `tests/unit/loom/config/test_config_errors.py`, `tests/unit/loom/config/recipes/test_expansion.py`, `tests/contracts/test_config_error_contract.py`, `tests/integration/config/test_compose_overrides.py`, and new resolver integration tests under `tests/integration/config/`.
- Scope-control checks: no public CLI commands; no root package exports; no public `ComposedConfig` fields; no pipeline imports; no run-store writes; no persisted resolved config; no resolver outputs, env values, or raw source bytes in artifact/provenance/fingerprint skeletons; no secret-aware hashes; no manifest/source-artifact/fingerprint population beyond current skeletons; no `_copy_`; no custom or non-allow-listed resolver execution; no plugin or remote resolver contracts; no recipe-dependent resolver shape work.

## Implementation Steps

1. Add resolver scanning and metadata primitives for plain config data. They should report resolver names, authored expressions, config paths, and whether the resolver is Phase 8-allowed (`oc.env`) or unsupported without executing the expression.
2. Introduce `ConfigUnsupportedResolverError` and structured context helpers for unsupported custom resolver-style interpolation. Add contract coverage for inheritance, serialization, and non-leaking plain-data context.
3. Split interpolation helpers into private artifact-safe no-execution validation/scanning and runtime resolution. Runtime resolution may execute only `oc.env`; custom and non-allow-listed resolvers fail before OmegaConf can execute them.
4. Wire compose internals so private artifact-safe data remains unresolved before runtime interpolation while preserving existing public `ComposedConfig.resolved` behavior for Python callers. Keep future public fields private/out of scope and do not move resolver execution before includes, user composition overrides, or ordinary override parsing.
5. Preserve resolver-dependent composition control-flow failures around file-defined include targets and Phase 7 user-composition include overrides, reusing scanner behavior only if it preserves existing structured include error contracts and `resolver_dependent` code.
6. Keep recipe argument interpolation no-execution in Phase 8. If shared scanner logic touches `recipes/expansion.py`, preserve the current fail-closed resolver-style rejection and defer resolver-dependent recipe shape semantics to Phase 9.
7. Add focused tests proving artifact-safe paths do not execute resolvers, `oc.env` executes only during runtime resolution, non-allow-listed built-ins and custom resolvers are structured failures, and resolver-dependent include/composition targets fail closed.

## Test Plan

### Package Suite

- Status: required only if public exports or import behavior change; otherwise deferred for targeted implementation and covered by final PR validation.
- Expected paths: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py`, `tests/package/test_public_api.py` if touched.
- Required assertions or deferral reason: no root exports are expected. If `loom.config` package exports `ConfigUnsupportedResolverError`, assert the export is intentional, mirrors existing config-error patterns, and stays cheap. Import-boundary tests must still prove `loom.config` does not import pipeline, stores, CLI, plugin discovery, project modules, network clients, or heavyweight optional dependencies eagerly.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_interpolation.py`, `tests/unit/loom/config/test_includes.py`, `tests/unit/loom/config/test_config_errors.py`, and `tests/unit/loom/config/recipes/test_expansion.py` if recipe interpolation helpers are touched.
- Required assertions or deferral reason: scanner finds resolver-style expressions in mappings/lists/scalars and records paths without execution; scanner/no-execution helpers can be tested with sentinel resolver names or monkeypatched OmegaConf resolver hooks proving no resolver executes; plain node interpolation remains supported at runtime; `oc.env` executes only through runtime resolution; private artifact-safe helper paths preserve authored strings; custom resolver tokens raise `ConfigUnsupportedResolverError`; non-allow-listed available built-ins such as `oc.create`, `oc.decode`, `oc.select`, `oc.dict.keys`, and `oc.dict.values` raise `ConfigUnsupportedResolverError`; unresolved ordinary interpolation still fails in runtime resolution; file-defined include targets containing interpolation/resolver expressions fail with structured `resolver_dependent` include errors; recipe-argument interpolation continues to reject resolver-style tokens without execution.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_config_error_contract.py`; `tests/contracts/test_config_artifact_contract.py` only if current skeleton artifact helpers gain resolver metadata serialization.
- Required assertions or deferral reason: `ConfigUnsupportedResolverError` is both a `ConfigError` and `NotImplementedError`; its structured context round-trips as plain data and includes code, source kind/order/path when available, config path, expression/directive, resolver name, authored token, and remediation; context does not contain resolved environment values, raw source bytes, or non-plain objects. `tests/unit/loom/config/test_config_errors.py` must assert the error-shape inheritance. If resolver metadata remains private without public serialization, artifact contract tests can remain unchanged.

### Integration Suite

- Status: required.
- Expected paths: new `tests/integration/config/test_compose_resolvers.py`, plus focused additions to `tests/integration/config/test_compose_overrides.py` for user-composition include overrides with resolver expressions. Additions to `tests/integration/config/test_compose_includes.py` are acceptable if they better preserve existing include coverage.
- Required assertions or deferral reason: public `compose_config` with `oc.env` resolves the runtime `ComposedConfig.resolved` value only in final runtime resolution; private artifact-safe scanner/no-execution helper results do not require executing resolver values and preserve authored expressions; custom resolver-style interpolation fails before execution with structured context; non-allow-listed available OmegaConf built-ins fail with `ConfigUnsupportedResolverError`; file-defined include targets containing resolver expressions fail before file resolution with existing include error code `resolver_dependent`; Phase 7 user composition overrides such as `pipeline.model._include_=${oc.env:MODEL}` and `+pipeline.dataset._include_=${oc.env:DATASET}` also fail before file resolution through the include path; no resolved resolver output appears in any Phase 8 artifact-safe helper result.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 8 does not complete public v1 inspection APIs, persisted artifacts, full artifact-safe fingerprints, CLI behavior, run-store writes, or pipeline execution changes. Public e2e coverage belongs to later orchestration and artifact phases.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: custom resolver plugins, remote resolvers, network-backed includes, raw source snapshots, secret-aware hashes, resolved-value persistence, and CLI behavior are out of scope.

## Risks

- A no-execution scanner can drift from OmegaConf syntax. Keep it narrow and test the supported v1 expression forms rather than trying to implement a full OmegaConf parser.
- Runtime resolution can accidentally execute custom or non-allow-listed built-in resolvers if unsupported names are not rejected before calling OmegaConf resolution.
- OmegaConf built-ins beyond `oc.env` are available in the environment; allowing them by accident could add value reshaping or interpretation semantics that are not reviewed in v1.
- Existing compose flow currently builds redaction, provenance, and fingerprints after runtime resolution. Phase 8 must avoid broad artifact redesign while establishing private unresolved/no-execution paths for later phases.
- Error contexts can leak authored secret-like strings. Tests should focus on avoiding resolved secret values and non-plain payloads; redaction policy population is later-phase work.
- Recipe argument interpolation currently sits near compose's interpolation path. Phase 8 should not accidentally implement or bless resolver-dependent recipe output shape behavior reserved for Phase 9.
- Sharing scanner logic with include resolution could regress existing include error codes or path context. Preserve existing structured include contracts.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/config/test_interpolation.py
uv run pytest tests/unit/loom/config/test_includes.py
uv run pytest tests/unit/loom/config/test_config_errors.py
uv run pytest tests/unit/loom/config/recipes/test_expansion.py
uv run pytest tests/contracts/test_config_error_contract.py
uv run pytest tests/integration/config/test_compose_resolvers.py
uv run pytest tests/integration/config/test_compose_overrides.py
uv run pytest tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: start with scanner and `ConfigUnsupportedResolverError` contracts, then split private artifact-safe and runtime interpolation helpers, then wire compose narrowly, then add integration coverage for `oc.env`, custom/non-allow-listed resolvers, file-defined includes, and user composition include overrides.
- Tests to run with each slice: unit interpolation tests after scanner/runtime work; unit and contract error tests after adding `ConfigUnsupportedResolverError`; include tests after touching include target scanning; recipe expansion tests if shared interpolation logic touches recipe helpers; resolver and compose-override integration tests after compose wiring; import-boundary package tests if exports or imports change.
- Decisions the executor must not revisit: Phase 8 resolver allow-list is `oc.env` only; no custom resolver execution; no execution of other available OmegaConf built-ins; no artifact-time resolver execution; no persisted resolved config; no secret-aware hashes; no recipe-dependent resolver shape behavior; no CLI, pipeline, plugin, remote resolver, `_copy_`, public `ComposedConfig` fields, manifest, source-artifact, or fingerprint population beyond current skeletons.
- Conditions that require stopping for the manager: implementing Phase 8 appears to require changing public artifact schemas, adding `ComposedConfig` v1 fields early, executing custom or non-allow-listed resolvers, changing recipe expansion policy beyond preserving no-execution rejection, importing pipeline/runtime/store/CLI modules, or adding a new dependency.
- Expanded-path refinement notes: completed. The refined contract fixes the Phase 8 resolver allow-list to `oc.env`, keeps artifact-safe behavior private/no-execution, preserves include error contracts, and keeps recipe resolver-dependent shape behavior deferred to Phase 9.

## Refinement And Review Budget Status

- Phase implementation refinement: used by the single allowed Phase 8 implementation refinement pass on 2026-05-05.
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed as `plan: add phase execution plan`.
- Final phase execution plan: completed by `loom_phase_planner`; committed as `plan: refine phase execution plan`.
- Implementation summary:
  - Added `ConfigUnsupportedResolverError` in `src/loom/config/errors.py` as a `ConfigError`/`NotImplementedError` pair with `ConfigErrorContext` metadata support.
  - Added no-execution resolver scanning in `src/loom/config/interpolation.py` (`scan_resolver_expressions`) with `ResolverExpressionRecord` metadata and resolver allow-list enforcement in runtime resolution.
  - Updated `src/loom/config/compose.py` to scan for resolver expressions prior to final runtime interpolation and only execute interpolation in the runtime stage.
  - Added phase-scoped unit/contract/integration tests for resolver allow-listing, no-execution behavior, and resolver-dependent include target/override failures.
- Implementation validation:
  - Initial executor validation used the wrong dependency setup and failed because optional config dependencies were unavailable in that test environment. The blocker was cleared by rerunning with `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config ...`.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_interpolation.py tests/unit/loom/config/test_config_errors.py tests/contracts/test_config_error_contract.py` initially failed with 9 phase-owned failures: `ConfigUnsupportedResolverError` did not accept structured `context=`, scanner paths did not match repository config-path formatting, and unsupported built-in resolvers with nested interpolation arguments reached OmegaConf and surfaced as `ConfigInterpolationError`.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_includes.py tests/unit/loom/config/recipes/test_expansion.py tests/integration/config/test_compose_resolvers.py tests/integration/config/test_compose_overrides.py tests/package/test_import_boundaries.py` initially failed with 4 phase-owned failures: unsupported resolver compose paths hit the same structured-error constructor issue, and user-composition include override resolver-expression tests expected `ConfigIncludeExpansionError` while the existing include target contract correctly raises `ConfigIncludeResolutionError` with code `resolver_dependent`.
  - After refinement, `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_interpolation.py tests/unit/loom/config/test_config_errors.py tests/contracts/test_config_error_contract.py` passed: 24 passed.
  - After refinement, `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_includes.py tests/unit/loom/config/recipes/test_expansion.py tests/integration/config/test_compose_resolvers.py tests/integration/config/test_compose_overrides.py tests/package/test_import_boundaries.py` passed: 83 passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed: Ruff passed; Pyright passed with 0 errors; default suite passed with 426 passed and 9 skipped; config-extra suite passed with 236 passed and 431 deselected; build succeeded.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed and wrote `build/test-summary.md`: package 36 passed/1 skipped; unit 354 passed/1 skipped; contract 27 passed/1 skipped; integration 9 passed/5 skipped; e2e 5 passed; config-extra 236 passed/431 deselected.
- Implementation refinement report:
  - Validation output reviewed: both corrected targeted pytest commands, `make validate-pr`, and `make test-summary`.
  - Blocking issues caused by this phase: unsupported-resolver structured error constructor, no-execution resolver scanner path formatting, nested resolver-token scanning before OmegaConf runtime resolution, and resolver-dependent include-override test expectations.
  - Issues confirmed out of scope: wrapping user-composition include target resolver expressions as `ConfigIncludeExpansionError`; preserving the existing `ConfigIncludeResolutionError`/`resolver_dependent` include contract is the refined phase behavior.
  - Fixes made: `ConfigUnsupportedResolverError` now inherits the structured config error base while remaining catchable as `NotImplementedError`; resolver scanning uses repository config-path formatting and scans balanced nested interpolation tokens before OmegaConf resolution; include override resolver-expression tests now expect `ConfigIncludeResolutionError` for the existing include target contract; type-check narrowing/casts were added for validation.
- Refinement summary: clarified `oc.env`-only runtime resolver allow-list, private artifact-safe scanner/no-execution semantics, include/user-composition resolver-expression coverage, recipe no-execution boundaries, structured error tests, and unchanged artifact/pipeline/CLI scope.
- PR preparation: pending.
- Stack maintenance: pending.
- Remaining blockers: none known after the single implementation refinement pass.
