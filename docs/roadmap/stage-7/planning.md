# Roadmap v7 Planning Notes: SLURM Operations

## Metadata

- Roadmap version: v7
- Source roadmap:
  `docs/roadmap.md`
- Previous version status: assumed complete for planning. Per the user request,
  v7 planning treats v6 SLURM script planning as implemented and available:
  dry-run single-job and afterok planning, schema-versioned planned submission
  manifests, deterministic scripts, logical job keys, structured SLURM options
  and resources, prepared-run continuation, and the generic execution-owned
  stage-job runner.
- Planning notes status: confirmed; implementation-plan quality gate passed
- Current discussion stage: Handoff complete
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Feature brainstorming: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: confirmed
  - Design decision review: confirmed
  - Phase shaping: confirmed
  - Handoff: confirmed
- Related implementation plans:
  - `docs/roadmap/stage-6/implementation-plan.md`
- Related feature docs:
  - `docs/features/slurm.md`
  - `docs/features/execution.md`
  - `docs/features/runtime-resources.md`
  - `docs/features/preflight.md`
  - `docs/features/cli.md`
  - `docs/features/run-store.md`
  - `docs/features/state.md`
  - `docs/features/provenance.md`
  - `docs/features/testing.md`
  - `docs/loom.md`
  - `docs/structure.md`
- Blockers:
  - None known for planning. Implementation must still verify that the v6
    contracts assumed above are present on the actual implementation base
    before phase work begins.

## Roadmap Extraction

Baseline roadmap outcome:

- Add optional live SLURM submission and operational commands on top of the v6
  script/submission model.
- Integrate `sbatch --parsable`, job ID parsing, command recording, redacted
  submission metadata, and persisted scheduler facts.
- Handle partial-submission failures with explicit submitted, skipped, and
  failed job records.
- Preserve SLURM stdout/stderr wrapper log path conventions under the run
  directory.
- Add `squeue` and `sacct` status integration where available, with
  capability-aware fallbacks when a cluster lacks one or both commands or when
  accounting data is delayed.
- Add `scancel` cancellation support for submitted jobs.
- Add CLI integration for live submission, job IDs, scheduler-aware status,
  cancellation, and JSON output.
- Add preflight checks for `sbatch`, optional status commands,
  profile-required fields, and writable submission/log directories.
- Add fake-command tests for submission parsing, status mapping, cancellation,
  command failures, and partial-submission recovery.

Prerequisites:

- v0 local runtime kernel: durable run stores, artifact stores, status records,
  plans, provenance, logs, failures, and conservative resume.
- v1 rebuildable config composition: artifact-safe source records and config
  provenance without unredacted secret-bearing snapshots.
- v2 CLI core: thin command wrappers and JSON output conventions.
- v3 diagnostics/preflight: stable preflight result/check models plus local
  run inspection patterns.
- v4 runtime options/resources: normalized `RunOptions`, executor descriptors,
  resource requests, runtime profiles, and safe runtime metadata.
- v5 stage worker/subprocess execution: worker handoff records, logs,
  subprocess failure metadata, and parent-managed stage worker behavior.
- v6 SLURM script planning: dry-run planned submissions, deterministic scripts,
  structured SLURM options/resources, logical job keys, wrapper log paths,
  prepared-run continuation for single-job scripts, and a generic
  self-finalizing stage-job runner for afterok scripts.

Primary feature docs:

- `slurm.md`
- `execution.md`
- `runtime-resources.md`
- `preflight.md`
- `cli.md`
- `run-store.md`
- `state.md`
- `provenance.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- No controller-mode SLURM scheduler loop.
- No job arrays.
- No multi-node MPI orchestration.
- No automatic retry classification or retry execution from accounting state.
- No remote stores or remote artifact synchronization.
- No distributed lock manager.
- No Docker, Apptainer, Singularity, or other containerized SLURM jobs.
- No cross-cluster submission.
- No dashboard or long-running service.
- No default test dependency on a real SLURM cluster.

Compatibility obligations:

- Keep `loom` domain-neutral. Project code owns cluster module setup, conda or
  venv activation, data paths, domain stages, and site policy.
- Preserve `docs/structure.md` boundaries: SLURM command construction,
  scheduler parsing, submission records, status mapping, and cancellation live
  under `loom.pipeline.executors.slurm`; generic lifecycle remains under
  `loom.pipeline.execution`; planning remains the source of RUN/REUSE/SKIP/
  BLOCKED decisions; run stores own persisted layout and path helpers; CLI
  formats API results and must not parse scheduler output directly.
- Extend v6 planned submission manifests rather than replacing them. V7 adds
  live job IDs, raw scheduler output, submitted/partial/failed submission
  state, status snapshots, and cancellation attempts to the existing logical
  job-key model.
- Continue to treat scheduler state as supplementary to Loom state. Scheduler
  `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `TIMEOUT`,
  `OUT_OF_MEMORY`, `NODE_FAIL`, and `DEPENDENCY` records help inspection, but
  they do not replace stage status or provenance written by Loom jobs.
- Persist live scheduler facts as provenance/state, not only terminal output.
- Keep generated scripts, manifests, commands, and scheduler snapshots
  artifact-safe and redacted. Do not persist environment variable values,
  unredacted resolved configs, or raw secret-bearing adapter payloads by
  default.
- Default validation remains local, deterministic, synthetic, and cluster-free
  through fake command runners.

## Version Briefing

What this version is:

- V7 is the first live SLURM operations layer. Assuming v6 has made scripts and
  dry-run manifests deterministic and reviewable, v7 allows Loom to call real
  SLURM CLI commands when the user selects a SLURM executor without `--dry-run`.
  It records what was submitted, maps logical jobs to scheduler job IDs, reports
  scheduler-aware status, and cancels submitted jobs.

Why this version exists:

- V6 proves what Loom would submit without requiring a cluster. That keeps the
  durable script, resource, dependency, and continuation contracts reviewable.
  V7 closes the operational gap: users on a SLURM submit host can submit the
  prepared scripts with `sbatch`, inspect the resulting scheduler state, recover
  from partial submission, and cancel jobs without losing the run-store and
  provenance trail.

Impacted or linked work:

- Direct predecessor: v6. V7 should reuse v6 script builders, planned
  submissions, logical job keys, wrapper log paths, and continuation commands.
  V7 should add scheduler command execution and submitted-state records rather
  than recalculating the plan or regenerating a separate artifact model.
- Direct successor: v8 run catalog and comparison. V7 should leave runs
  inspectable enough for v8 indexing to list submitted, partial, cancelled, and
  failed SLURM runs without needing scheduler access.
- Later links: v15 HPC container execution may wrap the same submitted-command
  model in Apptainer/Singularity command bodies. V16 reliability policies may
  consume v7 scheduler failure categories for retries/timeouts. Cleanup and
  retention work may later use job/cancellation metadata.
- Diagnostics link: v3 status/log inspection should remain useful. V7 adds
  scheduler-aware status paths, but default status should still be able to read
  persisted Loom state without importing project code or requiring a live
  scheduler query.

Likely public surfaces and durable artifacts:

- A small SLURM command runner abstraction for `sbatch`, `squeue`, `sacct`, and
  `scancel`, with fake implementations for tests.
- Public or semi-public result models for `SbatchResult`, scheduler job IDs,
  submitted job records, submission attempts, status snapshots, and cancellation
  results.
- v6 manifest extensions for live submission state: submitted timestamps,
  submit host/user, command argv, job IDs, raw `sbatch --parsable` output,
  scheduler dependency job IDs, failed submission records, status snapshots,
  and cancellation attempt records.
- CLI behavior for:
  - `loom run CONFIG --executor slurm-single-job`
  - `loom run CONFIG --executor slurm-afterok`
  - scheduler-aware status through `loom status RUN_URI --jobs` or
    `loom slurm status RUN_URI`
  - cancellation through `loom cancel RUN_URI --jobs` or
    `loom slurm cancel RUN_URI`
  - JSON output for submission, status, cancellation, and structured errors
- Preflight check IDs for required `sbatch`, optional `squeue`/`sacct`,
  profile-required fields, writable submission/log directories, active old
  submissions, and command-runner capabilities.
- Optional per-job state files under the run directory if needed for efficient
  inspection, with the manifest remaining the source of submitted-job identity.

Structure rationale:

- The roadmap split v6 and v7 because live scheduler operations introduce
  different failure modes from script generation: unavailable commands, parsing
  scheduler output, partial afterok submission, delayed accounting data,
  cancellation ambiguity, and jobs that fail before Loom code starts. These
  concerns are operationally related and can be implemented as one coherent
  plan after v6 establishes the artifact model.
- V7 is likely still one implementation-plan unit because it has one primary
  user-visible outcome: submit, inspect, and cancel SLURM runs using the v6
  submission model. The largest design questions are about state semantics,
  recovery policy, and scheduler command abstraction, not unrelated systems.

Visible assumptions, risks, and constraints:

- Assumption: v7 supports both v6 SLURM modes live: `slurm-single-job` and
  `slurm-afterok`.
- Assumption: live submission remains explicit through executor selection; dry
  run remains available and does not call `sbatch`.
- Assumption: `sbatch --parsable` is the required submission interface. V7
  supports common outputs such as `123456` and `123456;cluster`.
- Assumption: `squeue`, `sacct`, and `scancel` are optional/capability-aware
  where practical, except when a user asks for an operation that inherently
  requires the missing command.
- Assumption: the shared-run-directory model from v6 remains the only supported
  data path.
- Risk: adding a generic `SUBMITTED` state to Loom run/stage status can clarify
  CLI behavior, but it affects status transitions, resume semantics, and
  existing diagnostics. Keeping submitted state only in SLURM manifests is
  smaller, but default status may look less informative before jobs start.
- Risk: afterok submission can fail after earlier jobs have been queued.
  Manifest writes must be incremental and must not lose already-submitted job
  IDs.
- Risk: cancellation is inherently best-effort. Some jobs may already be
  completed, missing, running, or uncancellable; Loom must not claim a full
  cancel when only a partial cancel happened.
- Risk: scheduler status may be unavailable, stale, delayed, or contradictory
  with run-store state. V7 needs clear precedence and uncertainty reporting.
- Risk: re-submitting into a run directory with active old jobs can duplicate
  work or corrupt status. The likely conservative default is to fail loudly
  unless the user cancels or chooses a later explicit force policy.
- Constraint: no Python SLURM dependency and no default real-cluster tests.
- Constraint: no distributed locking by default; v7 may need a conservative
  submitted-job guard, but a general distributed lock manager is deferred.

User clarification questions and resolved answers:

- User had no clarifying questions or corrections about the startup v7
  briefing.
- User accepted the recommended planning priority: optimize v7 for
  conservative operational safety, including clear persisted records, loud
  partial-failure behavior, honest cancellation/status uncertainty, and
  cluster-free fake-command tests by default.

## User Intent

Target audience:

- Loom maintainers, executor-adapter authors, and downstream users who run on a
  SLURM submit host and need Loom to submit, inspect, and cancel jobs while
  preserving run-store/provenance auditability.

User-visible outcome:

- A user can submit a v6-planned SLURM single-job or afterok run, see submitted
  job IDs and manifest paths, inspect persisted and scheduler-aware state, and
  request cancellation without losing track of partial outcomes.

Success criteria:

- Both `slurm-single-job` and `slurm-afterok` support live submission in v7.
- `slurm-afterok` uses upfront DAG submission with scheduler-native
  `afterok` dependencies. The submission pass submits all planned `RUN` jobs in
  topological order, and SLURM holds downstream jobs until dependencies
  complete successfully.
- Scheduler operations are exposed through general Loom commands. Users should
  not need to know or remember a SLURM-specific command group for ordinary
  status or cancellation.
- General status remains persisted-state-first by default; scheduler queries
  are explicit through a jobs/scheduler option such as `loom status RUN_URI
  --jobs`.
- General cancellation can act on submitted jobs through a scheduler option
  such as `loom cancel RUN_URI --jobs`, using the persisted submission records
  to discover which executor/backend owns the jobs.
- Default validation uses fake command runners and local tests.
- Real SLURM tests are part of the implementation as an opt-in, explicitly
  marked, skipped-by-default cluster acceptance suite. The suite should be
  comprehensive enough for maintainers to validate live SLURM behavior on a
  real cluster, not only a two-test smoke check.
- Re-submitting into a run directory with active old submitted jobs fails loudly
  by default.
- Cancellation records per-job cancellation outcomes and updates Loom
  run/stage state only where safe. It must not overwrite final `SUCCEEDED` or
  `FAILED` stage outcomes.
- Selecting `slurm-single-job` or `slurm-afterok` without `--dry-run` submits
  live jobs immediately after generating or updating the v6 submission
  artifacts.
- `--dry-run` remains the non-submitting preview path.
- Live submission writes a draft manifest before calling `sbatch`, then updates
  the manifest after each successful submission.
- Partial afterok submission preserves already-submitted job IDs, marks the
  submission `PARTIAL`, returns nonzero, and directs the user to explicit
  cancellation if they want cleanup.
- Scheduler-aware status falls back from `sacct` to `squeue` to persisted
  manifest state and reports uncertainty rather than inventing a final state.
- For live submission preflight, missing `sbatch` is an error. Missing
  `squeue` or `sacct` is a warning unless the user requested the operation
  that requires that command.
- Cancellation targets all non-terminal submitted jobs in the latest active
  submission, records per-job results, returns nonzero on partial cancellation,
  and leaves completed jobs alone.
- Live submission, scheduler-aware status, and cancellation support concise
  human output plus schema-versioned JSON envelopes.
- When multiple submission directories exist, scheduler-aware status inspects
  the latest submission by default. Cancellation targets only the latest active
  submission unless the user provides a specific submission ID.
- Opt-in real SLURM cluster tests cover both live modes and operational
  behaviors extensively enough to validate live submission, status,
  cancellation, dependency behavior, selected failure paths, and artifact/log
  persistence on a real cluster.

Non-goals:

- Controller-style just-in-time submission, where a durable Loom process polls
  upstream completion and submits downstream jobs later.
- Job arrays, containers, retries, distributed locks, remote stores, and
  multi-node orchestration.

Constraints:

- Keep CLI scheduler operations backend-discovering and executor-neutral at the
  user surface, even though v7 only implements the SLURM backend.
- Do not require real SLURM for default tests.
- Do not query the scheduler from ordinary status unless the user asks for job
  information.
- Do not claim full cancellation when only some scheduler jobs were cancelled.
- Do not silently submit duplicate work over active old jobs in the same run
  directory.
- Do not require a live Loom parent/controller process after afterok submission
  succeeds.
- Do not automatically cancel already-submitted jobs after a partial submission
  failure in v7.
- Do not fail scheduler-aware status solely because accounting data is delayed
  when queue or manifest data can still explain uncertainty.
- Do not treat missing optional status commands as live-submission blockers.
- Do not let the default cancellation command cancel older historical
  submissions when a newer active submission is present.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | V7 planning assumes v6 is complete and treats live submission/status/cancel/recovery as the target roadmap theme. Target audience is Loom maintainers, executor-adapter authors, and downstream SLURM users. User-visible outcome is live submit, inspect, and cancel over v6 artifacts. | Optimize for conservative operational safety; use v6 artifacts as the base; preserve cluster-free default tests; keep scheduler state supplementary. | None. | Discover concrete workflows, success criteria, non-goals, constraints, and operational realities. |
| Intent discovery | Both live modes belong in v7. Afterok uses upfront DAG submission with scheduler-native dependencies. Scheduler operations should use general Loom commands rather than requiring users to know the underlying executor. Real SLURM tests should be included as opt-in validation. Re-submission over active old jobs fails loudly. Cancellation records per-job outcomes and updates Loom status only where safe. | Canonical status/cancel surface is general CLI with explicit jobs/scheduler flags; fake-command/local tests remain required by default; real cluster acceptance tests are skipped unless explicitly enabled; controller-style just-in-time submission is deferred. | None for intent discovery. | Brainstorm candidate capabilities and sort them into include/defer/out of scope. |
| Feature brainstorming | Include live single-job submission, live afterok DAG submission, `sbatch --parsable` runner/job ID parsing, incremental submitted manifests, partial submission diagnostics, scheduler-aware general status, general cancellation, active old submitted-job detection, preflight checks, fake command tests, and an opt-in real SLURM cluster acceptance suite. Defer force/resubmit policy, automatic cleanup/cancel after partial submission, retry policies, and strong distributed/stage-level locks. Exclude controller mode, job arrays, containers, remote stores/artifact sync, MPI/multi-node orchestration, and default real-cluster test requirements. | Manifest remains the submitted-job identity source unless per-job state files prove necessary during implementation. | None for feature brainstorming. | Confirm detailed user-visible behavior, defaults, failure behavior, and explicit deferrals. |
| Functionality and behavior confirmation | Non-dry-run SLURM executor selection submits live jobs immediately. `--dry-run` remains the preview path. Live submission writes a draft manifest before `sbatch` and updates after each successful job. Partial afterok submission preserves already-submitted job IDs, marks `PARTIAL`, returns nonzero, and tells the user to cancel explicitly if desired. Scheduler status falls back from `sacct` to `squeue` to manifest state and reports uncertainty. Missing `sbatch` is a live-submission error; missing `squeue`/`sacct` is a warning unless the requested operation needs it. Cancellation targets non-terminal jobs in the latest active submission, records per-job results, returns nonzero on partial cancellation, and leaves completed jobs alone. Submission/status/cancel all support concise human output and schema-versioned JSON envelopes. Status defaults to latest submission; cancellation defaults to latest active submission unless a specific submission ID is provided. Opt-in real SLURM acceptance tests cover both modes and operational behaviors extensively enough for cluster validation. | No extra `--submit` flag. No automatic cancellation after partial submission. No scheduler query for ordinary status without jobs flag. No default cancellation of older historical submissions. | None. | Record checkpoint, then start design decision review from notes. |
| Context compaction/reset checkpoint | Functionality and behavior are confirmed and should not be reopened unless the user explicitly asks. | Resume design review from `docs/roadmap/stage-7/planning.md`; classify design decisions before asking user-facing questions. | None. | Design decision review. |
| Design decision review | Use a common submitted lifecycle across executors by adding shared `SUBMITTED` run and stage statuses. Recorded recommendations also confirm backend-neutral submitted-operation discovery, scheduler snapshots as supplementary state, explicit partial-submission recovery, fail-loudly active-job guards, general `status --jobs` and `cancel --jobs` CLI surfaces, manifest-owned submitted-job identity, a SLURM command runner with fake-command tests, secret-safe scheduler persistence, and an opt-in real SLURM acceptance suite. | Accept the moderate cross-cutting cost of shared status vocabulary so submitted executors have consistent lifecycle semantics. Scheduler state remains supplementary and does not replace Loom status. | None. | Shape implementation phases. |
| Phase shaping | Seven phases are accepted: submitted lifecycle and registry foundations; SLURM live command and manifest models; live single-job submission; live afterok DAG submission; scheduler-aware status; submitted-job cancellation; preflight, opt-in cluster acceptance, docs, and hardening. Phase 1 isolates the cross-cutting `SUBMITTED` lifecycle change before live scheduler code. Phase 7 includes the comprehensive opt-in real SLURM acceptance suite while default validation stays fake-command and cluster-free. | Keep implementation review slices narrow: generic status/store foundations first, pure SLURM command/manifest models second, then live operations one behavior group at a time. | None. | Handoff and final planning confirmation. |
| Handoff | User confirmed the planning notes were ready for implementation-plan drafting. `docs/roadmap/stage-7/implementation-plan.md` was drafted, refined, reviewed, and passed the plan quality gate. | Phase work still requires a scope-complete phase execution plan before implementation begins. | None. | Phase execution planning. |

## Brainstormed Capabilities

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Live single-job submission | include | Roadmap includes live submission over the stable v6 script model. | Behavior details still need confirmation. |
| Live afterok DAG submission | include | Roadmap includes dependency-aware submission and partial-submission recovery. User confirmed afterok should use upfront DAG submission with scheduler-native dependencies, not controller-style delayed submission. | Submit all planned `RUN` jobs in topological order; downstream jobs receive `afterok` dependency flags. |
| `sbatch --parsable` command runner and job ID parser | include | Required for live submission while keeping tests fake-command based. | Behavior details still need confirmation. |
| Incremental submitted manifest updates | include | Needed to survive partial afterok submission. | Behavior details still need confirmation. |
| Scheduler-aware status using `squeue`/`sacct` | include | Roadmap includes capability-aware status integration, and user wants Loom to be the interface for scheduler operations. | Expose through a general command such as `loom status RUN_URI --jobs`; exact flag spelling remains to be confirmed later. |
| `scancel` cancellation | include | Roadmap includes submitted job cancellation, and user wants Loom to hide executor-specific command details. | Expose through a general command such as `loom cancel RUN_URI --jobs`; partial cancellation semantics still need confirmation. |
| Preflight command availability and profile checks | include | Roadmap includes required/optional command and profile checks. | Strictness defaults need confirmation. |
| Active old submission detection | include | Needed to avoid duplicate jobs in the same run directory. | Confirmed default: fail loudly when active old submitted jobs are detected. |
| Generic submitted-state status vocabulary | maybe | May improve run/status clarity, but affects shared state semantics. | Candidate design decision for later review. |
| Real cluster acceptance tests | include | User wants extensive real SLURM tests as part of implementation so behavior can be validated on a SLURM cluster. | Must be opt-in, skipped by default, isolated from normal validation, and broad enough to cover live submit/status/cancel/dependency/log/artifact behavior. |
| Per-job state files | maybe | Could make status inspection cheaper and easier, but adds another persisted schema. | Keep manifest as source of submitted-job identity unless implementation shows per-job files are needed. |
| Force/resubmit over active jobs | defer | Active old jobs are dangerous and should fail loudly by default. | Revisit after live submission and cancellation are stable. |
| Automatic cleanup/cancel after partial submission | defer | Automatic cancellation after partial submission can surprise users and can itself partially fail. | User can call general cancellation explicitly. |
| Retry policies from scheduler failure categories | defer | Reliability policies belong to v16. | V7 records failure categories but does not retry. |
| Strong distributed or stage-level locks | defer | Roadmap defers distributed locking; v7 only needs conservative submitted-job guards. | Revisit with controller/retry/distributed execution. |
| Controller mode | out of scope | Deferred by roadmap and SLURM feature doc. User confirmed v7 should not add just-in-time downstream submission. | Later design. |
| Job arrays | out of scope | Deferred by roadmap. | Later design. |
| Containerized SLURM jobs | out of scope | Roadmap assigns HPC containers to v15. | Later design. |

## Confirmed Functionality And Behavior

Included functionality:

- Live `slurm-single-job` submission.
- Live `slurm-afterok` upfront DAG submission with scheduler-native `afterok`
  dependencies.
- `sbatch --parsable` command runner and job ID parser.
- Draft-before-submit and incremental-after-success manifest persistence.
- Partial-submission records and diagnostics.
- Scheduler-aware general status and cancellation commands.
- Capability-aware `squeue`/`sacct` status fallback.
- Active old submitted-job detection with fail-loudly default.
- SLURM preflight checks.
- Fake-command tests and an opt-in real SLURM cluster acceptance suite.

User-visible behavior:

- `loom run CONFIG --executor slurm-single-job` submits one live scheduler job.
- `loom run CONFIG --executor slurm-afterok` submits all planned `RUN` jobs in
  topological order with `afterok` dependencies between submitted upstream job
  IDs.
- `--dry-run` remains the non-submitting preview mode.
- CLI submission output reports run URI, submission manifest path, job IDs,
  wrapper log paths, and partial-submission warnings where applicable.
- `loom status RUN_URI --jobs` combines run-store state, scheduler state, and
  manifest state. It reports uncertainty when scheduler facts are unavailable,
  stale, or incomplete.
- `loom cancel RUN_URI --jobs` cancels known non-terminal submitted jobs from
  the latest active submission and reports per-job cancellation outcomes.
- Live submission, scheduler-aware status, and cancellation all support concise
  human output and JSON output with schema-versioned envelopes.

Default behavior:

- Live submission occurs when a SLURM executor is selected without `--dry-run`.
- Live submission writes a draft manifest before `sbatch`.
- The manifest is updated after each successful `sbatch` call.
- Partial afterok submission does not trigger automatic cancellation.
- Scheduler status prefers final accounting data when available, then active
  queue data, then persisted manifest state.
- Missing `squeue`/`sacct` does not block live submission.
- Cancellation does not attempt to cancel completed jobs.
- When multiple submission directories exist, scheduler-aware status reads the
  latest submission by default.
- Cancellation targets only the latest active submission by default.

Failure behavior and diagnostics:

- If `sbatch` is missing, unavailable, returns nonzero, or returns an
  unparseable job ID, the command returns nonzero with a structured
  SLURM submission error.
- If an afterok submission fails after earlier jobs were submitted, Loom marks
  the submission `PARTIAL`, preserves already-submitted job IDs, returns
  nonzero, and tells the user to run a general cancellation command if cleanup
  is desired.
- Re-submission with active old submitted jobs fails loudly by default.
- `loom status RUN_URI --jobs` reports `UNKNOWN` or a warning when scheduler
  status cannot be determined from available sources.
- `loom cancel RUN_URI --jobs` returns nonzero when only some target jobs could
  be cancelled.

Explicit deferrals:

- Automatic cancellation or cleanup after partial submission.
- Force/resubmit policy over active old jobs.
- Retry policies from scheduler failure categories.
- Strong distributed or stage-level locks.
- Default real-cluster test requirement.

Out-of-scope behavior:

- Controller-style just-in-time downstream submission.
- Job arrays.
- Docker, Apptainer, Singularity, or other containerized SLURM jobs.
- Remote artifact synchronization or remote stores.
- MPI or multi-node orchestration.
- Automatic retry from scheduler failure categories.
- Default real-cluster test requirement.

Context compaction/reset checkpoint:

- Checkpoint status: complete; ready for design decision review after context
  compaction/reset.
- Notes path: `docs/roadmap/stage-7/planning.md`
- Resume instruction:
  `continue v7 design review from docs/roadmap/stage-7/planning.md`
- Functionality and behavior reopened after checkpoint: no

## Design Decision Review Queue

| Decision | Classification | Why it matters | Handling | Status |
| --- | --- | --- | --- | --- |
| Shared submitted lifecycle/status vocabulary | needs discussion | Adding generic `SUBMITTED` run/stage statuses affects shared status transitions, resume behavior, CLI output, diagnostics, and future submitted executors. Keeping submitted state only in manifests is smaller, but makes queued work less visible to generic status and future backends. | Add common `SUBMITTED` run and stage statuses for submitted executors. | confirmed |
| Backend-neutral submitted-operation discovery | recorded recommendation | General `loom status RUN_URI --jobs` and `loom cancel RUN_URI --jobs` need to discover the submitted backend without CLI scheduler-specific path walking. | Add a generic submitted-operation/run-store inspection contract that points to backend-specific records; keep SLURM payloads under `loom.pipeline.executors.slurm`. | confirmed |
| Scheduler-aware status reconciliation | recorded recommendation | `sacct`, `squeue`, run-store state, and manifests can disagree or be unavailable. The policy affects diagnostics and user trust. | Treat scheduler facts as supplementary snapshots. Scheduler-aware status may persist scheduler snapshot records under submission metadata, but does not rewrite core Loom run/stage status except through explicit lifecycle or cancellation APIs. | confirmed |
| Partial afterok submission recovery policy | recorded recommendation | Already-submitted jobs may keep running after a later submission fails. The recovery policy affects manifests, CLI guidance, cancellation, and rerun safety. | Keep the user-confirmed policy: write incrementally, preserve submitted job IDs, mark `PARTIAL`, return nonzero, and require explicit cancellation if cleanup is desired. | confirmed |
| Active old submitted-job guard | recorded recommendation | Reusing a run directory with active submitted jobs can duplicate work or corrupt state. | Fail loudly before new live submission when the latest active submission has non-terminal jobs and Loom cannot prove they are terminal or cancelled. Force/resubmit remains deferred. | confirmed |
| General scheduler operation CLI shape | recorded recommendation | Users should not need executor-specific commands for ordinary status/cancel operations, and the CLI must remain a thin presenter. | Use general commands with explicit job options, such as `loom status RUN_URI --jobs` and `loom cancel RUN_URI --jobs`; CLI delegates to backend APIs discovered from submitted-operation records. | confirmed |
| Submission manifest as source of submitted-job identity | recorded recommendation | Multiple persisted job identities would make recovery, cancellation, and later catalogs harder to reason about. | Extend the v6 manifest as the source of submitted-job identity. Per-job state files remain optional implementation support and must not become a second source of truth. | confirmed |
| SLURM command runner abstraction and fake-command testing | recorded recommendation | Live scheduler calls must be testable without a cluster and without CLI parsing scheduler output. | Add a small SLURM command runner/client abstraction for `sbatch`, `squeue`, `sacct`, and `scancel`, with fake implementations for unit/contract/integration tests. | confirmed |
| Secret-safe scheduler persistence | recorded recommendation | V7 adds raw command outputs and scheduler metadata, which can accidentally become a new secret path. | Persist argv, scheduler IDs, redacted command metadata, and bounded raw scheduler output needed for diagnostics; do not persist environment values, unredacted resolved configs, or raw secret-bearing adapter payloads by default. | confirmed |
| Opt-in real SLURM cluster acceptance suite | recorded recommendation | The implementation needs real-cluster validation without making default validation cluster-dependent, and user wants enough coverage to validate SLURM behavior comprehensively on a cluster. | Add an env-gated, skipped-by-default acceptance suite covering both live modes, status, cancellation, dependency behavior, selected failure paths, and artifact/log persistence on a real SLURM cluster. | confirmed |

## Design Decisions

| Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Debt and revisit trigger |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Shared submitted lifecycle/status vocabulary | Add shared `RunStatus.SUBMITTED` and `StageStatus.SUBMITTED` for work accepted by an external submitted executor but not yet started by the Loom runner or stage-job worker. Runs move `PLANNED -> SUBMITTED -> RUNNING -> terminal`; submitted stages move `PENDING -> SUBMITTED -> RUNNING -> terminal`. SLURM job state remains supplementary metadata shown by scheduler-aware status. | User confirmed a consistent common lifecycle is worth the cross-cutting cost. | Keeping submitted state only in SLURM manifests; adding only SLURM-specific submitted metadata; treating scheduler `PENDING` as Loom `RUNNING`; using executor-specific lifecycle concepts per backend. | The user explicitly wants consistent behavior across executors, and v7 general status/cancel commands need a common way to represent externally accepted work. The feature docs reserve submitted results for future cluster executors and already identify `SUBMITTED` as the cleaner status vocabulary if added. | Moderate cross-cutting impact: update status enums, transition helpers, lifecycle writers, run-store parsing tests, diagnostics/status summaries, resume interpretation, CLI output, SLURM submission writes, cancellation updates, and status JSON contracts. The risk is bounded if implemented in an early foundation phase with focused compatibility tests. | Gives future submitted executors, containers, and remote/batch backends a shared lifecycle instead of each inventing queued/pending semantics. Scheduler-specific states still live under backend metadata, so the shared vocabulary stays small. | Debt: `SUBMITTED` adds another non-terminal state that older tooling may not understand. Revisit if a second backend shows the state is too coarse, or if repair/reconcile work needs a richer submitted-operation state machine. |
| Backend-neutral submitted-operation discovery | Add a generic submitted-operation/run-store inspection contract that records backend, mode, submission ID, latest-active pointer or discoverable ordering, active/terminal state, and backend-specific manifest location. SLURM-specific job records, scheduler output parsing, and cancellation/status mechanics remain under `loom.pipeline.executors.slurm`. | Recorded recommendation from repo boundaries and user-confirmed executor-neutral CLI behavior. | CLI path-walking `slurm/submissions/...`; `loom slurm ...` as the required user surface; storing submitted job identity only in ad hoc SLURM files that generic commands cannot discover. | General commands need a backend-neutral way to find the owner of submitted jobs. The CLI docs require thin wrappers over Python APIs and prohibit scheduler parsing in CLI modules. | Keeps CLI simple and avoids coupling future executor operations to SLURM file layout. Requires one small generic abstraction, but prevents repeated executor-specific discovery logic. | Future container, cloud, or batch executors can expose the same inspection/cancel surface by registering submitted-operation records with backend-specific payloads. | Debt: only SLURM implements the backend in v7. Revisit when a second submitted backend arrives to validate the generic fields. |
| Scheduler-aware status reconciliation | Keep core Loom status authoritative. `loom status RUN_URI --jobs` combines run-store final statuses, `sacct` final accounting data, `squeue` active queue data, and manifest state, and reports uncertainty when facts are missing or stale. Scheduler queries may append or update scheduler snapshot records under submission metadata, but do not rewrite core run/stage statuses except through explicit lifecycle or cancellation APIs. | Recorded recommendation from `state.md`, `slurm.md`, and confirmed fallback behavior. | Treat scheduler state as primary Loom status; fail status solely when `sacct` is delayed; silently infer success/failure from manifest-only state; mutate stage `FAILED` from status inspection when the worker never started. | The docs repeatedly state scheduler state supplements Loom state. Preserving that boundary avoids accidental repair or false certainty while still making scheduler facts durable. | Keeps status inspection predictable and side-effect-light for core state. The main maintenance burden is defining snapshot schema and confidence/uncertainty fields. | Later reliability policies can consume scheduler snapshots without changing the v7 inspection contract. A future repair/reconcile command can explicitly opt into status mutation. | Debt: status inspection may show scheduler-terminal failures while core stage status remains `PENDING`/`SUBMITTED` until explicit reconciliation exists. Revisit with v16 reliability or a future repair/reconcile command. |
| Partial afterok submission recovery policy | Write the manifest before submission and update it after every successful `sbatch`. If a later submission fails, preserve already-submitted job IDs, record the failed job and raw error, mark the submission `PARTIAL`, return nonzero, and direct the user to explicit cancellation if cleanup is desired. | User confirmed no automatic cancellation after partial submission. | Roll back by automatically cancelling already-submitted jobs; hide the partial state and ask the user to resubmit; discard failed submission records. | Automatic cleanup can fail partially and can surprise users. Durable partial records make the safest next action explicit. | Keeps recovery logic clear and testable, with one durable source of truth for partial outcomes. | Later force/resubmit, cleanup, and retry work can build on the preserved partial manifest. | Debt: users must run cancellation explicitly after partial failure. Revisit when cleanup/retry policy is designed. |
| Active old submitted-job guard | Before live submission, fail loudly when the run has a latest active submission with non-terminal job records and Loom cannot prove those jobs are terminal or cancelled. Do not submit duplicate work over active old jobs. | User confirmed fail-loudly behavior. | Best-effort overwrite; implicit resubmit into the same run directory; automatic cancellation of old jobs; `--force` in v7. | Duplicate submitted jobs can corrupt run-store status and artifacts. A conservative guard is safer than trying to infer intent. | Centralizes duplicate-work prevention in submission preflight rather than spreading checks across submit/status/cancel code. | Future force/resubmit can be added explicitly with a stronger policy and tests. | Debt: stale manifests can block resubmission until the user cancels or a future repair policy exists. Revisit with force/resubmit or repair-state work. |
| General scheduler operation CLI shape | Use general Loom commands for ordinary scheduler operations: `loom status RUN_URI --jobs` for scheduler-aware inspection and `loom cancel RUN_URI --jobs` for submitted-job cancellation. Keep `loom slurm ...` deferred unless a later executor-specific diagnostic cannot fit the general command model. | User confirmed Loom should be the interface and users should not need to know the underlying executor. | Required `loom slurm status/cancel`; CLI parsing scheduler output directly; adding `loom submit` in v7. | This matches CLI docs and preserves backend discovery through generic APIs. | Reduces duplicated command surfaces and keeps CLI responsibilities presentation-only. | Future submitted executors can reuse the same commands. Executor-specific commands remain available later for diagnostics. | Debt: exact flag spelling is still implementation-level. Revisit only if `--jobs` conflicts with an existing CLI convention. |
| Submission manifest as source of submitted-job identity | Extend the v6 `slurm/submissions/<submission_id>/submission.json` manifest with live job IDs, raw `sbatch --parsable` output, dependency job IDs, status snapshots, cancellation attempts, partial failures, and schema-versioned submitted state. Per-job state files may be generated for convenience but must derive from and point back to the manifest. | Recorded recommendation from v6 logical-job-key model and SLURM docs. | Independent per-job files as canonical state; status commands reconstructing identity from scheduler queries; replacing the v6 manifest model. | V6 already made logical job keys and planned manifests the reviewable contract. V7 should add live scheduler facts to that model instead of introducing a second identity layer. | Keeps recovery and cancellation deterministic. The manifest schema becomes larger, so careful versioning and focused model tests are required. | Later run catalogs, retries, cleanup, and reliability can index submitted, partial, cancelled, and failed jobs from persisted manifests without scheduler access. | Debt: very large DAGs may make manifest reads heavier. Revisit when job arrays, catalogs, or large-scale DAG performance require indexed sidecars. |
| SLURM command runner abstraction and fake-command testing | Add a small command runner/client abstraction under `loom.pipeline.executors.slurm` for `sbatch --parsable`, `squeue`, `sacct`, and `scancel`. The CLI and generic execution layers call higher-level APIs, not subprocess directly. Tests use fake runners by default. | Recorded recommendation from SLURM and testing docs. | CLI subprocess calls; Python SLURM dependency; default tests requiring real SLURM; shelling out from generic execution. | Command execution is the adapter boundary where parsing, raw output preservation, capability detection, and fake tests all meet. | Isolates scheduler variability and keeps parser tests local. | Enables future retry/capability policies and real-cluster acceptance tests without changing CLI. | Debt: fake runners can miss site-specific SLURM behavior. Revisit when opt-in cluster acceptance tests uncover incompatible command output. |
| Secret-safe scheduler persistence | Persist scheduler facts needed for auditability: job IDs, raw job ID output, command argv, return codes, submit timestamps, submit host/user, bounded stdout/stderr snippets, script/log paths, and redacted scheduler metadata. Do not persist environment variable values, unredacted resolved configs, resolver outputs, or raw secret-bearing adapter payloads by default. | Recorded recommendation from v6 secret-boundary decisions and user-confirmed v7 artifact-safety expectations. | Persisting full environment snapshots; writing resolved config values into manifests; storing unlimited raw command output; relying on users to avoid secrets in scheduler metadata. | V7 introduces new operational records, so it must preserve the v6 no-secret persistence boundary. | Keeps persistence reviewable and consistent across generated scripts, manifests, status snapshots, and CLI JSON. | Future backends inherit the same redaction/safe-payload pattern. | Debt: some debugging details may be omitted by default. Revisit when a concrete site needs opt-in expanded diagnostics with explicit redaction policy. |
| Opt-in real SLURM cluster acceptance suite | Add tests that are skipped by default and gated by explicit environment variables or markers. They cover live single-job success, live afterok success, dependency behavior, scheduler-aware status, cancellation, selected scheduler/worker failure paths, wrapper log and manifest persistence, and artifact/run-store state written by real jobs. Fake-command tests remain the default source for exhaustive failure injection that is unsafe or impractical to force on a shared cluster. | User confirmed real SLURM tests should be extensive enough to validate behavior on a cluster. | No real-cluster tests; only minimal smoke tests; default CI requiring SLURM; relying on real tests for every synthetic edge case. | Fake runners validate deterministic edge cases, but real SLURM acceptance coverage is needed to prove the operational contract against an actual scheduler. | Keeps default validation deterministic while giving maintainers a meaningful cluster validation suite. Requires careful markers, environment gates, timeouts, and cleanup safeguards. | Later releases can expand the same opt-in suite for controller mode, arrays, containers, and retry policies. | Debt: real-cluster tests still cannot safely force every scheduler failure category on every site. Revisit when site-specific acceptance profiles or a dedicated CI cluster exist. |

## Practical Design Notes

Public Python API surface:

- Add shared `RunStatus.SUBMITTED` and `StageStatus.SUBMITTED`.
- Add generic submitted-operation records and inspection helpers under
  execution/run-store boundaries so CLI status/cancel can discover submitted
  backends without scheduler-specific path logic.
- Likely under `loom.pipeline.executors.slurm`: command runner, job ID parser,
  submission result records, status records, cancellation result records, and
  SLURM-specific errors.
- Generic lifecycle APIs should be reused from v6 rather than duplicated.

CLI surface:

- Candidate live submission commands reuse `loom run CONFIG --executor
  slurm-single-job` and `loom run CONFIG --executor slurm-afterok`.
- Canonical scheduler inspection should use a general command such as
  `loom status RUN_URI --jobs`; the CLI should discover the submitted executor
  from persisted submission records and delegate to the backend API.
- Canonical scheduler cancellation should use a general command such as
  `loom cancel RUN_URI --jobs`; the CLI should discover submitted job IDs from
  persisted submission records and delegate to the backend API.
- A `loom slurm ...` command group is not the preferred v7 user surface. Defer
  it unless implementation finds an executor-specific diagnostic that does not
  fit the general Loom command model.

Persisted records and file layout:

- Extend v6 `slurm/submissions/<submission_id>/...` layout.
- Record logical job keys and scheduler job IDs together.
- Record raw `sbatch --parsable` output, parsed job ID, command argv, submit
  timestamps, submit host/user, scheduler dependency job IDs, status snapshots,
  cancellation attempts, and partial failure records.

Import boundaries and dependencies:

- No Python SLURM dependency.
- CLI must not parse scheduler command output.
- SLURM code must not decide planner actions or duplicate execution lifecycle.
- Run-store path helpers should own run-relative path safety.

Failure modes and diagnostics:

- Missing `sbatch`.
- `sbatch` nonzero exit.
- Unparseable job ID output.
- Partial afterok submission after earlier jobs were queued.
- Missing dependency job ID.
- Missing or disabled `squeue`/`sacct`.
- Worker never starts.
- Scheduler state conflicts with run-store state.
- Partial cancellation.
- Active old jobs in a run directory.

Extension points and flexibility boundaries:

- Fake command runner for tests.
- Capability-aware status command use.
- Opt-in real-cluster acceptance tests, explicitly marked and skipped by
  default.
- Later retry, controller, job-array, container, and distributed-lock work must
  build on persisted submitted-job identity rather than replacing it.

Maintainability assessment:

- V7 has moderate cross-cutting design impact because `SUBMITTED` becomes part
  of the shared run/stage vocabulary. The risk is acceptable if the first phase
  isolates status enum, transition, store, diagnostics, CLI, and resume changes
  before live SLURM submission is wired in.
- The main maintainability rule is that generic execution/run-store code owns
  submitted lifecycle and backend discovery, while SLURM owns scheduler command
  execution, parsing, and SLURM-specific manifest payloads.
- Scheduler-aware status must remain side-effect-light for core Loom state.
  Persisting scheduler snapshots is acceptable; silently rewriting stage
  success/failure from status inspection is not.

Extensibility assessment:

- A shared `SUBMITTED` lifecycle state and generic submitted-operation records
  make future submitted executors consistent by default.
- SLURM-specific state remains nested under backend payloads, so future
  container, cloud, or batch executors can add their own submitted-job metadata
  without expanding the core status vocabulary for scheduler-specific states.
- The fake-command runner boundary gives later reliability, retry, cleanup, and
  cluster-acceptance work a stable API for command behavior and failure
  injection.

Flexibility and expansion assessment:

- V7 intentionally favors conservative operations over force/resubmit
  flexibility. That keeps the first live scheduler implementation safe and
  inspectable.
- Future force/resubmit, cleanup, retry, repair/reconcile, job-array, and
  controller features can build on persisted submission IDs, job IDs,
  snapshots, and cancellation records.

Scalability and future compatibility:

- Manifest-owned submitted-job identity is appropriate for v7 and reviewable
  for normal DAG sizes. Very large DAGs may later need indexed sidecars or job
  arrays, but those should derive from the manifest instead of replacing it.
- Status queries are explicit through `--jobs`, so ordinary persisted status
  inspection remains cheap and scheduler-free.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Shared `SUBMITTED` status is cross-cutting | Consistent executor lifecycle is more valuable than keeping submitted state hidden in SLURM metadata. | A second submitted backend shows `SUBMITTED` is too coarse, or status/resume semantics become ambiguous. |
| Status inspection records scheduler snapshots but does not reconcile core statuses | Avoids silent repair and false certainty from stale or incomplete scheduler data. | A future explicit repair/reconcile command or v16 reliability policy needs controlled mutation. |
| No force/resubmit over active jobs | Duplicate submitted work can corrupt run-store state and artifacts. | Users need safe resubmission after partial or stale submitted jobs. |
| No automatic cleanup after partial submission | Automatic cancellation can surprise users and can partially fail. | Cleanup/retry policy is designed with explicit user intent and recovery tests. |
| Manifest is canonical for submitted-job identity | Keeps recovery and cancellation deterministic for v7. | Very large DAGs, job arrays, or catalog indexing require derived sidecars. |

## Phase Sketch

### Phase 1 - Submitted Lifecycle And Registry Foundations

Goal:

- Add the shared submitted lifecycle vocabulary and generic submitted-operation
  discovery contract before SLURM live submission uses it.

Scope:

- Add `RunStatus.SUBMITTED` and `StageStatus.SUBMITTED`, transition/display
  helpers, serialization tests, and resume/status interpretation.
- Add lifecycle helpers for marking runs and stages submitted without implying
  they are running.
- Add generic submitted-operation records and run-store helpers for discovering
  the latest submission, latest active submission, backend, mode, submission ID,
  manifest path, and active/terminal state.
- Add diagnostics/inspection shapes so ordinary status can show persisted
  submitted state without scheduler queries.

Out of scope:

- No SLURM command runner, `sbatch`, `squeue`, `sacct`, or `scancel`.
- No live submission.

Acceptance criteria:

- Shared status enums and records round-trip `SUBMITTED`.
- Existing local/subprocess lifecycle semantics remain unchanged.
- Submitted-operation records are backend-neutral and can point to
  backend-specific manifests without CLI path walking.
- Resume/planning treats `SUBMITTED` as non-terminal and not reusable.

Test expectations:

- Package: status, execution, stores, diagnostics, and CLI imports remain
  optional-backend-safe.
- Unit: status parsing/display, transition helpers, lifecycle submit writers,
  and resume interpretation.
- Contract: run-store submitted-operation read/write/discovery behavior.
- Integration: `loom status` can display persisted submitted state without
  scheduler access or project imports.
- E2E: not required beyond status CLI smoke coverage.
- Opt-in: none.

Design impact:

- This is the cross-cutting public lifecycle change and should land before
  SLURM-specific live behavior.

Future compatibility:

- Future submitted executors reuse the same lifecycle and registry.

Alternatives rejected:

- SLURM-only submitted metadata and backend-specific queued lifecycle names.

Debt introduced:

- `SUBMITTED` is intentionally coarse; backend-specific queue/accounting state
  lives in submitted-operation metadata.

Reviewability:

- Review can focus on status/store/diagnostics changes without scheduler
  command behavior.

### Phase 2 - SLURM Live Command And Manifest Models

Goal:

- Extend v6 SLURM planned submissions into live-submission records and add a
  testable SLURM command runner boundary.

Scope:

- Add SLURM command runner/client abstractions for `sbatch --parsable`,
  `squeue`, `sacct`, and `scancel`, plus fake runners for tests.
- Add job ID parser support for `123456` and `123456;cluster`, preserving raw
  output separately.
- Extend v6 manifest models with schema-versioned live fields: submission
  status, submitted timestamps, submit host/user, job IDs, raw command output,
  command return records, dependency job IDs, failed submission records, status
  snapshots, and cancellation attempts.
- Add SLURM-specific errors for command absence, nonzero exit, unparseable job
  IDs, capability unavailability, and manifest update failures.

Out of scope:

- No `loom run` live submission integration.
- No scheduler-aware CLI status or cancellation command behavior.

Acceptance criteria:

- SLURM live records can represent prepared, submitted, partial, failed, and
  cancelled submission outcomes.
- Fake command runners can simulate success, command-not-found, nonzero exit,
  unparseable output, delayed accounting, missing queue data, and partial
  cancellation.
- Raw scheduler output persistence is bounded and secret-safe by default.

Test expectations:

- Package: SLURM module imports do not require scheduler commands.
- Unit: parsers, command result normalization, manifest validation, redaction,
  and error models.
- Contract: manifest schema round-trips and rejects unsafe or inconsistent
  live fields.
- Integration: fake-runner command flows without live `sbatch`.
- E2E: none.
- Opt-in: none.

Design impact:

- Establishes the SLURM adapter boundary for all later live operations.

Future compatibility:

- Later retry/status/cancel policies can consume the same command-result and
  manifest records.

Alternatives rejected:

- CLI subprocess calls, Python SLURM dependencies, and raw unstructured
  manifest append logs.

Debt introduced:

- Fake runners may miss site-specific command quirks until opt-in acceptance
  tests exercise a real cluster.

Reviewability:

- Review is concentrated on pure models, parsers, and fakeable command APIs.

### Phase 3 - Live Single-Job Submission

Goal:

- Make `slurm-single-job` submit one real scheduler job when selected without
  `--dry-run`.

Scope:

- Wire `loom run CONFIG --executor slurm-single-job` to generate/update v6
  artifacts, write a draft manifest, call `sbatch --parsable`, parse the job
  ID, update submitted-operation records, mark the run `SUBMITTED`, and return
  text/JSON submission output.
- Add live-submission preflight for required `sbatch`, writable
  submission/log directories, and active old submitted jobs.
- Preserve `--dry-run` as the non-submitting preview path.

Out of scope:

- No afterok multi-job submission.
- No scheduler-aware status beyond persisted submitted records.
- No cancellation.

Acceptance criteria:

- Non-dry-run `slurm-single-job` submits exactly one job through the command
  runner and records job ID, raw output, script path, log paths, and manifest
  path.
- Missing `sbatch`, failed `sbatch`, or unparseable job IDs return structured
  errors and do not mark the run successfully submitted.
- Re-submission with active old submitted jobs fails loudly.

Test expectations:

- Package: no new import-time scheduler requirement.
- Unit: single-job submission service and preflight branches.
- Contract: CLI JSON envelope and submitted manifest fields.
- Integration: fake-runner live single-job submission, active-job guard, and
  failure paths.
- E2E: CLI fake-runner smoke for live single-job submission.
- Opt-in: real single-job acceptance coverage is added later once full
  status/cancel exists.

Design impact:

- First live operation over v6 artifacts; validates the shared submitted
  lifecycle with one job.

Future compatibility:

- Whole-run container or batch executors can mirror the same submitted-run
  pattern.

Alternatives rejected:

- Adding a separate `loom submit` command or requiring an extra `--submit`
  flag.

Debt introduced:

- Final job outcome still requires later scheduler-aware status or the inner
  runner's run-store updates.

Reviewability:

- One-job path keeps live submission mechanics reviewable before afterok
  partial failure is added.

### Phase 4 - Live Afterok DAG Submission

Goal:

- Make `slurm-afterok` submit planned `RUN` stages as scheduler-dependent jobs
  in topological order.

Scope:

- Submit all planned `RUN` stage jobs up front with scheduler-native `afterok`
  dependencies among submitted upstream job IDs.
- Mark submitted stages `SUBMITTED` with scheduler metadata, preserving
  `PENDING`/`SKIPPED`/`BLOCKED` semantics for non-submitted stages.
- Write and update manifests incrementally after each successful `sbatch`.
- On partial submission, preserve submitted job IDs, mark submission
  `PARTIAL`, return nonzero, and print explicit cancellation guidance.
- Enforce active old submitted-job guard for afterok submissions.

Out of scope:

- No controller-style just-in-time downstream submission.
- No automatic cancellation after partial submission.
- No job arrays.

Acceptance criteria:

- Afterok submissions use scheduler job IDs for dependency flags and logical
  job keys for persisted identity.
- Partial failure records already-submitted jobs and failed jobs without losing
  recovery data.
- Downstream jobs are not submitted when dependencies lack submitted job IDs.

Test expectations:

- Package: unchanged.
- Unit: dependency construction, topological submission order, partial
  submission handling, active-job guard, and stage `SUBMITTED` writes.
- Contract: manifest and CLI JSON for successful and partial afterok
  submissions.
- Integration: fake-runner two-stage and branched DAG submissions, partial
  failures, and resume-safe submitted records.
- E2E: CLI fake-runner smoke for afterok success and partial failure.
- Opt-in: real afterok acceptance coverage is added later once status/cancel
  exists.

Design impact:

- Adds the main operational complexity: multi-job dependency submission and
  partial recovery.

Future compatibility:

- Later retries, cleanup, and job arrays can reuse logical-job to scheduler-job
  mappings.

Alternatives rejected:

- Controller mode, automatic rollback cancellation, and manifest replacement.

Debt introduced:

- Force/resubmit over partial or stale active jobs remains deferred.

Reviewability:

- Review focuses on dependency correctness, incremental persistence, and
  failure behavior.

### Phase 5 - Scheduler-Aware Status

Goal:

- Add general scheduler-aware inspection through `loom status RUN_URI --jobs`.

Scope:

- Add `--jobs` to `loom status`.
- Discover the latest submission through generic submitted-operation records.
- Query SLURM through backend APIs using `sacct` final state first, `squeue`
  active state second, and manifest state last.
- Persist status snapshots under submission metadata without rewriting core
  run/stage statuses.
- Report uncertainty, missing command capability, stale data, and conflicts in
  text and schema-versioned JSON output.

Out of scope:

- No cancellation.
- No default scheduler query for ordinary `loom status`.
- No repair/reconcile mutation of core statuses.

Acceptance criteria:

- `loom status RUN_URI` remains scheduler-free by default.
- `loom status RUN_URI --jobs` shows run/store status, stage status, job IDs,
  scheduler state, dependency state, log paths, and uncertainty warnings.
- Missing `sacct` or delayed accounting does not fail when queue or manifest
  data can explain uncertainty.

Test expectations:

- Package: CLI status remains import-light.
- Unit: scheduler state mapping, precedence, uncertainty, and snapshot
  serialization.
- Contract: status JSON schema with job data and warnings.
- Integration: fake `sacct`/`squeue` scenarios for final, active, missing,
  stale, and contradictory data.
- E2E: CLI fake-runner status for submitted, running, completed, failed,
  dependency-blocked, and unknown jobs.
- Opt-in: real status acceptance coverage is added in final hardening.

Design impact:

- Integrates scheduler facts while preserving Loom state authority.

Future compatibility:

- Reliability and catalog work can consume persisted scheduler snapshots.

Alternatives rejected:

- Scheduler queries by default, scheduler state as primary status, and silent
  core-state repair.

Debt introduced:

- Core stage status may remain `SUBMITTED` while scheduler snapshots report a
  terminal pre-worker failure.

Reviewability:

- Review can focus on read/inspect semantics without cancellation side effects.

### Phase 6 - Submitted-Job Cancellation

Goal:

- Add general submitted-job cancellation through `loom cancel RUN_URI --jobs`.

Scope:

- Add `loom cancel RUN_URI --jobs` and schema-versioned text/JSON output.
- Discover the latest active submission by default, with specific submission ID
  support if implementation already has the selector plumbing.
- Use SLURM `scancel` through backend APIs for non-terminal submitted jobs.
- Record per-job cancellation attempts and outcomes.
- Return nonzero on partial cancellation.
- Mark run/stages `CANCELLED` only where safe and never overwrite final
  `SUCCEEDED` or `FAILED` stage outcomes.

Out of scope:

- No cancellation of older historical submissions by default.
- No automatic cancellation after partial submission.
- No retrying cancellation until success.

Acceptance criteria:

- Cancellation targets known non-terminal jobs and leaves completed jobs alone.
- Partial cancellation is visible in output, JSON, and persisted records.
- Cancellation cannot claim full success when some jobs remain active or
  unknown.

Test expectations:

- Package: CLI cancel imports remain optional-backend-safe.
- Unit: target selection, safe status mutation, cancellation result mapping,
  and partial outcomes.
- Contract: cancellation JSON and manifest cancellation records.
- Integration: fake `scancel` success, partial failure, missing command, and
  terminal-job skip scenarios.
- E2E: CLI fake-runner cancellation smoke.
- Opt-in: real cancellation acceptance coverage and cleanup behavior are added
  in final hardening.

Design impact:

- Adds the main mutating scheduler operation after status semantics are stable.

Future compatibility:

- Cleanup and retry policies can build on per-job cancellation records.

Alternatives rejected:

- Best-effort output-only cancellation and cancellation of all historical
  submissions.

Debt introduced:

- No automatic cleanup workflow or retry loop for failed `scancel` calls.

Reviewability:

- Review can focus on explicit mutation and partial-failure safety.

### Phase 7 - Preflight, Opt-In Cluster Acceptance, Docs, And Hardening

Goal:

- Complete operational validation, documentation, and final edge-case coverage
  for the v7 live SLURM feature set.

Scope:

- Add or finish preflight check IDs for required `sbatch`, optional
  `squeue`/`sacct`, `scancel` when cancellation is requested, profile-required
  fields, writable submission/log directories, active old submissions, and
  command-runner capabilities.
- Add an env-gated, skipped-by-default real SLURM acceptance suite that
  maintainers can run on a cluster.
- Cover at least live single-job success, live afterok two-stage success,
  afterok branch or fan-in dependency behavior where practical, status during
  queued/running work and after completion, a tiny intentional worker failure
  or dependency-blocked path, cancellation of a queued or sleeping job, wrapper
  stdout/stderr log creation, manifest job/dependency/snapshot/cancellation
  records, and ordinary run-store status/output/artifact/failure metadata
  written by real jobs.
- Keep fake-command tests as the deterministic suite for hard-to-force
  scheduler failures such as missing commands, unparseable `sbatch`, partial
  submission at a specific DAG node, contradictory `sacct`/`squeue` results,
  and partial `scancel`.
- Harden docs, examples, structured error messages, JSON schema documentation,
  and fake-command e2e coverage.
- Verify secret-safe persistence across live manifests, command records,
  scheduler snapshots, cancellation records, CLI output, and generated scripts.

Out of scope:

- No default real-cluster requirement.
- No promise that every SLURM site supports every optional acceptance case.
- No controller mode, job arrays, retries, cleanup, remote stores, or
  containers.

Acceptance criteria:

- Default validation remains deterministic, local, and cluster-free.
- Opt-in cluster acceptance tests are clearly documented and impossible to run
  accidentally.
- Acceptance tests can be selected by marker or environment and can skip
  individual cases when a site lacks required optional behavior, while still
  failing loudly for core submit/status/cancel regressions.
- `make validate-pr` and `make test-summary` expectations are clear for phase
  PR preparation.
- Docs explain live submission, dry-run preview, status, cancellation,
  uncertainty, partial submission, and cleanup guidance.

Test expectations:

- Package: full import suite.
- Unit: remaining preflight/error/schema branches.
- Contract: final CLI and manifest schema contracts.
- Integration: fake-command coverage for the full submit/status/cancel flow.
- E2E: local fake-command CLI flows for single-job, afterok, partial failure,
  status, and cancellation.
- Opt-in: real SLURM cluster acceptance suite gated by explicit environment
  variables or markers.

Design impact:

- Consolidates operational evidence and user-facing documentation after core
  behavior lands.

Future compatibility:

- Gives v8 catalog work inspectable submitted/partial/cancelled run records and
  gives later SLURM features a real-cluster acceptance-test scaffold.

Alternatives rejected:

- Requiring real SLURM in default CI, limiting real validation to a tiny smoke
  check, and omitting real-cluster validation entirely.

Debt introduced:

- Real-cluster coverage is extensive but still not a certification matrix for
  every site-specific SLURM configuration.

Reviewability:

- Final phase is documentation, evidence, and edge-case hardening rather than
  new core behavior.

## Handoff Notes

Ready for implementation-plan draft:

- Complete. Draft/refine/quality gate complete at
  `docs/roadmap/stage-7/implementation-plan.md`.

Source notes for draft:

- Confirmed v7 roadmap planning notes in this file.
- `docs/roadmap.md`
- `docs/roadmap/stage-6/implementation-plan.md`
- Primary feature docs listed in metadata, especially `docs/features/slurm.md`,
  `docs/features/execution.md`, `docs/features/state.md`,
  `docs/features/cli.md`, `docs/features/run-store.md`,
  `docs/features/preflight.md`, and `docs/features/testing.md`.
- Confirmed design decisions:
  - shared `RunStatus.SUBMITTED` and `StageStatus.SUBMITTED`;
  - generic submitted-operation registry/discovery;
  - scheduler snapshots supplement core Loom status;
  - manifest-owned submitted-job identity;
  - general `loom status RUN_URI --jobs` and
    `loom cancel RUN_URI --jobs` surfaces;
  - fail-loudly active-job guard;
  - explicit partial-submission recovery with no automatic cleanup;
  - fake-command default tests plus opt-in real SLURM cluster acceptance.

Unresolved assumptions:

- Exact flag spelling for general scheduler status and cancellation commands is
  expected to use `--jobs`; revisit only if implementation finds a parser or
  CLI consistency conflict.

Plan-quality-gate risks:

- State vocabulary changes are intentionally cross-cutting and should be
  isolated in the first phase.
- Partial submission and cancellation semantics require careful persisted
  schema review.
- Status precedence must avoid implying certainty when scheduler data is
  missing or stale.
- The opt-in real SLURM acceptance suite must be comprehensive enough to
  validate live behavior on a cluster while remaining skipped by default and
  safe for shared cluster environments.
