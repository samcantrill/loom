# Phase 7 Execution Plan: User Composition Overrides

## Metadata

- Status: merged
- Feature focus: Configuration
- PR title: `Configuration - Phase 7: User Composition Overrides`
- Branch: `codex/config-user-composition-overrides`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-user-composition-overrides`
- Phase execution plan path: `docs/phases/config-user-composition-overrides.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 7 - User Composition Overrides
- Stack predecessor: none; Phases 1-6 are merged
- Base branch: `develop`
- Base commit: `c3ab85a4cd1310ff25d8cb9053a904a7dc62f6ed`
- Target branch: `develop`
- Merge eligibility: merged into `develop`
- Workflow path: expanded path
- Workflow path rationale: user-authored include replacement changes config composition semantics and depends on Phase 6 include-site records, override ordering, strict source context, and future public/artifact phases.
- Successor dependency notes: Phase 8 resolver security must see user-composed include targets without executing resolvers. Phase 9 recipes can finalize recipe-before-ordinary-override ordering later because Phase 7 will have already separated user composition overrides from ordinary value overrides.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact.
- Refine pass: completed by `loom_phase_planner`; expanded-path refinement tightened private-stage boundaries, override partitioning/order, exact include-site matching, source-local include context, local overlay replay, brand-new explicit relative source policy, source-aware errors, and implementation stop conditions.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid, but approved outside-sandbox `gh auth status` succeeded; `gh auth setup-git` succeeded. `git fetch origin` required approved access because writing `.git/FETCH_HEAD` was blocked by the sandbox, then succeeded. Local `develop` resolved to the assigned base commit `c3ab85a4cd1310ff25d8cb9053a904a7dc62f6ed`. `git worktree add` required approved access because writing Git refs was blocked by the sandbox.
- Blockers: none.

## Objective

Add the private user-composition stage that applies `path._include_=...` overrides after file-defined include expansion and before ordinary value overrides, supporting existing include-site swaps, explicit brand-new include sites, recomposed component subtrees, and ordinary value override targeting of recomposed values without adding public API, artifact, recipe, CLI, or pipeline behavior.

## Full-Plan Context

Phases 1-6 established config/package boundaries, artifact skeletons, structured loading/errors, strict overrides and `_replace_`, source-aware overlays, deterministic include resolution, and file-authored recursive includes. Phase 7 is the bridge from file-authored composition to user-authored composition. It must reuse Phase 6 include records and strict Phase 5 resolver behavior while keeping resolver execution, recipe expansion changes, public inspection orchestration, manifests, source artifacts, fingerprints, persistence, CLI behavior, and pipeline imports out of scope.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-6 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`, the implementation plan records Phase 6 and its follow-up as merged, and local `develop` matches the assigned base commit.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after the Phase 7 PR is merged and no successor phase branch depends on `codex/config-user-composition-overrides`.

## Source Phase Summary

- Goal: apply user-defined composition after file-defined composition.
- Required scope: existing-site bare include replacement; explicit brand-new user include sites only; recomposed swapped component subtrees; ordinary value override pass hooks for later expanded config updates.
- Required checkpoints: parse user overrides once; partition `_include_` composition overrides from ordinary value overrides; apply all include-composition overrides after file-defined includes and before ordinary value overrides; preserve ordinary override relative order; recompose swapped include subtrees before ordinary overrides; reject brand-new bare include sites; keep ordinary override strict update/add behavior against the recomposed concrete config.
- Acceptance criteria: `path._include_=...` can replace an existing file-defined include site; brand-new user include sites require explicit path, absolute path, or `file://`; ordinary overrides can target values introduced by recomposed includes.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/compose.py` currently orders load, source-aware file merge, file include expansion, parse/apply all user overrides, recipe expansion, interpolation, validation, redaction, provenance, and fingerprinting. `src/loom/config/includes.py` owns `resolve_include_target(...)`, recursive include expansion, include-site records, local customization records, and include expansion errors. `src/loom/config/overrides.py` parses strict update and `+` add overrides and applies ordinary values to an already concrete mapping. `src/loom/config/source_maps.py` owns exact tuple `ConfigPath` source authorship plus consumed replacement and mapping-site handoff. `src/loom/config/errors.py` already has structured include resolution/expansion errors but ordinary override errors are message-only.
- Existing tests or harness behavior: `tests/unit/loom/config/test_includes.py` covers include target resolution, recursive expansion, include records, cycle errors, and replacement requirements. `tests/unit/loom/config/test_overrides.py` covers typed override parsing and strict update/add application. `tests/integration/config/test_compose_includes.py` proves current public compose expands file includes before ordinary user overrides and enforces Phase 6 replacement rules. `tests/integration/config/test_compose_config.py` covers current compose order with recipes and ordinary overrides. Package import-boundary tests already assert `loom.config` does not import pipeline, stores, execution, or CLI.
- Import-boundary or dependency constraints: keep implementation under `src/loom/config/` and config tests. Do not import pipeline, stores, CLI modules, plugin discovery, project code, network clients, or heavyweight dependencies.
- Phase 6 record extension required: current `IncludeSiteRecord` stores the composed include-site path and source path/kind/order, but nested bare replacements need the source-local include-site path or equivalent source-relative resolution base. Phase 7 should add a private `IncludeRecompositionContext` or equivalent sidecar keyed by composed include-site path. It should carry the original source context, source-local include-site path, and local sibling overlay payload needed for deterministic replacement and replay. This is private `loom.config` state, not a public artifact contract.

## In-Scope Work

- Parse user override strings once, preserving parsed order and typed values, then partition composition overrides whose final path segment is `_include_` from ordinary strict update/add value overrides.
- Apply all user include-composition overrides in parsed order after file-defined include expansion and before the existing ordinary value override pass. Preserve the relative order of the ordinary overrides when they are later applied to the recomposed concrete config.
- Replace an existing file-defined include site with `path._include_=...`, allowing bare targets only when the override path exactly matches a Phase 6 file-defined include site that has deterministic source context in the private recomposition context.
- Recompose swapped component subtrees by loading and recursively expanding the replacement include target, then replaying the original local sibling overlay/customization payload for that include site before downstream ordinary value overrides run.
- Add explicit brand-new user include sites only when the target is an explicit relative path, absolute path, or `file://`; reject bare brand-new include targets, resolver expressions, plugin/remote/global-search-style targets, and unsupported URI schemes.
- Use a deterministic config-source context for brand-new explicit relative user includes: resolve them relative to the base config file directory through a synthetic private include site at the requested config path, and record that policy in tests. Absolute paths and `file://` remain source-independent except for diagnostics.
- Keep ordinary update and `+` add override semantics intact and apply ordinary value overrides against the recomposed concrete config so users can update values introduced by replacement includes.
- Add or extend internal include-site/recomposition records only as needed to carry source-local include paths, source context, local overlay/customization values, and user composition diagnostics for later phases.

## Out-of-Scope Work

- Recipe expansion changes, recipe argument override syntax, resolver execution, resolver scanning, and runtime interpolation policy changes.
- Final public `compose_config` orchestration redesign, public `inspect_config_composition(...)`, additive v1 `ComposedConfig` fields, manifest/provenance/source-artifact/fingerprint population, raw source snapshots, and run-store writes.
- `_copy_` support, Hydra defaults lists, list-valued includes, multiple include targets in one mapping node, list patching, global search paths, plugin/remote include resolvers, CLI commands, pipeline imports, or root package exports.
- Public persistence of resolver outputs, raw source bytes, or user override source bytes beyond existing authored override strings in provenance.

## Assumptions

- User composition overrides are still plain override strings in the existing Python API; v1 does not introduce a new CLI or public lower-level API in this phase.
- A composition override is identified by the final parsed dot-path segment `_include_`. The containing config path is the include site container path.
- Existing-site matching uses exact tuple `ConfigPath` semantics derived from parsed path segments; string path segments are not split again and keys with literal dots remain unsupported by the v1 override language.
- Existing-site replacements reuse the original include site's source context for bare and explicit relative resolution. For nested include sites, this requires the source-local include-site path or an equivalent resolution base from Phase 6 internals.
- Brand-new explicit relative user include sites use the base config source as the only available Python-API source context. The synthetic include source should use the base `ConfigSource` and the requested include-site path for diagnostics; resolution of explicit relative targets is anchored at the base config file directory. Brand-new bare targets remain rejected.
- A brand-new include site may create a missing container path through `+path._include_=...`. It must not silently replace an existing concrete mapping or scalar at the container path; existing concrete component replacement requires an exact recorded file-defined include site.
- Recomposing a swapped subtree must preserve the original file-authored local sibling customizations at that include site. Add a narrow internal local overlay/customization payload or preserve the pre-expansion container mapping for recomposition; do not derive replay data from the already merged final subtree.
- User-authored `_replace_` in override strings is not a Phase 7 feature. Replacement semantics for user include swaps are expressed by targeting `_include_` at a known site or by adding an explicit brand-new include site.

## Scope Contract

- Phase 7 adds an internal user composition stage, not a new public artifact contract. It may add internal records and helper functions under `loom.config`, but must not add public root exports or new `ComposedConfig` fields.
- Phase 7 stage order is fixed only around this phase boundary: file source merge, file include expansion, all user include-composition overrides, then the existing ordinary value override pass and downstream stages. Do not implement Phase 9 recipe ordering changes in this phase.
- Existing-site include replacement is allowed for `path._include_=bare` only when `path._include_` exactly matches a recorded file-defined include site and the private recomposition context has source context sufficient for deterministic bare resolution. Do not infer existing sites from the composed tree shape or from mappings that merely look like components.
- Brand-new include sites must be authored with `+path._include_=./target.yaml`, `+path._include_=/abs/target.yaml`, or `+path._include_=file:///...`. A missing existing site without `+` remains a strict update failure. A brand-new bare include target fails with a structured source/context error. A brand-new include container that already exists in the recomposed config fails rather than merging over existing concrete content.
- User composition must never execute interpolation or resolver expressions to decide include targets. Resolver-dependent include target strings fail through existing include resolution policy.
- Recomposition loads included files through existing strict loading and recursive include expansion. It must preserve Phase 6 cycle detection, source-aware errors, local sibling merge semantics, `_replace_` marker rejection, and no raw source byte persistence. Existing-site recomposition replays only the original local sibling overlay for that include site; it must not carry over stale values from the replaced included file.
- Ordinary overrides remain strict updates or explicit additions and operate only on the recomposed concrete config, in their original relative order. They must not create or modify `_include_`, `_replace_`, `_copy_`, recipes, manifests, fingerprints, or source artifacts beyond this phase's composition stage.

## Design Impact

- Maintainability: isolates user composition from generic ordinary override application so later recipe, inspection, and artifact phases can reason about composition stages explicitly.
- Extensibility: preserves future CLI and sweep behavior by making Python API overrides flow through the same internal semantics without adding CLI-only shortcuts.
- Domain neutrality: treats user include swaps as plain mapping composition with no model, dataset, stage, or project-schema assumptions.
- Source-tree boundaries: keeps the work inside `loom.config` and config tests with no dependency on `loom.pipeline`, stores, CLI, plugin discovery, remote IO, or project code.

## Future Compatibility

- Phase 8 can enforce resolver security after user-composed include targets are present without needing to reinterpret composition-control overrides.
- Phase 9 can finalize recipe ordering after user composition while preserving the Phase 7 guarantee that ordinary overrides see recomposed include values.
- Phase 12 can expose the user composition stage through inspection records without changing Phase 7 behavior.
- Phase 13/14 can serialize user composition records and fingerprint inputs additively while preserving artifact-safe defaults.
- Future CLI and sweep phases can generate the same override strings and rely on Phase 7's strict existing-site vs brand-new include-site distinction.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Treat `path._include_=...` as an ordinary value override after expansion | The expanded concrete config no longer contains `_include_`, and this would not recompose component subtrees. |
| Allow brand-new bare user include sites | User-authored overrides lack the file-local mapping context needed for deterministic bare resolution. |
| Resolve existing-site bare replacements from the composed path alone | Nested include sites need the source-local include path from the file that authored the original include. |
| Preserve local customizations by reading values from the final expanded subtree only | Nested mapping customizations can be indistinguishable from included values after merge; recomposition needs an internal local overlay or pre-expansion context. |
| Add public manifest/provenance fields in Phase 7 | Artifact population and public inspection are later phases; this phase should keep records internal. |
| Add plugin, global search, remote, or resolver-backed include resolution | Explicitly out of scope for v1 and conflicts with deterministic artifact-safe composition. |
| Allow brand-new user includes to replace existing concrete mappings | Existing component replacement must be explicit through a known include site; otherwise stale-key behavior and intent are ambiguous. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| User composition records remain internal and may need additive reshaping | Keeps Phase 7 focused on behavior before public inspection and artifact contracts are populated. | Revisit in Phase 12/13 when inspection, manifests, source artifacts, and fingerprints serialize composition stages. |
| Brand-new explicit relative user includes are anchored to base config source context | The existing Python API has no separate override source file, and brand-new bare includes are rejected. | Revisit during v2 CLI planning if CLI-authored overrides gain an explicit source-context model. |
| Ordinary override errors may remain message-only | Phase 3 owns strict ordinary override behavior; Phase 7 only needs composition-specific source-aware errors. | Revisit if integration tests cannot assert source-context failures without structured ordinary override contexts. |

## Reviewability

- Expected PR size and shape: focused private user-composition helper(s), narrow Phase 6 include recomposition-context extension, compose-stage partitioning/order wiring, and targeted unit/integration/contract tests. No broad public API or artifact-schema diff.
- Files and areas to inspect: likely `src/loom/config/includes.py`, `src/loom/config/overrides.py`, `src/loom/config/compose.py`, `src/loom/config/source_maps.py` if recomposition context requires source-map handoff, `src/loom/config/errors.py`, `tests/unit/loom/config/test_includes.py`, `tests/unit/loom/config/test_overrides.py`, `tests/integration/config/test_compose_includes.py`, and new or existing `tests/integration/config/test_compose_overrides.py`.
- Scope-control checks: no resolver execution or resolver scanning; no recipe expansion behavior change beyond preserving order; no public inspection API; no new `ComposedConfig` fields; no manifest/provenance/source-artifact/fingerprint population; no raw source persistence; no CLI, run-store, network, plugin, remote, global search, pipeline import, root export, `_copy_`, or future recipe argument override syntax.

## Implementation Steps

1. Extend internal include expansion output with a private recomposition context keyed by composed include-site path. It should retain composed include-site path, source-local include-site path or equivalent resolution base, source context, original local sibling overlay values, and local customization metadata without making those records public artifacts.
2. Add a user-composition override classifier that consumes parsed overrides in order, identifies `_include_` composition overrides, applies include-composition overrides in parsed order, and leaves ordinary strict update/add overrides in their original relative order for the later ordinary override pass.
3. Implement existing-site include replacement: locate the recorded include site, resolve the new target using its source context, recursively expand the replacement include, reapply original local customizations, and replace the container subtree.
4. Implement brand-new explicit user include additions: require an add operation, a missing include container, and an explicit relative, absolute, or `file://` target; resolve explicit relatives from the base config source; reject bare, resolver-dependent, missing, unsupported, existing-container, or ordinary update-to-missing cases with source-aware composition errors.
5. Wire the stage into `compose_config` after file-defined include expansion and before the existing ordinary value override pass, ensuring ordinary overrides can update values introduced by recomposed includes without changing Phase 9 recipe behavior.
6. Add focused unit, contract, and integration coverage for successful swaps, brand-new include restrictions, recomposition source context, and phase boundaries without implementing later public artifacts.

## Test Plan

### Package Suite

- Status: required only if public exports or import behavior change; otherwise deferred for targeted implementation and covered by final PR validation.
- Expected paths: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py` if touched.
- Required assertions or deferral reason: no public exports are expected. If implementation touches package exports or optional loading, assert no user-composition helpers are exported at the root and `loom.config` still does not import pipeline, stores, CLI, plugin discovery, network clients, or heavyweight optional dependencies eagerly.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_includes.py`, `tests/unit/loom/config/test_overrides.py`, and possibly `tests/unit/loom/config/test_source_maps.py` if recomposition context changes source-map handoff.
- Required assertions or deferral reason: parsed override partitioning preserves ordinary override relative order while applying all include-composition overrides first; exact include-site path matching works; existing-site bare replacement uses the recorded source-local include context; nested existing-site replacements do not resolve from the composed path by mistake; recomposition reapplies only local sibling customizations over the replacement include and does not preserve stale replaced-file values; `_include_` markers do not remain in final recomposed output; brand-new bare include sites fail; brand-new explicit relative targets resolve from the base config directory; absolute and `file://` brand-new sites resolve under strict rules; brand-new include containers that already exist fail; resolver-dependent and unsupported include targets fail through existing include resolution policy; ordinary update/add override behavior is unchanged.

### Contract Suite

- Status: required for structured composition errors or new record serialization; otherwise narrowly deferred.
- Expected paths: `tests/contracts/test_config_error_contract.py` and/or a focused config user-composition record contract test if record classes expose serialization helpers.
- Required assertions or deferral reason: any new user-composition error contexts serialize as plain data with source path/kind/order, config path, directive, authored target, raw override/order, original include-site context where applicable, resolved/candidate path where available, and failure reason; no raw YAML bytes, resolver outputs, or non-plain payloads appear. If new recomposition records remain internal without `to_dict()`, contract coverage can stay on structured error serialization.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_overrides.py` and/or focused additions to `tests/integration/config/test_compose_includes.py`.
- Required assertions or deferral reason: `pipeline.model._include_=replacement` swaps an existing file-defined include site and recomposes the subtree; local sibling customizations survive the swap while stale replaced-file values do not; a nested existing-site bare swap resolves relative to the included file that authored the nested include; `+pipeline.dataset._include_=./dataset/tabular.yaml` creates a brand-new explicit include site relative to the base config file directory; `+pipeline.dataset._include_=tabular` fails as brand-new bare; adding an include site over an existing concrete `pipeline.dataset` fails; ordinary overrides can update values introduced by the replacement include; ordinary overrides keep their relative order after composition overrides are removed; source-context errors identify the user override and original include context where applicable.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 7 does not complete final public v1 orchestration, public inspection APIs, artifact population, or CLI behavior. Public e2e coverage starts in later phases once full composition order and artifact-safe public surfaces are wired.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: raw source snapshots, remote/plugin resolvers, network-backed includes, resolver runtime-value persistence, and CLI behavior are out of scope.

## Risks

- Existing Phase 6 records are too thin for nested bare replacements and local customization replay unless Phase 7 adds a narrow internal source-local context and local overlay payload.
- Partitioning overrides can accidentally change ordinary override ordering. Tests must prove all composition overrides run first while ordinary overrides preserve their relative order afterward.
- Brand-new explicit relative include sites rely on the base config source because Python API overrides have no file source of their own.
- Recomposition can leak old included values if it derives local customizations from the final expanded subtree instead of original local overlays.
- Error handling can become inconsistent if include-composition failures use ordinary override errors without source/context details.
- Compose wiring can drift into Phase 9/12/13 by changing recipes, public inspection fields, artifacts, fingerprints, or provenance too early.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/config/test_includes.py
uv run pytest tests/unit/loom/config/test_overrides.py
uv run pytest tests/integration/config/test_compose_includes.py
uv run pytest tests/integration/config/test_compose_overrides.py
uv run pytest tests/integration/config/test_compose_config.py
uv run pytest tests/contracts/test_config_error_contract.py
uv run pytest tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: private include recomposition context first; override classification second; existing-site replacement third; brand-new explicit include sites fourth; compose-stage ordering fifth; tests alongside each slice.
- Tests to run with each slice: run include unit tests after record/context changes; run override unit tests after partitioning; run include/override integration tests after replacement and brand-new include behavior; run compose integration and import-boundary tests after stage wiring.
- Decisions the executor must not revisit: `loom.config` remains persistence-free; `loom.pipeline` must not depend on `loom.config` or manifests; `_copy_` is unsupported; default artifacts are security-first and artifact-safe; resolver outputs and raw source bytes are not persisted by default; v1 is Python-API-only with no CLI commands; no plugin/remote/global search include resolvers; Phase 7 must not implement recipe expansion changes, resolver execution, final public compose orchestration, manifests/artifacts/fingerprints/persistence, CLI, or pipeline imports.
- Conditions that require stopping for the manager: existing-site bare replacement cannot be implemented without exact Phase 6 include-site context; recomposed subtrees cannot preserve local customizations without a broad public record redesign; brand-new explicit relative include semantics conflict with the base-config source policy; ordinary override relative ordering cannot be preserved; satisfying tests requires recipes, resolver execution, public inspection fields, manifests, fingerprints, raw source persistence, CLI, pipeline imports, network access, or new dependencies.
- Expanded-path refinement notes: completed. The plan now requires a private recomposition context with source-local include-site data and local overlay replay payload, base-config source context for brand-new explicit relative includes, all include-composition overrides before ordinary overrides, ordinary override relative order preservation, and source-aware include-composition errors.

## Refinement And Review Budget Status

- Phase execution plan draft: used
- Phase execution plan refine: used
- Phase implementation refinement: used
- PR body draft: used
- PR body refine: used
- PR review: used

## Completion Notes

- Draft plan: completed in this artifact by `loom_phase_planner`.
- Final phase execution plan: refined in this artifact by `loom_phase_planner`; implementation refinement budget and PR review budget are used.
- Implementation summary:
  - Added `split_include_and_ordinary_overrides` in `src/loom/config/overrides.py` and preserved existing semantics for strict update/add value overrides.
  - Extended include expansion records in `src/loom/config/includes.py` with recomposition context (`IncludeRecompositionContext`) and source-local include-site metadata needed for nested existing-site swaps.
  - Implemented a private user-composition stage in `src/loom/config/compose.py`:
    - Parse once, split include-composition overrides from ordinary overrides.
    - Apply include-composition overrides before ordinary overrides.
    - Support existing-site replacement with source-context replay of local customizations.
    - Support explicit brand-new `+..._include_=...` additions only, with explicit-target requirement for bare brand-new sites.
    - Preserve ordinary override relative order on recomposed concrete mappings.
  - Refinement pass tightened strict operation semantics so `+path._include_=...` fails against an existing recorded include site instead of replacing it.
  - Refinement pass wraps non-mapping user replacement targets as structured `ConfigIncludeExpansionError` values with user override metadata and include-site context.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/unit/loom/config/test_overrides.py tests/integration/config/test_compose_overrides.py` — 22 passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/unit/loom/config/test_includes.py tests/integration/config/test_compose_includes.py tests/integration/config/test_compose_config.py tests/contracts/test_config_error_contract.py tests/package/test_import_boundaries.py` — 73 passed.
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` — passed.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` — passed; wrote `build/test-summary.md`.
- Refinement summary: completed expanded-path implementation refinement for private-stage boundaries, exact Phase 6 include-site matching, source-local include context, local overlay replay, brand-new explicit relative source policy, override partitioning/order, source-aware errors, suite obligations, and implementation stop conditions. Manager-noted checks confirmed two phase-scoped blockers, both fixed and covered: strict add/update semantics for existing include sites and structured user-context errors for non-mapping replacement roots.
- Refinement scope:
  - Validation output reviewed: executor targeted checks, `make validate-pr`, `make test-summary`, and refreshed validation from this pass.
  - Blocking issues caused by this phase: `+..._include_=` could replace existing recorded include sites; non-mapping user replacement targets surfaced `ConfigLoadError` before composition-level user override context was attached.
  - Issues confirmed out of scope: no public root exports, no new `ComposedConfig` fields, no artifact/manifest/fingerprint/provenance population, no CLI, no pipeline imports, no resolver execution, no future recipe ordering changes, and no `_copy_`.
- Fixes made:
  - Existing recorded include sites now reject `add` operations with structured code `existing_include_site`.
  - Non-mapping replacement roots are wrapped as structured code `included_root_not_mapping` with override raw/order/path metadata, resolved path, and included source context.
- Tests or validation re-run:
  - Focused override/composition suite: 22 passed.
  - Broader phase-targeted include/compose/error/import suite: 73 passed.
  - PR gate: `make validate-pr` passed.
  - Suite summary: `make test-summary` passed.
- PR preparation:
- Draft pass completed on 2026-05-05 using `.codex/prompts/pr-body-draft.md`.
- PR body artifact: `docs/phases/config-user-composition-overrides-pr-body.md`.
- PR facts confirmed:
  - Branch: `codex/config-user-composition-overrides`.
  - Worktree: `/home/samcantrill/work/loom-worktrees/config-user-composition-overrides`.
  - Target branch: `develop`.
  - Stack predecessor: none.
  - Merge eligibility: merge-eligible after PR review because target is `develop`.
  - PR title: `Configuration - Phase 7: User Composition Overrides`.
  - Base commit / merge base with `develop`: `c3ab85a4cd1310ff25d8cb9053a904a7dc62f6ed`.
  - Draft commit at preparation start: `0e9823e65b5d6f3f415930a210a6e723bb688554`.
  - Upstream tracking branch: none configured locally.
- Final diff reviewed against `develop`: phase execution plan, private config composition/include/override changes, and focused unit/integration coverage only.
- Scope confirmed: private user-composition override stage only; no public root exports, no new `ComposedConfig` fields, no manifests/artifacts/fingerprints/provenance population, no CLI, no pipeline imports, no resolver execution, no recipe ordering changes, and no `_copy_`.
- Validation rerun during PR preparation:
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` — passed; Ruff, Pyright, default harness, config-extra harness, and build succeeded.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` — passed; refreshed `build/test-summary.md` with overall 651 passed, 0 failed, 8 skipped, 430 deselected.
- PR opening status: intentionally not opened in this draft pass because expanded path is active. PR body refine pass remains pending.
- Refine/open pass completed on 2026-05-05 using `.codex/prompts/pr-body-refine.md`.
- PR body verification:
  - Reviewed against the final diff, source implementation plan, phase execution plan, public PR template, phase PR body template, and refreshed validation evidence.
  - Confirmed `@samcantrill` remains near the top of the body and no GitHub reviewer request is included.
  - Confirmed the body describes only Phase 7 private user-composition overrides and does not claim future-phase work.
  - Refined the GitHub checks row so the public body remains accurate before remote CI exists.
- PR opened: https://github.com/samcantrill/loom/pull/33
- PR verification:
  - `gh pr view 33 --json baseRefName,headRefName,state,url` — `baseRefName=develop`, `headRefName=codex/config-user-composition-overrides`, `state=OPEN`, `url=https://github.com/samcantrill/loom/pull/33`.
  - Target branch: `develop`.
  - Stack predecessor: none.
  - Merge eligibility: merge-eligible after PR review because target is `develop`.
  - GitHub/auth limitations: none; sandboxed `gh auth status` reported an invalid token, but approved network-backed `gh auth status` succeeded before push and PR creation.
- PR review:
  - `loom_phase_reviewer` completed the single read-only PR review pass after GitHub had already merged PR #33.
  - Findings: none blocking. The review found no correctness, scope, import-boundary, domain-neutrality, or validation-evidence issues.
  - Residual non-blocking risk: dedicated Phase 7 integration coverage exercises explicit-relative brand-new include additions and bare rejection; absolute and `file://` brand-new additions rely on the shared include resolver path.
  - Review budget: consumed.
  - Merge eligibility check: PR #33 targeted `develop`, head was `codex/config-user-composition-overrides`, and CI `checks` succeeded, so the PR was merge-eligible.
- Merge notes:
  - `gh pr view 33 --json baseRefName,headRefName,state,url,mergedAt,mergeCommit,statusCheckRollup` reported `state=MERGED`, `baseRefName=develop`, `headRefName=codex/config-user-composition-overrides`, `mergedAt=2026-05-05T10:50:29Z`, merge commit `e15279dee60920c8d943ecd9d3fbc1dbaaa3d89f`, and CI `checks` conclusion `SUCCESS`.
  - The control checkout fast-forwarded `develop` to `origin/develop` after the merge.
- Stack maintenance:
  - No successor phase branch depended on `codex/config-user-composition-overrides` at merge time.
  - Phase branch and worktree cleanup are safe after this metadata update.
- Remaining blockers: none.
