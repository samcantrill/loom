# Phase 4 Execution Plan: Source-Authored Overlays

## Metadata

- Status: draft phase execution plan
- Feature focus: Configuration
- PR title: `Configuration - Phase 4: Source-Authored Overlays`
- Branch: `codex/config-source-overlays`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-source-overlays`
- Phase execution plan path: `docs/phases/config-source-overlays.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 4 - Source-Authored Overlays
- Stack predecessor: none
- Base branch: `develop`
- Base commit: `8396040efc6b60e0aebf56c664922b6e533b9ccf`
- Target branch: `develop`
- Merge eligibility: merge-eligible after PR review because the target is `develop`
- Workflow path: expanded path
- Workflow path rationale: source authorship and provenance context become durable config behavior used by later include, manifest, provenance, and source-artifact phases.
- Successor dependency notes: Phase 5 include resolution and Phase 6 file-defined includes will depend on overlay-authored values retaining the correct source file context. This phase must not implement include resolution or public inspection APIs.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact.
- Refine pass: pending for expanded path.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid, but approved outside-sandbox `gh auth status` succeeded; `gh auth setup-git`, `git fetch origin`, and `git worktree add` required approved access. Local `develop`, `origin/develop`, and the worktree base all resolved to `8396040efc6b60e0aebf56c664922b6e533b9ccf`.
- Blockers: none.

## Objective

Add a focused source-authorship layer for base-plus-overlay composition so each retained value can be traced to the base file or a specific overlay file while preserving the user-provided overlay order exactly.

## Full-Plan Context

Phases 1-3 established config/pipeline boundaries, artifact skeletons, strict loading/errors, strict overrides, and `_replace_` merge primitives. Phase 4 now makes ordered overlays source-aware before Phase 5 defines include target resolution and Phase 6 expands file-authored includes. Later phases will use this source context for overlay-authored includes, source-aware errors, provenance/manifest population, source artifacts, and artifact-safe fingerprints.

Future behavior remains out of scope: recursive includes, user include replacement, recipe order changes, resolver security, validation boundaries, public `inspect_config_composition`, additive v1 `ComposedConfig` fields, manifest/provenance/fingerprint population, raw source snapshots, run-store writes, and CLI commands.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1, 2, and 3 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`, all earlier v1 phases are merged, and local/remote `develop` matched `8396040efc6b60e0aebf56c664922b6e533b9ccf` after fetch.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after this phase PR is merged and no successor phase branch depends on `codex/config-source-overlays`.

## Source Phase Summary

- Goal: apply base plus ordered overlays while preserving source authorship.
- Required scope: load overlays in user-provided order; merge overlays one-by-one; preserve source authorship metadata and path provenance context; ensure overlay-authored values retain overlay file context for later include resolution.
- Required checkpoints: overlay ordering is explicit and testable; source maps identify base versus each overlay for retained values; overlay-authored `_include_`-like values keep overlay `ConfigSource` context without resolving includes.
- Acceptance criteria: overlay order is preserved exactly; source maps identify whether values came from base or a specific overlay; include-like values authored in overlays retain overlay source context.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/load.py` returns `(mapping, ConfigSource)` for `base` and `overlay` sources; `src/loom/config/merge.py` owns recursive merge and strict `_replace_`; `src/loom/config/compose.py` currently loads overlays in caller order and merges them with `merge_configs`; `src/loom/config/provenance.py` records ordered `ConfigSource` values but has no per-path source map; `src/loom/config/api.py` keeps `ComposedConfig` limited to v0 fields until Phase 12.
- Existing tests or harness behavior: merge coverage lives in `tests/unit/loom/config/test_merge.py`; compose unit coverage in `tests/unit/loom/config/test_compose.py`; public integration coverage in `tests/integration/config/test_compose_config.py`; provenance model coverage in `tests/unit/loom/config/test_config_provenance.py`; package import boundaries in `tests/package/test_import_boundaries.py`.
- Import-boundary or dependency constraints: work should stay under `src/loom/config/` and config tests. Do not add pipeline, runner, store, CLI, plugin, project-code, or heavyweight dependency imports.

## In-Scope Work

- Add an internal source-map representation for config value authorship that can associate config paths with `ConfigSource` context for the base file and each overlay.
- Build the initial source map for the loaded base config, including nested mappings and list-contained mapping values where path tracking is useful for later source-aware diagnostics.
- Apply overlays one-by-one in the caller-provided order, updating the source map in the same precedence decisions as the merged config.
- Preserve base-authored source entries for lower-precedence values that survive recursive mapping merges.
- Mark overlay-authored added, replaced, or overwritten values with the overlay `ConfigSource`, including nested descendants of overlay-authored mappings and scalar/list/null replacements.
- Respect Phase 3 `_replace_: true` behavior when updating source maps: discarded lower-precedence mapping entries must not survive as authorship for replaced subtrees, and replacement marker entries must not appear as final authored values.
- Keep `_include_` as ordinary authored data in this phase, but ensure a path such as `$.model._include_` authored by an overlay maps to that overlay source so Phase 6 can resolve it relative to the overlay file.
- Thread the source-aware overlay composition through `compose_config` only as far as necessary to preserve current public behavior and enable tests; public `ComposedConfig` v1 fields and populated artifact records remain later-phase work.

## Out-of-Scope Work

- Include target resolution, include expansion, include cycle detection, include stacks, sibling customization records, and include-specific errors.
- User-authored include replacement or any user composition override ordering changes.
- Recipe catalog hardening, recipe expansion order changes, or recipe manifest changes.
- Resolver scanning, resolver execution policy, and resolver-dependent composition failures.
- Public `inspect_config_composition`, public stage records, or additive v1 `ComposedConfig` fields.
- Manifest, provenance, source artifact, fingerprint, or redaction population beyond minimal internal source-map plumbing.
- Raw source snapshots, run-store writes, persistence policy, public CLI commands, or CLI-only syntax.

## Assumptions

- The source-map API can remain internal until Phase 12 public inspection APIs and Phase 13 artifact population decide what must become stable.
- `ConfigSource` remains the source identity record for this phase; a source-map entry should reference or serialize enough of it to distinguish base versus overlay order/path.
- Config paths should follow the repository's existing `$`, `$.key`, and list-index style where practical for compatibility with Phase 2 loader error context.
- Source tracking for list elements is useful for diagnostics, but list merge semantics remain whole-list replacement; this phase must not add list patching behavior.
- Existing `ConfigProvenance.sources` remains the public ordered source list; per-path source maps need not be exposed through `ConfigProvenance` until later artifact-population phases.

## Scope Contract

- Overlay order is caller order. The first overlay has `ConfigSource(kind="overlay", order=1)`, the second order `2`, and so on, matching `load_config` and `ConfigProvenance.sources`.
- Merge semantics stay exactly Phase 3 semantics: mappings recursively merge, scalar/list/null values replace, `_replace_: true` consumes the marker and replaces an existing lower-precedence mapping, and invalid `_replace_` usage raises `ConfigMergeError`.
- Source-map updates must follow the returned merged value, not the raw overlay payload. No source-map entry should exist for consumed `_replace_` markers.
- When an overlay mapping recursively merges into a base mapping, base-authored descendants that survive keep base authorship; overlay-authored descendants that add or overwrite values get overlay authorship.
- When an overlay scalar, list, explicit `null`, mapping-over-non-mapping, non-mapping-over-mapping, or `_replace_` mapping replacement wins, the winning subtree is authored by that overlay unless a recursive merge preserves lower-precedence descendants.
- `_include_` and `_replace_` remain Loom-owned directive-looking keys, but this phase only source-tracks them according to Phase 3 loading/merge rules. Do not resolve `_include_` or reinterpret `_include_` as a directive yet.
- Existing `compose_config` resolved/redacted/fingerprint behavior may remain v0-oriented; do not re-order recipes, overrides, validation, or resolver execution to satisfy Phase 4 tests.
- `loom.config` remains persistence-free and `loom.pipeline` must not depend on config source maps or manifests.

## Design Impact

- Maintainability: isolates source authorship from include logic so later include/error/provenance phases can consume one merge-aligned source map instead of inferring authorship from merged values.
- Extensibility: leaves room for future public inspection and manifest records by keeping source entries plain, source-based, and path-oriented.
- Domain neutrality: tracks authored config values without interpreting project-specific model, dataset, experiment, or stage semantics.
- Source-tree boundaries: work stays in `loom.config` helper modules and tests, with no pipeline, store, runner, CLI, plugin, or project-code dependencies.

## Future Compatibility

- Phase 5 can use source context to report include target errors against the authored file and path.
- Phase 6 can resolve overlay-authored includes relative to the overlay file rather than the base file.
- Phase 12 can expose source-map or stage-record views through public inspection APIs after the internal shape proves sufficient.
- Phase 13 can populate artifact-safe provenance, manifest, and source records from the same source authorship data.
- Phase 14 can fingerprint source role/order and authored source context without treating absolute paths as semantic identity.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Infer source authorship later by comparing merged values to base and overlays | Ambiguous for identical values and unusable for overlay-authored include context. |
| Treat each overlay as a whole-tree source after merge | Loses base-authored descendants that survive recursive mapping merges. |
| Expose a public source-map API in Phase 4 | Public inspection API shape belongs to Phase 12 after include/user composition stages exist. |
| Implement include resolution while adding source tracking | Include target forms and recursive expansion are Phase 5 and Phase 6 scope. |
| Persist source maps by default from `loom.config` | Violates the persistence-free config boundary and belongs to later artifact/run-store phases. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Source-map representation remains internal and may need additive reshaping | Keeps Phase 4 review focused before include and inspection APIs prove final record needs. | Revisit during Phase 6 or Phase 12 if include expansion or inspection requires source context not captured here. |
| Public `ConfigProvenance` still exposes only the ordered source list, not per-path authorship | Artifact/provenance population is later scope. | Revisit in Phase 13 when manifest/provenance/source records are populated. |

## Reviewability

- Expected PR size and shape: focused config helper/test diff that adds source-map construction and source-aware overlay composition, plus narrow compose plumbing if needed.
- Files and areas to inspect: likely `src/loom/config/merge.py` or a new small source-aware composition helper, `src/loom/config/provenance.py` if a private/plain source-map record is added there, `src/loom/config/compose.py` for overlay threading, `tests/unit/loom/config/test_merge.py` or a new source-map unit test module, `tests/unit/loom/config/test_compose.py`, and `tests/integration/config/test_compose_config.py`.
- Scope-control checks: no include resolution module; no recursive include expansion; no user include swaps; no recipe/order refactor; no resolver policy changes; no public inspection API; no `ComposedConfig` v1 fields; no manifest/fingerprint/source-artifact population; no run-store writes or CLI.

## Implementation Steps

1. Define the internal source-map/value-authorship shape and base-map builder around existing `ConfigSource` and path conventions.
2. Add source-aware overlay merge behavior that wraps or composes with `merge_configs` so config values and source-map entries update together under Phase 3 merge and `_replace_` semantics.
3. Thread source-aware overlay composition into `compose_config` without changing public result fields or later-stage ordering.
4. Add focused unit tests for base source maps, ordered overlay source-map updates, recursive merge preservation, scalar/list/null replacement, and `_replace_` interactions.
5. Add integration coverage for public base plus multiple overlays proving overlay order and overlay-authored `_include_`-like values retain overlay source context through the internal helper or a narrowly exposed test seam.

## Test Plan

### Package Suite

- Status: conditional.
- Expected paths: `tests/package/test_import_boundaries.py` and `tests/package/test_config_api.py` if new modules are exported or import behavior changes.
- Required assertions or deferral reason: no public package exports are expected. If implementation adds a module-level export, assert cheap imports still avoid pipeline, stores, CLI, plugin discovery, and unexpected optional dependencies.

### Unit Suite

- Status: required.
- Expected paths: a new focused module such as `tests/unit/loom/config/test_source_maps.py`, plus `tests/unit/loom/config/test_merge.py` and `tests/unit/loom/config/test_compose.py` only where existing helpers are touched.
- Required assertions or deferral reason: base source-map entries identify the base source; overlays apply in exact order; later overlays override earlier overlay authorship for winning paths; recursive mapping merges preserve lower-precedence authorship for untouched descendants; scalar/list/null replacements mark the winning subtree as the overlay; `_replace_: true` discards lower-precedence source entries and omits marker authorship from final maps; invalid `_replace_` behavior still raises `ConfigMergeError`; `_include_` authored in an overlay is tracked with overlay source context.

### Contract Suite

- Status: conditional.
- Expected paths: `tests/contracts/test_config_artifact_contract.py`, `tests/contracts/test_config_error_contract.py`, or a new focused contract test only if a serialized source-map record becomes public-ish.
- Required assertions or deferral reason: no new public artifact contract is expected in Phase 4. If the implementation exposes serializable source-map records, contract tests must assert plain-data serialization, stable source kind/order/path fields, and absence of raw source bytes or resolved resolver values.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_config.py` or a focused new integration module under `tests/integration/config/`.
- Required assertions or deferral reason: compose base plus at least two overlays in caller order; assert final values reflect one-by-one order; assert retained source context distinguishes base, first overlay, and later overlay; assert an overlay-authored `_include_`-like value retains the overlay file/source context for later include resolution.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 4 does not complete public v1 composition through includes, inspection APIs, artifact population, or CLI behavior. Representative public e2e coverage starts in Phase 12/16 after the full composition order is wired.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: raw source snapshots, opt-in persistence, remote sources, and resolver runtime-value policies are out of scope.

## Risks

- Source-map behavior can accidentally diverge from `merge_configs`; keep tests aligned with Phase 3 merge cases, especially `_replace_`.
- Identical values authored in multiple files must still reflect the winning author, not value equality.
- Overlay-authored mapping parents can contain a mix of overlay and base descendants after recursive merge; avoid treating whole recursive merges as all-overlay.
- Adding public exposure too early could freeze the wrong record shape before includes and inspection APIs land.
- Include-like keys must be tracked as authored data without starting include resolution or validation early.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/config/test_source_maps.py
uv run pytest tests/unit/loom/config/test_merge.py tests/unit/loom/config/test_compose.py
uv run pytest tests/integration/config/test_compose_config.py
uv run pytest tests/package/test_import_boundaries.py tests/package/test_config_api.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: internal source-map shape first, base source-map builder second, source-aware overlay merge third, compose threading fourth, unit/integration tests fifth.
- Tests to run with each slice: run the new source-map unit tests after helper work; run merge tests after touching merge behavior; run compose unit tests after any compose threading; run config integration tests after public overlay flow changes; run package tests if exports/imports change.
- Decisions the executor must not revisit: overlays preserve caller order; `_replace_` remains Phase 3 strict behavior; `_copy_` remains unsupported; `_include_` is not resolved in this phase; no user include swaps; no recipe/order/reflection redesign; no public inspection API; no persistence or CLI.
- Conditions that require stopping for the manager: source tracking cannot be implemented without changing public `ComposedConfig` fields before Phase 12; the implementation needs to resolve includes to test source context; merge/source-map behavior conflicts with Phase 3 `_replace_` semantics; `ConfigSource` proves insufficient for overlay authored context and a public artifact contract decision is needed; satisfying tests requires recipe, resolver, validation, provenance-population, or fingerprint decisions; optional dependencies or pipeline imports leak into source-map helpers.
- Expanded-path refinement notes: pending; refine pass should confirm the internal source-map shape and test seam are sufficient for Phase 5/6 without overexposing public API.

## Refinement And Review Budget Status

- Phase execution plan draft: used
- Phase execution plan refine: pending for expanded path
- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed in this artifact by `loom_phase_planner`; implementation not started.
- Final phase execution plan:
- Implementation summary:
- Implementation validation:
- Refinement summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers:
