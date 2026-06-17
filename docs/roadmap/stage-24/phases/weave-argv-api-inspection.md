# Phase 3 Execution Plan: Public Argv API, Inspection, Diagnostics, And Docs

## Metadata

- Status: refined phase execution plan; implementation-ready
- Feature focus: Weave Argv Config Shorthand
- PR title: `Weave Argv Config Shorthand - Phase 3: Public Argv API and Inspection`
- Branch: `codex/weave-argv-api-inspection`
- Worktree: `/nas/home/can134/work/loom-worktrees/weave-argv-api-inspection`
- Phase execution plan path: `docs/roadmap/stage-24/phases/weave-argv-api-inspection.md`
- Full plan: `docs/roadmap/stage-24/implementation-plan.md`
- Source phase: Phase 3, `weave-argv-api-inspection`
- Stack predecessor: none; Phases 1 and 2 are merged into `develop`
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: merge eligible only when the PR targets `develop`, automated review passes, and validation/CI pass
- Workflow path: expanded path
- Successor dependency notes: no known Stage 24 successor phase; keep the branch until merge cleanup confirms no successor branch depends on it
- Plan quality gate: implementation-plan quality gate passed and is recorded in the full plan
- Plan quality gate loop budget: consumed upstream; review, refinement, and confirmation completed with no blocking findings remaining
- Draft pass: completed by `loom_phase_planner`
- Refine pass: completed because this phase changes public API, diagnostics, docs, and end-to-end behavior
- Setup limitations: configured root `/home/samcantrill/work/loom-worktrees` was unavailable in this session, so the fallback root `/nas/home/can134/work/loom-worktrees` was used
- Blockers: none; implementation may begin after this refined plan commit

## Objective

Expose the Stage 24 argv shorthand as a narrow public `weave` API, finish helper-local warnings and structured diagnostics, publish the argv inspection helper through `weave.api`, update feature documentation from proposal language to implemented behavior, and prove the full project-CLI adapter behavior end to end without changing existing non-argv composition callers.

## Full-Plan Context

Phase 1 added private argv parsing and records in `weave._argv`. Phase 2 added private scoped-overlay composition, provenance, artifact, fingerprint, raw snapshot, and internal `argv_scoped_overlays` inspection support. Phase 3 is the public integration phase: it wraps those private capabilities in stable result objects, exposes only the main compose helper at the top level, exposes the inspection companion and detailed records through `weave.api`, and documents the behavior for project-specific CLI authors.

This phase must not add a first-party `weave` executable, Loom CLI adapter work, runtime/store/scheduler behavior, Hydra/defaults/config-group semantics, a new source artifact kind, or persisted argv warning artifacts. Existing public `compose_config(...)` and `inspect_config_composition(...)` behavior, signatures, import surface, and non-argv inspection stage order must remain unchanged.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: Phase 1 PR #206 and Phase 2 PR #207 are merged into `develop`; the worktree was created from local `develop` at `19fab71`, which records Phase 2 merge metadata.
- Retarget/rebase plan after predecessor merge: none needed for this root PR.
- Branch cleanup constraints: the branch can be deleted after merge only after confirming no later branch has stacked on it.

## Source Phase Summary

- Goal: expose public helpers and result records, finish warnings/diagnostics, update docs, and validate the full argv helper flow.
- Required scope: public `compose_config_from_argv(...)` top-level export; `inspect_config_from_argv(...)` and detailed result/record/warning types through `weave.api`; helper-local warnings; docs for implemented behavior and deferrals; public-helper tests.
- Required checkpoints: top-level API remains narrow; `weave.api` exposes detailed types; warnings are not stored in `ComposedConfig`, manifests, provenance, source artifacts, raw snapshots, or fingerprints; direct non-argv callers remain behaviorally unchanged.
- Acceptance criteria: contract, package/import, unit, integration, e2e, docs/example, and final validation evidence cover public imports, result/warning shape, error context, inspection stage exposure, warning heuristics, documented examples, and non-argv regressions.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `packages/weave/src/weave/_argv.py` defines private parser records and `parse_config_argv(...)`. The current record `to_dict()` shapes are `ArgvValueOverride(raw, path, operation, value, order)`, `ScopedOverlayCandidate(path, origin, exists)`, `ArgvScopedOverlay(raw, scope_path, operation, rhs, candidates, resolved_path, order)`, `ArgvUnparsedArg(raw, order)`, and `ParsedConfigArgv(command, base_config_path, value_overrides, scoped_overlays, unparsed_args)`.
  - `packages/weave/src/weave/compose.py` defines private `_inspect_config_composition_with_argv_scoped_overlays(...)`, emits the argv-only `argv_scoped_overlays` stage when requested, and keeps public non-argv inspection unchanged.
  - `packages/weave/src/weave/api.py` owns public config dataclasses, wrapper validation, and `__all__`; this phase should add public result/warning dataclasses and helper wrappers there.
  - `packages/weave/src/weave/__init__.py` uses lazy top-level exports; this phase should add only `compose_config_from_argv` to the lazy public package surface.
  - `weave.errors.ConfigErrorContext` is the structured error contract. Public helper errors should preserve context codes, source kind/order/path, directive, remediation, and plain-data details from parser and composition failures.
  - `docs/features/config.md` still frames CLI behavior as future-facing and must be updated in the phase worktree during implementation, not in the dirty control checkout.
- Existing tests or harness behavior:
  - `packages/weave/tests/unit/config/test_argv.py` covers parser records, lookup rules, unparsed args, root overlay rejection, and parser diagnostics.
  - `packages/weave/tests/integration/config/test_compose_argv_scoped_overlays.py` covers private scoped-overlay composition, order, provenance, artifact metadata, raw snapshots, and structured target/load errors.
  - `packages/weave/tests/contracts/test_config_composition_inspection_contract.py` anchors public non-argv inspection stages and private argv-only stage position, including the empty-overlay argv path.
  - `packages/weave/tests/contracts/test_config_error_contract.py` anchors `ConfigErrorContext` serialization and round-tripping.
  - `tests/e2e/test_config_composition_public_api.py` is the public Python API e2e anchor for composition behavior.
- Import-boundary or dependency constraints:
  - `weave` must not import `loom`.
  - No new runtime dependency is expected.
  - Authored configs remain trusted project code.
  - Warnings are helper-result data only and must not affect artifact-safe fingerprints.

## In-Scope Work

- Add `compose_config_from_argv(...)` as the only new top-level `weave` export for this phase. It must also be available from `weave.api`.
- Add `inspect_config_from_argv(...)` through `weave.api` only; do not add it to top-level `weave.__all__`, lazy `_OPTIONAL_SYMBOLS`, or `TYPE_CHECKING` imports.
- Add public result and warning dataclasses through `weave.api` with validation aligned with existing API records:
  - `ConfigArgvCompositionResult` for composed-config results.
  - `ConfigArgvInspectionResult` for inspection results.
  - `ConfigArgvWarning` for helper-local warnings.
- Re-export the detailed argv record types through `weave.api`: `ArgvValueOverride`, `ArgvScopedOverlay`, `ScopedOverlayCandidate`, `ArgvUnparsedArg`, and `ParsedConfigArgv`. Keep `parse_config_argv(...)` private unless a separate public API decision is recorded.
- Compose helper behavior: parse `argv` defaulting to `sys.argv[1:]`, validate caller-supplied command choices, pass value override strings and scoped overlay records to existing composition machinery, and return command/base path/records/unparsed args/warnings plus the composed config.
- Inspection helper behavior: use the same parse and composition path, return the same argv metadata/warnings plus `ConfigCompositionInspection`, and expose the `argv_scoped_overlays` stage even when there are no scoped overlays because the private argv inspection path already records that stage.
- Generate conservative non-fatal warnings for likely overlay mistakes after enough composed target-shape context is available. Warnings must never change the composed config or persisted artifacts.
- Preserve all existing direct `compose_config(...)`, `compose_config_with_catalog(...)`, and `inspect_config_composition(...)` public behavior for non-argv callers.
- Update only the Stage 24-relevant portions of `docs/features/config.md` during implementation to document the implemented argv helper, trailing-slash overlay syntax, lookup rules, ordering, warnings, structured errors, inspection, audit behavior, and explicit deferrals.
- Add package-local and public Python API tests required by the suite plan.

## Out-of-Scope Work

- First-party `weave` executable, console script, argparse parser, or process exit/display policy.
- Loom CLI adapter work or any `loom.cli` parser changes.
- Runtime execution, pipeline planning, stores, schedulers, events, downstream operations, or run persistence.
- Persisting argv warnings into `ComposedConfig`, manifests, provenance, source artifacts, raw source snapshots, fingerprints, or run artifacts.
- New `SourceArtifactRecord.kind`, artifact schema version, manifest schema change, or source artifact migration.
- Hydra/defaults/config-group behavior, RHS overlay inference, escaped dot-path grammar, advanced list patching, or untrusted-config sandboxing.
- Exporting `inspect_config_from_argv(...)`, detailed argv records, or warning/result records from top-level `weave`.
- Making `parse_config_argv(...)` a public `weave.api` function without a separate recorded API decision.
- Broad docs rewrites outside the Stage 24 config feature section and directly related examples.

## Assumptions

- Public result and warning names are fixed for implementation as `ConfigArgvCompositionResult`, `ConfigArgvInspectionResult`, and `ConfigArgvWarning`.
- Existing internal `ArgvValueOverride`, `ArgvScopedOverlay`, `ScopedOverlayCandidate`, `ArgvUnparsedArg`, and `ParsedConfigArgv` records are stable enough to re-export through `weave.api`; wrapping or renaming them is out of scope unless implementation finds a concrete validation or typing blocker.
- `command_choices` remains caller-provided and command-name agnostic; `weave` does not hard-code commands or own process exit behavior.
- Warning heuristics should prefer false negatives over noisy or surprising warnings. A missing warning is acceptable when the mistaken-intent signal is weak; a warning that changes behavior or artifacts is not acceptable.
- Docs updates in the phase worktree may edit `docs/features/config.md` during implementation; unrelated local modifications in the control checkout must remain untouched.

## Scope Contract

### Public API And Export Boundary

`compose_config_from_argv(...)` should be discoverable as `weave.compose_config_from_argv` and available from `weave.api`. The top-level lazy package surface should add exactly that one new name and no argv record, warning, inspection, or parser names. Import tests must assert that `weave.inspect_config_from_argv`, `weave.ConfigArgvCompositionResult`, `weave.ConfigArgvInspectionResult`, `weave.ConfigArgvWarning`, `weave.ArgvScopedOverlay`, `weave.ArgvValueOverride`, `weave.ScopedOverlayCandidate`, `weave.ArgvUnparsedArg`, `weave.ParsedConfigArgv`, and `weave.parse_config_argv` are not top-level attributes.

`weave.api` should expose `compose_config_from_argv`, `inspect_config_from_argv`, the three public result/warning types, and the five selected detailed argv record types. `parse_config_argv(...)` should remain an internal function in `weave._argv`; project CLI callers should use the public compose/inspect helpers and inspect returned records rather than depending on the parser entrypoint.

Both public helpers should accept an argv-like sequence or `None` for `sys.argv[1:]`, caller command choices, `allow_unparsed`, optional `RecipeCatalog`, and `include_raw_source_snapshots`. They should not accept display, exit-code, argparse, Loom CLI, store, scheduler, or runtime execution parameters.

### Result Record Shape

`ConfigArgvCompositionResult` should be a frozen plain-data-validating API record with these public fields: `command`, `base_config_path`, `parsed_argv`, `value_overrides`, `scoped_overlays`, `unparsed_args`, `warnings`, and `composed_config`. The `value_overrides`, `scoped_overlays`, and `unparsed_args` fields should mirror the corresponding tuples on `parsed_argv` for ergonomic access; tests should ensure they stay consistent.

`ConfigArgvInspectionResult` should mirror the composition result fields but replace `composed_config` with `inspection`. It may expose a `to_composed_config()` convenience only if it delegates to `inspection.to_composed_config()` without changing metadata.

Result `to_dict()` methods should be plain-data-safe and include argv metadata, warnings, selected record `to_dict()` payloads, and a serialized config or inspection payload using existing `to_dict()` methods on nested config artifact/provenance/fingerprint records where available. If a complete serialized `ComposedConfig` would require a broad new serialization contract, stop and narrow `to_dict()` to argv metadata plus documented `resolved`/`redacted` payloads rather than inventing new artifact serialization semantics.

### Warning Record Shape And Behavior

`ConfigArgvWarning` should include `code`, `message`, `source_order`, `token`, `path`, `remediation`, and `details`. `details` must be plain data. `source_order` should use the argv token order when a warning maps to a token and `-1` only for whole-result warnings.

Required warning behavior is conservative and helper-local:

- Warn when a no-slash value override targets an existing mapping and the RHS is a scalar string that looks like a likely scoped-overlay selector, such as a relative stem that resolves near the target scope or base config directory.
- Do not warn for ordinary scalar overrides, numeric/boolean/null/object/array override values, explicit path-like value strings that do not resolve as overlay candidates, or tokens already using trailing-slash scoped overlay syntax.
- Warning codes should be stable and contract-tested; a reasonable initial code is `possible_missing_scoped_overlay_slash`.
- Warnings must live only on `ConfigArgvCompositionResult` and `ConfigArgvInspectionResult`. They must not be written into `ComposedConfig`, `ConfigCompositionInspection`, manifests, provenance, source artifacts, raw source snapshots, fingerprint records, artifact-safe fingerprint facts, or run artifacts.
- Warnings must not downgrade, catch, or replace structured errors for malformed argv, missing overlay files, non-mapping overlays, or invalid scoped targets.

### Structured Error Expectations

Error behavior must stay config-owned and structured. Malformed argv, invalid argv value types, invalid `command_choices`, unknown commands, missing command/base path, invalid value overrides, unsupported root overlays, missing overlay sources, non-mapping overlay sources, invalid scoped targets, and disallowed unparsed args should raise existing config error types with machine-readable `ConfigErrorContext` details. This phase may improve public helper context, but it must not replace structured errors with printing, exiting, `argparse` exceptions, or unstructured `ValueError`/`RuntimeError` failures.

Public-helper contract tests should assert context fields that matter for callers: `code`, `source_kind`, `source_order`, `source_path`, `directive`, `remediation`, and plain-data `details` such as command, token, scope path, RHS, candidate paths, unparsed args, resolved path, and config path when available. Error wrapping must preserve the original context code unless the wrapper adds strictly more specific argv-helper context without losing the underlying cause.

### Inspection Contract

`inspect_config_from_argv(...)` must use the argv-specific inspection path so the `argv_scoped_overlays` stage appears after `file_include_expansion` and before `recipe_argument_interpolation`/`recipe_expansion`. The stage should appear even when no scoped overlays are supplied through the argv helper. Existing `inspect_config_composition(...)` must retain its current stage tuple and output for non-argv callers.

## Design Impact

- Maintainability: keep argv adaptation in `weave.api` wrappers over the existing parser and private composition path instead of adding a separate CLI framework or duplicate composition route.
- Extensibility: expose the primary helper top-level and keep detailed types in `weave.api`, preserving room to evolve docs and future CLI adapters without making every record a top-level package name.
- Domain neutrality: examples and tests must use generic config trees and command names such as `run`, `train`, or `inspect` without Loom runtime, scheduler, store, model-training, or deployment assumptions.
- Source-tree boundaries: product code changes stay in `packages/weave`; docs change is limited to `docs/features/config.md`; no workflow, prompt, template, or Loom CLI files are phase-owned.

## Future Compatibility

- Future Loom CLI or project CLI adapters can call the public helpers and decide how to display warnings/errors without `weave` owning command execution.
- Future persisted argv audit artifacts remain possible because warnings are deliberately helper-local in this phase.
- Future Hydra bridge work remains separate because no defaults lists, global config groups, or RHS inference are introduced.
- Future artifact schema changes remain separate because scoped overlays continue to use overlay-family source artifacts and metadata from Phase 2.
- Future top-level API expansion should require a recorded review decision; this phase should not make inspection helpers or detailed records top-level names by accident.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add a first-party `weave` CLI or argparse integration | Stage 24 targets reusable project-specific CLI helpers, not executable ownership or display/exit policy. |
| Return bare `ComposedConfig` from `compose_config_from_argv(...)` | Callers need parsed argv records, unparsed args, and warnings as structured result data. |
| Export every argv record at the top level | The implementation plan requires a narrow top-level surface; detailed records belong in `weave.api`. |
| Persist warnings into composition artifacts | The user selected helper-local warnings to keep normal composition artifacts argv-agnostic. |
| Treat `model=model_B` as an overlay by inference | No-slash tokens are value overrides; warnings may suggest the trailing-slash form without changing behavior. |
| Add a new source artifact kind for scoped overlays | Phase 2 already proved overlay-family artifacts with metadata; schema changes are out of scope. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Public result and warning record fields become API surface through `weave.api` | Project CLI authors need stable typed data for composition, inspection, and diagnostics | User feedback or contract tests show fields are too broad, noisy, or hard to evolve |
| Warning heuristics may miss some mistaken no-slash overlays | Conservative warnings avoid false positives for legitimate path-like value overrides | Users repeatedly miss trailing slash or docs/tests identify a low-noise additional heuristic |

## Reviewability

- Expected PR size and shape: medium public API and docs PR with small wrappers, record dataclasses, warning helper logic, import/export updates, docs edits, and focused tests.
- Files and areas to inspect: `packages/weave/src/weave/api.py`, `packages/weave/src/weave/__init__.py`, `packages/weave/src/weave/_argv.py` only as needed for public exports or warning support, `packages/weave/src/weave/compose.py` only if the public inspection wrapper needs minor private-helper access, package-local tests, `tests/e2e/test_config_composition_public_api.py`, and `docs/features/config.md`.
- Scope-control checks: no `loom` imports in `weave`, no first-party CLI files, no new dependency, no persisted warning fields, no new source artifact kind/schema change, no broad docs rewrite, and no changed non-argv compose/inspection behavior.

## Implementation Steps

1. Define `ConfigArgvCompositionResult`, `ConfigArgvInspectionResult`, and `ConfigArgvWarning` in `weave.api`; re-export the selected detailed argv records through `weave.api`; add import-surface tests before broad behavior changes.
2. Add `compose_config_from_argv(...)` and `inspect_config_from_argv(...)` wrappers over `parse_config_argv(...)` and the existing public/private composition paths, including `argv=None`, command choices, `allow_unparsed`, recipe catalog, raw snapshot handling, and default-catalog behavior matching existing public compose helpers.
3. Add helper-local warning generation after composition or inspection has enough target-shape and candidate-path context; keep warning creation side-effect-free and artifact-free.
4. Add public-helper integration and e2e coverage for documented value overrides, scoped overlays, ordering, unparsed args, inspection stage exposure, structured errors, raw snapshots, and no-change guarantees for direct non-argv callers.
5. Update only `docs/features/config.md` to document the implemented helper API, examples, warnings/errors, inspection/audit behavior, and explicit deferrals.
6. Run targeted suite validation during implementation and leave final `make validate-pr` and `make test-summary` evidence for PR preparation.

## Documentation Scope

- Phase implementation may edit only `docs/features/config.md` among user-facing docs, plus tests/examples that directly validate the documented helper behavior. This planning pass intentionally edits only this phase execution plan.
- Replace future-facing CLI text where it conflicts with Stage 24 by documenting Python helper usage for project-specific CLIs, not a first-party command.
- Required docs content: `compose_config_from_argv(...)`, `inspect_config_from_argv(...)`, command/base argv shape, no-slash value override syntax, trailing-slash scoped overlay syntax, `+scope/=` add semantics, scope-directory then base-directory lookup, `.yaml` before `.yml`, exact absolute paths, no `~` expansion, ordering relative to recipes and value overrides, helper-local warnings, structured errors, inspection stage, source/audit behavior, and explicit deferrals.
- Docs must not promise `loom validate`, `loom plan`, `loom run`, a `weave` executable, Hydra config groups/defaults lists, RHS overlay inference, persisted warnings, or execution/store behavior.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `packages/weave/tests/test_import.py`, package build/import checks through `make validate-pr`.
- Required assertions or deferral reason: top-level `weave` exposes `compose_config_from_argv` and no other new argv names; `weave.api` exposes `compose_config_from_argv`, `inspect_config_from_argv`, result/warning types, and selected detailed records; importing `weave` still does not import `loom`.

### Unit Suite

- Status: required
- Expected paths: `packages/weave/tests/unit/config/test_argv.py` plus a focused new or existing unit test path for public argv result/warning validation.
- Required assertions or deferral reason: result and warning records validate plain-data fields and `to_dict()` output; `argv=None` normalization can be tested without leaking global state; warning helper produces conservative warnings for no-slash mapping replacement/overlay-like RHS and no warning for ordinary path-like value strings.

### Contract Suite

- Status: required
- Expected paths: `packages/weave/tests/contracts/test_config_error_contract.py`, `packages/weave/tests/contracts/test_config_composition_inspection_contract.py`, `packages/weave/tests/contracts/test_config_artifact_contract.py`.
- Required assertions or deferral reason: public helper errors preserve structured `ConfigErrorContext`; `inspect_config_from_argv(...)` exposes `argv_scoped_overlays` at the required position; non-argv `inspect_config_composition(...)` stages remain unchanged; source artifacts remain overlay-family records with Phase 2 metadata and no persisted warning fields.

### Integration Suite

- Status: required
- Expected paths: new `packages/weave/tests/integration/config/test_compose_argv_from_cli.py`, existing `packages/weave/tests/integration/config/test_compose_argv_scoped_overlays.py`, `packages/weave/tests/integration/config/test_compose_overrides.py`, and `packages/weave/tests/integration/config/test_compose_recipes.py` as regressions.
- Required assertions or deferral reason: public compose helper handles documented examples such as `data/=data_A`, `model/=model_B`, `model/pipeline/=pipeline_A`, `+runtime/=local`, value overrides, unparsed args, absolute scoped overlay paths, missing overlays, non-mapping overlays, invalid targets, and recipe/order behavior where value overrides win after recipes.

### E2E Suite

- Status: required for public Python API behavior; CLI/process e2e deferred
- Expected paths: `tests/e2e/test_config_composition_public_api.py`.
- Required assertions or deferral reason: add or extend public API e2e coverage showing a project-style argv sequence composes and inspects config through public Python APIs, including result metadata and warnings. First-party executable or Loom CLI e2e is deferred because it is explicitly out of scope.

### Opt-In Suites

- Status: required for affected opt-in config behavior; otherwise deferred
- Markers affected: raw source snapshot opt-in, existing optional dependency/config-extra coverage, docs/example checks if docs examples are executable.
- Required assertions or deferral reason: public argv helpers must preserve raw source snapshot opt-in behavior for scoped overlays; final `make validate-pr` must cover existing optional dependency/config-extra gates. No new live, scheduler, network, or external-service opt-in suite applies.

## Risks And Stop Conditions

Risks:

- Public result or warning fields could expose too much long-lived surface.
- Warning heuristics could become noisy and undermine the intentionally explicit trailing-slash grammar.
- Top-level lazy export changes could accidentally broaden public API or import `loom`.
- Public inspection wrapper could accidentally change non-argv inspection stage contracts.
- Docs could imply a first-party CLI or Loom CLI support that this phase does not ship.

Stop conditions for implementation:

- A needed public API shape is broader than `compose_config_from_argv` top-level plus `weave.api` inspection/result/record exports recorded here.
- Warning generation requires mutation of `ComposedConfig`, `ConfigCompositionInspection`, manifests, provenance, source artifacts, raw snapshots, fingerprints, or persisted run artifacts.
- Correct implementation requires a new source artifact kind, artifact schema version, manifest schema change, or migration.
- Correct implementation requires `weave` to import `loom`, add a first-party executable/argparse parser, or change Loom CLI behavior.
- Existing direct `compose_config(...)`, `compose_config_with_catalog(...)`, or `inspect_config_composition(...)` behavior or non-argv inspection stage order would need to change.
- Docs cannot accurately describe the shipped helper without promising future-phase features.
- Result serialization needs a broad new `ComposedConfig` or `ConfigCompositionInspection` serialization contract not already implied by existing nested `to_dict()` methods.

## Validation Commands

Targeted development commands:

```sh
uv run pytest packages/weave/tests/test_import.py packages/weave/tests/contracts/test_config_error_contract.py
uv run pytest packages/weave/tests/unit/config/test_argv.py
uv run pytest packages/weave/tests/integration/config/test_compose_argv_from_cli.py
uv run pytest packages/weave/tests/contracts/test_config_composition_inspection_contract.py packages/weave/tests/contracts/test_config_artifact_contract.py
uv run pytest packages/weave/tests/integration/config/test_compose_argv_scoped_overlays.py packages/weave/tests/integration/config/test_compose_overrides.py packages/weave/tests/integration/config/test_compose_recipes.py
uv run pytest tests/e2e/test_config_composition_public_api.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: public record/import boundary first, helper wrappers second, warning generation third, public integration/e2e tests fourth, docs last.
- Tests to run with each slice: run `packages/weave/tests/test_import.py` after export changes; run unit warning tests after warning logic; run the new public helper integration test after wrappers; run inspection/artifact contracts after inspection exposure; run the e2e and docs/example checks after docs updates.
- Decisions the executor must not revisit: top-level export is only `compose_config_from_argv`; `inspect_config_from_argv` and detailed records stay in `weave.api`; warnings stay helper-local; no first-party CLI, Loom CLI adapter, source artifact kind, schema change, or persisted warnings.
- Conditions that require stopping for the manager: public API shape needs more top-level exports; warning generation requires artifact mutation; non-argv composition/inspection behavior must change; implementation needs Loom imports or executable CLI work; docs cannot describe behavior without promising future-phase features.
- Expanded-path refinement notes: refine pass used; public record names, warning schema, docs scope, suite obligations, and stop conditions are confirmed for implementation.

## Refinement And Review Budget Status

- Phase planning refinement: draft completed; expanded-path plan refine used
- Phase implementation refinement: used
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed with `plan: add phase 3 execution plan`.
- Final phase execution plan: completed by expanded-path refine pass.
- Implementation summary: Public argv helpers are implemented. `compose_config_from_argv(...)` is the only new top-level export; `inspect_config_from_argv(...)`, `ConfigArgvCompositionResult`, `ConfigArgvInspectionResult`, `ConfigArgvWarning`, and selected parsed argv record types are exposed through `weave.api`. Helpers wrap the private parser and scoped-overlay composition path, support `argv=None`, command choices, `allow_unparsed`, recipe catalogs, raw snapshot opt-in, helper-local warnings, and structured error propagation. `docs/features/config.md` documents the shipped helper behavior and deferrals.
- Implementation validation: `uv run pytest packages/weave/tests/test_import.py packages/weave/tests/contracts/test_config_error_contract.py` passed (13 tests); `uv run pytest packages/weave/tests/unit/config/test_argv.py` passed (21 tests); `uv run pytest packages/weave/tests/integration/config/test_compose_argv_from_cli.py` passed (6 tests); `uv run pytest packages/weave/tests/contracts/test_config_composition_inspection_contract.py packages/weave/tests/contracts/test_config_artifact_contract.py` passed (18 tests); `PYTHONPATH=packages/weave uv run pytest packages/weave/tests/integration/config/test_compose_argv_scoped_overlays.py packages/weave/tests/integration/config/test_compose_overrides.py packages/weave/tests/integration/config/test_compose_recipes.py` passed (26 tests); `uv run pytest tests/e2e/test_config_composition_public_api.py` passed (2 tests); focused Ruff passed; focused Pyright reported 0 errors.
- Implementation refinement summary: preserved parser-owned structured validation for single-string `argv` inputs in the public wrapper and added coverage for `argv=None` normalization through `sys.argv[1:]`. No public API breadth, warning persistence, CLI behavior, source artifact schema, or Loom CLI scope changed.
- Implementation refinement validation: `uv run pytest packages/weave/tests/contracts/test_config_error_contract.py packages/weave/tests/integration/config/test_compose_argv_from_cli.py` passed (18 tests); `uv run pytest packages/weave/tests/test_import.py packages/weave/tests/unit/config/test_argv.py` passed (24 tests); `uv run pytest tests/e2e/test_config_composition_public_api.py` passed (2 tests); `uv run ruff check packages/weave/src/weave/api.py packages/weave/tests/contracts/test_config_error_contract.py packages/weave/tests/integration/config/test_compose_argv_from_cli.py` passed; `uv run pyright packages/weave/src/weave/api.py packages/weave/tests/contracts/test_config_error_contract.py packages/weave/tests/integration/config/test_compose_argv_from_cli.py` reported 0 errors.
- Blocker-resolution summary: not used
- PR preparation: completed; PR body drafted at `docs/roadmap/stage-24/phases/weave-argv-api-inspection-pr-body.md` and PR opened at https://github.com/samcantrill/loom/pull/208
- PR preparation validation: `make validate-pr` passed fully with Ruff, Pyright, default pytest, config-extra, weave, weave examples, and builds passing; observed rows included default `1983 passed, 108 deselected`, config-extra `128 passed, 3 skipped, 1986 deselected`, weave `415 passed`, and weave examples `8 passed`. `make test-summary` passed and wrote `build/test-summary.md` with overall `2534 passed, 0 failed, 0 errors, 3 skipped, 2088 deselected, 2537 total, 321.14s`.
- PR facts: #208, https://github.com/samcantrill/loom/pull/208, base `develop`, head `codex/weave-argv-api-inspection`, state `OPEN`, title `Weave Argv Config Shorthand - Phase 3: Public Argv API and Inspection`; verified with `gh pr view 208 --json baseRefName,headRefName,state,url` returning base `develop`, head `codex/weave-argv-api-inspection`, state `OPEN`.
- Stack maintenance: fallback worktree path recorded; no predecessor retarget/rebase needed
- Remaining blockers: none recorded after implementation refinement
