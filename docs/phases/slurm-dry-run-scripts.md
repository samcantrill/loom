# Phase 4 Execution Plan: SLURM Script Builders And Dry-Run Planning APIs

## Metadata

- Status: pr_open
- Feature focus: SLURM Script Planning
- PR title: `SLURM Script Planning - Phase 4: SLURM Script Builders and Dry-Run APIs`
- Branch: `codex/slurm-dry-run-scripts`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-dry-run-scripts`
- Phase execution plan path: `docs/phases/slurm-dry-run-scripts.md`
- PR body path: `docs/phases/slurm-dry-run-scripts-pr-body.md`
- Full plan: `docs/implementation-plans/implementation-plan-v6.md`
- Source phase: Phase 4 - SLURM Script Builders And Dry-Run Planning APIs
- PR: https://github.com/samcantrill/loom/pull/85
- PR state: open
- Stack predecessor: none; Phases 1-3 are merged into `develop`
- Base branch: `develop`
- Target branch: `develop`
- Base/head verification: `gh pr view 85 --json
  baseRefName,headRefName,state,url,statusCheckRollup` returned
  `baseRefName=develop`, `headRefName=codex/slurm-dry-run-scripts`,
  `state=OPEN`, and URL `https://github.com/samcantrill/loom/pull/85` on
  2026-05-08.
- Stack state: root phase targeting `develop`; no stack predecessor and no
  retargeting required at PR opening.
- GitHub checks: CI `checks` pending at final PR-prep verification on
  2026-05-08.
- Merge eligibility: root phase; merge-eligible only after the PR targets
  `develop`, the expanded-path refine pass is complete, implementation is
  phase-scoped, automated review passes, and validation/CI passes
- Workflow path: expanded path
- Expanded-path status: draft pass complete; refine pass complete; ready for
  implementation handoff
- Plan quality gate: passed on 2026-05-08 after initial review, one refinement
  pass, and confirmation review
- Plan quality gate loop budget: initial review used, refinement used,
  confirmation review used
- Draft pass: completed by `loom_phase_planner`
- Refine pass: completed on 2026-05-08 using architecture findings for SLURM
  package boundaries, persisted plan reads, store-owned writes, and renderer
  contracts
- Setup limitations: worktree was created from local `develop` at `434a9c1`; no
  remote synchronization or validation was run in this planning-only pass
- Blockers: none known after PR preparation

## Objective

Generate deterministic, reviewable SLURM dry-run artifacts from an existing Loom
run plan and prepared-run state. This phase stays inside
`src/loom/pipeline/executors/slurm/` and turns the Phase 3 model layer into
concrete scripts, manifest files, wrapper log paths, and planning metadata
through Python APIs only. It must not add CLI executor selection, preflight
presentation, shell lifecycle logic, live scheduler calls, scheduler job IDs,
submitted status, or fake scheduler state.

## Full-Plan Context

V6 already has the generic execution contracts needed by submitted jobs:
prepared-run metadata and store path helpers from Phase 1, continuation commands
from Phase 2, and SLURM options/resources/manifest/path contracts from Phase 3.
Phase 4 is the artifact-generation layer between those foundations and the
Phase 5 CLI integration.

The scripts produced here are durable review artifacts. Single-job scripts must
invoke `loom prepared-run continue --run-uri RUN_URI --executor local` through
`build_single_job_command_argv`. Afterok scripts must invoke
`loom stage-job run --run-uri RUN_URI --stage STAGE --executor local` through
`build_stage_job_command_argv` and express dependencies in manifests through
logical job keys, not scheduler job IDs.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phases 1, 2, and 3 are recorded as
  merged in the v6 implementation plan
- Why this base branch is correct: the manager assigned `develop` because all
  earlier v6 phases are merged
- Retarget/rebase plan after predecessor merge: none required unless `develop`
  moves before PR preparation, in which case rebase this branch onto updated
  `develop`
- Branch cleanup constraints: branch can be deleted after merge if no successor
  branch depends on it

## Source Phase Summary

- Goal: generate reviewable single-job and afterok SLURM dry-run artifacts from
  an existing Loom plan and prepared run state.
- Required scope: deterministic SBATCH scripts, single-job prepared-run
  continuation argv, afterok stage-job continuation argv, logical afterok
  dependency records, dry-run manifests, plan metadata, wrapper log paths, and
  store-owned generated artifact paths under
  `slurm/submissions/<planning_id>/...`.
- Required exclusions: no CLI executor selection, preflight presentation, live
  job ID parsing, scheduler polling, cancellation, controller mode, `sbatch`,
  submitted status, fake job IDs, or scheduler state.
- Required acceptance: Python APIs can generate single-job and afterok artifacts
  for synthetic pipelines; scripts are deterministic, shell-quoted, executable
  when practical, and avoid environment values; afterok scripts target
  `loom stage-job run`; dependency planning covers chain, fan-in, fan-out, and
  diamond DAGs; repeated dry-runs write distinct planning directories.

## Current Source Findings

- `loom.pipeline.executors.slurm` is a pure, optional-dependency-free package
  with Phase 3 exports for `SlurmMode`, `SlurmOptions`, `SlurmCommandArgv`,
  `SlurmPlannedJob`, `SlurmPlannedDependency`, `SlurmPlannedSubmission`,
  `SlurmSbatchDirective`, resource mapping, logical job keys, and generated
  artifact path helpers.
- Phase 4 should reuse the Phase 3 contracts directly:
  `SlurmOptions`, `SlurmCommandArgv`, `build_single_job_command_argv`,
  `build_stage_job_command_argv`, `build_sbatch_directives`,
  `SlurmPlannedJob`, `SlurmPlannedSubmission`, and
  `resolve_slurm_generated_artifact_path`.
- Phase 3 command argv helpers already target the v6 continuation commands:
  single-job argv uses `prepared-run continue`, and afterok argv uses
  `stage-job run`.
- Phase 3 path helpers build safe relative paths under
  `slurm/submissions/<planning_id>/...` and resolve them through
  `LocalRunStorePaths.local_generated_artifact_path`.
- The local run store persists `plan.json` and `prepared_run.json`; Phase 4
  should read them through `RunStore.read_plan` and
  `RunStore.read_prepared_run`, then parse through `ExecutionPlan.from_dict`
  and `PreparedRunRecord.from_dict`.
- `ExecutionPlan.ordered_stage_plans`, `StagePlan.action`, and
  `StagePlan.upstream_stages` provide the public dependency inputs needed for
  afterok planning. Prefer these plan facts over recomputing pipeline graph
  semantics.
- Store-owned local generated artifact resolution and atomic writes already
  exist through `local_generated_artifact_path`,
  `resolve_slurm_generated_artifact_path`, `atomic_write_text`, and
  `atomic_write_json`. Phase 4 must not walk run directories or import
  `LocalRunStore` internals.
- There is no existing shell-safe command renderer. Phase 4 needs a dedicated
  renderer module that turns structured `SlurmCommandArgv.argv` into shell text
  with standard-library `shlex.quote`.
- Existing SLURM tests cover options, resources, manifests, and store path
  helpers. Phase 4 should add script-rendering, dependency planning, artifact
  writing, and planning API tests without weakening Phase 3 contracts.

## In-Scope Work

- Add SLURM script rendering APIs under `loom.pipeline.executors.slurm` for
  deterministic SBATCH directive ordering, trusted prelude lines, quoted command
  bodies, wrapper log paths, and executable script content.
- Add dry-run planning APIs that take an existing run URI, persisted plan,
  prepared-run metadata, SLURM mode, structured `SlurmOptions`, canonical
  resources/runtime data, and a generated planning ID or planning-ID factory.
- Build a single-job planned submission with one `pipeline` job, one script,
  stdout/stderr wrapper log paths, a generated command argv record, planned
  resource/directive summaries, a copied or summarized plan metadata artifact,
  and a schema-versioned manifest.
- Build afterok planned submissions with one script per planned `RUN` stage,
  `stage:<stage_name>` logical job keys, logical `afterok` dependency records,
  per-job wrapper log paths, per-job command argv records, and a
  schema-versioned manifest.
- Write scripts, `plan.json` or equivalent planning metadata, and
  `manifest.json` under a distinct
  `slurm/submissions/<planning_id>/...` directory through store-owned generated
  artifact path helpers.
- Add an artifact writer/result model that records generated relative paths and
  local paths returned by the store helper, writes script text with
  `atomic_write_text`, writes manifest/metadata with `atomic_write_json`, and
  returns the parsed `SlurmPlannedSubmission` plus generated artifact paths.
- Keep scripts and manifests secret-safe: no unredacted resolved config values,
  resolver outputs, environment variable values, raw adapter payloads, full
  environment dumps, or submitted scheduler state by default.
- Add focused package, unit, contract, and integration coverage for rendering,
  quoting, dependency planning, manifest stability, and local run-store artifact
  writes.

## Out-of-Scope Work

- No `loom run --executor slurm-single-job` or
  `loom run --executor slurm-afterok`; Phase 5 owns CLI selection and output.
- No preflight presentation, `sbatch` availability checks, or CLI warning
  mapping; Phase 5 owns diagnostics integration.
- No live `sbatch`, `squeue`, `sacct`, `scancel`, scheduler API dependency,
  subprocess submission, command runner abstraction, or real cluster tests.
- No scheduler job ID parsing, placeholder IDs, submitted status, scheduler
  state, polling, cancellation, partial-submission recovery, or controller mode.
- No changes to `loom prepared-run continue`, `loom stage-job run`, or the v5
  `loom stage run` handoff-only worker contract.
- No generic wall-time resource, container command composition, remote-store
  support, plugin discovery, retries, timeout enforcement, cleanup policy, or
  retention policy.
- No broad runner, planner, store, config, runtime, or CLI refactors.
- No imports from `loom.cli`, `loom.config`, scheduler libraries, `subprocess`,
  or new root `loom` exports from the SLURM dry-run planner.

## Assumptions

- Phase 4 can introduce script-builder and dry-run planner modules inside the
  existing SLURM executor package without changing the Phase 3 public model
  wire contracts.
- The persisted plan has enough public data for Phase 4 to select planned
  `RUN` stages and logical upstream dependencies. If not, the executor must
  stop and record the missing safe plan contract instead of inferring from
  private store layout or config snapshots.
- Planning IDs should be deterministic when supplied by tests and distinct by
  default for repeated user dry-runs.
- Scripts may include trusted prelude lines from `SlurmOptions.prelude`; those
  lines are authored project code and are not sanitized into shell argv.
- Script executability should be set where practical on local files, but the
  durable contract is the generated file content and manifest paths.

## Scope Contract

The Phase 4 public API is a Python planning surface, not a CLI. It should accept
already-prepared run state and structured SLURM options, then return a typed
planned-submission result with manifest data and generated artifact paths. Lower
layers must remain independent of `loom.cli`.

The likely implementation modules are:

- `src/loom/pipeline/executors/slurm/rendering.py` or equivalent for shell-safe
  command and script rendering from structured argv and directive records.
- `src/loom/pipeline/executors/slurm/planning.py` or equivalent for the dry-run
  API that reads public run-store state, builds jobs/dependencies, and returns
  planned submissions.
- `src/loom/pipeline/executors/slurm/artifacts.py` or equivalent for generated
  artifact path resolution, atomic writes, and typed result records.

These names are guidance, not a mandate. Keep all Phase 4 product code under
the SLURM package and preserve import-light package behavior.

Script rendering must be deterministic. SBATCH directives are rendered from
generated directives, modeled `SlurmOptions`, mapped resources, and validated
`extra_sbatch` records in stable order. Generated directives own job name,
stdout path, stderr path, and dependency syntax. `extra_sbatch` remains unable
to override those fields through Phase 3 validation.

Shell command rendering must use standard-library `shlex.quote` over structured
argv. Scripts must not reconstruct commands by string parsing, print
environment values, inline resolver outputs, or replay an unredacted resolved
config. The only generated Loom command targets are the Phase 2 continuation
commands: `prepared-run continue` and `stage-job run` with `--executor local`.

Afterok planning must be derived from public persisted plan data:
`RunStore.read_plan`, `ExecutionPlan.from_dict`,
`ExecutionPlan.ordered_stage_plans`, `StagePlan.action`, and
`StagePlan.upstream_stages`. Use `PreparedRunRecord.from_dict` from
`RunStore.read_prepared_run` only for safe prepared-run/run metadata needed to
build the continuation commands and validate the run being planned. Do not
derive dependencies from scheduler assumptions, raw config, private DAG
internals, or run-directory walking.

Manifest and planning metadata remain dry-run-only. Scheduler job IDs, raw job
IDs, submitted status, scheduler state, and command-runner results must be
absent or null. Dependencies are logical records only, with dependency type
`afterok`.

Generated artifact paths remain store-owned. SLURM code supplies relative paths
under `slurm/submissions/<planning_id>/...` to the Phase 1/3 path helpers and
does not derive absolute run-directory paths by walking local store internals.
All writes should go through the resulting local paths with
`atomic_write_text` or `atomic_write_json`.

## Acceptance Criteria

- Python APIs generate single-job dry-run artifacts for a synthetic prepared
  run, including script file, wrapper stdout/stderr paths, planning metadata,
  and manifest.
- Python APIs generate afterok dry-run artifacts for synthetic chain, fan-in,
  fan-out, and diamond DAGs, with one script per planned `RUN` stage and
  correct logical dependency records.
- Single-job scripts invoke `loom prepared-run continue --run-uri RUN_URI
  --executor local` through the configured launcher argv.
- Afterok scripts invoke `loom stage-job run --run-uri RUN_URI --stage STAGE
  --executor local` through the configured launcher argv and never invoke
  `loom stage run`.
- Scripts render deterministic `#SBATCH` directives, trusted prelude lines, and
  shell-quoted command bodies; generated output is stable in tests.
- Generated artifacts are written only under the store-resolved
  `slurm/submissions/<planning_id>/...` paths, and repeated dry-runs use
  distinct planning directories unless the caller explicitly supplies the same
  planning ID.
- Manifests round-trip through the Phase 3 schema and record dry-run facts,
  planned scripts, wrapper logs, command argv, resource/directive summaries,
  logical jobs, and dependencies without scheduler-submitted state.
- Secret-bearing resolved config values, resolver outputs, environment variable
  values, and raw adapter payloads are absent from scripts, manifests, and
  planning metadata by default.
- Import-boundary tests prove the new SLURM dry-run modules do not import
  `loom.cli`, `loom.config`, scheduler libraries, `subprocess`, or root package
  exports.

## Design Impact

- Maintainability: separates script rendering and artifact writing from CLI
  presentation and future live submission, keeping the SLURM adapter layered on
  Phase 3 typed contracts.
- Extensibility: gives v7 a concrete planned-submission artifact set to submit
  and annotate with scheduler facts without changing dry-run logical identity.
- Domain neutrality: all SLURM-specific script and directive behavior remains
  in `loom.pipeline.executors.slurm`; generic execution continues to own
  continuation semantics.
- Source-tree boundaries: stores own local path resolution, execution owns
  continuation commands, planning/runtime provide durable run facts, SLURM owns
  scheduler script shape, and CLI remains untouched.

## Future Compatibility

- V7 can add a scheduler command-runner layer that submits the scripts generated
  here and fills scheduler job IDs/results into an extension record while
  preserving v6 logical job keys and dry-run manifests.
- Phase 5 can wrap the Python planning API with `loom run --executor slurm-*`
  without duplicating script rendering or dependency graph logic.
- Later controller, container, retry, timeout, and cluster-aware preflight work
  can compose around the generated command argv and manifest records instead of
  replacing them.
- Future schema extensions should add fields rather than changing command argv
  targets, logical job key shape, or dry-run path layout.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Print scripts to stdout only | V6 requires durable run-directory artifacts that can be inspected and used by later live submission work. |
| Generate CLI-owned scripts in Phase 5 | Lower-level Python APIs are needed for deterministic tests and to keep CLI as presentation. |
| Invoke `loom run CONFIG` from single-job scripts | Replaying original config risks secret exposure and hides the prepared-run boundary. |
| Invoke the v5 `loom stage run` worker from afterok scripts | That worker is handoff-only and depends on a parent process for finalization. |
| Embed environment values or resolved config in generated scripts | The v6 secret boundary requires runtime environment resolution at job start, not persisted secret-bearing payloads. |
| Add a live scheduler command runner now | V7 owns `sbatch`, job IDs, scheduler state, polling, and partial submission behavior. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No live command-runner abstraction | Phase 4 is dry-run artifact generation only, and a live runner would expand scope into v7. | V7 starts submitting generated scripts. |
| Script builder supports trusted prelude lines but not shell validation of prelude semantics | Prelude is authored project code and may need site-specific setup that cannot be safely normalized. | A future untrusted-config boundary or preflight policy needs stricter prelude linting. |
| Local artifact writing is the only required store behavior | V6 default validation is cluster-free and local-run-store based. | Remote stores or cross-cluster submission become in scope. |

## Reviewability

- Expected PR size and shape: moderate SLURM-adapter PR with script builder,
  dry-run planner, artifact writer, and focused tests; no CLI, scheduler
  process calls, job IDs, or broad runtime changes.
- Files and areas to inspect: `src/loom/pipeline/executors/slurm/`, package
  import tests, new unit tests for script/planner behavior, SLURM manifest
  contract tests, and local run-store integration tests.
- Scope-control checks: no imports from `loom.cli` in lower layers; no `sbatch`,
  `squeue`, `sacct`, or `scancel`; no scheduler status/job ID fields beyond
  absent/null manifest fields; no mutation of continuation command behavior; no
  local-store path walking; no Phase 5 CLI parser or preflight output changes.

## Implementation Steps

1. Add focused script-builder records/helpers for generated SBATCH directives,
   trusted prelude lines, `shlex.quote` command rendering, and per-job script
   content.
2. Add dry-run planning APIs that consume persisted run plan/prepared-run state,
   `SlurmOptions`, resource mappings, and Phase 3 path helpers to build
   single-job and afterok `SlurmPlannedSubmission` records.
3. Add artifact-writing behavior that writes scripts, planning metadata, and
   manifests through store-resolved generated artifact paths and returns typed
   result data.
4. Add dependency graph construction for afterok logical jobs using planned
   `RUN` stages and `StagePlan.upstream_stages` from
   `ExecutionPlan.ordered_stage_plans`.
5. Add package, unit, contract, and integration coverage, then run targeted
   suites before PR preparation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`,
  `tests/package/test_public_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: SLURM script/planner APIs remain
  importable without scheduler dependencies; package exports stay import-light;
  lower layers do not import `loom.cli`, `loom.config`, scheduler libraries, or
  `subprocess`; no root `loom.__init__` export or optional SLURM dependency is
  introduced.

### Unit Suite

- Status: required
- Expected paths: new
  `tests/unit/loom/pipeline/executors/slurm/test_slurm_scripts.py`, new
  `tests/unit/loom/pipeline/executors/slurm/test_slurm_planner.py`, and updates
  to existing SLURM option/resource/manifest tests as needed
- Required assertions or deferral reason: SBATCH directive ordering; generated
  job names; stdout/stderr path directives; dependency directive rendering;
  shell quoting for argv entries with whitespace/shell metacharacters; trusted
  prelude placement; single-job command body; afterok command body; rejection
  of `loom stage run` as a generated target; chain/fan-in/fan-out/diamond
  logical dependencies from `StagePlan.upstream_stages`; repeated planning ID
  behavior; script content determinism; no environment values or raw adapter
  payloads in rendered output; no direct string command assembly bypassing
  `SlurmCommandArgv`.

### Contract Suite

- Status: required
- Expected paths: update `tests/contracts/test_slurm_manifest_contract.py` and
  add a focused script/planning contract test if public result models are added
- Required assertions or deferral reason: generated manifests remain
  schema-versioned Phase 3 plain data; planned jobs include stable script/log
  relative paths and generated command argv; dependencies use logical job keys
  and `afterok`; scheduler job IDs/status/state remain absent or null; dry-run
  planning result serialization is stable if exposed.

### Integration Suite

- Status: required
- Expected paths: new
  `tests/integration/pipeline/test_slurm_dry_run_planning.py` or equivalent
  focused local-run-store coverage
- Required assertions or deferral reason: single-job and afterok planning read
  a prepared local run, write scripts/planning metadata/manifest under
  `slurm/submissions/<planning_id>/...`, return store-resolved paths, preserve
  manifest round trips, keep paths under the run directory, use
  `atomic_write_text`/`atomic_write_json` behavior, and avoid local store
  internals.

### E2E Suite

- Status: deferred
- Expected paths: none in Phase 4
- Required assertions or deferral reason: Phase 4 exposes Python APIs only.
  Public `loom run --executor slurm-* --dry-run` behavior begins in Phase 5.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: Phase 4 is deterministic, local, and
  cluster-free; no real SLURM, remote-store, container, or cluster acceptance
  suite applies.

## Risks

- Dependency extraction from persisted plans can couple to private plan shape or
  scheduler assumptions; mitigate by using only `ExecutionPlan.from_dict`,
  `ordered_stage_plans`, `StagePlan.action`, and `StagePlan.upstream_stages`,
  and stopping if required safe fields are unavailable.
- Command assembly can be duplicated or drift from Phase 3 helpers; mitigate by
  using `build_single_job_command_argv` and `build_stage_job_command_argv` as
  the only generated command constructors.
- Shell rendering can become stringly typed; mitigate by rendering only from
  `SlurmCommandArgv`, `SlurmOptions`, and `SlurmSbatchDirective` records with
  `shlex.quote`.
- `extra_sbatch` can accidentally bypass generated or modeled directive
  validation; mitigate by using `SlurmOptions` and `build_sbatch_directives`
  rather than accepting raw directive strings.
- Artifact writing can regress into path walking; mitigate by resolving paths
  through `resolve_slurm_generated_artifact_path` and writing only through
  `atomic_write_text`/`atomic_write_json`.
- Manifest and script metadata can drift; mitigate by generating both from the
  same planned job records and testing round trips.
- Secret leaks can enter through convenience debug metadata; mitigate with
  explicit deny-by-default planning metadata and tests that include synthetic
  secret-like environment/config values.
- Repeated dry-runs can overwrite artifacts if planning IDs are unstable;
  mitigate with distinct default planning IDs and deterministic supplied-ID
  behavior in tests.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import.py tests/package/test_public_api.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/executors/slurm/test_slurm_scripts.py tests/unit/loom/pipeline/executors/slurm/test_slurm_planner.py tests/unit/loom/pipeline/executors/slurm/test_slurm_options.py tests/unit/loom/pipeline/executors/slurm/test_slurm_resources.py tests/unit/loom/pipeline/executors/slurm/test_slurm_manifest.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_slurm_manifest_contract.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_slurm_dry_run_planning.py tests/integration/pipeline/test_slurm_model_store_paths.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Do not start implementation until the expanded-path refine pass completes in
  this artifact. The refine pass is now complete.
- Safe implementation slices: script rendering first, dry-run
  planned-submission construction from public persisted state second, artifact
  writing third, dependency graph coverage fourth, tests throughout.
- Decisions the executor must not revisit: no CLI wiring, no live scheduler
  calls, no scheduler job IDs or fake submitted status, no changes to
  continuation command spellings, no `loom stage run` generated afterok
  scripts, no shell lifecycle logic, no path walking outside store helpers, no
  unredacted config/env persistence, no `extra_sbatch` bypass, and no generic
  wall-time resource.
- Conditions that require stopping for the manager: persisted plan state is
  insufficient to derive `RUN` stages and dependencies safely; script generation
  requires changing Phase 2 continuation commands; artifact writing requires
  importing local-store internals; manifests need raw scheduler or adapter
  payloads; required package/unit/contract/integration tests cannot run for a
  non-environmental reason.

## Refinement And Review Budget Status

- Phase execution plan refinement: used; expanded-path refine pass completed on
  2026-05-08
- Phase implementation refinement: used; expanded-path implementation
  refinement pass completed on 2026-05-08. The pass reviewed the Phase 4 SLURM
  package implementation, touched tests, and phase artifact against the
  finalized scope. No product or test defect was found; only this phase artifact
  was updated to record the used pass and validation evidence.
- PR review: used; automated phase review found no blocking findings
- Blocker resolution: 0/3 used; no blocker-resolution pass has been consumed
  for Phase 4

## Completion Notes

- Draft plan: completed in this draft pass and committed with a `plan:` commit.
- Refinement summary: completed on 2026-05-08; tightened Phase 4 around SLURM
  package-only implementation, Phase 3 model reuse, public persisted
  plan/prepared-run reads, store-owned generated artifact writes, dedicated
  `shlex.quote` rendering, import-boundary restrictions, and focused test
  obligations.
- Implementation summary: completed on 2026-05-08. Added SLURM-only rendering,
  artifact writing, and dry-run planning APIs for deterministic single-job and
  afterok script artifacts. The planner reads `RunStore.read_plan` and
  `RunStore.read_prepared_run`, parses `ExecutionPlan.from_dict` and
  `PreparedRunRecord.from_dict`, uses `ExecutionPlan.ordered_stage_plans`,
  `StagePlan.action`, and `StagePlan.upstream_stages` for afterok jobs, and
  writes scripts, manifest, and secret-safe planning metadata under
  `slurm/submissions/<planning_id>/...` through store-owned path helpers and
  atomic store writes. Generated commands use the Phase 3 continuation argv
  helpers and render through `shlex.quote`; no CLI wiring, live scheduler calls,
  scheduler IDs, or generic continuation changes were added.
- Test summary: added package/import-boundary coverage for new SLURM dry-run
  modules, unit coverage for script rendering and single-job/afterok planning,
  contract coverage for planning-result serialization stability, and
  integration coverage for local run-store artifact writing and manifest
  round-trips.
- Validation summary: targeted phase validation passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import.py tests/package/test_public_api.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/executors/slurm/test_slurm_scripts.py tests/unit/loom/pipeline/executors/slurm/test_slurm_planner.py tests/unit/loom/pipeline/executors/slurm/test_slurm_options.py tests/unit/loom/pipeline/executors/slurm/test_slurm_resources.py tests/unit/loom/pipeline/executors/slurm/test_slurm_manifest.py tests/contracts/test_slurm_manifest_contract.py tests/integration/pipeline/test_slurm_dry_run_planning.py tests/integration/pipeline/test_slurm_model_store_paths.py`
  passed with 87 tests. Static targeted checks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/executors/slurm tests/unit/loom/pipeline/executors/slurm/test_slurm_scripts.py tests/unit/loom/pipeline/executors/slurm/test_slurm_planner.py tests/contracts/test_slurm_manifest_contract.py tests/integration/pipeline/test_slurm_dry_run_planning.py tests/package/test_import_boundaries.py`
  and `UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/executors/slurm tests/unit/loom/pipeline/executors/slurm/test_slurm_scripts.py tests/unit/loom/pipeline/executors/slurm/test_slurm_planner.py tests/contracts/test_slurm_manifest_contract.py tests/integration/pipeline/test_slurm_dry_run_planning.py`.
- Implementation refinement summary: completed on 2026-05-08. Reviewed the
  current diff and commits `4316c6d`, `d50bf20`, and `b7fed75` for Phase 4
  scope constraints: Phase 3 argv helpers and `shlex.quote` rendering,
  store-owned generated artifact paths with atomic writes, public persisted
  plan/prepared-run reads, logical afterok dependencies from
  `ExecutionPlan.ordered_stage_plans` and `StagePlan.upstream_stages`,
  dry-run-only manifests/metadata, and forbidden import/live scheduler
  boundaries. No code or test patch was needed. Re-ran the targeted pytest
  command above during the refinement pass; it passed with 87 tests.
- PR preparation summary: completed on 2026-05-08. Inspected the final diff
  against `develop` and confirmed it is Phase 4 only: SLURM package script
  rendering, dry-run planning, artifact writing, package/unit/contract/
  integration tests, and phase artifacts; no CLI executor selection, preflight
  presentation, live scheduler calls, scheduler job IDs, submitted status, or
  future Phase 5/7 work was added. Added
  `docs/phases/slurm-dry-run-scripts-pr-body.md` and opened PR #85 against
  `develop`.
- PR-prep validation summary: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr`
  passed Ruff, Pyright, default tests (`825 passed, 14 skipped, 8 deselected`),
  config-extra tests (`405 passed, 844 deselected`), and build.
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with overall
  `1249 passed, 0 failed, 0 errors, 11 skipped, 852 deselected`; suite summary
  was written to `build/test-summary.md`.
- PR verification summary: `gh pr view 85 --json
  baseRefName,headRefName,state,url,statusCheckRollup` returned
  `baseRefName=develop`, `headRefName=codex/slurm-dry-run-scripts`,
  `state=OPEN`, URL `https://github.com/samcantrill/loom/pull/85`, and CI
  `checks` pending.
- Stack maintenance: after the control checkout recorded Phase 4 as `pr_open`
  on `develop` with commit `a1a9ae8`, rebased
  `codex/slurm-dry-run-scripts` onto updated `develop` and force-pushed with
  lease; the PR remains a root phase PR targeting `develop`.
- Automated PR review: completed on 2026-05-08 with no blocking findings. The
  review confirmed the PR targets `develop`, stays inside Phase 4 scope, uses
  public persisted plan/prepared-run reads, derives logical afterok
  dependencies from `ExecutionPlan` and `StagePlan`, renders with
  `shlex.quote`, writes through store-owned generated artifact paths with
  atomic writes, and avoids CLI, live scheduler calls, job IDs, submitted
  state, and root exports.
- CI review evidence: GitHub CI `checks` passed on the reviewed post-rebase
  head; the managing agent will verify the final PR head before merge.
