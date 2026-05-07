# Phase 5 Execution Plan: Executor Descriptors And Capability Validation

## Metadata

- Status: draft phase execution plan
- Feature focus: Runtime Options
- PR title: `Runtime Options - Phase 5: Executor Descriptors and Capability Validation`
- Branch: `codex/executor-capabilities`
- Worktree: `/home/samcantrill/work/loom-worktrees/executor-capabilities`
- Phase execution plan path: `docs/phases/executor-capabilities.md`
- Full plan: `docs/implementation-plans/implementation-plan-v4.md`
- Source phase: Phase 5 - Executor Descriptors And Capability Validation
- Stack predecessor: none; Phases 1-4 are merged into `develop`
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop`, automated review passes, and validation/CI pass
- Workflow path: expanded path, draft pass only
- Successor dependency notes: Phase 6 should consume these descriptor and validation contracts for preflight/CLI/config diagnostics; Phase 7 should not reinterpret raw capability data.
- Plan quality gate: passed on 2026-05-07
- Plan quality gate loop budget: initial review used, gate refinement used, confirmation review used
- Draft pass: completed by `loom_phase_planner` on 2026-05-07
- Refine pass: pending because the manager selected the expanded path; not consumed in this draft pass
- Setup limitations: branch/worktree created from local `develop`; no remote fetch or broad validation was run for this draft-only planning pass
- Blockers: none known

## Objective

Add import-light executor descriptor, capability, registry, and runtime
capability-validation contracts so selected executor names, stage resource
entries, local ignored-resource policy, and adapter namespace ownership can be
checked before preflight, CLI/config mapping, runner wiring, plugin discovery,
or executor behavior changes exist.

## Full-Plan Context

Phase 1 created the import-light `loom.pipeline.runtime` facade. Phase 2
introduced entry-based `ResourceRequest` and explicit resource validator
registries. Phase 3 added `RunOptions`, `StageRuntimeOptions`, environment
requests, safe summaries, and planning adapters. Phase 4 added runtime
profiles and deterministic base/profile/explicit merge into normalized
`RunOptions`.

Phase 5 must consume those models and add metadata-only executor capability
validation. Later phases own preflight check IDs/groups and strict-mode
escalation, CLI/config runtime mapping, `RunRequest.options`, resolved
per-stage executor handoff, persisted `runtime.json`, plugin discovery, and
SLURM/Docker/Apptainer schemas.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 1 PR #70, Phase 2 PR #71,
  Phase 3 PR #72, and Phase 4 PR #73 are merged.
- Why this base branch is correct: `develop` includes the runtime package
  boundary, typed resources, run options/environment models, and runtime
  profile merge contract needed by this phase.
- Retarget/rebase plan after predecessor merge: no predecessor retarget is
  required.
- Branch cleanup constraints: phase branch may be deleted after merge only if
  no successor phase has stacked on it.

## Source Phase Summary

- Goal: add structured executor capability metadata and validation contracts.
- Required scope: executor descriptor records, structured capability and
  diagnostic policy, immutable/import-light registry contracts, built-in
  metadata-only `local` descriptor, resource capability validation for already
  validated resource entries, ignored local resource warnings, unknown
  executor failures, and unclaimed adapter namespace warnings.
- Required checkpoints: keep descriptor metadata separate from concrete
  executor implementations; keep validation diagnostics independent of
  preflight result models; keep resource schema validation failures separate
  from capability diagnostics.
- Acceptance criteria: runtime validation can inspect executor capabilities
  without constructing executors; unknown selected executors fail; ignored
  local resources and unclaimed adapter namespaces warn; capability support is
  structured enough for support level, enforcement expectation, default
  severity, and details; fake descriptors can claim or reject resource kinds
  without changing `ResourceRequest`.

## Current Source And Harness Findings

- `src/loom/pipeline/runtime/options.py` owns `RunOptions`,
  `ExecutionOptions`, `StageRuntimeOptions`, `parse_run_options`, and
  `validate_stage_runtime_options`.
- `src/loom/pipeline/runtime/profiles.py` owns profile parsing, selection, and
  `merge_run_options`; Phase 5 should validate the normalized output rather
  than reimplement profile merge rules.
- `src/loom/pipeline/resources.py` owns `ResourceEntry`,
  `ResourceRequest`, built-in `cpu`/`memory`/`gpu` validators, explicit
  `ResourceValidatorRegistry` composition, duplicate registration failures,
  and unregistered-kind schema errors.
- `src/loom/pipeline/executors/base.py` defines the runtime-checkable
  `Executor` protocol and imports execution request/result types only under
  `TYPE_CHECKING`; `local.py` constructs real in-process executor behavior and
  must not be imported by runtime descriptor modules.
- `src/loom/pipeline/executors/__init__.py` currently exports
  `Executor`, `ExecutorError`, `LocalExecutor`, and `LocalExecutorError`;
  descriptor exports should not force optional backend or plugin imports.
- Package import-boundary tests already assert `loom.pipeline.runtime` does not
  import CLI, config, diagnostics, execution, concrete executors, plugins, or
  optional backend packages.
- Existing contract tests assert the execution-envelope boundary remains
  unwired; Phase 5 must not add `RunRequest.options` or runtime fields on
  `StageExecutionRequest`.
- Existing integration coverage constructs runtime options with synthetic
  exact stage IDs; Phase 5 integration tests can use the same pattern without
  touching CLI, config loaders, runner workflows, or preflight.

## In-Scope Work

- Add descriptor, resource-capability, adapter-namespace, diagnostic-policy,
  registry, and validation models under the import-light runtime boundary,
  with public facade exports consistent with existing runtime model exports.
- Define executor descriptor identity around normalized executor names, with a
  deterministic immutable registry and duplicate-name rejection.
- Add a built-in default registry containing a metadata-only `local`
  descriptor without importing or constructing `LocalExecutor`.
- Treat `RunOptions.executor` as the selected executor when present and the
  local default when absent for capability validation, matching current local
  runner/CLI defaults without wiring this into runner behavior.
- Validate selected executor names through the descriptor registry: unknown
  names produce an error diagnostic and strict validation fails clearly.
- Validate only already parsed and schema-valid `ResourceRequest` entries
  against descriptor capability metadata; unregistered resource kinds remain
  `ResourceRequest` schema errors from Phase 2.
- Represent resource support with structured data that can carry support
  level, enforcement expectation, default severity, and plain diagnostic
  details. Local `cpu`, `memory`, and `gpu` support should warn that local
  execution ignores or does not enforce those requests.
- Let fake/custom descriptors claim, ignore, warn, or reject registered
  resource kinds through descriptor metadata without changing resource entry
  parsing or validator registries.
- Validate run-level and exact-stage `adapter_options` namespaces against
  descriptor-claimed namespaces and warn for unclaimed namespaces by default.
- Return deterministic, path-aware runtime capability diagnostics without
  importing `loom.diagnostics` or assigning preflight check IDs/groups.
- Add focused docs if needed to describe descriptor/capability contracts
  without claiming Phase 6 preflight or CLI behavior.

## Out-of-Scope Work

- Preflight check wiring, `PreflightGroup` changes, `STABLE_CHECK_IDS`,
  strict-mode warning escalation, JSON preflight result shape, or user-facing
  preflight command output.
- Plugin discovery, entry point loading, third-party descriptor discovery, or
  mutable process-global registration.
- SLURM, Docker, Apptainer, subprocess, retry, timeout, wall-time,
  remote-store, sweep, scheduler, or container option schemas.
- CLI/config runtime mapping, `runtime` / `runtime_profiles` config ingestion,
  CLI flags, or command behavior changes.
- `RunRequest.options`, `StageExecutionRequest.resolved_runtime`, runner
  wiring, `PipelineRunner` behavior, executor selection changes, or local
  executor enforcement changes.
- Persisted `runtime.json`, run-store APIs, raw adapter payload persistence, or
  environment key/value persistence.
- Semantic fingerprint changes.

## Assumptions

- Descriptor validation operates on normalized Python runtime objects or
  mappings parsed into `RunOptions`; config and CLI adapters will call the same
  helpers in Phase 6.
- `RunOptions.executor=None` means "use the current local default" for this
  phase's validation helpers only. This does not add runner wiring or change
  existing execution selection.
- Descriptor names use the same non-empty string standard as existing runtime
  option executor names, with additional normalization only when it is already
  needed for deterministic registry lookup.
- Capability diagnostics are runtime validation records, not preflight check
  results. Phase 6 may map these records into stable preflight IDs and groups.
- Descriptor-claimed adapter namespaces identify ownership only. This phase
  does not validate payload schemas or persist payload contents.

## Scope Contract

Executor descriptors are scheduler-neutral metadata. They describe what a
selected executor claims, ignores, or rejects without constructing an executor
or importing concrete executor modules. Runtime descriptor modules must remain
below CLI, config, diagnostics, execution runners, concrete executors, plugins,
and optional backend packages.

The descriptor registry is explicit and deterministic. The built-in default
registry contains `local`; tests can compose fake registries for additional
descriptors. Duplicate descriptor names fail rather than replace existing
metadata. Unknown executor resolution is an error, while unsupported resource
entries and unclaimed adapter namespaces are diagnostics whose severity comes
from descriptor policy.

Resource schema validation remains owned by `loom.pipeline.resources`.
Capability validation must never accept an unregistered resource kind by
itself, and it must not alter `ResourceRequest` parsing. A registered resource
kind that a descriptor does not claim is a capability diagnostic, not a
resource schema error.

Adapter namespaces remain opaque plain data. Validation checks namespace
ownership at run level and per exact stage ID and reports unclaimed namespaces
with stable paths. It must not deep-merge, inspect, or schema-validate adapter
payloads.

## Design Impact

- Maintainability: centralizes executor metadata and capability policy before
  preflight, CLI, and runner code can create parallel executor-name/resource
  interpretations.
- Extensibility: gives future executor, adapter, and plugin phases a common
  descriptor registry and capability diagnostic surface to populate.
- Domain neutrality: descriptors describe generic executor capabilities and
  adapter namespaces, not project-specific stage behavior or research data.
- Source-tree boundaries: descriptor records live on the import-light runtime
  side; concrete executor behavior stays under `loom.pipeline.executors`.

## Future Compatibility

- Phase 6 can map runtime capability diagnostics into
  `executor.resolve`, `executor.capabilities`, and `resources.capabilities`
  preflight checks without redesigning descriptor metadata.
- Phase 7 can persist safe runtime summaries and build resolved stage runtime
  handoff data using the selected descriptor outcome rather than raw adapter
  payloads.
- Future subprocess, SLURM, Docker, Apptainer, and plugin phases can register
  descriptors for new executor names, resource kinds, and adapter namespaces
  without changing `RunOptions` or `ResourceRequest`.
- Future adapter-schema phases can replace namespace-only claims with deeper
  validation while preserving this phase's warning behavior for unclaimed
  namespaces.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Name-only executor registry | It cannot distinguish ignored, advisory, unsupported, and enforced capabilities or produce useful resource diagnostics. |
| String-only capability statuses | Later preflight and executor phases need structured support level, enforcement expectation, default severity, and details. |
| Eager registry entries that import concrete executors | This would violate the runtime import-light boundary and pull execution behavior into model validation. |
| Resource schema changes for executor support | Phase 2 intentionally made resources executor-neutral; capability checks should sit beside the schema, not inside it. |
| Plugin discovery in this phase | V4 establishes registry contracts only; entry point discovery is a later roadmap phase. |
| Preflight result models as the diagnostic type | Lower runtime layers must not import diagnostics, and Phase 6 owns preflight groups/check IDs. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Adapter namespace validation is ownership-only | Deep schema validation belongs to adapter/executor/plugin phases. | Revisit when a concrete adapter descriptor defines a safe public schema. |
| Built-in registry contains only local metadata | V4 should not introduce subprocess, scheduler, container, or plugin behavior early. | Revisit in the first executor-specific roadmap phase. |
| Capability diagnostics are not preflight check results yet | Phase 5 is a model/contract phase and must stay below diagnostics. | Revisit in Phase 6 runtime preflight mapping. |

## Reviewability

- Expected PR size and shape: small-to-medium model/test PR, focused on new
  runtime descriptor/capability modules, facade exports, optional executor API
  export updates, and targeted docs/tests.
- Files and areas to inspect:
  - `src/loom/pipeline/runtime/`
  - `src/loom/pipeline/__init__.py`
  - `src/loom/pipeline/executors/__init__.py` only if descriptor exports are
    intentionally surfaced there without importing implementations
  - `tests/package/test_import_boundaries.py`
  - `tests/package/test_pipeline_api.py`
  - `tests/package/test_pipeline_executor_api.py`
  - new `tests/unit/loom/pipeline/test_executor_capabilities.py` or similar
  - `tests/contracts/test_executor_contract.py`
  - new `tests/contracts/test_executor_capabilities_contract.py` or similar
  - new or existing runtime integration tests under `tests/integration/pipeline/`
  - `docs/features/runtime-resources.md` and `docs/features/execution.md` if
    public descriptor/capability prose needs updates
- Scope-control checks: no imports from runtime descriptor/validation modules
  to CLI, config, diagnostics, execution runners, concrete executors, plugins,
  optional backend packages, stores, or project modules.

## Implementation Steps

1. Add import-light descriptor, capability, diagnostic, and registry models
   with deterministic serialization, duplicate-name rejection, and facade
   exports.
2. Add the metadata-only built-in `local` descriptor and default registry
   without importing `LocalExecutor` or changing executor behavior.
3. Add runtime capability validation helpers for selected executor resolution,
   registered resource entries in run stage options, ignored local resources,
   unsupported resource kinds, and unclaimed run/stage adapter namespaces.
4. Add fake descriptor tests that prove descriptors can claim, ignore, warn,
   or reject registered resource kinds without altering `ResourceRequest`.
5. Add package, unit, contract, and narrow integration coverage for import
   boundaries, registry behavior, diagnostic paths/severities, local defaults,
   and Phase 4 merged `RunOptions` consumption.
6. Update focused runtime/execution docs if needed, without adding Phase 6
   preflight, CLI/config, plugin, or executor-schema claims.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py`,
  `tests/package/test_pipeline_api.py`, and
  `tests/package/test_pipeline_executor_api.py` if executor facade exports
  change.
- Required assertions or deferral reason: descriptor, registry, capability,
  and validation APIs are exported from the intended public facades; importing
  `loom.pipeline.runtime` remains import-light and does not import CLI,
  config, diagnostics, execution runners, concrete executors, plugins,
  optional backend packages, stores, or project modules.

### Unit Suite

- Status: required.
- Expected paths: new `tests/unit/loom/pipeline/test_executor_capabilities.py`
  or equivalent, plus focused updates to runtime resource/options tests only
  when needed.
- Required assertions or deferral reason: descriptor construction and
  serialization, capability support records, diagnostic policy/severity
  defaults, registry lookup and duplicate rejection, default `local`
  descriptor behavior, `RunOptions.executor=None` resolving to local for
  validation, unknown executor error diagnostics and strict failure,
  registered resource support/ignore/reject behavior, ignored local resource
  warnings, unclaimed run/stage adapter namespace warnings, path-aware
  diagnostics, and deterministic result ordering.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_executor_contract.py` plus new
  `tests/contracts/test_executor_capabilities_contract.py` or equivalent.
- Required assertions or deferral reason: descriptor protocol/data contract is
  structural and import-light; fake descriptors can claim or reject resource
  kinds without changing resource schema validation; capability diagnostics are
  plain-data-compatible and independent of `loom.diagnostics`; `RunRequest` and
  `StageExecutionRequest` remain unwired for runtime options in this phase.

### Integration Suite

- Status: required.
- Expected paths:
  `tests/integration/pipeline/test_runtime_capabilities_integration.py` or
  focused additions near existing runtime option/profile integration tests.
- Required assertions or deferral reason: normalized or merged `RunOptions`
  with synthetic exact stage IDs validate against the default local descriptor;
  local resource requests produce warnings; unknown selected executors fail;
  fake custom descriptors validate custom registered resource kinds; unclaimed
  adapter namespaces warn without invoking config, CLI, runner, stores, or
  preflight.

### E2E Suite

- Status: deferred.
- Expected paths: none.
- Required assertions or deferral reason: Phase 5 adds Python model/validation
  contracts only; there is no CLI/config/preflight/run workflow behavior yet.
  Existing e2e coverage should remain green through `make validate-pr`.

### Opt-In Suites

- Status: deferred.
- Markers affected: none.
- Required assertions or deferral reason: no SLURM, Docker, Apptainer,
  network, plugin discovery, scheduler, or optional backend behavior is
  introduced.

## Risks

- Descriptor models can accidentally become executor factories. Keep them as
  metadata only and test that runtime imports do not load concrete executors.
- Capability diagnostics can drift into preflight result ownership. Keep them
  path-aware and plain-data-compatible, but leave preflight groups/check IDs to
  Phase 6.
- Local ignored-resource policy may create warning noise. Tests should pin
  the intended local behavior so later CLI/preflight strict-mode mapping is
  deliberate.
- Registered custom resource kinds require explicit test registries; do not
  relax Phase 2 unregistered-kind schema errors to make capability tests pass.
- Adapter namespace claims can drift into schema interpretation. Keep payloads
  opaque until adapter-specific phases own those schemas.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py tests/package/test_pipeline_executor_api.py
uv run pytest tests/unit/loom/pipeline/test_runtime_resources.py tests/unit/loom/pipeline/test_runtime_options.py tests/unit/loom/pipeline/test_executor_capabilities.py
uv run pytest tests/contracts/test_executor_contract.py tests/contracts/test_runtime_options_contract.py tests/contracts/test_executor_capabilities_contract.py
uv run pytest tests/integration/pipeline -k "runtime_options or runtime_profiles or runtime_capabilities or executor_capabilities"
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: descriptor/registry models first, local
  descriptor/default registry second, capability validation helpers third,
  tests/docs last.
- Tests to run with each slice: package import-boundary tests after exports,
  unit tests after descriptor/validation helpers, contract and integration
  tests after fake registry behavior exists.
- Decisions the executor must not revisit: no preflight wiring, no plugin
  discovery, no executor implementation changes, no resource schema changes,
  no CLI/config mapping, no runner wiring, and no adapter payload schema
  validation.
- Conditions that require stopping for the manager: implementing Phase 5 would
  require importing concrete executor implementations from runtime modules,
  changing `ResourceRequest` unknown-kind behavior, adding preflight groups or
  check IDs, or changing execution request/runner behavior.

## Refinement And Review Budget Status

- Phase plan refinement: unused; pending expanded-path refine assignment
- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on 2026-05-07 by `loom_phase_planner`.
- Final phase execution plan: pending expanded-path refine pass.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- Blocker-resolution summary: none.
- PR preparation: pending.
- Stack maintenance: none required so far; root phase targets `develop`.
- Remaining blockers: none known.
