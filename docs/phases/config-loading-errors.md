# Phase 2 Execution Plan: Strict Loading And Structured Errors

## Metadata

- Status: in_progress; phase execution plan refined
- Feature focus: Configuration
- PR title: `Configuration - Phase 2: Strict Loading and Structured Errors`
- Branch: `codex/config-loading-errors`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-loading-errors`
- Phase execution plan path: `docs/phases/config-loading-errors.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Source phase: Phase 2 - Strict Loading And Structured Errors
- Stack predecessor: none
- Base branch: `develop`
- Base commit: `548f4eb4def154197a0cc51fe7ef406f7deb02ed`
- Target branch: `develop`
- Merge eligibility: merge-eligible after PR review approval because this is a root phase targeting `develop`; no predecessor branch remains after Phase 1 and PR #24 are merged.
- Workflow path: expanded path
- Successor dependency notes: later config phases may depend on the structured error context and strict loader guarantees once this phase PR is open or prepared; this phase must not implement Phase 3+ merge, override, overlay source-authorship, include, resolver, recipe, validation, provenance population, fingerprint, persistence, or CLI behavior.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact.
- Refine pass: completed by `loom_phase_planner`; expanded-path refinement tightened the structured error context contract, loader-only boundary, suite obligations, compatibility risks, and executor stop conditions.
- Setup limitations: branch and worktree were created from local `develop`; initial sandboxed `git worktree add` could not create the nested `codex/...` branch ref, then succeeded with approved escalated Git worktree access.
- Blockers: none.

## Objective

Establish v1 strict YAML loading and structured config-error foundations so later composition phases can rely on consistent source/path diagnostics without parsing human message strings.

## Full-Plan Context

Phase 1 established persistence-free artifact skeletons and config/pipeline boundaries. Phase 2 now hardens the existing config loader and error hierarchy around the accepted v1 input contract: single-document UTF-8 YAML, non-empty mapping roots, plain-data parsed values, and `_copy_` rejection anywhere in authored config. Later phases will add strict merge/override behavior, source-authored overlays, include resolution and expansion, resolver security, recipes, validation boundaries, public orchestration, manifest/provenance population, fingerprints, raw snapshot policy, and docs/e2e coverage.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 1 is merged and its post-merge blocker was resolved by PR #24.
- Why this base branch is correct: the user selected current `develop`, all earlier v1 phases are merged, and no predecessor phase branch remains.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after this phase PR is merged and no successor branch depends on `codex/config-loading-errors`.

## Source Phase Summary

- Goal: enforce v1 loading rules and structured error foundations.
- Required scope: strict single-document UTF-8 YAML loading, non-empty mapping-root enforcement, plain-data parsed values, `_copy_` rejection anywhere in authored config, and `ConfigError` subclasses with machine-readable context.
- Required checkpoints: loader failures include path/source context; `_copy_` is reported as an explicit unsupported directive; structured errors can be serialized or inspected without parsing strings.
- Acceptance criteria: loader success and failure cases satisfy the v1 matrix; structured error context avoids resolved secret/runtime values; no later composition behavior is implemented.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/load.py` already reads bytes, decodes UTF-8, hashes source bytes, parses with `yaml.safe_load`, validates mapping roots, normalizes via `ensure_plain_data`, and returns `ConfigSource`; `src/loom/config/errors.py` currently defines thin `ConfigError` subclasses without structured context fields; `src/loom/errors.py` owns the root `ConfigError`; Phase 1 added `src/loom/config/artifacts.py` and contract tests for plain serializable records.
- Existing tests or harness behavior: loader tests live in `tests/unit/loom/config/test_load.py`; config error hierarchy tests live in `tests/unit/loom/config/test_config_errors.py`; artifact contract tests live in `tests/contracts/test_config_artifact_contract.py`; package import-boundary tests live in `tests/package/test_import_boundaries.py`; current compose tests still show v0 behavior that accepts reserved directive-looking keys until v1 phases replace it. Phase 2 may intentionally require updating compose tests that exercise `_copy_` through `load_config`, but only to reflect the accepted v1 loader decision and not to add compose orchestration behavior.
- Import-boundary or dependency constraints: `load.py` may import `yaml` because config loading requires optional config dependencies; cheap imports of `loom`, `loom.pipeline`, and Phase 1 artifact contracts must remain free of `yaml`, `omegaconf`, `pydantic`, pipeline, CLI, execution, store, and plugin imports.

## In-Scope Work

- Add or refine structured config error context models/helpers under `loom.config` so config errors expose machine-readable fields and a plain serializable representation.
- Prefer a config-domain context object plus a config-domain base/mixin for contextual exceptions in `src/loom/config/errors.py`; preserve existing public exception classes as `ConfigError` subclasses. Do not change `loom.errors.ConfigError` unless the executor proves the context cannot be added locally.
- Keep `ConfigLoadError` compatible for existing callers; add a narrow unsupported-directive subclass only if it still remains catchable as both `ConfigLoadError` and `ConfigError`, or otherwise keep unsupported directive failures as structured `ConfigLoadError` values.
- Enforce exactly one YAML document per file before or during parse; reject multi-document YAML streams even if `yaml.safe_load` would otherwise reject indirectly.
- Require parsed root values to be non-empty mappings.
- Preserve plain-data-only parsed values and reject non-string mapping keys or non-plain nested values with structured context.
- Reject `_copy_` anywhere in authored config mappings, including nested mappings and list-contained mappings, with an explicit unsupported-directive error that names `_copy_` as deferred out of v1.
- Include source path, config source kind, source order, config path where known, expected/actual shape where useful, machine-readable code, directive when relevant, and remediation guidance in structured error context.

## Out-of-Scope Work

- `_include_` implementation, include resolution, include stacks, include provenance records, include cycle detection, and include-related error subclasses beyond leaving additive room in the base context shape.
- `_replace_` handling beyond not confusing it with `_copy_`; strict `_replace_` behavior belongs to Phase 3 and include phases.
- Overlay merge behavior beyond the existing one-source `load_config(..., kind, order)` source context. Phase 2 may use `kind` and `order` in error/source metadata, but must not load or merge multiple sources itself.
- Override parsing, override application, strict update/add semantics, literal-dot handling, and typed override values.
- Schema validation, `_schema_` rejection, Loom-owned envelope validation, and project pass-through validation.
- Resolver scanning, resolver execution, `ConfigUnsupportedResolverError`, resolver-dependent control-flow failures, and resolver redaction paths.
- Recipe expansion, explicit catalog hardening, recipe manifests, and artifact-safe recipe outputs.
- Manifest/provenance/source/fingerprint population, raw source snapshot policy, run-store writes, persistence behavior, public CLI commands, and public compose orchestration or inspection APIs.

## Assumptions

- Structured context should be plain-data serializable and small enough to embed in tests, logs, future PR bodies, and later manifest/provenance records without including raw source bytes.
- A likely shape is a frozen `ConfigErrorContext` or similarly named config-domain record with `code`, `source_kind`, `source_order`, `source_path`, `config_path`, `directive`, `expected`, `actual`, `remediation`, and `details` fields. Field names may be adjusted to match local style, but the implementation must keep them plain, stable, additive, and inspectable.
- Context serialization should omit absent values or encode them as `None` consistently, and `details` must itself be normalized plain data so a bad context cannot recreate the Phase 1 plain-data validation defect.
- The existing root `loom.errors.ConfigError` can remain simple; structured context can be added in `loom.config.errors` through config-domain base classes or mixins without forcing unrelated `ConfigError` users to change.
- Existing message strings may remain human-readable, but tests should lock structured fields rather than relying on exact prose.
- Authored configs are trusted project code, but strict loading still rejects ambiguous, unsupported, or non-plain values.

## Scope Contract

- `load_config(path, *, kind, order)` remains the focused loader entrypoint for one local filesystem config source and continues returning `(dict[str, PlainData], ConfigSource)`.
- Structured error context is the public-ish boundary for this phase. It must be inspectable without parsing strings and serializable as plain data, with stable additive field names for source path/kind/order, config path, directive, expected shape, actual shape, reason/code, remediation, and plain-data details where available.
- The preferred API shape is local to `loom.config.errors`: contextual config exceptions should expose a `.context` attribute and either `to_dict()` or an equivalent plain-data serialization method. If a context helper has `from_dict()`, contract tests should cover it; if not, contract tests should assert the serialized shape only.
- Existing catch behavior must hold: `except ConfigError`, `except ConfigLoadError`, and existing subclass checks in tests continue to work. Unsupported `_copy_` rejection may introduce `UnsupportedConfigDirectiveError`, but only if the class is also catchable as `ConfigLoadError`; otherwise use `ConfigLoadError` with `context.directive == "_copy_"` and `context.code == "unsupported_directive"` or equivalent.
- Stable context codes should be short machine-readable strings, not message prose. Required Phase 2 codes should cover path validation/read, invalid UTF-8, YAML parse error, multiple YAML documents, empty document/root, non-mapping root, non-plain data, and unsupported directive.
- Error context must not store raw source bytes, resolved resolver outputs, environment values, or other runtime-derived secrets.
- `_copy_` is unsupported everywhere in authored config for v1. A nested occurrence must fail during loading before later composition stages see it.
- The loader must accept hierarchical nested mappings and lists containing plain data when they do not contain unsupported directives.
- Empty roots include YAML `null`, empty documents, and empty mapping roots. All must fail with structured load context.
- Multi-document YAML streams are out of scope and must fail explicitly; do not support selecting the first document or merging documents.
- Do not make `loom.pipeline` import `loom.config`, config errors, manifests, or optional config dependencies.
- Do not add public root exports for the context object or new error subclasses in this phase. Leaf-module exports from `loom.config.errors` are acceptable when tests need them.

## Design Impact

- Maintainability: centralizing structured loader errors early prevents later include, override, validation, resolver, and recipe phases from each inventing incompatible diagnostic payloads.
- Extensibility: stable additive context fields leave room for later include stacks, resolved target paths, override sources, schema boundaries, and security classifications without changing the exception hierarchy again.
- Domain neutrality: loader validation remains about Loom-owned config mechanics only; project experiment/model/stage mappings still pass through as plain data.
- Source-tree boundaries: work should stay under `src/loom/config/` and tests under config/package/contract suites; no pipeline, runner, store, CLI, plugin, or project-code imports.

## Future Compatibility

- Phase 3 can reuse structured context for `_replace_`, merge, and override errors.
- Phase 5 and Phase 6 can add include-specific fields such as authored include value, resolved target, and include stack without changing the base context shape.
- Phase 8 can add `ConfigUnsupportedResolverError` as both `ConfigError` and `NotImplementedError` using the same context pattern.
- Phase 13 can serialize redaction-safe error/provenance context without discovering late that loader errors only expose unstructured strings.
- Future CLI wrappers can display structured remediation without adding v1 CLI behavior now.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Continue with message-only `ConfigLoadError` failures | Later phases, tests, and future CLI tooling would need to parse human prose, which conflicts with the v1 structured diagnostic goal. |
| Add context fields to the root `loom.errors.ConfigError` by default | The structured context contract is config-domain-specific in Phase 2; changing the root error class would expand the blast radius across unrelated subsystems. |
| Support YAML multi-document streams by taking the first document | The implementation plan explicitly excludes multi-document YAML and chooses fail-closed loading. |
| Treat `_copy_` as ordinary project data until copy support exists | The accepted v1 decision requires `_copy_` to fail anywhere in authored config so users do not believe copy semantics are active. |
| Add schema validation while touching loader errors | Schema boundaries are Phase 10 scope and would blur project-owned data pass-through decisions. |
| Add CLI-specific error formatting | V1 is Python-API-only; structured context should be CLI-ready without adding CLI commands or UX. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Structured error context begins with loader and unsupported-directive fields only | Keeps Phase 2 narrow while providing the base pattern later phases can extend. | Revisit in Phase 5/6 if include-specific context cannot be added additively. |
| Existing v0 compose tests may still assert pre-v1 reserved-key behavior until orchestration phases change them | Phase 2 should not rewire public `compose_config` order beyond loader behavior, but `compose_config` currently calls `load_config`, so `_copy_` loader rejection can surface through existing compose tests. | Update affected tests only for `_copy_` rejection in this phase; revisit broader compose semantics in Phase 12 when public orchestration owns complete v1 behavior. |
| No redaction policy beyond avoiding runtime/resolver/raw-source values in error context | Phase 2 has no resolver execution or artifact population. | Revisit in Phase 13 when redaction and artifact serialization are populated. |

## Reviewability

- Expected PR size and shape: focused loader/error/test diff with no composition-order or public orchestration changes.
- Files and areas to inspect: `src/loom/config/errors.py`, `src/loom/config/load.py`, `tests/unit/loom/config/test_config_errors.py`, `tests/unit/loom/config/test_load.py`, a focused contract test for structured error context, and package import-boundary tests only if exports/import behavior changes.
- Scope-control checks: no include modules or resolution behavior; no override or merge primitive behavior; no schema validation; no resolver execution; no run-store writes; no CLI commands; no root exports; no changes that make pipeline import config; no broad rewrite of `compose_config` beyond tests or behavior naturally affected by stricter `load_config`.

## Implementation Steps

1. Define the structured config-error context shape and serialization helpers in `src/loom/config/errors.py`, preserving existing exception subclass compatibility and keeping the root `loom.errors.ConfigError` unchanged unless a concrete blocker is recorded.
2. Update loader failure paths in `src/loom/config/load.py` to raise structured `ConfigLoadError` values for path validation, read failures, invalid UTF-8, parse failures, multi-document streams, empty roots, non-mapping roots, and non-plain parsed values.
3. Add a recursive authored-config directive scan that rejects `_copy_` anywhere in parsed plain data with structured unsupported-directive context.
4. Extend unit tests for loader success/failure cases, nested `_copy_` path reporting, and structured error subclass/context behavior.
5. Add contract coverage for structured error context serialization and redaction-safe field expectations.
6. Adjust any existing compose tests that now encounter `_copy_` rejection through `load_config`, but do not add Phase 12 orchestration semantics.

## Test Plan

### Package Suite

- Status: required if public config exports or import behavior change; otherwise targeted package import-boundary check is optional during implementation and required at PR preparation through `make validate-pr`.
- Expected paths: `tests/package/test_config_api.py` if config package exports change; `tests/package/test_import_boundaries.py` if structured error helpers risk optional dependency or pipeline import leakage.
- Required assertions or deferral reason: config error exports, if changed, remain importable through intended config modules without changing root public API; `loom.pipeline` still imports without `loom.config` or optional config dependencies; importing `loom.config.errors` should not pull pipeline, stores, CLI, execution, `yaml`, `omegaconf`, or `pydantic`.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/config/test_load.py`; `tests/unit/loom/config/test_config_errors.py`
- Required assertions or deferral reason: successful UTF-8 single-document mapping load still returns plain data and `ConfigSource`; invalid path/read/UTF-8/YAML/multi-document/empty-root/empty-mapping/non-mapping/non-string-key/non-plain-value cases raise `ConfigLoadError` with structured context; `_copy_` at root, nested mapping, and list-contained mapping paths raises an explicit unsupported-directive config error with directive and config path fields; existing `issubclass(..., ConfigError)` and `except ConfigLoadError` behavior remains intact.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_config_error_contract.py` or another focused config error contract module.
- Required assertions or deferral reason: structured error context serializes to plain dictionaries with stable additive field names; round-trip or reconstruction helpers work where provided; serialized context excludes raw source bytes and resolved runtime values; callers can inspect code/source/path/directive/remediation fields without parsing `str(exc)`; `details` rejects or normalizes nested non-plain data.

### Integration Suite

- Status: deferred
- Expected paths: none for this phase.
- Required assertions or deferral reason: only single-source loading and error foundations are in scope. Multi-stage composition behavior starts when overlays, includes, overrides, recipes, and public orchestration are implemented in later phases.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase.
- Required assertions or deferral reason: no new public `compose_config` v1 flow or CLI behavior is complete. E2E coverage begins when the full composition order is wired through public APIs.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected.
- Required assertions or deferral reason: raw source snapshots, resolver runtime-value policies, and opt-in persistence behavior are out of scope.

## Risks

- Adding structured context can accidentally over-specify message text or internal implementation details; tests should lock fields, not prose.
- Rejecting `_copy_` during loading may affect existing v0 compose tests that previously treated `_copy_` as ordinary data because `compose_config` already calls `load_config`; update those tests narrowly and do not use that as permission to implement include/override/compose orchestration.
- Multi-document detection must produce clear errors without enabling partial loading.
- Recursive `_copy_` scanning must report a stable config path while staying plain-data-only and avoiding include/override path semantics that later phases own.
- New config error helpers must not make cheap config artifact or pipeline imports load optional dependencies.
- Adding too many specialized error subclasses now can freeze names before include, resolver, and validation phases prove they need them; prefer stable context codes over broad subclass proliferation.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/config/test_load.py tests/unit/loom/config/test_config_errors.py
uv run pytest tests/contracts/test_config_error_contract.py
uv run pytest tests/unit/loom/config/test_compose.py
uv run pytest tests/package/test_import_boundaries.py tests/package/test_config_api.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: structured error context first; loader strictness second; `_copy_` recursive rejection third; unit and contract tests fourth; narrow compose test compatibility updates fifth; import/export cleanup last.
- Tests to run with each slice: run `uv run pytest tests/unit/loom/config/test_config_errors.py` after error-shape work; run `uv run pytest tests/unit/loom/config/test_load.py` after loader strictness and `_copy_` rejection; run the new contract test after serialization helpers; run `uv run pytest tests/unit/loom/config/test_compose.py` if `_copy_` rejection changes current compose expectations; run package import tests if exports or import paths change.
- Decisions the executor must not revisit: `_copy_` unsupported in v1; single-document UTF-8 YAML only; non-empty mapping roots only; plain-data parsed values only; no includes, overlays beyond existing loader kind/order, overrides, schema validation, resolver execution, persistence, or CLI.
- Conditions that require stopping for the manager: structured error context cannot be made plain-data serializable without changing the root `loom.errors.ConfigError` contract; preserving `ConfigLoadError` catch compatibility conflicts with unsupported-directive specificity; `_copy_` rejection requires public compose orchestration changes outside loader scope; loader changes require pipeline imports from config; optional config dependencies leak into cheap imports; existing tests require Phase 3+ semantics to pass; or implementation needs to reopen the v1 plan quality gate.

## Refinement And Review Budget Status

- Phase execution plan draft: used
- Phase execution plan refine: used
- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed in this artifact by `loom_phase_planner`; implementation not started.
- Final phase execution plan: refined by `loom_phase_planner`; committed with `plan: refine phase 2 execution plan`.
- Implementation summary: added config-domain structured error context and context-bearing exceptions in `src/loom/config/errors.py`, enforced strict single-document UTF-8 YAML loading with plain-data + non-empty mapping checks in `src/loom/config/load.py`, added recursive `_copy_` rejection in authored mappings, and added targeted unit/contract coverage.
- Implementation validation: completed using
  - `UV_CACHE_DIR=/tmp PYTHONPATH=/usr/lib/python3/dist-packages:/usr/lib/python3.12/dist-packages uv run pytest tests/unit/loom/config/test_load.py tests/unit/loom/config/test_config_errors.py` (pass)
  - `uv run pytest tests/contracts/test_config_error_contract.py` (pass)
  - `UV_CACHE_DIR=/tmp PYTHONPATH=/usr/lib/python3/dist-packages:/usr/lib/python3.12/dist-packages uv run pytest tests/unit/loom/config/test_compose.py` (blocked)
- PR preparation: pending.
- Stack maintenance: none yet.
- Remaining blockers: compose coverage command still requires optional dependencies (`omegaconf`, `pydantic`) not available in this workspace.
