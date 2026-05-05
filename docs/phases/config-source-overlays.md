# Phase 4 Execution Plan: Source-Authored Overlays

## Metadata

- Status: refined phase execution plan
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
- Refine pass: completed by `loom_phase_planner`; expanded-path refinement tightened the internal helper seam, immutable path representation, source-map coverage rules, test boundaries, and public API exclusions.
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

- Add an internal source-map representation for config value authorship that can associate immutable config paths with `ConfigSource` context for the base file and each overlay.
- Prefer a private/internal helper, likely in a focused `loom.config` leaf module such as `source_maps.py` or `sources.py`, that returns both merged config data and source map together. `compose_config` may call this helper and discard or hold the source map internally, but must not expose it through public return fields.
- Build the initial source map for the loaded base config, including nested mappings and list-contained mapping values where path tracking is useful for later source-aware diagnostics.
- Apply overlays one-by-one in the caller-provided order, updating the source map in the same precedence decisions as the merged config.
- Preserve base-authored source entries for lower-precedence values that survive recursive mapping merges.
- Mark overlay-authored added, replaced, or overwritten values with the overlay `ConfigSource`, including mapping nodes, list nodes and descendants, nested descendants of overlay-authored mappings, and scalar/list/null replacements.
- Respect Phase 3 `_replace_: true` behavior when updating source maps: discarded lower-precedence mapping entries must not survive as authorship for replaced subtrees, and replacement marker entries must not appear as final authored values.
- Keep `_include_` as ordinary authored data in this phase, but ensure a path such as `$.model._include_` authored by an overlay maps to that overlay source so Phase 6 can resolve it relative to the overlay file.
- Thread the source-aware overlay composition through `compose_config` only as far as necessary to preserve current public behavior and enable tests; public `ComposedConfig` v1 fields and populated artifact records remain later-phase work.

## Out-of-Scope Work

- Include target resolution, include expansion, include cycle detection, include stacks, sibling customization records, and include-specific errors.
- User-authored include replacement or any user composition override ordering changes.
- Recipe catalog hardening, recipe expansion order changes, or recipe manifest changes.
- Resolver scanning, resolver execution policy, and resolver-dependent composition failures.
- Public `inspect_config_composition`, public stage records, or additive v1 `ComposedConfig` fields.
- Any public export, public API signature change, or public `ComposedConfig`/inspection field for source maps. Phase 12 owns public inspection and additive public return fields.
- Manifest, provenance, source artifact, fingerprint, or redaction population beyond minimal internal source-map plumbing.
- Raw source snapshots, run-store writes, persistence policy, public CLI commands, or CLI-only syntax.

## Assumptions

- The source-map API can remain internal until Phase 12 public inspection APIs and Phase 13 artifact population decide what must become stable.
- `ConfigSource` remains the source identity record for this phase; a source-map entry should reference or serialize enough of it to distinguish base versus overlay order/path.
- Internal config paths should not be dotted strings because mapping keys may contain dots. Prefer an immutable internal path representation such as `tuple[str | int, ...]`, with `()` representing the root, `str` segments representing exact mapping keys, and `int` segments representing list indexes.
- Path formatting is a diagnostics/test helper only. It may produce strings such as `$`, `$.model`, `$['key.with.dot']`, or `$[0]`, but source-map identity and lookups must use the immutable path tuple.
- Source tracking for list elements is useful for diagnostics, but list merge semantics remain whole-list replacement; this phase must not add list patching behavior.
- Existing `ConfigProvenance.sources` remains the public ordered source list; per-path source maps need not be exposed through `ConfigProvenance` until later artifact-population phases.

## Scope Contract

- Overlay order is caller order. The first overlay has `ConfigSource(kind="overlay", order=1)`, the second order `2`, and so on, matching `load_config` and `ConfigProvenance.sources`.
- The internal helper seam should be precise enough for implementation and tests: take already loaded base config/source and ordered overlay config/source pairs, apply the same one-by-one merge semantics, and return a small internal result containing `config: dict[str, PlainData]` and `source_map: Mapping[ConfigPath, ConfigSource]` or equivalent immutable/plain shape.
- `compose_config` may replace its direct `merge_configs` overlay loop with that helper while preserving the current public `ComposedConfig` shape. The source map must not be added to `ComposedConfig`, `ConfigProvenance`, root package exports, or public inspection APIs in this phase.
- Source-map keys are immutable path tuples, not dotted strings. Formatting functions are allowed only for assertions, diagnostics, and later error contexts.
- Merge semantics stay exactly Phase 3 semantics: mappings recursively merge, scalar/list/null values replace, `_replace_: true` consumes the marker and replaces an existing lower-precedence mapping, and invalid `_replace_` usage raises `ConfigMergeError`.
- Source-map updates must follow the returned merged value, not the raw overlay payload. No source-map entry should exist for consumed `_replace_` markers.
- Source maps should include the root node and every retained mapping node, list node, scalar value, `null` value, and list descendant node that can be represented from the final merged data. Container nodes are source-authored too: a new or replaced container gets the winning source, while recursive mapping merges preserve lower-precedence descendant authorship where those descendants survive.
- When an overlay mapping recursively merges into a lower-precedence mapping, base-authored descendants that survive keep base authorship; overlay-authored descendants that add or overwrite values get overlay authorship. The merged mapping node itself may carry the overlay source when the overlay authored that mapping at the path, but this must not imply all descendants are overlay-authored.
- When an overlay scalar, list, explicit `null`, mapping-over-non-mapping, non-mapping-over-mapping, or `_replace_` mapping replacement wins, the winning node and all retained descendants in that replacement subtree are authored by that overlay unless a recursive mapping merge explicitly preserves lower-precedence descendants.
- For `_replace_: true`, all lower-precedence source-map entries under the replaced subtree are discarded before applying the replacement mapping. The consumed marker path, for example `("section", "_replace_")`, must not appear in the final source map.
- Overlay-order assertions must inspect `ConfigSource.kind`, `ConfigSource.order`, and source path identity for final source-map entries. Do not infer authorship by comparing value equality between base and overlays, because identical values can be authored by different sources.
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
| Use dotted strings as source-map keys | Ambiguous for literal-dot mapping keys and inconsistent with future strict diagnostics. |
| Implement include resolution while adding source tracking | Include target forms and recursive expansion are Phase 5 and Phase 6 scope. |
| Persist source maps by default from `loom.config` | Violates the persistence-free config boundary and belongs to later artifact/run-store phases. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Source-map representation remains internal and may need additive reshaping | Keeps Phase 4 review focused before include and inspection APIs prove final record needs. The immutable path tuple should reduce future reshaping risk. | Revisit during Phase 6 or Phase 12 if include expansion or inspection requires source context not captured here. |
| Public `ConfigProvenance` still exposes only the ordered source list, not per-path authorship | Artifact/provenance population is later scope. | Revisit in Phase 13 when manifest/provenance/source records are populated. |

## Reviewability

- Expected PR size and shape: focused internal helper/test diff that adds source-map construction and source-aware overlay composition, plus narrow compose plumbing if needed. No public API diff is expected.
- Files and areas to inspect: likely a new `src/loom/config/source_maps.py` or similarly focused internal module, `src/loom/config/compose.py` for using the helper, `src/loom/config/merge.py` only if needed to share Phase 3 merge decisions safely, `tests/unit/loom/config/test_source_maps.py`, and a focused integration test under `tests/integration/config/`.
- Scope-control checks: no include resolution module; no recursive include expansion; no user include swaps; no recipe/order refactor; no resolver policy changes; no public inspection API; no `ComposedConfig` v1 fields; no `ConfigProvenance` per-path population; no manifest/fingerprint/source-artifact population; no raw source persistence; no run-store writes; no CLI; no pipeline imports.

## Implementation Steps

1. Define an internal immutable `ConfigPath` representation, source-map/result type, path formatter for diagnostics/tests, and base-map builder around existing `ConfigSource`.
2. Add a source-aware overlay merge helper that accepts loaded source/config pairs and returns merged data plus source map under Phase 3 merge and `_replace_` semantics.
3. Thread source-aware overlay composition into `compose_config` without changing public result fields, package exports, provenance payloads, or later-stage ordering.
4. Add focused unit tests for path identity/formatting, base source maps, ordered overlay source-map updates, recursive merge preservation, container/list coverage, scalar/list/null replacement, mapping/non-mapping replacements, and `_replace_` subtree replacement.
5. Add integration coverage using loaded base plus multiple overlays through the internal helper or compose-adjacent seam, proving overlay order and overlay-authored `_include_`-like values retain overlay source context without public API exposure.

## Test Plan

### Package Suite

- Status: required if exports/imports change; otherwise deferred for targeted implementation and covered by final PR validation.
- Expected paths: `tests/package/test_import_boundaries.py` and `tests/package/test_config_api.py` if new modules are exported or import behavior changes.
- Required assertions or deferral reason: no public package exports are expected. If implementation adds any importable helper beyond normal internal modules, assert cheap imports still avoid pipeline, stores, CLI, plugin discovery, and unexpected optional dependencies. Do not add root or package-level public symbols.

### Unit Suite

- Status: required.
- Expected paths: a new focused module such as `tests/unit/loom/config/test_source_maps.py`, plus `tests/unit/loom/config/test_merge.py` and `tests/unit/loom/config/test_compose.py` only where existing helpers are touched.
- Required assertions or deferral reason: immutable path tuples distinguish literal-dot keys from nested keys; formatting is diagnostic-only; base source-map entries identify the base source; overlays apply in exact order; later overlays override earlier overlay authorship for winning paths by asserting `ConfigSource.kind`, `.order`, and `.path`, not value equality; recursive mapping merges preserve lower-precedence authorship for untouched descendants; mapping nodes, list nodes, list descendants, scalar values, explicit `null`, mapping-over-non-mapping, and non-mapping-over-mapping replacements have expected authorship; `_replace_: true` discards lower-precedence source entries and omits marker authorship from final maps; invalid `_replace_` behavior still raises `ConfigMergeError`; `_include_` authored in an overlay is tracked with overlay source context.

### Contract Suite

- Status: deferred unless a public-ish serialized source-map record is introduced, which is not expected and should trigger manager review first.
- Expected paths: `tests/contracts/test_config_artifact_contract.py`, `tests/contracts/test_config_error_contract.py`, or a new focused contract test only if a serialized source-map record becomes public-ish.
- Required assertions or deferral reason: no new public artifact contract is expected in Phase 4. If the implementation appears to need a serialized source-map record, stop for the manager before exposing it; otherwise no contract test is required beyond existing artifact/error contract suites in final validation.

### Integration Suite

- Status: required.
- Expected paths: a focused new integration module under `tests/integration/config/`, or `tests/integration/config/test_compose_config.py` only if the existing compose integration file remains clearer.
- Required assertions or deferral reason: load base plus at least two overlays, run the internal source-aware helper, assert final values reflect one-by-one order, assert retained source context distinguishes base, first overlay, and later overlay through `ConfigSource` metadata, and assert an overlay-authored `_include_`-like value retains the overlay file/source context for later include resolution. Integration tests must not require public source-map fields, include resolution, manifest/provenance/fingerprint population, raw source persistence, CLI, or pipeline imports.

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
- Dotted-string source paths would make literal-dot keys ambiguous; use immutable path tuples for identity.
- List source tracking can become noisy; keep it deterministic and tied to whole-list replacement semantics rather than introducing list patching.

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

- Safe implementation slices: immutable internal path/source-map shape first, base source-map builder second, source-aware overlay merge helper third, compose threading without public exposure fourth, unit/integration tests fifth.
- Tests to run with each slice: run the new source-map unit tests after helper work; run merge tests after touching merge behavior; run compose unit tests after any compose threading; run config integration tests after internal source-aware overlay flow changes; run package tests if exports/imports change.
- Decisions the executor must not revisit: source maps are internal only; paths use immutable tuple identity; overlays preserve caller order; `_replace_` remains Phase 3 strict behavior; `_copy_` remains unsupported; `_include_` is not resolved in this phase; no user include swaps; no recipe/order/reflection redesign; no public inspection API; no public `ComposedConfig` fields; no persistence or CLI.
- Conditions that require stopping for the manager: source tracking cannot be implemented without changing public `ComposedConfig` fields before Phase 12; the implementation needs to resolve includes to test source context; tests require authorship inference by value equality; merge/source-map behavior conflicts with Phase 3 `_replace_` semantics; `ConfigSource` proves insufficient for overlay authored context and a public artifact contract decision is needed; satisfying tests requires recipe, resolver, validation, provenance-population, manifest, source-artifact, or fingerprint decisions; optional dependencies or pipeline imports leak into source-map helpers.
- Expanded-path refinement notes: completed; internal helper seam, immutable path identity, source-map coverage rules, and test boundaries are now recorded for implementation.

## Refinement And Review Budget Status

- Phase execution plan draft: used
- Phase execution plan refine: used
- Phase implementation refinement: used
- PR review: unused

## Completion Notes

- Draft plan: completed in this artifact by `loom_phase_planner`; implementation completed by this phase executor.
- Final phase execution plan: refined by `loom_phase_planner`; execution moved directly to scoped implementation.
- Implementation summary:
  - Added `src/loom/config/source_maps.py` with immutable path-based source map types, base-source map construction, path formatter, and source-aware overlay merge helper that mirrors Phase 3 merge and `_replace_` behavior.
  - Updated `src/loom/config/compose.py` to thread loaded overlay/base pairs through `compose_config_with_sources` while preserving current public `ComposedConfig` shape.
  - Added `tests/unit/loom/config/test_source_maps.py` covering tuple path identity, path formatting, recursive merge preservation, list/scalar/null replacement, `_replace_` behavior, and overlay-authored `_include_` context.
  - Added `tests/integration/config/test_source_map_integration.py` loading a base plus two overlays and asserting ordered provenance by `ConfigSource` through the internal helper path.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/config/test_source_maps.py` ✅ (8 passed)
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/config/test_merge.py tests/unit/loom/config/test_compose.py` ✅ (28 passed)
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/integration/config/test_compose_config.py tests/integration/config/test_source_map_integration.py` ✅ (5 passed)
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest ...` initially blocked on first run by read-only uv cache and DNS/network constraints; resolved by using writable cache directory and installing optional config extras once.
- Implementation refinement:
  - Budget status: used by the single expanded-path Phase 4 implementation/test refinement pass.
  - Validation output reviewed: prior executor validation in these completion notes plus the manager finding that source-aware `_replace_: true` semantics diverged from Phase 3 `merge_configs`.
  - Blocking issue caused by this phase: `src/loom/config/source_maps.py` reused normal recursive merge semantics while normalizing replacement children, which incorrectly reintroduced lower-precedence descendants under whole-section replacements.
  - Fix summary: replacement children now use replacement-mode normalization that mirrors `merge_configs`, so root and nested `_replace_: true` consume markers, validate nested marker lower mappings, discard lower source-map descendants under replaced subtrees, and author retained replacement descendants to the overlay source.
  - Regression coverage: source-map unit tests now compare replacement outputs with `merge_configs` for root replacement, nested replacement under a replaced section/root, lower-mapping failure cases, and source-map marker/descendant discard expectations.
  - Validation rerun:
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/config/test_source_maps.py` ✅ (11 passed)
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/config/test_merge.py tests/unit/loom/config/test_compose.py` ✅ (28 passed)
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/integration/config/test_compose_config.py tests/integration/config/test_source_map_integration.py` ✅ (5 passed)
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run ruff check src/loom/config/source_maps.py tests/unit/loom/config/test_source_maps.py tests/integration/config/test_source_map_integration.py` ✅
- PR preparation draft:
  - Draft pass status: completed by `loom_pr_preparer`; public draft written to `docs/phases/config-source-overlays-pr-body.md`.
  - Refine pass status: pending; expanded path is active and PR creation is intentionally left for `.codex/prompts/pr-body-refine.md`.
  - PR title: `Configuration - Phase 4: Source-Authored Overlays`
  - Branch: `codex/config-source-overlays`
  - Target branch: `develop`
  - Stack predecessor: none
  - Merge eligibility: merge-eligible after PR review because the target is `develop`.
  - PR review budget: unused.
  - GitHub PR creation: not attempted in this draft pass per expanded-path instructions.
- PR preparation validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` failed: Ruff passed, then Pyright reported one error in `tests/unit/loom/config/test_source_maps.py` because helper parameter `kind: str` is passed to `ConfigSource(kind=...)`, whose type expects `Literal["base", "overlay"]`.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` failed after writing `build/test-summary.md`: package, unit, contract, integration, and e2e suites passed; `config-extra` errored during collection because `tests/integration/config/test_source_maps.py` and `tests/unit/loom/config/test_source_maps.py` share the same basename under pytest import collection.
  - `build/test-summary.md` suite evidence: package 36 passed/1 skipped; unit 354 passed/1 skipped; contract 24 passed/1 skipped; integration 9 passed/5 skipped; e2e 5 passed; config-extra 1 collection error; overall 428 passed, 1 error, 8 skipped, 428 deselected.
  - Prior targeted validation after implementation refinement remains recorded above and passed with the writable cache pattern.
- User-authorized blocker-resolution pass:
  - Status: completed. This does not reset the original Phase 4 implementation refinement budget; that budget remains used.
  - Exact fix: changed the unit test `source()` helper annotation from `kind: str` to `kind: Literal["base", "overlay"]` so Pyright accepts construction of `ConfigSource`.
  - Exact fix: renamed `tests/integration/config/test_source_maps.py` to `tests/integration/config/test_source_map_integration.py`, preserving test content and behavior while avoiding duplicate pytest module basenames with `tests/unit/loom/config/test_source_maps.py`.
  - Validation rerun:
    - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` ✅ (Ruff passed; Pyright 0 errors; default harness 423 passed/9 skipped; config-extra 160 passed/428 deselected; build succeeded)
    - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` ✅ (wrote `build/test-summary.md`; overall 588 passed, 0 failed, 0 errors, 8 skipped, 428 deselected)
  - Updated PR-body draft evidence in `docs/phases/config-source-overlays-pr-body.md` with the passing validation and suite summary.
- Scope confirmation:
  - Final diff reviewed against `develop`; changed files are limited to this phase plan, `src/loom/config/compose.py`, `src/loom/config/source_maps.py`, `tests/unit/loom/config/test_source_maps.py`, and `tests/integration/config/test_source_map_integration.py`.
  - No future-phase implementation observed: no include resolution, recursive includes, user include replacement, public inspection/API fields, manifests/provenance population, fingerprints, raw source persistence, CLI, pipeline imports, run-store writes, or root package exports.
- Stack maintenance: no stack changes required in this scope.
- Remaining blockers:
  - None after the user-authorized blocker-resolution pass.
