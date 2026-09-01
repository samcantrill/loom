# `loom.pipeline.execution` and Executors Specification

## 1. Purpose

`loom.pipeline.execution` is the layer that performs an already validated and
planned pipeline.

It coordinates run lifecycle, stage context construction, executor invocation,
log capture, output validation, artifact registration, status transitions, and
failure handling. It should not own pipeline graph semantics, resume policy,
artifact identity, or run-store persistence details. Those are defined by the
pipeline, resume, artifact, and run-store specifications.

The execution layer answers one question:

```text
Given a pipeline spec, a run directory, a plan, and an executor, how should loom
perform the selected stages and record what happened?
```

The current design supports local in-process execution and serial subprocess
execution through the durable `loom stage run` worker contract. V6 SLURM
dry-run scripts use `loom prepared-run continue` and `loom stage-job run` as
generic continuation surfaces; live cluster and container execution details in
this document remain future scaffolding unless an implementation plan adds a
phase for them.

V11 queueing is owned by top-level `loom.queue`, not by the execution runner.
The queue dispatches whole runs through configured adapters and records
queue-local scheduling evidence, while authority remains lifecycle truth for
executed runs. See [queue.md](queue.md) for the queue service contract.

An authority-backed runner holds one exclusive controller lease for the whole
run and renews it privately while work is active. A renewal failure is surfaced
before another attempt allocation, output commit, or successful run
finalization. Stage output becomes reusable only after the authority accepts
the fenced output commit; writing a local payload or `outputs.json` is not
success and does not update the active artifact index.

Hard-loss recovery is explicit rather than PID-based. A replacement controller
can proceed only after authority reports expired ownership for both the old
controller and every incomplete active attempt. Recovery records
`INTERRUPTED`/`STALE` lifecycle evidence and events before executing attempt 2.
The earlier incomplete attempt remains diagnostic history, while only the new
successful attempt may publish reusable output and release downstream work.

### 1.1 Alignment With `loom.md`

This document refines stage execution goals from [loom.md](../loom.md). It keeps
execution as a coordinator over an already validated plan: project stages do the
work, stores persist state, executors invoke stages, and the runner records
outcomes without interpreting domain behavior. The local executor runs stage
code in process; the subprocess executor launches the same stage work through a
prepared durable worker request.

---

## 2. Core Position

Execution is a coordinator.

It should use this architecture:

```text
Pipeline spec:
  describes the stage graph and stage contracts

Planner:
  decides stage actions such as RUN, REUSE, SKIP, and BLOCKED

Execution:
  performs RUN actions, records lifecycle transitions, and validates results

Executors:
  run one stage through a backend such as local Python or subprocess

Stores:
  persist run state and artifacts

Project code:
  implements stage behavior
```

This means `loom.pipeline.execution` should not become a second planner, a
store implementation, or a framework for application-specific stage internals.
It should have enough structure to make failures inspectable and enough
restraint to keep stage logic in project code.

---

## 3. Package Boundary

### 3.1 `loom.pipeline`

Owns shared pipeline concepts.

Responsibilities:

```text
PipelineSpec
StageSpec
StageContext
pipeline validation
DAG construction
topological ordering
stage input/output binding
```

The execution layer should consume these concepts rather than redefining them.

### 3.2 `loom.pipeline.planning`

Owns plan construction.

Responsibilities:

```text
compute stage fingerprints
load prior run state
apply resume policy
apply stage selectors
produce stage actions
explain reuse and invalidation decisions
```

Execution should trust the plan as the authority for what to run. It may fail if
the plan is inconsistent with current state, but it should not quietly change
planning decisions.

### 3.3 `loom.pipeline.execution`

Owns runner lifecycle.

Responsibilities:

```text
create or open the run
persist resolved config references
persist the execution plan
construct StageContext objects
bind planned inputs
prepare stage directories
mark stages running, succeeded, failed, skipped, or cancelled
invoke executors
validate executor results
commit stage outputs
update artifact indexes
capture log metadata
finalize run status
```

It should be thin enough that unit tests can cover every lifecycle branch.

### 3.4 `loom.pipeline.executors`

Owns backend-specific stage invocation.

Responsibilities:

```text
local in-process execution
subprocess command construction
process exit handling
executor metadata capture
future cluster or container submission hooks
```

Executors should not decide whether a stage is stale or reusable. They execute a
request and return a result.

### 3.5 `loom.pipeline.stores.run_store`

Owns persisted run state.

Responsibilities:

```text
run directory creation
stage directory creation
status file writes
plan file writes
stage inputs file writes
stage outputs file writes
failure file writes
log path allocation
locking
atomic JSON writes
```

Execution should use the run-store API. It should not manually scatter JSON
writes throughout runner code when the store can own the format.

### 3.6 `loom.pipeline.stores.artifact_store`

Owns artifact storage and registration.

Responsibilities:

```text
allocate managed artifact paths
save artifacts through codecs
register externally written artifacts
verify checksums when requested
load artifact refs
update artifact metadata
```

Execution should validate that declared stage outputs become `ArtifactRef`s, but
the artifact store owns artifact persistence details.

### 3.7 `weave`

Owns configuration composition and object construction.

Responsibilities:

```text
load authored config
apply overlays and CLI overrides
expand recipes
resolve interpolation
provide generic object instantiation helpers outside pipeline stage specs
produce resolved config/provenance data for the runner/run store to persist
```

For v0, pipeline stage mappings are orchestration specs. Execution delegates stage
construction to pipeline-owned helpers, then invokes
`stage.run(context, inputs)`. `weave` should not be imported for stage
construction, and it should not treat stage mappings as generic `_target_` object
graphs or implement config loading rules there.

### 3.8 `loom.cli`

Owns command-line presentation.

Responsibilities:

```text
parse CLI options
load config
select executor
call PipelineRunner
print status and plan summaries
return process exit codes
```

The CLI should call the execution API. It should not implement runner lifecycle
logic directly.

### 3.9 Project Code

Owns stage internals.

Responsibilities:

```text
load domain data
train models
write reports
compute metrics
decide internal checkpointing behavior
return or register ArtifactRef outputs
```

Execution should treat stages as black boxes with explicit inputs, outputs, and
runtime metadata.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
serial execution of a planned DAG
local in-process executor
local execution request/result dataclasses or equivalent typed models
stage lifecycle transitions
input binding persistence
fingerprint persistence handoff
stdout/stderr log path conventions
Python exception capture for local execution
stage output validation
artifact index updates
run finalization
stop-on-first-failure policy
clear execution errors
unit-testable runner lifecycle
```

The first implementation can run stages serially even if the graph has
independent branches. Correctness and inspectability matter more than parallel
scheduling in v0.

### 4.2 Should Not Support in v0

```text
parallel local scheduling
advanced retry policies beyond bounded total attempts
timeout enforcement
dynamic DAG mutation
continue-on-failure for independent branches
subprocess executor implementation
subprocess executor command contract
stage-worker command entry point
distributed locks
remote run stores
remote artifact stores
Docker execution
Apptainer execution
SLURM afterok submission details
SLURM controller mode
rich dashboard output
automatic cleanup of all temporary files
```

These features need stable lifecycle semantics first. The execution API should
leave clear extension points without implementing all backends immediately.

---

## 5. Terminology

### 5.1 Runner

The high-level object that performs a pipeline run.

Recommended public name:

```text
PipelineRunner
```

The runner coordinates planning, stores, executors, lifecycle, and final
results. It should be the primary Python API for running pipelines.

### 5.2 Executor

An object that performs one stage execution request through a backend.

Examples:

```text
LocalExecutor
SubprocessExecutor, post-v0
SlurmExecutor, later
DockerExecutor, later
```

The executor should not mutate high-level pipeline state except through the
stage code it invokes. The runner remains responsible for status transitions and
result validation.

### 5.3 StageExecutionRequest

The structured request passed from the runner to an executor.

It includes:

```text
run identity
stage identity
stage spec
stage object or stage target
stage context
bound inputs
expected outputs
fingerprint
attempt number
runtime profile
log paths
environment hints
```

The request should contain enough information for subprocess and future remote
executors to reconstruct or locate the stage work.

### 5.4 StageExecutionResult

The structured result returned from an executor to the runner.

It includes:

```text
status
outputs
exception metadata
exit code
log paths
executor metadata
started and finished timestamps
```

The runner validates the result before committing stage success.

### 5.5 StageContext

The runtime object given to a stage. Phase 6 defines only the minimal static
context shape; execution adds runtime services after stores and runner wiring
exist.

Runtime execution may expose:

```text
run_uri
stage_name
local output directory when available
local workspace directory when available
artifact store
run store helpers
output path allocation
resolved stage config
runtime metadata
process-containment owner
```

`StageContext` should be generic. It should not contain project-specific helper
methods.

Its immutable `process_containment_owner` tells stage code who owns descendant
cleanup. `STAGE` requires the stage to clean up all children it launches.
`OUTER_BOUNDARY` is valid only when an enclosing agent or scheduler boundary
contains those descendants; the stage must retain that containment and must not
signal the enclosing group. The stage still owns normal child communication,
completion, and reaping. The field is a live execution fact, not config,
provenance, or a containment mechanism.

### 5.6 Attempt

A numbered execution attempt for a stage in a run directory.

In v0:

```text
attempt 1 is the normal stage run
later attempts are only used if a failed or interrupted stage is explicitly rerun
automatic retry can be added later
```

Attempt numbering should be persisted so failures and logs are not ambiguous.

### 5.7 Invocation Mode

The backend mechanism used to invoke a stage.

Examples:

```text
local
subprocess
slurm-afterok
slurm-single-job
docker
```

Invocation mode belongs to executor metadata, not to the stage implementation.
The Stage 17 Docker invocation mode is per-stage: the parent runner prepares
stage attempts and finalizes outputs on the host, while the Docker executor
launches the prepared worker command inside `docker run`.

### 5.8 Runtime Options And Profiles

`RunOptions` is the runtime package's canonical invocation-policy model for
Python callers. It owns run URI, executor, dry-run, selected profile name,
optional run-store selection, tags, notes, selector/resume adapter inputs,
execution settings, exact stage runtime options, environment requests, and
adapter options.

`runtime.run_store.root` selects the local collection for stores created by the
CLI. It is optional: omission keeps the historical `runs` default. An explicit
root must be a non-empty absolute path and is normalized to one canonical
spelling without creating or probing the directory. It can be set in `runtime`
or in the selected `runtime_profiles` entry; the normal base, selected-profile,
and explicit runtime-source precedence applies. For example:

```yaml
runtime:
  profile: cluster
runtime_profiles:
  cluster:
    run_store:
      root: /srv/loom/project-runs
```

Fresh runs, resume, `loom plan` with an explicit run, SLURM preparation, and
offline-first CLI runs use that same collection. The machine path is operational
runtime evidence, not a pipeline or scientific fingerprint. Direct Python
runners that receive an already constructed store retain that caller-supplied
store as their authority; `run_store` does not replace it.

The execution `RunRequest` remains the runner envelope for config, pipeline,
provenance, stores, and lifecycle inputs. Its `options` field is the canonical
invocation-policy source; legacy `run_uri`, `selectors`, and `resume` inputs
normalize into that field when they do not conflict. `open_existing` remains
run-store lifecycle policy and is not inferred from `RunOptions.resume`.

The runner resolves `RunOptions` once per run into typed
`ResolvedStageRuntimeOptions` objects and passes the matching object through
`StageExecutionRequest.resolved_runtime`. Executors receive typed runtime data
directly; they should not read persisted metadata to decide execution behavior.

Local runs also write a schema-versioned `runtime.json` observability document.
The document records safe summaries only: executor/profile/tags/notes, an
explicitly configured operational run-store root, selector and resume summaries,
resource entry summaries, execution setting keys, environment counts, and
adapter namespace names/counts. It does not record environment variable names
or values, raw adapter payloads, or semantic fingerprint inputs.

The managed-local daemon has a separate private exact runtime record, written
only during trusted managed-local preparation. It carries validated execution
options, resolved placement evidence, run concurrency, plan identity, and a
normalized digest. It is not a replacement for `runtime.json`; safe metadata
cannot be decoded as executable daemon input.

Examples:

```text
cpu count
memory
GPU count
walltime
environment variables
working directory policy
backend-specific metadata
```

Post-v0 execution layers may carry these hints. Backend-specific
interpretation belongs to the executor.

### 5.9 Log Paths

Canonical paths for stage logs.

Recommended initial files:

```text
stdout.log
stderr.log
traceback.txt
executor.json
```

The run store should provide path helpers. Executors should write to these paths
or return metadata pointing to equivalent files.

---

## 6. Guiding Design Principles

### 6.1 Plans Are Authoritative

Execution should run the plan it was given.

If the plan says:

```text
stage action = RUN
```

then execution may attempt the stage.

If the plan says:

```text
stage action = REUSE
```

then execution should not call the executor for that stage.

If state changes between planning and execution invalidate the plan, execution
should fail clearly rather than silently planning again.

### 6.2 Executors Are Backend Adapters

Executors should answer:

```text
How do I invoke this stage?
```

They should not answer:

```text
Is this stage reusable?
What does this artifact mean?
How should this pipeline be topologically sorted?
What config overlays should be applied?
```

This keeps executor implementations small and testable.

### 6.3 The Runner Owns Lifecycle Transitions

The runner should be the only component that decides when a stage moves through:

```text
PENDING
RUNNING
SUCCEEDED
FAILED
SKIPPED
CANCELLED
```

This prevents local, subprocess, and future cluster execution from drifting into
different state semantics.

### 6.4 Success Requires Validated Outputs

A stage should not be marked `SUCCEEDED` merely because its Python call returned
or its process exited with code 0.

Success requires:

```text
executor completed successfully
required outputs were returned or registered
outputs are valid ArtifactRef values
required artifact files exist when local validation applies
checksums validate when present and the store can read the URI
outputs.json is persisted
artifact index is updated
stage status is marked SUCCEEDED
```

If any step fails, the stage should be failed or treated as incomplete.

### 6.5 Logs Are First-Class Run State

Every stage attempt should have predictable log paths.

Even local in-process execution should provide enough failure metadata for a user
to answer:

```text
which stage failed?
which executor ran it?
what exception or exit code occurred?
where are stdout and stderr?
where is the traceback?
when did it start and finish?
```

### 6.6 Execution Must Be Inspectable Without Python

The run directory should remain useful from a shell.

A user should be able to inspect:

```text
run.json
status.json
plan.json
stages/<stage>/status.json
stages/<stage>/inputs.json
stages/<stage>/outputs.json
stages/<stage>/failure.json
stages/<stage>/logs/
artifacts.json
```

without importing project code.

### 6.7 Stage Internals Remain Project-Owned

Execution should provide output path helpers and artifact registration APIs, but
it should not prescribe how project code performs work internally.

For example, the stage may:

```text
write one file
write a directory tree
stream data to an external location
perform internal checkpointing
call another library
spawn internal workers
```

`loom` only needs explicit returned or registered artifacts at the stage
boundary.

### 6.8 Serial First, Parallel Later

The v0 runner should execute runnable stages in topological order serially.

Parallel execution requires additional design for:

```text
run-store concurrency
artifact index locking
executor queueing
failure propagation
resource scheduling
log interleaving
```

The execution API should make future parallel scheduling possible, but v0 should
prefer simple semantics.

### 6.9 Backend-Specific Metadata Should Be Nested

Generic execution fields should stay stable.

Backend-specific details should be nested under executor metadata:

```json
{
  "executor": "subprocess",
  "executor_metadata": {
    "pid": 12345,
    "command": ["loom", "stage", "run", "--run-uri", "..."],
    "exit_code": 1,
    "signal": null
  }
}
```

This avoids making core run-store schemas SLURM-specific, Docker-specific, or
cluster-specific.

---

## 7. Execution Model

### 7.1 High-Level Runner Flow

Recommended flow:

```text
1. Receive a run request.
2. Validate or load the pipeline spec.
3. Create or open the run directory.
4. Acquire the run-store lock before mutating run execution state.
5. Emit `run.created` or `run.opened` after the lock is held.
6. Persist run metadata and resolved config references.
7. Build or receive the execution plan.
8. Persist `plan.json`.
9. Mark the run `PLANNED`, then emit `run.planned` and one `stage.planned`
   event per planned stage.
10. Mark the run `RUNNING`, then emit `run.started`.
11. Iterate stage plans in dependency order.
12. Apply non-RUN actions without executor invocation.
13. Prepare each `RUN` stage attempt.
14. Persist bound inputs.
15. Persist fingerprint candidate.
16. Mark the stage `RUNNING`, then emit `stage.started`.
17. Invoke the executor.
18. Validate returned outputs.
19. Persist outputs.
20. Update artifact index.
21. Mark the stage `SUCCEEDED`, then emit `stage.completed`.
22. On failure, persist failure metadata, mark `FAILED`, emit
   `stage.failed`, persist downstream `BLOCKED` descendants, and emit
   `stage.blocked`.
23. Finalize root run status and emit `run.completed` or `run.failed`.
24. Release the run lock.
25. Return a structured run result.
```

The exact order should avoid reporting success before all durable state is
written.

### 7.2 Stage Actions

Execution should understand the planner action vocabulary:

```text
RUN
REUSE
SKIP
BLOCKED
STALE
```

Recommended execution behavior:

```text
RUN:
  invoke executor and commit outputs

REUSE:
  preserve or record reused artifact refs without executor invocation;
  emit stage.reused after the artifact index is updated

SKIP:
  mark stage skipped and emit stage.skipped

BLOCKED:
  do not run; persist status-only BLOCKED state and emit stage.blocked

STALE:
  do not run directly; persist a plan-execution failure
```

If `STALE` appears in a final executable plan, the runner should treat that as a
planner error unless the plan explicitly marks it as explanatory only.

### 7.3 Stage Ordering

The runner should execute stages in the order provided by the plan.

The planner should already have:

```text
validated the DAG
performed topological sorting
applied selectors
computed reuse actions
computed invalidation
```

Execution should not recompute graph order except as a defensive validation
check in tests.

### 7.4 Whole-Pipeline and Per-Stage Modes

Two execution shapes should be represented:

```text
whole-pipeline:
  one runner process coordinates and executes all RUN stages

per-stage:
  a coordinator invokes one stage at a time through separate processes or jobs
```

The same lifecycle should apply to both shapes.

For v0:

```text
local executor:
  whole-pipeline process, in-process stage calls
```

Future SLURM support can map either:

```text
single-job:
  one cluster job runs the whole pipeline

afterok:
  one cluster job per stage with scheduler dependencies
```

### 7.5 Preflight Checks

Future execution APIs may expose preflight checks before expensive execution or
submission.

Useful checks:

```text
pipeline validation
writable run and artifact directories
known input artifact existence
executor availability
SLURM command availability for SLURM modes
basic disk-space warnings when practical
```

Preflight should report what was checked and what could not be checked. It
should not mutate run state except when an explicit dry-run or planning command
chooses to persist an inspectable plan.

### 7.6 Run Result

The runner should return a structured result rather than only raising or exiting.

Recommended fields:

```text
run_uri
status
started_at
finished_at
stage_results
failed_stage
failure
plan_summary
artifact_index_path
```

The CLI can turn this result into printed output and exit codes.

---

## 8. PipelineRunner

### 8.1 Recommended Interface

Recommended shape:

```python
@dataclass(frozen=True)
class RunRequest:
    config: ComposedConfig | Mapping[str, PlainData] | None = None
    pipeline: PipelineSpec | None = None
    run_uri: str | None = None
    open_existing: bool = False
    selectors: PlanSelectors = field(default_factory=PlanSelectors)
    resume: ResumeOptions = field(default_factory=ResumeOptions)
    failure_policy: FailurePolicy = field(default_factory=FailurePolicy)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class PipelineRunner:
    def run(self, request: RunRequest) -> RunResult:
        ...
```

Convenience function:

```python
def run_pipeline(
    request: RunRequest,
    *,
    run_store: RunStore,
    executor: Executor | None = None,
) -> RunResult:
    ...
```

### 8.2 Constructor Dependencies

The runner should receive dependencies explicitly.

Recommended constructor:

```python
class PipelineRunner:
    def __init__(
        self,
        *,
        planner: PipelinePlanner,
        run_store: RunStore,
        artifact_store: ArtifactStore,
        executor: Executor,
        clock: Clock | None = None,
    ) -> None:
        ...
```

This keeps tests simple:

```text
fake planner
temporary local run store
temporary local artifact store
dummy executor
deterministic clock
```

### 8.3 Runner Responsibilities

The runner should own:

```text
dependency orchestration
stage lifecycle sequencing
status transitions
executor invocation
output validation
artifact index update ordering
failure conversion
run finalization
```

The runner should not own:

```text
YAML loading
recipe expansion
target import resolution
DAG validation internals
fingerprint hash policy
artifact path safety rules
low-level atomic file writes
SLURM script generation
stage business logic
```

### 8.4 Failure Policy

Initial failure policy:

```text
stop_on_first_failure = true
```

The runner should stop after the first failed `RUN` stage and finalize the run as
`FAILED`.

It should also record:

```text
failed stage name
blocked downstream stages, if known from the plan
failure metadata
log paths
```

Future policies:

```text
continue independent branches
retry transient failures
cancel submitted downstream jobs
mark branch-specific failures
```

### 8.5 Cancellation

V0 does not need full cooperative cancellation, but runner code should use
status vocabulary that can support it.

Recommended behavior for keyboard interruption:

```text
catch KeyboardInterrupt at the runner boundary
mark current stage CANCELLED if possible
mark root run CANCELLED
persist interruption metadata
re-raise or return a cancelled RunResult according to API choice
```

For CLI use, `KeyboardInterrupt` should produce a non-zero exit code and leave
the run directory inspectable.

---

## 9. StageExecutionRequest

### 9.1 Current Fields

Recommended dataclass:

```python
@dataclass(frozen=True)
class StageExecutionRequest:
    run_uri: str
    stage: StageSpec
    stage_plan: StagePlan
    stage_object: Stage
    context: StageContext
    inputs: Mapping[str, ArtifactRef]
    fingerprint: StageFingerprintRecord
    attempt: int
    stdout_path: Path
    stderr_path: Path
    traceback_path: Path
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

The exact field names may change, but the request should be explicit rather
than relying on executors to rediscover run state from global variables.

### 9.2 Stage Object Versus Stage Target

Local execution can receive an already constructed stage object.

Subprocess execution should receive enough information to reconstruct the stage
from persisted config and stage name.

Recommended approach:

```text
StageExecutionRequest.stage:
  optional constructed object for in-process execution

StageExecutionRequest.stage:
  always present

StageExecutionRequest.run_uri:
  always present
```

For future subprocess execution, the command should receive a run URI and stage
name, then let the appropriate store resolve durable state rather than trying to
pickle Python objects.

### 9.3 Serialization Boundary

`StageExecutionRequest` does not need to be fully JSON-serializable in v0 for
local execution.

However, the persistent subset should be clear:

```text
run_uri
stage_name
attempt
input artifact refs
expected output specs
fingerprint
resources metadata
log paths
```

Subprocess and future remote executors should pass only stable identifiers on
the command line and read durable state through the run store.

### 9.4 Environment Hints

The request may include environment hints:

```text
working directory
environment variables
Python executable
module path
extra command args
```

V0 should keep these minimal. Backend-specific environment construction belongs
to the executor.

---

## 10. StageExecutionResult

### 10.1 Recommended Fields

Recommended dataclass:

```python
@dataclass(frozen=True)
class StageExecutionResult:
    stage_name: str
    status: ExecutionStatus
    outputs: Mapping[str, ArtifactRef] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    signal: int | None = None
    exception_type: str | None = None
    message: str | None = None
    traceback_path: Path | None = None
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    executor: str | None = None
    executor_metadata: Mapping[str, Any] = field(default_factory=dict)
```

Recommended execution statuses:

```text
SUCCEEDED
FAILED
CANCELLED
SUBMITTED, later
```

The runner maps execution result status to persisted stage/run status.

### 10.2 Successful Result

A successful result should include:

```text
status = SUCCEEDED
outputs
started_at
finished_at
executor
log paths
executor metadata
```

The runner should still validate outputs before marking the stage succeeded.

### 10.3 Failed Result

A failed result should include:

```text
status = FAILED
exception_type, exit_code, or signal
message
traceback path when available
stdout/stderr paths
executor metadata
```

Executors should avoid raising backend exceptions for expected stage failures
when a structured result can describe the failure. They may raise for executor
misconfiguration or internal loom errors.

### 10.4 Submitted Result

Future cluster executors may return:

```text
status = SUBMITTED
job_id
submission command
submission script path
dependency metadata
```

The v0 runner does not need to support asynchronous submitted jobs. This result
shape is reserved so a later SLURM design can extend execution without
rewriting the executor protocol.

---

## 11. Stage Lifecycle

### 11.1 Preparation

Before invoking an executor, the runner should:

```text
create the stage directory
allocate attempt number
allocate log paths
bind input ArtifactRefs
construct StageContext
write inputs.json
write fingerprint.json or fingerprint candidate
write initial executor metadata if useful
mark stage RUNNING
update root status current_stage
```

This ordering ensures that an interrupted process leaves enough information to
understand what was running.

### 11.2 Invocation

The runner invokes:

```python
result = executor.execute(request)
```

The executor should be responsible for:

```text
calling the stage
capturing local exceptions
capturing process exit codes
writing stdout/stderr when applicable
returning structured metadata
```

The runner should be responsible for:

```text
interpreting the result
validating outputs
persisting state transitions
```

### 11.3 Commit

On successful executor result:

```text
1. validate required outputs are present
2. validate output names are declared or allowed by policy
3. validate output values are ArtifactRefs
4. validate artifact existence when configured
5. compute or verify checksums when configured
6. write outputs.json
7. update artifacts.json
8. write stage provenance when available
9. mark stage SUCCEEDED
10. update root status
```

If commit fails after the stage ran, the stage should not be marked succeeded.
The failure metadata should explain that execution completed but commit failed.

### 11.4 Failure

On executor failure:

```text
1. normalize failure metadata
2. write failure.json
3. write executor metadata
4. mark stage FAILED
5. update root status
6. stop further stage execution by default
```

The runner should preserve any artifacts the stage wrote, but it should not add
them to the run-level artifact index unless output validation and commit
succeeded.

### 11.5 Skipped and Reused Stages

For `SKIP`:

```text
record status SKIPPED when the run store tracks selected-out stages
do not invoke executor
do not update outputs unless prior output preservation is part of plan
```

For `REUSE`:

```text
do not invoke executor
record reuse metadata in plan/status if useful
preserve or rebuild artifact index entries from prior outputs
```

The exact reuse write behavior is defined by the resume and run-store specs.
Execution should make the reuse visible in the run result.

### 11.6 Atomic Stage Transactions

The execution layer should provide a conceptual transaction around stage commit:

```text
prepare
run
validate
commit
finalize
```

Low-level atomic file writes belong to the run store. Execution-level atomicity
means that the run should not present partial work as successful.

If v0 does not implement a formal transaction object, the runner should still
preserve the ordering:

```text
outputs persisted before SUCCEEDED
artifact index updated before SUCCEEDED
failure persisted before FAILED
```

### 11.7 Lifecycle Events And Future Sinks

The local runner emits generic lifecycle events while preserving the same status
semantics.

Events may include:

```text
run.created
run.opened
run.planned
run.started
run.completed
run.failed
run.cancelled
run.interrupted
run.preparation_failed
stage.planned
stage.started
stage.completed
stage.failed
stage.cancelled
stage.skipped
stage.reused
stage.stale
stage.blocked
```

The execution layer produces structured event records in local `events.jsonl`.
Service-specific notification delivery should live outside core `loom`.

Lifecycle events should be emitted after the corresponding durable state change
when one exists. For example, `stage.started` follows persisted `RUNNING`,
`stage.completed` follows output commit and persisted `SUCCEEDED`, and
`stage.failed` follows failure metadata and persisted `FAILED`.

Explicit event sinks observe persisted records best-effort. They are
observe-only and must not mutate plans, artifacts, stage results, status
transitions, or run-store state. Generic event filtering and activation remain
future extension work.

---

## 12. StageContext Construction

### 12.1 Required Context Values

Phase 9 runtime context construction may include:

```text
run_uri
stage_name
local output directory
local workspace directory
artifact_store
run_store
output path helpers
resources metadata
stage config
executor metadata
```

The context should be immutable where practical, except for methods that
allocate or register artifacts.

### 12.2 Output Path Allocation

Recommended helper:

```python
path = context.local_output_path("metrics", suffix=".json")
```

The helper should:

```text
validate logical output names
avoid path traversal
place files under the stage artifact area
avoid overwriting committed outputs unless explicitly allowed
return pathlib.Path for local stores
```

Remote artifact stores should not implement this local helper. A future context
may instead provide a URI or writer API.

### 12.3 Artifact Registration

Stages should have two common options:

```text
managed save:
  context.save_artifact("metrics", value, artifact_type="json", codec_key="json.v1")

manual register:
  context.register_artifact("checkpoint", path, artifact_type="checkpoint")
```

Both should return `ArtifactRef`s that the stage returns in its output mapping.
For v0, the runner only accepts the direct `stage.run(context, inputs)` return
mapping. Context-collected outputs are post-v0.

### 12.4 Runtime Services

Context can expose generic services:

```text
logger
artifact store
run store path helpers
resolved stage config
attempt metadata
```

It should avoid application helpers such as:

```text
load_dataset
build_model
plot_results
```

Those belong in project code.

---

## 13. Executor Protocol

### 13.1 Recommended Protocol

```python
class Executor(Protocol):
    name: str

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult:
        ...
```

Optional future methods:

```python
class SubmittedExecutor(Protocol):
    name: str

    def submit(self, request: StageExecutionRequest) -> SubmittedStage:
        ...

    def poll(self, submitted: SubmittedStage) -> StageExecutionResult | None:
        ...

    def cancel(self, submitted: SubmittedStage) -> None:
        ...
```

V0 should implement synchronous `execute`.

### 13.2 Executor Naming

Executor names should be stable strings:

```text
local
subprocess
slurm-afterok
slurm-single-job
docker
apptainer
```

The name is persisted in status and failure metadata.

### 13.3 Executor Registry

An executor registry can be deferred until more than one configurable executor
exists.

When added, it should map:

```text
executor name -> factory or executor instance
```

It should not become a registry for all stage types or project objects.

### 13.4 Executor Errors

Executors may raise `ExecutorError` when the backend cannot be used.

Examples:

```text
subprocess command cannot be built
Python executable does not exist
sbatch command is unavailable
container image is missing
invalid backend resource option
```

Stage failures should normally be returned as `StageExecutionResult(status=FAILED)`
with metadata, not raised as raw exceptions through the runner.

---

## 14. LocalExecutor

### 14.1 Purpose

`LocalExecutor` runs a stage in the current Python process.

Use cases:

```text
unit tests
local development
small pipelines
CI smoke tests
debugging stage APIs
```

It should be the first executor implemented.

### 14.2 Invocation

Recommended behavior:

```text
1. receive StageExecutionRequest
2. get constructed stage object or construct from stage spec
3. call stage.run(context, inputs)
4. validate the returned ArtifactRef mapping
5. capture exceptions
6. write traceback when needed
7. return StageExecutionResult
```

The v0 stage call form must match the pipeline spec exactly:

```python
stage.run(context, inputs)
```

Callable stages, `stage.run(context)` without explicit inputs, and stage objects
that collect outputs through context are post-v0.

### 14.3 Stdout and Stderr

Capturing stdout/stderr in-process can be useful but may surprise libraries that
expect normal streams.

Recommended v0 policy:

```text
support optional capture_stdout_stderr flag
default can be passthrough for local development
always write traceback.txt for exceptions
record whether streams were captured
```

The CLI can choose a default appropriate for non-interactive runs.

### 14.4 Exception Capture

On exception, the local executor should capture:

```text
exception type
message
traceback path
executor name
started_at
finished_at
```

The traceback file should contain the full Python traceback. The JSON failure
metadata should contain concise structured fields.

### 14.5 Return Value Validation

V0 stages must return:

```text
Mapping[str, ArtifactRef]
```

The local executor or runner should validate this mapping against declared
outputs. Returning a `StageResult`, returning `None`, callable stages, or relying
on context-registered outputs are post-v0 behaviors.

Recommended policy:

```text
runner validates the direct returned output mapping
executor returns the direct stage return mapping or failure metadata
context save/register helpers return ArtifactRefs
```

---

## 15. Post-v0 SubprocessExecutor

### 15.1 Purpose

`SubprocessExecutor` runs one stage through a separate process.

Use cases:

```text
stage isolation
independent logs
closer behavior to parent-managed submitted workers
debugging command entry points
avoiding leaked in-process state
```

It is the bridge between local execution and parent-managed subprocess
execution. Submitted afterok jobs use `loom stage-job run` instead because they
must finalize one stage from durable run-store state without a live parent
process.

### 15.2 Command Contract

Recommended command:

```bash
loom stage run --run-uri RUN_URI --stage STAGE_NAME --attempt ATTEMPT
```

Current optional flags:

```text
--attempt ATTEMPT
--format {text,json}
--traceback
```

The command should not require pickled Python objects or a normal `--config`
input. It should reconstruct stage context from durable run-store files,
prepared request metadata, resolved config/source records, and resolved runtime
handoff data.

### 15.3 Coordinator Responsibilities

The parent runner should:

```text
prepare the stage attempt
write inputs.json
write fingerprint.json
mark stage RUNNING
allocate log paths
start subprocess
wait for completion
read worker result files
interpret exit code
commit or fail the stage
```

Current subprocess execution follows this flow for
`loom run CONFIG --executor subprocess`. The runner prepares the durable worker
request, marks the stage running, invokes `SubprocessExecutor`, reads the
worker handoff through store APIs, and then uses the normal parent-owned
success/failure finalization path.

### 15.4 Worker Responsibilities

The `loom stage run` worker should:

```text
load run metadata
load resolved config
locate stage spec
construct stage object
construct StageContext
load bound inputs
run stage through local execution machinery
write worker result file
exit with a meaningful code
```

The worker should not finalize the whole run. It should only perform one stage
attempt.

SLURM afterok dry-run scripts generated in v6 do not call `loom stage run`.
They call `loom stage-job run --run-uri RUN_URI --stage STAGE --executor local`.

### 15.5 Result Handoff

Recommended worker output:

```text
stages/<stage>/worker_result.json
```

The latest-stage-compatible file carries explicit attempt identity. Full
`stages/<stage>/attempts/<attempt>/...` archives are deferred until retry or
retention policy needs attempt history.

The result should include:

```text
status
outputs
exception metadata
log paths
executor metadata
exit_code
signal
```

The parent process should read this result and perform final commit semantics.

### 15.6 Exit Codes

Recommended subprocess exit codes:

```text
0:
  stage execution completed and result file was written

1:
  stage ran and failed

2:
  loom usage or config error

3:
  executor infrastructure error

130:
  interrupted
```

The parent should prefer structured result files when present. Exit code is the
fallback when the worker dies before writing structured state.

Current behavior treats nonzero process exit, signal termination, missing
worker result, invalid worker result, identity mismatch, and
structured-success/process-failure conflicts as stage failures. Signal facts are
recorded separately from ordinary exit codes.

### 15.7 Environment

The subprocess executor defaults to:

```text
current Python executable
current environment
current working directory or configured project root
loom.cli.main worker invocation
```

Future options:

```text
explicit Python executable
environment variable overlays
clean environment mode
project root
module invocation
```

The executor records redacted command and process metadata. Availability
preflight for the Python executable and worker command is handled by selected
subprocess executor checks before `loom run` invokes user stage code.

### 15.8 Current v5 Guarantees And Boundaries

Current v5 support covers local in-process execution and serial subprocess
execution on the same machine. Subprocess execution provides process isolation
for stage calls and durable worker handoff files; it is not a security sandbox
for untrusted project code. Authored configs, stage targets, and example stage
modules are trusted project code.

Subprocess runs currently guarantee:

```text
one prepared worker request per runnable stage attempt
parent-owned finalization for outputs, failures, provenance, artifact indexes,
stage status, and run status
structured failures for missing, invalid, mismatched, and process-failed worker
results
separate exit-code and signal facts
redacted command/process metadata
selected-executor preflight for Python and worker command availability
```

Subprocess runs currently do not guarantee:

```text
timeouts
automatic retries
parallel worker pools
SLURM or container submission
plugin-discovered executors
remote run stores
attempt archive directories
full environment persistence
automatic cleanup or retention
strong multi-coordinator locking
```

Full environment persistence is deferred because environments can contain
secrets. Current metadata records command and process facts with redaction and
does not persist complete environment variable values by default.

---

## 16. Logs and Failure Metadata

### 16.1 Log Layout

Recommended stage attempt layout:

```text
stages/<stage>/
  status.json
  inputs.json
  outputs.json
  fingerprint.json
  failure.json
  logs/
    stdout.log
    stderr.log
    traceback.txt
    executor.json
```

If attempts are represented as subdirectories later:

```text
stages/<stage>/attempts/<attempt>/logs/
```

The run-store spec should decide final path details. Execution should request
paths from the run store rather than constructing them ad hoc.

### 16.2 Failure Metadata Fields

Recommended fields:

```text
schema_version
run_uri
stage_name
attempt
failed_at
executor
exception_type
message
traceback_path
exit_code
signal
stdout_path
stderr_path
executor_metadata
```

For local execution, Python exception fields are primary.

For subprocess and future SLURM execution, exit code, signal, and log paths are
primary.

### 16.3 Executor Metadata

Recommended fields:

```text
executor
invocation_mode
started_at
finished_at
host
pid
command
cwd
environment_summary
backend
```

Avoid storing full environment variables by default because they may contain
secrets. Store selected non-sensitive summaries unless the user explicitly opts
in.

### 16.4 Tracebacks

Tracebacks should be written to text files rather than embedded entirely in JSON.

JSON should include:

```text
exception_type
message
traceback_path
```

This keeps status and failure files compact while preserving debugging detail.

---

## 17. Runtime and Resource Profiles

Runtime and resource profiles are post-v0.

### 17.1 Generic ResourceSpec

Current generic resource entries:

```text
cpu
memory
gpu
```

These entries are scheduler-neutral declarations. The local executor does not
enforce `StageSpec.resources`; later SLURM or container executors can translate
validated resource entries after their contracts are introduced.

### 17.2 RuntimeSpec

Recommended generic fields:

```text
executor
working_dir
env
timeout_seconds
retry
container
backend
```

Backend-specific values should be nested:

```yaml
runtime:
  executor: slurm-afterok
  resources:
    entries:
      cpu:
        kind: cpu
        amount: 16
        unit: count
        attributes: {}
      memory:
        kind: memory
        amount: 64
        unit: GiB
        attributes: {}
      gpu:
        kind: gpu
        amount: 1
        unit: count
        attributes: {}
  slurm:
    partition: gpu
    account: research
```

The generic execution doc should define how runtime metadata is carried. A
dedicated SLURM doc should define SLURM translation.

### 17.3 Local Resource Enforcement

The local executor should not attempt heavyweight resource enforcement in v0.

It may:

```text
record requested resources
warn on unsupported enforcement
pass environment variables
support timeout in a later subprocess mode
```

Hard resource limits are backend-specific and can be added later if needed.

### 17.4 Timeouts

V0 timeout policy can be deferred, but the request/result shapes should leave
space for:

```text
timeout_seconds
timed_out flag
timeout message
executor cleanup metadata
```

Subprocess timeout support is simpler than in-process timeout support and should
be the first implementation when timeouts are added.

### 17.5 Retries

Automatic retry is opt-in and conservative. The runner owns retry decisions and
executors continue to execute a single attempt at a time.

Retry policy is configured through runtime reliability options:

```yaml
runtime:
  reliability:
    retry:
      enabled: true
      max_attempts: 2
```

`max_attempts` is the total attempt budget including the first attempt. Before
the runner schedules attempt 2 or later, it persists a retry decision with the
denial or allow reason. Retry is denied for disabled policy, exhausted attempt
budget, cancellation, non-retriable failure classification, missing transaction
evidence, or unsafe output transaction state. Attempts that reached staged,
committed, or commit-failed output state are not retried automatically.

Selected per-stage reliability policy is persisted as a read-model fact during
runner startup. Status diagnostics can therefore show the policy, transaction,
retry, and timeout facts without reconstructing behavior from runtime metadata,
executor logs, or status messages.

### 17.6 Deferred Behavior Owners

Later roadmap work should own deferred behavior explicitly:

| Deferred behavior | Likely owner | Revisit trigger |
| --- | --- | --- |
| Retries and failure policy | Reliability policy and runner lifecycle | Users need more than single-attempt stop-on-first-failure execution. |
| Timeouts | Executor-specific reliability support | Subprocess or scheduler execution needs bounded wall-clock enforcement. |
| Worker pools and parallel scheduling | Runner scheduling plus store locking | Independent stages should run concurrently. |
| SLURM | `loom.pipeline.executors.slurm` | Cluster submission is added. |
| Containers | Container executor layer | Docker/Apptainer execution is added. |
| Plugins | Plugin registry and capability discovery | Executors or stores are loaded outside built-ins. |
| Remote stores | Run-store and artifact-store backends | Non-local run URIs are supported. |
| Cleanup and retention | Reliability cleanup commands | Managed temporary files or old runs need explicit lifecycle. |
| Attempt archives | Run-store attempt layout | Retries or retention require historical attempt state. |
| Stronger locking | Store concurrency and scheduler integration | Multiple coordinators may mutate the same run. |

---

## 18. Concurrency and Scheduling

### 18.1 V0 Serial Scheduling

V0 runner scheduling:

```text
for stage_plan in plan.stage_plans:
    handle stage according to action
```

No worker pool is required.

### 18.2 Future Parallel Scheduling

Future local parallelism should account for:

```text
ready queue based on DAG dependencies
resource constraints
run-store locking
artifact index update serialization
failure propagation
cancellation
log path isolation
```

This should be a separate enhancement, not a hidden behavior in v0.

### 18.3 Submitted Job Scheduling

Future submitted executors may split execution into:

```text
submit ready stages
record submitted job IDs
poll or rely on scheduler dependencies
collect completed results
finalize run state
```

SLURM afterok may not need a long-running controller, while controller mode
does. That distinction belongs in the SLURM design document.

### 18.4 Stage 29 Managed Stage Scheduling

Stage 29 changes managed execution from whole-run dispatch to durable scheduling
of individual ready stage attempts. This is a planned evolution of the current
runner contract, not a description of behavior available before Stage 29 lands.
Historical whole-run delegated SLURM remains separate because its existing
controller owns that run. Stage 29 also permits one exact ready attempt inside a
managed-stage run to target an explicitly selected SLURM profile; the
coordinator retains run/readiness/lifecycle orchestration while SLURM owns node
placement and external job state.

The run remains what a user submits, monitors, and cancels. The unit offered to
the managed scheduler is narrower:

```python
@dataclass(frozen=True)
class StageWork:
    stage_work_id: str
    admission_id: str
    run_uri: str
    stage_name: str
    attempt: int
    readiness_generation: str
    upstream_commit_ids: tuple[str, ...]
    placement: ResolvedStagePlacement
```

`StageWork` is illustrative internal data, not a new public API. It identifies
one already planned attempt that authority has idempotently prepared in
`PENDING` for an exact readiness generation. That authority transaction records
bound-input/readiness evidence but creates no worker request, workspace,
assignment, execution lease, or process. It carries the resolved resource,
preference, and immutable execution route/profile for that exact stage; it does
not carry arbitrary command text, invent a new attempt, or reinterpret the
pipeline graph.

For new managed work, `(coordinator_id, run_uri)` has one digest-bound
admission and one execution owner. Exact submit replay returns that admission;
changed intent/owner conflicts, resume addresses it, and rerun needs a new
`run_uri`. Admission first commits as `PENDING_AUTHORITY` with a durable
authority-operation intent. It becomes `ACTIVE` and may expose stage work only
after per-run authority returns or reconciliation proves the exact owner,
normalized intent digest, and operation receipt. An outage leaves a visible
accepted-but-not-runnable admission; a conflict blocks rather than creating a
second execution owner. The stage-work semantic key includes admission, stage,
attempt, and readiness generation and therefore rebuilds to the same
`stage_work_id` even if its projection revision or diagnostics change.

The execution flow becomes:

```text
client submits run
        |
        v
coordinator reconciles authoritative plan and statuses
        |
        +-- resolve REUSE / SKIP / BLOCKED without agent capacity
        |
        +-- authority prepares exact ready PENDING RUN attempt
        |
        +-- expose its rebuildable StageWork projection
                         |
                         v
              resolve exact tagged target
                         |
             +-----------+-----------+
             |                       |
             v                       v
     managed-agent kernel       explicit SLURM profile
     + exact resource claim     + durable submit operation
             |                       |
             v                       v
        managed agent          restricted bootstrap
             +-----------+-----------+
                         |
                         v
              authority grant/fence
                         |
                         v
             one execution-only stage worker
                         |
                         v
          result retention -> authority output commit
                         |
                         v
            reconcile newly ready downstream work
```

The assignment target is a closed tagged value. A managed target retains exact
agent/session/offer/resource-claim identities. A SLURM target retains exactly
one named profile, request fingerprint, and stable submission operation while
holding no agent claim. Both consume the run's atomic stage-concurrency slot and
bind the same authority-owned `PENDING` attempt. A missing agent offer never
changes an explicit SLURM route, and an unavailable profile never falls back to
an agent or another profile.

The SLURM route persists immutable request/script evidence and `SUBMITTING`
before invoking `sbatch` at most once. Its only submission outcomes are accepted
with an exact job ID, definitely rejected with positive non-acceptance evidence,
or unknown. Crash, timeout, malformed output, or lost response after
`SUBMITTING` stays unknown and reconciles by a stable scheduler-visible
operation ID; it never invokes `sbatch` again automatically.

The submitted script runs a fixed assignment-scoped Loom bootstrap rather than
authored code directly. It authenticates the exact assignment/submission/job/
incarnation, stages inputs, and requests the authority grant. Only after the
grant creates the current fence may it consume one start permit and call the
same execution-only stage worker. A duplicate or scheduler-requeued bootstrap
cannot receive a second permit. The bootstrap is not an agent, owns no offer or
agent session, and has no direct authority credential.

The flow can place successive or independent pipeline stages on different
agents or explicit targets, but one managed-agent stage attempt remains wholly
on one agent. A SLURM job choosing one node is still a single delegated attempt,
not Loom gang scheduling. A multi-node training
attempt is a distributed stage and would require gang admission: all required
agents reserved together, one rendezvous/rank plan, coordinated launch and
cancellation, and group failure/retry semantics. Stage 29 introduces none of
those multi-agent execution states.

For either target, authority success requires an exact current-fence Loom result
and coordinator/backend-accessible output refs. Agent process exit and SLURM
`COMPLETED` are observations, not lifecycle commits. `scancel` success is only a
control request. Unknown external work stays bound until exact reconciliation,
authoritative terminal truth, or Phase 9 positive containment; it is not
automatically retried or assigned elsewhere.

Managed execution is also non-preemptive. Run priority and placement
preferences affect only which unstarted work is selected next. They never
checkpoint, stop, or release a granted lower-priority assignment. Fair-share
would be a separate durable user/project usage and entitlement policy; it is not
another placement score. A general solver would normally select a snapshot-
bound batch across several jobs and agents, while the Stage 29 policy chooses
one already validated `(stage_work_id, candidate_id)` or waits. Those features
need new lifecycle/accounting/batch-reservation owners rather than broader
executor behavior.

One import-light readiness function interprets the persisted plan, current
stage/attempt statuses, and committed upstream outputs. The coordinator uses it
both when exposing work and again during the expected-state assignment
mutation. This prevents a queue loop, runner, and worker from each maintaining a
slightly different DAG interpreter. Only an authoritative output commit makes a
dependent stage ready; an agent process exit, local output file, or retained
result is not enough.

The current `PipelineRunner` remains the synchronous public facade, but managed
calls no longer own an in-memory ready loop or a full-run execution lock. It
composes or connects to the same coordinator and agent services used by a
persistent daemon, submits the run, waits for authoritative terminal state, and
returns the existing `RunResult` shape:

```python
class PipelineRunner:
    def run(self, request: RunRequest) -> RunResult:
        admitted = self._managed_runtime.submit(request)
        terminal = self._managed_runtime.wait_for_run(admitted.run_uri)
        return self._results.from_authority(terminal)
```

The sketch fixes delegation, not private member names. A one-command local run,
a local daemon accepting many runs, and an authenticated multi-machine pool all
therefore use the same stage scheduler. Their differences are composition and
transport rather than scheduling semantics.

Command lifetime is not state lifetime. A production embedded command opens
retained explicitly initialized coordinator/agent roots and leaves safety state
after return. If a compatible daemon owns those roots, the facade uses its
client view when configured/reachable; a held but unreachable/conflicting owner
fails closed. Temporary or in-memory role state is test-only and cannot be used
to mint a different coordinator identity for a production run.

The kernel is fixed, pure, and mutation-free. Trusted downstream code may be
explicitly composed behind narrow subsystem protocols to plan one resource
kind from a validated opportunity through a complete claim result, add a hard
rejection to a complete placement, add bounded utility/quality-band preference
evidence, or select one existing grouped work/candidate pair. The kernel owns
search completeness, site-tier aggregation, durable-time fallback, and result
validation. A separate agent resource provider owns
physical prepare/reconcile/activate/release. None of these protocols can inspect
the DAG, write coordinator/authority state, launch a process, or commit a result;
invalid/exceptional output fails before assignment mutation. Implementation
identity/version is durable plain data, while live objects remain local. Exact
descriptor bindings remain retained while nonterminal work or live claims name
them; a configuration epoch cannot silently reinterpret those records.

Configuration reload is intentionally not distributed. The coordinator swaps
its planners, rules, scorers, and policy in one owner-local transaction while
retaining referenced descriptors. Each agent separately swaps its pools,
providers, manageable inventory, and resident capabilities under the same
retained-reference rule. A temporary claim-contract mismatch makes that
opportunity ineligible; neither service rolls back the other.

Ready-work projection does not consume `max_parallel_stages`. When a pure
decision becomes an assignment, one coordinator transaction revalidates the
work/snapshot/offer, atomically checks the run's active assignment count,
reserves every namespaced capacity atom, and stores bounded policy-epoch,
score/fallback, and reason evidence. This is the final concurrency and audit
boundary; two scheduling cycles cannot both consume the same last run slot.

The adapted worker accepts one exact assigned attempt. Its request is closer to:

```python
@dataclass(frozen=True)
class AssignedStageRequest:
    assignment_id: str
    stage_work_id: str
    run_uri: str
    stage_name: str
    attempt: int
    execution_fence: str
    input_manifest: Mapping[str, ArtifactRef]
    resolved_runtime: ResolvedStageRuntimeOptions
```

Before launch, the agent verifies that this assignment has the current grant,
that the grant has not been fenced, that its exact inputs are durably staged,
and that the claimed physical resources are bound. The worker then executes
only the named attempt. The managed worker path is extracted from the current
stage-worker pieces and does not take the legacy whole-run execution lock or
write authority directly:

```python
def execute_assigned_stage(request: AssignedStageRequest) -> StageWorkerResult:
    context = build_context_from_assigned_request(request)
    return selected_executor(request).execute(context)
```

The worker must not:

```text
allocate or advance an attempt
decide whether upstream stages are complete
schedule a downstream stage
reacquire resources already bound by the agent
commit authoritative stage or run success
release an assignment it does not own
```

These restrictions give each correctness decision one owner. Pipeline planning
owns graph meaning. The coordinator owns readiness orchestration and logical
placement. Per-run authority owns attempt/lifecycle/output truth. The agent owns
physical admission, process containment, retained results, and resource
release. The executor only invokes project stage code.

Result handling preserves that split. The agent durably records the worker
result and, for remote execution, transfers outputs into coordinator- or
backend-accessible artifact references. The coordinator presents the exact
assignment and execution fence to per-run authority. Authority validates and
commits outputs before it marks success. Repeated delivery is idempotent, and a
coordinator outage leaves the agent free to finish and retain the result for
later replay. Authority terminal commit permits coordinator logical release;
the agent's physical provider release is a later exact idempotent operation
after containment and retained-result acknowledgement. Capacity becomes
schedulable only through a fresh availability revision, so terminal lifecycle
never masquerades as physical release.

Critical agent facts are journalled with stable event IDs and monotonic per-
assignment sequence. Coordinator acknowledgements cover only durably persisted
contiguous evidence; a gap stays pending. Stable coordinator identity survives
restart while its process epoch rotates and the assignment retains its issuer
epoch. A new epoch may reconcile exact old-issuer facts for that assignment but
old connections cannot create new work/control. Transport timeout or disconnect
after send is indeterminate and retries the same operation identity/digest.

`SUBMITTED` means the accepted assignment has a durable execution grant, not
that a process is known to be running. The agent records grant/start intent
before its one root launcher invocation and then records `PROCESS_STARTED`,
`START_FAILED`, or `START_UNKNOWN`. Only exact current-fence confirmed process
evidence may advance authority to `RUNNING`; unknown start remains `SUBMITTED`
and cannot be launched again. `START_FAILED` is definitive only when the
launcher proves no managed process was created or can later run; every timeout,
lost response, or uncertain spawn is `START_UNKNOWN`. A fenced terminal result
can commit from either `SUBMITTED` or `RUNNING`.

Per-run authority remains a distinct service/API owner. The coordinator calls a
narrow least-privilege authority view after authenticating the service and
verifying workspace/generation/schema/capability identity. Persistent HTTP,
including loopback, uses mutual TLS; owner-contained local IPC may use verified
peer identity. Agents and workers receive neither authority credentials nor
direct database access. If authority is unavailable, the coordinator pauses
preparation, binding, grant/delivery, and terminal commit while already-granted
agents continue and retain results. A restarted authority generation becomes
current only after receipt-aware continuity over one consistent authority-
relevant cut. Before each coordinator-originated authority mutation, the
coordinator durably records its operation ID, canonical intent digest,
principal, and expected state/revision; authority stores the matching receipt
atomically with its mutation. Each retained admission/tombstone must either
match the last acknowledged checkpoint or advance through an ordered chain of
those receipts. This accepts a committed request whose response was lost before
both services restarted, while regression, missing receipts, unexplained
mutation, owner/intent mismatch, or torn per-run reads fail closed. The
checkpoint is comparison evidence, not lifecycle truth. A pristine empty
authority is valid only when the coordinator has no authority-relevant retained
admission/tombstone; missing or divergent expected truth remains degraded.

Cancellation follows the same ownership split: coordinator durably records the
client request, authority installs the canonical cancellation epoch, and only
that effective epoch blocks readiness, bind, grant, descendants, and retry.
Assignment controls are fan-out, not cancellation truth. Joined status preserves
owner-labelled lifecycle, scheduling, execution, transfer, cancellation, and
health axes with owner revisions, coordinator-accepted receipt times, and freshness
rather than flattening them into one lifecycle enum. It is not a globally atomic
snapshot; top-level `as_of` is the coordinator join boundary, and remote clocks
are never used for ordering, expiry, or freshness. A detected coordinator clock
regression/out-of-policy jump pauses scheduling and reports degraded time health
rather than extending stale capacity or resetting deadline semantics.

The first remote artifact relay accepts immutable regular-file payloads only.
Directory/tree, special-file, or ambiguous payload forms make that remote
candidate ineligible without blocking an otherwise eligible local execution.
One stable transfer identity retains exact byte/finalize progress while a
separate short-lived authorization ID/revision may expire and be renewed.
Authorization expiry blocks only the next transfer operation: it does not erase
bytes, release the assignment, or change lifecycle. Exact offset/content replay
is idempotent and conflicting overlap fails closed. No implicit archive format
is invented; a later explicit tree or direct-backend contract may extend the
data boundary.

The same-host managed-local route does not use that network tree contract. It
atomically mirrors each successful resident stage's regular-file artifact
directory into the coordinator run and isolates a prior stage directory beside
each bound primary input. This preserves manifest-relative companion files with
the same paths they have during ordinary local execution. Only returned
`ArtifactRef` values are declared outputs or authority facts; sibling files
remain payload companions. Symlinks and non-regular members fail closed, and an
exact already-published tree is the only accepted replay. Remote agents and
SLURM bootstraps remain regular-file-only.

Managed whole-run `LaunchContract.resources`, synthetic whole-run command
snapshots, and `claim_next -> dispatch(item)` cease to be execution inputs for
new managed runs. Delegated adapters remain supported. `ManagedLocalQueueRuntime`
and its old managed-local request/root formats are removed; `PipelineRunner` is
not a second managed execution owner. Fresh daemon roots and persisted-plan
admission are the only supported local managed path. The detailed state transitions
are authoritative in [Stage 29 planning](../roadmap/stage-29/planning.md) and
its linked phase execution plans.

---

## 19. Integration With Stores

### 19.1 RunStore Integration

The runner should use run-store methods for:

```text
create_run
open_run
write_plan
write_run_status
prepare_stage
write_stage_inputs
write_stage_fingerprint
write_stage_status
write_stage_outputs
write_stage_failure
write_stage_provenance
stage_log_paths
append_event
acquire_run_lock
release_run_lock
```

The local runner acquires the run-store lock after creating or opening the run
and releases it after final status and event commits. Lock conflicts propagate
instead of writing failed status into a run that another owner may be mutating.

The exact method names can differ, but runner code should not duplicate path
and schema rules from the run-store spec.

### 19.2 ArtifactStore Integration

The runner should use artifact-store methods for:

```text
allocating managed output paths
saving values through codecs when context helpers are used
registering manually written paths
checking output existence
checking checksums
loading or reusing artifact refs
```

The execution layer should not hard-code JSON, text, or binary artifact codecs.

### 19.3 Consistency Checks

Before marking a stage succeeded, the runner should be able to check:

```text
outputs.json matches returned outputs
artifact index contains committed outputs
required artifacts exist
checksums match when present and locally readable
stage status transition is valid
```

These checks can be partly delegated to stores.

### 19.4 Locking

V0 local execution acquires a run-level lock around mutating execution state.
The lock protects:


```text
status files
artifact index
stage output commits
run finalization
```

Stage-level locks can be deferred until parallel or external per-stage execution
requires them.

---

## 20. Public API

### 20.1 Execution Types

Recommended exports:

```python
from loom.pipeline.execution import (
    FailurePolicy,
    PipelineRunner,
    RunRequest,
    RunResult,
    StageExecutionRequest,
    StageExecutionResult,
)
```

### 20.2 Executor Types

V0 executor exports:

```python
from loom.pipeline.executors import Executor, LocalExecutor
```

Post-v0 recommended exports:

```python
from loom.pipeline.executors import (
    Executor,
    LocalExecutor,
    SubprocessExecutor,
)
```

Avoid importing optional cluster or container executors from the main package if
they require optional behavior.

### 20.3 Convenience API

Recommended convenience:

```python
from loom.pipeline.execution import (
    RunRequest,
    create_authority_backed_serial_run_store,
    run_pipeline,
)
from loom.pipeline.stores import path_to_run_uri

run_store = create_authority_backed_serial_run_store("runs")
run_uri = path_to_run_uri("runs/example")
result = run_pipeline(
    RunRequest(pipeline=pipeline, run_uri=run_uri),
    run_store=run_store,
)
```

The convenience API should call `PipelineRunner`, not duplicate its logic.

### 20.4 API Stability

Stable public concepts:

```text
PipelineRunner
Executor protocol
StageExecutionRequest
StageExecutionResult
RunResult
```

Internal modules can change as long as these concepts remain importable from
the public package boundary.

---

## 21. CLI Integration

### 21.1 `loom run`

Functional CLI commands are post-v0. V0 provides only import-safe CLI modules
and unsupported stubs.

`loom run` should:

```text
load and resolve config
construct PipelineSpec
select executor
construct RunRequest
call PipelineRunner.run
print concise run summary
return non-zero on failure
```

Example:

```bash
loom run experiment.yaml --run-uri file:///abs/project/runs/example --executor local
```

### 21.2 `loom stage run`

`loom stage run` is the direct parent-managed worker entry point for one
prepared stage attempt. Subprocess workers invoke this command instead of
embedding stage execution logic. Submitted afterok workers use `loom stage-job
run` so they can finalize one stage without a live parent process.

It should:

```text
open an existing run URI
load stage information
run exactly one stage attempt
write structured result
exit with meaningful code
```

Example:

```bash
loom stage run --run-uri file:///abs/project/runs/example --stage train --attempt 1
```

It should not:

```text
perform whole-pipeline planning
modify unrelated stages
finalize the whole run
submit scheduler jobs
```

Current direct-worker exit codes:

```text
0  successful worker result handoff
1  failed stage result handoff
2  usage error
3  missing, invalid, or ambiguous prepared worker state
130 interrupted
```

### 21.3 `loom logs`

Functional CLI commands are post-v0.

Execution should make logs easy for CLI commands to find:

```bash
loom logs runs/example train
```

The CLI should use run-store path helpers or metadata rather than assuming path
strings.

### 21.4 `loom status`

Functional CLI commands are post-v0.

Execution should write enough state for:

```bash
loom status runs/example
```

to show:

```text
run status
current or failed stage
stage counts
started and finished times
failure summary
```

The CLI should not import project stage code just to show status.

---

## 22. Error Model

### 22.1 ExecutionError

Base error for runner lifecycle failures.

Examples:

```text
plan cannot be executed
stage action is invalid
stage context cannot be constructed
stage commit fails
run finalization fails
```

### 22.2 ExecutorError

Base error for backend invocation failures.

Examples:

```text
subprocess executable missing
command cannot be built
backend option invalid
worker result missing after process exit
```

### 22.3 StageFailed

Structured representation of a stage failure.

This may be an exception type, a result status, or both. It should include:

```text
stage name
attempt
executor
message
failure path
```

### 22.4 OutputValidationError

Raised when stage outputs do not satisfy the declared contract.

Examples:

```text
required output missing
unknown output returned
output value is not ArtifactRef
artifact path is unsafe
artifact file missing
checksum mismatch
```

### 22.5 Error Message Shape

Errors should be path-aware and stage-aware.

Example:

```text
Stage output validation failed at pipeline.stages.train.outputs.metrics:
required output "metrics" was not returned by stage "train"
```

For executor failures:

```text
Subprocess executor failed for stage "train" attempt 1:
exit code 1; see stages/train/logs/stderr.log
```

---

## 23. Testing Strategy

### 23.1 Runner Lifecycle Tests

Test:

```text
fresh successful run
failed stage stops downstream stages
skipped stage is not executed
reused stage is not executed
outputs are persisted before succeeded status
failure metadata is written before failed status
run status finalizes correctly
```

### 23.2 Executor Contract Tests

Each executor should pass shared contract tests:

```text
successful stage returns outputs
stage exception becomes failed result
stdout/stderr paths are populated when supported
executor metadata includes executor name
invalid request fails clearly
```

### 23.3 LocalExecutor Tests

Test:

```text
stage.run(context, inputs)
returned ArtifactRef mapping
Python exception capture
traceback file writing
```

### 23.4 Post-v0 SubprocessExecutor Tests

Test:

```text
command construction
successful worker result
non-zero exit with result file
non-zero exit without result file
stdout/stderr log capture
working directory behavior
environment summary redaction
```

These can use tiny dummy stages and temporary run directories.

### 23.5 Store Integration Tests

Test:

```text
stage inputs are written before execution
outputs are written after success
artifact index updates after output validation
failure files are inspectable
interrupted RUNNING stages are not reused
```

### 23.6 Post-v0 CLI Smoke Tests

Test:

```text
loom run with local executor
loom status after success
loom status after failure
loom logs finds expected paths
```

The CLI tests should assert behavior through files and exit codes, not internal
implementation details.

---

## 24. Initial Implementation Plan

### 24.1 Phase 1: Core Types

Implement:

```text
StageExecutionRequest
StageExecutionResult
RunRequest
RunResult
FailurePolicy
Executor protocol
ExecutionError types
```

Keep fields minimal but explicit.

### 24.2 Phase 2: Local Runner

Implement:

```text
PipelineRunner.run
serial stage loop
local executor invocation
stage lifecycle writes
output validation
failure handling
run finalization
```

Use temporary directories and dummy stages for tests.

### 24.3 Phase 3: Context Helpers

Implement:

```text
StageContext output path allocation
context.save_artifact
context.register_artifact
returned ArtifactRef mapping validation
```

Keep the helpers generic and artifact-store backed.

### 24.4 Post-v0: Subprocess Worker

Implement:

```text
loom stage run
SubprocessExecutor
worker result file
stdout/stderr capture
exit code mapping
```

This phase should reuse local stage invocation code where possible.

### 24.5 Phase 5: Operational Polish

Implement:

```text
better log commands
execution summaries
keyboard interruption handling
basic timeout plumbing for subprocesses
executor registry, if needed
```

### 24.6 Deferred Phases

Defer:

```text
parallel local execution
automatic retries
SLURM afterok
SLURM controller mode
Docker and Apptainer
remote stores
distributed locking
```

Each should have a design document or design section before implementation.

---

## 25. Summary

`loom.pipeline.execution` should be a small, explicit coordinator around a
planned pipeline.

The core contract is:

```text
planner decides what should happen
runner records lifecycle and commits results
executor invokes one stage
stores persist inspectable state
project code performs domain work
```

The v0 execution system should prioritize serial local correctness, durable
state, clear logs, and structured failures. Subprocess execution should use the
same lifecycle so later SLURM and container backends can reuse the model instead
of introducing a separate execution semantics.
