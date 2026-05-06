# Phase 2 Execution Plan: Strict Authoring And Override Semantics

## Metadata

- Status: draft phase execution plan
- Feature focus: V1 Post Configuration
- PR title: `V1 Post Configuration - Phase 2: Strict Authoring And Override Semantics`
- Branch: `codex/v1-post-strict-authoring`
- Worktree: `/home/samcantrill/work/loom-worktrees/v1-post-strict-authoring`
- Phase execution plan path: `docs/phases/v1-post-strict-authoring.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1-post.md`
- Source phase: Phase 2. Strict Authoring And Override Semantics
- Stack predecessor: none; Phase 1 PR #44 has merged into `develop`
- Base branch: `origin/develop` at `5341d2e` (`docs: record v1-post phase 1 merged (#45)`)
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after review/checks because target is `develop`
- Workflow path: expanded path
- Successor dependency notes: later v1-post phases should start from this phase branch only after its PR is opened or prepared, validated, and recorded as `pr_open`; no current successor depends on this draft plan.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v1-post.md`; no blockers remain.
- Plan quality gate loop budget: initial `loom_plan_reviewer` review used, automated plan refinement pass used, confirmation review used.
- Draft pass: completed by `loom_phase_planner`
- Refine pass: pending; expanded path selected because this phase changes public config authoring, loader, and override behavior.
- Setup limitations: local `develop` in the control checkout is intentionally obsolete and was not used; `origin/develop` was verified at `5341d2e`. `gh auth status` initially reported an invalid token in the sandbox, then succeeded with approved network access; `gh auth setup-git` and `git fetch origin` required approved access because the sandbox could not write git credential or fetch metadata.
- Blockers: none

## Objective

Close strict authoring gaps that can hide user mistakes by rejecting duplicate YAML keys before composition, parsing JSON-quoted scalar override values as literal strings, and adding public regression coverage for unsupported literal-dot override addressing and `_copy_` authoring in overlays and includes.

## Full-Plan Context

Phase 1 has merged and cleaned the source boundary and documentation baseline. This phase is the first v1-post runtime behavior change: it tightens trusted config authoring semantics without adding new composition features. Later phases still own source-authorship completion, structured error expansion, artifact-safe ordering, provenance/fingerprint changes, pipeline persistence, recipe residual-risk hardening, and final documentation/evidence cleanup. This phase must not implement literal-dot escape syntax, `_copy_`, list patching, schema registries, or persistence changes.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 1 PR #44 and metadata PR #45 are merged to `develop`.
- Why this base branch is correct: the manager recorded `origin/develop` at `5341d2e` as the continuation base after Phase 1 merged; the original checkout's local `develop` is ahead/behind and contains obsolete unpushed metadata, so it must not seed this branch.
- Retarget/rebase plan after predecessor merge: not applicable; the PR target remains `develop`.
- Branch cleanup constraints: after merge, delete `codex/v1-post-strict-authoring` only when no successor phase branch depends on it.

## Source Phase Summary

- Goal: close strict authoring gaps that can otherwise hide user mistakes.
- Required scope: JSON-quoted scalar override parsing, existing typed override parsing preservation, global duplicate YAML key rejection, literal-dot/no-escape compose regressions, and public compose `_copy_` rejection in overlays and included files.
- Required checkpoints: duplicate keys fail during YAML loading before merge/include composition; quoted override strings such as `"true"`, `"false"`, `"null"`, `"123"`, and `"1.5"` become literal strings; unquoted booleans, `null`, finite numbers, arrays, and objects retain current parsing; dot-path override strings still have no literal-dot escape behavior.
- Acceptance criteria: strict authoring errors are source-aware enough to identify file kind/order/path when currently available; no future syntax is introduced; unit, integration, and config-extra evidence covers the changed behavior.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/load.py` uses `yaml.safe_load_all(...)`, validates root/plain data, rejects recursive aliases, and rejects unsupported `_copy_` and `_schema_` directives with structured `ConfigLoadError` context. `src/loom/config/overrides.py` parses override values with hand-rolled booleans, `null`, finite numbers, and JSON arrays/objects; JSON scalar strings are currently not decoded because only `[` and `{` enter `json.loads(...)`.
- Existing tests or harness behavior: loader unit coverage lives in `tests/unit/loom/config/test_load.py`; override parsing and application coverage lives in `tests/unit/loom/config/test_overrides.py`; public compose coverage lives in `tests/unit/loom/config/test_compose.py` and integration files under `tests/integration/config/`, especially `test_compose_config.py`, `test_compose_includes.py`, `test_compose_overrides.py`, and `test_compose_invalid_yaml_public.py`.
- Import-boundary or dependency constraints: config loader tests require the optional config dependency set, including PyYAML. The config test conftests mark or select these rows through `optional_dependency`; phase evidence must include config-extra rows, not only default no-extra rows.

## In-Scope Work

- Parse JSON-quoted scalar override values into literal strings without quote characters, including quoted boolean-like, null-like, integer-like, and float-like text.
- Preserve current override parsing for unquoted `true`, `false`, `null`, finite integers, finite floats, arrays, and objects.
- Preserve rejection of invalid JSON array/object values and non-finite JSON numeric values.
- Reject duplicate YAML mapping keys globally during loading for base, overlay, and included config files, not only duplicate `_include_`.
- Add public compose tests showing there is no literal-dot escape syntax and mapping keys containing literal dots cannot be addressed by v1 override strings.
- Add public compose tests proving `_copy_` is rejected when authored in overlays and in included files, not only base configs.

## Out-of-Scope Work

- Literal-dot escape syntax or any new override path quoting mechanism.
- List patching, deletion, splice semantics, or numeric list indexing through overrides.
- YAML schema authoring or project schema registries.
- Source authorship/error completion, artifact-safe ordering/provenance, pipeline persistence, recipe hardening, CLI behavior, `_copy_` implementation, plugin/remote resolvers, or default resolved persistence.
- Broad structured-error hierarchy changes beyond the existing context needed for duplicate-key loader failures.
- Documentation sweeps beyond tests or small comments needed to explain the changed strict behavior.

## Assumptions

- Duplicate YAML key rejection is acceptable as a strict authoring change even if PyYAML previously allowed last-key-wins behavior.
- Duplicate-key detection should run before plain-data conversion and unsupported directive scanning so ambiguous YAML is rejected before composition semantics inspect it.
- YAML keys remain required to be string keys after parsing; this phase does not define special duplicate semantics for non-string keys beyond rejecting duplicate authored keys and keeping existing plain-data validation.
- Existing `ConfigLoadError` and `ConfigErrorContext` are sufficient for duplicate-key failures; Phase 3 owns broader structured error completion.
- Public compose tests may live under integration rather than e2e because `compose_config(...)` is the public API surface changed by this phase.

## Scope Contract

The public override contract changes only for JSON-quoted scalar values: a value text that is valid JSON string syntax must decode to the contained string and must not be reinterpreted as a boolean, `null`, or number after decoding. Existing unquoted scalar parsing stays unchanged. Override path parsing remains a simple split on literal dots with explicit `+` add semantics; backslash, quoted path segments, bracket notation, and other escape syntaxes are unsupported and must not be added.

The loader contract changes from PyYAML's permissive duplicate-key behavior to strict duplicate-key rejection for every YAML mapping in base, overlay, and included files. Duplicate YAML keys are authoring errors because composition cannot reliably distinguish user intent after YAML parsing has collapsed or overwritten them.

## Design Impact

- Maintainability: centralizes strict YAML authoring behavior in the loader rather than trying to detect ambiguity after merge or include expansion.
- Extensibility: leaves room for future explicit override path syntax because this phase records unsupported literal-dot addressing instead of reserving an ad hoc escape.
- Domain neutrality: all examples and tests should remain synthetic config data, not domain-specific research pipeline schemas.
- Source-tree boundaries: changes stay inside `loom.config` loader/override/compose behavior and tests; no pipeline, store, CLI, or packaging surfaces should change.

## Future Compatibility

Strict duplicate-key rejection makes future composition and provenance work safer because authored ambiguity never enters source maps, manifests, recipes, or artifact-safe records. Keeping literal-dot escapes unsupported avoids committing to a path grammar before v2 CLI or schema work can design it deliberately. JSON-quoted scalar parsing aligns Python API override strings with a future CLI that can pass raw strings to the config parser without lossy type guessing.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Preserve PyYAML last-key-wins duplicate behavior | It silently hides authored mistakes and loses ambiguity before composition, source maps, or provenance can inspect it. |
| Reject only duplicate `_include_` keys | Any duplicate YAML key has the same ambiguity problem before composition sees the mapping. |
| Treat JSON-quoted scalar values as raw strings including quote characters | That preserves a surprising workaround and contradicts the plan's accepted override parsing contract. |
| Reparse decoded JSON strings for booleans or numbers | Quoting is the explicit way to request a literal string, so a second type-guessing pass would defeat the feature. |
| Add backslash or bracket escaping for literal-dot keys now | Literal-dot escape syntax is explicitly out of scope and needs a broader public grammar decision. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Mapping keys containing literal dots remain unaddressable by override strings. | V1 override paths intentionally split on dots and have no escape syntax. | V2 CLI or schema work designs an explicit path grammar with escaping or segment quoting. |

## Reviewability

- Expected PR size and shape: small loader and override parser changes plus focused unit/integration regression tests; no broad docs or artifact changes.
- Files and areas to inspect: `src/loom/config/load.py`, `src/loom/config/overrides.py`, `tests/unit/loom/config/test_load.py`, `tests/unit/loom/config/test_overrides.py`, `tests/unit/loom/config/test_compose.py`, and targeted files under `tests/integration/config/` for public compose behavior.
- Scope-control checks: diff must not add `_copy_` implementation, literal-dot escape support, list override semantics, schema registry behavior, pipeline/store/CLI changes, provenance schema changes, or future-phase structured error expansion.

## Implementation Steps

1. Add focused failing unit tests for JSON-quoted scalar override values and duplicate YAML keys, covering base and overlay loader context.
2. Update override parsing so valid JSON string scalars decode to strings while the existing unquoted scalar, array, object, invalid JSON, and non-finite number behavior remains intact.
3. Add strict duplicate-key detection to YAML loading before root validation and unsupported directive scanning, with `ConfigLoadError` context that identifies duplicate key, source kind/order/path, and best-effort config path.
4. Add public compose regressions for duplicate keys flowing through `compose_config(...)`, literal-dot/no-escape override behavior, and mapping keys containing literal dots remaining unaddressable.
5. Add public compose regressions for `_copy_` in overlays and included files, preserving existing unsupported directive error code and source-path context.
6. Run targeted config-extra tests, then leave final repository validation to PR preparation.

## Test Plan

### Package Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: no package import, public export, dependency metadata, or distribution surface changes are in scope.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_overrides.py`, `tests/unit/loom/config/test_load.py`, and possibly `tests/unit/loom/config/test_compose.py` if the smallest public compose checks are already housed there.
- Required assertions or deferral reason: override parser returns literal strings for JSON-quoted `"true"`, `"false"`, `"null"`, integer-looking, float-looking, and ordinary string values; unquoted booleans, `null`, finite numbers, arrays, and objects keep existing typed values; invalid arrays/objects and non-finite JSON numeric values remain rejected. Loader tests must reject duplicate keys at the root and nested mapping levels, for base and overlay kinds, and assert structured context including `duplicate_key` details or equivalent machine-readable facts.

### Contract Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: no extension protocol, public artifact/provenance contract, or error serialization contract shape changes are required. If implementation changes `ConfigErrorContext.to_dict()` or public error payload fields, add contract coverage or stop for manager confirmation because that would expand Phase 3 scope.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_invalid_yaml_public.py`, `tests/integration/config/test_compose_overrides.py`, `tests/integration/config/test_compose_includes.py`, and/or `tests/integration/config/test_compose_config.py`.
- Required assertions or deferral reason: `compose_config(...)` rejects duplicate keys in base, overlay, and included YAML sources; attempted literal-dot escaping does not address literal-dot keys; override strings cannot update or add through a mapping key that contains a literal dot unless the nested mapping path already exists by separate segment keys; `_copy_` in overlays and included files raises the existing unsupported directive error with the correct source kind/order/path.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: this phase changes the public compose API but not a full runner or CLI workflow. Integration coverage through `compose_config(...)` is sufficient and more precise.

### Opt-In Suites

- Status: required.
- Markers affected: `optional_dependency` and config-extra summary rows for unit-config and integration-config.
- Required assertions or deferral reason: because config composition depends on optional config dependencies, targeted and summary evidence must include config-extra rows containing the new loader, override, and public compose cases. PR preparation must report `make test-summary` config-extra evidence or explain why the optional dependency environment was unavailable.

## Risks

- PyYAML duplicate-key detection must preserve existing safety behavior for invalid YAML, recursive aliases, multiple documents, unsupported tags, and non-string keys.
- Duplicate-key error paths may be best effort because YAML constructors expose authored nodes rather than the final plain-data path; context should still identify the duplicate key and source file clearly.
- JSON string parsing can accidentally broaden accepted values, for example quoted arrays or malformed quotes; only valid JSON strings should use the scalar string path, while existing arrays/objects keep their current JSON path.
- Literal-dot tests can become misleading if they accidentally create nested mappings that make the override succeed for ordinary reasons; fixtures should distinguish `{"model.name": ...}` from `{"model": {"name": ...}}`.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run --locked --group dev --extra config pytest -m optional_dependency tests/unit/loom/config/test_overrides.py tests/unit/loom/config/test_load.py
UV_CACHE_DIR=/tmp/uv-cache uv run --locked --group dev --extra config pytest -m optional_dependency tests/integration/config/test_compose_invalid_yaml_public.py tests/integration/config/test_compose_overrides.py tests/integration/config/test_compose_includes.py tests/integration/config/test_compose_config.py
make test-config-extra
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: tests for override parser and duplicate loader behavior first, parser update second, loader duplicate-key rejection third, public compose regressions fourth.
- Tests to run with each slice: run the relevant targeted config-extra pytest command after each source change; run `make test-config-extra` once the public compose coverage is in place.
- Decisions the executor must not revisit: no literal-dot escape syntax, no `_copy_` implementation, no list patching, no schema registry, no pipeline/store/CLI changes, no artifact/provenance ordering changes, and no broad error hierarchy expansion.
- Conditions that require stopping for the manager: strict duplicate-key rejection requires changing public error serialization contracts; PyYAML cannot provide enough duplicate-key context without replacing the loader dependency; JSON-quoted scalar parsing conflicts with existing accepted array/object behavior; or literal-dot regression coverage cannot be written without deciding a new path grammar.
- Expanded-path refinement notes: pending. The refinement pass should confirm the duplicate-key context expectation is precise enough, the literal-dot tests do not accidentally define future syntax, and suite obligations remain complete without adding future-phase behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on `codex/v1-post-strict-authoring`.
- Final phase execution plan: pending expanded-path refinement.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- PR preparation: pending.
- Stack maintenance: pending.
- Remaining blockers: none at draft time.
