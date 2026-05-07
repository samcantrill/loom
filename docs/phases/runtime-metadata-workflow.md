# Phase 7 Execution Plan: Run Workflow And Runtime Metadata

## Metadata

- Status: refined; ready for implementation
- Feature focus: Runtime Options
- PR title: `Runtime Options - Phase 7: Run Workflow and Runtime Metadata`
- Branch: `codex/runtime-metadata-workflow`
- Worktree: `/home/samcantrill/work/loom-worktrees/runtime-metadata-workflow`
- Phase execution plan path: `docs/phases/runtime-metadata-workflow.md`
- PR body draft path: `docs/phases/runtime-metadata-workflow-pr-body.md`
- Full plan: `docs/implementation-plans/implementation-plan-v4.md`
- Source phase: Phase 7 - Run Workflow And Runtime Metadata
- Stack predecessor: none; Phases 1-6 are merged into `develop`
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop`,
  automated review passes, and validation/CI pass
- Workflow path: expanded path
- PR preparation path: expanded path
- Successor dependency notes: later v5 worker/subprocess phases should consume
  the typed resolved stage runtime handoff without re-reading raw config,
  runtime profiles, CLI flags, or persisted `runtime.json`.
- Plan quality gate: passed on 2026-05-07
- Plan quality gate loop budget: initial review used, gate refinement used,
  confirmation review used
- Draft pass: completed by managing agent on 2026-05-07
- Refine pass: completed by managing agent on 2026-05-07; used to pin
  CLI composition/run-URI ordering, request compatibility enforcement, dry-run
  handling boundaries, and the separation between planning resume policy and
  run-store open-existing lifecycle behavior
- Setup limitations: branch/worktree created from local `develop`; no
  validation has run for this planning-only pass
- Blockers: none known

## Objective

Thread normalized `RunOptions` through public workflow entrypoints, make
`RunRequest.options` the runner's canonical invocation-policy field, provide a
typed resolved per-stage runtime handoff for executors/workers, and persist a
safe schema-versioned `runtime.json` summary for completed or attempted runs.

## Full-Plan Context

Phases 1-2 established resource/environment models. Phase 3 added canonical
`RunOptions`. Phase 4 added runtime profiles and merge semantics. Phase 5 added
executor descriptors and capability diagnostics. Phase 6 exposed config/CLI
runtime inputs and preflight checks. Phase 7 completes v4 by carrying those
normalized runtime options through planning/execution surfaces and recording
safe runtime metadata.

Later roadmap versions still own subprocess/stage-worker execution, plugin
descriptor discovery, executor-specific adapter schemas, retry/timeout
behavior, and concrete non-local executor behavior. This phase must therefore
add stable contracts and metadata, not backend-specific behavior.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-6 are merged.
- Why this base branch is correct: `develop` contains runtime config/CLI
  mapping, descriptor capability validation, and preflight diagnostics needed
  by this phase.
- Retarget/rebase plan after predecessor merge: no predecessor retarget is
  required.
- Branch cleanup constraints: phase branch may be deleted after merge only if
  no successor phase has stacked on it.

## Source Phase Summary

- Goal: thread normalized runtime options through validate/plan/run workflows
  and persist safe runtime metadata.
- Required scope: add `RunRequest.options`, migrate runner/planning surfaces to
  consume normalized options, add typed resolved stage runtime handoff, add
  run-store `runtime.json` read/write APIs, write safe runtime metadata during
  runs, and ensure semantic fingerprints are unchanged.
- Required exclusions: no raw adapter payload persistence, no environment
  key/value persistence, no plugin discovery, no executor-specific command
  behavior, and no runtime fields in semantic fingerprints.
- Acceptance criteria: `runtime.json` is schema-versioned and safe; store APIs
  read/write it; a future worker/executor receives typed per-stage runtime
  without profile merge; compatibility fields conflict clearly; CLI/config/API
  use the same normalized `RunOptions`; commands stay thin wrappers.

## Current Source And Harness Findings

- `src/loom/pipeline/runtime/options.py` already has `RunOptions`,
  `StageRuntimeOptions`, `to_safe_metadata()`, selector/resume conversion, and
  stage-id validation. This phase should build on those models instead of
  adding a second runtime schema.
- `src/loom/pipeline/runtime/config.py` owns config/profile/explicit merge for
  composed configs. CLI and diagnostics should continue delegating to it.
- `src/loom/pipeline/runtime/environment.py` records normalized run-level and
  stage-level environment requests, but the normalized concrete models do not
  retain whether default `inherit=True` was explicitly authored. Phase 7 should
  avoid false environment override semantics by carrying normalized run and
  stage environment requests separately in the resolved handoff.
- `src/loom/pipeline/execution/models.py` owns `RunRequest` and
  `StageExecutionRequest`. Both can import runtime models without pulling in
  optional config dependencies.
- `src/loom/pipeline/execution/runner.py` currently uses legacy
  `RunRequest.run_uri`, `selectors`, and `resume` directly, builds
  `StageExecutionRequest` without runtime data, and writes config/provenance
  but no `runtime.json`.
- `src/loom/pipeline/stores/run_store.py` and `local_runs.py` expose document
  APIs as plain-data mappings. A runtime metadata store API should follow that
  pattern so stores do not depend on runtime model imports.
- Stage semantic fingerprints are built from stage specs, bound inputs, and
  explicit fingerprint context. Runtime metadata must not be added to those
  fingerprint inputs.
- Existing tests cover run request validation, runner wiring, local store
  document wrappers, import boundaries, CLI run/plan orchestration, and
  planning fingerprint non-impact for runtime unless explicitly declared.
- `loom plan` and `loom run` currently resolve run URIs before composing
  config. Phase 7 changes that ordering where needed so config-authored
  `runtime.run_uri`, `runtime.profile`, selectors, and resume settings can
  participate in the same normalized options object as explicit CLI flags.
  CLI usage checks that previously happened before composition may need
  targeted updates when config-authored runtime values can satisfy them.
- `loom validate` has no runtime-specific CLI flags. Its Phase 7 responsibility
  is config-authored runtime normalization and exact-stage validation after the
  pipeline is validated, not adding another CLI runtime surface.

## In-Scope Work

- Add a runtime metadata/resolution module under
  `src/loom/pipeline/runtime/` with:
  - `RUNTIME_METADATA_SCHEMA_VERSION`;
  - a typed `ResolvedStageRuntimeOptions` handoff;
  - a typed run-level metadata model or builder for safe persisted summaries;
  - helpers to resolve per-stage runtime from a normalized `RunOptions` and
    canonical stage IDs.
- Make `RunRequest.options` accept `RunOptions` or a mapping and normalize it
  during `RunRequest.__post_init__`.
- Retain legacy `RunRequest.run_uri`, `selectors`, and `resume` only as
  compatibility inputs that normalize into `RunRequest.options`; conflicting
  non-default values must fail with clear `RunRequestError` messages.
- Mirror normalized values back onto legacy attributes during construction so
  existing read-only callers still observe the effective run URI, selectors,
  and resume options.
- Keep `RunRequest.open_existing` as run-store lifecycle policy and
  `RunOptions.resume.enabled` as planning reuse policy. The CLI `--resume`
  workflow may set both, but config-authored `runtime.resume` must not
  implicitly open an existing run.
- Use `request.options.run_uri`, `request.options.to_plan_selectors()`, and
  `request.options.to_resume_options()` in `PipelineRunner` and `run_pipeline`
  instead of legacy request fields.
- Add a typed `resolved_runtime` field to `StageExecutionRequest`; runner
  constructs it once from normalized options and passes the per-stage object to
  the executor-facing request.
- Write safe runtime metadata through a new run-store API during run setup,
  after config/spec resolution and before stage execution begins.
- Add run-store protocol methods and `LocalRunStore` implementations for
  reading/writing `runtime.json` as a schema-versioned plain-data document.
- Update `loom plan`, `loom run`, and `loom validate` where relevant to merge
  config/profile/CLI runtime options into `RunOptions` and pass normalized
  selectors/resume/run URI rather than reinterpreting CLI flags.
- Keep `loom run --dry-run` as the existing plan-only CLI path. If the Python
  runner receives `RunOptions.dry_run=True` for concrete execution, runner
  workflow code should fail clearly instead of silently executing a dry-run
  request.
- Add user-facing docs for `runtime.json` safety boundaries and the resolved
  stage runtime handoff.

## Out-of-Scope Work

- Persisting raw adapter payloads by default.
- Persisting environment variable names or values in `runtime.json`.
- Applying environment variables to the current Python process.
- Plugin discovery or third-party descriptor loading.
- Concrete non-local executor behavior.
- Retry, timeout, scheduler, container, subprocess, or remote store behavior.
- Adding runtime data to semantic fingerprints.
- Changing stage config semantics or planner graph behavior unrelated to
  normalized selectors/resume.

## Assumptions

- `runtime.json` is a run-level metadata document with a stable wrapper and a
  safe runtime payload; it is not the source of truth for executor handoff.
- Resource metadata may expose safe entry summaries such as kind, amount, unit,
  and attribute counts, but should not persist resource-entry attributes until a
  later descriptor/schema phase decides they are safe.
- Adapter metadata should persist namespace names/counts only unless later
  descriptor validation adds an approved summary.
- Run-level and stage-level environment requests must remain separate in the
  resolved stage handoff until the runtime model can preserve sparse authored
  environment intent or a future executor defines exact merge semantics.
- `open_existing=True` continues to be supported as a store lifecycle
  compatibility entrypoint. It should not be inferred from
  `RunOptions.resume.enabled`, because runtime resume is planning reuse policy.
- Existing `RunRequest` callers with only legacy selectors/resume/run URI
  should continue to work when values do not conflict with `options`.
- Config-authored `runtime.run_uri` may satisfy plan/run resume run-URI
  requirements once config has been composed. Explicit CLI `--run-uri` remains
  the highest-precedence source and should still be resolved through the run
  store before persistence or planning.

## Scope Contract

The canonical public invocation policy after this phase is
`RunRequest.options: RunOptions`. Legacy `RunRequest.run_uri`, `selectors`, and
`resume` exist only as conflict-checked adapters into that field. Runner,
planner, CLI, and store metadata must consume the normalized `RunOptions`
object instead of raw config/profile/CLI dictionaries.

`ResolvedStageRuntimeOptions` is the typed executor-facing runtime handoff. It
may include safe summaries for persistence, but executor code must receive the
typed object directly through `StageExecutionRequest`, not by reading
`runtime.json`.

`runtime.json` is an observability artifact. It must be safe to read for run
catalogs, bundles, diagnostics, and humans, but it must not contain environment
keys/values or raw adapter payloads and must not participate in semantic stage
fingerprints.

## Design Impact

- Maintainability: runtime normalization remains centralized in
  `RunOptions`/profile/config helpers; execution consumes typed runtime data
  instead of duplicating CLI/config merge logic.
- Extensibility: future worker, subprocess, scheduler, and plugin phases get a
  stable per-stage handoff and safe run metadata document without depending on
  raw authored config shapes.
- Domain neutrality: metadata describes generic execution policy, not
  research-domain concepts.
- Source-tree boundaries: runtime owns runtime metadata models, execution owns
  request/handoff wiring, stores own plain-data document persistence, and CLI
  remains a thin adapter.

## Future Compatibility

- v5 subprocess/stage-worker phases can pass `ResolvedStageRuntimeOptions`
  across a worker boundary before introducing backend-specific execution.
- Later plugin/adapter phases can extend safe adapter summaries without
  changing the store wrapper or requiring executor code to parse metadata.
- Later environment phases can add explicit environment merge semantics without
  changing the fact that stage execution receives a typed runtime field.
- Run catalogs and bundles can read `runtime.json` through store APIs without
  knowing local filesystem paths.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Persist `RunOptions.to_dict()` directly as `runtime.json` | It would expose environment keys/values and raw adapter payloads. |
| Make `runtime.json` the executor handoff | It would couple executor behavior to persisted metadata and force stores into the hot path. |
| Merge run/stage environment requests into one effective environment now | The current normalized models cannot distinguish omitted stage defaults from explicit stage intent. |
| Keep legacy `RunRequest` fields as independent semantics | It would preserve duplicate invocation-policy sources and cause future drift. |
| Put runtime metadata in semantic fingerprints | The v4 design explicitly keeps runtime policy observable without changing stage reuse semantics. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Resolved stage handoff carries run and stage environment requests separately | Avoids false override semantics while preserving typed data for future executors. | A later phase adds explicit sparse environment merge intent or concrete executor environment application. |
| Adapter metadata remains namespace/count only | Prevents raw payload persistence before adapter schemas exist. | A descriptor/plugin roadmap adds safe adapter summary providers. |
| Python runner rejects dry-run execution requests instead of producing a dry-run `RunResult` | CLI already uses plan-only dry-run behavior; adding a synthetic run result would expand execution semantics. | A later roadmap requires Python API dry-run result objects from `PipelineRunner.run`. |

## Reviewability

- Expected PR size and shape: moderate-to-large, with one runtime
  metadata/resolution module, execution request changes, runner/store wiring,
  CLI validation/plan/run updates, docs, and focused tests.
- Files and areas to inspect: `src/loom/pipeline/runtime/`,
  `src/loom/pipeline/execution/`, `src/loom/pipeline/stores/`,
  `src/loom/cli/`, docs, package/contract/unit/integration/e2e tests.
- Scope-control checks: no executor-specific behavior, no raw adapter payload
  persistence, no environment names/values in `runtime.json`, no fingerprint
  inputs changed, no plugin discovery.

## Implementation Steps

1. Add runtime metadata/resolution models and tests for safe summaries,
   per-stage resolution, environment separation, and schema round trips.
2. Extend `RunRequest` with normalized `options`, compatibility conflict
   checks, legacy selector/resume normalization into options, and tests.
3. Add `StageExecutionRequest.resolved_runtime` and runner handoff wiring.
4. Add run-store protocol/local-store `runtime.json` read/write APIs and
   contract/unit tests.
5. Wire `PipelineRunner` to resolve runtime once, reject concrete dry-run
   execution clearly, use normalized selectors and resume, write runtime
   metadata, and pass per-stage runtime requests.
6. Update CLI validate/plan/run to merge config/profile/CLI runtime options and
   pass normalized options to public APIs without duplicating runtime semantics.
7. Add integration/e2e coverage for a local run with profile/resources/tags and
   safe `runtime.json`, plus fingerprint non-impact coverage.
8. Update docs, run targeted suites, then `make validate-pr` and
   `make test-summary`.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import_boundaries.py`,
  `tests/package/test_pipeline_api.py`, and store API import tests as needed.
- Required assertions: runtime metadata models and store APIs are exported
  intentionally without introducing optional config/CLI imports into package
  facades.

### Unit Suite

- Status: required.
- Expected paths: new or updated tests under
  `tests/unit/loom/pipeline/test_runtime_metadata.py`,
  `tests/unit/loom/pipeline/execution/test_execution_models.py`,
  `tests/unit/loom/pipeline/execution/test_runner.py`,
  `tests/unit/loom/pipeline/stores/test_local_runs.py`,
  `tests/unit/loom/cli/test_plan.py`, `test_run.py`, and `test_validate.py`.
- Required assertions: safe metadata excludes environment keys/values and raw
  adapter payloads; resolved stage runtime is typed and per-stage; `RunRequest`
  normalizes compatibility fields and rejects conflicts; runner dry-run
  execution fails clearly; local store writes/reads runtime metadata; CLI
  adapters pass normalized options.

### Contract Suite

- Status: required.
- Expected paths: new or updated contract tests for runtime metadata,
  resolved stage runtime handoff, run-store `runtime.json`, `RunRequest.options`
  invocation policy, and fingerprint non-impact.
- Required assertions: stable schema fields, store wrapper fields, handoff
  shape, compatibility conflict behavior, and unchanged semantic fingerprints
  when runtime options change outside explicit fingerprint fields.

### Integration Suite

- Status: required.
- Expected paths: config/CLI run and diagnostics integration tests plus local
  pipeline execution integration tests.
- Required assertions: composed config with `runtime`/`runtime_profiles` drives
  normalized plan/run selectors and resume where relevant; local run writes
  safe `runtime.json`; executor receives `StageExecutionRequest.resolved_runtime`.

### E2E Suite

- Status: required.
- Expected paths: focused CLI e2e test using config extras if needed.
- Required assertions: local synthetic run with runtime profile/resources/tags
  writes safe `runtime.json`, resource warning behavior remains preflight-owned,
  and stage semantic fingerprints remain unchanged by runtime-only changes.

### Opt-In Suites

- Status: deferred.
- Markers affected: none beyond existing optional config dependencies.
- Required assertions or deferral reason: no backend-specific optional executor
  support is implemented in this phase.

## Risks

- `RunRequest` compatibility normalization can silently choose the wrong source
  if conflict checks are too loose; tests must cover mismatched run URI,
  selectors, and resume values.
- The CLI term `--resume` currently combines opening an existing run with
  planning resume. Runtime `resume` is only planning policy, so runner and CLI
  tests must prevent config-authored `runtime.resume` from implying
  `open_existing=True`.
- Environment merge semantics are easy to overstate. The resolved handoff must
  carry normalized run/stage requests separately until a later phase defines
  sparse intent or executor application.
- `runtime.json` safety must be tested with environment keys/values and adapter
  payloads that would be obvious leaks if persisted.
- Runtime metadata write timing must not make failed early runs look
  successful; write after config/spec/runtime resolution and before stage
  execution, with clear schema wrapper fields.
- CLI run URI allocation and config-authored run URI precedence must stay
  compatible with Phase 6 preflight behavior.
- Moving CLI plan/run composition before final run URI resolution may change
  the timing of some usage errors; tests should pin the intended cases where
  config-authored runtime values are now allowed to satisfy the request.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/test_runtime_metadata.py
uv run pytest tests/unit/loom/pipeline/execution/test_execution_models.py tests/unit/loom/pipeline/execution/test_runner.py
uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py
uv run pytest tests/unit/loom/cli/test_plan.py tests/unit/loom/cli/test_run.py tests/unit/loom/cli/test_validate.py
uv run --extra config pytest tests/integration/config/test_cli_plan.py tests/integration/config/test_cli_run.py
uv run --extra config pytest tests/e2e/test_cli_core.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: runtime metadata/resolution models first,
  `RunRequest`/`StageExecutionRequest` wiring second, store API third,
  runner/CLI integration fourth, docs/tests last.
- Tests to run with each slice: run nearest unit tests first, then store
  contracts and config-extra CLI integration before broader validation.
- Decisions the executor must not revisit: no raw adapter payload persistence,
  no environment key/value persistence, no plugin discovery, no concrete
  non-local executor behavior, no semantic fingerprint changes.
- Conditions that require stopping for the manager: runtime metadata safety
  requires persisting environment names/values or raw adapter payloads; a
  change requires altering resource schemas; a conflict cannot be handled
  without removing legacy `RunRequest` compatibility fields; or dry-run support
  would require synthetic execution results beyond this phase.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on 2026-05-07.
- Final phase execution plan: refined on 2026-05-07.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- Blocker-resolution summary: pending.
- PR preparation: pending.
- Stack maintenance: not needed yet.
- Remaining blockers: none known.
