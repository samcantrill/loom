# Phase 1 Execution Plan: Argv Parser And Records

## Metadata

- Status: draft phase execution plan
- Feature focus: Weave Argv Config Shorthand
- PR title: `Weave Argv Config Shorthand - Phase 1: Argv Parser And Records`
- Branch: `codex/weave-argv-parser-records`
- Worktree: `/nas/home/can134/work/loom-worktrees/weave-argv-parser-records`
- Phase execution plan path: `docs/roadmap/stage-24/phases/weave-argv-parser-records.md`
- Full plan: `docs/roadmap/stage-24/implementation-plan.md`
- Source phase: Phase 1, `weave-argv-parser-records`
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: merge eligible when the PR targets `develop`, automated review passes, and validation/CI pass
- Workflow path: expanded path
- Successor dependency notes: Phase 2 may stack on `codex/weave-argv-parser-records` if this PR is open or approved but not merged.
- Plan quality gate: verified passed in the selected implementation plan; initial blocker, refinement, confirmation review, and non-blocking note resolution are recorded there.
- Plan quality gate loop budget: consumed and passed for the implementation plan; no blocking plan-review findings remain.
- Draft pass: completed by `loom_phase_planner`
- Refine pass: pending for expanded-path refinement before implementation
- Setup limitations: the assigned `/home/samcantrill/work/loom-worktrees` path does not exist for this user and could not be created due host permissions. The worktree was created at the equivalent current-account path `/nas/home/can134/work/loom-worktrees/weave-argv-parser-records`.
- Blockers: product implementation must wait for the expanded-path refine pass; no blocker to committing this draft plan.

## Objective

Define the argv shorthand grammar, package-local parser records, scoped-overlay RHS candidate resolution, and structured parser diagnostics for `weave` without changing config composition behavior or adding public compose helpers.

## Full-Plan Context

Stage 24 adds optional `weave` helpers for project-specific CLIs that want to parse argv config shorthand before composing config through existing machinery. Phase 1 owns only the argv adapter layer: command/base parsing, token classification, value-override lowering, scoped-overlay request records, deterministic candidate resolution, and parser diagnostics. Phase 2 will load and merge scoped overlays with provenance and fingerprint participation. Phase 3 will expose public compose/inspect helpers, warnings, docs, and end-to-end behavior.

Future-phase work must remain out of scope here: scoped overlay YAML loading or merge behavior, source artifacts, provenance, fingerprints, inspection stage plumbing, warning UX, public `compose_config_from_argv(...)`, public `inspect_config_from_argv(...)`, docs updates, first-party CLI integration, and any Loom runtime behavior.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: Phase 1 has no predecessor and the assignment names `develop` as both base and target.
- Retarget/rebase plan after predecessor merge: not applicable for this root phase.
- Branch cleanup constraints: branch can be deleted after merge only if no successor phase branch is stacked on it.

## Source Phase Summary

- Goal: define argv grammar, record shapes, RHS candidate resolver, and structured parser diagnostics without changing composition behavior.
- Required scope: new package-local argv/shorthand module under `packages/weave/src/weave/`, optional `weave.api` exports only if needed for the chosen record boundary, optional `weave.errors` additions only if existing structured errors are insufficient, and package-local parser/import tests.
- Required checkpoints: parser records are plain-data-safe; value tokens reuse existing override parsing; scoped overlay requests preserve raw token, scope, mode, RHS, candidate paths, and resolved path where available; diagnostics include token/scope/RHS/command/candidate context.
- Acceptance criteria: targeted tests cover command choices, base config token handling, no-slash value overrides, path-like value RHS, trailing-slash overlays, nested slash scopes, `+scope/=`, absolute and relative RHS lookup, suffix probing, no `~` expansion, unparsed args, and `/=root` rejection.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `packages/weave/src/weave/overrides.py` already parses value override strings into `ParsedOverride` records; `packages/weave/src/weave/provenance.py` defines that record shape; `packages/weave/src/weave/errors.py` provides config-owned structured errors through `ConfigErrorContext`; `packages/weave/src/weave/api.py` and `packages/weave/src/weave/__init__.py` keep public exports explicit and lazy.
- Existing tests or harness behavior: `packages/weave/tests/unit/config/test_overrides.py` covers value parsing and apply invariants; `packages/weave/tests/test_import.py` covers import safety and runtime dependencies; package test markers include package, unit, contract, integration, and optional dependency suites.
- Import-boundary or dependency constraints: `weave` must not import Loom modules, must not add heavyweight runtime dependencies, and should keep Stage 24 parser behavior package-local and domain-neutral.
- Worktree source-plan note: the clean branch from `develop` does not contain the dirty control-checkout `docs/roadmap/stage-24` source artifacts. This phase plan is created from the manager-provided source-plan content and commits only this phase execution plan.

## In-Scope Work

- Add an internal argv/shorthand parser module under `packages/weave/src/weave/`.
- Define frozen, typed, plain-data-safe records for parsed argv, value override tokens, scoped overlay requests, candidate paths, and unparsed args.
- Parse `<command> <base-config> ...` and validate command against caller-provided choices without hard-coded command names.
- Treat tokens beginning with `-` as unparsed command args and fail when `allow_unparsed=False`.
- Classify no-slash LHS tokens as value override strings and lower them through the existing override parser where practical.
- Recognize trailing-slash scoped overlay syntax, including nested slash scopes and `+scope/=`.
- Reject root overlay syntax such as `/=root`.
- Resolve scoped overlay RHS candidates in scope-directory then base-directory order, with `.yaml` before `.yml` for suffixless relative RHS values, exact absolute paths, no `expanduser()`, and normalized relative escapes.
- Raise config-owned structured parser errors with command, token, scope, RHS, and candidate context where relevant.
- Add focused parser/record tests and regression coverage for existing override parsing.

## Out-of-Scope Work

- Scoped overlay YAML loading, mapping validation, or merge behavior.
- Changes to `compose_config(...)`, `inspect_config_composition(...)`, recipe expansion, include expansion, source maps, provenance, source artifacts, manifests, or fingerprints.
- Public `compose_config_from_argv(...)` or `inspect_config_from_argv(...)` helpers.
- Warning generation for likely overlay mistakes.
- First-party `weave` CLI, Loom CLI integration, argparse ownership, printing, shell completion, process exits, or command-specific parsing.
- Hydra/defaults/config-group behavior, RHS inference, escaped dot-path grammar, advanced list patching, untrusted config sandboxing, runtime execution, pipeline planning, stores, or downstream operations.

## Assumptions

- Phase 1 may keep record types internal unless a narrow `weave.api` export is necessary for the implementation boundary; any export must be contract-tested through package import coverage.
- Missing base config path means the argv input lacks the second token. Base file existence remains normal composition/loading responsibility unless needed only for scoped overlay candidate resolution.
- `~` is not expanded. If authored as a relative RHS segment, it remains literal during candidate construction rather than resolving to a user home.
- Relative escapes such as `../shared/model_A` are allowed and recorded after normal path normalization; the parser does not reject candidates merely because they leave the base config directory.
- Candidate resolution checks filesystem existence for overlay RHS selection but does not parse or load YAML content in this phase.

## Scope Contract

Phase 1 defines argv parser behavior, not composition behavior. The executor must preserve these public grammar decisions:

- The first argv token is `command`, the second is `base_config_path`, and remaining tokens are config shorthand or unparsed command args.
- Command validation is against caller-provided choices only.
- Tokens beginning with `-` are unparsed args and never config shorthand.
- A token without `=` is malformed unless it is an unparsed arg.
- No-slash LHS tokens are value overrides, including root keys, dotted paths, and path-like RHS strings.
- Existing override value parsing remains authoritative for booleans, null, numbers, JSON arrays and objects, JSON-quoted strings, and raw strings.
- Trailing slash on the LHS is the only scoped-overlay marker. Slash segments, not dot segments, identify overlay scopes.
- `+scope/=` records add-only overlay mode. `scope/=` records update overlay mode. `/=...` and `+/=...` are unsupported root overlays.
- RHS candidate order is deterministic and auditable: scope directory first, base directory second; suffixless relative stems probe `.yaml` then `.yml`; suffixed `.yaml`/`.yml` RHS values probe only that authored suffix; absolute paths are exact and do not probe suffixes.

Record fields should stay plain-data-safe and useful to later phases: raw token, order, operation/mode, command, base config path, value override raw/parsed data, scope path segments, authored RHS, candidate paths, resolved path, and unparsed args. Do not add result warnings or persisted audit records in this phase.

Structured parser errors should use existing config-owned error patterns where possible. If a new error class is required, keep it in `weave.errors`, include `ConfigErrorContext`, and add import/contract coverage for the new public name.

## Design Impact

- Maintainability: parser decisions stay isolated in one package-local module and reuse the existing override parser rather than forking value syntax.
- Extensibility: later composition and public-helper phases can consume stable request records without adding a CLI framework or global resolver.
- Domain neutrality: command names, config keys, and overlay scopes are caller-authored data; implementation must not hard-code project concepts.
- Source-tree boundaries: all behavior stays in `packages/weave`; no `loom` imports, CLI package imports, or runtime/store dependencies.

## Future Compatibility

This phase preserves room for Phase 2 provenance and fingerprint work by recording candidate and resolved path facts early, but it must not decide manifest/source artifact schemas. It also preserves future Loom CLI or Hydra bridge work by avoiding command-framework ownership, config groups, defaults lists, and RHS inference.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Use `argparse` or own process exits in `weave` | Project CLIs own presentation and command-specific parsing; `weave` should return structured records/errors. |
| Infer overlays from RHS paths or YAML-looking values | Confirmed behavior says no-slash tokens are always value overrides, so path-like values remain valid values. |
| Accept dot-path overlay scopes | Slash scopes keep overlay grammar distinct from existing dot-path value overrides. |
| Add public compose helpers in Phase 1 | Phase 3 owns public helper integration after composition, inspection, warnings, and docs are ready. |
| Change the existing override parser | Value override syntax is already implemented and tested; Phase 1 should reuse it and only add argv classification around it. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Conditional early exposure of parser record types through `weave.api` if implementation needs it | The implementation plan allows Phase 1 record exports only if needed by the chosen public type boundary. | Refine pass or import tests show the public surface is broader than necessary; move records back internal before implementation. |
| Worktree path differs from the manager-assigned `/home/samcantrill/...` path in this environment | The assigned path is absent and not creatable by the current user, while the equivalent actual account home is available. | A later workflow requires the literal `/home/samcantrill/...` path; manager should recreate or move the worktree on a host where that path exists. |

## Reviewability

- Expected PR size and shape: small parser-focused PR with one new `weave` module, focused unit tests, and optional import/error exports only if justified.
- Files and areas to inspect: `packages/weave/src/weave/argv*.py` or equivalent new parser module, optional `packages/weave/src/weave/api.py`, optional `packages/weave/src/weave/errors.py`, `packages/weave/tests/unit/config/test_argv.py`, `packages/weave/tests/unit/config/test_overrides.py`, and `packages/weave/tests/test_import.py` if exports change.
- Scope-control checks: no edits to composition order, source artifacts, provenance, fingerprints, docs/features implementation text, Loom CLI, or runtime modules.

## Implementation Steps

1. Add the internal parser module and record dataclasses with plain-data validation patterns consistent with existing `weave` records.
2. Implement command/base-token parsing, command-choice validation, unparsed arg handling, and missing/malformed argv diagnostics.
3. Implement token classification so no-slash LHS strings lower through existing override parsing while trailing-slash LHS strings become scoped overlay request records.
4. Implement scoped overlay scope validation and RHS candidate resolution with deterministic candidate lists, resolved path selection, absolute-path exactness, suffix rules, no `~` expansion, and normalized relative escapes.
5. Add structured parser diagnostics for root overlay, invalid scope, unknown command, missing base config token, disallowed unparsed args, malformed shorthand, and missing overlay candidates.
6. Add focused tests and any narrow import/export coverage required by the implementation boundary.

## Test Plan

### Package Suite

- Status: required if parser records or errors are exported through `weave.api` or top-level `weave`; otherwise deferred with no package-surface change.
- Expected paths: `packages/weave/tests/test_import.py`
- Required assertions or deferral reason: prove `import weave` stays Loom-free, new intended `weave.api` exports are importable if added, top-level exports do not expand beyond the accepted surface, and runtime dependency declarations do not change. If Phase 1 keeps records internal, record that no package import test update is required.

### Unit Suite

- Status: required
- Expected paths: `packages/weave/tests/unit/config/test_argv.py`, `packages/weave/tests/unit/config/test_overrides.py`
- Required assertions or deferral reason: cover argv command/base parsing, command choices, missing command/base tokens, no-slash value overrides, root and dotted value keys, path-like RHS values, JSON/typed values through existing override parser, trailing-slash overlay classification, nested slash scopes, `+scope/=`, root overlay rejection, absolute/relative RHS candidate ordering, suffix probing, literal `~` handling, relative escape normalization, unparsed arg failure/allowance, and missing overlay candidate diagnostics. Existing override tests must remain green to prove value parser behavior is unchanged.

### Contract Suite

- Status: conditional/deferred
- Expected paths: `packages/weave/tests/contracts/test_config_error_contract.py` or a new `packages/weave/tests/contracts/test_config_argv_contract.py` only if Phase 1 introduces public parser records or a new public error type.
- Required assertions or deferral reason: if public, round-trip record `to_dict`/`from_dict` or equivalent plain-data shape and structured error context payloads. If records remain internal, defer stable public record-contract coverage to Phase 3 and keep record-shape assertions in unit tests.

### Integration Suite

- Status: deferred
- Expected paths: Phase 2/3 integration tests such as `packages/weave/tests/integration/config/test_compose_argv_scoped_overlays.py` or `test_compose_argv_from_cli.py`
- Required assertions or deferral reason: Phase 1 does not load YAML overlays, merge config, or call composition helpers; integration coverage starts when scoped overlays affect composed config.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase
- Required assertions or deferral reason: no first-party CLI executable or Loom CLI adapter is in scope.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: Phase 1 adds no optional dependency behavior, target checks, CLI e2e markers, or external service requirements.

## Risks

- Public record names or fields could stabilize too early if exported before Phase 3.
- Candidate resolution may accidentally imply global config groups or RHS inference; tests must keep it to local path candidates only.
- Reusing the override parser must not change existing override semantics or error behavior.
- Structured diagnostics can become too CLI-specific; keep codes helper-scoped and config-owned.
- The source plan is dirty in the control checkout and absent from the clean worktree, so reviewers must compare this phase plan against the manager-provided Stage 24 source plan until those docs are landed.

## Validation Commands

Targeted development commands:

```sh
uv run pytest packages/weave/tests/unit/config/test_argv.py
uv run pytest packages/weave/tests/unit/config/test_overrides.py
uv run pytest packages/weave/tests/test_import.py
uv run pytest packages/weave/tests/contracts/test_config_error_contract.py
```

`packages/weave/tests/test_import.py` is required when API imports are introduced. `packages/weave/tests/contracts/test_config_error_contract.py` is required when a new public error type or public structured error contract is introduced; otherwise parser diagnostics can be covered in `test_argv.py`.

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: parser records first, command/base parsing second, token classification third, candidate resolution fourth, structured diagnostics and tests last.
- Tests to run with each slice: run the new parser unit test module as it grows; run `test_overrides.py` after value lowering is wired; run import/contract tests only when public exports or public errors are added.
- Decisions the executor must not revisit: no RHS overlay inference, no dot-path overlay scopes, no composition behavior changes, no public compose helper, no warnings, no first-party CLI integration, and no Loom imports.
- Conditions that require stopping for the manager: needing a broader CLI framework, needing changes to `compose_config(...)`, needing global search paths/config groups, failing to reuse existing override parser without semantic changes, or needing to expose more public API than the plan permits.
- Expanded-path refinement notes: refine pass should review record names/field stability, whether any `weave.api` exports are truly needed in Phase 1, and whether missing-overlay diagnostics belong in parser errors or should be narrowed before implementation.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed as the phase draft artifact.
- Final phase execution plan: pending expanded-path refine pass.
- Implementation summary: pending
- Implementation validation: pending
- Refinement summary: pending
- Blocker-resolution summary: pending
- PR preparation: pending
- Stack maintenance: pending
- Remaining blockers: expanded-path refine pass must complete before product implementation begins.
