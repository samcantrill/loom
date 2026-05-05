# Phase 11 Execution Plan: Strict Instantiation And Runtime Injection

## Metadata

- Status: final phase execution plan
- Feature focus: Configuration
- PR title: `Configuration - Phase 11: Strict Instantiation And Runtime Injection`
- Branch: `codex/config-instantiation-strict`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-instantiation-strict`
- Phase execution plan path: `docs/phases/config-instantiation-strict.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 11 - Strict Instantiation And Runtime Injection
- Stack predecessor: none; Phases 1-10 are merged.
- Base branch: `develop`
- Base commit: `1060558e33699bd554b9cdb4bfc3bc1a0c966112`
- Target branch: `develop`
- Merge eligibility: root phase; eligible to merge into `develop` only after implementation, phase-scoped validation, pre-submit blocker gate, PR preparation/submission, and passing review/CI against `develop`.
- Workflow path: expanded path
- Workflow path rationale: instantiation is a public runtime construction boundary with import semantics, runtime injection behavior, and compatibility impact for later public compose orchestration.
- Successor dependency notes: Phase 12 may call optional instantiation after runtime resolution, but must keep composition and inspection artifacts independent from runtime-created objects. Phases 13-14 must not fingerprint injected runtime objects as config artifact facts.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact; draft budget used.
- Refine pass: completed by `loom_phase_planner` in this artifact; refine budget used.
- Phase implementation refinement budget: unused.
- Pre-submit/PR review budget: unused. The revised workflow requires a pre-submit blocker gate before PR submission; if that gate reviews the implementation diff, PR body, suite evidence, scope boundary, and known review risks, it consumes the Phase 11 PR-review budget unless the submitted diff changes afterward.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid; approved outside-sandbox `gh auth status` succeeded. Sandboxed `gh auth setup-git` failed because `/home/samcantrill/.gitconfig` was read-only; approved `gh auth setup-git` succeeded. Sandboxed `git fetch origin` failed when writing `.git/FETCH_HEAD`; approved `git fetch origin` succeeded. Local `develop`, `origin/develop`, and `HEAD` resolved to the assigned base commit. Initial sandboxed `git worktree add` could not create the branch ref; approved `git worktree add` created the branch and worktree successfully.
- Blockers: none.

## Objective

Keep `_target_` object construction outside composition while locking the existing runtime-instantiation contract: accepted dotted and colon target strings import exactly one top-level module attribute, nested target configs construct bottom-up, `_partial_` returns callable partials without constructing parents, and `_inject_` reports duplicate or missing runtime values explicitly.

## Full-Plan Context

Phases 1-10 established config/pipeline boundaries, artifact skeletons, strict loading, merge and override primitives, source overlays, includes, user composition overrides, resolver security, recipe expansion, and validation ownership. Phase 10 specifically locked `_target_` as inert during composition. Phase 11 now tightens only the explicit runtime instantiation path before Phase 12 wires public orchestration and inspection APIs. This phase must preserve accepted v1 decisions: `loom.config` remains persistence-free, `loom.pipeline` must not depend on `loom.config`, `_copy_` remains unsupported, resolver outputs and raw source bytes are not persisted by default, v1 stays Python-API-only, no CLI behavior is added, and plugin/remote/global search include resolvers remain out of scope.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-10 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`, the implementation plan records Phase 10 merged, and fetched/local `develop` matches the assigned base commit.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after the Phase 11 PR is merged and no successor branch depends on `codex/config-instantiation-strict`.

## Source Phase Summary

- Goal: keep object construction separate while tightening target and injection behavior.
- Required scope: strict dotted and colon `_target_` forms; no nested object lookup after the final dotted class segment or after the colon target; bottom-up recursive construction; `_partial_`; `_inject_` duplicate and missing key checks.
- Required checkpoints: accepted import forms work; invalid target forms fail clearly; nested target nodes construct before their parents; partial mode preserves target, args, and kwargs; duplicate and missing runtime injections raise `RuntimeInjectionError`.
- Acceptance criteria: phase-scoped unit coverage proves the import matrix, invalid targets, bottom-up construction order, partial construction, and injection failures, followed by final PR validation.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/api.py` exposes the public `instantiate(...)` forwarding API. `src/loom/config/instantiate/targets.py` owns `_target_` import resolution through `import_target(...)`; it already accepts dotted and colon forms, rejects multiple colons and colon object paths containing dots, imports exactly one module with `importlib.import_module`, and fetches exactly one attribute with `getattr`. Nested lookup and fallback/progressive import splitting are not currently implemented. `src/loom/config/instantiate/recursive.py` owns recursive construction, `_args_`, `_partial_`, reserved-key misuse, and runtime path labels. It currently instantiates child kwargs and args before importing/calling the parent target. `src/loom/config/instantiate/injection.py` owns `_inject_` duplicate and missing runtime-key checks. `src/loom/config/errors.py` defines the shared exception classes, while `src/loom/config/instantiate/errors.py` re-exports the instantiation-specific errors for local import paths.
- Existing tests or harness behavior: `tests/unit/loom/config/instantiate/test_targets.py`, `test_recursive.py`, and `test_injection.py` already cover basic accepted imports, invalid forms, scalar/list/mapping recursion, `_partial_`, and injection failures. `tests/unit/loom/test_deferred_stubs.py` includes public API smoke for `loom.config.instantiate`. `tests/integration/config/test_compose_config.py` includes coverage that public `compose_config(...)` leaves `_target_` dictionaries inert. Phase 11 should extend these focused files rather than create a monolithic new test file.
- Import-boundary or dependency constraints: prefer no production refactor unless a focused test exposes a contract gap. If implementation changes are needed, keep them under `src/loom/config/instantiate/`, `src/loom/config/api.py` only for public forwarding defects, and `src/loom/config/errors.py` or `src/loom/config/instantiate/errors.py` only for small error-path corrections. Do not import `loom.pipeline`, stores, CLI modules, plugin discovery, project packages beyond test fixtures, network clients, or add runtime dependencies.

## In-Scope Work

- Lock and, only if needed, harden the strict `_target_` import grammar used by instantiation:
  accepted forms are `package.module.Object` and `package.module:Object`.
- For dotted targets, preserve the current one-split behavior: import only the module portion before the final dot and retrieve only the final object name from that module. Do not progressively shorten module paths or traverse attributes after the final object segment.
- For colon targets, preserve the current single-colon behavior: require a non-empty module path and a non-empty single object name after the colon. Reject any colon target that would require nested object lookup such as `module:Outer.Inner`.
- Make invalid target forms fail with clear `TargetImportError` diagnostics, including empty values, whitespace-only segments, multiple colons, missing module/object segments, unsupported punctuation, missing modules, missing objects, and nested lookup attempts.
- Preserve recursive bottom-up construction for mappings, lists, tuples, and `_args_`: every nested `_target_` child must be constructed before the parent callable is invoked.
- Preserve `_partial_: true` behavior so instantiated output is a `functools.partial` with recursively constructed args/kwargs and injected values, without calling the target.
- Tighten `_inject_` behavior around duplicate constructor kwargs and missing runtime keys, keeping failures explicit as `RuntimeInjectionError` and validating `_inject_` key/value shapes before applying runtime values.
- Keep target import and instantiation errors in the instantiation path only. Public composition must continue returning `_target_` mappings as plain data.

## Out-of-Scope Work

- Pipeline/runtime object fingerprint policy implementation, runtime-object hashing, secret-aware runtime fingerprints, or resume comparison of injected objects.
- Composition artifact fingerprints, manifest/provenance/source-artifact population, redaction policy changes, or persistence of resolver outputs/raw source bytes.
- CLI behavior, public inspection API fields, public `ComposedConfig` v1 field additions, run-store writes, plugin discovery, remote target loading, global registries, sandboxing or import allow-lists.
- Project schema inference from `_target_`, constructor-signature validation during composition, project schema registries, YAML `_schema_`, or changing Phase 10 validation boundaries.
- Broad refactors of instantiation internals, compose, recipes, includes, resolver handling, pipeline specs, or package exports unless a focused test exposes a minimal Phase 11 defect.

## Assumptions

- Authored configs remain trusted project code; Phase 11 strictness is about deterministic runtime semantics, not untrusted import sandboxing.
- The existing public Python API `loom.config.instantiate(value, runtime=...)` remains the entrypoint for runtime construction.
- `_target_` values inside `compose_config(...)` output remain inert dictionaries unless a caller explicitly passes them to `instantiate(...)`.
- Python modules and target objects used by tests can live in `tests.support.config_samples`; no domain-specific fixture package is needed.
- Clear failure means a specific exception type and actionable message/path; this phase does not need to redesign instantiation errors into structured artifact contracts.

## Scope Contract

Instantiation owns `_target_`, `_args_`, `_partial_`, and `_inject_` validation only when `instantiate(...)` is called. Composition must not import targets, inspect constructors, resolve runtime injections, or infer schemas from `_target_`. A target string resolves to exactly one module import and one top-level attribute lookup. `module.Object` imports `module` and gets `Object`; `module:Object` imports `module` and gets `Object`. Forms that require nested attribute traversal after that object name are invalid, even if Python could theoretically resolve them by repeated `getattr`. Runtime injection is kwargs-only: injected constructor keys must not duplicate explicitly authored kwargs, and every referenced runtime key must exist in the provided runtime mapping.

## Design Impact

- Maintainability: keeps import parsing, recursive construction, and runtime injection in separate small helpers with focused tests.
- Extensibility: leaves room for future explicit registries, allow-lists, or runtime fingerprint policies without weakening the v1 strict import contract.
- Domain neutrality: target examples and tests use synthetic helpers and do not encode model, dataset, or pipeline semantics.
- Source-tree boundaries: stays within `loom.config` runtime helpers and does not introduce dependencies on pipeline, stores, CLI, plugin discovery, project code, or persistence.

## Future Compatibility

- Phase 12 can optionally call `instantiate(...)` after runtime resolution without also making composition artifacts depend on runtime-created objects.
- Phases 13-14 can record that `_target_` was authored as plain config data without hashing or serializing constructed objects.
- A later plugin or registry design can add explicit target-discovery behavior by introducing a new public contract; v1 does not reserve implicit nested lookup or global registry behavior.
- A later runtime fingerprint policy can account for injected runtime objects outside config artifact fingerprints.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Traverse nested attributes after a colon target, for example `module:Outer.Inner` | The v1 plan explicitly rejects nested object lookup after the colon target; requiring top-level module objects or factories keeps imports deterministic and reviewable. |
| Guess dotted module/object splits by progressively importing shorter module prefixes | This would make `a.b.C.d` ambiguous and could silently support nested lookup after the final class segment. |
| Instantiate `_target_` during `compose_config(...)` | Phase 10 locked `_target_` as inert during composition and Phase 11 is runtime-only. |
| Treat `_inject_` as a source of defaults when runtime keys are missing | Missing runtime values should fail explicitly so runtime dependencies are visible. |
| Include runtime objects in config fingerprints | Runtime object identity and output impact belong to pipeline/runtime fingerprint policy, outside Phase 11. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No import allow-list or sandbox for `_target_` | Authored configs are trusted project code in v1, and allow-list design would be a larger public security contract. | A future roadmap introduces untrusted configs, plugin target discovery, or deployment policies that need import restrictions. |
| Error payloads may remain message-first for instantiation failures | Phase 11 acceptance focuses on clear runtime failures, not a new serialized artifact contract. | Public inspection/API consumers need machine-readable instantiation error records beyond exception type and path. |
| Runtime object fingerprint policy remains undefined in config | The implementation plan assigns injected runtime object policy outside v1 config fingerprints. | Pipeline/runtime fingerprint planning needs to account for injected objects affecting outputs. |

## Reviewability

- Expected PR size and shape: focused changes to target parsing/import validation, recursive construction ordering or validation if needed, injection checks, and phase-scoped tests. No compose orchestration, artifact models, manifest/fingerprint population, persistence, CLI, or pipeline code.
- Files and areas to inspect: `src/loom/config/instantiate/targets.py`, `src/loom/config/instantiate/recursive.py`, `src/loom/config/instantiate/injection.py`, `src/loom/config/instantiate/__init__.py`, `src/loom/config/api.py` only if public API forwarding needs adjustment, `src/loom/config/errors.py` only if local error clarity needs a small refinement, `tests/unit/loom/config/instantiate/test_targets.py`, `tests/unit/loom/config/instantiate/test_recursive.py`, `tests/unit/loom/config/instantiate/test_injection.py`, `tests/support/config_samples.py`, `tests/package/test_config_api.py`, and existing compose inertness tests only if touched.
- Scope-control checks: no `loom.pipeline` imports from config; no project schema inference; no compose-time target imports; no artifact/fingerprint/source-record changes; no CLI; no `_copy_`; no resolver-output or raw-source persistence; no plugin/remote/global target lookup.

## Implementation Steps

1. Add target-import contract tests for no nested lookup after the final dotted object segment, no colon nested lookup, no fallback/progressive import splitting, whitespace or missing segment failures, and accepted dotted/colon forms.
2. Change `targets.py` only if those tests expose a real gap; preserve the current one module import plus one `getattr` design.
3. Add synthetic fixture helpers only as needed to prove construction order and target parsing without domain-specific code.
4. Strengthen recursive instantiation tests so child targets in kwargs, `_args_`, lists, and tuples construct before parent invocation; avoid production changes unless the ordering contract fails.
5. Extend `_partial_` coverage to include recursively constructed args/kwargs and runtime injection without calling the target.
6. Extend `_inject_` coverage for duplicate authored kwargs, missing runtime keys, invalid `_inject_` shape, invalid injected key/value shapes, and non-mapping runtime validation.
7. Run targeted package/unit checks, then final PR-preparation validation after the pre-submit blocker gate has a PR body draft and suite evidence to review.

## Test Plan

### Package Suite

- Status: required as a boundary guard if public forwarding or exports change; otherwise existing package/import checks should be run as targeted verification before PR preparation.
- Expected paths: `tests/package/test_config_api.py` and `tests/package/test_import_boundaries.py` if any import/export path changes.
- Required assertions or deferral reason: prove `loom.config.instantiate` remains available through the existing public/lazy API without eager optional dependencies or `loom.pipeline` imports. If implementation stays entirely inside existing helper internals with no export changes, no new package tests are required beyond running existing package checks.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/instantiate/test_targets.py`, `tests/unit/loom/config/instantiate/test_recursive.py`, `tests/unit/loom/config/instantiate/test_injection.py`, `tests/unit/loom/test_deferred_stubs.py`, and `tests/support/config_samples.py` for synthetic callables/classes.
- Required assertions or deferral reason: accepted dotted and colon imports work; invalid forms fail as `TargetImportError`; nested lookup after the colon target and after the final dotted object segment is rejected or fails without fallback traversal; no fallback/progressive import splitting occurs for dotted targets; nested target children construct bottom-up before parent calls across kwargs, `_args_`, lists, and tuples; `_partial_: true` returns a `functools.partial` with recursively instantiated args/kwargs and injected values without calling the parent target; non-bool `_partial_`, invalid `_args_`, invalid `_inject_`, invalid injected key/value shapes, duplicate injected kwargs, missing runtime keys, non-mapping runtime inputs, non-callable targets, and constructor failures raise the existing explicit exception families. Public deferred-stub smoke should continue proving `loom.config.instantiate` is live.

### Contract Suite

- Status: deferred unless implementation changes structured error contracts.
- Expected paths: `tests/contracts/test_config_error_contract.py` only if `TargetImportError`, `TargetInstantiationError`, or `RuntimeInjectionError` gain structured context or serialization behavior.
- Required assertions or deferral reason: Phase 11 does not add artifact contracts, manifest/provenance/source-record fields, or required serialized error shapes. Existing exception types and clear messages are sufficient unless the implementation intentionally changes error contract plumbing.

### Integration Suite

- Status: deferred for new behavior, with an existing compose-inertness guard required as targeted verification.
- Expected paths: `tests/integration/config/test_compose_config.py`.
- Required assertions or deferral reason: instantiation is already a separate public runtime path and this phase can be covered by unit tests. Public compose must remain inert for `_target_`; run the existing compose target guard to ensure no compose-time imports, constructor inspection, or schema inference were introduced. No new full-config integration is required unless the executor changes compose-adjacent code.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 11 does not complete public v1 orchestration, final artifact population, CLI behavior, run-store writes, or docs/e2e hardening. Representative end-to-end public composition flows belong to Phase 16 after Phase 12-15 behavior exists.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: no raw source snapshot opt-in, secret-aware runtime fingerprints, plugin/remote resolvers, network behavior, or CLI behavior is in scope.

## Risks

- Dotted target parsing can accidentally become permissive by trying alternate module splits. Tests must prove unsupported nested lookup does not silently work.
- `_partial_` can hide bottom-up construction bugs because the parent target is not called. Tests should assert nested args/kwargs are already instantiated inside the returned partial.
- `_inject_` duplicate checks must run after recursively instantiated authored kwargs are collected and before target invocation so failures do not call user code.
- Import-error handling can accidentally mask exceptions raised inside imported modules as missing modules. Keep changes focused on clear target-form validation and existing import semantics.
- The pre-submit blocker gate may find missing unit evidence or scope drift. Known blockers must be resolved before PR submission or the phase must be marked blocked; do not submit a PR expecting GitHub review or CI to rediscover known local blockers.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/instantiate/test_targets.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/instantiate/test_recursive.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/instantiate/test_injection.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/instantiate
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_config_api.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_config.py -k target
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr
UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: start by adding target import contract tests and change production code only if a gap appears; add bottom-up construction order fixtures/tests; extend `_partial_` tests; extend `_inject_` validation/failure tests; then run package/import-boundary and compose inertness guards.
- Tests to run with each slice: target tests after parser/import coverage or changes; recursive tests after construction-order or partial coverage; injection tests after runtime injection coverage; `tests/unit/loom/test_deferred_stubs.py` after public API smoke changes; package/import-boundary tests after any API/export import changes; compose target guard before PR preparation.
- Decisions the executor must not revisit: instantiation remains separate from composition; accepted target forms are only dotted `package.module.Object` and colon `package.module:Object`; no nested lookup after final object segment; no project schema inference from `_target_`; no pipeline/runtime object fingerprint policy; no artifact/fingerprint/source-record population; no CLI, persistence, plugin/remote/global lookup, or `_copy_` work.
- Conditions that require stopping for the manager: satisfying acceptance criteria appears to require changing public `compose_config` field shape, importing `loom.pipeline`, adding a target registry/allow-list public API, changing artifact contracts, implementing runtime object fingerprint policy, or broadening target syntax beyond the v1 plan.
- Expanded-path refinement notes: completed. The refined plan incorporates manager/architecture findings that the current implementation already has clean separation and already implements the core one-import/one-getattr parser shape. Executor scope is narrowed to contract hardening and coverage gaps first, with production edits only for observed Phase 11 defects.

## Refinement And Review Budget Status

- Phase implementation refinement: unused.
- Pre-submit blocker gate: unused. Must run before PR submission against the phase plan, implementation diff, draft PR body, suite evidence, scope boundary, and known review risks; it consumes the Phase 11 PR-review budget when it reviews that full set unless the submitted diff changes afterward.
- PR review: unused. A post-submit PR review should run only if the pre-submit gate did not review the full diff/body/evidence set or if the submitted diff changes after that gate.

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed as `plan: add phase execution plan`.
- Final phase execution plan: completed by `loom_phase_planner`; committed as `plan: refine phase execution plan`.
- Implementation summary:
- Implementation validation:
- Refinement summary: incorporated manager/architecture findings about existing module boundaries, existing parser behavior, existing test coverage, and the revised pre-submit blocker gate. The final plan now directs the executor to avoid unnecessary refactors and primarily lock contracts with focused tests for no nested lookup, no fallback import splitting, bottom-up order, partial behavior, injection validation, public API smoke, and compose-time `_target_` inertness.
- PR preparation:
- Stack maintenance:
- Remaining blockers: none.
