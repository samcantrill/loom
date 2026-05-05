# Phase 6 Execution Plan: File-Defined Recursive Includes

## Metadata

- Status: draft phase execution plan
- Feature focus: Configuration
- PR title: `Configuration - Phase 6: File-Defined Recursive Includes`
- Branch: `codex/config-file-includes`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-file-includes`
- Phase execution plan path: `docs/phases/config-file-includes.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
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
- Refine pass: pending; expanded path is active.
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

- Existing files or modules that constrain this phase: `src/loom/config/includes.py` provides internal include target resolution and structured `ConfigIncludeResolutionError`; `src/loom/config/load.py` enforces strict YAML loading and returns `ConfigSource`; `src/loom/config/source_maps.py` provides `ConfigPath`, `format_config_path(...)`, `ComposedConfigWithSources`, and source-aware overlay merge behavior; `src/loom/config/merge.py` owns strict `_replace_` merge semantics; `src/loom/config/errors.py` has `ConfigErrorContext` and structured config-domain errors; `src/loom/config/compose.py` currently merges base/overlays with sources but does not expand includes.
- Existing tests or harness behavior: `tests/unit/loom/config/test_includes.py` covers Phase 5 target resolution; `tests/unit/loom/config/test_source_maps.py` and `tests/integration/config/test_source_map_integration.py` cover source-map merge behavior; `tests/unit/loom/config/test_merge.py` covers `_replace_`; `tests/contracts/test_config_error_contract.py` covers structured error serialization; `tests/integration/config/test_compose_config.py` covers current compose behavior.
- Import-boundary or dependency constraints: keep work under `loom.config` and config tests. Do not import pipeline, stores, CLI, plugin discovery, project code, network clients, or heavyweight dependencies.

## In-Scope Work

- Add internal recursive file-include expansion over a source-aware config tree after base/overlay merge and before user overrides.
- Load included YAML files through existing strict loading rules, preserving source metadata for included files and source-aware error context.
- Validate `_include_` placement and value shape for file-authored configs: mapping-local only, scalar string targets only, at most one `_include_` key per mapping node by YAML key uniqueness, and included document root must be a mapping.
- Expand included mappings recursively before merging local siblings over them with existing strict merge semantics.
- Track include stack records for diagnostics and future artifact population, including include site path, authored target, source file, resolved target path, and target kind.
- Detect include cycles by resolved target path plus active stack and fail with structured include-stack context instead of recursing.
- Record sibling/local customizations when keys beside `_include_` override or add to included content, while omitting `_include_` and consumed `_replace_` markers from the final expanded config.
- Enforce same-site `_replace_: true` when an `_include_` appears at a mapping path that already has lower-precedence mapping content from base/overlay merge.
- Preserve Phase 5 target resolution policy exactly: no global search, no plugin/remote resolvers, no extension probing, no resolver-dependent include targets, no raw source byte persistence.

## Out-of-Scope Work

- User composition overrides, including `path._include_=...` swaps and brand-new user include sites.
- Recipes, recipe ordering changes, runtime interpolation, resolver execution policy, and resolver scanning.
- Public `inspect_config_composition(...)`, additive `ComposedConfig` v1 fields, manifest/provenance/source-artifact/fingerprint population, redaction changes, or raw source snapshots.
- `_copy_` support, Hydra defaults lists, list-valued includes, multiple include targets in one mapping node, list patching, global search paths, plugin/remote include resolvers, CLI commands, run-store writes, and pipeline imports.

## Assumptions

- Phase 6 may add internal include expansion and record types, but public persistence contracts remain Phase 13+ work unless existing contract tests require plain serialization for internal handoff records.
- `ConfigSource.kind` currently supports base and overlay. Included-source representation may use a new internal include source/record type or an additive internal extension, but it must not force `loom.pipeline` or public artifact contracts to depend on config composition.
- Include expansion should operate on the source-aware merged file tree so overlay-authored `_include_` values resolve relative to the overlay file that authored them.
- The include site path passed to `resolve_include_target(...)` must point to the `_include_` key; the containing mapping path is `include_site_path[:-1]`.
- Same-site `_replace_` means the mapping that contains `_include_` must also contain `_replace_: true` when that containing mapping path already had lower-precedence mapping content before the include-site mapping was applied.
- Existing strict `_replace_` behavior remains authoritative for ordinary overlay/merge replacement. Phase 6 adds only the include-specific requirement for component swaps.
- Included files remain trusted project code and may contain nested `_include_`; `_copy_` remains rejected by the loader.

## Scope Contract

- File-authored include expansion is an internal config composition stage. It should remove `_include_` and consumed `_replace_` markers from the expanded config and return plain data plus internal records; it must not add new public root exports or public persistence fields in this phase.
- Include expansion loads the included mapping first, recursively expands includes inside that mapping, then merges local sibling keys over the expanded included mapping. Mappings recursively merge; scalars, lists, and explicit `null` replace according to existing merge semantics.
- Include target failures must remain source-aware by using the source that authored the `_include_` value, including overlay-authored includes.
- Include cycles fail with structured context that includes the active include stack and the attempted repeated target. The error should be inspectable without parsing a message string and should not include raw source bytes or resolver outputs.
- Non-mapping included document roots fail with source-aware context naming the include site and resolved target.
- Sibling customization records must distinguish local sibling additions from local sibling overrides of included content where practical. They are review/debug records, not persisted manifest records yet.
- Include swaps over an existing lower-precedence mapping require `_replace_: true` in the same mapping as `_include_`; missing, invalid, or unnecessary replacement behavior should align with the strict v1 decision tree and existing `_replace_` errors.
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
| `ConfigSource` may not be the final representation for included files | It currently models base/overlay authorship only, and forcing it into a public shape early could freeze the wrong contract. | Revisit when included source artifacts are populated in Phase 13 or if Phase 6 cannot provide source-aware errors without a narrow internal include-source model. |

## Reviewability

- Expected PR size and shape: focused internal include traversal/records plus unit, contract, and integration tests; small compose-stage wiring is acceptable only to exercise file-authored includes after base/overlay merge and before existing overrides.
- Files and areas to inspect: likely `src/loom/config/includes.py`, `src/loom/config/errors.py`, `src/loom/config/source_maps.py` if source-map helpers need narrow additions, `src/loom/config/compose.py` if the stage is wired into current composition, `tests/unit/loom/config/test_includes.py`, `tests/unit/loom/config/test_merge.py` only if replacement regressions need coverage, `tests/contracts/test_config_error_contract.py` or a focused include-record contract test, and `tests/integration/config/test_compose_includes.py`.
- Scope-control checks: no Phase 7 user include swaps; no recipes/order refactor; no resolver execution or artifact-time resolver scanning; no public inspection API or new `ComposedConfig` fields; no manifest/provenance/fingerprint/source-artifact population; no raw source persistence; no CLI; no run-store writes; no pipeline imports; no root package exports unless already required by prior public API policy.

## Implementation Steps

1. Define internal recursive include expansion result and record shapes for expanded config, include stack/site records, and local sibling customizations.
2. Add tree traversal that finds mapping-local `_include_` directives in the source-aware merged file tree, resolves targets through Phase 5 primitives, loads included files, and recursively expands included mappings.
3. Implement include-stack tracking and cycle detection with structured source-aware errors for repeated targets, missing/invalid targets delegated from Phase 5, non-string include values, invalid placement, and non-mapping include roots.
4. Merge local siblings over expanded included mappings with existing strict merge behavior, consume `_include_`/valid `_replace_`, enforce the include-specific same-site replacement requirement, and record sibling additions/overrides.
5. Add focused unit and contract tests for traversal, records, error context, cycles, replacement requirements, and provenance-safe serialization.
6. Add integration coverage for base plus overlay-authored includes through the existing source-aware composition path or compose-adjacent seam, without implementing user composition or public inspection fields.

## Test Plan

### Package Suite

- Status: deferred unless public exports/imports change.
- Expected paths: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py` if touched.
- Required assertions or deferral reason: no public package exports are expected. If the implementation changes `loom.config.__init__` or root exports, assert recursive include helpers/records remain internal unless deliberately exposed, and assert config imports still do not pull in pipeline, stores, CLI, plugin discovery, network clients, or heavyweight optional dependencies.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_includes.py`, with narrow additions to `tests/unit/loom/config/test_merge.py` or `tests/unit/loom/config/test_source_maps.py` only if needed for replacement/source-map edge coverage.
- Required assertions or deferral reason: nested includes expand included content before sibling merge; overlay-authored include sites use overlay source context; sibling scalar/list/null replacement and mapping merge follow existing semantics; local sibling additions and overrides are recorded; `_include_` and consumed `_replace_` are omitted from expanded output; missing `_replace_` fails when an include swaps over existing lower-precedence mapping content; invalid or unnecessary `_replace_` behavior remains strict; include values must be strings; included document roots must be mappings; include cycles fail with active stack context; include target resolution failures preserve Phase 5 context; `_copy_` remains unsupported by loading.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_config_error_contract.py` and/or a focused config include record contract test.
- Required assertions or deferral reason: include stack, include site, and local customization records serialize to plain data if record classes expose `to_dict()`/`from_dict()`; structured include expansion errors carry stable `ConfigErrorContext` fields plus plain-data details for include site path, authored target, source path, resolved target path, stack entries, and cycle reason; no raw YAML bytes, resolved resolver values, or non-plain payloads appear in records or errors.

### Integration Suite

- Status: required.
- Expected paths: new `tests/integration/config/test_compose_includes.py` or focused additions under `tests/integration/config/`.
- Required assertions or deferral reason: base config includes and overlay-authored includes expand through the source-aware composition path; nested includes resolve relative to each including file; overlay include replacement over a lower-precedence mapping requires same-site `_replace_`; sibling customizations are available from the internal result; existing user overrides remain ordinary value overrides and do not perform include swaps.

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
- Replacement enforcement can drift from Phase 3 `_replace_` semantics; tests should compare or reuse existing merge behavior instead of inventing parallel rules.
- Local customization records can become too detailed or public too early; keep them internal and plain-data compatible.
- Wiring into `compose_config` can accidentally implement Phase 7 user include swaps or Phase 12 public fields; keep override behavior unchanged.
- Error details can leak raw source bytes or resolver outputs if loading/diagnostics are too eager; only source paths, digests, config paths, authored target text, and stack metadata should appear.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/config/test_includes.py
uv run pytest tests/contracts/test_config_error_contract.py
uv run pytest tests/integration/config/test_compose_includes.py
uv run pytest tests/unit/loom/config/test_source_maps.py tests/integration/config/test_source_map_integration.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: internal record/error shape first; recursive traversal and include loading second; stack/cycle detection third; sibling merge/customization and replacement enforcement fourth; compose-stage integration for file-authored includes fifth; focused unit/contract/integration tests alongside each slice.
- Tests to run with each slice: run include unit tests after record/traversal work; run error contract tests after structured errors/records; run source-map tests after any source-map helper changes; run integration include tests after compose-stage wiring.
- Decisions the executor must not revisit: `loom.config` remains persistence-free; `loom.pipeline` must not depend on `loom.config` or manifests; `_copy_` is unsupported; default artifacts are security-first and artifact-safe; resolver outputs and raw source bytes are not persisted by default; v1 is Python-API-only with no CLI commands; no plugin/remote/global search include resolvers; Phase 6 must not implement user composition overrides.
- Conditions that require stopping for the manager: recursive file includes cannot be implemented without changing public `ComposedConfig` fields before Phase 12; include records require a public artifact schema decision; `ConfigSource` cannot represent included-file source context even internally; strict replacement behavior conflicts with Phase 3 merge semantics; satisfying tests requires user include swaps, recipes, runtime interpolation, raw snapshots, optional dependencies, network access, run-store writes, CLI, or pipeline imports.
- Expanded-path refinement notes: refine pass is pending and should tighten record shapes, same-site replacement detection, source-map interactions, cycle-stack payloads, and integration boundaries before implementation begins.

## Refinement And Review Budget Status

- Phase execution plan draft: used
- Phase execution plan refine: unused; pending because expanded path is active
- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed in this artifact by `loom_phase_planner`.
- Final phase execution plan: pending expanded-path refinement.
- Implementation summary:
- Implementation validation:
- Refinement summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers: none at draft time.
