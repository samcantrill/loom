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

The v0 design is local in-process execution only. Subprocess, cluster, and
container execution details in this document are future scaffolding and must not
be treated as v0 acceptance criteria unless the implementation plan adds a
phase for them.

### 1.1 Alignment With `loom.md`

This document refines stage execution goals from [loom.md](../loom.md). It keeps
execution as a coordinator over an already validated plan: project stages do the
work, stores persist state, executors invoke stages, and the runner records
outcomes without interpreting domain behavior. For v0, that executor is local
and in-process.

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

### 3.7 `loom.config`

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

For v0, pipeline stage mappings are orchestration specs. Execution imports the
stage `target_path`, calls the target with no constructor kwargs, then invokes
`stage.run(context, inputs)`. It should not treat stage mappings as generic
`_target_` object graphs or implement config loading rules.

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
retry policies beyond a single attempt
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
run_id
stage_name
run directory
stage directory
artifact store
run store helpers
output path allocation
resolved stage config
runtime metadata
```

`StageContext` should be generic. It should not contain project-specific helper
methods.

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
slurm-afterok, later
slurm-single-job, later
docker, later
```

Invocation mode belongs to executor metadata, not to the stage implementation.

### 5.8 Runtime Profile

Runtime profiles and typed resource hints are post-v0. In v0, stage resources
are opaque plain-data metadata preserved for inspection; the local executor does
not interpret them.

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
    "command": ["loom", "stage", "run", "--run-dir", "..."],
    "exit_code": 1
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
4. Prepare atomic write state; do not acquire a run lock in v0.
5. Persist run metadata and resolved config references.
6. Build or receive the execution plan.
7. Persist plan.json.
8. Initialize root run status.
9. Iterate stage plans in dependency order.
10. Apply non-RUN actions without executor invocation.
11. Prepare each RUN stage attempt.
12. Persist bound inputs.
13. Persist fingerprint candidate.
14. Mark the stage RUNNING.
15. Invoke the executor.
16. Validate returned outputs.
17. Persist outputs.
18. Update artifact index.
19. Mark the stage SUCCEEDED.
20. On failure, persist failure metadata and mark FAILED.
21. Stop or continue according to failure policy.
22. Finalize root run status.
23. Release any post-v0 run lock if one is later added.
24. Return a structured run result.
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
  preserve or record reused artifact refs without executor invocation

SKIP:
  mark stage skipped if the plan requires a persisted status

BLOCKED:
  do not run; record blocked reason in run result

STALE:
  do not run directly; stale should normally resolve to RUN or BLOCKED
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
run_id
run_dir
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
    pipeline: PipelineSpec
    run_dir: Path
    run_id: str | None = None
    resolved_config: Mapping[str, Any] | None = None
    resume: ResumePolicy | None = None
    selectors: StageSelector | None = None
    executor: Executor | None = None
    failure_policy: FailurePolicy | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class PipelineRunner:
    def run(self, request: RunRequest) -> RunResult:
        ...
```

Convenience function:

```python
def run_pipeline(
    pipeline: PipelineSpec,
    *,
    run_dir: Path,
    executor: Executor | None = None,
    resume: ResumePolicy | None = None,
    selectors: StageSelector | None = None,
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

### 9.1 V0 Fields

Recommended dataclass:

```python
@dataclass(frozen=True)
class StageExecutionRequest:
    run_id: str
    run_dir: Path
    stage_name: str
    stage_spec: StageSpec
    stage_context: StageContext
    inputs: Mapping[str, ArtifactRef]
    expected_outputs: Mapping[str, OutputSpec]
    fingerprint: str
    resources: ResourceSpec | None
    stdout_path: Path
    stderr_path: Path
    traceback_path: Path
    executor_metadata_path: Path
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

StageExecutionRequest.stage_spec:
  always present

StageExecutionRequest.run_dir:
  always present
```

For future subprocess execution, the command should load the run directory and
stage spec rather than trying to pickle Python objects.

### 9.3 Serialization Boundary

`StageExecutionRequest` does not need to be fully JSON-serializable in v0 for
local execution.

However, the persistent subset should be clear:

```text
run_id
run_dir
stage_name
attempt
input artifact refs
expected output specs
fingerprint
resources metadata
log paths
```

Subprocess and future remote executors should pass only stable identifiers on
the command line and read durable state from the run directory.

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
exception_type or exit_code
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

### 11.7 Lifecycle Event Sinks

Future runner implementations may emit generic lifecycle events while preserving
the same status semantics.

Events may include:

```text
run started
stage started
stage succeeded
stage failed
run finished
submission created
```

The execution layer should only produce structured event records or call a small
callback interface. Service-specific notification delivery should live outside
core `loom`.

---

## 12. StageContext Construction

### 12.1 Required Context Values

Phase 9 runtime context construction may include:

```text
run_id
run_dir
stage_name
stage_dir
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
path = context.output_path("metrics", suffix=".json")
```

The helper should:

```text
validate logical output names
avoid path traversal
place files under the stage artifact area
avoid overwriting committed outputs unless explicitly allowed
return pathlib.Path for local stores
```

For remote artifact stores, a future context may return a URI or provide a
different writer API.

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
closer behavior to SLURM and containers
debugging command entry points
avoiding leaked in-process state
```

It is the bridge between local execution and future remote execution.

### 15.2 Command Contract

Recommended command:

```bash
loom stage run --run-dir RUN_DIR --stage STAGE_NAME --attempt ATTEMPT
```

Optional flags:

```text
--config CONFIG_PATH
--executor-worker
--log-level LEVEL
--strict
```

The command should not require pickled Python objects. It should reconstruct
stage context from run-store files and resolved config.

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

### 15.5 Result Handoff

Recommended worker output:

```text
stages/<stage>/attempts/<attempt>/result.json
```

or the v0 equivalent under the stage directory.

The result should include:

```text
status
outputs
exception metadata
log paths
executor metadata
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

### 15.7 Environment

The subprocess executor should default to:

```text
current Python executable
current environment
current working directory or configured project root
```

Future options:

```text
explicit Python executable
environment variable overlays
clean environment mode
project root
module invocation
```

Keep v0 simple and record the actual command and working directory in executor
metadata.

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
run_id
stage_name
attempt
failed_at
executor
exception_type
message
traceback_path
exit_code
stdout_path
stderr_path
executor_metadata
```

For local execution, Python exception fields are primary.

For subprocess and future SLURM execution, exit code and log paths are primary.

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

Possible future generic fields:

```text
cpus
memory_mb
gpus
wall_time_seconds
disk_gb
tmp_gb
```

These fields would be hints. The v0 local executor ignores
`StageSpec.resources`; post-v0 SLURM or container executors can translate a
typed resource model after that contract is introduced.

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
    cpus: 16
    memory_mb: 65536
    gpus: 1
    wall_time_seconds: 28800
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

V0 should not automatically retry failed stages.

Future retry policy:

```yaml
retry:
  max_attempts: 2
  retry_on:
    - executor_failure
    - timeout
```

Retries require careful attempt directories, failure preservation, and artifact
commit semantics. They should be designed after single-attempt execution is
stable.

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
```

Run-store lock methods are post-v0 unless atomic/interruption tests prove a lock
manager is required.

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

V0 does not acquire a run-level lock by default. It relies on atomic writes and
conservative resume validation. Revisit locking only if atomic-write,
interrupted-run, or concurrent-run tests expose a concrete race.

Post-v0, a run-level lock may protect:


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
from loom.pipeline.execution import run_pipeline

result = run_pipeline(
    pipeline,
    run_dir=Path("runs/example"),
    executor=LocalExecutor(),
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
loom run experiment.yaml --run-dir runs/example --executor local
```

### 21.2 `loom stage run`

`loom stage run` is the future subprocess worker entry point. It is not part of
v0 functional behavior.

It should:

```text
open an existing run directory
load stage information
run exactly one stage attempt
write structured result
exit with meaningful code
```

Example:

```bash
loom stage run --run-dir runs/example --stage train --attempt 1
```

It should not:

```text
perform whole-pipeline planning
modify unrelated stages
finalize the whole run
submit scheduler jobs
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
