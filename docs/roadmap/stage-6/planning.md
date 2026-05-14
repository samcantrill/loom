# Roadmap v6 Planning Notes: SLURM Script Planning

## Metadata

- Roadmap version: v6
- Source roadmap:
  `docs/roadmap.md`
- Previous version status: v5 is recorded as completed with Phases 1-5 merged
  into `develop`. V6 planning may depend on the v4 runtime/resource outcome and
  the v5 stage-worker/subprocess outcome, including normalized `RunOptions`,
  scheduler-neutral `ResourceRequest` entries, resolved per-stage runtime
  handoff data, executor descriptors/capabilities, `loom stage run`, prepared
  stage attempts, structured worker handoff records, subprocess-style logs, and
  baseline failure metadata.
- Planning notes status: confirmed; handed off to implementation-plan draft
- Current discussion stage: Handoff complete
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Feature brainstorming: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: confirmed
  - Design decision review: confirmed
  - Phase shaping: confirmed
  - Handoff: complete; implementation-plan draft created
- Related implementation plans:
  - `docs/roadmap/stage-4/implementation-plan.md`
  - `docs/roadmap/stage-5/implementation-plan.md`
  - `docs/roadmap/stage-6/implementation-plan.md`
- Related feature docs:
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
  - `docs/loom.md`
  - `docs/structure.md`
- Blockers:
  - None known for planning. V6 implementation must still wait for the normal
    implementation-plan quality gate and should verify that the required v5
    worker/subprocess contracts are present on `develop`.

## Roadmap Extraction

Baseline roadmap outcome:

- Make SLURM execution inspectable and testable before adding live scheduler
  submission.
- Add SLURM option models, modes, job records, submission records, and script
  builder interfaces.
- Map scheduler-neutral CPU, memory, GPU, and wall-time/resource metadata to
  SBATCH fields.
- Generate single-job scripts where one SLURM allocation runs the whole
  pipeline through normal Loom entry points.
- Generate afterok scripts where one job per runnable stage invokes the v5
  stage worker or its generic successor and scheduler dependency edges mirror planned stage
  dependencies.
- Add a separate prepared-run continuation entry point for submitted or
  externally launched jobs that should continue from an already prepared run
  directory instead of replaying `loom run CONFIG` or consuming an unredacted
  resolved config snapshot.
- Write dry-run manifests under the run directory with planned jobs, scripts,
  dependencies, resources, and worker commands.
- Add CLI integration for selecting SLURM dry-run planning and printing
  generated script and manifest paths.
- Add preflight checks for SLURM profile validity, resource mapping support,
  shared-run-directory assumptions, and optional command availability when
  known.
- Add fake-command and pure unit tests for script generation and dependency
  construction.

Prerequisites:

- v0 local runtime kernel: static DAG planning, local execution lifecycle,
  local run/artifact stores, inspectable run layout, logs, failures,
  fingerprints, and conservative resume.
- v1 rebuildable config composition: artifact-safe source records and
  deterministic config inputs that generated cluster scripts can point back to
  without hidden global search behavior.
- v2 CLI core: `loom validate`, `loom plan`, and `loom run` as thin wrappers
  over public APIs.
- v3 local diagnostics and preflight: stable preflight/check result models plus
  status, logs, and artifact inspection paths that must remain useful for
  cluster-prepared runs.
- v4 runtime options/resources: normalized `RunOptions`, runtime profiles,
  scheduler-neutral resource entries, executor descriptors/capabilities,
  config/CLI mapping, and safe `runtime.json` metadata.
- v5 stage worker/subprocess execution: prepared stage attempts,
  `loom stage run --run-uri RUN_URI --stage STAGE [--attempt N]`, structured
  worker request/result/failure records, logs, and baseline subprocess-style
  failure/process metadata.

Primary feature docs:

- `slurm.md`
- `config.md`
- `execution.md`
- `provenance.md`
- `fingerprints.md`
- `runtime-resources.md`
- `preflight.md`
- `cli.md`
- `run-store.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- No live `sbatch` submission.
- No scheduler polling, `squeue`/`sacct` status, `scancel` cancellation, or
  recovery after partial live submission.
- No controller mode, job arrays, MPI orchestration, interactive allocations,
  advanced `srun` behavior, retry policy, timeout enforcement, or cleanup
  policy.
- No remote run stores, remote artifact synchronization, cross-cluster
  submission, Docker/Apptainer composition, container image handling, plugin
  discovery, run catalogs, bundles, sweeps, dashboards, or domain-specific
  cluster behavior.
- No cluster-specific defaults that assume a module system, account policy, GPU
  syntax, accounting availability, or filesystem layout beyond the documented
  shared-run-directory assumption.

Compatibility obligations:

- Keep `loom` domain-neutral. Project code owns environment setup, modules,
  conda/venv activation, datasets, models, and cluster-specific conventions.
- Preserve the import boundaries in `docs/structure.md`: SLURM behavior belongs
  under `loom.pipeline.executors.slurm`; CLI code presents results but does not
  build scripts; planning owns stage actions and dependency order; execution
  owns lifecycle and worker contracts; stores own persisted layout and path
  helpers.
- Generated scripts must invoke stable Loom entry points such as `loom run` or
  a prepared-run continuation command for whole-run jobs, and the generic
  execution-owned stage job runner for one-stage jobs, not duplicate runner or
  stage logic.
- Use normalized runtime/resource data and adapter options rather than adding
  SLURM fields to semantic pipeline specs.
- Keep generated scripts and manifests plain, deterministic, inspectable, and
  safe to review from the run directory.
- Default tests must be local, deterministic, synthetic, and cluster-free.

## Version Briefing

What this version is:

- V6 is the dry-run SLURM planning layer. It introduces the models, mappers,
  script builders, manifest files, CLI selection path, and preflight checks
  needed to turn an already planned Loom run into reviewable SLURM scripts
  without calling `sbatch`.

Why this version exists:

- V5 gives Loom a durable one-stage worker contract and a subprocess executor,
  but there is still no scheduler adapter. Jumping straight to live SLURM
  submission would mix durable schema, command construction, resource mapping,
  dependency planning, run-store layout, and operational error handling in one
  step. V6 intentionally makes scheduler work inspectable first: users and
  tests can see exactly what would be submitted before v7 adds live operations.

Impacted or linked work:

- Direct predecessor: v5 stage worker and subprocess execution. V6 should
  preserve the v5 handoff-only worker for parent-managed subprocess behavior,
  but afterok live readiness needs a generic execution-owned stage job runner
  that can finalize one planned stage without a live parent. Single-job scripts
  should call a separate prepared-run continuation pathway inside one
  allocation, so generated scripts do not need to replay authoring-time config
  arguments or point at an unredacted resolved config snapshot.
- Direct successor: v7 SLURM operations. V7 should be able to add `sbatch`,
  job ID parsing, status, cancellation, and partial-submission recovery on top
  of the v6 script and manifest model.
- Later links: v15 HPC container execution can compose Apptainer/Singularity
  command construction with the v6/v7 SLURM script surface. V16 reliability
  policies can build on planned job/resource/failure metadata once live
  scheduler states exist.
- Diagnostics link: v3/v5 status/log/failure inspection should remain useful
  because generated scripts point SLURM wrapper logs and Loom stage logs to
  known run-directory paths.

Likely public surfaces and durable artifacts:

- Public or semi-public Python models for SLURM mode selection, SLURM options,
  planned jobs, planned submissions, dependency edges, scripts, and manifests.
- A `SlurmScriptBuilder`/resource-mapping surface under
  `loom.pipeline.executors.slurm`.
- Executor descriptor/capability metadata for SLURM dry-run modes.
- CLI support through `loom run CONFIG --executor slurm-single-job --dry-run`
  and `loom run CONFIG --executor slurm-afterok --dry-run`, or an equivalent
  executor/mode spelling confirmed during planning.
- A separate prepared-run continuation command, exact spelling still to be
  finalized, for example `loom prepared-run continue --run-uri RUN_URI
  --executor local`.
- Stable run-directory additions such as `slurm/submissions/<id>/manifest.json`,
  `scripts/pipeline.sh`, `scripts/stages/<stage>.sh`, and wrapper log paths.
- Stable preflight check IDs for SLURM profile validation, command availability
  when checked, resource mapping support, and shared-run-directory assumptions.

Structure rationale:

- The roadmap split v6 and v7 because script planning is a durable design
  contract even without a cluster. V6 can be fully tested with pure unit tests,
  fake command availability checks, temporary run directories, and synthetic
  pipelines. V7 can then focus on live scheduler operations without
  relitigating script layout, dependency construction, and resource mapping.
- V6 should probably remain one implementation plan because it has one primary
  user-visible outcome: generate reviewable SLURM dry-run artifacts from Loom
  plans. The broadest design questions are around ownership boundaries and
  durable artifact shape, not separate unrelated subsystems.

Visible assumptions, risks, and constraints:

- Assumption: a shared filesystem is the only supported SLURM data path in v6.
  Compute nodes are expected to see the run directory, generated scripts,
  project code, artifact-safe config/provenance records, prepared-run metadata,
  and input artifacts. Secret-bearing environment values are supplied through
  the process environment or trusted project setup, not through persisted Loom
  artifacts.
- Assumption: authored SLURM prelude and extra SBATCH options are trusted
  project config and can be written into scripts after type/path validation.
- Assumption: dry-run manifests may be persisted under the run directory even
  though no scheduler job has been submitted.
- Risk: afterok planning may accidentally become a second planner if it
  recalculates runnable stages instead of consuming the existing plan.
- Risk: generated single-job scripts can recursively select the SLURM executor
  unless the inner command shape forces local/subprocess execution.
- Risk: adding a `SUBMITTED` status or live job state in v6 would pull v7
  operations into scope too early.
- Risk: overly typed SLURM options could lock Loom into one cluster's policy;
  overly raw options could make validation and testability weak.
- Risk: scripts can leak sensitive environment values if runtime environment
  requests or project prelude handling are not explicit.
- Risk: using persisted resolved config or resolved stage metadata as the
  prepared-run command source can leak secrets or environment resolver outputs
  into durable artifacts.
- Constraint: no real SLURM cluster, network, container runtime, or optional
  scheduler dependency should be required for default tests.

User clarification questions and resolved answers:

- User had no corrections or clarifying questions about the startup v6
  briefing.
- User accepted the recommended planning priority: optimize first for
  conservative inspectability while keeping generated scripts and manifests
  shaped for v7 live-submission readiness.

## User Intent

Target audience:

- Loom maintainers, executor-adapter authors, and downstream users who need to
  review or version-control SLURM submission plans before allowing Loom to call
  a live scheduler.

User-visible outcome:

- A user can run SLURM dry-run planning for a local Loom run and inspect
  generated scripts, dependency edges, resource mappings, log paths, and a
  manifest without submitting jobs.
- V6 behaves as a run-directory planning step, not as a stdout-only script
  preview and not as a live pre-submission operation.
- Generated single-job scripts continue an already prepared run through a
  dedicated continuation entry point rather than depending on persisted
  unredacted resolved configuration.

Success criteria:

- Single-job and afterok dry-run planning produce deterministic run-directory
  artifacts and concise CLI output from the same normalized runtime/options and
  existing execution plan used by Loom execution.
- Prepared-run continuation is available as generic execution infrastructure
  for whole-run jobs and is used by the SLURM single-job script body.
- Both `slurm-single-job` and `slurm-afterok` dry-run planning are included.
  Afterok carries the stronger acceptance burden because it exercises
  dependency edges, generic stage-job runner commands, and stage-level
  resources.
- `--dry-run` persists the Loom plan plus SLURM scripts and manifests under the
  run directory.
- Missing `sbatch` does not block script generation. Command availability can
  be reported by preflight as environment information, while live scheduler
  availability becomes blocking in v7.

Non-goals:

- No live submission, status polling, cancellation, retry, controller mode, job
  arrays, containers, remote stores, or cluster-specific auto-discovery.
- No stdout-only planning mode as the primary v6 behavior. Human and JSON CLI
  output should point to durable artifacts rather than replacing them.

Constraints:

- Keep the implementation cluster-free by default, use only the standard
  library and existing Loom APIs, and preserve existing package/import
  boundaries.
- Keep unredacted resolved config values and secret-bearing environment values
  out of generated scripts, manifests, and default run-store config snapshots.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Startup briefing confirmed; user accepted conservative inspectability first with v7-ready script/manifest shape. | Dry-run-first SLURM planning; shared filesystem; no live `sbatch`; generated scripts call Loom entry points; default tests use fakes/synthetic pipelines. | None. | Intent discovery: workflows, success criteria, operational realities, and non-goals. |
| Intent discovery | Confirmed both single-job and afterok dry-run planning; dry run persists plan/scripts/manifests under the run directory; missing `sbatch` does not block generation. | Treat v6 as a run-directory planning step with afterok as the stronger acceptance path. | None. | Feature brainstorming: sort candidate capabilities into include, defer, maybe, and out of scope. |
| Feature brainstorming | Confirmed include/defer sorting for script generation, manifests, resource mapping, adapter options, CLI dry-run integration, preflight, and cluster-free tests. Live operations, status/cancel, controller mode, job arrays, containers, and real cluster acceptance are deferred or out of scope. | Include both single-job and afterok dry-run paths; keep v6 focused on generated artifacts and validation. | None. | Functionality and behavior confirmation: define observable CLI/API, persisted state, defaults, and failure behavior. |
| Functionality and behavior confirmation | Confirmed CLI shape, dry-run persistence boundaries, generated command bodies, manifest contents, resource mapping rules, preflight failure policy, SLURM option scope, dry-run layout, and CLI output shape. | `loom run ... --executor slurm-single-job|slurm-afterok --dry-run`; non-dry-run SLURM fails in v6; single-job uses a prepared-run continuation command with a non-SLURM inner executor defaulting to `local`; afterok scripts use the generic stage job runner command; structured resource/SLURM classes are the mapping input; deterministic resource/config conflicts fail loudly; repeated dry-runs use distinct planning directories. | None. | Context checkpoint before design decision review. |
| Context compaction/reset checkpoint | Functionality and behavior checkpoint recorded and resumed. | Resume design review from this notes file; do not reopen functionality unless explicitly requested. | None. | Draft design-decision queue. |
| Design decision review | Recorded repo-supported recommendations for ownership, public API, persisted layout, structured resources/options, dry-run status boundaries, script safety, preflight/CLI/test boundaries, generic wall-time deferral, dry-run replan semantics, generic stage job runner finalization, prepared-run continuation, secret-safe config/environment handoff, generated command launcher, logical dependency identity, and strict option parsing. | Ask only about remaining high-impact decisions without a strong repo-supported default. | None currently. | Phase shaping. |
| Phase shaping | Drafted and confirmed six-phase shape: prepared-run/lifecycle foundations; generic continuation commands; SLURM models/options/resources/manifests; script builders and dry-run planning APIs; CLI/preflight integration; e2e/docs hardening. | Keep generic execution work ahead of SLURM adapter work so generated scripts can target stable continuation commands. | None. | Handoff. |
| Handoff | User confirmed notes are ready; implementation-plan draft created at `docs/roadmap/stage-6/implementation-plan.md`. | Downstream plan quality gate must run before phase execution planning or implementation. | None. | Implementation-plan review/refinement. |

## Brainstormed Capabilities

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Single-job script generation | include | Confirmed v6 workflow for one allocation running the whole pipeline. | Inner executor must avoid recursive SLURM selection. |
| Afterok per-stage script generation | include | Confirmed v6 workflow and strongest acceptance path for stage-level resources and scheduler dependency edges. | Should consume existing plan actions and prepare only `RUN` stages. |
| Dry-run submission manifest | include | Required for inspectable planned jobs, scripts, dependencies, resources, commands, and log paths. | Needs durable layout decision. |
| Scheduler-neutral resource mapping | include | Required bridge from v4 resources to SBATCH fields. | Must balance generic CPU/memory/GPU defaults with explicit SLURM overrides. |
| SLURM adapter options model | include | Needed for partition/account/qos/prelude/extra SBATCH without polluting pipeline semantics. | Scope should avoid typing every SLURM option. |
| CLI dry-run integration | include | User-visible path for generating scripts and reporting artifact paths. | Likely `loom run ... --executor <slurm-mode> --dry-run`. |
| SLURM preflight checks | include | Needed to fail early on invalid profile/resource/shared-directory assumptions. | Missing `sbatch` is informational/non-blocking for generation in v6. |
| Fake command runner/test support | include | Keeps default suites cluster-free while making v7 live operations easier. | V6 may need command availability fakes, not live command runners. |
| Prepared-run continuation command | include | Single-job scripts need a clean generic way to continue an already prepared run without replaying config authoring inputs or depending on persisted unredacted resolved config. | Tentative CLI spelling is `loom prepared-run continue --run-uri RUN_URI --executor local`; exact command naming can be finalized during implementation-plan drafting. |
| Generic stage job runner contract | include | Keeps finalization behavior consistent across submitted executors and avoids SLURM-specific lifecycle logic. | Replaces eager afterok worker-request preparation as the live afterok foundation. |
| Secret-safe prepared-run handoff | include | Prepared-run and submitted-stage jobs must avoid leaking resolved config values, resolver outputs, or environment variable values into scripts, manifests, config snapshots, or public summaries. | Persist artifact-safe/unresolved or redacted records and runtime metadata; pass values through process environment at launch/job time only. |
| Live `sbatch` submission | out of scope | Belongs to v7 operations. | V6 must not enqueue jobs. |
| Scheduler status and cancellation | out of scope | Belongs to v7 operations after submitted job IDs exist. | No `squeue`, `sacct`, or `scancel` behavior beyond optional command availability reporting. |
| Controller mode and job arrays | out of scope | Explicitly deferred in roadmap and SLURM feature doc. | Separate lifecycle design needed. |
| Containerized SLURM scripts | out of scope | Belongs to v15 HPC container execution. | V6 scripts should remain non-container SLURM wrappers. |
| Real cluster acceptance tests | defer | Default test policy is cluster-free. | Add opt-in cluster tests only in later live operations work if needed. |

## Confirmed Functionality And Behavior

Included functionality:

- `loom run CONFIG --executor slurm-single-job --dry-run` generates one
  single-allocation SLURM script and corresponding dry-run manifest artifacts.
- `loom run CONFIG --executor slurm-afterok --dry-run` generates one script per
  planned `RUN` stage, dependency edges, and stage-job runner commands,
  and corresponding dry-run manifest artifacts.
- Add a separate generic prepared-run continuation command for whole-run
  execution from an already prepared run directory. Generated single-job SLURM
  scripts use this command instead of replaying the original config CLI or
  reading a persisted unredacted resolved config snapshot.
- Add a generic execution-owned stage job runner contract for running one
  planned stage to durable completion from run-store state. This contract is
  shared executor infrastructure, not SLURM-specific finalization logic.
- Selecting either SLURM executor without `--dry-run` fails clearly in v6
  because live submission belongs to v7.
- Dry-run planning may create or open the run directory, persist artifact-safe
  config/provenance records, `plan.json`, prepared-run metadata, SLURM scripts,
  wrapper log paths, manifests, and stage-job runner planning metadata. It
  should not persist unredacted resolved config snapshots by default, and it
  should not eagerly prepare downstream v5 handoff-only worker request records
  for afterok stages.
- Dry-run manifests record schema version, run URI, mode, dry-run flag,
  planning/submission ID, created time, plan path, scripts, wrapper log paths,
  planned jobs, stage names, attempts, dependency placeholders, worker commands,
  resource summaries, and SLURM options. Scheduler job IDs are absent or null in
  v6.
- Resource mapping consumes structured runtime/resource classes, especially
  `ResourceRequest` and `ResourceEntry`, rather than ad hoc strings or untyped
  mappings.
- SLURM options use typed/structured classes for common options:
  `partition`, `account`, `qos`, `constraint`, `nodes`, `ntasks`,
  `cpus_per_task`, `mem`, `mem_per_cpu`, `gres`, `time`, `prelude`, and
  `extra_sbatch`.
- `extra_sbatch` remains a validated escape hatch for uncommon flags, but v6
  does not model every SLURM option.
- Each dry run writes into a distinct planning/submission directory such as
  `slurm/submissions/<planning_id>/...`, with the manifest, scripts, and
  wrapper log paths under that directory.
- Single-job scripts run the generic whole-run continuation pathway inside the
  allocation with the prepared-run continuation entry point and a non-SLURM inner executor,
  defaulting to `local` unless explicitly configured.
- Afterok scripts invoke
  the generic stage job runner command once that command shape is finalized.
  The existing v5 handoff-only `loom stage run --run-uri RUN_URI --stage STAGE
  --attempt ATTEMPT` remains available for parent-managed subprocess behavior,
  but it is not the live afterok finalization contract.
- Generated scripts and manifests do not embed environment variable values.
  Environment-dependent config values should remain unresolved in persisted
  config/provenance artifacts and be resolved by the continuation or stage job
  process from its process environment at job start. Missing required
  environment values fail clearly before user stage code runs.

User-visible behavior:

- Users invoke SLURM planning through the existing `loom run` command with
  `--dry-run` and an explicit SLURM executor mode.
- CLI output should summarize what was generated and point to durable manifest,
  script, and log paths rather than printing full scripts by default.
- Text output reports counts and paths: manifest path, script directory, number
  of planned jobs, root/final stage jobs for afterok, and warnings. JSON output
  returns the same facts in a structured envelope.

Default behavior:

- SLURM dry-run is durable by default: generated planning artifacts live under
  the run directory.
- The single-job inner executor defaults to `local` to avoid recursive SLURM
  selection.
- Prepared-run continuation defaults to artifact-safe metadata and redacted
  summaries for persistence. Any command or manifest field that would require
  writing a secret-bearing resolved value must fail explicitly or require a
  future opt-in secret policy outside v6's default path.
- Generic `cpu`, `memory`, `gpu`, and SLURM `time` values map to SBATCH fields
  by default. Explicit structured SLURM options such as `cpus_per_task`, `mem`,
  `gres`, or `time` may override generic mappings only when the override is
  unambiguous.
- Repeated dry runs use distinct planning IDs by default, avoiding accidental
  overwrite and giving v7 a natural submission-attempt structure.

Failure behavior and diagnostics:

- A SLURM executor selected without `--dry-run` fails with a clear
  not-implemented/live-submission-deferred error.
- Deterministic conflicts in resources or SLURM configuration fail explicitly
  and loudly before script generation. Failures should be structured and
  path-aware where possible.
- Invalid SLURM profile shape, unsafe script or log paths, unsupported resource
  mapping, unknown SLURM mode, and non-shared/local run URI assumption failures
  are errors.
- Missing `sbatch` is warning or informational preflight output in v6 because
  dry-run generation does not require a live scheduler command.

Explicit deferrals:

- Live `sbatch` submission is deferred to v7.
- Marking jobs `SUBMITTED` or recording live scheduler job IDs is deferred to
  v7.
- Scheduler status, cancellation, and partial live-submission recovery are
  deferred to v7.
- Controller mode, job arrays, MPI, and advanced `srun` behavior are deferred
  to later explicit design work.
- Containerized SLURM scripts are deferred to v15 HPC container execution.
- Real cluster acceptance tests are deferred or opt-in later; v6 default tests
  remain cluster-free.

Out-of-scope behavior:

- V6 must not call `sbatch`, mark scheduler jobs submitted, or pretend planned
  stages ran.

Context compaction/reset checkpoint:

- Checkpoint status: complete; pause before design decision review because this
  client session has no direct context-compaction command.
- Notes path: `docs/roadmap/stage-6/planning.md`
- Resume instruction: reread this planning-notes file,
  `.codex/prompts/roadmap-stage-planning-facilitate.md`, and the
  related roadmap/feature docs before starting design decision review. Treat
  the confirmed functionality and behavior above as locked unless the user
  explicitly reopens them.
- Functionality and behavior reopened after checkpoint: no

## Design Decision Review Queue

| Decision | Why it matters | User feedback needed | Status |
| --- | --- | --- | --- |
| SLURM ownership and import boundaries | Prevents CLI, planning, execution, and store responsibilities from collapsing into a scheduler-specific path. | None; repo structure gives a clear recommendation. | confirmed; recorded recommendation |
| Public Python API surface | V7 and tests need stable planning records without exposing live scheduler operations too early. | None; expose structured dry-run planning models and keep live command runners out of v6. | confirmed; recorded recommendation |
| Durable manifest and file layout | This becomes the handoff artifact for v7 submission, status, and cancellation. | None; confirmed behavior and run-store docs support one directory per planning/submission ID under the run directory. | confirmed; recorded recommendation |
| Structured resource and SLURM options model | Resource mapping is a compatibility contract and must fail loudly on conflicts. | None; user confirmed structured classes and loud conflict failures. | confirmed; recorded recommendation |
| Generic wall-time policy | Runtime resources currently reject generic `wall_time_seconds`, while v6 needs SLURM time mapping. | None; use `SlurmOptions.time` in v6 and defer generic wall-time until multiple executors need it. | confirmed; recorded recommendation |
| Dry-run lifecycle and status boundary | Prevents v6 from pretending scripts were submitted or stages ran. | None; confirmed behavior and status docs support manifest-only dry-run state. | confirmed; recorded recommendation |
| Script safety and trust boundary | Generated shell scripts are durable artifacts and can accidentally leak or misquote user inputs. | None; repo docs clearly recommend deterministic directives, standard-library quoting, trusted prelude, and no secret environment persistence. | confirmed; recorded recommendation |
| CLI, preflight, and test boundaries | Keeps presentation, diagnostics, and cluster-free validation aligned with existing architecture. | None; repo docs give clear ownership and default test policy. | confirmed; recorded recommendation |
| Afterok worker finalization path | V5 direct worker writes only a handoff, but future submitted executors cannot rely on a live parent process to finalize stage state. | User selected a generic execution-owned stage job runner contract, not a SLURM-specific finalizer. | confirmed |
| Generated command launcher portability | Clusters differ in environment setup; hardcoding `loom` is simple but less portable than a structured launcher command. | Use a structured generated-command launcher argv option, defaulting to `["loom"]`, with prelude kept separate for environment setup. | confirmed |
| Dry-run replan, existing-run, and lock semantics | Dry-run writes real run-directory state; unclear open/resume behavior can corrupt run plans or make repeated dry-runs surprising. | User accepted normal run safety defaults: omitted `--run-uri` allocates a new run; existing run without `--resume` fails; `--resume` opens and replans through normal semantics; active/unsafe locks fail. | confirmed |
| Prepared-run continuation command | Single-job scripts must reconstruct the intended run on compute nodes without replaying config CLI inputs or relying on unredacted resolved config snapshots. | User requested a fully separate prepared-run continuation command as cleaner long-term scope; use `loom prepared-run continue --run-uri RUN_URI --executor local` as the planned CLI spelling unless implementation-plan review finds a blocking parser issue. | confirmed |
| Secret-safe config and environment handoff | Persisting resolved config, resolver outputs, runtime environment values, or raw adapter payloads can leak secrets into durable run artifacts. | Use artifact-safe/unresolved or redacted persisted records; environment values are supplied through process environment at job start and are not written into scripts/manifests; validate prepared-run payloads for secret-bearing resolved values. | confirmed |
| Single-job command source | Single-job scripts must reconstruct the intended run on compute nodes; using original config, persisted resolved config, or a prepared run continuation has different reproducibility and CLI-surface costs. | Use the prepared-run continuation command as the source of truth; do not use persisted unredacted resolved config. | confirmed |
| Afterok preparation side effects | Preparing v5 handoff-only worker requests during dry-run mutates stage attempt state before any scheduler job exists and cannot bind downstream inputs up front. | Do not eagerly prepare v5 worker requests for afterok dry-run; represent planned stage jobs and let the generic stage job runner bind inputs at job start. | confirmed |
| Dependency identity before scheduler job IDs | V6 has no job IDs but still needs dependency edges that v7 can turn into `afterok` options. | Use deterministic logical job keys and dependency job keys as the primary manifest identity; scheduler job IDs remain absent/null in v6 and are added by v7. | confirmed |
| Scheduler option strictness and escape hatch policy | Strict structured classes catch bad config early, but SLURM sites vary and over-validation can block valid cluster-specific usage. | Reject unknown structured option fields; allow unknown scheduler flags only through validated `extra_sbatch`; reject `extra_sbatch` conflicts with modeled/generated SBATCH directives. | confirmed |

## Design Decisions

| Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Debt and revisit trigger |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SLURM ownership and import boundaries | Keep dry-run planning, option parsing, resource mapping, script building, manifest models, and SLURM-specific errors under `loom.pipeline.executors.slurm`; CLI calls public APIs and formats results; planning supplies stage actions/dependencies; execution supplies worker preparation contracts; run store supplies path/persistence helpers. | Not separately requested; repo evidence gives a clear recommendation. | CLI-owned script generation; planning-owned scheduler mapping; store-owned scheduler semantics; SLURM code importing config internals or diagnostics models. | `docs/structure.md`, `docs/features/slurm.md`, and `docs/features/execution.md` define these ownership lines. | Keeps backend code reviewable and prevents a second scheduler-shaped runner from forming. | Lets v7 add live command runners and later container composition without moving CLI/planning/store code. | Some store path helpers may be added for SLURM layout; revisit if executor code starts path-walking run directories. |
| Public Python API surface | Expose structured dry-run planning vocabulary needed by tests and v7, such as `SlurmMode`, `SlurmOptions`, `SlurmPlannedJob`, `SlurmPlannedSubmission`, `SlurmScriptBuilder`, `SlurmResourceMapper`, and focused SLURM planning errors. Do not expose or implement live `SlurmCommandRunner` behavior in v6. | Not separately requested; repo evidence gives a clear recommendation. | Stringly typed manifest dictionaries only; exposing live submission APIs before they exist; top-level `loom` exports. | V6 needs testable structured models, while v7 owns live scheduler command execution. | Gives type-checkable seams without making the public surface bigger than the dry-run contract. | V7 can layer submission records/job IDs onto the same planned-submission model. | Exact export set may be refined during implementation; revisit when v7 needs live command runner APIs. |
| Durable manifest and file layout | Use schema-versioned dry-run manifests under `slurm/submissions/<planning_id>/...`, with scripts and wrapper log paths in the same planning directory and job IDs absent or null. Use run-store path helpers where available. | User confirmed distinct planning directories and manifest contents. | One mutable `slurm/submission.json`; stdout-only script previews; job-state files by fake job IDs in v6. | One directory per planning ID avoids accidental overwrite and matches the future submission-attempt model. | Keeps repeated dry-runs inspectable and easier to compare. | V7 can update the same manifest family with submitted job IDs and partial-submission state. | No migration story beyond schema versioning yet; revisit when v7 writes live job records. |
| Structured resource and SLURM options model | Map from `ResourceRequest`/`ResourceEntry` and structured `SlurmOptions`; allow explicit SLURM overrides only when unambiguous; fail loudly with structured, path-aware errors for deterministic conflicts. | User explicitly requested structured resource classes and loud conflict failures. | Untyped SBATCH string assembly; silently preferring explicit SLURM fields over conflicting generic fields; accepting stale mixed resource aliases. | The runtime/resource docs make scheduler-neutral resources the source of truth, and the user emphasized strict conflict behavior. | Centralizes mapping and conflict handling in one testable place. | Later executors can share generic resource semantics while SLURM-specific fields remain adapter-owned. | Cluster-specific GPU and memory conventions remain explicit config; revisit if multiple sites need pluggable mapping policies. |
| Generic wall-time policy | Keep wall time as structured `SlurmOptions.time` in v6; do not add generic `wall_time_seconds` to `ResourceRequest` until more than one executor needs a shared wall-time concept. | Not separately requested; reconciles confirmed functionality with current runtime docs. | Add a generic wall-time resource entry in v6; ignore wall time entirely; encode wall time in `ExecutionOptions.settings`. | Runtime docs currently defer generic wall-time, while SLURM docs place `time` in SLURM-specific options. | Avoids changing cross-executor runtime semantics for one adapter. | Leaves room for Docker/Apptainer/reliability phases to define a broader timeout/wall-time model later. | SLURM time is adapter-specific debt; revisit when another executor needs wall-time mapping or v16 timeout policies define a generic field. |
| Dry-run lifecycle and status boundary | V6 may persist artifact-safe config/provenance records, `plan.json`, prepared-run metadata, scripts, manifests, wrapper log paths, stage-job planning metadata, and generic stage-job runner contract artifacts, but it must not persist unredacted resolved config snapshots by default, call `sbatch`, record live job IDs, mark jobs `SUBMITTED`, or imply stages ran. | User confirmed this boundary, later refined afterok away from eager v5 worker preparation, and asked to avoid persisted resolved configs because they may contain sensitive keys. | Add `SUBMITTED` status in v6; use fake job IDs; update stage status as if queued; eagerly prepare v5 handoff-only worker requests for all afterok stages; use unredacted resolved config as the generated command source. | V6 is inspectable script planning; v7 owns live operations; config docs already prefer artifact-safe source/provenance records over resolved-config persistence. | Prevents status semantics and secret exposure from outrunning actual scheduler integration. | V7 can add submitted/partial/cancelled state with real scheduler facts and use the generic stage job runner for live afterok. | Live submitted-job status remains deferred; revisit in v7. |
| Script safety and trust boundary | Generate deterministic SBATCH directives, shell-quote paths/arguments with standard-library helpers, write scripts as user-executable when practical, type-validate prelude and `extra_sbatch`, and treat prelude as trusted project code without sandboxing. Do not persist environment variable names/values from runtime environment requests by default. | Not separately requested; repo docs give a clear recommendation. | Unsafe string concatenation; auto-capturing environment; sandboxing trusted prelude; rejecting all raw extra SBATCH options. | SLURM docs emphasize cluster portability, trusted authored config, durable scripts, and path quoting. | Keeps scripts reviewable and reduces accidental command injection or secret leakage. | Allows project-specific environment setup through prelude without adding cluster-specific discovery. | No sandbox for prelude; revisit only if Loom adds an untrusted config mode. |
| CLI, preflight, and test boundaries | CLI presents counts/paths/JSON envelopes and never builds scripts directly; preflight maps SLURM validation into stable check IDs; missing `sbatch` is warning/info in v6; default tests use synthetic pipelines and fake command availability, with real cluster tests deferred or opt-in. | User confirmed CLI output and missing-`sbatch` behavior. | Golden tests against real SLURM; CLI parsing scheduler output; lower layers importing diagnostics; blocking dry-run on missing `sbatch`. | Current CLI, preflight, and testing docs already define these boundaries. | Keeps default validation deterministic and reviewable without a cluster. | V7 can add opt-in/live scheduler tests and command-runner fakes without changing the dry-run contract. | No real cluster acceptance evidence in v6; revisit in v7 operations or a later opt-in acceptance suite. |
| Dry-run replan, existing-run, and lock semantics | Follow normal run safety defaults. If `--run-uri` is omitted, allocate/create a new run normally. If `--run-uri` points to an existing run and `--resume` is not set, fail clearly. If `--resume` is set, open the existing run, replan using normal resume semantics, write a new distinct SLURM planning directory, and update `plan.json` only through the same runner/planner path used by normal dry-run behavior. Active locks or unsafe/stale state fail clearly. | User said to follow defaults. | Planning-only reopening without `--resume`; always requiring a fresh run; force-unlock or stale-job cleanup in v6. | This preserves Loom's existing run safety model while still supporting resume-based SLURM planning. | Avoids surprising mutation of existing runs and keeps SLURM dry-run aligned with existing run/resume semantics. | V7 can layer active submitted-job checks and stack-safe resubmission policy onto the same run-safety baseline. | No force or cleanup policy in v6; revisit in v7 if live submitted jobs need explicit replan/resubmit handling. |
| Generic stage job runner and afterok finalization | Add a generic execution-owned stage job runner contract for running one planned stage to durable completion from run-store state. The runner opens an existing run, reads the persisted plan and stage/runtime metadata, validates the stage is planned `RUN`, verifies dependencies through run-store state, allocates or validates the attempt at job start, binds inputs just in time from upstream outputs/artifact index, runs the stage through shared local execution machinery, validates outputs, and commits outputs, provenance, artifact index, stage status, and failure records through shared lifecycle helpers. | User explicitly selected a generic execution-owned stage job runner contract, not a SLURM-specific finalizer. | SLURM-specific finalization; a long-running SLURM parent/controller process; relying on v5 handoff-only `loom stage run` for live afterok completion; eager v5 worker request preparation for every afterok dry-run stage. | Submitted executors need consistent behavior across SLURM, containers, and future remote workers. Current v5 handoff-only worker is correct for parent-managed subprocess but not sufficient for submitted per-stage execution, and eager preparation cannot bind downstream inputs before upstream jobs run. | Centralizes commit/failure semantics in execution instead of duplicating them in each executor. | Provides a reusable contract for SLURM afterok, containerized stages, and future remote workers while preserving the v5 handoff-only worker for parent-managed subprocess. | Requires extracting private runner commit/input-binding helpers into reusable execution lifecycle APIs; revisit if stage-level concurrency requires stronger artifact-index locking. |
| Prepared-run continuation command and single-job source | Add a generic execution-owned prepared-run continuation command for whole-run execution from an existing prepared run directory. Single-job SLURM scripts invoke this command with an explicit non-SLURM inner executor, defaulting to `local`, instead of replaying the original `loom run CONFIG ...` command or consuming `config/resolved.yaml`. Planned CLI spelling is `loom prepared-run continue --run-uri RUN_URI --executor local` unless implementation-plan review finds a blocking parser issue. | User asked to add a fully separate prepared-run continuation command because it is cleaner long term and agreed with the tentative command direction. | Original config replay from generated scripts; persisted resolved-config command source; SLURM-specific single-job finalizer; overloading `loom run CONFIG` with hidden prepared-run behavior. | A separate command gives generated scripts a stable continuation contract and avoids coupling script bodies to authoring-time CLI details or secret-bearing resolved config snapshots. | Keeps single-job execution generic and separates "prepare a run" from "continue a prepared run." | Later executors, containers, and live submission can reuse the same prepared-run continuation contract. | Revisit only if CLI implementation-plan review finds the nested command shape conflicts with existing parser conventions. |
| Secret-safe config and environment handoff | Persist artifact-safe/unresolved config provenance, redacted summaries, prepared-run metadata, and safe runtime metadata. Do not persist unredacted resolved config snapshots, resolver outputs, environment variable values, or raw adapter payloads by default. Environment-dependent values remain unresolved in persisted config artifacts and are resolved by the prepared-run continuation or stage job process from its process environment at job start. Missing required environment values fail clearly before user stage code runs. | User raised the concern that resolved configurations may contain sensitive keys and suggested leaving items unresolved while passing environment values to spawned processes. | Persist resolved config; write environment values into scripts or manifests; auto-capture the submit-host environment; silently drop missing environment values; rely on `runtime.json` to carry raw environment requests. | Existing config and runtime docs already avoid default resolved-config snapshots, raw source snapshots, resolver outputs, and environment value persistence. Passing values through the process environment preserves secret locality while keeping run artifacts reviewable. | Reduces accidental secret leakage and makes the handoff contract explicit. | V7 may add live submission-time environment export policies without changing v6 artifacts. Future secret policies can add encryption or explicit opt-in persistence separately. | V6 must audit prepared-run, plan, stage fingerprint, and manifest payloads for secret-bearing resolved values. Revisit if stage fingerprints require secret values for reproducibility; stored summaries should remain redacted or unresolved. |
| Generated command launcher portability | Add a structured launcher argv option for generated Loom commands, defaulting to `["loom"]`. The launcher is a sequence of command arguments prepended to generated Loom subcommands, for example `["python", "-m", "loom.cli"]`, `["uv", "run", "loom"]`, or `["loom"]`. Prelude remains trusted shell setup and is not overloaded as the command launcher. Generated scripts shell-quote every launcher and command argument. | User agreed with the prepared-run/safe-handoff direction; this resolves the remaining launcher portability item with a conservative structured default. | Hardcode `loom` only; make users place all launch mechanics in shell prelude; accept a raw launcher string; auto-discover Python or virtualenv launchers. | A structured argv launcher covers common cluster environments without weakening quoting or requiring cluster discovery. | Keeps generated command construction testable and avoids duplicating shell assembly across single-job and afterok modes. | Later containers and remote executors can reuse or adapt the same generated-command launcher model. | Does not solve every environment bootstrap problem; revisit if multiple executors need a richer generic command-launcher contract. |
| Logical dependency identity before scheduler job IDs | Use deterministic logical job keys as the primary v6 identity for planned jobs and dependencies. Single-job mode has one logical key such as `pipeline`; afterok jobs use stage-derived keys such as `stage:<stage_name>`. Manifests record `dependency_job_keys` and dependency type `afterok`; scheduler `job_id`, `raw_job_id`, and `dependency_job_ids` are absent or null in v6 and added only by v7 live submission. | User agreed to continue with the default recommendations. | Fake job IDs; opaque job-ID placeholders as primary identity; dependencies represented only as stage names; v6 `slurm/jobs/<job_id>.json` files. | Logical keys let dry-run artifacts represent the graph without pretending scheduler facts exist. | Keeps manifest comparisons stable and removes a class of fake-ID migration problems. | V7 can map logical keys to submitted scheduler job IDs while preserving the dry-run dependency model. | Key naming is a small schema commitment; revisit only if v7 needs multi-attempt submitted jobs for the same stage in one submission directory. |
| Scheduler option strictness and escape hatch policy | Structured SLURM options reject unknown fields and validate type/shape. `extra_sbatch` is the only v6 path for uncommon scheduler flags and accepts deterministic mapping entries from `--flag` to `true` for valueless flags or a string value for valued flags. `false`, null, whitespace/control characters, and duplicate or conflicting generated/modeled flags fail loudly. `extra_sbatch` must not override generated job name, output/error paths, dependency directives, or modeled resource directives such as CPU, memory, GRES, or time. | User emphasized structured classes and loud conflict failures; this applies that rule to the escape hatch. | Accept arbitrary raw `#SBATCH` lines; silently let raw flags override modeled fields; reject all uncommon scheduler flags; model every SLURM option. | This keeps portability without turning `extra_sbatch` into an unreviewable shadow configuration language. | Centralizes validation and conflict detection in one mapper. | Additional typed options can be promoted later from `extra_sbatch` when recurring site patterns appear. | Raw list-style extra options from the feature doc remain deferred; revisit only if the validated mapping cannot express a real site need. |

## Practical Design Notes

Public Python API surface:

- Structured dry-run planning models and helpers live under
  `loom.pipeline.executors.slurm`.
- Prepared-run continuation models/helpers live under `loom.pipeline.execution`
  and provide whole-run continuation from a prepared run directory.
- Generic stage job runner models/helpers live under `loom.pipeline.execution`
  and are consumed by submitted executors.
- Candidate exports include `SlurmMode`, `SlurmOptions`, `SlurmPlannedJob`,
  `SlurmPlannedSubmission`, `SlurmScriptBuilder`, `SlurmResourceMapper`, and
  focused SLURM planning/configuration errors.
- Live scheduler command-runner APIs remain deferred to v7.

CLI surface:

- `loom run CONFIG --executor slurm-single-job --dry-run`
- `loom run CONFIG --executor slurm-afterok --dry-run`
- Prepared-run continuation command spelling is
  `loom prepared-run continue --run-uri RUN_URI --executor local`, unless
  implementation-plan review finds a blocking parser issue.
- Selecting either SLURM executor without `--dry-run` fails clearly in v6.
- Text output reports counts and paths. JSON output returns the same facts in a
  structured envelope.

Persisted records and file layout:

- Persist artifact-safe config/provenance records and prepared-run metadata;
  do not persist unredacted resolved config snapshots by default.
- Dry-run artifacts live under `slurm/submissions/<planning_id>/...`.
- Each planning directory contains a schema-versioned manifest plus generated
  scripts and wrapper log paths.
- Manifest job IDs are absent or null in v6.
- Afterok dry-run manifests record planned stage jobs rather than prepared v5
  worker request records for every stage.
- Generated command bodies reference prepared-run continuation or generic stage
  job runner commands and do not embed environment variable values.
- Generated command bodies use the structured launcher argv, defaulting to
  `["loom"]`, and shell-quote every argument.
- Afterok manifests use deterministic logical job keys and
  `dependency_job_keys`; scheduler job IDs remain absent/null in v6.
- Run-store path helpers should own layout details where practical.

Import boundaries and dependencies:

- SLURM planning code does not import `loom.cli`, config composition internals,
  diagnostics models, or downstream project packages.
- CLI imports and calls public SLURM planning APIs.
- Diagnostics/preflight maps SLURM validation records to check results.
- No Python SLURM dependency is introduced.

Failure modes and diagnostics:

- Prepared-run continuation fails clearly if the run lacks required prepared-run
  metadata, has an incompatible plan, requests a recursive submitted executor,
  or cannot resolve required environment values from the process environment.
- Deterministic resource/config conflicts fail before script generation with
  structured, path-aware errors where possible.
- Invalid SLURM profile shape, unsafe script/log paths, unsupported resource
  mapping, unknown mode, and non-local/shared-run-directory assumption failures
  are errors.
- Missing `sbatch` is warning or informational in v6.

Extension points and flexibility boundaries:

- `extra_sbatch` is the v6 escape hatch for uncommon scheduler flags.
- Unknown structured SLURM option fields fail. `extra_sbatch` accepts only
  validated mapping entries and cannot override generated or modeled SBATCH
  directives.
- Cluster-specific module/venv setup belongs in trusted prelude.
- Pluggable resource mapping, live command runners, status/cancel APIs,
  generic wall-time, and containers are deferred.

Maintainability assessment:

- Maintainability depends on keeping dry-run planning as a thin scheduler
  adapter over existing planner, execution, runtime, and store contracts.
- The biggest resolved design risk is that submitted executors need a generic
  execution-owned stage job runner, not executor-specific finalization logic.
- Single-job execution now has a matching generic prepared-run continuation
  contract, keeping "prepare the run" and "execute the prepared run" separate.
- Remaining design risks are implementation risks rather than open design
  choices: prepared-run payload safety, lifecycle helper extraction, and
  keeping SLURM dry-run planning from growing live-submission behavior.

Extensibility assessment:

- The planned manifest and model family should let v7 add live job IDs,
  partial-submission records, status, and cancellation without reshaping v6
  dry-run artifacts.
- The structured options/resource mapper keeps later cluster-specific behavior
  adapter-owned.
- Prepared-run continuation and stage-job continuation provide reusable
  execution entry points for later submitted executors and container wrappers.

Flexibility and expansion assessment:

- V6 favors explicit, inspectable configuration over cluster auto-discovery.
- The model supports single-job and afterok first, with controller mode, job
  arrays, MPI, and containers left to later designs.

Scalability and future compatibility:

- Afterok dependency construction should consume the planner's DAG/actions and
  should be testable on fan-in, fan-out, and diamond graphs without real SLURM.
- One planning directory per dry run keeps repeated planning attempts
  inspectable and future-submission-compatible.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No live scheduler operations | V6 is dry-run script planning by design. | v7 SLURM operations starts. |
| No generic wall-time resource | Current runtime docs defer generic wall-time; v6 only needs SLURM `time`. | Another executor needs wall-time or v16 timeout policies define a generic field. |
| No real cluster acceptance tests | Default tests must be deterministic and cluster-free. | v7 live operations or a later opt-in acceptance suite. |
| Stage job runner requires lifecycle helper extraction | Current parent runner commit/input-binding logic is private to `PipelineRunner`. | V6 implementation of the generic stage job runner. |
| Secret-safe prepared-run handoff requires payload audit | Current persisted plans and stage fingerprints may carry resolved stage values even when config snapshots are artifact-safe. | V6 implementation must define safe persisted payloads or fail loudly when a prepared-run payload would persist secret-bearing resolved values. |

## Phase Sketch

### Phase 1 - Prepared-Run And Lifecycle Foundations

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

Out of scope:

- No SLURM models, scripts, manifests, `sbatch`, CLI executor selection, or
  live scheduler behavior.

Acceptance criteria:

- Prepared-run metadata can be written/read through public execution/store APIs.
- Secret-bearing resolved values are either absent from prepared-run payloads or
  rejected with structured errors.
- Shared lifecycle helpers preserve existing local/subprocess behavior.

Test expectations:

- Package: execution and store exports remain importable without optional SLURM
  dependencies.
- Unit: prepared-run schema validation, payload safety checks, lifecycle helper
  success/failure paths.
- Contract: run-store read/write behavior for prepared-run metadata.
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

### Phase 2 - Generic Continuation Commands

Goal:

- Implement generic CLI/API continuation entry points for prepared whole-run
  execution and execution-owned one-stage jobs.

Scope:

- Add `loom prepared-run continue --run-uri RUN_URI --executor local`.
- Add or finalize the generic stage-job runner command shape for one planned
  stage to durable completion.
- Ensure continuation opens an existing run, validates the persisted plan and
  prepared metadata, prevents recursive submitted executor selection, resolves
  required environment values from process environment, and fails before user
  stage code when required handoff state is missing.

Out of scope:

- No generated SLURM scripts, scheduler dependency planning, or live scheduler
  operations.

Acceptance criteria:

- Whole-run continuation can execute a prepared run with a non-SLURM executor.
- Stage-job continuation can finalize one planned `RUN` stage from run-store
  state without a parent process.
- Missing prepared metadata, incompatible plans, unresolved environment
  requirements, and recursive submitted executors fail clearly.

Test expectations:

- Package: CLI command registration remains import-light.
- Unit: command argument parsing, continuation validation, recursive-executor
  rejection, missing environment behavior.
- Contract: command result/error envelopes match CLI conventions.
- Integration: whole-run and stage-job continuation against a local run store.
- E2E: a tiny prepared run continues through the public CLI.
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

- Exact stage-job command naming may still be adjusted if CLI review finds a
  clearer non-conflicting spelling.

Reviewability:

- Review can focus on CLI/API behavior and continuation invariants before any
  SLURM adapter code exists.

### Phase 3 - SLURM Models, Options, Resources, And Manifest Schema

Goal:

- Add the structured SLURM dry-run vocabulary and mapper layer without script
  generation or CLI wiring.

Scope:

- Add `SlurmMode`, `SlurmOptions`, structured `extra_sbatch` validation,
  generated-command launcher argv, resource-to-SBATCH mapper, logical job keys,
  planned dependency records, planned job records, and planned submission
  manifest models under `loom.pipeline.executors.slurm`.
- Add path-safe helpers or adapter-local path construction for
  `slurm/submissions/<planning_id>/...` pending run-store helper needs.

Out of scope:

- No generated shell scripts, CLI integration, live command runner, job ID
  parsing, status, cancellation, or real scheduler calls.

Acceptance criteria:

- Structured option parsing rejects unknown fields and conflicts.
- `extra_sbatch` accepts only validated mapping entries and cannot override
  generated/modeled directives.
- Resource conflicts fail with structured, path-aware errors.
- Manifest models round trip with job IDs absent/null and dependencies expressed
  by logical job keys.

Test expectations:

- Package: SLURM module imports without optional dependencies.
- Unit: option parsing, extra SBATCH validation, resource mapping, logical
  dependency records, manifest round trips.
- Contract: public model serialization stays deterministic and schema-versioned.
- Integration: none required beyond model/store path helpers.
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

### Phase 4 - SLURM Script Builders And Dry-Run Planning APIs

Goal:

- Generate reviewable single-job and afterok SLURM dry-run artifacts from an
  existing Loom plan and prepared run state.

Scope:

- Build deterministic SBATCH scripts for single-job and afterok modes.
- Single-job scripts invoke prepared-run continuation through the structured
  launcher argv.
- Afterok scripts invoke the generic stage-job runner through the structured
  launcher argv and use logical dependency keys in manifests.
- Write dry-run manifests, scripts, wrapper log paths, and planning metadata
  under `slurm/submissions/<planning_id>/...`.
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

### Phase 5 - CLI And Preflight Integration

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

### Phase 6 - End-To-End Hardening And Documentation

Goal:

- Close v6 with cluster-free end-to-end evidence, documentation updates, and
  compatibility checks across the generic continuation and SLURM dry-run
  surfaces.

Scope:

- Add final e2e coverage for single-job and afterok dry-runs with generated
  artifact inspection.
- Add regression coverage that environment resolver outputs and environment
  values are not persisted in SLURM scripts/manifests/config snapshots.
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

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Do you have clarifying questions or corrections about the v6 briefing before we lock roadmap framing? | Roadmap framing | No corrections; proceed with dry-run SLURM planning scope from the roadmap. | resolved; no clarifying questions or corrections |
| What should v6 optimize for relative to the roadmap: conservative inspectability, future v7 live-submission readiness, or smallest useful user workflow? | User intent and phase priorities | Conservative inspectability first, while keeping v7-ready manifests/scripts. | resolved; default accepted |
| Should v6 include both single-job and afterok dry-run planning? | Intent discovery | Include both; afterok is the stronger acceptance path. | resolved; default accepted |
| Should `--dry-run` persist artifacts under the run directory or only print scripts to stdout? | Intent discovery | Persist plan, scripts, and manifests under the run directory. | resolved; default accepted |
| Should missing `sbatch` block v6 script generation? | Intent discovery | No; report command availability via preflight/environment checks, but do not block dry-run generation. | resolved; default accepted |
| Is the proposed include/defer/out-of-scope capability sorting acceptable? | Feature brainstorming | Use the drafted sorting: include dry-run models/scripts/manifests/resource mapping/adapter options/CLI/preflight/tests; defer live operations/status/cancel/controller/job arrays/containers/real cluster tests. | resolved; accepted |
| Should v6 expose SLURM dry-run through `loom run CONFIG --executor slurm-single-job|slurm-afterok --dry-run`, and fail clearly without `--dry-run`? | Functionality and behavior | Yes; live submission is v7. | resolved; accepted |
| How much durable state may SLURM dry-run write? | Functionality and behavior | Create/open the run directory, persist artifact-safe config/provenance records, `plan.json`, prepared-run metadata, scripts/manifests/log paths, and stage-job planning metadata; do not persist unredacted resolved config snapshots by default; do not eagerly prepare v5 handoff-only worker requests for downstream afterok stages, call `sbatch`, or mark jobs submitted. | resolved; revised during design review |
| What should generated script command bodies run? | Functionality and behavior | Single-job invokes the prepared-run continuation command with a non-SLURM inner executor defaulting to `local`; afterok invokes the generic execution-owned stage job runner command rather than the v5 handoff-only worker command. | resolved; revised during design review |
| What should dry-run manifests record? | Functionality and behavior | Record schema version, run URI, mode, dry-run flag, planning/submission ID, created time, plan path, scripts, wrapper log paths, planned jobs, stage names, attempts, dependency placeholders, worker commands, resource summaries, and SLURM options; job IDs absent/null. | resolved; accepted |
| How should resources map to SBATCH? | Functionality and behavior | Use structured resource classes; map generic CPU, memory, GPU, and SLURM time by default; allow only unambiguous explicit SLURM overrides; deterministic resource/config conflicts fail loudly before generation. | resolved; accepted with emphasis on structured classes and loud conflict failures |
| What should SLURM preflight treat as blocking in v6? | Functionality and behavior | Invalid profile shape, unsafe script/log paths, unsupported resource mapping, unknown mode, or non-shared/local run URI assumption failures are errors; missing `sbatch` is warning/info. | resolved; accepted |
| What SLURM options should v6 model? | Functionality and behavior | Use structured classes for common options: partition, account, qos, constraint, nodes, ntasks, cpus_per_task, mem, mem_per_cpu, gres, time, prelude, and extra_sbatch; keep extra_sbatch as validated escape hatch; do not model every SLURM option. | resolved; accepted |
| How should repeated dry-run outputs be laid out? | Functionality and behavior | Write each dry run into a distinct planning/submission directory under `slurm/submissions/<planning_id>/...`. | resolved; accepted |
| What should CLI output show? | Functionality and behavior | Text reports counts and paths; JSON returns the same facts in a structured envelope; do not print full scripts by default. | resolved; accepted |
| How should v6 reconcile the v5 handoff-only worker with future SLURM afterok finalization? | Design decision review | Add a generic execution-owned stage job runner contract, not a SLURM-specific finalizer; keep v5 handoff-only worker for parent-managed subprocess. | resolved; accepted |
| Should generated scripts assume `loom` is available on `PATH` after prelude, or should v6 add a structured launcher option? | Design decision review | Add a structured launcher argv option, defaulting to `["loom"]`; prelude remains environment setup and generated scripts shell-quote launcher arguments. | resolved; accepted |
| What should happen when SLURM dry-run targets an existing run directory or repeated planning attempt? | Design decision review | Follow normal run safety defaults: omitted run URI creates new run; existing run without `--resume` fails; `--resume` replans through normal semantics into a new planning directory; active/unsafe locks fail. | resolved; accepted |
| What should generated single-job scripts use as their command source of truth? | Design decision review | Use a separate prepared-run continuation command; do not replay original config CLI inputs or use persisted unredacted resolved config. | resolved; revised during design review |
| How should prepared-run continuation handle config and environment secrets? | Design decision review | Persist artifact-safe/unresolved or redacted records; leave environment-dependent values unresolved in artifacts; pass values through process environment at job start; fail clearly if required environment values are missing. | resolved; accepted as v6 scope |
| What exact CLI spelling should prepared-run continuation use? | Design decision review / CLI phase shaping | Use `loom prepared-run continue --run-uri RUN_URI --executor local`, unless implementation-plan review finds a blocking parser issue. | resolved; accepted |
| Should afterok dry-run eagerly write worker preparation metadata? | Design decision review | No. Eager v5 worker request preparation cannot bind downstream inputs before upstream jobs run. Record planned stage jobs and let the generic stage job runner bind inputs at job start. | resolved; accepted |
| How should dry-run manifests represent afterok dependencies before scheduler job IDs exist? | Design decision review | Use deterministic logical job keys and `dependency_job_keys`; scheduler job IDs are absent/null in v6 and added by v7. | resolved; accepted |
| How strict should structured SLURM option parsing be around unknown fields and `extra_sbatch`? | Design decision review | Reject unknown structured fields; allow unknown scheduler flags only through validated `extra_sbatch`; reject conflicts with generated/modeled SBATCH directives. | resolved; accepted |
