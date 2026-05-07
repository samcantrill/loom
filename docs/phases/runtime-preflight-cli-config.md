# Phase 6 Execution Plan: Runtime Preflight And CLI/Config Mapping

## Metadata

- Status: pr_open
- Feature focus: Runtime Options
- PR title: `Runtime Options - Phase 6: Runtime Preflight and CLI/Config Mapping`
- Branch: `codex/runtime-preflight-cli-config`
- Worktree: `/home/samcantrill/work/loom-worktrees/runtime-preflight-cli-config`
- Phase execution plan path: `docs/phases/runtime-preflight-cli-config.md`
- PR body draft path: `docs/phases/runtime-preflight-cli-config-pr-body.md`
- PR: https://github.com/samcantrill/loom/pull/75
- Full plan: `docs/implementation-plans/implementation-plan-v4.md`
- Source phase: Phase 6 - Runtime Preflight And CLI/Config Mapping
- Stack predecessor: none; Phases 1-5 are merged into `develop`
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop`,
  automated review passes, and validation/CI pass
- Workflow path: expanded path, draft and refine passes complete
- PR preparation path: expanded path; draft/open pass complete
- Successor dependency notes: Phase 7 should consume the normalized
  `RunOptions` and preflight diagnostics from this phase without redefining
  CLI/config parsing.
- Plan quality gate: passed on 2026-05-07
- Plan quality gate loop budget: initial review used, gate refinement used,
  confirmation review used
- Draft pass: completed by managing agent on 2026-05-07
- Refine pass: completed by managing agent on 2026-05-07; used to pin sparse
  explicit CLI merge behavior, preflight check ownership, and run-command
  executor boundaries
- Setup limitations: branch/worktree created from local `develop`; no full
  validation has run for this planning-only pass
- Blockers: none known

## Objective

Expose Phase 3-5 runtime options through top-level config sections and CLI
flags, then map normalized runtime/profile/stage/capability facts into stable
preflight checks without threading runtime options through the full run
workflow, persisting runtime metadata, or moving descriptor logic into
diagnostics.

## Full-Plan Context

Phase 3 introduced canonical `RunOptions`, per-stage runtime options, tags,
notes, selectors, resume, execution settings, and environment requests. Phase 4
added runtime profiles and deterministic base/profile/explicit merge. Phase 5
added executor descriptors and capability diagnostics. Phase 6 is the
user-input and preflight mapping layer over those contracts.

Phase 7 still owns attaching runtime options to `RunRequest`, resolved
per-stage executor handoff, and persisted `runtime.json`. Later adapter/plugin
phases own plugin discovery, executor-specific command behavior, adapter
payload schemas, and concrete executor descriptors beyond the metadata-only
`local` descriptor.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-5 are merged.
- Why this base branch is correct: `develop` contains runtime options,
  profiles, resource requests, and capability validation contracts needed by
  this phase.
- Retarget/rebase plan after predecessor merge: no predecessor retarget is
  required.
- Branch cleanup constraints: phase branch may be deleted after merge only if
  no successor phase has stacked on it.

## Source Phase Summary

- Goal: expose runtime options through config/CLI inputs and preflight
  diagnostics.
- Required scope: parse top-level `runtime` and `runtime_profiles`; add CLI
  mapping for profile, executor, run URI, dry-run, selectors, resume, tags, and
  notes; add runtime/profile/stage/executor/resource preflight checks; add
  `runtime` and `resources` preflight groups; preserve strict warning
  escalation.
- Required checkpoints: CLI/config mapping must produce normalized
  `RunOptions`; capability diagnostics must remain descriptor-owned; JSON
  preflight shape must stay stable.
- Acceptance criteria: unknown profiles and executors fail; ignored resources
  and unclaimed adapter namespaces warn; strict mode escalates warnings; group
  normalization, default group selection, stable check IDs, and serialized JSON
  are contract-tested.

## Current Source And Harness Findings

- `src/loom/pipeline/runtime/options.py` and `profiles.py` already own parsing,
  validation, and merge semantics for runtime option data. Phase 6 should call
  those helpers rather than duplicating field semantics in CLI or diagnostics.
- `src/loom/pipeline/runtime/capabilities.py` returns runtime-local
  `CapabilityDiagnostic` records. Diagnostics should map those records into
  preflight `PreflightCheckResult` objects by group/check ID, not reinterpret
  executor descriptors.
- `src/loom/diagnostics/models.py` owns `PreflightGroup`,
  `DEFAULT_PREFLIGHT_GROUPS`, `STABLE_CHECK_IDS`, preflight request/result
  serialization, and strict status aggregation.
- `src/loom/diagnostics/preflight.py` composes config lazily and already keeps
  checks grouped by stable IDs. It can be extended with cached runtime options
  and capability results.
- `src/loom/cli/options.py`, `run.py`, `plan.py`, and `preflight.py` own CLI
  option adapters. The current run command still supports only concrete local
  execution; this phase may validate selected executors in preflight but must
  not add non-local execution behavior.
- Config composition validates only the top-level composition boundary and
  leaves project-authored configs opaque. Runtime config extraction should
  treat `runtime` and `runtime_profiles` as optional top-level sections after
  composition, without changing the general config loader.
- Existing contract and integration tests cover preflight JSON shape, stable
  groups/check IDs, strict-mode warning exits, full local preflight, and CLI
  preflight orchestration.

## In-Scope Work

- Add a small runtime/config mapping helper that extracts optional top-level
  `runtime` and `runtime_profiles` sections from a resolved config mapping and
  merges them with explicit CLI/API runtime options through
  `merge_run_options`.
- Add shared CLI parsing for runtime flags:
  `--profile`, `--executor`, `--run-uri`, `--dry-run`, selector flags,
  `--resume`, repeatable `--tag KEY=VALUE`, and repeatable `--note TEXT`.
- Keep CLI flags as explicit `RunOptions` sources, layered after config
  runtime sections and the selected runtime profile. This source must be a
  sparse mapping, not a fully defaulted `RunOptions`, so absent CLI flags do
  not override config/profile fields.
- Add `PreflightGroup.RUNTIME` and `PreflightGroup.RESOURCES`, update default
  group order, group normalization, and `STABLE_CHECK_IDS`.
- Add checks for `runtime.options`, `runtime.profile`,
  `runtime.stage_options`, `executor.resolve`, `executor.capabilities`, and
  `resources.capabilities`.
- Map Phase 5 capability diagnostics into executor or resource preflight
  checks with deterministic details while preserving the existing preflight
  result JSON schema.
- Extend `PreflightRequest` with an explicit runtime-options source and keep
  `selectors` compatibility for existing callers until CLI/preflight uses the
  normalized runtime options internally.
- Let `loom run` run the new runtime preflight before concrete execution, then
  keep the existing local-only execution guard for any descriptor-known
  non-local executor that future registries might make preflight-clean.
- Preserve v3 strict behavior by keeping warnings as `WARN` results and using
  the existing CLI strict exit-code logic.
- Add focused docs if needed to describe user-facing config and CLI runtime
  inputs without claiming Phase 7 runtime persistence or executor behavior.

## Out-of-Scope Work

- Threading `RunOptions` through `RunRequest`, `PipelineRunner`, or
  `StageExecutionRequest`.
- Persisting `runtime.json`, raw adapter payloads, or environment key/value
  data.
- Plugin discovery, adapter schema validation, or third-party descriptor
  loading.
- SLURM, Docker, Apptainer, retry, timeout, remote-store, sweep, scheduler, or
  container command behavior.
- Exposing every nested runtime/profile/adapter field as CLI flags.
- Changing concrete local executor behavior or adding non-local executor
  execution support.
- Changing semantic fingerprints or persisted run-store documents.

## Assumptions

- Top-level config sections are named exactly `runtime` and
  `runtime_profiles`; absent sections mean empty runtime options and no
  profiles.
- Config-authored runtime sections are trusted project code, but their runtime
  data still passes through the strict Phase 3/4 runtime parsers.
- CLI `--tag` uses `KEY=VALUE` pairs and rejects missing or empty keys.
- CLI notes append in argument order and are plain strings.
- CLI boolean flags are explicit only when set. In particular, absent
  `--dry-run` and `--resume` must not overwrite config/profile runtime values.
- Runtime profile selection can come from config `runtime.profile` or explicit
  CLI `--profile`; explicit CLI selection wins through the existing merge
  helper.
- Stage runtime options remain exact-stage only; Phase 6 validates them against
  composed pipeline stage IDs and does not add glob, tag, or group matching.

## Scope Contract

The public runtime data model remains `RunOptions`. Config and CLI adapters
must output the same normalized `RunOptions.to_dict()` shape as the Python API.
Preflight request/result serialization remains the existing plain-data schema;
new checks only add stable group/check values and details payloads.

`runtime.options` owns parse/merge failures for runtime option data.
`runtime.profile` owns selected-profile existence and reports the active
profile when selection succeeds. `runtime.stage_options` owns exact-stage
validation against the composed pipeline's stage IDs.

`executor.resolve` owns selected-executor existence. `executor.capabilities`
owns non-resource capability diagnostics such as unclaimed adapter namespaces.
If executor resolution fails, capability checks should skip with a clear
`executor_unresolved` reason rather than duplicating the unknown-executor
failure. `resources.capabilities` owns resource support diagnostics and should
skip when the executor is unresolved. Unknown resource kinds remain Phase 2
schema errors before capability validation.

## Design Impact

- Maintainability: user input parsing remains a thin adapter over runtime
  models; descriptor logic stays in `loom.pipeline.runtime.capabilities`.
- Extensibility: future plugins can add descriptors and adapter namespaces
  without changing CLI/config merge semantics or preflight JSON shape.
- Domain neutrality: runtime sections and flags describe generic execution
  policy, not research-domain concepts.
- Source-tree boundaries: config composition stays opaque, CLI owns argparse
  surfaces, diagnostics owns check grouping, and runtime owns option/profile
  parsing.

## Future Compatibility

- Phase 7 can attach the normalized `RunOptions` object to run workflow
  requests without redesigning config or CLI parsing.
- Later executor/plugin phases can populate descriptor registries and adapter
  namespaces behind the same capability preflight checks.
- Later CLI work can expose additional nested runtime fields by extending the
  explicit `RunOptions` source rather than adding independent semantics.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Parse runtime config inside the generic config composer | It would make composition pipeline-aware and couple config loading to runtime semantics. |
| Make CLI option dataclasses authoritative semantics | It would duplicate `RunOptions`, profile merge, selector, and resume validation. |
| Map each capability diagnostic to a separate preflight check ID | It would make check ID stability depend on descriptor payloads and future plugins. |
| Replace `executor.local` with descriptor checks | Existing preflight coverage expects the concrete local availability probe; this phase should add descriptor checks without removing that probe. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Nested runtime/profile/adapter fields remain config/Python API only | This keeps CLI scope reviewable and avoids inventing ad hoc nested flag syntax. | A later roadmap requires ergonomic CLI control for a specific nested field. |
| Built-in preflight uses the default descriptor registry only | Plugin discovery is out of scope for v4 Phase 6. | A plugin/adapter roadmap adds descriptor loading or registry injection. |
| Run command still rejects non-local concrete execution after preflight | Concrete executor behavior is out of scope until Phase 7+ executor workflow work. | A later phase adds non-local executor implementations or run workflow dispatch. |

## Reviewability

- Expected PR size and shape: moderate, with one runtime config adapter, small
  CLI option changes, preflight group/check additions, and focused tests.
- Files and areas to inspect: `src/loom/pipeline/runtime/`, `src/loom/cli/`,
  `src/loom/diagnostics/`, docs describing runtime inputs, and tests under
  package/unit/contract/integration/e2e.
- Scope-control checks: no runner wiring, no runtime persistence, no plugin
  discovery, no concrete non-local executor behavior, no semantic fingerprint
  changes.

## Implementation Steps

1. Add runtime config extraction/merge helpers and tests for
   `runtime`/`runtime_profiles` plus sparse explicit runtime-option layering.
2. Extend CLI option adapters and parsers for runtime flags, tags, notes, and
   shared conversion into explicit `RunOptions`.
3. Extend preflight request/context/group/check models and map normalized
   runtime/profile/stage diagnostics into stable runtime checks.
4. Map executor descriptor resolution and Phase 5 capability diagnostics into
   executor/resource preflight checks while preserving `executor.local`.
5. Add CLI/integration/e2e coverage and concise docs for config/CLI runtime
   inputs.
6. Run targeted suites, then `make validate-pr` and `make test-summary`.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py`,
  `tests/package/test_import.py`, and public pipeline/runtime facade tests as
  needed.
- Required assertions: CLI/config runtime mapping imports remain cheap enough
  for existing boundaries; public exports are intentional.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/cli/test_options.py`,
  `tests/unit/loom/cli/test_preflight.py`, `tests/unit/loom/cli/test_run.py`,
  `tests/unit/loom/diagnostics/test_diagnostics_preflight.py`, and new/updated
  runtime config tests.
- Required assertions: tag/note parsing, explicit CLI `RunOptions` conversion,
  config runtime extraction, profile errors, stage-option errors, capability
  check formatting, and strict warning behavior.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_diagnostics_preflight_contract.py`,
  `tests/contracts/test_cli_preflight_contract.py`, and a runtime CLI/config
  mapping contract if needed.
- Required assertions: `PreflightGroup` values, default groups,
  `STABLE_CHECK_IDS`, preflight JSON shape, stable `RunOptions.to_dict()`
  output from CLI/config mapping, and strict warning escalation.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/diagnostics/test_diagnostics_preflight_integration.py`,
  `tests/integration/diagnostics/test_cli_preflight.py`, and runtime profile
  integration tests as needed.
- Required assertions: real composed configs with `runtime` and
  `runtime_profiles` produce normalized options; unknown profiles/executors
  fail; ignored local resources and unclaimed adapter namespaces warn.

### E2E Suite

- Status: required.
- Expected paths: `tests/e2e/test_cli_core.py` or a focused e2e CLI preflight
  test.
- Required assertions: local preflight on a config requesting ignored resources
  reports warnings and `--strict` exits with the existing pipeline failure
  code.

### Opt-In Suites

- Status: deferred.
- Markers affected: none beyond existing optional config dependencies.
- Required assertions or deferral reason: no backend-specific optional executor
  support is implemented in this phase.

## Risks

- Stable check ID or group order changes could break downstream preflight JSON
  consumers; contract tests must pin the new order and IDs.
- Duplicating runtime merge logic in CLI would create future drift; CLI must
  build explicit runtime sources and delegate to runtime helpers.
- Mapping all capability diagnostics into a single check per group may obscure
  details if the details payload is too sparse; include sorted diagnostic
  payloads.
- Run command behavior must remain honest: runtime options can be parsed and
  preflighted, but non-local concrete execution is still out of scope.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/test_runtime_config.py
uv run pytest tests/unit/loom/cli/test_options.py tests/unit/loom/cli/test_preflight.py tests/unit/loom/diagnostics/test_diagnostics_preflight.py
uv run pytest tests/contracts/test_diagnostics_preflight_contract.py tests/contracts/test_cli_preflight_contract.py
uv run pytest tests/integration/diagnostics/test_diagnostics_preflight_integration.py tests/integration/diagnostics/test_cli_preflight.py
uv run pytest tests/e2e/test_cli_core.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: runtime config adapter first, CLI explicit
  options second, diagnostics/preflight mapping third, docs/tests last.
- Tests to run with each slice: run the nearest unit/contract test files before
  broader integration/e2e suites.
- Decisions the executor must not revisit: no runner wiring, no runtime
  persistence, no plugin discovery, no nested adapter CLI syntax, no concrete
  non-local executor behavior.
- Conditions that require stopping for the manager: an implementation requires
  changing the `RunOptions` schema, removing existing preflight checks, changing
  persisted run records, or expanding executor behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-07
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on 2026-05-07.
- Final phase execution plan: refined on 2026-05-07.
- Implementation summary: added runtime config-section extraction and
  `merge_config_run_options`; exported config helpers from the import-light
  runtime and pipeline facades; extended sparse CLI runtime sources for
  profile, executor, run URI, dry-run, selectors, resume, tags, and notes;
  added runtime/resource preflight groups and stable check IDs; mapped runtime
  option, profile, exact-stage, executor resolve, executor capability, and
  resource capability diagnostics into preflight results; preserved local-only
  run execution and avoided runner, store, plugin, adapter schema, and
  `runtime.json` wiring.
- Implementation validation: `make validate-pr` passed on 2026-05-07,
  including Ruff, Pyright, default no-extra test harness, config-extra test
  harness, and package build. Targeted pre-validation also passed for runtime
  config/CLI/preflight unit tests, preflight contracts, package import/API
  tests, diagnostics integration tests with config extras, and CLI e2e tests
  with config extras.
- Refinement summary: bounded implementation refinement reviewed the Phase 6
  diff for scope leaks and future-version risk, then tightened preflight run
  URI precedence so an explicit `runtime_options.run_uri` wins when supplied,
  legacy `PreflightRequest.run_uri` remains compatible, and run/artifact-only
  preflight groups still skip without forcing config composition. Focused
  runtime/preflight tests, Ruff, and Pyright passed after the refinement.
- Blocker-resolution summary: pending.
- PR preparation: draft PR body committed on 2026-05-07; PR opened as
  https://github.com/samcantrill/loom/pull/75 with verified base `develop`,
  head `codex/runtime-preflight-cli-config`, and state `OPEN`; GitHub CI
  started and was initially pending.
- Stack maintenance: not needed yet.
- Remaining blockers: none known.
