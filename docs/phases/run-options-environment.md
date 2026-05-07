# Phase 3 Execution Plan: Run Options And Environment Models

## Metadata

- Status: refined phase execution plan
- Feature focus: Runtime Options
- PR title: `Runtime Options - Phase 3: Run Options and Environment Models`
- PR URL: https://github.com/samcantrill/loom/pull/72
- PR state: `OPEN`
- PR base/head: `develop` <- `codex/run-options-environment`
- Branch: `codex/run-options-environment`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-options-environment`
- Phase execution plan path: `docs/phases/run-options-environment.md`
- Full plan: `docs/implementation-plans/implementation-plan-v4.md`
- PR body draft path: `docs/phases/run-options-environment-pr-body.md`
- Source phase: Phase 3 - Run Options And Environment Models
- Stack predecessor: none; Phase 1 and Phase 2 are merged
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop`, automated review passes, and validation/CI pass
- Workflow path: expanded path
- PR preparation status: draft PR body pass completed on 2026-05-07; PR body
  refine/open pass completed on 2026-05-07 with PR #72 opened against
  `develop`
- Successor dependency notes: Phase 4 should branch from `develop` if this phase merges first; otherwise it may stack on `codex/run-options-environment` after this phase reaches `pr_open`.
- Plan quality gate: passed on 2026-05-07 after initial review, refinement, and confirmation review
- Plan quality gate loop budget: initial review used, gate refinement used, confirmation review used
- Draft pass: completed by `loom_phase_planner`
- Refine pass: completed on 2026-05-07 because this phase introduces durable public runtime option models and planning/execution boundary contracts
- Setup limitations: `gh auth status` required approved network access because the sandbox reported the token as invalid; network-verified auth succeeded, `gh auth setup-git` and `git fetch origin` completed, and the worktree was created from local `develop` at `12a0d6b`.
- Blockers: none known

## Objective

Add the public, import-light runtime option model layer that Python callers can construct, validate, adapt to planning inputs, summarize safely, and serialize before runtime profile merge, CLI/config mapping, preflight, run workflow wiring, or persisted runtime metadata are introduced.

## Full-Plan Context

Phase 1 created the split `loom.pipeline.runtime` facade, and Phase 2 hard-swapped resources to entry-based `ResourceRequest`. This phase uses those foundations to define `RunOptions`, `ExecutionOptions`, `StageRuntimeOptions`, and run/stage environment request models as the canonical invocation-policy API. Later phases own profile selection and merge, executor descriptors and capability diagnostics, CLI/config mapping, `RunRequest.options` workflow wiring, resolved per-stage runtime handoff data, and persisted `runtime.json`; none of that should be implemented here.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 1 PR #70 and Phase 2 PR #71 are merged
- Why this base branch is correct: `develop` records Phase 2 merge metadata and includes the entry-based resource model this phase depends on
- Retarget/rebase plan after predecessor merge: no predecessor retarget is required
- Branch cleanup constraints: phase branch may be deleted after merge only if no successor phase has stacked on it

## Source Phase Summary

- Goal: add core runtime invocation models before profile merge and workflow wiring.
- Required scope: implement `RunOptions`, `ExecutionOptions`, `StageRuntimeOptions`, run-level and stage-level environment request models, serialization, validation basics, safe metadata summaries, privacy defaults, typed-resource integration through entry-based `ResourceRequest`, and adapters from runtime options to planning-owned `PlanSelectors` and `ResumeOptions`.
- Required checkpoints: preserve runtime package import boundaries, keep planning selector/resume semantics in planning, define but do not wire the execution-envelope boundary, and keep local execution from applying or inspecting environment requests.
- Acceptance criteria: Python callers can construct and serialize the models; `RunOptions` is tested/documented as canonical for run URI, executor, dry-run, profile, tags, notes, selector/resume adapters, execution settings, stage runtime options, environment requests, and adapter options; stage runtime options can carry entry-based resources, execution, environment, and adapter options; environment keys/values are absent from safe metadata; planning ownership is unchanged.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `src/loom/pipeline/runtime/__init__.py` currently re-exports only `RuntimeRequest`, `RuntimeKind`, `parse_runtime_request`, and `RUNTIME_SCHEMA_VERSION`.
  - `src/loom/pipeline/runtime/_models.py` owns the local-only `RuntimeRequest` foundation and already rejects deferred runtime fields such as executor, profile, and environment.
  - `src/loom/pipeline/resources.py` now exposes immutable entry-based `ResourceRequest` and `ResourceEntry`; `StageRuntimeOptions.resources` should reuse this model.
  - `src/loom/pipeline/planning/models.py` owns `PlanSelectors` and `ResumeOptions`; `src/loom/pipeline/planning/selectors.py` and `resume.py` own their semantics.
  - `src/loom/pipeline/execution/models.py` owns `RunRequest`, `FailurePolicy`, and `StageExecutionRequest`; in this phase it should only gain boundary tests or minimal compatibility declarations if needed, not workflow behavior.
- Existing tests or harness behavior:
  - Runtime/resource model tests live in `tests/unit/loom/pipeline/test_runtime_resources.py`.
  - Import-boundary tests in `tests/package/test_import_boundaries.py` expect the runtime facade to stay lightweight and not import CLI, config, diagnostics, execution, executors, plugins, optional backend packages, or project modules.
  - Execution model tests in `tests/unit/loom/pipeline/execution/test_execution_models.py` cover current `RunRequest` behavior and should remain green.
- Import-boundary or dependency constraints:
  - Runtime models may depend on serialization helpers, pipeline errors, resources, and narrow planning model adapters, but must not import planner execution policy, execution runners, concrete executors, stores, diagnostics, config composition, CLI, plugins, or optional backends.

## In-Scope Work

- Add focused runtime submodules for options and environment models under `loom.pipeline.runtime`, with public facade exports.
- Implement strict, immutable, plain-data-compatible `RunOptions`, `ExecutionOptions`, `StageRuntimeOptions`, and environment request models.
- Define `RunOptions` fields for run URI, executor, dry-run, profile name, tags, notes, selector/resume adapter inputs, run-level execution settings, exact stage runtime options, run-level environment request, and adapter options.
- Integrate `StageRuntimeOptions.resources` with the Phase 2 entry-based `ResourceRequest` model only; old `cpus`, `memory_mb`, `gpus`, and `custom` resource aliases remain rejected by the resource layer and must not be reintroduced through runtime options.
- Add runtime-to-planning adapter methods or functions that return existing `PlanSelectors` and `ResumeOptions` without importing or duplicating selector/resume eligibility semantics.
- Add safe metadata summary helpers that exclude environment keys and values and avoid raw adapter payload persistence by default; these helpers are plain in-memory summaries only and must not create a persisted `runtime.json` contract.
- Add docs and tests that establish `RunOptions` as canonical invocation policy while `RunRequest` remains the execution envelope until Phase 7 wires `RunRequest.options`.

## Out-of-Scope Work

- Runtime profile selection, profile collection models, merge precedence, or profile-derived stage option resolution.
- Executor descriptors, capability checks, local ignored-resource warnings, or unclaimed adapter namespace warnings.
- Preflight check IDs, groups, JSON output, or strict-mode behavior.
- Persisted `runtime.json`, run-store APIs, or run metadata writes.
- CLI flags, config `runtime` / `runtime_profiles` mapping, command formatting, or CLI dry-run behavior changes.
- Plugin discovery, adapter schema validation, SLURM/Docker/Apptainer interpretation, retry, timeout, wall-time, subprocess, or worker process behavior.
- Environment key/value persistence or local in-process environment application.
- Adding `RunRequest.options`, threading `RunOptions` through `PipelineRunner`, `run_pipeline`, `StageExecutionRequest`, stores, config composition, diagnostics, or CLI entrypoints.
- Executor descriptor/capability models, executor capability metadata, executor registry behavior, or runtime preflight checks.

## Assumptions

- `executor` validation in this phase is basic string validation only; unknown-executor resolution belongs to Phase 5.
- `profile` is a plain selected-profile name on `RunOptions` only; no runtime profile lookup, merge, or profile existence validation occurs in this phase.
- `dry_run` is a normalized invocation flag only; no runner or CLI behavior changes occur in this phase.
- Tags, notes, and adapter options are plain invocation metadata/options, must be frozen and plain-data-compatible, and must not affect semantic fingerprints or execution behavior in this phase.
- Stage option keys are exact stage IDs syntactically, but validation against a supplied synthetic or known stage-id set should be exposed as a pure helper and not tied to profile merge or execution wiring.
- Environment request models may serialize full in-memory requests for Python API handoff, but any safe metadata summary produced by this phase must not include environment variable names or values.
- Existing `RuntimeRequest` remains available for compatibility; `RunOptions` is a new invocation aggregate rather than a replacement for `RuntimeRequest`.

## Scope Contract

`RunOptions` is the canonical public invocation-policy aggregate for v4. It must be strict about unknown fields and plain-data compatibility, freeze mutable inputs, provide deterministic `to_dict` / `from_dict` round trips, and keep defaults domain-neutral. The model should accept typed objects and mapping forms for nested runtime models where the existing codebase uses that pattern.

The durable `RunOptions` field set for this phase must cover run URI, executor name, dry-run flag, selected profile name, tags, notes, selector adapter inputs, resume adapter input, run-level `ExecutionOptions`, exact-stage `StageRuntimeOptions`, run-level environment request, and adapter options. Validation should be basic model validation only: non-empty strings where strings are required, booleans for boolean flags, plain-data mappings/sequences for serialized fields, duplicate/invalid mapping keys rejected with path-aware errors, and deterministic normalization of sequence or mapping order where the public contract depends on it.

`ExecutionOptions` is a small runtime model for invocation/execution options that can be shared at run and stage scope. It may carry only phase-owned plain-data options needed as a future handoff surface and must not define executor descriptor capabilities, retry/timeout/wall-time semantics, preflight policy, subprocess behavior, or backend-specific schemas.

`StageRuntimeOptions` must carry `resources`, `execution`, `environment`, and `adapter_options`. `resources` must be a Phase 2 `ResourceRequest` or mapping parsed through the entry-based resource schema. Stage options are keyed by exact stage ID strings. This phase should include basic syntactic stage-id validation and, where useful for tests or public helpers, a pure known-stage validation function that accepts a supplied stage-id set. It must not perform profile merge behavior, glob/tag/group matching, graph reachability checks, or executor capability checks.

Selector and resume fields in `RunOptions` are adapter inputs only. The phase may provide `to_plan_selectors()` and `to_resume_options()` or equivalent pure helpers, but it must not validate graph reachability, stage eligibility, resume artifact state, or any planning policy. Those semantics remain in `loom.pipeline.planning`.

The execution boundary is declarative in this phase: `RunOptions` owns invocation policy, while `RunRequest` continues to own config, pipeline, provenance, stores, lifecycle inputs, fingerprint context, and current compatibility fields. Document that Phase 7 will add or wire `RunRequest.options` as the execution-envelope boundary, but do not add runner request rewiring or make runner code consume `RunOptions` in this phase. Do not thread `RunOptions` through `PipelineRunner`, `run_pipeline`, `StageExecutionRequest`, run stores, CLI, diagnostics, or config mapping yet.

Run-level and stage-level environment request models must default to privacy-preserving safe summaries. They may carry requested environment additions/removals for future isolated executors, but no helper that represents persisted or safe runtime metadata may include environment keys or values. Local in-process execution must not apply, inspect, or mutate process environment from these requests in this phase.

`StageRuntimeOptions` must represent per-stage resources, execution settings, environment request, and adapter options using exact stage IDs supplied by the caller. It must not add glob, tag, group, or pattern matching.

## Design Impact

- Maintainability: keeps runtime option models in the runtime package and preserves planning/execution/store/CLI ownership boundaries.
- Extensibility: gives later profile, descriptor, CLI/config, run workflow, and executor phases one canonical invocation-policy object to consume.
- Domain neutrality: models describe generic invocation policy and scheduler-neutral resources, not domain-specific project or backend behavior.
- Source-tree boundaries: runtime imports remain below CLI/config/diagnostics/execution runners and above only shared serialization, errors, resources, and narrow planning model adapter types.

## Future Compatibility

- Phase 4 can merge base/profile/explicit sources into the same `RunOptions` and `StageRuntimeOptions` objects without redefining their schema.
- Phase 5 can validate `executor`, resources, and adapter namespaces against descriptors without changing the model storage shape.
- Phase 6 can map CLI/config inputs into `RunOptions` instead of keeping CLI-specific option semantics.
- Phase 7 can attach normalized `RunOptions` to `RunRequest.options` and derive resolved per-stage runtime handoff and safe `runtime.json` summaries from the same model.
- Subprocess, scheduler, container, sweep, and plugin phases can consume environment/resource/adapter request data from typed models instead of raw config dictionaries.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Put selector and resume semantics directly in runtime models | Planning already owns graph-aware selector normalization and same-run resume policy; duplicating it would create conflicting public contracts. |
| Wire `RunOptions` through `PipelineRunner` in this phase | Workflow wiring belongs to Phase 7 after profile merge, descriptor validation, CLI/config mapping, and safe metadata contracts exist. |
| Persist or summarize environment keys and values now | The v4 privacy choice is to avoid accidental secret disclosure until explicit audit/redaction policy exists. |
| Treat stage options as glob or tag patterns | Exact IDs are the v4 deterministic contract; broader matching is deferred until a concrete later roadmap need. |
| Validate adapter namespaces with backend schemas now | Adapter schemas and plugin discovery are explicitly out of scope; this phase preserves plain data only. |
| Add executor descriptor fields or preflight hooks while defining `executor` | Executor descriptors, capabilities, and preflight diagnostics are Phase 5/6 scope; this phase only preserves the selected executor name as invocation policy. |
| Add `RunRequest.options` now as a convenience field | Phase 7 owns runner request rewiring and conflict handling after profiles, descriptors, and CLI/config mapping exist. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No local environment application | Avoid process-global side effects and secret handling before isolated executors exist. | Revisit in subprocess/container execution phases. |
| No environment key/value recording | Preserve safe metadata defaults and avoid secret leakage. | Revisit only with explicit audit/provenance and redaction policy. |
| No adapter schema validation | Keeps Phase 3 focused on canonical model shape before descriptors and plugins. | Revisit in descriptor, adapter, and plugin phases. |
| `RunRequest` still has overlapping compatibility fields | Phase 7 owns workflow migration and conflict handling once upstream mappings exist. | Revisit when Phase 7 adds `RunRequest.options`. |
| Stage options are exact IDs only | Avoids introducing matching policy before profile merge and graph-aware runtime handoff exist. | Revisit only when a later roadmap phase defines pattern/tag/group selection semantics. |

## Reviewability

- Expected PR size and shape: small-to-medium model/test PR, mostly new runtime submodules plus public exports, focused docs, and targeted package/unit/contract tests.
- Files and areas to inspect:
  - `src/loom/pipeline/runtime/`
  - `src/loom/pipeline/__init__.py`
  - `src/loom/pipeline/execution/models.py` only for boundary declarations/tests if required
  - `tests/package/test_import_boundaries.py`
  - `tests/package/test_pipeline_api.py`
  - `tests/unit/loom/pipeline/test_runtime_resources.py` or a new runtime-options unit test module
  - `tests/contracts/` runtime/planning/execution boundary tests
  - `docs/features/runtime-resources.md`, `docs/features/execution.md`, or `docs/structure.md` if public docs need the new model boundary
- Scope-control checks: no CLI/config/preflight/store/runtime.json changes; no executor descriptor registry or capability metadata; no local environment application; no resource schema changes; no `RunRequest.options` runner rewiring.

## Implementation Steps

1. Add runtime option and environment model modules with strict dataclass-style validation, deterministic serialization, frozen plain-data mappings, and facade/package exports.
2. Add `RunOptions` field coverage for run URI, executor, dry-run, profile, tags, notes, selector/resume adapter inputs, run execution options, stage options, run environment request, and adapter options.
3. Add `RunOptions` adapter helpers for `PlanSelectors` and `ResumeOptions`, keeping graph/stage/resume semantics delegated to planning-owned models and helpers.
4. Add `StageRuntimeOptions` support for entry-based `ResourceRequest`, `ExecutionOptions`, stage environment requests, and adapter options keyed by exact stage IDs, plus basic syntactic and supplied-known-stage validation helpers.
5. Add safe metadata summary behavior that excludes environment keys/values and raw adapter payloads while allowing non-sensitive invocation fields such as executor, dry-run, profile presence/name, tags, notes, and resource summaries where appropriate.
6. Add docs and boundary notes showing `RunOptions` as canonical invocation policy and `RunRequest` as the execution envelope that Phase 7 will later carry as `options`.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_api.py`, and package-level runtime facade coverage as needed.
- Required assertions or deferral reason: public imports expose the new runtime models from `loom.pipeline.runtime` and `loom.pipeline`; runtime facade remains import-light and does not import CLI, config, diagnostics, execution runners, concrete executors, plugins, optional backend packages, or project modules.

### Unit Suite

- Status: required
- Expected paths: new or existing `tests/unit/loom/pipeline/test_runtime_resources.py` / `tests/unit/loom/pipeline/test_runtime_options.py`.
- Required assertions or deferral reason: construct defaults and populated `RunOptions`, `ExecutionOptions`, `StageRuntimeOptions`, and run/stage environment requests; reject unknown fields and invalid scalar types; freeze mutable tags, notes, adapter options, resources, and environment inputs; validate run URI, executor, dry-run, profile, adapter options, stage option key shape, and optional known-stage failures; verify deterministic serialization; verify safe metadata summaries omit environment keys and values.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_runtime_options_contract.py` or similarly focused contract coverage.
- Required assertions or deferral reason: plain-data serialization contract for runtime options, including entry-based `ResourceRequest` integration; adapter contract from `RunOptions` to `PlanSelectors` and `ResumeOptions`; execution-envelope boundary contract that `RunOptions` owns invocation policy while current `RunRequest` remains the execution envelope and local `StageExecutionRequest` does not consume environment requests yet.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/` or a new narrow integration test for Python API construction.
- Required assertions or deferral reason: Python callers can construct runtime options with synthetic exact stage IDs and entry-based resources; known-stage validation succeeds/fails deterministically where the helper is used; no local run workflow, profile merge, or config/CLI mapping is required to consume the options in this phase.

### E2E Suite

- Status: deferred
- Expected paths: none.
- Required assertions or deferral reason: Phase 3 adds public Python model behavior only and does not expose user-facing CLI/config/run workflow behavior; existing e2e should remain unaffected through `make validate-pr`.

### Opt-In Suites

- Status: deferred
- Markers affected: none.
- Required assertions or deferral reason: no SLURM, Docker, Apptainer, network, plugin discovery, or other opt-in backend behavior is introduced.

## Risks

- Public model field choices are durable; the refine pass should check that the model is useful for Phase 4 merge and Phase 7 workflow wiring without importing those future behaviors.
- Import-light runtime facade could regress if adapter helpers import broad planning or execution modules; tests must pin forbidden imports.
- Environment request serialization and safe metadata behavior could be confused; tests must distinguish full in-memory model serialization from safe metadata summaries that omit keys/values and from future persisted `runtime.json` work.
- Overlapping `RunRequest` fields may tempt early workflow migration; executor should keep that work out of scope.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py
uv run pytest tests/unit/loom/pipeline/test_runtime_resources.py tests/unit/loom/pipeline/test_runtime_options.py
uv run pytest tests/contracts/test_runtime_options_contract.py
uv run pytest tests/integration/pipeline -k runtime_options
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: runtime/environment models first, planning adapters second, safe metadata summaries third, docs and tests last.
- Tests to run with each slice: package import tests after facade changes; unit serialization/privacy tests after model changes; contract tests after adapter and boundary helpers; narrow integration tests after known-stage validation support.
- Decisions the executor must not revisit: `RunOptions` is canonical invocation policy; `RunRequest.options` is only a documented Phase 7 execution-envelope boundary for now; resources use entry-based `ResourceRequest`; no profile selection/merge, no CLI/config mapping, no preflight, no executor descriptors/capabilities, no `runtime.json`, no local environment application, no environment key/value recording, no glob/tag/group stage matching, and no planning semantic migration into runtime.
- Conditions that require stopping for the manager: if the model field set cannot satisfy Phase 4/Phase 7 without adding profile merge or workflow wiring now; if import-boundary tests require runtime to import execution or concrete executors; if environment privacy cannot be represented without recording keys or values.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-07 for the expanded-path
  implementation/test refinement pass
- PR body draft: used on 2026-05-07 for the expanded-path draft-only PR body
  pass
- PR body refine/open pass: used on 2026-05-07; PR #72 opened and verified
  with `baseRefName=develop`, `headRefName=codex/run-options-environment`,
  `state=OPEN`
- PR review: used on 2026-05-07; automated review found no blocking findings
  and one stale PR-body evidence note, which was corrected before merge
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on 2026-05-07.
- Final phase execution plan: refined on 2026-05-07 for expanded-path implementation.
- PR body draft: committed as `97ffa63 docs: draft phase 3 pr body`.
- PR opened: https://github.com/samcantrill/loom/pull/72 on 2026-05-07 with
  base `develop`, head `codex/run-options-environment`, and state `OPEN`.
- Stack state: root phase PR targeting `develop`; no stack predecessor.
- PR review: completed on 2026-05-07 by `loom_phase_reviewer`. Review found no
  blocking findings, confirmed Phase 3 scope and target branch, and noted one
  low stale PR-body GitHub-checks row after live CI passed. The PR body was
  updated to record the `checks` workflow `SUCCESS` result before merge.
- Implementation summary: completed on 2026-05-07. Added import-light public
  runtime option models with `RunOptions`, `ExecutionOptions`,
  `StageRuntimeOptions`, `RunEnvironmentRequest`, and
  `StageEnvironmentRequest`; exposed facade and `loom.pipeline` exports; added
  plain-data serialization, immutable mappings, safe metadata summaries,
  planning-owned selector/resume adapters, entry-based resource integration,
  exact-stage validation, and supplied-known-stage validation without wiring
  runner/config/CLI/stores/preflight/profile behavior.
- Implementation validation: targeted package tests passed
  (`uv run pytest tests/package/test_import_boundaries.py
  tests/package/test_pipeline_api.py`); targeted runtime unit tests passed
  (`uv run pytest tests/unit/loom/pipeline/test_runtime_resources.py
  tests/unit/loom/pipeline/test_runtime_options.py`); runtime options contract
  tests passed (`uv run pytest tests/contracts/test_runtime_options_contract.py`);
  narrow integration selection passed (`uv run pytest tests/integration/pipeline
  -k runtime_options`); `make validate-pr` passed after renaming the integration
  runtime-options test file to avoid a Pytest module basename collision.
- Implementation refinement pass: completed on 2026-05-07. Reviewed
  `AGENTS.md`, the v4 implementation plan, this phase execution plan,
  `.codex/prompts/implementation-test-refinement.md`, the current
  `develop...HEAD` diff, and commits `ebe450a`, `d147dc9`, and `49599bb`.
  Confirmed Phase 3 remains scoped to runtime option and environment models:
  no runtime profile/profile merge, executor descriptors/capabilities,
  preflight, CLI/config runtime mapping, persisted `runtime.json`, plugin
  discovery, adapter schemas, local environment application, or runner request
  wiring was introduced.
- Refinement validation output reviewed: initial sandboxed `uv run pytest`
  attempts could not lock the default home-directory uv cache because it is
  read-only in this session; reruns with `UV_CACHE_DIR=/tmp/loom-uv-cache`
  passed for package/runtime import coverage, runtime unit coverage, runtime
  option contract coverage, and narrow runtime-options integration coverage.
- Refinement blocking issues caused by this phase: none found. The public
  runtime models provide deterministic plain-data serialization, freeze mutable
  inputs, keep planning adapters on existing `PlanSelectors` and
  `ResumeOptions`, preserve exact-stage validation only, omit environment keys
  and values from safe summaries, avoid raw adapter payloads in safe metadata,
  and keep `RunOptions` unwired from `RunRequest`, `PipelineRunner`, CLI,
  config, stores, preflight, and persisted runtime metadata.
- Refinement fixes made: no code, test, or public-doc fixes were required; this
  artifact update records the consumed implementation refinement budget and
  handoff evidence.
- Refinement tests re-run: `UV_CACHE_DIR=/tmp/loom-uv-cache uv run pytest
  tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py`
  passed with 27 tests; `UV_CACHE_DIR=/tmp/loom-uv-cache uv run pytest
  tests/unit/loom/pipeline/test_runtime_resources.py
  tests/unit/loom/pipeline/test_runtime_options.py` passed with 73 tests;
  `UV_CACHE_DIR=/tmp/loom-uv-cache uv run pytest
  tests/contracts/test_runtime_options_contract.py
  tests/integration/pipeline/test_runtime_options_integration.py` passed with
  4 tests. `UV_CACHE_DIR=/tmp/loom-uv-cache make validate-pr` initially passed
  Ruff and Pyright but failed in the sandbox when the isolated default test
  environment needed to download `typing-extensions==4.15.0`; the same command
  passed with approved network access, including Ruff, Pyright, the default
  test harness with 617 passed / 13 skipped / 12 deselected, the config-extra
  harness with 396 passed / 632 deselected, and `uv build`.
- Refinement summary: scope clarified for durable public runtime models,
  entry-based resource integration, planning adapters, execution-envelope
  deferral, privacy guarantees, stage validation boundaries, explicit
  later-phase exclusions, and the completed implementation refinement pass.
- Blocker-resolution summary: none used.
- PR preparation draft: completed on 2026-05-07. Read `AGENTS.md`, the v4
  implementation plan, this phase execution plan, `.github/PULL_REQUEST_TEMPLATE.md`,
  the current `develop...HEAD` diff, runtime model/test changes, and the
  generated `build/test-summary.md` evidence. Created
  `docs/phases/run-options-environment-pr-body.md` for
  `Runtime Options - Phase 3: Run Options and Environment Models`. This was a
  draft-only pass; no PR was opened, no GitHub checks were run, and no merge or
  implementation refinement was attempted.
- PR preparation validation: `UV_CACHE_DIR=/tmp/loom-uv-cache make
  test-summary` passed on 2026-05-07 and wrote `build/test-summary.md` with
  package 50 passed / 1 skipped, unit 513 passed / 1 skipped, contract 44
  passed / 2 skipped, integration 10 passed / 6 skipped / 12 deselected, e2e
  15 passed, config-extra 396 passed / 632 deselected, and overall 1028 passed
  / 10 skipped / 644 deselected.
- Stack maintenance: none required yet.
- Remaining blockers: none known.
