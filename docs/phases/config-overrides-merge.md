# Phase 3 Execution Plan: Overrides And Merge Primitives

## Metadata

- Status: in_progress
- Feature focus: Configuration
- PR title: `Configuration - Phase 3: Overrides and Merge Primitives`
- Branch: `codex/config-overrides-merge`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-overrides-merge`
- Phase execution plan path: `docs/phases/config-overrides-merge.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 3 - Overrides And Merge Primitives
- Stack predecessor: none
- Base branch: `develop`
- Base commit: `dd1ff1b`
- Target branch: `develop`
- Merge eligibility: merge-eligible after PR review approval because this is a root phase targeting `develop`; Phases 1 and 2 plus their blocker-resolution follow-ups are merged into `develop`.
- Workflow path: expanded path
- Workflow path rationale: this phase hardens public `compose_config(..., overrides=...)` behavior and the merge primitive used by overlays, includes, and later user composition. It has durable API/composition-order impact even though the implementation should stay helper-focused, so one phase-plan refine pass is required before implementation begins.
- Successor dependency notes: Phase 4 source-authored overlays, Phase 6 recursive includes, Phase 7 user composition overrides, Phase 12 public orchestration, and Phase 14 fingerprints all depend on these strict override and merge semantics. This phase must leave source authorship, include expansion, recipe order, artifact population, persistence, and CLI behavior for later phases.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact.
- Refine pass: completed by `loom_phase_planner`; expanded-path refinement tightened `_replace_` semantics, override parent-creation behavior, compose/recipe compatibility boundaries, error-structure decisions, suite obligations, and executor stop conditions.
- Setup limitations: branch and worktree were created from local `develop`; initial sandboxed worktree creation could not create the nested `codex/...` branch ref, then succeeded with approved escalated Git worktree access.
- Blockers: none.

## Objective

Implement the strict override parser/application language and recursive merge primitive that later v1 composition stages can reuse without inventing alternate semantics.

## Full-Plan Context

Phase 1 established config artifact skeletons and pipeline/config boundaries. Phase 2 established strict YAML loading and structured config errors. Phase 3 now tightens the existing v0 override and merge helpers: ordinary `path=value` overrides update existing paths only, `+path=value` adds missing paths only, override values parse to typed plain data, dot paths split on literal dots without escaping, mappings recursively merge, scalar/list/null values replace, and `_replace_: true` is the only whole-section replacement marker.

Future behavior remains out of scope: Phase 4 source-authored overlay metadata, Phase 5 include target resolution, Phase 6 recursive include expansion, Phase 7 user include swaps and post-file-composition override ordering, Phase 8 resolver security, Phase 9 recipes, Phase 10 schema boundaries, Phase 12 public inspection/orchestration, Phase 13 artifact population, Phase 14 fingerprints, Phase 15 raw snapshot policy, and Phase 16 docs/e2e hardening.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: the user selected current `develop`; Phase 1 and Phase 2 are merged and blocker-resolved; current `develop` includes PR #25, follow-up PR #26, and metadata commit `dd1ff1b`.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after this phase PR is merged and no successor phase branch depends on `codex/config-overrides-merge`.

## Source Phase Summary

- Goal: implement strict override and merge primitives.
- Required scope: strict `path=value` update overrides, explicit `+path=value` add overrides, typed override parsing, simple dot paths with no escaping, recursive mapping merge, scalar/list/null replacement, and strict `_replace_` handling.
- Required checkpoints: update overrides fail on missing paths; add overrides fail on existing paths; mapping-over-mapping without `_replace_` recursively merges; `_replace_: true` is the only way to request whole-section mapping replacement and fails when unnecessary or invalid; scalar/list/null replacements do not require `_replace_`; lists replace as whole lists.
- Acceptance criteria: helper behavior is covered with focused unit tests; public `compose_config` override behavior changes only through existing helper wiring needed for override tests; no include, recipe, persistence, CLI, provenance population, or source-authored overlay behavior is implemented.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/overrides.py` already parses update/add operations, typed scalars, JSON arrays/objects, and applies overrides; `src/loom/config/merge.py` already recursively merges mappings and replaces scalar/list/null values; `src/loom/config/provenance.py` owns `ParsedOverride`; `src/loom/config/errors.py` has structured loader context but override/merge errors are still message-only `ConfigError` subclasses; `src/loom/config/compose.py` currently applies overrides before recipe expansion as v0 behavior, which Phase 3 may test for strict ordinary override helper behavior but must not redesign into the final v1 order.
- Existing tests or harness behavior: focused override tests live in `tests/unit/loom/config/test_overrides.py`; merge tests live in `tests/unit/loom/config/test_merge.py`; compose helper tests live in `tests/unit/loom/config/test_compose.py`; current integration compose tests are v0-oriented and should not become full v1 orchestration tests in this phase.
- Import-boundary or dependency constraints: work should remain under `src/loom/config/` and config unit/contract/package tests. Do not add heavyweight dependencies, do not import pipeline, execution, stores, CLI, plugin discovery, or project code, and do not make `loom.pipeline` depend on config helpers.

## In-Scope Work

- Harden override parsing for `path=value` updates and `+path=value` additions with ordered `ParsedOverride` records.
- Parse override values to plain data for exact `true`, `false`, `null`, integers, finite floats, JSON arrays, JSON objects, and strings otherwise.
- Define dot-path behavior as simple literal splitting on `.`, with no escaping and no list-index traversal.
- Apply update overrides strictly: every parent segment must exist and be a mapping, and the final key must already exist.
- Apply add overrides strictly: the final key must not exist. Parent creation for missing mapping parents is allowed only for `+` add operations, and traversal through a scalar/list/null parent fails.
- Preserve override order and apply sequentially so earlier operations can create or update paths observed by later operations.
- Harden recursive merge behavior: mapping/mapping merges recurse, scalar/list/null values replace, plain-data validation remains enforced, and inputs are not mutated.
- Add `_replace_: true` handling to the merge primitive: when a higher-precedence mapping is merged over an existing lower-precedence mapping at the same path, `_replace_: true` discards the lower-precedence mapping before applying the higher-precedence mapping and is omitted from the returned config.
- Enforce strict `_replace_` failures: invalid values; use where the lower-precedence value is absent; use where the lower-precedence value is not a mapping; or use where the higher-precedence value is not the mapping that owns the directive. `_replace_` is required only to request mapping-over-mapping whole-section replacement. Absence of `_replace_` means recursive merge for mapping-over-mapping and must not fail merely because a lower-precedence mapping exists. Ordinary scalar, list, `null`, or mapping-over-non-mapping replacements do not require `_replace_`.
- Keep override and merge errors as stable `OverrideParseError`, `OverrideApplyError`, and `ConfigMergeError` subclasses in this phase. They may remain message-only if tests assert stable exception classes and behavioral cases. Add `ConfigErrorContext` only if it can be done locally without broadening scope; do not require it for Phase 3 because Phase 2 structured context was loader-focused and no public CLI/inspection API consumes override/merge diagnostics until later phases.
- Add focused unit tests for parser values, invalid override forms, update/add success and failure, ordering, merge behavior, `_replace_` required/unnecessary/invalid cases, and list replacement.
- Add contract tests only if the implementation exposes new override or merge record/context shapes beyond existing `ParsedOverride`.

## Out-of-Scope Work

- Include loading, include target resolution, recursive include expansion, include stacks, include provenance, and include-related source context.
- Source-authored overlay authorship, source maps, and per-value source provenance for overlays.
- Recipe expansion changes, recipe catalog hardening, recipe manifests, and recipe/override ordering beyond preserving existing helper wiring needed by current override tests.
- Resolver scanning, resolver execution, resolver-dependent composition failures, interpolation policy changes, and artifact-safe resolver metadata.
- Schema validation, `_schema_` rejection, project pass-through validation, and Loom-owned envelope validation changes.
- Public `inspect_config_composition`, additive `ComposedConfig` v1 fields, full accepted `compose_config` ordering, public orchestration refactors, and e2e v1 composition flows.
- Persistence, run-store writes, manifests/provenance/source/fingerprint population, raw source snapshots, and CLI commands.
- Advanced override syntax: escaped literal-dot keys, list indexing, list patching, deletion, insertion, splice operators, Hydra defaults lists, `_copy_`, or broad schema-aware additions.

## Assumptions

- `ParsedOverride` remains the override parse result for this phase; adding fields is acceptable only when needed for strict behavior or structured diagnostics and must preserve existing round-trip compatibility.
- Override parser behavior should stay Python-API-friendly and future CLI-ready, but v1 ships no CLI commands.
- JSON-quoted scalar strings are the preferred way to author literal strings that look like typed values if the parser supports them without weakening the plain-data contract.
- `_replace_` validation belongs in the merge primitive now so Phase 4 overlays and Phase 6 includes can reuse one behavior instead of duplicating replacement logic.
- Override/merge errors can remain message-only in Phase 3 because the immediate contract is helper behavior, stable exception classes, and future-compatible operation records. The executor should not convert every override/merge failure to `ConfigErrorContext` unless that change is small and local.

## Scope Contract

- Public override language for this phase:
  - `path=value` is a strict update. It fails when any parent segment is missing, any parent segment is not a mapping, or the final key is absent.
  - `+path=value` is an explicit add. It fails when an existing parent segment is not a mapping or the final key already exists. Missing parent segments may be created as mappings only for `+` add operations.
  - Add parent creation is sequential and local to the override application result: a later override can update or add beneath a parent created by an earlier `+` override, but update overrides must never create parents themselves.
  - Neither add nor update may traverse into lists, scalars, or `null`. Numeric-looking path segments are ordinary mapping keys, not list indexes.
  - Paths split on literal dots. Empty segments are invalid. No escaping, list indexes, deletion, or patch operations exist in v1.
  - Overrides apply in caller order and later overrides see earlier changes.
- Typed parser contract:
  - Exact `true`, `false`, and `null` parse to booleans and `None`.
  - Integer-looking values parse to `int`.
  - Float-looking values parse to finite `float`; non-finite values fail.
  - Values beginning with `[` or `{` parse as JSON arrays/objects and must normalize to plain data.
  - Other values remain strings, preserving authored whitespace except where existing local parser behavior intentionally strips control syntax.
- Merge contract:
  - Mapping plus mapping recursively merges.
  - Mapping plus mapping without `_replace_` is always recursive merge, including when the higher-precedence mapping only adds keys, only updates existing child keys, or does both. This must not be treated as an error or implicit whole-section replacement.
  - A higher-precedence mapping may replace a lower-precedence mapping as a whole section only when the higher-precedence mapping contains `_replace_: true`. The returned mapping contains the higher-precedence siblings after the marker is consumed and none of the lower-precedence mapping's keys survive unless re-authored in the higher-precedence mapping.
  - Scalar, list, and explicit `null` overlay values replace the lower-precedence value.
  - A higher-precedence mapping over a lower-precedence scalar/list/null replaces that value as an ordinary type replacement without `_replace_`; `_replace_: true` in that case is unnecessary and must fail.
  - A higher-precedence scalar/list/null over a lower-precedence mapping replaces that mapping as an ordinary scalar/list/null replacement without `_replace_`; there is no marker location in the scalar/list/null value.
  - Lists always replace as whole lists.
  - `_replace_: true` is consumed as a merge directive and must not appear in the returned config.
  - `_replace_` must be exactly boolean `true`; any other value fails.
  - `_replace_: true` fails when no lower-precedence value exists, when the lower-precedence value is not a mapping, or when the directive appears without sibling keys to apply as the replacement mapping.
- Boundary contract:
  - This phase may update existing `compose_config` tests only to assert strict ordinary override behavior through the existing public helper path. It must not implement Phase 7 user composition overrides or Phase 12 public orchestration order.
  - Existing `compose_config` currently applies ordinary overrides before recipe expansion. Phase 3 may keep that wiring and adjust tests for strict add/update failures, but the executor must stop if a failing recipe/compose test requires deciding the final v1 order of recipes, user composition overrides, or ordinary overrides.
  - Do not add `inspect_config_composition`, v1 `ComposedConfig` fields, include-site records, or override stage records to solve Phase 3 test failures.
  - `loom.config` remains persistence-free and `loom.pipeline` must not depend on `loom.config` or manifests.

## Design Impact

- Maintainability: centralizes strict override and replacement semantics in helpers that later overlay, include, user-composition, recipe, provenance, and fingerprint phases can call instead of reimplementing path logic.
- Extensibility: leaves future CLI and sweep generators a small explicit language with stable update/add operation kinds, while preserving space for future syntax by rejecting list patching and escaped-dot keys now.
- Domain neutrality: operations apply to plain config data and Loom-owned directive markers only; they do not encode model, dataset, experiment, or pipeline semantics.
- Source-tree boundaries: work stays in `loom.config` helper modules and tests; no pipeline, run-store, CLI, plugin, or project imports are needed.

## Future Compatibility

- Phase 4 can call the same `_replace_` merge behavior for ordered overlays and add source-authorship metadata around it.
- Phase 6 can use strict replacement for include sibling merges and component swaps.
- Phase 7 can reuse parsed operation kinds for user include swaps and ordinary value overrides after file-defined composition.
- Phase 10 and Phase 12 can rely on add/update strictness before validation and public orchestration expose v1 behavior broadly.
- Phase 14 can fingerprint override paths, operation kinds, and artifact-safe values without needing to reinterpret legacy permissive overrides.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Let ordinary `path=value` create missing paths | Conflicts with the accepted v1 strict authoring model and makes typos look intentional. |
| Use `+path=value` as a permissive upsert | Weakens the explicit add marker; v1 requires add to fail on existing targets. |
| Support escaped literal-dot keys in v1 | Adds parser complexity and ambiguity before the strict core behavior is reliable. |
| Support list indexes or list patch operators | The v1 plan explicitly rejects list patching, insertion, deletion, and splice language. |
| Leave `_replace_` to include phases only | Overlays and future generated mappings also need the same whole-section replacement semantics, so the primitive belongs in merge. |
| Treat `_replace_` as ordinary project data | `_replace_` is a Loom-owned composition directive and must be validated consistently. |
| Implement user include swaps while touching overrides | That is Phase 7 scope and requires file-defined include-site records that do not exist yet. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Override and merge errors remain message-only unless local context wiring is trivial | Keeps Phase 3 focused on behavior primitives while preserving stable subclasses and avoiding premature public diagnostic payloads before CLI/inspection APIs exist. | Revisit in Phase 7 or Phase 12 when user composition records, inspection stages, or future CLI formatting need machine-readable override/merge diagnostics. |
| No literal-dot key syntax | Accepted v1 simplification keeps override paths deterministic and reviewable. | Revisit only if real config authors repeatedly need dot-containing keys and an explicit escaping design can preserve provenance. |
| Add overrides may create missing parent mappings | Useful for explicit additions without schema knowledge, but it can create larger new subtrees. | Revisit if Phase 10 validation or Phase 14 fingerprint review finds this too permissive for project-owned data. |

## Reviewability

- Expected PR size and shape: focused helper/test diff in override and merge modules, plus narrow compose test updates only where existing public helper wiring exposes strict override behavior.
- Files and areas to inspect: `src/loom/config/overrides.py`, `src/loom/config/merge.py`, `src/loom/config/errors.py` only if contextual errors are added, `src/loom/config/provenance.py` only if `ParsedOverride` changes, `tests/unit/loom/config/test_overrides.py`, `tests/unit/loom/config/test_merge.py`, and targeted `tests/unit/loom/config/test_compose.py`.
- Scope-control checks: no include files/modules; no source-map or overlay authorship model; no recipe/resolver/order refactor; no manifest/provenance/fingerprint population; no run-store writes; no CLI; no pipeline imports from config; no `_copy_` implementation.

## Implementation Steps

1. Refine override parsing and application around the strict update/add contract, preserving ordered `ParsedOverride` records and plain-data value normalization.
2. Add or adjust override unit tests for typed values, invalid forms, ordered operations, strict update failures, explicit add failures, parent traversal, and non-mutating behavior where relevant.
3. Extend the merge primitive with `_replace_: true` handling and strict failure cases while preserving recursive mapping merge and scalar/list/null replacement.
4. Add merge unit tests for recursive replacement, list replacement, `_replace_` required/unnecessary/invalid behavior, marker omission from returned data, and input immutability.
5. Update existing compose helper tests only for strict ordinary override behavior that flows through current `compose_config`, without changing recipe, include, validation, provenance, or public orchestration semantics.

## Test Plan

### Package Suite

- Status: required if exports, imports, or exception class placement change; otherwise deferred for targeted implementation and covered through final PR validation.
- Expected paths: `tests/package/test_import_boundaries.py` and `tests/package/test_config_api.py` through `make validate-pr`.
- Required assertions or deferral reason: no new public modules, root exports, package exports, or import-boundary changes are expected. If implementation changes exports or exception imports, add targeted package assertions that cheap imports still do not pull pipeline, stores, CLI, plugin discovery, or optional config dependencies unexpectedly.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_overrides.py`, `tests/unit/loom/config/test_merge.py`, and narrowly `tests/unit/loom/config/test_compose.py` if strict public override behavior changes existing compose expectations.
- Required assertions or deferral reason: typed parser values; invalid override forms; ordered update/add application; update missing-parent/final-key failures; add existing-final-key and non-mapping-parent failures; add-created parent mappings can be used by later overrides; updates never create parents; no traversal through scalar/list/null; numeric path segments are mapping keys rather than list indexes; JSON plain-data validation; recursive mapping merge when `_replace_` is absent; adding and updating child keys inside mapping-over-mapping merges; scalar/list/null replacement; mapping-over-non-mapping and non-mapping-over-mapping replacement; `_replace_` marker omission; `_replace_` whole-section replacement; `_replace_` unnecessary/no-lower-mapping/no-sibling/invalid-value failures; inputs are not mutated.

### Contract Suite

- Status: conditional.
- Expected paths: existing `tests/contracts/test_config_error_contract.py` or a new focused override/merge contract test only if new structured context or serialized records are exposed.
- Required assertions or deferral reason: `ParsedOverride` already has serialization coverage through provenance contracts. No new contract suite is required if override/merge errors remain message-only and no record shape changes. If new public-ish override/merge diagnostic payloads are added, contract tests must assert plain-data serialization, stable operation/path/directive fields, and absence of raw source bytes or resolved resolver values.

### Integration Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: full composition ordering with overlays, includes, recipes, validation, and public inspection remains later-phase work. Existing integration tests may run in final validation, but no new v1 integration flow should be added here.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: no complete v1 public `compose_config` flow or CLI exists yet. E2E coverage starts when Phase 12 and Phase 16 expose and harden representative public composition.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: raw source snapshots, resolver runtime-value policies, and opt-in persistence behavior are out of scope.

## Risks

- `_replace_` strictness can conflict with existing v0 recursive merge tests or compose fixtures; update tests only to reflect accepted v1 primitive behavior and do not add Phase 4+ authorship logic. Missing `_replace_` must not be treated as an error for ordinary recursive mapping merges.
- Applying strict overrides through current `compose_config` may affect recipe argument override tests because the existing v0 order applies overrides before recipes; keep changes narrow and stop if satisfying tests requires redesigning Phase 9 or Phase 12 order.
- Structured override/merge diagnostics could expand the phase if every error is converted at once; prioritize strict behavior and stable exception classes. Context fields are optional in this phase, not an executor design decision.
- Parent creation for add overrides must not accidentally permit traversal through scalars, lists, or null.
- `_replace_` marker removal must not mutate caller-provided base or overlay mappings.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/config/test_overrides.py
uv run pytest tests/unit/loom/config/test_merge.py
uv run pytest tests/unit/loom/config/test_compose.py
uv run pytest tests/contracts/test_config_error_contract.py tests/contracts/test_config_artifact_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: override parser/application hardening first, override unit coverage second, merge `_replace_` behavior third, merge unit coverage fourth, narrow compose compatibility tests last.
- Tests to run with each slice: run `uv run pytest tests/unit/loom/config/test_overrides.py` after override changes; run `uv run pytest tests/unit/loom/config/test_merge.py` after merge changes; run `uv run pytest tests/unit/loom/config/test_compose.py` after any current `compose_config` helper behavior changes; run package tests if exports/imports move; run contract tests only if serialized diagnostics or records change.
- Decisions the executor must not revisit: `_copy_` remains unsupported; `_replace_` must be exactly boolean `true`; no literal-dot escaping; no list patching/indexing; no include loading; no Phase 4 source authorship; no Phase 7 user composition swaps; no Phase 12 public orchestration refactor; no persistence or CLI.
- Conditions that require stopping for the manager: strict override behavior cannot be implemented without changing `ComposedConfig` or public inspection APIs; current recipe/compose tests require Phase 7, Phase 9, or Phase 12 ordering decisions; `_replace_` behavior appears to require source-authorship metadata rather than pure merge inputs; satisfying tests would require treating missing `_replace_` as an error for ordinary recursive merge; error context changes require altering root `loom.errors.ConfigError`; optional dependencies or pipeline imports leak into helper modules; or implementation needs to reopen the fully used v1 plan quality gate.

## Refinement And Review Budget Status

- Phase execution plan draft: used
- Phase execution plan refine: used
- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed in this artifact by `loom_phase_planner`; implementation not started.
- Final phase execution plan: refined in this artifact by `loom_phase_planner`; implementation not started.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: clarified `_replace_` as an explicit whole-section mapping replacement marker while absence of `_replace_` means recursive mapping merge; clarified scalar/list/null and mapping-over-non-mapping replacements do not require `_replace_`; clarified `+` add parent creation and update strictness; bounded current `compose_config` testing to strict helper behavior without Phase 7/9/12 ordering decisions; decided override/merge errors may remain message-only with stable subclasses/tests unless local `ConfigErrorContext` wiring is trivial; tightened suite obligations and Spark executor stop conditions.
- PR preparation: pending.
- Stack maintenance: none yet.
- Remaining blockers: none.
