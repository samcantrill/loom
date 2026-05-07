# Roadmap v5 Planning Notes: Stage Worker And Subprocess Execution

## Metadata

- Roadmap version: v5
- Source roadmap: `docs/implementation-plans/implementation-roadmap.md`
- Previous version status: v4 assumed complete per user instruction during v5
  roadmap framing. V5 planning may depend on the full
  `docs/implementation-plans/implementation-plan-v4.md` outcome, including
  `RunOptions`, resolved per-stage runtime handoff, executor descriptors and
  capabilities, runtime/resource preflight checks, and persisted `runtime.json`
  metadata.
- Planning notes status: implementation-plan draft created
- Current discussion stage: Handoff complete
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Feature brainstorming: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: confirmed; stop before design review
  - Design decision review: confirmed
  - Phase shaping: confirmed
  - Handoff: confirmed; implementation-plan draft created
- Related implementation plans:
  - `docs/implementation-plans/implementation-plan-v4.md`
- Related feature docs:
  - `docs/features/execution.md`
  - `docs/features/reliability.md`
  - `docs/features/state.md`
  - `docs/features/run-store.md`
  - `docs/features/cli.md`
  - `docs/features/preflight.md`
  - `docs/features/testing.md`
- Blockers:
  - None known for planning. V5 implementation should not begin until the
    assumed v4 work is actually complete and the normal plan quality gate has
    passed for the v5 implementation plan.

## Roadmap Extraction

Baseline roadmap outcome:

- Add the process-isolated execution substrate that later executor adapters can
  reuse.
- Define stage execution request/result records for exactly one prepared stage
  attempt.
- Add `loom stage run --run-dir RUN_DIR --stage STAGE` or equivalent run-URI
  worker command as the stable single-stage worker entry point.
- Add stage-worker APIs that read prepared run metadata, execute one stage,
  write outputs through store contracts, and persist a structured result.
- Add `SubprocessExecutor` using the same stage contract, run store, artifact
  store, fingerprint records, and failure files as local execution.
- Add baseline `FailureRecord` behavior for Python exceptions, exit codes,
  signals, log paths, attempt numbers, and timestamps.
- Add log capture, traceback recording, redacted command recording, and
  nonzero exit-code mapping.
- Add preflight checks for worker command availability and subprocess executor
  capability support.
- Add fake-command and synthetic-stage tests without real cluster or container
  requirements.

Prerequisites:

- v0 local runtime kernel: static DAG planning, local in-process execution,
  stage context construction, local run/artifact stores, status records,
  fingerprints, provenance, logs, failures, and same-run-directory resume.
- v1 config composition: rebuildable authored config/source records available
  from persisted run metadata.
- v2 CLI core: functional `loom` entry point and command delegation to Python
  APIs.
- v3 local diagnostics and preflight: run status, logs, artifact inspection,
  and stable preflight result/check infrastructure.
- v4 runtime options and resources, assumed complete for this planning pass:
  normalized invocation policy, executor descriptors/capabilities,
  per-stage resolved runtime handoff, and safe `runtime.json` metadata.

Primary feature docs:

- `execution.md`
- `reliability.md`
- `state.md`
- `run-store.md`
- `cli.md`
- `preflight.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- SLURM script planning and submission.
- Docker, Apptainer, and container command construction.
- Automatic retries, retry policy, rich failure categorization, and cleanup
  policy beyond baseline failure records.
- Timeout enforcement beyond recording process result metadata, unless planning
  later confirms a minimal bounded timeout behavior for v5.
- Parallel local scheduling or worker pools.
- Remote stores, run catalogs, run bundles, sweeps, plugin discovery,
  dashboards, and domain-specific worker behavior.

Compatibility obligations:

- Keep `loom` domain-neutral.
- Keep pipeline specs semantic and portable across local, subprocess, SLURM,
  and container execution.
- Preserve the source-tree and import boundaries in `docs/structure.md`:
  execution coordinates runner lifecycle, executors own backend invocation, run
  stores own persisted state layout, artifact stores own artifact persistence,
  CLI remains an outer presentation layer.
- Treat authored configs and persisted run metadata as trusted project code, but
  do not require pickled Python objects or opaque command-line payloads for the
  worker contract.
- Use run-store and artifact-store APIs instead of path walking where public
  APIs exist.
- Keep default tests local, synthetic, and network-free.
- Keep the worker command stable enough for v6 SLURM planning and later
  container executors to invoke.
- Do not make subprocess execution affect semantic fingerprints differently
  from equivalent local execution unless an explicit future policy says so.

## Version Briefing

What this version is:

- V5 is the first process-isolated execution version. It turns the local
  in-process runner foundation into a reusable one-stage worker contract and a
  subprocess executor that can launch that worker, collect logs, read
  structured results, and persist failures through the same durable run-store
  surface used by local execution.

Why this version exists:

- V0 through v4 establish local execution, inspection, preflight, and a typed
  runtime/options surface, but stages still run in the coordinator process. V5
  closes the next operational gap: a stage must be executable in a separate
  process from durable run metadata alone. That is the bridge needed before
  SLURM scripts, live scheduler operations, and container executors can invoke
  Loom stages without duplicating runner internals.

Impacted or linked work:

- Direct predecessor: v4 runtime options/resources. V5 should consume the
  resolved per-stage runtime handoff rather than reinterpreting raw
  config/profile/CLI inputs.
- Direct successor: v6 SLURM script planning. V6 generated scripts should be
  able to invoke the v5 worker command or whole-run entry points instead of
  embedding stage logic.
- Later links: v7 live SLURM operations, v14 Docker executor, v15
  Apptainer/SLURM-container composition, and v16 reliability policies all
  depend on stable stage attempt, log, failure, and executor metadata records.
- Current diagnostics link: v3 `loom status`, `loom logs`, and artifact
  inspection should be able to explain subprocess failures using the same public
  store-backed inspection paths.

Likely public surfaces and durable artifacts:

- Public Python APIs for stage execution request/result records and worker
  execution helpers.
- Executor API changes for `SubprocessExecutor` and possibly shared
  executor-facing request/result fields.
- CLI surface for `loom stage run`.
- Preflight check IDs for worker command availability and subprocess executor
  support.
- Persisted stage attempt result records, failure records, log files,
  traceback files, and executor metadata files.
- Exit-code mapping for the worker command and parent subprocess executor.

Structure rationale:

- The version is intentionally shaped around one primary outcome: executing one
  prepared stage attempt in another process with equivalent persisted semantics
  to local execution. This keeps the scope reviewable while creating the stable
  contract later scheduler and container adapters need.
- The planning discussion should first confirm which exact worker and
  subprocess behaviors are in scope, then separately review design decisions
  around request/result ownership, parent/worker commit boundaries, attempt
  layout, command construction, log capture, failure semantics, preflight, and
  test strategy.

Visible assumptions, risks, and constraints:

- Assumption: v4 provides normalized `RunOptions`, resolved per-stage runtime
  handoff data, executor descriptors/capabilities, and safe runtime metadata
  before v5 implementation begins.
- Assumption: a worker can reconstruct enough state from the run directory and
  resolved config/source records to execute one selected stage without passing
  pickled objects over the command line.
- Risk: parent process and worker process may both try to own status/failure
  finalization unless the commit boundary is explicit.
- Risk: persisted attempt layout may need to support future retries and
  scheduler/container metadata without implementing v16 reliability too early.
- Risk: log capture can leak secrets if command, cwd, or environment summaries
  are recorded too broadly.
- Risk: subprocess behavior can become a second runner if it performs planning,
  whole-run finalization, or unrelated stage mutation.
- Constraint: default tests must use fake commands and synthetic stages rather
  than real clusters, containers, network, or downstream project packages.

User clarification questions and resolved answers:

- User had no clarification questions about the startup v5 briefing.
- User confirmed v5 should optimize first for a stable future-executor contract,
  with local debugging strong enough to validate the contract and behavior.

## User Intent

Target audience:

- Loom maintainers, future executor-adapter authors, and downstream users who
  need subprocess execution to behave like a debuggable local preview of later
  scheduler/container execution.

User-visible outcome:

- Users can run the same small pipeline through local in-process execution and
  subprocess execution with equivalent persisted semantics, inspect failures and
  logs through existing diagnostics, and rely on `loom stage run` as the stable
  worker command future executors will invoke.

Success criteria:

- `loom run CONFIG --executor subprocess` runs a small serial pipeline through
  the subprocess executor with persisted semantics equivalent to local
  in-process execution.
- `loom stage run --run-uri RUN_URI --stage STAGE --attempt N` or the selected
  equivalent directly executes one prepared stage attempt from durable run
  metadata.
- Successful and failing subprocess stages persist status, outputs,
  `result.json`, `failure.json`, stdout/stderr logs, traceback path, executor
  metadata, and enough state for existing v3 inspection commands to debug the
  run.
- The worker command and request/result contract are stable enough for v6 SLURM
  script planning and later container executors to invoke without embedding
  stage internals.

Non-goals:

- SLURM script planning or live submission.
- Docker, Apptainer, or other container command construction.
- Automatic retries, rich failure policy, cleanup/retention policy, or v16
  reliability semantics.
- Timeout enforcement beyond recording process result metadata.
- Parallel scheduling or worker pools.
- Plugin discovery, remote stores, run catalogs, bundles, sweeps, dashboards,
  or domain-specific worker behavior.

Constraints:

- Prioritize future-executor contract stability over the smallest possible
  subprocess implementation.
- Keep debugging behavior strong enough to validate the contract and observable
  behavior.
- Subprocess execution defaults to the current Python executable, current
  environment, and current working directory or configured project root.
- Persist redacted command/executor metadata, not full environment values.
- Default tests use fake commands, synthetic stages, and temporary run
  directories rather than real clusters, containers, network, or downstream
  project packages.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | V4 may be treated as completed for v5 planning. V5 depends on the v4 runtime/options, executor descriptor, per-stage runtime handoff, preflight, and runtime metadata outcomes. User had no clarification questions and confirmed v5 should optimize first for a stable future-executor contract, with local debugging strong enough to validate the contract and behavior. Target audience is Loom maintainers, future executor-adapter authors, and downstream users who need subprocess execution as a debuggable preview of later scheduler/container execution. | Stable future-executor contract first; debugging strong enough to prove equivalent persisted behavior. Keep SLURM, containers, retries, cleanup, sweeps, catalogs, and plugins deferred. | None. | Discover workflows, success criteria, non-goals, constraints, and operational realities. |
| Intent discovery | V5 includes both `loom run CONFIG --executor subprocess` for a serial whole-run path and direct `loom stage run --run-uri RUN_URI --stage STAGE --attempt N` or equivalent for one prepared stage attempt. Done means local and subprocess runs of a simple success/failure pipeline have equivalent persisted semantics, including status, outputs, `result.json`, `failure.json`, stdout/stderr logs, traceback path, executor metadata, and v3 inspection compatibility. | Subprocess defaults to current Python executable, current environment, and current cwd/project root. Persist redacted command/executor metadata. Use fake-command and synthetic-stage tests. | None. | Sort candidate capabilities into include, defer, maybe, and out of scope. |
| Feature brainstorming | User confirmed the proposed include/defer/out-of-scope split. Include stable one-stage worker command, stage execution request/result records, subprocess executor, attempt-aware records, baseline failure metadata, redacted executor metadata, worker/subprocess preflight checks, parent/worker commit boundary, durable metadata reconstruction, worker exit-code contract, fake command runner test support, and v3 diagnostics compatibility. Defer/out of scope timeout enforcement, automatic retries, scheduler/container commands, parallel scheduling, and plugin-discovered executors. No missing v5 capabilities were identified. | Commit now to attempt-aware APIs and records; decide concrete attempt directory layout during behavior/design review. | None. | Confirm concrete functionality, user-visible behavior, defaults, failure behavior, and explicit deferrals. |
| Functionality and behavior confirmation | Confirmed stable public worker minimum is `loom stage run --run-uri RUN_URI --stage STAGE`; public users should not need attempt counts. Parent-launched commands pass the prepared attempt explicitly when available. Parent runner prepares/finalizes state; worker executes one assigned stage attempt and writes Loom-owned result handoff. Worker reconstructs only from durable Loom state. Whole-run subprocess execution is serial in v5. Missing/invalid/conflicting results fail loudly. Preflight checks worker availability and subprocess capability without launching user code. CLI output stays concise with failure log paths. | Keep latest-stage files compatible while adding attempt-aware APIs/records; decide attempt archive layout during design review only if needed. Nonzero worker exit code always fails the stage. Use strong and comprehensive testing/validation. | None for functionality. Design pass must settle exact schemas, file layout, API ownership, and phase boundaries. | Complete checkpoint and reload context before design decision review. |
| Context compaction/reset checkpoint | Functionality and behavior baseline is complete and checkpointed in this notes file. User confirmed checkpoint readiness. | Resume design review from these notes and do not reopen functionality/behavior unless user explicitly asks. | None. | Reload notes, prompt, roadmap, v4 plan, and v5 feature docs; draft the design-decision review queue. |
| Design decision review | Queue drafted from confirmed functionality and behavior; user accepted queue scope. D01-D15 are confirmed, including worker CLI/API/schema, parent/worker boundary, durable reconstruction, latest-stage-compatible layout, subprocess orchestration, failure semantics, metadata privacy, preflight, CLI UX, import/dependency policy, testing obligations, deferred work, and trust/security assumptions. | Testing is a plan-quality gate input. Deferred behavior must be documented with later-version owners and revisit triggers. V5 provides metadata privacy but no sandboxing. | None for design review. | Shape reviewable implementation phases. |
| Phase shaping | User confirmed five phases are the right granularity; preflight/diagnostics should remain its own phase; final hardening/docs should remain its own phase. Each phase needs comprehensive component-level testing, and the version needs examples demonstrating behavior and functionality. User confirmed the detailed phase breakdown is ready for handoff. | Phase sketch keeps contract/persistence, worker CLI, subprocess integration, preflight/diagnostics, and hardening/examples/docs as separate review boundaries. | None. | Draft handoff summary and ask whether to proceed into implementation-plan drafting. |
| Handoff | Handoff source material drafted below. User explicitly confirmed implementation-plan drafting, and `docs/implementation-plans/implementation-plan-v5.md` was created. | The implementation plan is a draft and still requires refinement plus the normal plan quality gate before phase work begins. | None. | Next workflow should refine/review the draft implementation plan before phase execution planning. |

## Brainstormed Capabilities

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Stable one-stage worker command | include | Roadmap requires a durable entry point for subprocess, SLURM, containers, and future remote workers; user confirmed direct worker invocation is required. | Exact run URI vs run-dir spelling and optional flags need confirmation during behavior confirmation. |
| Stage execution request/result records | include | Parent and worker need a typed handoff for one prepared stage attempt; user confirmed persisted `result.json` is part of done. | Must avoid duplicating whole-run planning. |
| Subprocess executor | include | Main v5 executor substrate and bridge to later adapters; user confirmed whole-run subprocess execution is required. | Should use fake command runners in default tests. |
| Attempt-aware result/failure/log records | include | Needed for subprocess debugging, user-confirmed done criteria, and future retry/scheduler work. | Must decide whether v5 introduces attempt directories or preserves existing layout with attempt fields. |
| Baseline failure metadata | include | Roadmap names Python exceptions, exit codes, signals, log paths, attempt numbers, and timestamps; user confirmed persisted failure debug data is required. | Rich retry/failure categories remain v16. |
| Redacted command and executor metadata | include | Needed for debugging subprocess invocations without leaking secrets; user confirmed redacted metadata default. | Environment summaries need strict privacy defaults. |
| Worker/subprocess preflight checks | include | Roadmap names command availability and capability support checks, and user confirmed debugging/contract validation priority. | Should integrate with v4 executor descriptors/capabilities. |
| Explicit parent/worker commit boundary | include | Prevents subprocess behavior from becoming a second runner or double-finalizing status. | Current recommended split: parent prepares and finalizes; worker executes one stage attempt and writes a structured result/failure handoff. |
| Worker reconstruction from durable run metadata | include | Future executors need a command that can run from run URI, stage ID, attempt, resolved config/source records, and prepared stage request. | Do not pass pickled Python objects or opaque payloads on the command line. |
| Worker exit-code contract | include | The parent subprocess executor and shell users need stable interpretation when result files are present or missing. | Candidate codes: 0 completed and wrote result; 1 stage failed; 2 usage/config error; 3 executor infrastructure error; 130 interrupted. |
| Fake process runner / command runner seam for tests | include | Default tests must prove command construction, exit handling, and missing result behavior without launching fragile external systems. | Keep implementation small and local; no dependency-heavy process framework. |
| Direct v3 diagnostics compatibility | include | User confirmed debugging through persisted logs/failure records is part of done. | Prefer existing store-backed status/log/artifact inspection paths over new diagnostic command families. |
| Timeout enforcement | defer | Roadmap defers timeout enforcement beyond basic process result metadata. | Revisit in v16 reliability policies or if subprocess tests require process-kill semantics. |
| Automatic retries and retry attempts | defer | Rich retry policy belongs in v16 reliability; v5 only needs attempt-aware records that do not block future retries. | Use a single explicit attempt by default. |
| Scheduler/container command construction | out of scope | V6, v7, v14, and v15 own scheduler and container behavior. | V5 should only ensure those adapters can invoke the worker contract later. |
| Parallel worker scheduling | out of scope | Parallel local scheduling is deferred in the roadmap. | Serial whole-run subprocess execution is enough to validate the contract. |
| Plugin-discovered executors | out of scope | Plugin discovery is v11. | V5 may consume v4 descriptor/capability contracts but should not load entry points. |

## Confirmed Functionality And Behavior

Included functionality:

- Stable direct worker command with `--run-uri RUN_URI` and `--stage STAGE` as
  the stable public minimum identity. Public direct worker use should not
  require users to know how many attempts have completed or been tried.
  Parent-launched subprocesses and future scheduler/container commands should
  pass the prepared attempt explicitly when available.
- Parent/worker execution split where the parent runner prepares and finalizes
  stage lifecycle, while the worker executes exactly one assigned stage attempt
  and writes structured handoff records.
- Structured worker result handoff written by Loom worker plumbing, not by
  user-authored stage code. The handoff records what happened in the isolated
  process; the parent runner reads it and performs durable state mutation.
- Attempt-aware APIs and records that remain compatible with the latest-stage
  file layout unless design review finds a strong reason to introduce
  `stages/<stage>/attempts/<n>/...` immediately.
- Log and executor metadata capture with privacy-preserving defaults.
- Subprocess preflight checks for executor resolution/capability and worker
  command availability, without launching user stage code.
- Worker reconstruction from durable Loom state only: run URI, selected stage,
  prepared request/input/fingerprint metadata, resolved config/source snapshots,
  pipeline spec, artifact/run-store records, and the v4 resolved stage runtime
  handoff.
- Serial whole-run subprocess execution through `loom run CONFIG --executor
  subprocess`, using the same planner as local execution and launching one
  worker process per runnable stage.

User-visible behavior:

- `loom stage run` runs only the requested prepared stage work. It does not
  perform whole-pipeline planning, finalize the whole run, submit scheduler
  jobs, or mutate unrelated stages.
- Users write ordinary stage code that consumes inputs, produces declared
  outputs, or raises exceptions. Users do not need to write code that mutates
  Loom state files or handoff records correctly.
- `loom run CONFIG --executor subprocess` remains serial in v5. It prepares and
  runs stages in planner order through one worker process per runnable stage,
  then finalizes stage and run state through the parent runner.
- Normal CLI output remains concise and similar to local run output. On
  subprocess failure, CLI output shows stage name, exit code, failure message,
  and log paths; detailed command/executor metadata stays in persisted records,
  JSON output, or inspection APIs.

Default behavior:

- `loom stage run --run-uri RUN_URI --stage STAGE` infers the prepared attempt
  only when exactly one unambiguous prepared/running attempt exists for the
  selected stage.
- Internal parent-launched subprocess, scheduler, and container commands pass
  the exact prepared attempt explicitly to avoid races with reruns, stale
  workers, or future retry behavior.
- If a direct worker command omits attempt information and the prepared attempt
  cannot be inferred unambiguously, it fails clearly with a usage/state error
  instead of guessing.
- V5 preserves compatibility with existing latest-stage files for status,
  inputs, outputs, fingerprints, failures, provenance, and diagnostics unless a
  later design decision explicitly selects attempt subdirectories for a bounded
  reason.
- Worker commands do not receive pickled Python objects, raw stage objects, or
  opaque parent-process payloads.

Failure behavior and diagnostics:

- If a subprocess exits without a structured result, the parent treats it as an
  executor infrastructure failure, records `failure.json` with the exit code,
  logs, redacted command metadata, and a missing-result diagnostic, and marks
  the stage failed.
- Subprocess and worker records capture stdout/stderr paths, traceback path for
  Python exceptions, redacted command, cwd or project root, executable, pid/host
  when available, and whether the environment was inherited.
- Full environment variables are not persisted by default.
- If the structured worker result exists, the parent runner uses it as the
  subprocess handoff. If it is missing, the parent falls back to exit-code/log
  metadata and records an executor infrastructure failure.
- A nonzero worker process exit code makes the stage fail loudly. The parent
  must not let a structured success result override a nonzero process exit.
- If a structured result and process exit code conflict, the parent records a
  diagnostic and treats the outcome as failed. A valid failed-stage result with
  nonzero exit code is the normal stage-failure path.
- Worker exit codes are:
  - `0`: stage succeeded and structured result was written.
  - `1`: stage ran and failed, and structured failure result was written when
    possible.
  - `2`: CLI usage, config, or run-state error before stage execution.
  - `3`: worker infrastructure error.
  - `130`: interrupted.

Explicit deferrals:

- Attempt archive directories unless design review proves they are needed now.
- Timeout enforcement.
- Automatic retries and retry policy.
- Worker pools and parallel scheduling.
- SLURM or container command construction.
- Plugin-discovered executors.
- Remote stores.
- Sweeps, run catalogs, and run bundles.
- Cleanup and retention policy.
- Full environment variable persistence.

Out-of-scope behavior:

- Worker-owned whole-run finalization.
- Worker mutation of unrelated stages.
- Worker-side whole-pipeline planning.
- Pickled object handoff from parent to worker.
- Worker pools or parallel scheduling.
- User-authored mutation of Loom handoff, status, output, failure, provenance,
  or result records.

Testing and validation obligations:

- Strong and comprehensive testing is required for v5 behavior and validation.
- Package coverage for public worker/subprocess execution exports and
  import-boundary expectations.
- Unit coverage for worker command parsing, request/result serialization,
  result schema validation, exit-code mapping, missing/invalid/conflicting
  result handling, redacted metadata, and subprocess command construction.
- Contract coverage for parent/worker commit boundary, run-store/artifact-store
  handoff semantics, result/failure/log metadata records, and v3 diagnostics
  compatibility.
- Integration coverage for worker reconstruction from durable run metadata,
  preflight worker/subprocess checks, serial subprocess runner orchestration,
  stdout/stderr/traceback metadata, and equivalent local/subprocess persisted
  semantics.
- E2E coverage for one synthetic success pipeline and one synthetic failure
  pipeline through both local and subprocess execution.
- Opt-in external-system tests are not required in v5.

Context compaction/reset checkpoint:

- Checkpoint status: complete
- Notes path: `docs/implementation-plans/roadmap-v5-planning-notes.md`
- Resume instruction: Reload this notes file,
  `.codex/prompts/roadmap-version-planning-notes-facilitate.md`,
  `docs/implementation-plans/implementation-roadmap.md`,
  `docs/implementation-plans/implementation-plan-v4.md`, and the v5 primary
  feature docs before continuing. Treat confirmed functionality and behavior as
  stable unless the user explicitly reopens it. Start by drafting the complete
  design-decision review queue implied by the confirmed behavior.
- Functionality and behavior reopened after checkpoint: no

## Design Decision Review Queue

| Decision | Why it matters | User feedback needed | Status |
| --- | --- | --- | --- |
| D01. Worker CLI contract | Defines the stable command future subprocess, SLURM, container, and direct-debug workflows invoke, including `--run-uri`, `--stage`, internal `--attempt`, and metadata/debug flags. | User confirmed `--config` stays out of the stable worker CLI unless design later proves durable run metadata is insufficient. | confirmed |
| D02. Public Python API and module ownership | Determines where `StageExecutionRequest`, worker result records, `SubprocessExecutor`, and helper APIs live, what is exported publicly, and how imports stay cheap and boundary-safe. | User confirmed execution owns request/result and worker APIs; subprocess executor owns process launch and collection. | confirmed |
| D03. Stage request and worker result schemas | Establishes schema-versioned durable records for exactly one prepared stage attempt, including outputs, failures, logs, executor metadata, timestamps, and validation behavior. | User confirmed schema validation remains part of this decision rather than a separate queue item. | confirmed |
| D04. Parent/worker lifecycle and commit boundary | Prevents double-finalization and defines which process prepares attempts, marks state, validates outputs, writes final status, and handles whole-run finalization. | User agreed to minimal stale-worker/result-identity validation and deferring heavier locking/concurrency control. | confirmed |
| D05. Durable worker reconstruction contract | Defines the exact durable Loom state the worker may read: run URI, stage, prepared request/input/fingerprint metadata, resolved config/source snapshots, pipeline spec, artifact/run-store records, and v4 runtime handoff. | User strongly confirmed only durable Loom records are allowed and stages should only require prior stage artifacts. | confirmed |
| D06. Persisted layout and attempt compatibility | Chooses how v5 stores `result.json`, failure records, logs, executor metadata, and attempt-aware data while preserving v0/v3 latest-stage diagnostics and future retry compatibility. | User agreed to keep latest-stage-compatible layout for v5 and defer attempt archive directories. | confirmed |
| D07. SubprocessExecutor orchestration and process-runner seam | Defines serial whole-run subprocess execution, command construction, stdout/stderr capture, fake command runner support, and how executor results flow back to the runner. | User confirmed fake/injectable process runner as a testability contract and allowed an in-memory runner path for tests that executes without spawning. | confirmed |
| D08. Failure, exit-code, and conflict semantics | Makes nonzero exits fail loudly and specifies behavior for missing, invalid, partial, or conflicting structured results, interrupted workers, and infrastructure errors. | User confirmed exit-code handling and failure-record normalization should stay together. | confirmed |
| D09. Logs, executor metadata, and privacy | Controls what debugging metadata is persisted while avoiding full environment or secret leakage: redacted command, cwd/project root, executable, pid/host, log paths, traceback paths, and inherited-env summary. | User confirmed the metadata list is sufficient and full environment persistence remains out of scope. | confirmed |
| D10. Preflight and executor capability integration | Connects v5 subprocess checks to the v3/v4 preflight/check-group and executor descriptor/capability contracts without launching user stage code. | User agreed selected subprocess execution should fail preflight when the worker command or Python executable is unavailable. | confirmed |
| D11. CLI and diagnostics user experience | Keeps normal output local-run-like while ensuring failures show stage, exit code, message, and log paths, with detailed command metadata available through JSON and inspection. | User confirmed direct worker CLI should default to concise human output, with machine-readable output through existing JSON/output conventions. | confirmed |
| D12. Import boundaries and dependency policy | Protects source-tree ownership: CLI remains outer presentation, execution coordinates lifecycle, executors own backend invocation, stores own persistence, and no heavyweight dependencies are added. | User confirmed v5 should add no new heavyweight runtime dependencies. | confirmed |
| D13. Testing and validation strategy | Turns the user-confirmed strong validation requirement into package, unit, contract, integration, and E2E obligations with synthetic stages and fake process runners. | User confirmed testing should be a plan-quality gate input with the proposed suite obligations. | confirmed |
| D14. Future compatibility and accepted debt | Records explicit deferrals for retries, timeout enforcement, worker pools, SLURM/container command construction, plugins, remote stores, cleanup, and full environment persistence, with revisit triggers. | User confirmed no deferred behavior should move into v5, and deferred behavior must be documented as belonging to later versions. | confirmed |
| D15. Security and trust assumptions | Clarifies that authored configs are trusted project code while subprocess command and metadata handling still avoid unnecessary secret persistence and do not imply sandboxing. | User agreed this should remain a dedicated design decision documenting trusted config, no sandboxing, and metadata privacy. | confirmed |

## Design Decisions

| Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Debt and revisit trigger |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D01. Worker CLI contract | Stable public command is `loom stage run --run-uri RUN_URI --stage STAGE`. `--attempt N` is an advanced/internal flag used by parent-launched subprocesses and future scheduler/container commands. Optional metadata/debug flags stay narrow: likely `--executor-name NAME`, `--result-file PATH`, and `--log-level LEVEL`. `--config` is not part of the stable worker CLI unless durable run metadata proves insufficient during design or implementation. | User confirmed `--config` should stay out of the stable worker CLI unless absolutely necessary. | Rejected requiring public users to pass attempt counts; rejected making `--config` a normal worker input; rejected broad worker CLI flags that duplicate whole-run planning/config behavior. | The worker contract should be reconstructible from durable run state and stable identifiers, keeping future executors from embedding parent-process state or raw config merge logic. | Keeps the CLI small and reduces branching between direct debug use and executor-launched use. Avoids making CLI parsing the owner of runtime reconstruction. | Supports subprocess, SLURM, containers, and future remote workers through the same minimal invocation shape. `--attempt` remains available for precise internal launches without burdening public users. | Debt: the exact optional metadata/debug flag list may need minor adjustment during implementation. Revisit if durable metadata cannot reconstruct the worker context or if v6 script planning requires an additional stable flag. |
| D02. Public Python API and module ownership | Execution-owned modules define stage execution request/result contracts and worker orchestration APIs. `loom.pipeline.executors.subprocess` owns subprocess command construction, process launch, log capture, and result collection. CLI remains an outer adapter calling execution APIs. Run stores and artifact stores own persistence APIs and layout. | User confirmed execution should own request/result and worker API, while subprocess executor owns process launch/collection. | Rejected CLI-owned worker logic; rejected having subprocess executor own durable request/result schemas; rejected lower layers importing CLI. | This matches `docs/structure.md` and the execution feature split: execution coordinates lifecycle, executors invoke backends, stores persist state. | Keeps module responsibilities reviewable and avoids a second runner hidden inside the subprocess executor. Public exports can remain typed and import-light. | Later SLURM/container executors can reuse the execution-owned worker contract without depending on subprocess internals. Store-backed reconstruction remains portable across executor backends. | Debt: exact file/module names remain implementation-plan work. Revisit if current source layout after v4 makes a different package split materially simpler while preserving ownership boundaries. |
| D03. Stage request and worker result schemas | Add schema-versioned records for one prepared stage attempt. Request fields conceptually include schema version, run URI, stage name, attempt, bound input refs, expected outputs, fingerprint, log paths, and resolved runtime handoff reference or safe summary. Result fields include schema version, run URI, stage name, attempt, status, outputs on success, failure fields on failure, stdout/stderr/traceback paths, executor metadata, and started/finished timestamps. Schema validation is part of this decision. | User confirmed schema validation should remain inside D03. | Rejected unversioned ad hoc JSON; rejected opaque parent payloads; rejected splitting validation into a separate design decision for v5. | Structured records are the parent/worker handoff and the future executor contract. Schema versioning and validation make invalid, partial, or conflicting handoffs explicit failures instead of ambiguous state. | Centralizes contract validation and makes tests precise across local, subprocess, and future backends. | Future submitted-job, retry, scheduler, and container metadata can extend versioned records without changing the minimal command contract. | Debt: exact JSON field spelling and validation strictness are left to the implementation plan. Revisit when v6/v16 need submitted-job or retry fields. |
| D04. Parent/worker lifecycle and commit boundary | Parent prepares one stage attempt, writes request/input/fingerprint metadata, marks the stage running, launches or delegates worker execution, validates result identity, validates outputs, writes final outputs/failure/provenance/status, and finalizes whole-run state. Worker executes only the assigned attempt and writes the structured result handoff. V5 includes minimal stale-worker/result-identity validation and defers heavier locking/concurrency control. | User agreed after reviewing the implications of deferring heavier locking/concurrency control. | Rejected worker-owned finalization; rejected duplicate parent/worker status mutation; rejected v5-wide locks, leases, compare-and-swap transitions, and multi-coordinator concurrency semantics. | The serial subprocess runner needs clear ownership, not a full scheduler coordination layer. Identity validation catches stale or mismatched worker results without pulling v5 into retry/parallel/remote-store policy. | Reduces race-prone lifecycle duplication and keeps state mutation in one process. Keeps v5 implementation tractable and testable. | Later retry, parallel scheduling, and remote/scheduler work can add stronger locking or leases at the run-store layer without changing the worker command. | Debt: v5 does not promise coherent behavior for two parent runners or duplicate workers racing on the same run URI. Revisit when automatic retries, parallel scheduling, remote stores, or scheduler coordination are implemented. |
| D05. Durable worker reconstruction contract | Worker reconstructs only from durable Loom state: run URI, stage, attempt, prepared request/input/fingerprint metadata, resolved config/source snapshots, pipeline spec, run/artifact-store records, prior stage artifacts, and the v4 resolved runtime handoff. Stages must require only prior stage artifacts and durable Loom records, not parent memory or raw config fallback. | User strongly confirmed durable-only reconstruction and clarified that stages should only require prior stage artifacts. | Rejected `--config` or raw config path fallback as normal worker input; rejected pickled objects, raw stage objects, opaque parent payloads, and parent-process memory dependencies. | Durable-only reconstruction is the core future-executor contract: a subprocess, scheduler job, or container can run the same prepared stage without sharing parent process state. | Makes worker behavior testable through stores and records rather than process state. Keeps lifecycle bugs local to explicit persistence APIs. | Enables SLURM and container workers to invoke the same command from shared durable state. Supports future remote-store work by keeping reconstruction record-driven. | Debt: exact reconstruction API boundaries remain implementation-plan work. Revisit if v6 script planning or remote stores expose a missing durable record. |
| D06. Persisted layout and attempt compatibility | V5 keeps latest-stage-compatible files for status, inputs, outputs, fingerprints, failures, provenance, and diagnostics, while adding attempt fields and schema-versioned request/result records. Full `stages/<stage>/attempts/<n>/...` archive directories are deferred. | User agreed to keep the latest-stage-compatible layout for v5 and defer attempt archive directories. | Rejected introducing full attempt archive directories immediately; rejected ignoring attempt identity in records. | This preserves v0/v3 diagnostics compatibility and avoids broad layout churn while still making attempt identity explicit in v5 records. | Keeps implementation and review scope smaller. Existing status/log/artifact inspection can continue to work with fewer migrations. | Future retry/reliability phases can introduce archive directories when multiple attempts per stage become real behavior. | Debt: latest-stage files do not provide complete multi-attempt history. Revisit when automatic retries, cleanup/retention, or reliability policies are implemented. |
| D07. SubprocessExecutor orchestration and process-runner seam | Production `SubprocessExecutor` remains serial and process-isolating: it builds the worker command, allocates/captures stdout/stderr paths, launches the worker process, reads the structured result, interprets process metadata, and returns an executor result to the parent runner. V5 also includes a fake/injectable process-runner seam and may include an in-memory runner path for tests that executes the worker API in-process without spawning. | User confirmed fake/injectable process runner as a testability contract and said an in-memory runner that does not spawn anything is acceptable. | Rejected making subprocess orchestration a second runner; rejected real process spawning as the only way to test worker behavior; rejected promoting the in-memory runner as the main user-visible subprocess behavior. | The production path must validate process isolation, while tests need deterministic ways to exercise command/result/failure contracts without fragile process management. | Keeps subprocess process-control code thin and testable. Separates command construction/process collection from runner lifecycle finalization. | Future scheduler/container executors can reuse contract tests around command construction and worker handoff while providing their own backend launchers. | Debt: the process-runner seam is a planned testability contract, not necessarily a broad public API. Revisit if downstream executor authors need a stable pluggable launcher API. |
| D08. Failure, exit-code, and conflict semantics | Exit-code handling and failure-record normalization are one decision. `0` with a valid success result is a success candidate, still subject to parent output validation. `1` with a valid failure result is a normal stage failure. `2`, `3`, and `130` map to usage/config/run-state, infrastructure, and interrupted failure paths. Missing or invalid structured results become infrastructure failures. Any nonzero exit with structured success is a conflict and fails loudly. | User confirmed exit-code handling and failure-record normalization should stay together. | Rejected allowing structured success to override nonzero process exit; rejected treating missing result as success; rejected scattering exit-code interpretation across CLI, executor, and runner layers. | The process exit and structured result are one outcome boundary. Keeping them together makes failure behavior predictable and directly testable. | Centralizes subprocess failure policy and reduces ambiguous state transitions. | Later reliability policy can categorize these normalized failures without redefining the worker exit contract. | Debt: v5 records baseline failure metadata but does not implement retry policy or rich failure categories. Revisit in v16 reliability policies. |
| D09. Logs, executor metadata, and privacy | Persist redacted command, cwd or project root, executable, pid when available, host when available, stdout/stderr paths, traceback path, result path, exit code, started/finished timestamps, executor name, nested executor metadata, and whether the environment was inherited. Do not persist full environment values by default. | User confirmed the metadata list is sufficient and full environment persistence remains out of scope. | Rejected full environment persistence; rejected unredacted command metadata; rejected omitting command/log paths needed for debugging future executor behavior. | V5 must be debuggable enough to validate the executor contract without turning run metadata into a secret dump. | Gives diagnostics stable fields while keeping privacy policy simple. | Later executor-specific metadata can live in nested mappings without changing the baseline record. Future environment policy can add explicit opt-in fields. | Debt: environment persistence is intentionally minimal. Revisit when explicit environment overlays, clean-environment modes, or scheduler/container environment capture are designed. |
| D10. Preflight and executor capability integration | Add subprocess checks under the existing preflight/executor capability model. For selected subprocess execution, missing worker command or unresolvable Python executable is a `FAIL`, not a warning. Checks must not launch user stage code. Suggested stable IDs include `executor.subprocess.available`, `executor.subprocess.worker`, and `executor.subprocess.runtime`, with exact IDs settled during implementation planning. | User agreed selected subprocess execution should fail preflight when the worker command or Python executable is unavailable. | Rejected warning-only selected-subprocess failures; rejected preflight checks that execute user stage code; rejected subprocess-only ad hoc validation outside the preflight/check-group model. | A selected executor that cannot launch its worker cannot run correctly, so preflight should report that as a structured failure before execution. | Keeps operational validation centralized in preflight and executor capability contracts. | Future SLURM/container checks can follow the same selected-executor availability pattern. | Debt: exact check IDs and grouping remain implementation-plan details. Revisit when v6/v14/v15 add executor-specific command checks. |
| D11. CLI and diagnostics user experience | `loom run --executor subprocess` keeps normal output close to local run output. Direct `loom stage run` defaults to concise human output and uses existing JSON/output conventions for machine-readable output. On failure, output shows stage, attempt when known, exit code, failure message, stdout/stderr paths, and traceback or failure path. Detailed command/executor metadata remains in persisted records, JSON output, or inspection APIs. | User confirmed direct worker CLI should default to concise human output, with machine-readable output through existing JSON/output conventions. | Rejected verbose default command dumps; rejected machine-only direct worker output; rejected a separate diagnostics command family for v5. | Users need immediate failure pointers without duplicating persisted diagnostics in normal terminal output. | Keeps CLI presentation thin and consistent with local execution. | Existing diagnostics and JSON output can expose richer metadata without changing the worker command contract. | Debt: exact formatting is left to CLI implementation. Revisit if direct worker use becomes a common machine-invoked interface outside parent executors. |
| D12. Import boundaries and dependency policy | Preserve source-tree ownership: CLI adapts arguments to execution APIs; execution owns lifecycle and worker orchestration; executors own backend invocation; stores own persistence; no lower layers import CLI. V5 should add no heavyweight runtime dependencies and should rely on the standard library `subprocess` plus existing local helpers. | User confirmed v5 should add no new heavyweight runtime dependencies. | Rejected adding a process-management framework; rejected moving worker orchestration into CLI; rejected executor modules owning store layout or lifecycle finalization. | The v5 goal is a stable contract, not a dependency expansion. Standard-library process control is enough for the subprocess substrate. | Keeps imports cheap, runtime installation simple, and module responsibilities aligned with `docs/structure.md`. | Future executors can add optional backend dependencies in their roadmap phases without making v5 heavier. | Debt: advanced process features remain minimal. Revisit if later executor phases need a shared optional process abstraction. |
| D13. Testing and validation strategy | Testing is a plan-quality gate input. The implementation plan must require package/import-boundary tests for public exports; unit tests for worker command parsing, schema validation, exit mapping, metadata redaction, command construction, missing/invalid/conflicting results, and preflight behavior; contract tests for parent/worker commit boundary and store handoff; integration tests for durable reconstruction and serial subprocess orchestration; and E2E success/failure pipelines through both local and subprocess execution. Default tests use synthetic stages, fake/injectable runners, in-memory runner support where useful, and temporary run directories, with no external systems. | User confirmed D13 should become a plan-quality gate input with the proposed suite obligations. | Rejected treating tests as a late phase detail; rejected relying only on E2E tests; rejected requiring clusters, containers, network, or downstream project packages in default tests. | V5 is a contract-building version, so tests must validate behavior at schema, lifecycle, store, CLI, and executor boundaries. | Forces reviewable suite obligations into the plan before phase work starts. Reduces the risk of subtle parent/worker drift. | Shared contract tests can later be reused by SLURM/container executors and reliability work. | Debt: no opt-in external-system suite is required in v5. Revisit when scheduler/container executor phases add real backend integrations. |
| D14. Future compatibility and accepted debt | Keep current deferrals in v5: retries and rich failure policy to v16; timeout enforcement to v16 or executor-specific later phases; worker pools/parallel scheduling to later execution/reliability work; SLURM script planning/live operations to v6/v7; Docker/Apptainer command construction to v14/v15; plugin-discovered executors to v11; remote stores to v12/v13; cleanup/retention to v17; full environment persistence to later runtime/executor design; attempt archive directories to retry/reliability work. The v5 implementation plan must document these later-version owners and revisit triggers. | User confirmed no deferred behavior should be promoted into v5 and asked that deferred behavior be documented as implemented in later versions. | Rejected promoting any deferred behavior into v5; rejected vague out-of-scope language without later-version routing; rejected designing retry/timeout/pool behavior early. | V5 should create the worker/subprocess contract without absorbing future roadmap versions. Explicit later-version routing prevents accidental permanent omission. | Keeps v5 scope reviewable while making accepted debt visible. | Later versions have clear hooks and triggers tied to the v5 contract. | Debt: v5 leaves several operational capabilities incomplete by design. Revisit at the named roadmap versions or when a phase discovers the v5 contract blocks a planned successor. |
| D15. Security and trust assumptions | Authored configs remain trusted project code. V5 does not provide sandboxing or untrusted-code isolation. Security/privacy work in v5 is limited to avoiding unnecessary secret persistence: do not persist full environment values by default, redact command metadata, keep detailed executor metadata in structured records, and make the absence of sandboxing explicit in docs and implementation-plan design choices. | User agreed D15 should remain a dedicated design decision documenting trusted config, no sandboxing, and metadata privacy. | Rejected implying subprocess execution is a sandbox; rejected full environment persistence; rejected burying trust assumptions as an unstated implementation detail. | Process isolation is useful for lifecycle/debugging but is not a security boundary. Making this explicit prevents users and future plans from overclaiming v5 guarantees. | Keeps security assumptions easy to review and avoids scattered privacy decisions. | Later container or remote execution phases may add stronger isolation or explicit environment policy without changing v5's trusted-config baseline. | Debt: no sandboxing or untrusted-code execution support in v5. Revisit in container/remote execution phases if the project chooses to support stronger isolation. |

## Practical Design Notes

Public Python API surface:

- Execution owns public request/result records and worker orchestration APIs.
- Subprocess executor APIs own process command construction, launch, log
  capture, and result collection.
- A fake/injectable process runner and optional in-memory worker runner may be
  exposed enough for tests, but are not the primary user-facing subprocess API.
- Exact module names remain implementation-plan work.

CLI surface:

- Stable public worker minimum: `loom stage run --run-uri RUN_URI --stage
  STAGE`.
- Advanced/internal exact-attempt flag: `--attempt N`.
- Narrow optional metadata/debug flags may include `--executor-name NAME`,
  `--result-file PATH`, and `--log-level LEVEL`.
- `--config` is not part of the stable worker CLI unless durable run metadata
  proves insufficient.

Persisted records and file layout:

- Stage request/result records are schema-versioned and describe exactly one
  prepared stage attempt.
- Request records include run/stage/attempt identity, bound inputs, expected
  outputs, fingerprint, log paths, and resolved runtime handoff reference or
  safe summary.
- Result records include run/stage/attempt identity, status, outputs or
  failure fields, log/traceback paths, executor metadata, and timestamps.
- V5 keeps latest-stage-compatible files and records attempt identity in
  schemas; full attempt archive directories are deferred.

Import boundaries and dependencies:

- CLI adapts arguments to execution APIs and remains an outer presentation
  layer.
- Execution owns lifecycle and worker orchestration.
- Executors own backend invocation and process collection.
- Stores own persistence APIs and layout.
- Lower layers do not import CLI.
- V5 adds no heavyweight runtime dependencies; standard library `subprocess`
  and existing local helpers should be sufficient.

Failure modes and diagnostics:

- Parent rejects missing, stale, mismatched, invalid, or conflicting worker
  results loudly.
- V5 does not provide full multi-writer locking or scheduler-style lease
  semantics.
- Exit-code handling and failure-record normalization are one policy surface.
- Nonzero process exits always fail the stage, including conflicts where a
  structured success result exists.
- Missing or invalid structured results are executor infrastructure failures.
- Persisted diagnostic metadata includes redacted command, cwd/project root,
  executable, pid/host when available, stdout/stderr paths, traceback path,
  result path, exit code, timestamps, executor name, nested executor metadata,
  and whether the environment was inherited.
- Full environment values are not persisted by default.
- For selected subprocess execution, missing worker command or unresolvable
  Python executable is a preflight failure.

Extension points and flexibility boundaries:

- Production subprocess execution validates the process-isolated path.
- Fake/injectable and in-memory runners are testability aids for exercising the
  same command/result/failure contracts without fragile process spawning.
- Subprocess preflight follows existing executor/check-group conventions so
  later executors can add analogous availability checks.

Maintainability assessment:

- Maintainability depends on keeping ownership boundaries explicit:
  execution owns lifecycle/worker orchestration, executors own backend
  invocation, stores own persistence, and CLI remains presentation.
- Schema-versioned request/result records and centralized failure normalization
  keep the contract testable.
- Testing obligations are part of the plan-quality gate rather than late
  implementation cleanup.

Extensibility assessment:

- The minimal worker command and durable-only reconstruction contract are the
  extension point for SLURM, container, and future remote workers.
- Nested executor metadata and versioned schemas allow backend-specific
  extensions without changing the public worker command.
- Deferred behavior has named later-version owners and revisit triggers.

Flexibility and expansion assessment:

- V5 keeps flexibility by validating attempt identity without committing to
  full attempt archive directories, retries, pools, or locking semantics.
- Fake/injectable and in-memory runners make the contract testable without
  constraining production executor implementation.

Scalability and future compatibility:

- V5 is serial by design. It is compatible with later scheduler/container
  adapters because the worker command uses stable identifiers and durable
  state.
- V5 is not a concurrency-safe multi-coordinator system; heavier coordination
  belongs to later retry, parallel scheduling, remote-store, or scheduler work.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No full attempt archive directories | Preserves v0/v3 diagnostics compatibility and avoids layout churn before retries exist. | Automatic retries, cleanup/retention, or reliability policies need attempt history. |
| No heavyweight locking or lease semantics | Serial subprocess execution has one parent coordinator; minimal result-identity validation is enough for v5. | Parallel scheduling, retries, remote stores, scheduler coordination, or duplicate-worker recovery. |
| No retry or rich failure policy | Belongs to v16 reliability; v5 only needs baseline failure records and attempt identity. | v16 reliability policies or a prior phase needing retry-aware failure categorization. |
| No timeout enforcement | Timeout policy is executor/reliability work beyond the v5 contract. | v16 reliability or an executor phase that can enforce timeouts. |
| No worker pools or parallel scheduling | V5 validates the one-stage worker contract through serial orchestration. | Later execution/reliability phase introduces parallel scheduling or pools. |
| No SLURM/container command construction | Later executor phases own backend-specific command and submission behavior. | v6/v7 for SLURM, v14/v15 for Docker/Apptainer. |
| No plugin-discovered executors | Plugin discovery belongs to v11. | v11 plugin discovery. |
| No remote stores | Remote store semantics belong to later remote-store roadmap work. | v12/v13 remote-store phases. |
| No cleanup/retention policy | Cleanup is separate operational lifecycle work. | v17 cleanup/retention work. |
| No full environment persistence | Avoids secret persistence and keeps v5 privacy simple. | Later explicit environment overlay, clean environment, scheduler/container environment capture, or opt-in provenance policy. |
| No sandboxing guarantee | Authored configs are trusted project code; subprocess isolation is not a security boundary. | Container/remote execution phases if stronger isolation becomes a product goal. |

## Phase Sketch

### Phase 1 - Contracts And Persistence

Goal:

- Establish the stable request/result/failure contract and persistence surface
  for one prepared stage attempt.

Scope:

- Define stage execution request and worker result records with schema
  versions, validation, and serialization.
- Add baseline failure/result metadata fields for subprocess handoff,
  including attempt identity, log paths, traceback paths, executor metadata,
  timestamps, and status.
- Add or extend run-store/artifact-store APIs needed for prepared attempt
  request/result persistence without path walking from execution code.
- Preserve latest-stage-compatible files while recording explicit attempt
  identity in new/updated records.
- Add metadata redaction helpers needed by persisted executor records.

Out of scope:

- Worker CLI behavior.
- Real subprocess process launch.
- Preflight checks.
- Attempt archive directories and retry history.

Acceptance criteria:

- Request/result/failure records round-trip through the selected serialization
  path and reject invalid, missing, or conflicting required fields.
- Persisted records include run URI, stage, attempt, schema version, timestamps,
  and executor/log/failure fields needed by later phases.
- Store-facing APIs preserve current diagnostics-compatible latest-stage layout.

Test expectations:

- Package: import-boundary tests for new public record/store exports.
- Unit: schema validation, serialization, redaction, missing fields, invalid
  status, and result/failure field combinations.
- Contract: run-store/artifact-store request/result/failure persistence
  contracts.
- Integration: temporary run directory persistence/readback through store APIs.
- E2E: not required in this phase.
- Opt-in: none.

Design impact:

- Creates the durable contract that parent runners, workers, subprocess, and
  future executors share.

Future compatibility:

- Records attempt identity without committing to attempt archive directories,
  leaving retry history to later reliability work.

Alternatives rejected:

- Unversioned ad hoc JSON, opaque parent payloads, CLI-owned state mutation,
  and full attempt archive layout in v5.

Debt introduced:

- Exact attempt history is not preserved beyond latest-stage-compatible records.

Reviewability:

- Focused on pure models, validation, and store API changes before process or
  CLI behavior exists.

### Phase 2 - Worker Execution And Direct CLI

Goal:

- Implement the one-stage worker API and `loom stage run` command against
  durable run metadata.

Scope:

- Add execution-owned worker orchestration APIs that reconstruct one prepared
  stage attempt from durable Loom state.
- Implement direct `loom stage run --run-uri RUN_URI --stage STAGE` with
  advanced/internal `--attempt N` support and narrow metadata/debug flags.
- Implement attempt inference only when exactly one unambiguous prepared/running
  attempt exists.
- Execute stage code through the local stage execution machinery and write the
  structured worker result handoff.
- Implement worker exit codes `0`, `1`, `2`, `3`, and `130`.
- Add fake/injectable and in-memory runner paths for component tests where
  useful.

Out of scope:

- Production subprocess parent orchestration.
- Whole-run subprocess execution.
- Preflight integration.
- Worker-owned final stage/run finalization.

Acceptance criteria:

- Direct worker command executes exactly one prepared stage attempt and does not
  plan the whole pipeline or mutate unrelated stages.
- Worker reconstructs only from durable Loom records and prior stage artifacts.
- Users do not write handoff/status mutation code.
- Worker returns clear usage/state errors for ambiguous or missing attempts.

Test expectations:

- Package: public worker API and CLI import-boundary tests.
- Unit: command parsing, attempt inference, exit-code mapping, durable
  reconstruction errors, and result handoff validation.
- Contract: worker writes only the handoff it owns and respects parent/worker
  commit boundary.
- Integration: direct worker success/failure against temporary prepared runs
  using synthetic stages and in-memory/fake runner support.
- E2E: direct worker smoke success/failure if phase scope permits.
- Opt-in: none.

Design impact:

- Introduces the stable worker entry point future executors invoke.

Future compatibility:

- `--attempt` gives parent/scheduler/container launches precise identity
  without requiring public users to know attempt counts.

Alternatives rejected:

- `--config` as a normal worker input, pickled payloads, worker-side planning,
  and worker-owned finalization.

Debt introduced:

- Direct worker is still tied to local durable run-store semantics; remote store
  concerns remain future work.

Reviewability:

- Isolates worker behavior before adding real subprocess process control.

### Phase 3 - Subprocess Executor And Serial Run Integration

Goal:

- Add production subprocess execution and serial whole-run integration through
  the normal parent runner lifecycle.

Scope:

- Implement `SubprocessExecutor` command construction, worker process launch,
  stdout/stderr capture, result-file location, process metadata collection, and
  structured result readback.
- Wire `loom run CONFIG --executor subprocess` into the existing planner and
  parent runner lifecycle as a serial one-worker-per-runnable-stage path.
- Keep parent-owned final commit semantics: output validation, outputs/failure,
  provenance/status, and run finalization.
- Implement conflict handling where process exit and structured result disagree.
- Use fake/injectable process runner support for deterministic component tests
  and real subprocess integration tests for the production path.

Out of scope:

- Parallel scheduling and worker pools.
- Timeout enforcement.
- SLURM/container command construction.
- Heavy locking, leases, or multi-coordinator semantics.

Acceptance criteria:

- A small success pipeline runs through local and subprocess execution with
  equivalent persisted outputs/status/result metadata.
- A small failure pipeline fails loudly with structured failure metadata,
  stdout/stderr paths, traceback path when applicable, and redacted executor
  command metadata.
- Missing, invalid, stale, and conflicting worker results become explicit
  failures.

Test expectations:

- Package: subprocess executor export/import-boundary tests.
- Unit: command construction, redaction, process result mapping, missing/invalid
  result handling, and conflict semantics.
- Contract: parent/worker commit boundary, result identity validation, and
  failure normalization.
- Integration: serial subprocess orchestration for synthetic success/failure
  pipelines using temporary run directories.
- E2E: `loom run --executor subprocess` success/failure smoke coverage.
- Opt-in: none.

Design impact:

- Proves the worker contract through real process isolation while keeping the
  runner lifecycle parent-owned.

Future compatibility:

- Provides the launch/result pattern later scheduler and container executors
  adapt without reimplementing stage execution.

Alternatives rejected:

- Treating subprocess as a second runner, relying only on in-memory tests, and
  accepting nonzero exits as success when structured result says success.

Debt introduced:

- No parallelism, timeout enforcement, retries, or multi-coordinator safety.

Reviewability:

- Focused on process orchestration and whole-run integration after contracts
  and worker behavior are already established.

### Phase 4 - Preflight, Diagnostics, And CLI UX

Goal:

- Make subprocess execution diagnosable and validate selected executor
  availability before running user stage code.

Scope:

- Add subprocess preflight checks under the existing preflight and executor
  capability model.
- Fail selected subprocess preflight when the worker command or Python
  executable is unavailable.
- Keep checks deterministic and avoid launching user stage code.
- Add concise CLI failure output for worker/subprocess failures, including
  stage, attempt when known, exit code, message, stdout/stderr paths, and
  traceback/failure path.
- Ensure existing v3 diagnostics/status/log/artifact inspection can explain
  subprocess failures from persisted records.
- Support machine-readable output through existing JSON/output conventions.

Out of scope:

- New diagnostics command family.
- Scheduler/container preflight checks.
- Full environment persistence.

Acceptance criteria:

- Selected subprocess preflight reports structured failures for missing worker
  command or Python executable.
- CLI output remains concise and local-run-like in normal runs.
- Failure output points users to persisted logs and failure records.
- Existing inspection paths read subprocess metadata without importing project
  stage code unnecessarily.

Test expectations:

- Package: preflight/check ID import-boundary tests where public.
- Unit: check result construction, selected-executor failure severity, CLI
  formatting, JSON output shape, and no-user-code preflight behavior.
- Contract: diagnostics compatibility with persisted failure/log metadata.
- Integration: CLI/preflight subprocess failure scenarios with controlled PATH
  or fake executable resolution.
- E2E: failure UX smoke coverage through `loom run --executor subprocess`.
- Opt-in: none.

Design impact:

- Separates operability and diagnostics from the core executor wiring.

Future compatibility:

- Establishes the selected-executor availability pattern for SLURM/container
  checks in later versions.

Alternatives rejected:

- Warning-only selected-subprocess availability failures, verbose default
  command dumps, and checks that run user stage code.

Debt introduced:

- Exact check IDs and CLI formatting may evolve with later executor phases.

Reviewability:

- Keeps preflight and diagnostics as their own PR-scale behavior, as confirmed
  by the user.

### Phase 5 - Contract Hardening, Examples, And Documentation

Goal:

- Harden cross-component behavior, provide examples, and document deferred
  later-version behavior and trust assumptions.

Scope:

- Add comprehensive cross-component tests for local/subprocess equivalence,
  worker result validation, failure normalization, stale/mismatched results,
  missing/invalid results, redacted metadata, and diagnostics compatibility.
- Add examples that demonstrate:
  - local vs subprocess success behavior,
  - subprocess stage failure with logs/failure inspection,
  - direct `loom stage run` against a prepared stage,
  - missing/invalid worker result diagnostics where practical.
- Document no sandboxing guarantee, trusted authored configs, privacy defaults,
  and full-environment-persistence deferral.
- Document deferred behavior with later-version owners and revisit triggers:
  retries/failure policy, timeouts, worker pools/parallel scheduling, SLURM,
  containers, plugins, remote stores, cleanup/retention, attempt archive
  directories, and stronger locking.
- Run final validation and prepare the notes needed for implementation-plan
  quality review.

Out of scope:

- Implementing any deferred later-version behavior.
- Real cluster/container examples requiring external systems.
- Network or downstream-project-dependent examples.

Acceptance criteria:

- Component and cross-component behavior has comprehensive test evidence.
- Examples are runnable locally with synthetic/domain-neutral stages.
- Docs explicitly state what v5 does, what it does not do, and which later
  versions own deferred behavior.
- Plan-quality-gate inputs are clear for the implementation plan.

Test expectations:

- Package: final public export/import sweep.
- Unit: targeted regression tests for hardening gaps found in prior phases.
- Contract: executor contract tests covering local/subprocess equivalence and
  parent/worker boundaries.
- Integration: durable reconstruction, diagnostics, and subprocess orchestration
  edge cases.
- E2E: synthetic success and failure pipelines through both local and
  subprocess; example smoke tests where practical.
- Opt-in: none.

Design impact:

- Converts design decisions into verified behavior and user-facing examples.

Future compatibility:

- Documentation gives later roadmap versions explicit ownership of deferred
  behavior.

Alternatives rejected:

- Shipping the contract without examples, treating docs as implicit, or
  deferring cross-component validation.

Debt introduced:

- Examples remain local/synthetic until later executor phases add real backend
  examples.

Reviewability:

- Dedicated hardening phase keeps broad verification and documentation changes
  out of earlier implementation PRs.

## Handoff Summary

Implementation-plan draft source material:

- Primary planning notes: `docs/implementation-plans/roadmap-v5-planning-notes.md`
- Roadmap source: `docs/implementation-plans/implementation-roadmap.md`
- Assumed predecessor plan: `docs/implementation-plans/implementation-plan-v4.md`
- Primary feature docs:
  - `docs/features/execution.md`
  - `docs/features/reliability.md`
  - `docs/features/state.md`
  - `docs/features/run-store.md`
  - `docs/features/cli.md`
  - `docs/features/preflight.md`
  - `docs/features/testing.md`
- Architecture boundary source: `docs/structure.md`

Confirmed v5 outcomes:

- Stable one-stage worker command and execution-owned worker API.
- Schema-versioned stage request/result/failure handoff records for one
  prepared stage attempt.
- Durable-only worker reconstruction from Loom records and prior stage
  artifacts.
- Parent-owned final lifecycle commit; worker writes structured handoff only.
- Latest-stage-compatible persistence with explicit attempt identity.
- Production subprocess executor with serial whole-run integration.
- Fake/injectable process-runner support and in-memory runner support for tests.
- Strong failure, exit-code, missing-result, invalid-result, and conflict
  semantics.
- Privacy-preserving log/executor metadata with no full environment
  persistence.
- Subprocess preflight and diagnostics integration.
- No new heavyweight runtime dependencies.
- Comprehensive package, unit, contract, integration, E2E, and example
  validation obligations.
- Examples demonstrating local/subprocess success, subprocess failure
  inspection, direct worker execution, and missing/invalid result diagnostics
  where practical.

Implementation phases:

1. Contracts And Persistence.
2. Worker Execution And Direct CLI.
3. Subprocess Executor And Serial Run Integration.
4. Preflight, Diagnostics, And CLI UX.
5. Contract Hardening, Examples, And Documentation.

Explicit deferrals with later-version owners:

- Retries and rich failure policy: v16 reliability.
- Timeout enforcement: v16 or later executor-specific phases.
- Worker pools and parallel scheduling: later execution/reliability work.
- SLURM script planning/live operations: v6/v7.
- Docker and Apptainer command construction: v14/v15.
- Plugin-discovered executors: v11.
- Remote stores: v12/v13.
- Cleanup and retention: v17.
- Full environment persistence: later runtime/executor design.
- Attempt archive directories: retry/reliability work.
- Heavyweight locking/leases: parallel scheduling, retries, remote stores, or
  scheduler coordination.
- Sandboxing or untrusted-code isolation: later container/remote execution
  phases only if made a product goal.

Unresolved assumptions and blockers:

- V5 planning assumes v4 implementation is complete, including `RunOptions`,
  resolved per-stage runtime handoff, executor descriptors/capabilities,
  runtime/resource preflight checks, and `runtime.json`.
- V5 implementation should not begin until the assumed v4 work is actually
  complete and the v5 implementation plan passes the normal plan quality gate.
- No planning blockers are known.

Plan-quality-gate risks to review:

- Public worker CLI and schema stability for future SLURM/container invocation.
- Parent/worker lifecycle boundary and stale-result validation.
- Latest-stage-compatible layout versus future attempt history.
- Comprehensive component and cross-component testing obligations.
- Documentation clarity for deferred behavior, no sandboxing, and metadata
  privacy.

Handoff status:

- User explicitly confirmed implementation-plan drafting.
- `docs/implementation-plans/implementation-plan-v5.md` has been created as a
  draft implementation plan.
- The draft still requires refinement and the normal plan quality gate before
  any phase execution planning or implementation begins.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Does the user have clarifying questions about the v5 version briefing before planning priorities are confirmed? | Roadmap framing | Answer questions before moving to intent discovery. | resolved: no clarification questions |
| What should v5 optimize for relative to the roadmap: stable future-executor contract, local debugging ergonomics, or minimal subprocess implementation? | Roadmap framing and phase priorities | Stable future-executor contract first, with local debugging strong enough to validate the contract. | resolved: confirmed recommended default |
| Which workflows must be supported to consider v5 successful? | Intent discovery | Whole-run subprocess execution plus direct worker invocation for one prepared stage. | resolved: confirmed |
| Which behaviors should be explicit non-goals so v5 does not become v6/v16 early? | Intent discovery | Defer SLURM, containers, automatic retries, rich failure policy, and parallel scheduling. | resolved: confirmed |
| What operational constraints should shape the subprocess contract? | Intent discovery | Default to current Python executable/environment/cwd with redacted metadata and fake-command tests. | resolved: confirmed |
| Should v5 introduce attempt subdirectories now or keep current stage-level files with attempt fields? | Feature brainstorming and persisted layout | Introduce attempt-aware APIs and records; decide layout during behavior/design review. | resolved: defer concrete layout decision |
| Should v5 include parent-runner orchestration only, worker-only APIs only, or both? | Feature brainstorming and review boundaries | Both: whole-run subprocess path plus direct worker API/CLI. | resolved: confirmed |
| Should any timeout behavior be included beyond recording process metadata? | Feature brainstorming and deferrals | No timeout enforcement in v5. | resolved: confirmed no timeout enforcement |
| What is the canonical worker command surface? | Functionality and behavior confirmation | Stable public minimum is `loom stage run --run-uri RUN_URI --stage STAGE`; public direct worker use should not require knowing attempt counts. Parent-launched subprocess/scheduler/container commands pass `--attempt N` explicitly when available. If omitted, infer only when exactly one prepared/running attempt exists; otherwise fail clearly. | resolved: confirmed |
| Which process owns final stage status and commit semantics? | Functionality and behavior confirmation | Parent runner prepares and finalizes; worker executes one attempt and writes structured handoff records. | resolved: confirmed |
| What should happen when a worker exits but no structured result exists? | Functionality and behavior confirmation | Parent records executor infrastructure failure using exit code, logs, command metadata, and missing-result diagnostic. | resolved: confirmed |
| If `loom stage run` omits `--attempt`, how should the worker choose the attempt? | Functionality and behavior confirmation | Infer only when exactly one prepared/running attempt exists for the stage; otherwise fail with a usage/state error. Parent-launched commands should pass `--attempt` explicitly. | resolved: confirmed |
| Should v5 keep latest-stage files or introduce attempt subdirectories immediately? | Functionality and behavior confirmation | Keep latest-stage files compatible with existing diagnostics while adding attempt-aware APIs/records; decide attempt archives later unless design review finds a strong immediate need. | resolved: confirmed |
| What logs and executor metadata should v5 capture by default? | Functionality and behavior confirmation | Capture stdout/stderr paths, traceback path, redacted command, cwd/project root, executable, pid/host when available, and environment inheritance summary; do not persist full environment variables. | resolved: confirmed |
| Should the worker write a structured result handoff file? | Functionality and behavior confirmation | Yes. The worker writes Loom-owned handoff plumbing, not user-authored state mutation code; the parent runner reads it and mutates durable Loom state. | resolved: confirmed |
| What worker exit-code contract should v5 use? | Functionality and behavior confirmation | `0` success, `1` stage failure, `2` usage/config/run-state error, `3` infrastructure error, `130` interrupted. Parent prefers valid structured failure detail but any nonzero process exit makes the stage fail loudly. | resolved: confirmed |
| How should parent handle result/exit-code conflicts? | Functionality and behavior confirmation | Treat conflicts as failure diagnostics. A structured success result cannot override a nonzero process exit. | resolved: confirmed |
| What subprocess preflight behavior belongs in v5? | Functionality and behavior confirmation | Check subprocess executor resolution/capability and worker command availability without launching user stage code. | resolved: confirmed |
| What state may the worker reconstruct from? | Functionality and behavior confirmation | Durable Loom state only: run URI, stage, prepared request/input/fingerprint metadata, resolved config/source snapshots, pipeline spec, artifact/run-store records, and v4 resolved stage runtime handoff. No pickled objects or raw stage objects from the parent. | resolved: strongly confirmed |
| Should whole-run subprocess execution be serial in v5? | Functionality and behavior confirmation | Yes. Use the same planner as local execution, launch one worker process per runnable stage, and defer worker pools/parallel scheduling. | resolved: confirmed |
| What should CLI/debug output show by default? | Functionality and behavior confirmation | Keep normal CLI output concise and local-run-like; on subprocess failure show stage name, exit code, failure message, and log paths, with detailed command/executor metadata in persisted records/JSON/inspection. | resolved: confirmed |
| Is the drafted design-decision review queue complete and correctly scoped? | Design decision review | Review D01-D15 before deciding individual items; add, remove, split, merge, or rescope decisions now. | resolved: user accepted queue |
| What are the implications of deferring heavier locking/concurrency control in D04? | Design decision review | Minimal v5 protection validates run/stage/attempt identity and prepared state before accepting a result; heavier locks, leases, and multi-coordinator concurrency semantics are deferred. | resolved: user agreed |
| Should fake/injectable and in-memory process runners be part of v5? | Design decision review | Include fake/injectable process-runner support as a testability contract, and allow an in-memory runner path for tests while keeping production `SubprocessExecutor` process-isolating. | resolved: confirmed |
| Should exit-code handling and failure-record normalization stay together? | Design decision review | Keep them together in D08 as one outcome-boundary policy. | resolved: confirmed |
| Is the D09 diagnostic metadata list sufficient and should full environment persistence remain out of scope? | Design decision review | Persist redacted command/process/log metadata and inherited-env summary; do not persist full environment values. | resolved: confirmed |
| For selected subprocess execution, should missing worker command or Python executable be a preflight failure? | Design decision review | Treat missing worker command or unresolvable Python executable as `FAIL` for selected subprocess execution. | resolved: confirmed |
| Should direct worker CLI default to concise human output? | Design decision review | Default to concise human output, with machine-readable output through existing JSON/output conventions. | resolved: confirmed |
| Should v5 avoid new heavyweight runtime dependencies? | Design decision review | Use standard library `subprocess` and existing local helpers; add no heavyweight runtime dependencies. | resolved: confirmed |
| Should D13 testing obligations become a plan-quality gate input? | Design decision review | Require package, unit, contract, integration, and E2E obligations in the implementation plan, with default tests using synthetic stages and fake/in-memory runners rather than external systems. | resolved: confirmed |
| Should any D14 deferred behavior be promoted into v5? | Design decision review | No. Keep deferrals and document later-version owners and revisit triggers. | resolved: confirmed |
| Should D15 remain a dedicated design decision? | Design decision review | Yes. Document trusted authored configs, no sandboxing guarantee, and metadata privacy. | resolved: confirmed |
| Is five phases the right v5 implementation granularity? | Phase shaping | Use five phases: contracts/persistence; worker/direct CLI; subprocess serial integration; preflight/diagnostics; hardening/examples/docs. | resolved: confirmed |
| Should preflight and diagnostics be their own phase? | Phase shaping | Keep preflight, diagnostics, and CLI UX as a dedicated phase. | resolved: confirmed |
| Should final hardening/docs be its own phase? | Phase shaping | Keep contract hardening, examples, and documentation as a dedicated final phase. | resolved: confirmed |
| Should v5 include examples demonstrating behavior and functionality? | Phase shaping | Add local synthetic examples for local/subprocess success, subprocess failure and inspection, direct worker execution, and missing/invalid worker-result diagnostics where practical. | resolved: confirmed |
| Is the detailed five-phase sketch ready for handoff? | Phase shaping | Review the expanded Phase Sketch scopes, acceptance criteria, test expectations, design impact, future compatibility, rejected alternatives, debt, and reviewability. | resolved: confirmed |
| Should this workflow proceed into implementation-plan drafting now? | Handoff | Wait for explicit user confirmation before creating or updating `docs/implementation-plans/implementation-plan-v5.md`. | resolved: confirmed and draft created |
