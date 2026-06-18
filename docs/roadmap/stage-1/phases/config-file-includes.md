# Phase 6 Execution Plan: File-Defined Recursive Includes

## Metadata

- Status: pr_open
- Feature focus: Configuration
- PR title: `Configuration - Phase 6: File-Defined Recursive Includes`
- PR: https://github.com/samcantrill/loom/pull/31
- Branch: `codex/config-file-includes`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-file-includes`
- Phase execution plan path: `docs/roadmap/stage-1/phases/config-file-includes.md`
- Full plan: `docs/roadmap/stage-1/implementation-plan.md`
- Planning notes: `docs/roadmap/stage-1/planning.md`
- Source phase: Phase 6 - File-Defined Recursive Includes
- Stack predecessor: none; Phases 1-5 are merged
- Base branch: `develop`
- Base commit: `75847f8f774226062b667529c63f1bfcb7f166e6`
- Target branch: `develop`
- Merge eligibility: merge-eligible after PR review because target is `develop`
- Workflow path: expanded path
- Workflow path rationale: recursive include expansion, include-stack and cycle semantics, sibling merge/local customization records, strict replacement requirements, and source-aware errors define durable config composition behavior that later user composition and artifact phases depend on.
- Successor dependency notes: Phase 7 must consume the file-defined include-site records for user include swaps without re-expanding Phase 6 scope. Later manifest, source artifact, fingerprint, and inspection phases may serialize these records but must not require Phase 6 to persist them publicly.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact.
- Refine pass: completed by `loom_phase_planner`; expanded-path refinement tightened internal record boundaries, same-site `_replace_` detection, source-map interactions, include cycle identity, stack/error payloads, suite obligations, and implementation stop conditions.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid, but approved outside-sandbox `gh auth status` succeeded; `gh auth setup-git` succeeded. `git fetch origin` required approved access because writing `.git/FETCH_HEAD` was blocked by the sandbox, then succeeded. Local `develop` and `origin/develop` both resolved to `75847f8f774226062b667529c63f1bfcb7f166e6`. `git worktree add` required approved access because writing Git refs was blocked by the sandbox.
- Blockers: none.

## Objective

Implement file-authored recursive `_include_` expansion for base and overlay config sources using the strict v1 include resolver, while preserving source context, cycle diagnostics, sibling customization records, and same-site `_replace_` requirements without adding user composition overrides or persistence behavior.

## Full-Plan Context

Phases 1-5 established config/pipeline boundaries, artifact skeletons, structured loading/errors, strict merge and `_replace_`, source-authored overlays, and deterministic include target resolution. Phase 6 is the first phase that loads included files and recursively composes their mappings. It must provide the internal records and behavior that Phase 7 uses for user include swaps, while leaving recipes, runtime interpolation, public inspection APIs, manifest/source-artifact population, fingerprints, raw snapshots, CLI behavior, and run-store writes to later phases.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-5 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`, all earlier v1 phases are merged, and local/remote `develop` matched `75847f8f774226062b667529c63f1bfcb7f166e6` after fetch.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after the Phase 6 PR is merged and no successor phase branch depends on `codex/config-file-includes`.

## Source Phase Summary

- Goal: expand file-authored includes recursively under the strict decision tree.
- Required scope: recursive include expansion; include stacks; cycle detection; sibling merge and local customization records; strict include replacement; source-aware include errors.
- Required checkpoints: included documents load through the strict loader; nested includes are expanded before local siblings merge; include stacks are tracked through all recursive loads; cycles fail before unbounded recursion; sibling overrides are recorded as local customizations; include swaps over existing mapping content require same-site `_replace_: true`.
- Acceptance criteria: nested includes work; include cycles fail with include-stack context; sibling overrides are recorded; include swaps over existing mapping content require same-site `_replace_`.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/includes.py` provides internal include target resolution and structured `ConfigIncludeResolutionError`; Phase 6 must consume `resolve_include_target()` and `IncludeResolutionResult` rather than reimplement target parsing or path-safety checks. `src/loom/config/load.py` enforces strict YAML loading and returns `ConfigSource`. `src/loom/config/source_maps.py` provides `ConfigPath`, `format_config_path(...)`, `ComposedConfigWithSources`, `compose_config_with_sources(...)`, and `build_base_source_map(...)`; it tracks source by immutable tuple paths, preserves surviving base descendants through recursive merge, and currently treats `_include_` as ordinary authored data. `src/loom/config/merge.py` owns strict `_replace_` merge semantics. `src/loom/config/errors.py` has `ConfigErrorContext` and structured config-domain errors. `src/loom/config/provenance.py` models ordered base/overlay sources and parsed overrides, not per-include stack records. `src/loom/config/artifacts.py` is the closest config-domain contract home if plain-data serialization helpers are needed, but Phase 6 records should remain additive and internal. `src/loom/config/compose.py` currently orders stages as load overlays, source-aware file merge, user overrides, recipes, interpolation, validation; Phase 6 should insert file-authored recursive include expansion after source-aware file merge and before user overrides/recipes.
- Existing tests or harness behavior: `tests/unit/loom/config/test_includes.py` covers Phase 5 target resolution; `tests/unit/loom/config/test_source_maps.py` and `tests/integration/config/test_source_map_integration.py` cover source-map merge behavior; `tests/unit/loom/config/test_merge.py` covers `_replace_`; `tests/contracts/test_config_error_contract.py` covers structured error serialization; `tests/integration/config/test_compose_config.py` covers current compose behavior.
- Import-boundary or dependency constraints: keep work under `loom.config` and config tests. Do not import pipeline, stores, CLI, plugin discovery, project code, network clients, or heavyweight dependencies.

## In-Scope Work

- Add internal recursive file-include expansion over a source-aware config tree after base/overlay merge and before user overrides or recipes.
- Load included YAML files through existing strict loading rules, preserving source metadata for included files and source-aware error context.
- Validate `_include_` placement and value shape for file-authored configs: mapping-local only, scalar string targets only, at most one `_include_` key per mapping node by YAML key uniqueness, and included document root must be a mapping.
- Expand included mappings recursively before merging local siblings over them with existing strict merge semantics.
- Track include stack records for diagnostics and future artifact population, including include site path, authored target, source file, resolved target path, target kind, and explicit-escape flag from `IncludeResolutionResult`.
- Detect include cycles by normalized resolved target path identity in the active include stack and fail with structured include-stack context instead of recursing.
- Record sibling/local customizations when keys beside `_include_` override or add to included content, while omitting `_include_` and consumed `_replace_` markers from the final expanded config.
- Enforce same-site `_replace_: true` when an `_include_` appears at a mapping path that has lower-precedence mapping content from base/overlay merge, using a narrow internal replacement-site signal because valid overlay `_replace_` markers are consumed by existing source-aware merge before Phase 6 sees the merged tree.
- Preserve Phase 5 target resolution policy exactly: no global search, no plugin/remote resolvers, no extension probing, no resolver-dependent include targets, no raw source byte persistence.

## Out-of-Scope Work

- User composition overrides, including `path._include_=...` swaps and brand-new user include sites.
- Recipes, recipe ordering changes, runtime interpolation, resolver execution policy, and resolver scanning.
- Public `inspect_config_composition(...)`, additive `ComposedConfig` v1 fields, manifest/provenance/source-artifact/fingerprint population, redaction changes, or raw source snapshots.
- `_copy_` support, Hydra defaults lists, list-valued includes, multiple include targets in one mapping node, list patching, global search paths, plugin/remote include resolvers, CLI commands, run-store writes, and pipeline imports.

## Assumptions

- Phase 6 may add internal include expansion and record types, but public persistence contracts remain Phase 13+ work unless existing contract tests require plain serialization for internal handoff records.
- Include stack, include site, and local customization records should be new internal config-domain records, likely near include expansion. Do not force them into `ConfigSource` or `ConfigProvenance`; only add narrow plain-data methods if tests or future handoff compatibility require serialization.
- `ConfigSource.kind` currently supports base and overlay. Do not extend it for include stack records unless implementation proves a narrow internal source representation is unavoidable for source-aware errors. Included file source facts can be carried by include records or load results without becoming pipeline or persistence APIs.
- Include expansion should operate on the source-aware merged file tree so overlay-authored `_include_` values resolve relative to the overlay file that authored them.
- The include site path passed to `resolve_include_target(...)` must point to the `_include_` key; the containing mapping path is `include_site_path[:-1]`.
- Same-site `_replace_` means the mapping that contains `_include_` must have authored `_replace_: true` in the same source mapping when that containing mapping path had lower-precedence mapping content at file-merge time. Because current source-aware merge consumes valid `_replace_` markers, Phase 6 should not look for `_replace_` in the merged config as proof. It should consume or add a narrow internal merge-operation/replacement-site record from the file merge, keyed by `ConfigPath`, that records whether a valid replacement marker was authored at that mapping path.
- Existing strict `_replace_` behavior remains authoritative for ordinary overlay/merge replacement. Phase 6 adds only the include-specific requirement for component swaps.
- Included files remain trusted project code and may contain nested `_include_`; `_copy_` remains rejected by the loader.
- Tuple `ConfigPath` semantics are exact: never split string segments on dots. A key named `"model.v1"` remains one path segment and one directory segment for bare include resolution.

## Scope Contract

- File-authored include expansion is an internal config composition stage. It should remove `_include_` and any consumed `_replace_` markers from the expanded config and return plain data plus internal records; it must not add new public root exports, `ComposedConfig` fields, pipeline APIs, or public persistence fields in this phase.
- Include expansion must run after `compose_config_with_sources(...)` and before `parse_overrides(...)`/`apply_overrides(...)`, recipe argument interpolation, recipe expansion, runtime interpolation, validation, redaction, provenance assembly, and fingerprinting.
- Include expansion loads the included mapping first, recursively expands includes inside that mapping, then merges local sibling keys over the expanded included mapping. Mappings recursively merge; scalars, lists, and explicit `null` replace according to existing merge semantics.
- The executor should use `resolve_include_target()` and the returned `IncludeResolutionResult` for target identity, authored target, target kind, explicit escape, and resolved path. Do not duplicate Phase 5 parsing or weaken its path-safety checks.
- Internal include records should carry only plain-data-compatible diagnostics: include-site path as tuple/list payload, authored target, source path/source kind/source order, resolved target path, target kind, explicit escape flag, and stack order. They are not manifest records in Phase 6.
- Local customization records should be keyed by exact tuple `ConfigPath` and identify the local sibling source, whether the sibling added a new path or overrode included content, and the included site it customized. They should avoid storing raw source bytes or resolved runtime values.
- Include target failures must remain source-aware by using the `ConfigSource` from the `source_map` entry for the `_include_` path, including overlay-authored includes. If the source map lacks an `_include_` path for a directive, stop and report a source-map consistency blocker instead of guessing from parent paths.
- Include cycles fail with structured context that includes the active include stack and the attempted repeated target. Cycle identity is the normalized `IncludeResolutionResult.resolved_path` string/path in the active stack, not the authored target string. The cycle payload should include stack entries in traversal order plus the repeated resolved path and repeated include site.
- Non-mapping included document roots fail with source-aware context naming the include site, authored target, resolved target path, and included source path. Reuse `ConfigErrorContext` with `directive="_include_"`; use `ConfigIncludeResolutionError` only when the failure is target resolution, otherwise use a narrow config-domain include expansion subclass if needed.
- Include swaps over existing lower-precedence mapping content require same-site `_replace_: true`. Detection should compare the containing include mapping path with internal file-merge/source-map facts: if a mapping containing an `_include_` was authored by a higher-precedence source while lower-precedence descendants survived or the path replaced an existing mapping, the valid replacement-site record must be present for that exact containing `ConfigPath`; otherwise fail. A valid replacement-site record satisfies the requirement even though the `_replace_` marker is absent from the merged config.
- Unnecessary `_replace_` remains strict. Existing merge logic may already reject `_replace_` without an existing mapping during overlay merge; Phase 6 should preserve that behavior and add tests only for include-specific same-site requirements.
- Sibling customization records must distinguish local sibling additions from local sibling overrides of included content where practical. They are review/debug records, not persisted manifest records yet.
- Phase 6 must not implement Phase 7 user composition overrides. User override strings are still parsed/applied by existing behavior after this stage and must not be reinterpreted as include swaps.

## Design Impact

- Maintainability: separates recursive traversal and stack/cycle handling from Phase 5 target resolution and from later public orchestration/artifact population.
- Extensibility: creates internal include-site and customization records that later user composition, manifest, source-artifact, and fingerprint phases can reuse additively.
- Domain neutrality: treats includes as plain mapping composition without interpreting model, dataset, stage, or project-specific schema.
- Source-tree boundaries: confines behavior to `loom.config` modules and tests with no dependency on pipeline execution, stores, CLI, plugin discovery, network access, or project imports.

## Future Compatibility

- Phase 7 can update known file-defined include sites using the recorded include-site context without introducing global search or bare user include ambiguity.
- Phase 12 can surface include stages through `inspect_config_composition(...)` without changing the recursive expansion semantics.
- Phase 13/14 can serialize include records, source records, and fingerprint inputs from the internal records created here while preserving the security-first default of no raw source bytes or resolver outputs.
- Future plugin or remote include resolver work can extend resolver families explicitly because Phase 6 preserves the local-only Phase 5 resolver boundary.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Reimplement include target classification inside recursive expansion | Phase 5 already locked deterministic resolver behavior; duplicating it risks drift. |
| Expand includes before source-aware overlay merge | Overlay-authored includes must resolve relative to the overlay source that authored them. |
| Let includes over existing mappings silently recursive-merge without `_replace_` | Violates the accepted safe component-swap rule and can leak stale lower-precedence keys. |
| Surface final manifest/provenance/source artifact fields in Phase 6 | Artifact population belongs to later phases after public orchestration and security policy are wired. |
| Add user include swaps while file includes are implemented | Phase 7 owns user composition overrides and needs Phase 6 records as input. |
| Add global search, plugin, remote, or registry include resolvers | Explicitly out of scope for v1 and conflicts with deterministic provenance. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Include expansion records remain internal and may need additive reshaping | Keeps Phase 6 focused on behavior before public inspection and artifact contracts are populated. | Revisit in Phase 7 if user include swaps need additional site metadata, and in Phase 12/13 before public serialization. |
| Source-aware file merge may need a narrow internal replacement-site side channel | Current merge helpers consume valid `_replace_` markers before include expansion, but Phase 6 must know whether same-site replacement was authored. | Revisit in Phase 12/13 if public inspection or manifests need to expose replacement records; otherwise keep it internal. |
| Include source facts remain separate from `ConfigSource`/`ConfigProvenance` | `ConfigSource` currently models ordered base/overlay inputs, and forcing include stacks into it would blur authorship and persistence contracts. | Revisit when included source artifacts are populated in Phase 13 or if Phase 6 cannot provide source-aware errors without a narrow internal include-source model. |

## Reviewability

- Expected PR size and shape: focused internal include traversal/records plus a narrow source-map merge-operation addition for consumed replacement sites, compose-stage insertion, and unit/contract/integration tests. The PR should not broaden into public inspection or artifact population.
- Files and areas to inspect: likely `src/loom/config/includes.py`, `src/loom/config/errors.py`, `src/loom/config/source_maps.py` for replacement-site/source-map handoff, `src/loom/config/compose.py` for stage order insertion, `tests/unit/loom/config/test_includes.py`, `tests/unit/loom/config/test_source_maps.py`, `tests/contracts/test_config_error_contract.py` or a focused include-record contract test, and `tests/integration/config/test_compose_includes.py`.
- Scope-control checks: no Phase 7 user include swaps; no recipes/order refactor; no resolver execution or artifact-time resolver scanning; no public inspection API or new `ComposedConfig` fields; no manifest/provenance/fingerprint/source-artifact population; no raw source persistence; no CLI; no run-store writes; no pipeline imports; no root package exports; no reimplementation of Phase 5 target parsing; no dot-splitting of tuple `ConfigPath` string segments.

## Implementation Steps

1. Add internal include expansion result, include stack/site, local customization, and replacement-site handoff records that are plain-data compatible but not public exports or artifact contracts.
2. Extend source-aware file merge only as needed to expose consumed valid `_replace_` sites by exact `ConfigPath`, while preserving existing config/source-map outputs and Phase 3 merge behavior.
3. Add tree traversal that finds mapping-local `_include_` directives in the source-aware merged file tree, resolves targets through Phase 5 primitives, loads included files, builds source maps for included roots, and recursively expands included mappings.
4. Implement include-stack tracking and cycle detection by normalized resolved target path with structured source-aware errors for repeated targets, non-string include values, invalid placement, source-map consistency failures, and non-mapping include roots. Delegate target resolution failures to Phase 5 errors.
5. Merge local siblings over expanded included mappings with existing strict merge behavior, consume `_include_`/valid replacement intent, enforce the include-specific same-site replacement requirement from replacement-site/source-map facts, and record sibling additions/overrides.
6. Wire the file-authored include stage into `compose_config` after source-aware file merge and before user overrides, then add focused unit, contract, and integration tests without implementing user composition or public inspection fields.

## Test Plan

### Package Suite

- Status: required only if exports/import surfaces change; otherwise deferred for targeted implementation and covered by final PR validation.
- Expected paths: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py` if touched.
- Required assertions or deferral reason: no public package exports are expected. If the implementation changes `loom.config.__init__` or root exports, assert recursive include helpers/records are not added to root exports, and assert config imports still do not pull in pipeline, stores, CLI, plugin discovery, network clients, or heavyweight optional dependencies.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_includes.py`, with narrow additions to `tests/unit/loom/config/test_merge.py` or `tests/unit/loom/config/test_source_maps.py` only if needed for replacement/source-map edge coverage.
- Required assertions or deferral reason: nested includes expand included content before sibling merge; included files get source maps via existing base-source helpers or equivalent internal logic; overlay-authored include sites use overlay source context; tuple `ConfigPath` string segments are not dot-split; sibling scalar/list/null replacement and mapping merge follow existing semantics; local sibling additions and overrides are recorded; `_include_` and consumed `_replace_` are omitted from expanded output; missing `_replace_` fails when an overlay include swaps over existing lower-precedence mapping content; a valid consumed same-site replacement record satisfies the include replacement requirement; invalid or unnecessary `_replace_` behavior remains strict; include values must be strings; included document roots must be mappings; include cycles fail by repeated normalized resolved target path with active stack context; include target resolution failures preserve Phase 5 context; source-map consistency failures stop with structured context; `_copy_` remains unsupported by loading.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_config_error_contract.py` and/or a focused config include record contract test.
- Required assertions or deferral reason: include stack, include site, local customization, and replacement-site records serialize to plain data if record classes expose `to_dict()`/`from_dict()`; structured include expansion errors carry stable `ConfigErrorContext` fields plus plain-data details for include site path, authored target, source path, resolved target path, target kind, explicit escape flag, stack entries, repeated cycle target, and failure reason; no raw YAML bytes, resolved resolver values, or non-plain payloads appear in records or errors. If no public serialization methods are added, contract coverage should assert error serialization and plain-data compatibility of internal record payloads through test-only construction.

### Integration Suite

- Status: required.
- Expected paths: new `tests/integration/config/test_compose_includes.py` or focused additions under `tests/integration/config/`.
- Required assertions or deferral reason: base config includes and overlay-authored includes expand through the source-aware composition path; include expansion runs after base/overlay merge and before user overrides/recipes; nested includes resolve relative to each including file; overlay include replacement over a lower-precedence mapping requires same-site `_replace_`; a valid overlay `_replace_` marker consumed during file merge allows the include swap; sibling customizations are available from the internal result or compose-adjacent test seam; existing user overrides remain ordinary value overrides and do not perform include swaps.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 6 does not complete the public v1 orchestration, public inspection API, artifact population, or CLI behavior. Representative public e2e coverage starts in Phase 12/16 after full composition order and public surfaces are wired.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: raw source snapshots, remote/plugin resolvers, network-backed includes, resolver runtime-value persistence, and CLI behavior are out of scope.

## Risks

- Include traversal can accidentally lose overlay source context if it reads only values and not the Phase 4 source map.
- Cycle detection can be under-specified if it keys only on authored targets rather than normalized resolved paths and active stack entries.
- Valid `_replace_` markers are consumed before include expansion, so same-site replacement checks will be wrong unless the source-aware file merge exposes a narrow internal replacement-site signal.
- Replacement enforcement can drift from Phase 3 `_replace_` semantics; tests should compare or reuse existing merge behavior instead of inventing parallel rules.
- Local customization records can become too detailed or public too early; keep them internal and plain-data compatible.
- Wiring into `compose_config` can accidentally implement Phase 7 user include swaps or Phase 12 public fields; keep override behavior unchanged.
- Error details can leak raw source bytes or resolver outputs if loading/diagnostics are too eager; only source paths, digests, config paths, authored target text, and stack metadata should appear.
- Reusing `ConfigSource` for include stack records would blur ordered source provenance with recursive traversal diagnostics; prefer internal records unless a narrow source representation is unavoidable.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/config/test_includes.py
uv run pytest tests/contracts/test_config_error_contract.py
uv run pytest tests/integration/config/test_compose_includes.py
uv run pytest tests/unit/loom/config/test_source_maps.py tests/integration/config/test_source_map_integration.py
uv run pytest tests/integration/config/test_compose_config.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: internal record/error shape first; source-map replacement-site handoff second; recursive traversal and include loading third; stack/cycle detection fourth; sibling merge/customization and replacement enforcement fifth; compose-stage integration for file-authored includes sixth; focused unit/contract/integration tests alongside each slice.
- Tests to run with each slice: run include unit tests after record/traversal work; run source-map tests after replacement-site handoff changes; run error contract tests after structured errors/records; run integration include and existing compose tests after compose-stage wiring.
- Decisions the executor must not revisit: consume `resolve_include_target()` and `IncludeResolutionResult`; preserve tuple `ConfigPath` semantics exactly with no dot-splitting; insert file-authored include expansion after source-aware file merge and before user overrides/recipes; keep include stack/local customization records internal and out of `ConfigSource`/`ConfigProvenance` unless a narrow internal representation is unavoidable; `loom.config` remains persistence-free; `loom.pipeline` must not depend on `loom.config` or manifests; `_copy_` is unsupported; default artifacts are security-first and artifact-safe; resolver outputs and raw source bytes are not persisted by default; v1 is Python-API-only with no CLI commands; no plugin/remote/global search include resolvers; Phase 6 must not implement user composition overrides.
- Conditions that require stopping for the manager: recursive file includes cannot be implemented without changing public `ComposedConfig` fields before Phase 12; include records require a public artifact schema decision; source-map/replacement-site information cannot distinguish a missing same-site `_replace_` from a valid consumed marker; source context for an authored `_include_` is missing from the source map; strict replacement behavior conflicts with Phase 3 merge semantics; cycle detection cannot use normalized resolved target paths without weakening Phase 5 path safety; satisfying tests requires user include swaps, recipes, runtime interpolation, raw snapshots, optional dependencies, network access, run-store writes, CLI, or pipeline imports.
- Expanded-path refinement notes: completed; record boundaries, same-site replacement detection, source-map interactions, cycle-stack payloads, source-aware errors, suite obligations, and stop conditions are now tightened for implementation.

## Refinement And Review Budget Status

- Phase execution plan draft: used
- Phase execution plan refine: used
- Phase implementation refinement: used
- PR review: used; PR #31 blocking review finding was addressed by the
  user-authorized scoped blocker-resolution pass. Do not request another
  automated review pass for Phase 6.

## Completion Notes

- Draft plan: completed in this artifact by `loom_phase_planner`.
- Final phase execution plan: refined in this artifact by `loom_phase_planner`; implementation refinement budget is now used and PR review budget remains unused.
- Implementation summary: implemented file-authored recursive `_include_` expansion in `src/loom/config/includes.py` with include-stack tracking, cycle detection, source-aware include-root errors, local customization records, and same-site `_replace_` enforcement during expansion. Wired expansion into `compose_config` after source-aware merge and before overrides/recipes. Added consumed include replacement and mapping-site tracking support in `src/loom/config/source_maps.py` and include-expansion error type in `src/loom/config/errors.py`.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_includes.py` (passed, 41/41).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_includes.py` (passed, 5/5).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_source_maps.py tests/integration/config/test_source_map_integration.py` (passed, 14/14).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_error_contract.py` (passed, 6/6).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_compose.py` (passed, 11/11).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config ruff check src/loom/config/compose.py src/loom/config/errors.py src/loom/config/includes.py src/loom/config/source_maps.py tests/contracts/test_config_error_contract.py tests/unit/loom/config/test_compose.py tests/unit/loom/config/test_includes.py tests/unit/loom/config/test_source_maps.py tests/integration/config/test_compose_includes.py` (passed).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pyright src/loom/config/compose.py src/loom/config/errors.py src/loom/config/includes.py src/loom/config/source_maps.py tests/contracts/test_config_error_contract.py tests/unit/loom/config/test_compose.py tests/unit/loom/config/test_includes.py tests/unit/loom/config/test_source_maps.py tests/integration/config/test_compose_includes.py` (passed).
- Refinement scope:
  - Validation output reviewed: manager-provided blocking findings plus local reruns of include unit tests, include integration tests, source-map tests, error contract tests, compose unit tests, Ruff, and Pyright.
  - Blocking issues caused by this phase: raw included-root `ConfigLoadError`, nested bare-name includes resolving from composed outer paths, unconsumed local `_replace_` handling, integration test expectation drift, and Pyright type errors in include helpers and changed tests.
  - Issues confirmed out of scope: none remain from the requested targeted validation set.
- Fixes made:
  - Translated only included-root `ConfigLoadError` with `non_mapping_root` context into `ConfigIncludeExpansionError` carrying include-site and resolved-target details.
  - Split global include-site record paths from file-local source lookup paths so nested bare-name targets resolve relative to the included file's own mapping path while records retain composed paths.
  - Filtered consumed `_replace_` from local sibling merge and rejected unconsumed local `_replace_` markers beside `_include_` so base-local markers cannot replace away included content.
  - Corrected integration tests for YAML boolean parsing, required top-level `name`, and explicit `+` add override syntax.
  - Added type narrowing in changed tests and tightened include record source-kind typing for Pyright.
- Refinement summary: completed the single expanded-path implementation/test refinement pass and added focused regression coverage for the manager blockers.
- User-authorized blocker resolution: fixed cycle errors to use the `ConfigSource` for the current attempted `_include_` directive while preserving resolved-path cycle identity and active include-stack details. Added focused include unit assertions for current source path/kind/order and composed attempted config path.
- Blocker-resolution validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_includes.py` (passed, 41/41).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config ruff check src/loom/config/includes.py tests/unit/loom/config/test_includes.py` (passed).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pyright src/loom/config/includes.py tests/unit/loom/config/test_includes.py` (passed).
  - `git diff --check` (passed).
- User-authorized PR #31 blocking review resolution: rejected unconsumed `_replace_` markers authored inside included content during recursive expansion, including root and nested markers, while preserving valid same-site overlay `_replace_` include swaps. Added assertions that successful include expansions do not retain `_replace_` markers.
- PR #31 blocker-resolution validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_includes.py` (passed, 43/43).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_includes.py` (passed, 6/6).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config ruff check src/loom/config/includes.py tests/unit/loom/config/test_includes.py tests/integration/config/test_compose_includes.py` (passed).
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pyright src/loom/config/includes.py tests/unit/loom/config/test_includes.py tests/integration/config/test_compose_includes.py` (passed, 0 errors).
  - `git diff --check` (passed).
- Post-merge blocker follow-up: PR #31 merged before the `_replace_` blocker
  fix landed on the phase branch, so the manager cherry-picked the exact
  blocker fix onto `codex/config-file-includes-replace-blocker` for a narrow
  follow-up PR targeting `develop`.
- Follow-up PR validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` (passed: Ruff passed;
    Pyright 0 errors; default harness 425 passed, 9 skipped; config-extra 212
    passed, 430 deselected; build succeeded)
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` (passed: wrote
    `build/test-summary.md`; overall 642 passed, 0 failed, 0 errors, 8
    skipped, 430 deselected)
- PR facts confirmed for draft body: branch/head `codex/config-file-includes`;
  target/base `develop`; stack predecessor none; root PR; merge eligibility
  remains merge-eligible after PR review because target is `develop`; PR title
  `Configuration - Phase 6: File-Defined Recursive Includes`; PR body artifact
  `docs/roadmap/stage-1/phases/config-file-includes-pr-body.md`.
- PR body draft: completed in
  `docs/roadmap/stage-1/phases/config-file-includes-pr-body.md` using
  `.codex/templates/phase-pr-body.md`; mentions `@samcantrill` near the top;
  keeps workflow internals out of the public body; summarizes implemented scope,
  implementation notes, tests, suite evidence, assumptions, and risks.
- PR body refine pass: completed using `.codex/prompts/pr-body-refine.md`.
  The existing public body was checked against the final diff, phase plan,
  accepted v1 decisions, acceptance criteria, scope boundaries, validation
  evidence, assumptions, and risks; no public body changes were required.
- PR opening: opened https://github.com/samcantrill/loom/pull/31 with explicit
  base `develop`, head `codex/config-file-includes`, title
  `Configuration - Phase 6: File-Defined Recursive Includes`, and body file
  `docs/roadmap/stage-1/phases/config-file-includes-pr-body.md`.
- PR verification: `gh pr view https://github.com/samcantrill/loom/pull/31
  --json baseRefName,headRefName,state,url` returned base `develop`, head
  `codex/config-file-includes`, state `OPEN`, URL
  `https://github.com/samcantrill/loom/pull/31`.
- Stack state: root PR with no stack predecessor; merge-eligible after review
  because the verified target branch is `develop`.
- Final validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` (passed): Ruff passed,
    Pyright reported 0 errors, default suite passed 425/425 with 9 skipped,
    config-extra suite passed 209/209 selected with 430 deselected, and
    `uv build` produced both sdist and wheel.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` (passed): wrote
    `build/test-summary.md`; package passed 36 with 1 skipped; unit passed 354
    with 1 skipped; contract passed 26 with 1 skipped; integration passed 9
    with 5 skipped; e2e passed 5; config-extra passed 209 with 430 deselected;
    overall passed 639 with 8 skipped and 430 deselected.
- Budget status confirmed after user-authorized blocker resolution:
  implementation refinement used; PR review used.
- Stack maintenance: N/A for this root PR; no predecessor retargeting or rebase
  work was performed during PR preparation.
- Remaining blockers: none.
