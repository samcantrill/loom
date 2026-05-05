# Phase 5 Execution Plan: Include Resolution Primitives

## Metadata

- Status: refined phase execution plan
- Feature focus: Configuration
- PR title: `Configuration - Phase 5: Include Resolution Primitives`
- Branch: `codex/config-include-resolution`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-include-resolution`
- Phase execution plan path: `docs/phases/config-include-resolution.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 5 - Include Resolution Primitives
- Stack predecessor: none
- Base branch: `develop`
- Base commit: `29163292885a0a2543c4e66614b962f1cda1893f`
- Target branch: `develop`
- Merge eligibility: merge-eligible after PR review because target is `develop`
- Workflow path: expanded path
- Workflow path rationale: include target resolution defines durable path, URI, safety, and resolver-dependent failure behavior used by Phase 6+ recursive include expansion.
- Successor dependency notes: Phase 6 file-defined recursive includes must consume these primitives without redefining target classification or error semantics. Later user composition phases may reuse the same resolver with stricter source-context rules for user-authored include swaps.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact.
- Refine pass: completed by `loom_phase_planner`; expanded-path refinement tightened bare-name grammar, include-site path assumptions, explicit path and `file://` handling, unsafe normalization behavior, structured error scope, resolver-dependent target detection, and suite obligations.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid, but approved outside-sandbox `gh auth status` succeeded; `gh auth setup-git` and `git fetch origin` succeeded. Local `develop`, `origin/develop`, and worktree base all resolved to `29163292885a0a2543c4e66614b962f1cda1893f`. `git worktree add` required approved access because writing Git refs was blocked by the sandbox.
- Blockers: none.

## Objective

Define and test strict local include target resolution primitives for accepted v1 target forms without loading or expanding included config content.

## Full-Plan Context

Phases 1-4 established config/pipeline boundaries, artifact skeletons, strict loading/errors, strict overrides and merge behavior, and source-authored overlay tracking. Phase 5 turns source context plus a mapping key path into one deterministic include target result or one structured failure. Phase 6 will use this resolver while recursively expanding file-authored includes; Phase 7 will reuse it for user include swaps with additional source-context restrictions.

Future behavior remains out of scope: recursive include expansion, include stacks/cycles, sibling merge, include replacement requirements, user-authored include replacement, plugin/remote resolvers, recipe/resolver ordering changes, public inspection APIs, manifest/provenance/fingerprint/source-artifact population, raw source persistence, run-store writes, and CLI commands.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1, 2, 3, and 4 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`, all earlier v1 phases are merged, and local/remote `develop` matched `29163292885a0a2543c4e66614b962f1cda1893f` after fetch.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after the Phase 5 PR is merged and no successor phase branch depends on `codex/config-include-resolution`.

## Source Phase Summary

- Goal: resolve accepted include target forms strictly and deterministically.
- Required scope: bare-name resolution from including file plus mapping key path; exact relative paths; exact absolute paths; `file://` URIs; `.yaml` bare-name behavior; no extension probing; unsupported URI scheme failures; resolver-dependent include target failures.
- Required checkpoints: target classification is deterministic; accepted target forms produce exact filesystem paths/URI-derived local paths; explicit paths require exact filenames; bare names are simple component names that append exactly `.yaml`; unsafe, missing, ambiguous, unsupported, and resolver-dependent targets fail with source/path context.
- Acceptance criteria: every accepted target form resolves deterministically; explicit paths require exact filenames; bare names append exactly `.yaml`; ambiguous, missing, unsafe, unsupported, or resolver-dependent targets fail.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/source_maps.py` provides immutable `ConfigPath` tuples, `format_config_path(...)`, and per-path `ConfigSource` authorship; `src/loom/config/load.py` resolves config source paths and builds structured `ConfigLoadError` context; `src/loom/config/errors.py` has `ConfigErrorContext` and structured load errors but no include-specific error class yet; `src/loom/config/interpolation.py` currently rejects resolver-style interpolation during runtime interpolation validation; `src/loom/config/compose.py` keeps current public v0-oriented composition behavior.
- Existing tests or harness behavior: source-map coverage lives in `tests/unit/loom/config/test_source_maps.py` and `tests/integration/config/test_source_map_integration.py`; structured error contracts live in `tests/contracts/test_config_error_contract.py`; package import boundaries live in `tests/package/test_import_boundaries.py` and `tests/package/test_config_api.py`; compose tests currently preserve `_include_` as ordinary authored data.
- Import-boundary or dependency constraints: work should stay under `src/loom/config/` and config tests. Do not add pipeline, runner, store, CLI, plugin, project-code, network, or heavyweight dependency imports.

## In-Scope Work

- Add an internal include-target resolution helper, likely in a focused `src/loom/config/includes.py`, that accepts an authored target string, the including `ConfigSource`, and the include-site `ConfigPath` for the `_include_` key.
- Define a small internal result shape for resolved local include targets, including enough context for later phases to know the authored target, include site, source file, resolved path, and whether the target escaped the including config tree by explicit author choice.
- Classify accepted target forms deterministically: bare names, exact explicit relative paths, exact absolute paths, and `file://` URIs.
- Resolve bare names from the including file directory plus the parent mapping path of the `_include_` key, then append exactly `.yaml`; do not probe `.yml`, append extensions for explicit paths, or try fallback candidates.
- Resolve exact explicit relative paths from the including file directory and require the normalized target to exist as the exact authored filename.
- Resolve exact absolute paths and local-only `file://` URIs to local filesystem paths, requiring exact existing files and rejecting unsupported or ambiguous URI forms.
- Fail on unsupported URI schemes and resolver-dependent include target strings before any runtime interpolation can execute.
- Fail on unsafe normalization where a target attempts to escape the implicit bare-name config subtree without using an explicit relative path, absolute path, or `file://` URI.
- Prefer an internal `ConfigIncludeResolutionError` in `loom.config.errors` only if include failures need a distinct subclass. It should subclass `_ConfigError`, reuse `ConfigErrorContext`, and not be exported from `loom.config` root in this phase.

## Out-of-Scope Work

- Scanning full config trees for `_include_` placement or value type.
- Loading included YAML files or validating included document shape.
- Recursive include expansion, include stack records, include cycle detection, sibling override merge, or local customization records.
- Requiring or interpreting `_replace_` for include swaps over existing lower-precedence mapping content.
- User-authored include replacement, user composition override ordering, or CLI-authored include behavior.
- Plugin, remote, registry, global search path, or custom include resolver APIs.
- Manifest, provenance, source artifact, fingerprint, redaction, public inspection, or additive `ComposedConfig` population.
- Raw source snapshots, run-store writes, public CLI commands, pipeline imports, or project-code imports.

## Assumptions

- The resolver helper can remain internal in Phase 5; public inspection and artifact contracts remain later-phase scope.
- `ConfigSource.path` is already an absolute local source path from `load_config` for base and overlay files. Tests may construct equivalent `ConfigSource` values directly.
- Include-site paths are immutable `ConfigPath` tuples pointing to the `_include_` key. The helper should require a non-empty path ending in the exact string segment `"_include_"`; bare-name directory derivation uses only `include_site_path[:-1]`.
- Include-site path segments before `_include_` must be string mapping-key segments for Phase 5. Integer/list-index segments are rejected as invalid include-site context instead of being treated as filesystem directories. Future list/include placement validation remains Phase 6 scope.
- Path tuple string segments are exact mapping keys and must not be split on literal dots. A segment such as `"model.v1"` is one directory name for bare resolution, while empty, `"."`, `".."`, or separator-containing string segments are unsafe for bare-name directory derivation and should fail rather than normalize silently.
- A bare-name target is a non-empty ASCII component token matching `[A-Za-z0-9_-]+`. Literal dots are not allowed, so `resnet50.v2`, `.hidden`, and `resnet50.yaml` are not bare names. Bare names have no path separators, no URI scheme, no dot segments, and no explicit suffix/extension.
- Explicit relative path indicators are `./`, `../`, embedded `/`, or an exact basename with an explicit suffix such as `resnet50.yaml`. `resnet50.yaml` is an exact relative path from the including file directory, not a bare name, and must not be resolved through the mapping-key directory.
- Any `${...}` token anywhere in the authored target makes the target resolver-dependent for Phase 5 and must fail before OmegaConf or any runtime resolver execution. Do not distinguish `${path}` from `${oc.env:...}` in this phase.
- Phase 5 uses POSIX-local filesystem semantics in this repository context. Windows drive paths, UNC paths, and Windows-style `file://` drive forms are not accepted positive target forms on POSIX; only add portable rejection tests if implementation handles them explicitly.
- File existence checks are part of the primitive because missing exact targets are an acceptance criterion. Reading/parsing the target file is Phase 6 scope.

## Scope Contract

- The resolver returns exactly one local file target or raises one structured config error. It must not return multiple candidates or silently choose between alternatives.
- Bare target `resnet50` at include site `("model", "_include_")` in `/project/configs/experiment.yaml` resolves to `/project/configs/model/resnet50.yaml`. Bare target `small` at `("model", "encoder", "_include_")` resolves to `/project/configs/model/encoder/small.yaml`.
- Bare resolution must remain under `including_file.parent / *parent_mapping_segments`. The implementation should verify the normalized candidate stays under that derived directory before the final filename check. Explicit relative, absolute, and `file://` escapes are allowed only because the author made the escape explicit and the exact target exists.
- Explicit relative targets `./local.yaml`, `../shared/optimizer.yaml`, `components/resnet50.yaml`, and `resnet50.yaml` resolve from the including file directory, may leave the implicit config subtree when the authored target says so, and require that exact filename to exist.
- Absolute path and `file://` targets are explicit local filesystem choices. They are accepted only for local file targets that normalize to an exact existing file.
- `file://` support is local only. Reject non-empty netloc/host values, query strings, fragments, params, empty paths, directory targets, malformed or ambiguous percent escapes, and decoded paths that cannot be represented as one deterministic local path. Treat `file://localhost/...` as non-empty host and reject it for Phase 5.
- Unsupported URI schemes such as `s3://`, `https://`, `pkg://`, or unknown scheme-like targets fail with an unsupported-scheme code and no resolver fallback.
- Bare names append exactly `.yaml`; explicit paths never probe `.yml`, `.yaml`, suffix variants, directories, or extensionless fallbacks. An authored exact path to `resnet50.yml` may be treated only as that exact file if the implementation chooses to support exact YAML filenames generally, but it must never be discovered as fallback for `resnet50` or `resnet50.yaml`.
- Unsafe implicit normalization fails when the include-site path or bare-name-derived path would escape its derived directory/root or otherwise cannot be normalized to a single safe local file under the implicit bare-name layout.
- Resolver-dependent targets fail before runtime interpolation, and errors must not include resolved resolver values.
- Missing targets fail after deterministic candidate construction, with context that includes source path, include-site config path, authored target, and deterministic candidate/resolved path.
- Invalid include-site context, including a path not ending in `_include_` or containing list-index segments, fails in the primitive with structured context. It is not a caller precondition because Phase 6 will consume this helper for source-aware errors.
- The helper must not call `load_config`, modify `compose_config` public behavior, expose new root package symbols, or persist resolver output/raw source bytes.

## Design Impact

- Maintainability: isolates target classification and path safety from recursive include expansion so Phase 6 can focus on traversal, cycle handling, sibling merge, and source-aware composition.
- Extensibility: keeps local path and `file://` behavior explicit while leaving future plugin/remote resolver contracts unimplemented and unreserved beyond structured unsupported failures.
- Domain neutrality: resolves authored config file targets without interpreting model, dataset, stage, or project semantics.
- Source-tree boundaries: work stays in `loom.config` helper/error modules and tests, with no pipeline, store, runner, CLI, plugin, network, or project-code dependencies.

## Future Compatibility

- Phase 6 can use the same result shape to load included files, report include stacks, detect cycles, and record sibling customization context.
- Phase 7 can reuse the resolver for explicit user include targets while applying separate rules for bare user replacements at known file-defined include sites.
- Phase 13/14 can later serialize authored targets, explicit-escape indicators, and deterministic resolved metadata into provenance, manifests, source artifacts, and fingerprints without treating absolute paths as semantic identity.
- Future plugin/remote resolver work can add new resolver families explicitly instead of inheriting silent URI fallback behavior.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Extension probing for `.yaml`, `.yml`, or extensionless paths | Creates ambiguous authored intent and conflicts with the v1 accepted `.yaml` bare-name rule. |
| Global search paths or registry aliases | Makes component origin implicit and is explicitly deferred out of v1. |
| Loading included files in Phase 5 | Would mix target policy with recursive expansion and document-shape validation owned by Phase 6. |
| Treating interpolation in include targets as runtime-resolvable | Composition control flow must be decidable before runtime resolver execution and must not depend on resolver outputs. |
| Exposing a public include resolver API now | Public inspection/API shape belongs to Phase 12 after include expansion and user composition records exist. |
| Allowing literal-dot bare names | Conflicts with the simple component-token grammar and can be confused with explicit suffixes or future dotted shorthand. Authors can use explicit paths for such filenames. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Include result records remain internal and may need additive fields for include stacks or artifacts | Keeps Phase 5 focused on deterministic target policy before Phase 6 proves traversal needs. | Revisit during Phase 6 if recursive expansion needs context not captured by the primitive result. |
| `ConfigIncludeResolutionError`, if added, remains internal to `loom.config.errors` and unexported from `loom.config` root | Avoids freezing public API before full composition orchestration while still giving tests and callers a structured config-domain error. | Revisit during Phase 6/12 when include errors are surfaced through public compose/inspection paths. |

## Reviewability

- Expected PR size and shape: focused internal helper plus include-specific error tests; no compose orchestration, public return fields, manifest/provenance population, root public API export, or recursive expansion.
- Files and areas to inspect: likely `src/loom/config/includes.py`, `src/loom/config/errors.py`, `tests/unit/loom/config/test_includes.py`, `tests/unit/loom/config/test_config_errors.py` if a new error subclass is added, `tests/contracts/test_config_error_contract.py` if structured include errors serialize through `ConfigErrorContext`, and package tests to confirm no root public API changes if exports are touched.
- Scope-control checks: no YAML loading of target files; no traversal of config trees; no include cycles/stacks; no sibling merge; no `_replace_` include-swap logic; no user composition; no recipes/resolver runtime changes; no public inspection API; no artifact/fingerprint/source-record population; no persistence; no CLI; no pipeline imports.

## Implementation Steps

1. Add internal include target types and resolver helper around `ConfigSource`, `ConfigPath`, and existing path formatting/context helpers, validating include-site paths end in `_include_`.
2. Implement deterministic target classification for bare, relative, absolute, local-only `file://`, unsupported URI, ambiguous, unsafe, missing, and resolver-dependent cases.
3. Add include-specific structured error handling, reusing `ConfigErrorContext` and keeping raw source bytes/resolver outputs out of error payloads.
4. Add focused unit tests for every accepted form and failure branch, using temporary filesystem fixtures for exact-file and missing-file behavior.
5. Add contract/package tests only if the implementation exposes a new structured include error/result shape beyond an internal module.

## Test Plan

### Package Suite

- Status: required if exports/imports change; otherwise deferred for targeted implementation and covered by final PR validation.
- Expected paths: `tests/package/test_config_api.py` and `tests/package/test_import_boundaries.py` if a new include error class or helper is exported.
- Required assertions or deferral reason: no public package exports are expected. If implementation touches `loom.config.__init__` or package exports, assert `ConfigIncludeResolutionError` and resolver helpers are not added to the root public API, and assert config imports remain cheap and do not pull in pipeline, stores, CLI, plugin discovery, network clients, or heavyweight optional dependencies.

### Unit Suite

- Status: required.
- Expected paths: new `tests/unit/loom/config/test_includes.py`, plus `tests/unit/loom/config/test_config_errors.py` if a new error subclass is added.
- Required assertions or deferral reason: bare names match only `[A-Za-z0-9_-]+`, reject empty targets, literal dots, suffixes/extensions, URI schemes, path separators, and dot segments, derive directories from including source plus parent mapping path, and append exactly `.yaml`; include-site paths must end in `_include_`; list-index include-site segments fail; mapping-key string segments are exact and are not split on dots; nested bare include paths work with exact string segments; unsafe mapping path segments or implicit normalization fail; explicit relative paths using `./`, `../`, embedded `/`, and exact suffixed basenames such as `resnet50.yaml` resolve from the including file directory and require exact filenames; absolute paths require exact existing files; local-only `file://` paths require exact existing files and reject hosts, query, fragment, params, empty paths, directories, and malformed/ambiguous percent escapes; explicit `.yaml` paths are not suffixed again; no `.yml` or fallback probing happens; unsupported schemes fail; ambiguous URI/path forms fail; any `${...}` target fails before interpolation; missing targets report deterministic candidate and include-site context; explicit relative/absolute/`file://` escapes are accepted only when the exact target exists.

### Contract Suite

- Status: required if include-specific structured errors are added; otherwise deferred.
- Expected paths: `tests/contracts/test_config_error_contract.py` or a new focused config include error contract test.
- Required assertions or deferral reason: if a new `ConfigIncludeResolutionError` or equivalent structured error exists, assert `to_dict()` carries stable `ConfigErrorContext` fields plus plain-data include details such as authored target, include site, candidate/resolved path, scheme, and safety reason, with no raw source bytes or resolved resolver values. Confirm the subclass reuses `_ConfigError` and `ConfigErrorContext`. If errors reuse existing structured load/config context without a new serialized shape, note the deferral in the PR body.

### Integration Suite

- Status: deferred.
- Expected paths: none required for Phase 5.
- Required assertions or deferral reason: recursive include expansion and compose orchestration are out of scope. Integration coverage becomes required in Phase 6 when the resolver is consumed by file-authored include traversal.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 5 does not expose public v1 include behavior through `compose_config`; representative public e2e coverage starts after full composition orchestration is wired in later phases.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: raw source snapshots, remote/plugin resolvers, network-backed includes, resolver runtime-value persistence, and CLI behavior are out of scope.

## Risks

- Target classification can become too permissive if URI-like strings are treated as paths after unsupported-scheme parsing fails; fail closed on scheme-like targets.
- Bare-name safety can be weakened by accepting separators, literal dots, dot segments, suffixes, empty values, or normalization escapes as bare names; keep bare names simple and exact.
- Include-site path ambiguity can leak into filesystem layout if literal-dot mapping keys are split or list indexes become directories; use exact string segments only and fail on list-index segments.
- `file://` parsing can accidentally accept host, query, fragment, params, or percent-decoding variants that are not one local file; reject ambiguous forms explicitly.
- Error payloads can leak runtime values if resolver-dependent targets are interpolated before failure; detect interpolation syntax textually and fail before resolver execution.
- Introducing public exports too early could freeze the wrong include result/error shape before Phase 6 and Phase 12.
- File existence tests can accidentally parse/read YAML content; Phase 5 should stop at path existence and regular-file checks.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/config/test_includes.py
uv run pytest tests/unit/loom/config/test_config_errors.py tests/contracts/test_config_error_contract.py
uv run pytest tests/package/test_config_api.py tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: internal include result/error type first, include-site path validation and bare-name grammar second, deterministic explicit path/URI classifier third, filesystem exact-target and safety checks fourth, structured error context fifth, focused unit/contract/package tests sixth.
- Tests to run with each slice: run the new include unit tests after helper work; run config error unit/contract tests after adding error classes or context payloads; run package/import tests only if exports or import surfaces change.
- Decisions the executor must not revisit: no global search path; no plugin/remote resolvers; bare names are `[A-Za-z0-9_-]+` only and append exactly `.yaml`; literal-dot bare names are rejected; include-site paths end in `_include_` and list-index segments are rejected; mapping-key string segments are exact and not dot-split; `resnet50.yaml` is an exact relative path from the including file directory; explicit paths are exact; local-only `file://` rejects host/query/fragment/params/directories/ambiguous percent escapes; any `${...}` target fails before interpolation; no recursive expansion; no user include swaps; no public inspection API; no root public API export; no manifest/provenance/fingerprint/source-artifact population; no persistence or CLI; no pipeline imports.
- Conditions that require stopping for the manager: deterministic resolution cannot be implemented without changing public `compose_config` fields before Phase 12; accepted target forms require a new public resolver API; safe path behavior conflicts with the accepted explicit escape rules; source context from Phase 4 is insufficient to derive bare-name paths; satisfying tests requires recursive loading/expansion, include stacks/cycles, user composition, resolver execution, artifact population, optional dependencies, network access, or pipeline imports.
- Expanded-path refinement notes: completed; bare-name grammar, include-site path assumptions, exact mapping-key handling, explicit relative filename behavior, local-only `file://` handling, unsafe normalization, structured error scope, resolver-dependent target detection, and suite obligations are now recorded for implementation.

## Refinement And Review Budget Status

- Phase execution plan draft: used
- Phase execution plan refine: used
- Phase implementation refinement: used
- PR review: unused

## Completion Notes

- Draft plan: completed in this artifact by `loom_phase_planner`.
- Final phase execution plan: refined by `loom_phase_planner` in this artifact; implementation refinement budget is now used and PR review budget remains unused.
- Implementation summary:
  - Added internal include target resolver in `src/loom/config/includes.py` with deterministic classification for bare-name, explicit relative, absolute, and local `file://` forms.
  - Added `ConfigIncludeResolutionError` to `loom.config.errors` (unexported from package root) and structured source/site/error-context payloads for resolver failures.
  - Added `tests/unit/loom/config/test_includes.py` covering accepted forms and documented failure branches for this phase.
  - Added include-error shape and contract coverage in `tests/unit/loom/config/test_config_errors.py` and `tests/contracts/test_config_error_contract.py`.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/config/test_includes.py` (30 passed)
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/config/test_config_errors.py tests/contracts/test_config_error_contract.py` (10 passed)
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/package/test_config_api.py tests/package/test_import_boundaries.py` (17 passed)
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run ruff check src/loom/config/includes.py tests/unit/loom/config/test_includes.py tests/unit/loom/config/test_config_errors.py tests/contracts/test_config_error_contract.py` (passed)
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pyright src/loom/config/includes.py tests/unit/loom/config/test_includes.py tests/unit/loom/config/test_config_errors.py tests/contracts/test_config_error_contract.py` (0 errors, 0 warnings)
- Refinement summary: completed on 2026-05-05; tightened explicit-relative classification so standalone dot-prefixed names are rejected unless authored with a documented relative indicator, required `file://` instead of ambiguous `file:/` forms, normalized returned and error candidate paths, rejected invalid UTF-8 percent escapes, and narrowed include-test `ConfigSource.kind` typing for Pyright.
- User-authorized blocker resolution: completed on 2026-05-05; added bare-name-only containment validation so a normalized candidate must remain under the derived config directory path before final file validation, while preserving explicit relative, absolute, and `file://` escape behavior.
- Blocker-resolution validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/unit/loom/config/test_includes.py` (31 passed)
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run ruff check src/loom/config/includes.py tests/unit/loom/config/test_includes.py` (passed)
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pyright src/loom/config/includes.py tests/unit/loom/config/test_includes.py` (0 errors, 0 warnings)
- PR preparation: not performed (user requested stop after implementation and initial validation).
- Stack maintenance: none changed; no successor dependency in-flight.
- Remaining blockers: none.
