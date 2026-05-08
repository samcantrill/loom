# Phase 5 Execution Plan: CLI And Preflight Integration

## Metadata

- Status: ready_for_implementation
- Feature focus: SLURM Script Planning
- PR title: `SLURM Script Planning - Phase 5: CLI and Preflight Integration`
- Branch: `codex/slurm-cli-preflight`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-cli-preflight`
- Phase execution plan path: `docs/phases/slurm-cli-preflight.md`
- PR body path: `docs/phases/slurm-cli-preflight-pr-body.md`
- Full plan: `docs/implementation-plans/implementation-plan-v6.md`
- Source phase: Phase 5 - CLI And Preflight Integration
- Stack predecessor: none; Phases 1-4 are merged into `develop`
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase; not merge-eligible until the expanded-path
  refine pass is complete, implementation remains phase-scoped, automated PR
  review passes, and validation/CI passes with the PR targeting `develop`
- Workflow path: expanded path because this phase exposes public CLI behavior
  and diagnostics/preflight integration
- Expanded-path status: draft pass complete; refine pass complete; ready for
  implementation handoff
- Plan quality gate: passed on 2026-05-08 after initial review, one refinement
  pass, and confirmation review
- Plan quality gate loop budget: initial review used, refinement used,
  confirmation review used
- Draft pass: completed by `loom_phase_planner`
- Refine pass: completed by `loom_phase_planner` using architecture findings
  for `loom run --dry-run`, Phase 4 persisted-state inputs, dry-run-only SLURM
  executor resolution, preflight stable IDs, and CLI output envelope helpers
- Setup limitations: worktree was created from local `develop` at `9480ac0`;
  no remote synchronization, product-code validation, or broad checks were run
  in this planning-only pass
- Blockers: none known for implementation handoff

## Objective

Expose the v6 SLURM dry-run planning layer through public CLI and diagnostics
surfaces. Users must be able to run:

```sh
loom run CONFIG --executor slurm-single-job --dry-run
loom run CONFIG --executor slurm-afterok --dry-run
```

and receive concise text or JSON output that points to generated manifests,
scripts, log paths, warnings, and counts without printing full scripts by
default. Selecting either SLURM executor without `--dry-run` must fail clearly
as v7-deferred live submission.

## Full-Plan Context

Phases 1-4 provide the generic prepared-run state, continuation commands, SLURM
models/options/resources/manifests, and Python dry-run planning APIs. Phase 4
SLURM planners deliberately read persisted execution-plan and prepared-run
records from the run store before writing artifacts. Therefore Phase 5's central
architectural decision is that the CLI must perform a bounded, artifact-safe
preparation flow before calling those public Phase 4 APIs. It must not use
`PipelineRunner.run()` for SLURM dry-runs, because the runner is an execution
surface and rejects dry-run requests by design.

Phase 5 is also the diagnostics/runtime integration point. Runtime capability
support must make `slurm-single-job` and `slurm-afterok` resolvable dry-run
executor names, claim the `slurm` adapter namespace, and expose resource
mapping diagnostics without constructing a live scheduler executor or implying
live submission support.

Preflight is best-effort diagnostics. For v6, SLURM preflight checks must report
shape, support, and local readiness issues for dry-run planning while treating
missing `sbatch` as warning or informational output, not a dry-run blocker.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phases 1-4 are recorded as merged in
  the v6 implementation plan
- Why this base branch is correct: the manager assigned `develop` because all
  earlier v6 phases are merged
- Retarget/rebase plan after predecessor merge: none required unless `develop`
  moves before PR preparation, in which case rebase this branch onto updated
  `develop`
- Branch cleanup constraints: branch can be deleted after merge if no successor
  branch depends on it

## Source Phase Summary

- Required scope: add public `loom run` dry-run behavior for
  `slurm-single-job` and `slurm-afterok`; fail clearly for non-dry-run SLURM
  executor selection; report counts, manifest paths, script directories, and
  warnings in text/JSON; add stable SLURM preflight checks for profile shape,
  resource mapping support, shared/local run URI assumptions, safe script/log
  paths, launcher command shape, and optional `sbatch` availability.
- Required exclusions: no live submission, scheduler job ID parsing,
  status/cancel commands, real cluster acceptance tests, fallback PR/merge
  workflow changes, controller mode, scheduler state, or fake submitted state.
- Required acceptance: CLI dry-run commands create the same artifacts as the
  Python API; non-dry-run SLURM fails with a v7-deferred error; output points to
  manifest/script directories and reports warnings; preflight errors and
  warnings use stable check IDs.

## Current Source Findings

- `src/loom/cli/run.py` currently handles any `--dry-run` by delegating to
  `loom.cli.plan.build_plan_result`; it returns planning summaries only and
  does not create run directories, write prepared-run metadata, or call SLURM
  dry-run APIs.
- `src/loom/cli/run.py` supports non-dry-run executors only through local and
  subprocess construction. Unknown executors raise `UnsupportedExecutorError`
  with a generic local/subprocess message.
- `src/loom/cli/plan.py` plans with `persist=False`; Phase 5 needs a
  dry-run-preparation path that persists the execution plan and safe
  prepared-run record before invoking Phase 4 SLURM planners.
- `src/loom/pipeline/executors/slurm/planning.py` exposes
  `plan_single_job_slurm_dry_run` and `plan_afterok_slurm_dry_run`; both read
  persisted plan and prepared-run state and write artifacts through public
  store/path APIs.
- `PipelineRunner.run()` is not a valid implementation shortcut for this
  phase. It is an execution path, not a dry-run artifact-preparation path, and
  it must not be invoked for SLURM dry-run generation.
- `src/loom/pipeline/executors/slurm` already owns script rendering,
  artifact writing, manifest records, options, resources, and logical job keys.
  Phase 5 should reuse those public APIs and result models.
- `src/loom/diagnostics/models.py` has stable check IDs for generic groups but
  no SLURM-specific IDs yet. `_result()` asserts that every emitted ID is
  registered in `STABLE_CHECK_IDS`.
- `src/loom/diagnostics/preflight.py` currently checks local/subprocess
  executor readiness, generic capability validation, resources, run URI, and
  filesystem inputs. It has no SLURM-specific profile/options, launcher,
  generated-artifact path, or `sbatch` checks.
- The default executor capability registry includes `local` and `subprocess`
  only. Phase 5 must decide how to make `slurm-single-job` and `slurm-afterok`
  resolvable for dry-run diagnostics without enabling live execution.
- Existing output envelope helpers live in `src/loom/cli/formatting.py` and
  CLI result/warning plain-data helpers live in `src/loom/cli/results.py`;
  Phase 5 should extend these patterns instead of inventing a separate output
  envelope.

## In-Scope Work

- Extend `loom run` dry-run dispatch so explicit executor values
  `slurm-single-job` and `slurm-afterok` enter a SLURM dry-run path instead of
  the generic plan-only dry-run path.
- In the SLURM dry-run path, compose config, validate pipeline, merge runtime
  options and selectors, resolve or allocate a local run URI, create/open the
  run according to existing run-uri semantics, persist a safe execution plan,
  persist prepared-run metadata, and call the matching Phase 4 public dry-run
  planning API.
- Keep the bounded preparation flow local to the CLI layer:
  1. compose config and validate pipeline;
  2. merge runtime/profile/selector options;
  3. resolve or allocate a local run URI;
  4. run preflight using the resolved dry-run runtime options;
  5. create the run directory;
  6. plan with `persist=True`;
  7. write a schema-versioned artifact-safe `PreparedRunRecord`;
  8. call the selected Phase 4 SLURM dry-run planner;
  9. adapt the typed result into existing CLI text/JSON envelope helpers.
- Parse SLURM options from `RunOptions.adapter_options["slurm"]` and
  stage-level `adapter_options["slurm"]` using `SlurmOptions`, preserving
  existing runtime profile merge semantics and path-aware structured errors.
- Pass generic run-level resources to single-job dry-run planning and
  per-stage resources to afterok dry-run planning using existing runtime
  resource models and Phase 3 resource mapping.
- Add a CLI-facing SLURM dry-run result model with stable plain-data output:
  run URI, mode, dry-run flag, planning ID, manifest path, plan path, generated
  script paths or script directory, wrapper log paths, job/dependency counts,
  generated command summaries, resource summaries, and preflight warnings.
- Add a stable JSON schema version for SLURM dry-run output, while keeping the
  existing generic plan dry-run schema for non-SLURM dry-run planning.
- Add concise text formatting that reports generated artifact counts and paths
  without printing script bodies by default.
- Emit warnings from SLURM preflight into CLI JSON/text output in the existing
  top-level warning style or an equivalent stable result field.
- Add a clear v7-deferred non-dry-run error for `slurm-single-job` and
  `slurm-afterok`, with a stable error code and hint to use `--dry-run`.
- Add SLURM executor descriptors or equivalent capability-registration support
  so preflight can resolve the SLURM dry-run executor names, claim the `slurm`
  adapter namespace, and report CPU/memory/GPU mapping support without enabling
  live execution.
- Extend diagnostics preflight with stable SLURM check IDs for executor mode,
  structured SLURM options/profile shape, resource mapping, run URI locality,
  generated script/log path safety, launcher argv shape, and `sbatch`
  availability.
- Register these exact new preflight check IDs in `STABLE_CHECK_IDS` and lock
  them with contract tests:
  - Runtime group: `runtime.slurm.options`
  - Run group: `run_uri.slurm.local`
  - Executor group: `executor.slurm.mode`, `executor.slurm.launcher`,
    `executor.slurm.sbatch`
  - Resources group: `resources.slurm.mapping`
  - Filesystem group: `filesystem.slurm.generated_paths`
- Treat missing `sbatch` as `WARN` or `INFO` for SLURM dry-run modes. It must
  not prevent artifact generation.
- Add focused package, unit, contract, integration, and e2e coverage for public
  CLI and diagnostics behavior.

## Out-of-Scope Work

- No `sbatch`, `squeue`, `sacct`, `scancel`, subprocess scheduler command
  runner, job ID parsing, partial submission records, status polling,
  cancellation, scheduler state, submitted stage status, or fake scheduler IDs.
- No `loom slurm status`, `loom slurm cancel`, controller mode, job arrays,
  MPI orchestration, advanced `srun`, retry, timeout, cleanup, retention,
  remote stores, containers, plugin discovery, or real cluster tests.
- No changes to generated script semantics already owned by Phase 4 except
  through existing public SLURM options/resource inputs.
- No CLI-owned script rendering or manifest construction.
- No change to generic `loom plan` semantics unless a small shared helper is
  needed to avoid duplicating config/runtime/planning code.
- No use of `PipelineRunner.run()` or executor construction to create SLURM
  dry-run artifacts.
- No weakening of the v6 secret boundary: do not persist unredacted resolved
  config values, resolver outputs, environment values, or raw adapter payloads.
- No workflow prompt, template, `AGENTS.md`, PR/merge policy, or product-unrelated
  refactors.

## Assumptions

- SLURM CLI options are supplied through existing runtime profile and
  `adapter_options` mechanisms, not through a broad new set of `loom run`
  flags in Phase 5.
- If the CLI must persist prepared-run metadata for dry-run planning, it should
  use the Phase 1 `PreparedRunRecord` contract with artifact-safe summaries and
  continuation type `whole_run`; it must not persist replay payloads to make
  whole-run continuation executable.
- The run URI for Phase 5 dry-run artifacts is local. If a remote or unsupported
  URI is selected, preflight and CLI should fail clearly before SLURM artifact
  writes.
- Existing generated-artifact path helpers are sufficient to validate script
  and log path safety. If they are not, stop and record the missing store/path
  contract rather than path-walking run directories in CLI code.
- `sbatch` availability can be checked with standard-library path lookup only;
  no scheduler command should be invoked in v6.

## Scope Contract

The CLI SLURM dry-run path is a presentation adapter over config/runtime,
planning, execution preparation, diagnostics, and SLURM dry-run APIs. The likely
shape is a new helper in `src/loom/cli/run.py` or a new import-light module such
as `src/loom/cli/slurm_dry_run.py`; either is acceptable if `loom.cli.main`
remains cheap and lower layers do not import `loom.cli`.

The CLI should not call `PipelineRunner.run()` for dry-run requests because the
runner intentionally rejects dry-run execution. Instead, it should perform a
bounded preparation flow: compose config, validate pipeline, merge runtime
options, resolve run URI, run preflight, create the run, plan with persistence,
write prepared-run metadata, and invoke the Phase 4 SLURM planner. Any shared
helper extracted from `loom.cli.plan` or `loom.cli.run` must be small and
presentation-layer-local.

The preparation flow must write only documents already allowed by existing
store contracts: persisted `ExecutionPlan` via planning persistence and
`PreparedRunRecord` via the prepared-run store validation. Prepared metadata
should summarize the selected dry-run executor, continuation type, safe runtime
facts, and plan facts needed by Phase 4; it must not add replay payloads,
resolved config snapshots, resolver outputs, environment values, or raw adapter
payloads.

Preflight check IDs are public diagnostic contract. Add new IDs only by updating
`STABLE_CHECK_IDS` and contract tests. Use these exact IDs:

| Group | Check IDs |
| --- | --- |
| `runtime` | `runtime.slurm.options` |
| `run` | `run_uri.slurm.local` |
| `executor` | `executor.slurm.mode`, `executor.slurm.launcher`, `executor.slurm.sbatch` |
| `resources` | `resources.slurm.mapping` |
| `filesystem` | `filesystem.slurm.generated_paths` |

`runtime.slurm.options` validates the `slurm` adapter-option shape after
runtime profile merging. `executor.slurm.mode` verifies the selected executor is
one of the two v6 dry-run modes and reports non-dry-run live behavior as
deferred. `executor.slurm.launcher` validates structured launcher argv shape.
`executor.slurm.sbatch` checks `shutil.which("sbatch")` only and reports a
non-fatal warning/info when absent. `resources.slurm.mapping` validates generic
CPU, memory, and GPU resource mapping through Phase 3 resource mappers.
`run_uri.slurm.local` and `filesystem.slurm.generated_paths` validate local
run-store assumptions and generated-artifact path safety through store/path
helpers.

SLURM executor names must be resolvable for dry-run diagnostics but must not
construct live executor objects. Non-dry-run `loom run` with either SLURM mode
should fail before runner construction with a stable v7-deferred error. Dry-run
preflight warnings should be visible in output, but warning status alone must
not block artifact generation unless `--strict` behavior is explicitly used by
the preflight command, not `loom run`.

CLI output must use the existing `format_json_envelope` warning channel and
plain-data normalization in `cli.results`. Add a focused SLURM dry-run result
model and text formatter alongside existing run/plan result types instead of a
custom JSON serializer.

## Acceptance Criteria

- `loom run CONFIG --executor slurm-single-job --dry-run` creates the same
  single-job manifest, script, log-path records, and planning metadata as
  `plan_single_job_slurm_dry_run` for equivalent inputs.
- `loom run CONFIG --executor slurm-afterok --dry-run` creates the same afterok
  manifest, scripts, logical dependency records, log-path records, and planning
  metadata as `plan_afterok_slurm_dry_run` for equivalent inputs.
- The CLI persists only artifact-safe plan/prepared-run metadata needed by the
  Phase 4 APIs and does not persist resolved secrets, resolver outputs,
  environment values, or raw adapter payloads.
- `PipelineRunner.run()` is not used by the SLURM dry-run CLI path; the
  implementation proves artifact generation comes from persisted plan and
  prepared-run state consumed by public Phase 4 APIs.
- Non-dry-run `slurm-single-job` and `slurm-afterok` fail with a clear
  v7-deferred error and a stable error code.
- Text output reports run URI, mode, planning ID, manifest path, script count
  or directory, dependency count, and warnings without script bodies.
- JSON output is schema-versioned and includes stable result and warning
  fields suitable for tests and future v7 extension.
- Preflight emits the exact stable SLURM check IDs
  `runtime.slurm.options`, `run_uri.slurm.local`, `executor.slurm.mode`,
  `executor.slurm.launcher`, `executor.slurm.sbatch`,
  `resources.slurm.mapping`, and `filesystem.slurm.generated_paths`.
- Missing `sbatch` is not fatal for v6 dry-run planning.
- CLI and diagnostics remain import-light; lower layers do not import
  `loom.cli`, diagnostics does not import heavy optional scheduler libraries,
  and SLURM planning code does not import CLI modules.

## Design Impact

- Public CLI behavior expands from local/subprocess execution plus generic
  plan-only dry-run to durable SLURM dry-run artifact generation.
- Diagnostics gains scheduler-aware but cluster-free checks. These checks are
  public contract because their IDs and JSON payloads can be consumed by
  tooling.
- Runtime capability registration distinguishes dry-run planning support from
  live executor availability. `slurm-single-job` and `slurm-afterok` become
  valid dry-run names that claim the `slurm` adapter namespace and resource
  mapping diagnostics, while non-dry-run execution remains v7-deferred.
- The phase reinforces the source-tree boundary: CLI owns presentation,
  diagnostics owns best-effort readiness checks, runtime owns capability
  descriptors, execution/planning/stores own durable prepared state, and SLURM
  owns script/manifest generation.

## Future Compatibility

- V7 can add live submission by extending the same executor names with a live
  path, scheduler command runner, job ID reporting, and submitted-state
  persistence without changing the dry-run result shape.
- V7 can lift `sbatch` from warning/info to required live-submission preflight
  when `--dry-run` is absent.
- Future status/cancel commands can read v7 scheduler records while preserving
  the v6 logical job keys and dry-run manifest shape.
- Future container or remote-store phases can reuse the CLI preparation pattern
  but should define their own diagnostics and path contracts.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep `loom run --dry-run` as generic plan output for SLURM executors | V6 requires durable SLURM scripts and manifests through the public CLI. |
| Use `PipelineRunner.run()` to prepare dry-run artifacts | The runner is an execution path and rejects dry-run requests; Phase 5 must persist safe plan/prepared-run state and call Phase 4 APIs directly. |
| Generate scripts directly in CLI code | SLURM rendering and manifest contracts belong under `loom.pipeline.executors.slurm`; CLI is only presentation. |
| Block dry-runs when `sbatch` is missing | V6 is cluster-free dry-run planning and must work on development machines without SLURM. |
| Treat `slurm-single-job` and `slurm-afterok` as fully supported executors | Live submission is explicitly deferred to v7; Phase 5 must fail non-dry-run selection clearly. |
| Add many SLURM-specific CLI flags now | Runtime profiles and adapter options already provide the structured configuration path; broad flag design belongs to a later public CLI design pass if needed. |
| Print generated scripts by default | Default output should be concise and path-oriented; script inspection can happen by opening generated artifacts. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| SLURM executor names are dry-run-only public selections | V6 intentionally stops before live submission while still exposing dry-run artifacts. | V7 live submission starts. |
| No public CLI flags for individual SLURM options | Runtime profiles keep Phase 5 small and avoid an unstable flag matrix. | Repeated user need for ad hoc CLI overrides after v6/v7. |
| `sbatch` readiness is informational for dry-run | Missing scheduler binaries should not block local artifact planning. | Live submission path makes scheduler availability required. |
| Status/cancel remain absent | Scheduler job IDs and submitted records do not exist in v6. | V7 adds live job IDs and scheduler state. |

## Reviewability

- Expected PR size and shape: moderate CLI/diagnostics integration PR with
  focused result models, formatting, runtime capability/preflight additions,
  and tests; no script-rendering rewrite or scheduler command runner.
- Files and areas to inspect: `src/loom/cli/run.py`,
  `src/loom/cli/results.py`, `src/loom/cli/formatting.py`,
  `src/loom/diagnostics/models.py`, `src/loom/diagnostics/preflight.py`,
  `src/loom/pipeline/runtime/capabilities.py`,
  `src/loom/pipeline/executors/slurm/`, and corresponding tests under package,
  unit, contract, integration, and e2e suites.
- Scope-control checks: no `sbatch` execution, no scheduler IDs or statuses,
  no `loom slurm status/cancel`, no CLI-owned script construction, no
  `PipelineRunner.run()` use for SLURM dry-run, no resolved-secret persistence,
  no lower-layer `loom.cli` imports, no
  product-unrelated docs/workflow changes, and no broad executor registry or
  plugin redesign.

## Test Plan

### Package Suite

- Status: required
- Expected paths: package import and boundary tests such as
  `tests/package/test_import.py`, `tests/package/test_public_api.py`, and
  `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: CLI remains import-light before
  command dispatch; SLURM package imports without optional scheduler
  dependencies; dry-run-only SLURM runtime capability descriptors do not import
  diagnostics, CLI, or scheduler modules; lower layers do not import
  `loom.cli`.

### Unit Suite

- Status: required
- Expected paths: new or updated tests under `tests/unit/loom/cli/`,
  `tests/unit/loom/diagnostics/`, `tests/unit/loom/pipeline/runtime/`, and
  existing SLURM unit tests
- Required assertions or deferral reason: `loom run` parser routes explicit
  SLURM dry-run modes to the bounded preparation flow and keeps generic
  non-SLURM `--dry-run` on plan output; non-dry-run SLURM errors are stable;
  `PipelineRunner.run()` is not called for SLURM dry-run generation; text and
  JSON result formatting uses existing envelope helpers and is concise and
  schema-versioned; SLURM adapter options and stage adapter options parse
  through `SlurmOptions`; the exact stable preflight check IDs, statuses, and
  details are stable; missing `sbatch` is warning/info; resource mapping
  diagnostics cover CPU, memory, GPU, unsupported resources, and conflicts.

### Contract Suite

- Status: required
- Expected paths: new or updated contract tests such as
  `tests/contracts/test_cli_run_slurm_contract.py`,
  `tests/contracts/test_cli_preflight_contract.py`,
  `tests/contracts/test_diagnostics_preflight_contract.py`,
  `tests/contracts/test_executor_capabilities_contract.py`, and existing
  `tests/contracts/test_slurm_manifest_contract.py`
- Required assertions or deferral reason: SLURM dry-run JSON schema and warning
  payloads are stable; `STABLE_CHECK_IDS` includes
  `runtime.slurm.options`, `run_uri.slurm.local`, `executor.slurm.mode`,
  `executor.slurm.launcher`, `executor.slurm.sbatch`,
  `resources.slurm.mapping`, and `filesystem.slurm.generated_paths`; SLURM
  executor descriptors claim the `slurm` adapter namespace and expose dry-run
  capability without implying live submission; generated manifest contract
  remains unchanged.

### Integration Suite

- Status: required
- Expected paths: new or updated integration tests under
  `tests/integration/config/test_cli_run.py`,
  `tests/integration/pipeline/test_slurm_dry_run_planning.py`, and
  `tests/integration/pipeline/` as needed
- Required assertions or deferral reason: CLI dry-run generation against a
  temporary local run store creates the same artifact family as the Python API;
  persisted plan and prepared-run records are present and artifact-safe before
  Phase 4 planners run; both modes report paths and warnings; preflight
  integrates with real composed config/runtime profile data; repeated dry-runs
  create distinct planning directories.

### E2E Suite

- Status: required
- Expected paths: new or updated e2e tests such as
  `tests/e2e/test_cli_slurm_dry_run.py`
- Required assertions or deferral reason: a small local config works through
  `loom run --executor slurm-single-job --dry-run` and
  `loom run --executor slurm-afterok --dry-run`; generated artifacts can be
  inspected for manifest/script path presence; no scheduler binary or cluster
  is required.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: no real SLURM, live scheduler,
  remote-store, container, or cluster acceptance suite applies in Phase 5.

## Risks

- CLI preparation may duplicate planning/run setup logic from `loom plan` and
  `loom run`; mitigate with small CLI-local helpers instead of moving
  presentation code into lower layers.
- Making SLURM executor names resolvable can accidentally imply live execution
  support; mitigate with explicit dry-run-only descriptor details and
  non-dry-run error tests.
- Preflight check IDs are public contract; choose stable IDs once in the refine
  pass and lock them with contract tests.
- Runtime adapter option parsing can leak raw payloads or bypass Phase 3
  validation; always construct `SlurmOptions` and pass typed summaries only.
- Persisting prepared-run state from CLI can reopen the secret boundary; reuse
  `PreparedRunRecord` validation and add regression tests for environment
  values and resolver outputs.
- Runtime capability support can overstate v6 readiness; descriptor details and
  non-dry-run tests must make live submission explicitly deferred.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import.py tests/package/test_public_api.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/cli tests/unit/loom/diagnostics tests/unit/loom/pipeline/runtime tests/unit/loom/pipeline/executors/slurm
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_cli_run_slurm_contract.py tests/contracts/test_cli_preflight_contract.py tests/contracts/test_diagnostics_preflight_contract.py tests/contracts/test_executor_capabilities_contract.py tests/contracts/test_slurm_manifest_contract.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/config/test_cli_run.py tests/integration/pipeline/test_slurm_dry_run_planning.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/e2e/test_cli_slurm_dry_run.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Stop Conditions

- SLURM dry-run CLI cannot persist the plan/prepared-run state needed by Phase
  4 without storing unredacted resolved config values, resolver outputs,
  environment values, or raw adapter payloads.
- Supporting SLURM executor names requires enabling live scheduler behavior or
  weakening the non-dry-run v7-deferred error.
- The exact stable preflight check IDs named in this plan cannot be registered
  in `STABLE_CHECK_IDS` without a diagnostics model migration that exceeds
  Phase 5 scope.
- Safe generated-artifact path validation cannot be performed through existing
  store/path helpers and would require CLI path-walking of run directories.
- Integration or e2e coverage would need a real scheduler binary or cluster to
  pass.
- Implementation requires changes to Phase 4 script/manifest contracts that are
  not presentation-level integration fixes.

## Handoff Notes For `loom_phase_executor`

- Start with the public behavior boundary: route explicit SLURM dry-run
  executor names to the bounded preparation flow, keep generic non-SLURM
  `--dry-run` on plan output, add the v7-deferred non-dry-run error, and define
  the CLI result schema before broadening diagnostics.
- The bounded preparation flow is the core implementation contract: compose,
  validate, merge runtime, resolve/allocate local run URI, preflight, create
  run, persist plan, write artifact-safe `PreparedRunRecord`, call the selected
  Phase 4 planner, then format with existing CLI envelope helpers.
- Keep SLURM script and manifest work inside `loom.pipeline.executors.slurm`;
  call `plan_single_job_slurm_dry_run` and `plan_afterok_slurm_dry_run` rather
  than building artifacts in CLI code.
- Add capability/preflight support in a way that keeps `slurm-single-job` and
  `slurm-afterok` valid dry-run selections but unmistakably non-live in v6.
- Register and test exactly these preflight IDs:
  `runtime.slurm.options`, `run_uri.slurm.local`, `executor.slurm.mode`,
  `executor.slurm.launcher`, `executor.slurm.sbatch`,
  `resources.slurm.mapping`, and `filesystem.slurm.generated_paths`.
- Use focused tests as the behavior driver. Do not implement status/cancel,
  scheduler command runners, real cluster checks, or new broad SLURM CLI flag
  families.
- Conditions requiring manager stop are listed above; do not solve them by
  persisting secret-bearing state or introducing fake scheduler state.

## Refinement And Review Budget Status

- Phase plan draft: used on 2026-05-08
- Phase plan refine: used on 2026-05-08 to lock the bounded artifact-safe CLI
  preparation flow, dry-run-only runtime/diagnostics support for SLURM executor
  names, exact stable preflight check IDs, and existing CLI output-envelope use
- Phase implementation refinement: unused; reserved for the implementation
  stage if expanded-path refinement, validation failure, or missing coverage
  requires it
- PR review: unused; reserved for the PR review stage
- Blocker resolution: 0/3 used
