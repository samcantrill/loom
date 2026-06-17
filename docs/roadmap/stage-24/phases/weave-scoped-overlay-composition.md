# Phase 2 Execution Plan: Scoped Overlay Composition

## Metadata

- Status: refined phase execution plan
- Feature focus: Weave Argv Config Shorthand
- PR title: `Weave Argv Config Shorthand - Phase 2: Scoped Overlay Composition`
- Branch: `codex/weave-scoped-overlay-composition`
- Worktree: `/nas/home/can134/work/loom-worktrees/weave-scoped-overlay-composition`
- Phase execution plan path: `docs/roadmap/stage-24/phases/weave-scoped-overlay-composition.md`
- Full plan: `docs/roadmap/stage-24/implementation-plan.md`
- Source phase: Phase 2, `weave-scoped-overlay-composition`
- Stack predecessor: none; Phase 1 merged into `develop`
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: merge eligible when the PR targets `develop`, automated review passes, and validation/CI pass
- Workflow path: expanded path
- Successor dependency notes: Phase 3 may stack on this branch only if this PR is open/prepared and cannot merge immediately; otherwise Phase 3 should branch from updated `develop` after Phase 2 merges.
- Plan quality gate: implementation-plan quality gate passed and is recorded in the full plan
- Plan quality gate loop budget: consumed upstream; review, refinement, and confirmation completed with no blocking findings remaining
- Draft pass: completed by `loom_phase_planner`
- Refine pass: completed by `loom_phase_planner`
- Setup limitations: configured root `/home/samcantrill/work/loom-worktrees` was unavailable in this session, so the fallback root `/nas/home/can134/work/loom-worktrees` was used.
- Blockers: none for implementation handoff.

## Objective

Integrate Phase 1 scoped overlay records into private config composition plumbing so argv-scoped overlays load, merge, and audit like authored overlay-family sources at the confirmed insertion point, while preserving source/provenance records, manifests, raw snapshot references where applicable, artifact-safe fingerprints, and all existing public non-argv composition behavior.

## Full-Plan Context

Phase 1 added private argv parsing records in `weave._argv`, including resolved `ArgvScopedOverlay` records and value override records, without changing composition. Phase 2 consumes those private records through internal composition plumbing only. Phase 3 remains responsible for public `compose_config_from_argv(...)`, public `inspect_config_from_argv(...)`, `weave.api` export changes, warnings, first-party docs updates, and end-to-end public helper behavior.

This phase must keep direct public `compose_config(...)` and `inspect_config_composition(...)` signatures unchanged and must not change their non-argv output shape, stage names, stage order, source artifacts, manifests, provenance, or fingerprints except for behavior already covered by existing direct-call inputs. It may add internal helpers or private parameters used by later public wrappers, but those helpers are not public API and must not be exported.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: Phase 1 merged via PR #206, and `develop` includes post-merge metadata commit `8006929 docs: record stage 24 phase 1 merge`.
- Retarget/rebase plan after predecessor merge: none needed for this root PR.
- Branch cleanup constraints: the branch can be deleted after merge only if no Phase 3 successor branch is stacked on it.

## Source Phase Summary

- Goal: apply scoped overlay requests at the confirmed point in config composition with full auditability.
- Required scope: load scoped overlay YAML as mappings; apply normal recursive merge semantics at non-root scope targets; enforce update/add target rules; insert internal `argv_scoped_overlays` inspection stage; record overlay-family source artifacts and fingerprint facts; preserve raw snapshot references when snapshot capture is enabled.
- Required checkpoints: direct non-argv composition signatures and output contracts unchanged; scoped overlay values have correct final authorship; manifest, provenance metadata, source artifacts, raw snapshot references, and artifact-safe fingerprint metadata include scoped overlay facts.
- Acceptance criteria: integration, unit, contract, and regression tests prove merge order, provenance, fingerprint, artifact, inspection, recipe/order, and override behavior required by the implementation plan.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `packages/weave/src/weave/_argv.py` defines `ArgvScopedOverlay` with `raw`, `scope_path`, `operation`, `rhs`, `candidates`, `resolved_path`, and `order`.
  - `packages/weave/src/weave/compose.py` owns composition stage orchestration, source artifacts, provenance metadata, raw snapshot bundles, and artifact-safe fingerprint record construction.
  - `packages/weave/src/weave/source_maps.py` already tracks source-aware recursive overlay merges, `_replace_: true`, mapping sites, replacement sites, and final source maps.
  - `packages/weave/src/weave/artifacts.py` allows `SourceArtifactRecord.kind` values `base`, `overlay`, `include`, and `recipe`; `overlay` can carry scoped overlay metadata without a schema change.
  - `packages/weave/src/weave/fingerprints.py` builds artifact-safe fingerprint facts from source artifacts while avoiding raw source bytes and runtime resolver outputs; scoped overlay additions must preserve that artifact-safe boundary.
  - `packages/weave/src/weave/load.py` loads base/overlay YAML, returns `ConfigSource`, and can capture source text for raw snapshot opt-in behavior.
- Existing tests or harness behavior:
  - `packages/weave/tests/unit/config/test_argv.py` covers Phase 1 parser records and resolution rules.
  - `packages/weave/tests/contracts/test_config_composition_inspection_contract.py` asserts the current public non-argv inspection stage tuple.
  - Existing provenance, artifact, fingerprint, raw snapshot, recipe, and override tests provide regression anchors for this phase.
- Import-boundary or dependency constraints:
  - `weave` must not import `loom`.
  - No heavyweight runtime dependency is needed.
  - Public `compose_config(...)`, `inspect_config_composition(...)`, top-level exports, and `weave.api` exports are not phase-owned.

## In-Scope Work

- Add private composition plumbing that can accept Phase 1 `ArgvScopedOverlay` records without changing public `compose_config(...)` or `inspect_config_composition(...)` signatures or non-argv output.
- Load resolved scoped overlay files through existing config load/source mechanisms with `kind="overlay"` and deterministic source ordering.
- Apply scoped overlays after explicit overlays and file-authored include expansion, and before recipe argument interpolation and recipe expansion.
- Merge overlay mapping content at the requested non-root scope using existing recursive merge semantics, including `_replace_: true`.
- Enforce scoped overlay update/add rules: `scope/=` requires an existing target but may replace an existing leaf with a mapping; `+scope/=` creates missing scopes and must not overwrite an existing target.
- Record scoped overlay sources as overlay-family artifacts with metadata for authored token, scope path, operation, RHS, candidates, resolved path, order, and insertion stage.
- Preserve final value authorship, manifest metadata, provenance metadata, raw snapshot references, and artifact-safe fingerprint facts for values introduced or changed by scoped overlays.
- Add internal inspection plumbing for an argv-path-only stage named `argv_scoped_overlays` immediately after `file_include_expansion`; tests may use a private helper but must not require exporting `inspect_config_from_argv(...)`.
- Add focused package-local tests required by the suite plan.

## Out-of-Scope Work

- Public `compose_config_from_argv(...)`.
- Public `inspect_config_from_argv(...)`.
- New `weave.api` or top-level export changes for argv composition.
- Any Phase 3 public helper, result record, warning record, or API naming decision.
- Warning UX for likely overlay mistakes.
- First-party `weave` CLI integration or Loom CLI integration.
- `docs/features/config.md` or `docs/roadmap.md` updates.
- Hydra/defaults/config-group behavior, RHS inference, escaped dot-path grammar, advanced list patching, or runtime execution behavior.
- New persisted `SourceArtifactRecord.kind`, `SourceArtifactRecord.kind` enum changes, or manifest schema version changes; if any appears necessary, stop for manager review before implementation continues.

## Assumptions

- Phase 1 parser records are the only input contract this phase needs for scoped overlays.
- Existing `load_config(_with_source_text)` can load scoped overlay files as ordinary overlay sources; non-mapping roots should surface structured config load context with scoped overlay metadata added by the caller where needed.
- Overlay-family source artifacts with explicit metadata are sufficient for auditability and fingerprinting in this phase without changing the public source artifact kind enum.
- The executor may choose the smallest private helper shape that keeps direct public composition APIs unchanged and lets Phase 3 wrap it. Any suggested helper name is internal-only.

## Scope Contract

No public API changes are in scope. Direct public `compose_config(...)` and `inspect_config_composition(...)` signatures and non-argv outputs must remain unchanged. The internal contract is: a sequence of already-resolved `ArgvScopedOverlay` records can be provided to private composition plumbing; each record has a non-empty scope path, operation `update` or `add`, and a resolved file path. The composition must treat those records as trusted authored config input, load their YAML as mappings, and apply them only at the requested scope.

Error behavior must remain structured. Missing source resolution stays parser-owned from Phase 1. This phase must add structured context for load failures, non-mapping overlay roots, missing update targets, existing add targets, invalid non-mapping intermediate targets, and invalid `_replace_` usage at scoped targets. Context should include token/order/scope metadata without exposing a public warning or helper result.

The public non-argv inspection contract must not change. The argv-path-only inspection path must include `argv_scoped_overlays` after `file_include_expansion` and before recipe argument interpolation/expansion, but this phase may test that through private/internal helpers only. Public exposure waits for Phase 3.

## Design Impact

- Maintainability: keep scoped overlay composition inside existing `weave` composition/source/provenance helpers, and avoid a parallel wrapper-YAML implementation.
- Extensibility: use private plumbing that Phase 3 can wrap, while preserving room for a future schema-versioned source kind only if metadata proves insufficient.
- Domain neutrality: fixtures and metadata should describe generic config scopes and source files, not Loom runtime, training, stores, schedulers, or domain workflows.
- Source-tree boundaries: changes stay in `packages/weave` source and tests; no Loom CLI, docs feature copy, or workflow files are phase-owned.

## Future Compatibility

- Future Phase 3 helpers should be able to call the internal composition path without reimplementing merge/provenance/fingerprint logic or changing the already-tested private contracts.
- Existing artifact-safe fingerprint policy must remain path-portable and must not include raw source bytes or resolved runtime values. Absolute resolved paths may remain in source artifact records as they do today, but scoped overlay additions must not introduce raw bytes or runtime outputs into artifact-safe fingerprint payloads.
- Metadata keys for scoped overlays should be plain-data and stable enough for Phase 3 docs, but not treated as new public schema unless a later compatibility decision records that.
- Any need for a new public source artifact kind enum value, manifest schema version, or changed non-argv inspection stage tuple is a stop condition.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Expose `compose_config_from_argv(...)` in this phase | Public helper ownership belongs to Phase 3 after composition internals and inspection contracts are proven. |
| Add a new persisted `SourceArtifactRecord.kind` for scoped overlays | The implementation plan defaults to `kind="overlay"` metadata to avoid schema churn; a new kind requires manager review. |
| Generate temporary wrapper YAML files for scoped overlays | It hides authored token/candidate metadata and complicates raw snapshot/fingerprint auditability. |
| Change `compose_config(...)` or `inspect_config_composition(...)` public signatures or non-argv output | Direct callers must see no behavior change; Phase 2 is internal composition plumbing. |
| Implement warning heuristics while composing scoped overlays | Warning UX and helper-local result records are Phase 3 scope. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| None planned | The phase can use existing overlay artifacts with explicit metadata and private helpers. | Revisit if implementation cannot represent scoped overlay facts artifact-safely without schema changes. |

## Reviewability

- Expected PR size and shape: medium `packages/weave` PR with private composition/inspection plumbing, scoped merge/source-map support, artifact/fingerprint metadata additions, and focused tests.
- Files and areas to inspect: `packages/weave/src/weave/compose.py`, `load.py`, `source_maps.py`, `provenance.py`, `artifacts.py`, `fingerprints.py`, `_argv.py` only as needed, plus package-local unit, integration, and contract tests.
- Scope-control checks: no public argv helper/export, no docs/features edits, no Loom CLI imports, no new artifact kind or manifest schema version, no changed non-argv inspection stage tuple/output, no broad rewrite of recipe/include/override behavior.

## Implementation Steps

1. Add private composition input/plumbing for scoped overlay records and thread it through the existing composition orchestration without changing public compose or inspect signatures or non-argv output.
2. Load scoped overlay sources with existing overlay load/source text paths, preserve raw source text when requested, and attach scoped overlay metadata to source records.
3. Apply scoped overlays at the post-include, pre-recipe insertion point using source-aware recursive merge behavior and explicit add/update target validation.
4. Extend final value authorship, source artifact metadata, provenance/manifest metadata, raw snapshot references, and artifact-safe fingerprint facts for scoped overlay sources and values.
5. Add internal `argv_scoped_overlays` inspection stage support for the private argv path, using a private helper if needed for tests, while keeping public non-argv inspection stages unchanged.
6. Add focused tests and run targeted validation before final PR-preparation gates.

## Test Plan

### Package Suite

- Status: deferred for targeted package-level changes; required through final `make validate-pr`.
- Expected paths: `packages/weave/tests/test_import.py` only if implementation touches `weave/api.py` or `weave/__init__.py`, which is out of scope.
- Required assertions or deferral reason: no public import surface should change in Phase 2; final build/import checks still run before PR preparation.

### Unit Suite

- Status: required
- Expected paths: `packages/weave/tests/unit/config/test_config_provenance.py`, `packages/weave/tests/unit/config/test_config_fingerprints.py`, `packages/weave/tests/unit/config/test_config_artifacts.py`, and focused new or existing unit tests for scoped target validation/source-map merge behavior.
- Required assertions or deferral reason: scoped overlay value authorship identifies overlay source and `argv_scoped_overlays`; artifact metadata is plain-data and round-trippable as `kind="overlay"`; fingerprint metadata changes when scoped overlay authored content or metadata changes; no artifact-safe payload includes raw bytes or resolved runtime values.

### Contract Suite

- Status: required
- Expected paths: `packages/weave/tests/contracts/test_config_artifact_contract.py`, `packages/weave/tests/contracts/test_config_composition_inspection_contract.py`.
- Required assertions or deferral reason: artifact and manifest contracts include scoped overlay overlay-family records without a new kind; non-argv `inspect_config_composition(...)` stage tuple is unchanged; internal argv inspection stage ordering is covered without exporting `inspect_config_from_argv(...)`.

### Integration Suite

- Status: required
- Expected paths: new `packages/weave/tests/integration/config/test_compose_argv_scoped_overlays.py`, plus `packages/weave/tests/integration/config/test_compose_recipes.py`, `packages/weave/tests/integration/config/test_compose_overrides.py`.
- Required assertions or deferral reason: `data/=data_A`, `model/=model_B`, `model/pipeline/=pipeline_A`, `+runtime/=local`, and `_replace_: true` merge correctly; scoped overlays apply after file includes and before recipe expansion; value overrides still win after recipe expansion; update/add target errors are structured; the dedicated scoped overlay integration test records scoped overlay files in raw snapshot opt-in behavior.

### E2E Suite

- Status: deferred
- Expected paths: Phase 3 public argv helper tests, likely `packages/weave/tests/integration/config/test_compose_argv_from_cli.py`.
- Required assertions or deferral reason: no public `compose_config_from_argv(...)`, `inspect_config_from_argv(...)`, CLI integration, or docs UX exists in Phase 2.

### Opt-In Suites

- Status: required for affected config opt-in behavior
- Markers affected: `optional_dependency` contract tests and raw source snapshot opt-in behavior.
- Required assertions or deferral reason: contract tests run under existing optional dependency setup; `packages/weave/tests/integration/config/test_compose_argv_scoped_overlays.py` must include the scoped overlay raw snapshot opt-in assertion so the required path is dedicated and unambiguous.

## Risks

- Provenance or fingerprint support may need broader source-map changes than expected.
- Internal argv inspection plumbing could accidentally change public non-argv stage names or ordering.
- Scoped overlay metadata could become too broad for artifact-safe fingerprints if it includes absolute paths or raw source bytes in the wrong place.
- Add/update semantics at nested missing or non-mapping paths need precise structured errors.
- Stop if a new source artifact kind enum value, manifest schema change, public API change, raw bytes/runtime outputs in artifact-safe fingerprints, or non-argv inspection contract change appears necessary.

## Validation Commands

Targeted development commands:

```sh
uv run pytest packages/weave/tests/integration/config/test_compose_argv_scoped_overlays.py
uv run pytest packages/weave/tests/unit/config/test_config_provenance.py packages/weave/tests/unit/config/test_config_fingerprints.py packages/weave/tests/unit/config/test_config_artifacts.py
uv run pytest packages/weave/tests/contracts/test_config_artifact_contract.py packages/weave/tests/contracts/test_config_composition_inspection_contract.py
uv run pytest packages/weave/tests/integration/config/test_compose_recipes.py packages/weave/tests/integration/config/test_compose_overrides.py
uv run pytest packages/weave/tests/unit/config/test_argv.py packages/weave/tests/unit/config/test_overrides.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: private plumbing first, then scoped source loading, then source-aware merge semantics, then provenance/artifact/fingerprint records, then inspection stage/tests.
- Tests to run with each slice: start with new scoped overlay integration tests for merge order; add unit tests when source-map/authorship/fingerprint code changes; finish with contract and regression commands listed above.
- Decisions the executor must not revisit: no public argv helper/export, no first-party CLI integration, no warning UX, no new source artifact kind or manifest schema version without stopping, no changes to direct non-argv inspection stage tuple or output.
- Conditions that require stopping for the manager: schema-versioned manifest/source kind seems necessary; public `compose_config(...)` or `inspect_config_composition(...)` signatures or non-argv outputs would need to change; scoped overlay facts cannot be artifact-safe without raw bytes or runtime outputs; public `inspect_config_from_argv(...)` exposure is needed to test the stage; validation shows broad unrelated regressions.
- Expanded-path refinement notes: completed; no additional plan refinement pass is budgeted without explicit manager instruction.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed with `plan: add phase execution plan`.
- Final phase execution plan: completed by `loom_phase_planner` in the single expanded-path refine pass.
- Implementation summary: Private scoped-overlay composition plumbing is implemented without public API exports. The argv path loads resolved scoped overlay YAML as overlay sources, applies update/add scoped merges after file include expansion and before recipe expansion, records the internal `argv_scoped_overlays` inspection stage, and carries scoped overlay metadata through source artifacts, final value authorship, provenance/manifest metadata, raw source snapshots, and artifact-safe fingerprint facts.
- Implementation validation: `uv run pytest packages/weave/tests/integration/config/test_compose_argv_scoped_overlays.py` passed (6 tests); `uv run pytest packages/weave/tests/unit/config/test_config_provenance.py packages/weave/tests/unit/config/test_config_fingerprints.py packages/weave/tests/unit/config/test_config_artifacts.py` passed (29 tests); `uv run pytest packages/weave/tests/contracts/test_config_artifact_contract.py packages/weave/tests/contracts/test_config_composition_inspection_contract.py` passed (17 tests); `PYTHONPATH=packages/weave uv run pytest packages/weave/tests/integration/config/test_compose_recipes.py packages/weave/tests/integration/config/test_compose_overrides.py` passed (20 tests) after using the package support import path; `uv run pytest packages/weave/tests/unit/config/test_argv.py packages/weave/tests/unit/config/test_overrides.py` passed (46 tests); focused Ruff and Pyright passed.
- Refinement summary: pending
- Blocker-resolution summary: pending
- PR preparation: pending
- Stack maintenance: pending
- Remaining blockers: none recorded for implementation handoff.
