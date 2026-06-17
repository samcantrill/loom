# Phase 3 Execution Plan: Public Argv API, Inspection, Diagnostics, And Docs

## Metadata

- Status: draft phase execution plan
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
- Refine pass: pending because this phase changes public API, diagnostics, docs, and end-to-end behavior
- Setup limitations: configured root `/home/samcantrill/work/loom-worktrees` was unavailable in this session, so the fallback root `/nas/home/can134/work/loom-worktrees` was used
- Blockers: expanded-path refine pass must complete before implementation handoff

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
  - `packages/weave/src/weave/_argv.py` defines private parser records and `parse_config_argv(...)`.
  - `packages/weave/src/weave/compose.py` defines private `_inspect_config_composition_with_argv_scoped_overlays(...)` and keeps public non-argv inspection unchanged.
  - `packages/weave/src/weave/api.py` owns public config dataclasses and wrapper validation.
  - `packages/weave/src/weave/__init__.py` uses lazy top-level exports; this phase should add only `compose_config_from_argv` there.
  - `docs/features/config.md` still frames CLI behavior as future-facing and must be updated in the phase worktree, not in the dirty control checkout.
- Existing tests or harness behavior:
  - `packages/weave/tests/unit/config/test_argv.py` covers parser records, lookup rules, unparsed args, root overlay rejection, and parser diagnostics.
  - `packages/weave/tests/integration/config/test_compose_argv_scoped_overlays.py` covers private scoped-overlay composition, order, provenance, artifact metadata, raw snapshots, and structured target/load errors.
  - `packages/weave/tests/contracts/test_config_composition_inspection_contract.py` anchors public non-argv inspection stages.
  - `tests/e2e/test_config_composition_public_api.py` is the public Python API e2e anchor for composition behavior.
- Import-boundary or dependency constraints:
  - `weave` must not import `loom`.
  - No new runtime dependency is expected.
  - Authored configs remain trusted project code.
  - Warnings are helper-result data only and must not affect artifact-safe fingerprints.

## In-Scope Work

- Add `compose_config_from_argv(...)` as the only new top-level `weave` export for this phase.
- Add `inspect_config_from_argv(...)` through `weave.api`; do not add it to top-level `weave.__all__` unless a separate plan review accepts broader public surface.
- Add public result and warning dataclasses through `weave.api` with plain-data-safe `to_dict()` behavior and validation aligned with existing API records.
- Re-export detailed argv records through `weave.api` as needed for callers to inspect parsed value overrides, scoped overlays, scoped overlay candidates, and unparsed command args.
- Compose helper behavior: parse `argv` defaulting to `sys.argv[1:]`, validate caller-supplied command choices, pass value override strings and scoped overlay records to existing composition machinery, and return command/base path/records/unparsed args/warnings plus the composed config.
- Inspection helper behavior: use the same parse and composition path, return the same argv metadata/warnings plus `ConfigCompositionInspection`, and expose the `argv_scoped_overlays` stage even when there are no scoped overlays if the private argv inspection path already does so.
- Generate conservative non-fatal warnings for likely overlay mistakes after enough target-shape context is available, especially no-slash mapping replacement where the RHS looks like an overlay selector. Warnings must never change the composed config or persisted artifacts.
- Preserve all existing direct `compose_config(...)`, `compose_config_with_catalog(...)`, and `inspect_config_composition(...)` public behavior for non-argv callers.
- Update `docs/features/config.md` to document the implemented argv helper, trailing-slash overlay syntax, lookup rules, ordering, warnings, structured errors, inspection, audit behavior, and explicit deferrals.
- Add package-local and public Python API tests required by the suite plan.

## Out-of-Scope Work

- First-party `weave` executable, console script, argparse parser, or process exit/display policy.
- Loom CLI adapter work or any `loom.cli` parser changes.
- Runtime execution, pipeline planning, stores, schedulers, events, downstream operations, or run persistence.
- Persisting argv warnings into `ComposedConfig`, manifests, provenance, source artifacts, raw source snapshots, fingerprints, or run artifacts.
- New `SourceArtifactRecord.kind`, artifact schema version, manifest schema change, or source artifact migration.
- Hydra/defaults/config-group behavior, RHS overlay inference, escaped dot-path grammar, advanced list patching, or untrusted-config sandboxing.
- Broad docs rewrites outside the Stage 24 config feature section and directly related examples.

## Assumptions

- The public result names may be finalized during the refine pass, but they should be narrow and config-owned; a reasonable default is `ConfigArgvCompositionResult`, `ConfigArgvInspectionResult`, and `ConfigArgvWarning`.
- Existing internal `ArgvValueOverride`, `ArgvScopedOverlay`, `ScopedOverlayCandidate`, `ArgvUnparsedArg`, and `ParsedConfigArgv` records are suitable to expose through `weave.api` unless refinement finds a stronger naming or stability reason to wrap them.
- `command_choices` remains caller-provided and command-name agnostic; `weave` does not hard-code commands.
- Warning heuristics should prefer false negatives over noisy or surprising warnings.
- Docs updates in the phase worktree may edit `docs/features/config.md`; unrelated local modifications in the control checkout must remain untouched.

## Scope Contract

Public helper shape is phase-owned. `compose_config_from_argv(...)` should be discoverable as `weave.compose_config_from_argv` and available from `weave.api`. It should accept an argv-like sequence or `None` for `sys.argv[1:]`, caller command choices, `allow_unparsed`, optional `RecipeCatalog`, and the existing raw-source-snapshot option. It should return a result record, not a bare `ComposedConfig`, so callers receive the composed config alongside command, base config path, parsed value overrides, scoped overlays, unparsed args, and warnings.

`inspect_config_from_argv(...)` should be available from `weave.api` and return the inspection counterpart result with the same argv metadata and warnings plus `ConfigCompositionInspection`. It must use the argv-specific inspection path so the `argv_scoped_overlays` stage appears after `file_include_expansion` and before recipe interpolation/expansion. Existing `inspect_config_composition(...)` must retain its current stage tuple and output for non-argv callers.

Public records must be plain-data-safe and stable enough for project-specific CLI authors. Warning records should include a stable code, message, source order or token context, and plain-data details/remediation where useful. Detailed parser/composition records exposed through `weave.api` should remain data records, not CLI framework objects. Top-level exports must stay limited to the main compose helper plus existing names.

Error behavior must stay config-owned and structured. Malformed argv, unknown commands, missing command/base path, invalid value overrides, unsupported root overlays, missing overlay files, non-mapping overlay sources, invalid scoped targets, and disallowed unparsed args should raise existing config error types with machine-readable `ConfigErrorContext` details. This phase may improve public helper context, but it must not replace structured errors with printing, exiting, or argparse exceptions.

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

1. Define the public result/warning API in `weave.api`, re-export the selected detailed argv records through `weave.api`, and add import-surface tests before broad behavior changes.
2. Add `compose_config_from_argv(...)` and `inspect_config_from_argv(...)` wrappers over `parse_config_argv(...)` and the existing public/private composition paths, including `argv=None`, command choices, `allow_unparsed`, recipe catalog, and raw snapshot handling.
3. Add helper-local warning generation with conservative target-shape/context checks, ensuring warnings live only on result records and are omitted from all composition artifacts.
4. Add public-helper integration and e2e coverage for documented value overrides, scoped overlays, ordering, unparsed args, inspection stage exposure, structured errors, raw snapshots, and no-change guarantees for direct non-argv callers.
5. Update `docs/features/config.md` to document the implemented helper API, examples, warnings/errors, inspection/audit behavior, and explicit deferrals.
6. Run targeted suite validation and leave final `make validate-pr` and `make test-summary` evidence for PR preparation.

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

## Risks

- Public result or warning fields could expose too much long-lived surface.
- Warning heuristics could become noisy and undermine the intentionally explicit trailing-slash grammar.
- Top-level lazy export changes could accidentally broaden public API or import `loom`.
- Public inspection wrapper could accidentally change non-argv inspection stage contracts.
- Docs could imply a first-party CLI or Loom CLI support that this phase does not ship.
- Stop if implementation needs a new source artifact kind, persisted warning artifact, Loom CLI import, first-party executable, changed non-argv compose/inspection behavior, or broader public API than recorded here.

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
- Expanded-path refinement notes: refine pass is pending and should confirm public record names, warning schema, docs scope, and suite obligations before implementation starts.

## Refinement And Review Budget Status

- Phase planning refinement: draft completed; expanded-path refine pass pending
- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed with `plan: add phase 3 execution plan`.
- Final phase execution plan: pending expanded-path refine pass.
- Implementation summary: pending
- Implementation validation: pending
- Refinement summary: pending
- Blocker-resolution summary: pending
- PR preparation: pending
- Stack maintenance: fallback worktree path recorded; no predecessor retarget/rebase needed
- Remaining blockers: expanded-path refine pass must complete before implementation handoff
