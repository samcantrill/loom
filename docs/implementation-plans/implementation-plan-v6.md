# Implementation Plan v6: SLURM Script Planning

## Metadata

- Status: ready for phase implementation
- Related planning notes:
  `docs/implementation-plans/roadmap-v6-planning-notes.md`
- Related source docs:
  - `docs/implementation-plans/implementation-roadmap.md`
  - `docs/implementation-plans/implementation-plan-v4.md`
  - `docs/implementation-plans/implementation-plan-v5.md`
  - `docs/features/slurm.md`
  - `docs/features/config.md`
  - `docs/features/execution.md`
  - `docs/features/provenance.md`
  - `docs/features/fingerprints.md`
  - `docs/features/runtime-resources.md`
  - `docs/features/preflight.md`
  - `docs/features/cli.md`
  - `docs/features/run-store.md`
  - `docs/features/testing.md`
  - `docs/structure.md`
- Draft pass: complete on 2026-05-08 from confirmed roadmap v6 planning notes
- Refine pass: complete on 2026-05-08 from plan quality gate refinement
- Plan quality gate: passed on 2026-05-08 after initial review, one refinement
  pass, and confirmation review
- Blockers: none known for planning

## Goal

Implement the v6 SLURM dry-run planning layer for `loom`.

After v6, users can select SLURM single-job or afterok dry-run modes and inspect
deterministic run-directory artifacts: prepared-run metadata, SLURM scripts,
logical dependency edges, resource mappings, wrapper log paths, generated Loom
commands, and schema-versioned manifests. V6 must make scheduler integration
reviewable and testable without calling `sbatch` or recording fake submitted
state.

V6 also adds the generic execution continuation contracts that make submitted
executors consistent: a prepared whole-run continuation command for single-job
scripts and an execution-owned stage-job runner for afterok scripts. These are
generic execution surfaces, not SLURM-specific finalizers.

## Context

V4 provides normalized `RunOptions`, scheduler-neutral `ResourceRequest` and
`ResourceEntry` models, resolved per-stage runtime handoff data, executor
descriptors/capabilities, and safe `runtime.json` metadata. V5 provides the
handoff-only stage worker and serial subprocess executor. The v5 worker is
correct for parent-managed subprocess execution, where the parent runner owns
finalization, but it is not sufficient for future submitted afterok jobs that
will not have a live parent process.

The roadmap names v6 as the SLURM script planning and dry-run layer, with live
SLURM operations deferred to v7. The confirmed v6 planning notes refine that
scope in three important ways:

- SLURM dry-run scripts must call generic Loom continuation entry points rather
  than duplicating runner logic.
- Single-job scripts should invoke a prepared-run continuation command instead
  of replaying the original config CLI or reading an unredacted resolved config
  snapshot.
- Afterok scripts should invoke a generic execution-owned stage-job runner that
  finalizes one planned stage from run-store state.

The config and runtime docs also define a strong secret boundary. Artifact-safe
config records preserve unresolved resolver expressions and redacted summaries;
runtime metadata does not persist environment variable names or values by
default. V6 must not introduce a new secret leak through prepared-run payloads,
SLURM manifests, scripts, generated commands, `plan.json`, or stage metadata.

## Desired Outcome

When all phases are complete:

- `loom run CONFIG --executor slurm-single-job --dry-run` creates one
  single-allocation SLURM script plus a dry-run manifest under the run
  directory.
- `loom run CONFIG --executor slurm-afterok --dry-run` creates one script per
  planned `RUN` stage, logical afterok dependency records, and a dry-run
  manifest under the run directory.
- Selecting either SLURM executor without `--dry-run` fails clearly because
  live submission belongs to v7.
- Generated scripts use deterministic SBATCH directives, standard-library shell
  quoting, structured launcher argv, trusted prelude lines, and stable wrapper
  log paths.
- Single-job scripts invoke
  `loom prepared-run continue --run-uri RUN_URI --executor local` through the
  structured launcher argv by default.
- Afterok scripts invoke
  `loom stage-job run --run-uri RUN_URI --stage STAGE --executor local` through
  the same launcher argv by default.
- Dry-run manifests record schema version, run URI, SLURM mode, dry-run flag,
  planning ID, created time, plan path, script paths, wrapper log paths,
  planned logical job keys, dependency job keys, generated command argv,
  resource summaries, and SLURM options.
- Scheduler job IDs, raw job IDs, dependency job IDs, submitted status, and
  scheduler state are absent or null in v6.
- Prepared-run and stage-job continuation read only durable run-store state,
  validate the persisted plan and metadata, prevent recursive submitted
  executor selection, resolve required environment values from the process
  environment, and fail before user stage code when required handoff state or
  upstream dependency state is missing.
- Unredacted resolved config values, resolver outputs, environment variable
  values, and raw adapter payloads are not persisted by default in generated
  scripts, manifests, config snapshots, or prepared-run metadata.
- Missing `sbatch` is warning or informational preflight output in v6.
- Default tests are deterministic, local, synthetic, cluster-free, and require
  no optional scheduler dependency.

## Non-Goals

- No live `sbatch` submission.
- No scheduler job ID parsing, status polling, `squeue`, `sacct`, `scancel`, or
  partial live-submission recovery.
- No scheduler `SUBMITTED` state, fake job IDs, or stage status updates that
  imply queued scheduler work.
- No controller mode, job arrays, MPI orchestration, interactive allocations,
  advanced `srun`, automatic retries, timeout enforcement, cleanup, or
  retention policy.
- No Docker, Apptainer, Singularity, or other container command composition.
- No remote run stores, remote artifact synchronization, cross-cluster
  submission, plugin discovery, run catalogs, bundles, sweeps, dashboards, or
  domain-specific cluster behavior.
- No cluster-specific auto-discovery of module systems, accounts, partitions,
  GPU syntax, accounting availability, or filesystem policy.
- No real cluster acceptance tests in the default suite.
- No generic wall-time resource field until more than one executor needs a
  shared wall-time concept.
- No full environment variable persistence.
- No sandboxing or untrusted-config execution boundary.

## Constraints

- Keep `loom` domain-neutral.
- Preserve the source-tree and import boundaries in `docs/structure.md`.
- Treat authored configs and script prelude lines as trusted project code.
- Keep SLURM-specific planning, option parsing, resource mapping, script
  building, manifest models, and SLURM-specific errors under
  `loom.pipeline.executors.slurm`.
- Keep generic prepared-run and stage-job continuation under
  `loom.pipeline.execution`.
- Keep CLI as an outer presentation layer. Lower layers must not import
  `loom.cli`.
- Use run-store APIs and path helpers where available instead of path-walking
  run directories from execution or executor code.
- Do not introduce a Python SLURM dependency or another heavyweight runtime
  dependency.
- Do not start phase execution until this plan passes the plan quality gate.
- Use `make validate-pr` before phase PR review and `make test-summary` before
  PR preparation.

## Design Principles

- Dry-run artifacts are durable contracts, not throwaway previews.
- Prepared execution is split from continuation: one path prepares the run, a
  separate generic path continues it from durable state.
- Submitted executors share execution-owned lifecycle semantics instead of
  implementing executor-specific finalization.
- Logical job keys are the v6 identity. Scheduler job IDs appear only after
  v7 live submission.
- Structured runtime/resources/options are the source of truth; raw strings are
  limited to validated trusted prelude lines and bounded `extra_sbatch`.
- Script generation is deterministic, quoted, and inspectable.
- Secret safety is a default contract. Persist artifact-safe/unresolved or
  redacted records, not resolved secret-bearing values.
- Runtime and SLURM choices are operational provenance by default, not semantic
  pipeline spec fields or fingerprint inputs unless an explicit future policy
  says otherwise.
- Default validation remains cluster-free.

## Key Design Choices

- Add prepared-run metadata records that are safe to persist and sufficient for
  whole-run continuation.
- Add or extract shared execution lifecycle helpers for input binding, output
  commit, provenance/failure commit, artifact-index updates, and status
  updates so submitted stage jobs can use the same semantics as local and
  subprocess runs.
- Add `loom prepared-run continue --run-uri RUN_URI --executor local` as the
  generic whole-run continuation command used by single-job scripts.
- Add
  `loom stage-job run --run-uri RUN_URI --stage STAGE --executor local` as the
  generic execution-owned stage-job runner command for one planned stage to
  durable completion from run-store state. `--attempt N` may be accepted for an
  exact prepared-attempt debug path, but generated SLURM afterok scripts use the
  stage-level form.
- Keep existing `loom stage run` as the v5 handoff-only worker command for
  parent-managed subprocess execution; do not change it into a self-finalizing
  submitted-job runner.
- Reject recursive submitted executor selection from continuation commands.
- Resolve required environment values from the process environment at job
  start and fail clearly before user stage code if required values are missing.
- Add SLURM dry-run models such as `SlurmMode`, `SlurmOptions`,
  `SlurmPlannedJob`, `SlurmPlannedSubmission`, `SlurmScriptBuilder`, and
  `SlurmResourceMapper`.
- Use structured `SlurmOptions` for common options:
  `partition`, `account`, `qos`, `constraint`, `nodes`, `ntasks`,
  `cpus_per_task`, `mem`, `mem_per_cpu`, `gres`, `time`, `prelude`,
  `extra_sbatch`, and related focused fields when implementation needs them.
- Reject unknown structured SLURM option fields.
- Use `extra_sbatch` as a validated mapping escape hatch only. Valueless flags
  use `true`; valued flags use strings. `false`, null, whitespace/control
  characters, duplicate flags, and conflicts with generated/modeled directives
  fail loudly.
- Do not allow `extra_sbatch` to override generated job names, output/error
  paths, dependency directives, or modeled resource directives such as CPU,
  memory, GRES, or time.
- Keep `SlurmOptions.time` SLURM-specific in v6 rather than adding generic
  wall-time resources.
- Map generic `cpu`, `memory`, and `gpu` resource entries to SBATCH defaults,
  while allowing explicit structured SLURM options only when the override is
  unambiguous.
- Use structured launcher argv for generated Loom commands, defaulting to
  `["loom"]`. The launcher may be configured as sequences such as
  `["uv", "run", "loom"]` or `["python", "-m", "loom.cli"]`.
- Keep prelude as trusted shell setup, not as the command launcher model.
- Write each dry-run attempt under a distinct directory such as
  `slurm/submissions/<planning_id>/...` using a store-owned path-safe helper for
  run-scoped generated artifacts. SLURM owns the relative layout; the store owns
  resolving it under the run directory and rejecting unsafe paths.
- Use deterministic logical job keys such as `pipeline` and
  `stage:<stage_name>`, with `dependency_job_keys` and dependency type
  `afterok` in v6 manifests.
- Keep scheduler job IDs absent or null in v6 manifests.
- CLI output reports counts and paths. It does not print full generated
  scripts by default.

## Conflicts And Tradeoffs

- Generic execution foundation vs smaller SLURM diff: v6 accepts prepared-run
  and stage-job continuation work before SLURM models so generated scripts have
  stable generic targets.
- Inspectability vs live usefulness: v6 creates durable planned submissions but
  intentionally does not call `sbatch`, record job IDs, or alter status as if
  jobs were submitted.
- Portability vs strictness: `extra_sbatch` keeps uncommon site options
  possible, but only inside a validated mapping that cannot override modeled
  directives silently.
- Secret safety vs replayability: v6 rejects unredacted resolved-config command
  sources, even though they can be simpler to replay, because resolved configs
  and resolver outputs may contain secrets.
- Logical job keys vs scheduler placeholders: v6 uses logical keys because job
  IDs do not exist until live submission; v7 owns the mapping from logical keys
  to scheduler job IDs.
- CLI stability vs command naming: `loom prepared-run continue` is explicit and
  reviewable, while a shorter overloaded `loom run` form would hide the
  prepared-run boundary.
- Stage worker compatibility vs submitted-job clarity: v6 keeps
  `loom stage run` as the v5 parent-managed worker handoff and adds the separate
  `loom stage-job run` command for self-finalizing submitted jobs, avoiding a
  silent behavior change in the existing worker command.
- Tests vs cluster realism: v6 favors pure local determinism and defers real
  cluster evidence to v7 or later opt-in suites.

## Maintainability Assessment

Maintainability depends on keeping the new submitted-executor behavior as a
thin adapter over existing Loom planning, execution, runtime, and store
contracts. Execution owns continuation and lifecycle semantics. SLURM owns only
SLURM option/resource mapping, script rendering, logical planned jobs, and
dry-run manifests. CLI adapts user input to public APIs and presents results.

The biggest maintainability risk is creating two runner implementations: one in
`PipelineRunner` and another inside SLURM. The plan prevents that by requiring
generic prepared-run and stage-job continuation before SLURM script generation.

The second risk is secret leakage through a new persistence path. V6 treats
prepared-run metadata, manifests, generated commands, stage fingerprints, and
plan records as payloads that must be audited or rejected when they would carry
secret-bearing resolved values.

Secret-boundary test obligations are assigned by persistence surface:

| Surface | Phase owner | Required evidence |
| --- | --- | --- |
| Prepared-run metadata | Phase 1 | Unit and contract tests prove payloads are artifact-safe or rejected. |
| `plan.json` and stage fingerprints/metadata | Phase 1 with Phase 6 regression | Unit/contract tests define allowed fields; integration/e2e hardening proves resolver outputs and environment values are absent. |
| Runtime and config records | Phase 1 with existing config/runtime coverage and Phase 6 regression | Integration checks preserve artifact-safe config snapshots and runtime metadata without environment values. |
| SLURM manifests and generated command argv | Phases 3-4 with Phase 6 regression | Model/script contract tests prove schema output contains logical metadata, not resolved secrets or raw adapter payloads. |
| Generated scripts, wrapper log paths, and SLURM options | Phases 3-4 with Phase 6 regression | Unit/integration/e2e tests prove Loom-generated content omits environment values; authored prelude remains trusted project code. |
| Raw adapter payloads | Phases 1 and 3 | Unit tests reject persistence unless converted to typed, artifact-safe summaries. |

The phase order keeps review slices small: generic execution/store foundations,
generic CLI continuation, pure SLURM models, script/dry-run API generation,
CLI/preflight integration, and final e2e/docs hardening.

## Extensibility Assessment

V6 is the immediate base for v7 live SLURM operations:

- V7 can add `sbatch`, job ID parsing, partial submission records, status, and
  cancellation on top of v6 planned submissions.
- V7 can map v6 logical job keys to scheduler job IDs without changing the
  dry-run graph model.
- Future container phases can wrap the same prepared-run and stage-job
  continuation commands inside container launchers.
- Later reliability phases can add retry, timeout, cleanup, and stronger
  locking while reusing shared lifecycle helper boundaries.
- Later executor/plugin phases can add command runners or adapter-specific
  resource mappers without moving CLI or execution ownership.

The plan deliberately avoids generic wall-time, real cluster tests, controller
mode, job arrays, containers, and remote stores until their own roadmap
versions define those contracts.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No live scheduler operations | V6 is dry-run script planning by design. | v7 SLURM operations starts. |
| No generic wall-time resource | Current runtime docs defer generic wall-time; v6 only needs SLURM `time`. | Another executor needs wall-time or v16 timeout policies define a generic field. |
| No real cluster acceptance tests | Default tests must be deterministic and cluster-free. | v7 live operations or a later opt-in acceptance suite. |
| Stage job runner requires lifecycle helper extraction | Current parent runner commit/input-binding logic is private to `PipelineRunner`. | V6 Phase 1 and Phase 2 implementation. |
| Secret-safe prepared-run handoff requires payload audit | Current persisted plans and stage fingerprints may carry resolved stage values even when config snapshots are artifact-safe. | V6 Phase 1 implementation must define safe persisted payloads or fail loudly when a payload would persist secret-bearing resolved values. |
| Strong submitted-job locking is deferred | V6 dry-run and cluster-free continuation do not need multi-coordinator locking beyond existing run-store safety. | Live submission, parallel submitted jobs, retries, or duplicate-worker recovery require stronger coordination. |
| Raw list-style `extra_sbatch` is deferred | Validated mapping covers reviewable uncommon flags while avoiding raw SBATCH shadow syntax. | A real site need cannot be expressed by validated mapping entries. |

## Plan Quality Gate

- Status: passed
- Required reviewer: `loom_plan_reviewer`
- Required before: creating any v6 phase execution plan or starting Phase 1
  implementation
- Review focus:
  - whether prepared-run continuation and stage-job continuation are generic
    execution contracts rather than SLURM-specific finalizers;
  - sufficiency of the secret-safe persistence boundary across prepared-run
    metadata, plans, stage fingerprints, manifests, generated commands, config
    records, and runtime metadata;
  - correctness of the phase order: generic execution foundation before SLURM
    model/script/CLI work;
  - stability of `loom prepared-run continue --run-uri RUN_URI --executor local`
    as a public CLI/API continuation surface;
  - consistency between logical job keys in v6 and scheduler job IDs in v7;
  - strictness and portability of `SlurmOptions`, resource mapping, structured
    launcher argv, prelude, and `extra_sbatch`;
  - preservation of CLI, execution, planning, runtime, store, diagnostics, and
    SLURM import boundaries;
  - adequacy of package, unit, contract, integration, e2e, and opt-in test
    obligations;
  - clarity of deferred v7 live submission, status, cancellation, partial
    submission, controller, container, remote-store, and real-cluster work.
- Loop budget:
  - Initial review: used on 2026-05-08; blocking findings were exact stage-job
    command shape and self-finalizing lifecycle contract, with medium findings
    on secret-surface coverage and store-owned dry-run paths.
  - Gate refinement pass: used on 2026-05-08; refined this plan to fix the
    command shape, lifecycle acceptance criteria, secret-boundary test matrix,
    and store-owned path-helper requirement.
  - Confirmation review: used on 2026-05-08; no blocking findings remained.
- Current gate result: passed. Phase implementation may begin.

## Phased Implementation

### Phase 1 - Prepared-Run And Lifecycle Foundations

Status: merged
Branch: `codex/slurm-prepared-run-foundations`
PR: https://github.com/samcantrill/loom/pull/82

Goal:

- Define the generic, secret-safe prepared-run state and shared execution
  lifecycle helpers needed by whole-run and one-stage continuation.

Scope:

- Add prepared-run metadata records under execution/run-store boundaries.
- Define what persisted prepared-run payloads may contain and fail loudly when
  a payload would require unredacted resolved config, resolver outputs,
  environment values, or raw adapter payloads.
- Extract or add shared execution lifecycle helpers for input binding, output
  commit, provenance/failure commit, artifact-index updates, and status updates
  without introducing SLURM-specific behavior.
- Add a path-safe run-store helper for resolving run-scoped generated artifact
  paths so later SLURM code does not path-walk run directories directly.

Out of scope:

- No SLURM models, scripts, manifests, `sbatch`, CLI executor selection, or
  live scheduler behavior.

Acceptance criteria:

- Prepared-run metadata can be written/read through public execution/store APIs.
- Secret-bearing resolved values are absent from prepared-run payloads or
  rejected with structured errors.
- Shared lifecycle helpers preserve existing local/subprocess behavior.
- The implementation does not add SLURM-specific code paths to generic
  execution lifecycle helpers.
- Run-scoped generated-artifact paths can be resolved through a store-owned
  helper that rejects unsafe relative paths without knowing SLURM semantics.

Test expectations:

- Package: execution and store exports remain importable without optional SLURM
  dependencies.
- Unit: prepared-run schema validation, payload safety checks, lifecycle helper
  success/failure paths, generated-artifact path safety.
- Contract: run-store read/write behavior for prepared-run metadata and
  run-scoped generated-artifact path resolution.
- Integration: existing local and subprocess execution tests still pass.
- E2E: not required beyond existing local/subprocess coverage.
- Opt-in: none.

Design impact:

- Establishes the generic execution handoff foundation that keeps submitted
  executors consistent.

Future compatibility:

- Enables SLURM, containers, and later remote executors to share continuation
  semantics.

Alternatives rejected:

- SLURM-specific finalization, resolved-config command source, and executor
  duplication of runner commit logic.

Debt introduced:

- Stronger locking for concurrent submitted stage jobs remains deferred unless
  implementation discovers an immediate correctness blocker.

Reviewability:

- Review is concentrated on execution/store contracts and invariant-preserving
  lifecycle extraction.

Notes:

- Preserve the v5 handoff-only worker for parent-managed subprocess execution.

Completion summary:

- PR opened on 2026-05-08 against `develop`.
- PR merged on 2026-05-08 with squash merge commit
  `f78ea8ee2a4f094870b13763fef93fb508afed82`.
- Implemented schema-versioned prepared-run metadata as a generic
  execution/store sibling record, local `prepared_run.json` persistence,
  store-owned safe-relative generated artifact path resolution, and narrow
  lifecycle helper extraction for input binding and artifact-index updates.
- Preserved the v5 `loom stage run` handoff-only worker contract and avoided
  Phase 2 continuation CLI, SLURM models/scripts, scheduler state, and live
  submission behavior.
- Validation and review: automated manager review passed; GitHub CI `checks`
  passed on PR #82; local `make validate-pr` passed; `make test-summary` passed
  with 1170 passed, 0 failed, 0 errors.
- Stack maintenance: no successor branch depended on Phase 1 at merge time; the
  PR branch was eligible for deletion.
- Follow-up for Phase 2: build continuation commands on the prepared-run
  metadata and lifecycle helper foundation.

### Phase 2 - Generic Continuation Commands

Status: merged
Branch: `codex/slurm-continuation-commands`
PR: https://github.com/samcantrill/loom/pull/83

Goal:

- Implement generic CLI/API continuation entry points for prepared whole-run
  execution and execution-owned one-stage jobs.

Scope:

- Add `loom prepared-run continue --run-uri RUN_URI --executor local`.
- Add
  `loom stage-job run --run-uri RUN_URI --stage STAGE --executor local` for one
  planned stage to durable completion. The command may accept `--attempt N` for
  exact prepared-attempt debugging, but generated submitted-job scripts use the
  stage-level form.
- Ensure continuation opens an existing run, validates the persisted plan and
  prepared metadata, prevents recursive submitted executor selection, resolves
  required environment values from process environment, and fails before user
  stage code when required handoff state is missing.
- Ensure stage-job continuation validates that the target stage exists in the
  persisted plan with action `RUN`, verifies upstream dependencies are
  successful or reusable before user code starts, runs only the targeted stage,
  and uses the shared lifecycle helpers for success and failure finalization.

Out of scope:

- No generated SLURM scripts, scheduler dependency planning, or live scheduler
  operations.
- No change to the v5 `loom stage run` handoff-only worker contract.

Acceptance criteria:

- Whole-run continuation validates prepared metadata, executor choice,
  persisted plan identity, and runtime state, then either executes from an
  explicitly safe prepared payload or returns structured insufficient-state
  failure before user code when no safe replay payload exists.
- Stage-job continuation can finalize one planned `RUN` stage from run-store
  state without a parent process.
- Stage-job success writes the same durable output records, provenance,
  artifact-index updates, logs, and final stage status semantics as the parent
  runner for the targeted stage.
- Stage-job failure writes the same durable failure record and failed stage
  status semantics as the parent runner for the targeted stage.
- Stage-job continuation mutates only the targeted stage and run-level status.
  It marks the run failed when the targeted stage fails, marks the run succeeded
  only after it can verify all planned stages are terminal success/reuse/skip,
  and otherwise leaves the run running.
- Missing prepared metadata, incompatible plans, unresolved environment
  requirements, and recursive submitted executors fail clearly.
- CLI text and JSON output use schema `loom.cli.stage_job.run.v1` for
  stage-job results and existing CLI structured-error conventions for failures.

Test expectations:

- Package: CLI command registration remains import-light.
- Unit: command argument parsing, continuation validation, recursive-executor
  rejection, missing environment behavior, upstream-dependency validation, and
  run-level terminal status rules.
- Contract: command result/error envelopes match CLI conventions; stage-job
  success/failure artifacts match parent-runner lifecycle semantics.
- Integration: prepared-run validation and stage-job continuation against a
  local run store, including stage-job success and failure paths that do not use
  `loom stage run`.
- E2E: public continuation parser and structured-failure smoke coverage, with
  successful stage-job finalization covered in integration.
- Opt-in: none.

Design impact:

- Separates "prepare a run" from "execute a prepared run" and makes the
  submitted-job contract generic.

Future compatibility:

- SLURM single-job, SLURM afterok, containers, and later submitted executors can
  invoke stable Loom continuation commands.

Alternatives rejected:

- Overloading `loom run CONFIG`, reusing v5 handoff-only `loom stage run` for
  finalizing submitted jobs, and requiring a live parent process.

Debt introduced:

- None for command naming; `loom stage-job run` is the fixed v6 generated-script
  target unless the confirmation plan review finds a blocking parser issue.

Reviewability:

- Review can focus on CLI/API behavior and continuation invariants before any
  SLURM adapter code exists.

Notes:

- The prepared-run command spelling is fixed for this plan unless the plan
  quality gate finds a blocking parser issue.
- `loom stage run` remains the parent-managed subprocess worker and must not be
  used by generated afterok scripts.

Completion summary:

- Phase execution plan:
  `docs/phases/slurm-continuation-commands.md`.
- PR #83 opened against `develop` from
  `codex/slurm-continuation-commands` on 2026-05-08.
- PR #83 merged into `develop` on 2026-05-08 with squash merge commit
  `8386e05e8f5bb18de2ded5cd3fd8380abf6c2cfb`.
- Implemented generic execution-owned continuation APIs for prepared-run
  validation and self-finalizing stage jobs, import-light
  `loom prepared-run continue` and `loom stage-job run` CLI groups, and narrow
  shared lifecycle helpers used by both the parent runner and stage-job runner.
- Automated PR review found two blocking stage-job lifecycle gaps; blocker
  resolution pass 1/3 fixed missing-run-status ordering before reconstruction
  and self-finalization for target-construction failures.
- Preserved `loom stage run` as the v5 handoff-only worker path and kept Phase
  3 SLURM scripts, manifests, scheduler state, and dry-run executors out of the
  diff.
- Whole-run prepared continuation intentionally returns structured
  `execution.prepared_run.insufficient_prepared_state` before user code unless a
  future safe replay payload is added.
- Final merge verification: before merge, `gh pr view 83 --json
  baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup` returned
  `baseRefName=develop`, `headRefName=codex/slurm-continuation-commands`,
  `state=OPEN`, no merge commit yet, and CI check `checks` completed with
  `SUCCESS`.
- Final local validation: `make validate-pr` passed in the phase worktree after
  blocker resolution; `make test-summary` passed with overall `1190 passed, 11
  skipped, 793 deselected`.
- Stack cleanup: no successor branches depended on
  `codex/slurm-continuation-commands`; branch deletion was requested during
  squash merge and remaining local worktree/branch cleanup is recorded in the
  manager handoff.

### Phase 3 - SLURM Models, Options, Resources, And Manifest Schema

Status: merged
Branch: `codex/slurm-dry-run-models`
PR: https://github.com/samcantrill/loom/pull/84

Goal:

- Add the structured SLURM dry-run vocabulary and mapper layer without script
  generation or CLI wiring.

Scope:

- Add `SlurmMode`, `SlurmOptions`, structured `extra_sbatch` validation,
  generated-command launcher argv, resource-to-SBATCH mapper, logical job keys,
  planned dependency records, planned job records, and planned submission
  manifest models under `loom.pipeline.executors.slurm`.
- Consume the Phase 1 store-owned generated-artifact path helper for
  `slurm/submissions/<planning_id>/...`; do not add adapter-local run-directory
  path walking.

Out of scope:

- No generated shell scripts, CLI integration, live command runner, job ID
  parsing, status, cancellation, or real scheduler calls.

Acceptance criteria:

- Structured option parsing rejects unknown fields and conflicts.
- `extra_sbatch` accepts only validated mapping entries and cannot override
  generated/modeled directives.
- Resource conflicts fail with structured, path-aware errors.
- Manifest models round trip with job IDs absent/null and dependencies
  expressed by logical job keys.
- SLURM planning code can request safe run-scoped dry-run paths without
  importing local-store internals or constructing absolute run-directory paths.

Test expectations:

- Package: SLURM module imports without optional dependencies.
- Unit: option parsing, extra SBATCH validation, resource mapping, logical
  dependency records, manifest round trips.
- Contract: public model serialization stays deterministic and schema-versioned.
- Integration: model/store path helper interaction for the planned submission
  directory.
- E2E: none.
- Opt-in: none.

Design impact:

- Establishes the durable dry-run schema that v7 live submission will extend.

Future compatibility:

- Live submission can add scheduler job IDs and command results without
  replacing logical dependency identity.

Alternatives rejected:

- Stringly typed SBATCH dictionaries, fake job IDs, raw `#SBATCH` line lists,
  and modeling every SLURM option in v6.

Debt introduced:

- Some site-specific options remain in `extra_sbatch`; promote them later only
  when repeated usage justifies typed fields.

Reviewability:

- Pure model/mapper phase with deterministic unit coverage and no scheduler
  side effects.

Notes:

- Raw list-style `extra_sbatch` from the feature doc is deferred unless the
  validated mapping cannot express a concrete site need.

Completion summary:

- Phase execution plan:
  `docs/phases/slurm-dry-run-models.md`.
- PR #84 opened against `develop` from `codex/slurm-dry-run-models` on
  2026-05-08.
- PR #84 merged into `develop` on 2026-05-08 with squash merge commit
  `01315a98967f7a85aaf4c8587fe878cfa89e2834`.
- Implemented pure, optional-dependency-free SLURM dry-run contracts under
  `loom.pipeline.executors.slurm`, including mode/options parsing,
  `extra_sbatch` validation, continuation argv models, resource-to-SBATCH
  mapping, logical job keys, planned dependencies, planned jobs, planned
  submissions, and generated-artifact path helpers.
- Automated PR review found two blocking Phase 3 contract gaps; blocker
  resolution pass 1/3 fixed mutually exclusive `mem`/`mem_per_cpu` handling,
  direct resource-mapping attribute rejection, and focused unit regressions.
- Kept generated scripts, CLI integration, live scheduler calls, submitted
  state, job ID assignment, and Phase 4 dry-run planning APIs out of scope.
- Final merge verification: before merge, `gh pr view 84 --json
  baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup` returned
  `baseRefName=develop`, `headRefName=codex/slurm-dry-run-models`,
  `state=OPEN`, no merge commit yet, and CI check `checks` completed with
  `SUCCESS`.
- Final local validation: after blocker resolution, `make validate-pr` passed
  Ruff, Pyright, isolated default tests (`811 passed, 14 skipped, 8
  deselected`), isolated config-extra tests (`405 passed, 830 deselected`),
  and build; `make test-summary` passed with overall `1235 passed, 11
  skipped, 838 deselected`.
- Stack cleanup: no successor branches depended on
  `codex/slurm-dry-run-models`; branch deletion was requested during squash
  merge and remaining local worktree/branch cleanup is recorded in the manager
  handoff.

### Phase 4 - SLURM Script Builders And Dry-Run Planning APIs

Status: merged
Branch: `codex/slurm-dry-run-scripts`
PR: https://github.com/samcantrill/loom/pull/85

Goal:

- Generate reviewable single-job and afterok SLURM dry-run artifacts from an
  existing Loom plan and prepared run state.

Scope:

- Build deterministic SBATCH scripts for single-job and afterok modes.
- Single-job scripts invoke prepared-run continuation through the structured
  launcher argv.
- Afterok scripts invoke
  `loom stage-job run --run-uri RUN_URI --stage STAGE --executor local` through
  the structured launcher argv and use logical dependency keys in manifests.
- Write dry-run manifests, scripts, wrapper log paths, and planning metadata
  under `slurm/submissions/<planning_id>/...` through the store-owned
  generated-artifact path helper.
- Preserve no-live-submission behavior: no `sbatch`, no submitted status, no
  fake job IDs.

Out of scope:

- No CLI executor selection, preflight presentation, live job ID parsing,
  scheduler polling, cancellation, or controller mode.

Acceptance criteria:

- Python APIs can generate single-job and afterok dry-run artifacts for a
  synthetic pipeline.
- Scripts are deterministic, shell-quoted, executable when practical, and do
  not embed environment values.
- Generated afterok argv targets `loom stage-job run`, never the v5
  handoff-only `loom stage run` worker.
- Afterok dependencies cover chain, fan-in, fan-out, and diamond DAG shapes.
- Repeated dry-runs write distinct planning directories.

Test expectations:

- Package: generated scripts require no optional scheduler dependency.
- Unit: script rendering, quoting, directive ordering, command body generation,
  dependency graph construction.
- Contract: manifest schema and generated command records are stable.
- Integration: dry-run artifact writing against a local run store.
- E2E: not yet through `loom run`; public API coverage is enough.
- Opt-in: none.

Design impact:

- Converts abstract dry-run records into the user-visible artifacts that v6 is
  meant to deliver.

Future compatibility:

- V7 can submit these generated scripts and fill in scheduler facts.

Alternatives rejected:

- Stdout-only script previews, mutable single manifest files, eager v5 worker
  request preparation, and embedded environment values.

Debt introduced:

- No scheduler command-runner abstraction is implemented until v7 needs live
  submission.

Reviewability:

- Review can inspect generated scripts and manifests from deterministic tests.

Notes:

- Generated scripts must call continuation commands, not reimplement
  execution lifecycle logic.

Completion summary:

- Phase execution plan:
  `docs/phases/slurm-dry-run-scripts.md`.
- PR #85 opened against `develop` from `codex/slurm-dry-run-scripts` on
  2026-05-08.
- PR #85 merged into `develop` on 2026-05-08 with squash merge commit
  `4ae86f1537357006d973cfee172c2c7f14bd8b65`.
- Implemented SLURM-only rendering, artifact writing, and dry-run planning APIs
  for deterministic single-job and afterok scripts. The planner reads persisted
  execution plans and prepared-run metadata through public store protocols,
  derives afterok dependencies from `ExecutionPlan.ordered_stage_plans` and
  `StagePlan.upstream_stages`, renders commands through Phase 3 argv helpers
  with shell quoting, and writes scripts, manifest, and secret-safe planning
  metadata under `slurm/submissions/<planning_id>/...` through store-owned path
  helpers and atomic writes.
- Automated PR review found no blocking findings; residual secret-surface
  hardening remains assigned to Phase 6.
- Kept CLI wiring, live scheduler calls, scheduler IDs/state, submitted state,
  and Phase 5/7 behavior out of scope.
- Final merge verification: before merge, `gh pr view 85 --json
  baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup` returned
  `baseRefName=develop`, `headRefName=codex/slurm-dry-run-scripts`,
  `state=OPEN`, no merge commit yet, and CI check `checks` completed with
  `SUCCESS`.
- Final local validation: `make validate-pr` passed Ruff, Pyright, isolated
  default tests (`825 passed, 14 skipped, 8 deselected`), isolated
  config-extra tests (`405 passed, 844 deselected`), and build;
  `make test-summary` passed with overall `1249 passed, 11 skipped, 852
  deselected`.
- Expanded-path implementation refinement was used and found no code or test
  blocker; blocker resolution budget remained unused.
- Stack cleanup: no successor branches depended on
  `codex/slurm-dry-run-scripts`; branch deletion was requested during squash
  merge and remaining local worktree/branch cleanup is recorded in the manager
  handoff.

### Phase 5 - CLI And Preflight Integration

Status: merged
Branch: `codex/slurm-cli-preflight`
PR: https://github.com/samcantrill/loom/pull/86

Goal:

- Expose SLURM dry-run planning through the public CLI and diagnostics surface.

Scope:

- Add `loom run CONFIG --executor slurm-single-job --dry-run`.
- Add `loom run CONFIG --executor slurm-afterok --dry-run`.
- Selecting either SLURM executor without `--dry-run` fails clearly.
- Text and JSON output report counts and paths without printing full scripts by
  default.
- Add SLURM preflight checks for profile shape, resource mapping support,
  shared/local run URI assumptions, safe script/log paths, launcher command
  shape, and optional `sbatch` availability as warning/info.

Out of scope:

- No live submission, status/cancel commands, real cluster acceptance tests, or
  fallback PR/merge workflow changes.

Acceptance criteria:

- CLI dry-run commands create the same artifacts as the Python API.
- Non-dry-run SLURM selection fails with a clear v7-deferred error.
- CLI output points to manifest/script directories and reports warnings.
- Preflight errors and warnings use stable check IDs.

Test expectations:

- Package: CLI remains import-light before command dispatch.
- Unit: CLI parsing/output envelopes, preflight check mapping, error messages.
- Contract: JSON result schema and warnings are stable.
- Integration: CLI dry-run generation against temporary run stores.
- E2E: small local config through both SLURM dry-run modes.
- Opt-in: none.

Design impact:

- Makes v6 user-visible while preserving CLI/lower-layer ownership boundaries.

Future compatibility:

- V7 can add live submission flags and job ID reporting without changing the
  dry-run output shape.

Alternatives rejected:

- CLI-owned script generation, blocking dry-run on missing `sbatch`, and
  printing full scripts as primary output.

Debt introduced:

- Status/cancel inspection remains deferred until live job IDs exist.

Reviewability:

- Review combines user-visible CLI behavior with targeted integration evidence.

Notes:

- CLI must call public SLURM dry-run APIs and must not build scripts directly.

Completion summary:

- Phase execution plan:
  `docs/phases/slurm-cli-preflight.md`.
- PR #86 opened against `develop` from `codex/slurm-cli-preflight` on
  2026-05-08 after the expanded-path implementation refinement pass.
- PR #86 merged into `develop` on 2026-05-08 with squash merge commit
  `2379e14a81304d2d48bc3dc7a28921cf2b8aef5b`.
- Implemented public SLURM dry-run CLI routing for explicit, config-resolved,
  and profile-resolved `slurm-single-job` and `slurm-afterok` selections.
- Added dry-run-only runtime capability descriptors, stable SLURM preflight
  check IDs, concise text/JSON output, default wrapper log-path pointers, and
  v7-deferred non-dry-run SLURM errors.
- Automated PR review found two blocking findings: stage-level SLURM adapter
  options were validated but not applied to generated artifacts, and default
  text output omitted wrapper log-path pointers. Blocker-resolution pass 1/3
  fixed both findings; manager verification found no remaining blocker.
- Final merge verification: before merge, `gh pr view 86 --json
  baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup` returned
  `baseRefName=develop`, `headRefName=codex/slurm-cli-preflight`,
  `state=OPEN`, no merge commit yet, and CI check `checks` completed with
  `SUCCESS`.
- Final local validation after blocker resolution: focused Phase 5 tests passed
  with 21 tests; CLI/diagnostics unit coverage passed with 28 tests;
  `make validate-pr` passed Ruff, Pyright, isolated default tests (`833
  passed, 15 skipped, 8 deselected`), isolated config-extra tests (`410
  passed, 853 deselected`), and build; `make test-summary` passed with overall
  `1263 passed, 11 skipped, 861 deselected`.
- Stack cleanup: no successor branches depended on
  `codex/slurm-cli-preflight`; the remote branch was deleted, the local
  worktree was removed, and stale local branch/tracking refs were pruned.

### Phase 6 - End-To-End Hardening And Documentation

Status: pr_open
Branch: `codex/slurm-dry-run-hardening`
PR: https://github.com/samcantrill/loom/pull/87

Goal:

- Close v6 with cluster-free end-to-end evidence, documentation updates, and
  compatibility checks across the generic continuation and SLURM dry-run
  surfaces.

Scope:

- Add final e2e coverage for single-job and afterok dry-runs with generated
  artifact inspection.
- Add regression coverage for the secret-boundary matrix: environment resolver
  outputs and environment values are not persisted in prepared-run metadata,
  `plan.json`, stage fingerprints/metadata, runtime/config records, SLURM
  manifests, generated argv/scripts, wrapper log paths, or typed SLURM options.
- Add fan-in/fan-out/diamond dry-run examples and docs.
- Update feature docs or implementation notes where v6 decisions supersede old
  resolved-config or v5 worker command examples.
- Record v7 handoff notes and remaining deferred work clearly.

Out of scope:

- No live cluster tests, `sbatch`, scheduler status/cancel, containers, job
  arrays, controller mode, or generic wall-time resources.

Acceptance criteria:

- Final validation covers both SLURM modes, continuation commands, secret-safe
  artifact boundaries, repeated dry-runs, and dependency shapes.
- Secret-boundary regression covers every surface assigned in the matrix, or the
  phase records an explicit accepted risk with a revisit trigger.
- Docs no longer recommend persisted unredacted resolved config as the SLURM
  command source.
- Remaining v7 handoff notes are explicit.

Test expectations:

- Package: full package validation expected.
- Unit: any gaps found during hardening.
- Contract: manifest/script command schema regression checks.
- Integration: repeated dry-run and secret-boundary checks.
- E2E: both public SLURM dry-run CLI modes.
- Opt-in: no real cluster coverage in v6.

Design impact:

- Ensures the v6 dry-run contract is documented and testable before live
  scheduler behavior is added.

Future compatibility:

- Leaves v7 with a clear, tested handoff for job ID parsing, submission,
  status, cancellation, and partial-submission recovery.

Alternatives rejected:

- Treating docs/e2e hardening as optional despite superseding older SLURM
  examples.

Debt introduced:

- Real cluster acceptance evidence remains deferred to v7 or later opt-in test
  suites.

Reviewability:

- Review focuses on final behavior evidence, documentation consistency, and
  whether any hidden live-submission behavior leaked into v6.

Notes:

- This phase should not broaden into live operations. It is a hardening and
  documentation closure phase for the dry-run contract.

Completion summary:

- Phase execution plan:
  `docs/phases/slurm-dry-run-hardening.md`.
- PR #87 opened against `develop` from `codex/slurm-dry-run-hardening` on
  2026-05-08 after final local validation.
- Implemented final public CLI e2e hardening for both SLURM dry-run modes using
  a diamond DAG, generated manifest/script/log/command inspection, repeated
  afterok dry-run evidence, and secret-boundary scanning across persisted run
  artifacts.
- Fixed SLURM dry-run preparation so persisted root `plan.json` is built from
  the composed config's artifact-safe unresolved pipeline view rather than
  resolved environment values. This preserves authored resolver expressions
  while avoiding resolver-output persistence.
- Updated SLURM, CLI, execution, pipeline, and preflight feature docs to
  describe the implemented v6 dry-run contract, generated `prepared-run` and
  `stage-job` command shapes, missing-`sbatch` warning behavior, and v7-deferred
  live submission/status/cancel/real-cluster work.
- Final local validation before PR opening: targeted Phase 6 suite passed with
  26 tests; focused Ruff and Pyright passed for changed Python files;
  `make validate-pr` passed Ruff, Pyright, isolated default tests (`833
  passed, 15 skipped, 8 deselected`), isolated config-extra tests (`410
  passed, 854 deselected`), and build; `make test-summary` passed with overall
  `1264 passed, 11 skipped, 862 deselected`.
- Expanded-path implementation refinement was used locally after the new e2e
  secret-boundary test exposed a resolved environment value in dry-run
  `plan.json`. No blocker-resolution pass was needed before PR opening.
- Stack state: root phase PR targets `develop`; no predecessor branch and no
  successor dependency at PR opening.
