# Phase 4 Execution Plan: Runtime Profiles And Merge Semantics

## Metadata

- Status: draft phase execution plan
- Feature focus: Runtime Options
- PR title: `Runtime Options - Phase 4: Runtime Profiles and Merge Semantics`
- PR URL: pending
- PR state: pending
- PR base/head: `develop` <- `codex/runtime-profiles-merge`
- Branch: `codex/runtime-profiles-merge`
- Worktree: `/home/samcantrill/work/loom-worktrees/runtime-profiles-merge`
- Phase execution plan path: `docs/phases/runtime-profiles-merge.md`
- Full plan: `docs/implementation-plans/implementation-plan-v4.md`
- Source phase: Phase 4 - Runtime Profiles And Merge Semantics
- Stack predecessor: none; Phases 1-3 are merged into `develop`
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop`, automated review passes, and validation/CI pass
- Workflow path: expanded path, draft pass only in this assignment
- Plan quality gate: passed on 2026-05-07 after initial review, refinement, and confirmation review
- Plan quality gate loop budget: initial review used, gate refinement used, confirmation review used
- Draft pass: completed by `loom_phase_planner`
- Refine pass: unused in this draft assignment; expected only if the manager continues the expanded path before implementation
- Blockers: none known

## Objective

Add import-light runtime profile models and deterministic merge helpers so
Python callers can combine base runtime options, a selected runtime profile, and
explicit invocation options into canonical `RunOptions` and
`StageRuntimeOptions` objects before descriptor validation, config/CLI mapping,
preflight wiring, runner handoff, or persisted runtime metadata exist.

## Full-Plan Context

Phase 1 split `loom.pipeline.runtime` into an import-light facade. Phase 2
hard-swapped resources to entry-based `ResourceRequest`. Phase 3 added
`RunOptions`, `ExecutionOptions`, `StageRuntimeOptions`, run/stage environment
requests, safe summaries, planning adapters, and exact-stage validation. Phase
4 must build on those public models without redefining their field shape.

Later phases own executor descriptors and capability diagnostics, config and
CLI mapping, preflight check IDs/groups, `RunRequest.options` workflow wiring,
resolved per-stage executor handoff data, and persisted `runtime.json`.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 1 PR #70, Phase 2 PR #71, and
  Phase 3 PR #72 are merged.
- Why this base branch is correct: `develop` includes Phase 3 runtime models
  and v4 merge metadata, so Phase 4 does not need a stacked predecessor.
- Retarget/rebase plan after predecessor merge: no predecessor retarget is
  required.
- Branch cleanup constraints: phase branch may be deleted after merge only if
  no successor phase has stacked on it.

## Source Phase Summary

- Goal: add runtime profiles and deterministic option/profile merge behavior.
- Required scope: implement `RuntimeProfile`, profile collections and
  selection, strict validation for core profile sections, adapter namespace
  preservation as plain data, deterministic precedence
  `config base < selected profile < explicit CLI/API invocation options`, and
  exact-stage stage-option merge plus known-stage validation.
- Acceptance criteria: Python callers can normalize runtime options from
  base/profile/explicit sources; stage options merge and validate by exact
  stage ID; profile core sections are strict; adapter namespaces are preserved
  as plain data; profile selection and schema failures are clear.

## Current Source And Harness Findings

- `src/loom/pipeline/runtime/options.py` owns `RunOptions`,
  `ExecutionOptions`, `StageRuntimeOptions`, `parse_run_options`, and
  `validate_stage_runtime_options`.
- `src/loom/pipeline/runtime/environment.py` owns strict run/stage environment
  request models and privacy-preserving safe summaries.
- `src/loom/pipeline/runtime/__init__.py` and `src/loom/pipeline/__init__.py`
  expose the current runtime option API; Phase 4 should add profile/merge names
  there without making runtime imports eager.
- Package import-boundary tests already assert `loom.pipeline.runtime` does not
  import CLI, config, diagnostics, execution, executors, plugins, optional
  backend packages, or project modules.
- Phase 3 contract tests intentionally assert `RunRequest` has no `options`
  field and `StageExecutionRequest` has no runtime/environment handoff field;
  Phase 4 must preserve that boundary.

## In-Scope Work

- Add focused runtime profile and merge behavior under `loom.pipeline.runtime`,
  likely in a `profiles` or similarly narrow submodule, with public facade
  exports.
- Implement immutable, plain-data-compatible `RuntimeProfile` and
  profile-collection/selection models or helpers.
- Define profile names as explicit, non-empty keys with deterministic ordering
  and path-aware failures for missing, unknown, duplicate, or invalid selected
  profiles.
- Parse profile core sections into existing typed runtime models:
  `executor`, `dry_run`, `tags`, `notes`, `selectors`, `resume`, `execution`,
  `stage_options`, `environment`, and `adapter_options`.
- Validate core profile sections strictly by reusing `RunOptions`,
  `ExecutionOptions`, `StageRuntimeOptions`, `RunEnvironmentRequest`, and
  `StageEnvironmentRequest` parsing rules.
- Preserve non-core adapter namespace sections as frozen plain data without
  interpreting or warning on namespace ownership, and normalize them into the
  `RunOptions.adapter_options` namespace surface during merge.
- Implement deterministic merge helpers that combine base options, the selected
  profile, and explicit options with this precedence:
  `config base < selected profile < explicit CLI/API invocation options`.
- Merge mappings shallowly unless an existing typed model owns stricter
  behavior; replace scalar values and lists/tuples; merge `stage_options` by
  exact stage ID.
- For a stage ID present in multiple sources, merge its
  `StageRuntimeOptions` fields by the same deterministic rules:
  resources merge through typed `ResourceRequest` entry identity where supplied,
  execution settings merge shallowly, environment fields use explicit model
  semantics, and adapter option namespaces are preserved as shallow mapping data.
- Support post-pipeline known-stage validation by composing with the existing
  exact-stage validation helper rather than graph-aware planning behavior.
- Add tests and docs that make the merge policy observable and stable for later
  config/CLI and workflow phases.

## Out-of-Scope Work

- Executor descriptors, executor registries, capability records, ignored local
  resource warnings, unknown executor resolution, or unclaimed adapter namespace
  warnings.
- Preflight checks, preflight groups, stable check IDs, strict-mode warning
  escalation, or JSON diagnostic output.
- Persisted `runtime.json`, run-store APIs, runtime metadata writes, or raw
  adapter payload persistence policy beyond existing safe summaries.
- CLI flags, CLI parsing, config command mapping, config composition wiring, or
  user-facing `runtime` / `runtime_profiles` ingestion.
- Plugins, plugin discovery, adapter schemas, SLURM/Docker/Apptainer
  interpretation, retry, timeout, wall-time, subprocess, worker, or scheduler
  behavior.
- Adding `RunRequest.options`, threading `RunOptions` through
  `PipelineRunner`, `run_pipeline`, `StageExecutionRequest`, stores,
  diagnostics, or CLI entrypoints.
- Glob, tag, group, pattern, graph reachability, or eligibility-based stage
  option matching.

## Assumptions

- "Config base" in Phase 4 means a caller-supplied `RunOptions` or mapping
  shaped like future config runtime data; config files are not parsed or
  composed in this phase.
- "Explicit CLI/API invocation options" means a caller-supplied final
  `RunOptions` or mapping. CLI flags themselves are Phase 6 scope.
- `RunOptions.profile` selects a profile by name during merge. The resolved
  output should retain the selected profile name for later metadata and
  diagnostics, but the profile selection object must not imply executor
  capability validation.
- Optional or absent values should not clobber lower-precedence values unless a
  source explicitly represents replacement according to the model contract. If
  this cannot be expressed cleanly with current `RunOptions` defaults, stop for
  the manager rather than inventing broad sentinel semantics.
- Adapter namespaces are opaque plain data in this phase. Preservation covers
  explicitly supplied `adapter_options` data and non-core top-level profile
  namespace sections, with deterministic freeze/serialization and shallow
  namespace merge but no schema validation.

## Scope Contract

`RuntimeProfile` is an operational-defaults model. It must not become a
pipeline semantic model, executor descriptor, preflight diagnostic, or CLI
argument container. Its core fields must be the existing runtime option fields
owned by Phase 3. Unknown or invalid core fields fail with clear, path-aware
errors. Non-core top-level profile sections are preserved as adapter namespace
payloads and merge into `RunOptions.adapter_options`; they are not interpreted
as executor descriptors or schemas in this phase.

Profile collections own selection, missing-profile errors, and deterministic
serialization. They should accept plain mapping input for Python callers and
future config mapping, but they must not import `loom.config` or depend on
Hydra/OmegaConf/YAML/Pydantic.

Merge helpers return normalized `RunOptions`. They must not return raw
dictionaries that later phases need to reinterpret. The merge policy is a
public contract: lower precedence values provide defaults, selected profile
values override base values, and explicit invocation values override both.
Mappings merge shallowly, scalars replace, lists/tuples replace, and typed
models decide their own nested behavior.

Stage runtime options merge only by exact stage ID. If `extract` appears in
base and profile data, the result is one `extract` `StageRuntimeOptions` built
from merged typed fields. If a profile mentions an unknown stage, the model can
be constructed but supplied known-stage validation must fail deterministically
after the pipeline's canonical stage IDs are known.

## Acceptance Criteria

- Public imports expose runtime profile and merge APIs from
  `loom.pipeline.runtime` and `loom.pipeline` without breaking existing imports.
- Python callers can construct and serialize runtime profiles and profile
  collections from plain data.
- Unknown core profile fields and invalid core section shapes fail with clear
  path-aware errors.
- Selecting a missing or invalid profile fails clearly before merge.
- Base/profile/explicit sources merge deterministically into a normalized
  `RunOptions`.
- Scalars and sequences replace; mappings merge shallowly; `stage_options`
  merge by exact stage ID.
- Adapter namespaces and payloads, including non-core top-level profile
  sections, are preserved as frozen plain data without descriptor/schema
  interpretation.
- Known-stage validation catches unknown merged stage-option IDs when supplied
  canonical stage IDs are available.
- Existing Phase 3 runtime option, planning adapter, safe metadata, import
  boundary, and execution-envelope boundary tests remain valid.

## Design Impact

- Maintainability: centralizes profile selection and merge semantics in the
  runtime package instead of letting future config, CLI, and runner code each
  invent precedence behavior.
- Extensibility: gives future descriptor, config/CLI, workflow, executor,
  sweep, and plugin phases one normalized `RunOptions` result to consume.
- Domain neutrality: profiles describe invocation policy only; they do not
  encode domain-specific pipeline behavior or backend-specific semantics.
- Source-tree boundaries: runtime profiles remain import-light and below
  config/CLI/diagnostics/execution runners.

## Future Compatibility

- Phase 5 can validate resolved executor, resources, and adapter namespaces
  against descriptors without changing the merge output shape.
- Phase 6 can map config and CLI inputs into the same base/profile/explicit
  merge helpers instead of duplicating precedence rules.
- Phase 7 can attach the already-resolved `RunOptions` to `RunRequest.options`
  and derive per-stage runtime handoff data without re-running raw profile
  merge logic.
- Future adapter/plugin phases can claim preserved adapter namespaces and add
  schema validation around the same opaque data boundary.
- Future sweep or profile-composition work can build on deterministic profile
  collection serialization and exact-stage merge rules.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Deep arbitrary merge for all nested fields | It makes adapter payload behavior hard to predict and conflicts with the v4 shallow-merge design choice. |
| List concatenation | Replacement is deterministic, easier to reason about, and avoids accidental duplicate selectors, notes, or unset variables. |
| CLI-specific precedence | The public Python/runtime API is the source of truth; CLI is only a later adapter. |
| Silently accept misspelled core fields as adapter namespaces | Core runtime fields must stay strict so profile typos fail; intentional non-core namespaces remain preserved as adapter data. |
| Glob, tag, group, or pattern stage matching | Exact stage IDs are the v4 contract and avoid inventing graph or selection policy in runtime. |
| Validate executor names or adapter namespaces during merge | Descriptor/capability ownership starts in Phase 5. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No glob/tag/group stage option matching | Exact IDs keep merge deterministic and reviewable. | Revisit only when a later roadmap phase defines matching semantics. |
| Adapter payloads are preserved but not validated | Phase 4 must not introduce descriptors, schemas, or plugins. | Revisit in descriptor, adapter, and plugin phases. |
| Config-shaped data is supported only as plain mappings | Config loading and CLI mapping are Phase 6 scope. | Revisit when Phase 6 wires config and CLI inputs. |
| No explicit user-facing profile command behavior | This phase is Python/runtime API behavior only. | Revisit in Phase 6 CLI/config mapping. |

## Reviewability

- Expected PR size and shape: small-to-medium model/test PR, focused on one new
  runtime profile/merge module, facade exports, targeted docs, and tests.
- Files and areas to inspect:
  - `src/loom/pipeline/runtime/`
  - `src/loom/pipeline/__init__.py`
  - `tests/package/test_import_boundaries.py`
  - `tests/package/test_pipeline_api.py`
  - `tests/unit/loom/pipeline/test_runtime_options.py`
  - new `tests/unit/loom/pipeline/test_runtime_profiles.py` or equivalent
  - new `tests/contracts/test_runtime_profiles_contract.py` or equivalent
  - `tests/integration/pipeline/test_runtime_options_integration.py` or a new
    narrow runtime profile integration test
  - `docs/features/runtime-resources.md` if public profile/merge prose needs to
    be updated
- Scope-control checks: no `loom.config`, `loom.cli`, diagnostics, execution
  runner, executor descriptor, store, plugin, or optional backend imports from
  `loom.pipeline.runtime`.

## Implementation Steps

1. Add the runtime profile model surface with strict parsing, deterministic
   serialization, profile-name validation, and facade exports.
2. Add profile collection/selection helpers with clear errors for missing or
   invalid selected profiles.
3. Add merge helpers for base/profile/explicit sources that return normalized
   `RunOptions` and preserve existing Phase 3 model behavior.
4. Add exact-stage merge behavior for `StageRuntimeOptions` and compose with
   known-stage validation after merge.
5. Add package, unit, contract, and narrow integration tests that pin import
   boundaries, selection failures, schema failures, adapter namespace
   preservation, and deterministic merge rules.
6. Update focused runtime resource/profile docs if needed to describe the
   implemented profile merge contract without adding Phase 6 config/CLI claims.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py`,
  `tests/package/test_pipeline_api.py`.
- Required assertions or deferral reason: runtime profile and merge APIs are
  exported from `loom.pipeline.runtime` and `loom.pipeline`; runtime facade
  remains import-light and does not import CLI, config, diagnostics, execution
  runners, concrete executors, plugins, optional backend packages, or project
  modules.

### Unit Suite

- Status: required.
- Expected paths: new or existing
  `tests/unit/loom/pipeline/test_runtime_profiles.py` plus focused updates to
  `tests/unit/loom/pipeline/test_runtime_options.py` if needed.
- Required assertions or deferral reason: profile construction,
  serialization, strict core-field validation, selected-profile success and
  failures, schema errors, base/profile/explicit precedence, scalar/list
  replacement, shallow mapping merge, exact-stage option merge, adapter
  namespace preservation, and known-stage validation after merge.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_runtime_profiles_contract.py` or
  similarly focused coverage.
- Required assertions or deferral reason: plain-data profile serialization and
  deterministic merge contract, including that callers receive normalized
  `RunOptions`, adapter namespaces are preserved as plain data, and runtime
  merge does not import or depend on config/CLI/execution/descriptors.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/pipeline/test_runtime_profiles_integration.py`
  or focused additions near `tests/integration/pipeline/test_runtime_options_integration.py`.
- Required assertions or deferral reason: config-shaped base/profile/explicit
  dictionaries normalize to expected `RunOptions` using synthetic exact stage
  IDs; known-stage validation succeeds/fails deterministically after merge.
  No actual config loader, CLI, runner, preflight, or store wiring is required.

### E2E Suite

- Status: deferred.
- Expected paths: none.
- Required assertions or deferral reason: Phase 4 adds public Python model and
  merge behavior only; it does not expose CLI/config/run workflow behavior.
  Existing e2e coverage should remain green through `make validate-pr`.

### Opt-In Suites

- Status: deferred.
- Markers affected: none.
- Required assertions or deferral reason: no SLURM, Docker, Apptainer,
  network, plugin discovery, scheduler, or other optional backend behavior is
  introduced.

## Risks

- Merge semantics become a durable public contract. Tests must pin precedence,
  replacement, shallow mapping behavior, and exact-stage merge behavior.
- Current `RunOptions` defaults can make "unset" versus "explicit default"
  ambiguous. If preserving lower-precedence values cannot be done without a
  clear caller contract, stop for the manager instead of adding broad sentinel
  behavior.
- Adapter namespace preservation can drift into schema validation. Keep
  adapter data opaque and leave warnings/claims to Phase 5.
- Import boundaries can regress if profile code imports config, CLI, execution,
  diagnostics, descriptors, or optional dependencies.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py
uv run pytest tests/unit/loom/pipeline/test_runtime_options.py tests/unit/loom/pipeline/test_runtime_profiles.py
uv run pytest tests/contracts/test_runtime_options_contract.py tests/contracts/test_runtime_profiles_contract.py
uv run pytest tests/integration/pipeline -k "runtime_options or runtime_profiles"
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: profile model and exports first, selection
  helpers second, merge helpers third, docs/tests last.
- Tests to run with each slice: package import tests after facade changes; unit
  profile tests after model/selection changes; merge contract tests after
  helpers; narrow integration tests after known-stage validation composition.
- Decisions the executor must not revisit: precedence is
  `config base < selected profile < explicit CLI/API invocation options`;
  mappings merge shallowly except where typed models own stricter behavior;
  scalars and lists/tuples replace; stage options merge by exact stage ID; no
  descriptor/preflight/config/CLI/runtime.json/plugin/runner behavior belongs
  in this phase.
- Conditions that require stopping for the manager: current `RunOptions`
  defaults cannot distinguish absent from explicit values well enough to
  preserve deterministic precedence; profile merge needs public sentinel or
  replacement semantics not approved by the plan; satisfying tests requires
  importing config/CLI/execution/descriptors; adapter namespace preservation
  cannot be represented without schema validation.

## Refinement And Review Budget Status

- Phase execution plan draft: used on 2026-05-07.
- Phase execution plan refine: unused; expanded-path continuation is expected
  only if the manager assigns a refine pass before implementation.
- Phase implementation refinement: unused; reserved for the implementation
  stage if targeted validation fails, suite coverage is missing, or the manager
  continues the expanded path.
- PR body draft: unused; reserved for PR preparation.
- PR body refine/open pass: unused; reserved for PR preparation.
- PR review: unused; reserved for automated PR review.
- Blocker-resolution budget: unused, 0 of 3 scoped passes consumed.
