# `loom.pipeline.executors.slurm` Specification

## 0. Implementation Status

V7 implements both the cluster-free SLURM dry-run planning layer and optional
live SLURM submission. The dry-run commands remain:

```bash
loom run experiment.yaml --executor slurm-single-job --dry-run
loom run experiment.yaml --executor slurm-afterok --dry-run
```

These commands create deterministic run-directory artifacts without calling
`sbatch`: root `plan.json`, `prepared_run.json`, a
`slurm/submissions/<planning_id>/manifest.json`, a SLURM dry-run plan, generated
scripts, and stable wrapper stdout/stderr log paths. Missing `sbatch` is a
warning in dry-run preflight output.

The live commands are:

```bash
loom run experiment.yaml --executor slurm-single-job
loom run experiment.yaml --executor slurm-afterok
loom status RUN_URI --jobs
loom cancel RUN_URI --jobs
```

Live submission uses `sbatch --parsable`, records scheduler job IDs in the same
`slurm/submissions/<submission_id>/manifest.json` artifact, marks submitted work
as `SUBMITTED`, and stores command records, status snapshots, cancellation
attempts, partial submission facts, and safe scheduler metadata. Missing
`sbatch` is a live-submission error. Missing `squeue`, `sacct`, or `scancel`
is a preflight warning, while the operation that needs the command fails clearly
at use time.

V11 queue delegated SLURM dispatch is a queue-service adapter path rather than a
replacement for live submitted-operation manifests. A delegated queue item
stores the queue-owned `run_uri`, the external SLURM job id returned by
`sbatch --parsable`, the submit command record, and status-read evidence in its
dispatch handle. Foreground queue draining may exit only after the external
handle is persisted and at least one downstream `squeue` or `sacct` read has
succeeded. Delegated SLURM-pending work does not hold Loom resource leases by
default; downstream SLURM capacity owns pending/running admission until richer
bundle or submit-host transport exists. If the external handle is active but no
authority run is visible yet, queue status reports that as diagnostic evidence
and continues to reuse the same handle instead of resubmitting.
See [queue.md](queue.md) for the queue config, CLI, and preflight surfaces for
delegated SLURM pools.

Generated single-job scripts call the generic whole-run continuation command:

```bash
loom prepared-run continue --run-uri RUN_URI --executor local
```

Generated afterok scripts call the generic self-finalizing stage-job command:

```bash
loom stage-job run --run-uri RUN_URI --stage STAGE --executor local
```

Manifests use logical job keys such as `pipeline` and `stage:train`; live
records add scheduler job IDs and backend state without replacing the generic
run-store lifecycle. Default validation remains fake-command and cluster-free.
The real SLURM acceptance suite is marked `slurm` and `slow` and runs only when
the maintainer explicitly enables it.

### 0.1 Authority Deployment Profiles

Post-v9 SLURM support must treat authority deployment as an explicit selected
profile instead of assuming a long-running login-node service is always
available.

Supported authority handoff profiles:

- Managed service authority: jobs receive an authority reference, endpoint,
  run URI, stage name, attempt id, owner id, lease id, and fencing token.
  Preflight must prove service health and compute-to-authority reachability
  before live jobs are submitted.
- Allocation-scoped service authority: the scheduler allocation owns service
  start, health check, endpoint distribution, shutdown, and recovery notes.
  Live workers use the same authority reference, endpoint, lease, and fencing
  handoff fields, but the service lifetime is tied to the allocation.
- Direct transactional database authority: jobs receive a redacted authority
  reference and database endpoint only when the backend proves the transaction,
  server-time, lease, and fencing capabilities required for live commits.
- Co-located authority: development/test authority for one process or host. It
  must not be advertised as live multi-host SLURM authority.
- Deferred finalization: workers do not receive live fencing material. They
  write a sealed result envelope plus materialized outputs; a controller or
  reconciler later accepts or rejects that evidence through authority.

Deferred result envelopes are not lifecycle state. A successful envelope becomes
visible only when authority reconciliation validates the recorded submission and
attempt, rejects stale/cancelled/superseded evidence, and commits through the
authority store with reconciler-held fencing material.

V9-post command generation carries authority selection explicitly. `loom run`,
`loom prepared-run continue`, `loom stage run`, `loom stage-job run`,
`loom status --jobs`, `loom cancel --jobs`, preflight, and backend diagnostics
all accept the shared authority flags used by the runtime store adapter. Dry-run
manifests and generated worker commands include redacted authority summaries so
reviewers can confirm which backend/profile will be used without exposing
service credentials. Live SLURM still requires backend capability admission:
development co-located service authority is suitable for local and subprocess
proof paths, but it is not advertised as a multi-host SLURM authority.

## 1. Purpose

`loom.pipeline.executors.slurm` is the optional cluster execution layer for
running `loom` pipelines on SLURM-managed systems.

It translates a validated pipeline plan and generic runtime/resource metadata
into SLURM-oriented scripts, dependency edges, logs, and manifests. It should
not change pipeline semantics. The same stage contracts, artifact references,
run-store state, resume rules, and generic execution-owned continuation
commands should apply whether work runs locally, under subprocess execution, or
through a future submitted backend.

The design should support two practical modes first:

```text
single-job:
  submit one SLURM job that runs the whole pipeline inside one allocation

afterok:
  submit one SLURM job per runnable stage and use scheduler dependencies
```

Controller mode, job arrays, and container-specific execution can be added after
these two modes are stable.

### 1.1 Alignment With `loom.md`

[loom.md](../loom.md) includes SLURM as execution scaffolding rather than a core
dependency. This document keeps SLURM optional and executor-shaped: it maps
generic plans and runtime metadata onto scheduler scripts and, in v7/later,
submissions without changing pipeline semantics or requiring a Python SLURM
library.

---

## 2. Core Position

SLURM support is an executor concern.

It should use this architecture:

```text
Pipeline planner:
  decides what stages should run, reuse, skip, or block

Execution layer:
  defines lifecycle, worker command, result files, and run-store updates

SLURM executor:
  maps runnable work to sbatch scripts and scheduler dependencies

SLURM scheduler:
  starts jobs according to resources and dependency constraints

Stage worker:
  runs one stage or one whole pipeline command inside the allocation
```

The SLURM executor should not implement a separate pipeline model. V6 generated
scripts use `loom prepared-run continue` for whole-run single-job scripts and
`loom stage-job run` for afterok stage scripts. `loom stage run` remains the
v5 parent-managed subprocess worker and is not the generated afterok command.

---

## 3. Package Boundary

### 3.1 `loom.pipeline.executors.slurm`

Owns SLURM-specific behavior.

Responsibilities implemented in v6:

```text
SLURM executor modes
SBATCH script generation
generic resource to SBATCH mapping
dependency option construction
dry-run manifest writing
script path allocation
SLURM log path allocation
SLURM-specific dry-run and option errors
```

Responsibilities implemented in v7:

```text
sbatch --parsable live submission
single-job and afterok job ID recording
submitted-operation records
squeue/sacct scheduler-aware status snapshots
scancel cancellation attempts
partial submission and partial cancellation reporting
active submitted-work guards
```

SLURM command execution uses `subprocess` through a fakeable command-runner
abstraction. SLURM support does not require a Python SLURM dependency.

### 3.2 `loom.pipeline.execution`

Owns generic execution lifecycle.

Responsibilities:

```text
RunRequest and RunResult
StageExecutionRequest and StageExecutionResult
stage lifecycle semantics
subprocess worker command contract
result file shape
failure metadata shape
```

The SLURM executor should reuse these contracts.

### 3.3 `loom.pipeline.planning`

Owns stage actions and dependency planning.

Responsibilities:

```text
topological order
stage action calculation
resume and reuse decisions
selector application
downstream invalidation
blocked-stage explanations
```

The SLURM executor consumes a plan. It should not decide whether an artifact is
reusable.

### 3.4 `loom.pipeline.stores.run_store`

Owns persisted run state.

Responsibilities:

```text
run metadata
plan.json
stage inputs
stage fingerprints
stage status
stage failures
logs
submission manifests
lock files
```

The SLURM executor should use run-store path helpers when writing scripts,
manifests, and submission state.

### 3.5 `loom.pipeline.stores.artifact_store`

Owns artifact persistence and validation.

Responsibilities:

```text
artifact refs
artifact files
artifact registration
checksums
artifact index
```

SLURM jobs should communicate outputs through the same artifact-store and
run-store state as subprocess execution.

### 3.6 `loom.cli`

Owns user-facing commands.

Responsibilities:

```text
select slurm executor mode
parse resource overrides
submit pipelines or stages
print job IDs
show submission status
cancel submitted jobs
```

The CLI should call Python APIs. It should not generate SBATCH scripts directly.

### 3.7 Project Code

Owns domain-specific stage behavior.

Responsibilities:

```text
load data
run training or analysis
write output files
return ArtifactRefs
handle application-level checkpoints
```

Project code should not need to know whether it is running under local,
subprocess, or SLURM execution except through generic environment and runtime
metadata.

---

## 4. Initial Scope

### 4.1 Must Support in First SLURM Implementation

```text
single-job mode
afterok per-stage mode
script generation into the run directory
dry-run manifest JSON
afterok dependency construction
generic CPU, memory, and GPU mapping
optional partition/account/qos mapping
stdout/stderr log paths
continuation command handoff through run-store files
dry-run script generation without submission
missing sbatch reported as warning/info for dry-runs
live sbatch submission for single-job and afterok modes
scheduler-aware status through loom status RUN_URI --jobs
submitted-job cancellation through loom cancel RUN_URI --jobs
```

The first implementation should assume a shared filesystem visible to the submit
host and compute nodes. This matches common HPC usage and keeps remote artifact
transfer out of the first design.

Automatic retries, cleanup policies, exact submitted-operation selection, and
remote artifact transfer remain later scope.

### 4.2 Should Not Support Initially

```text
Python SLURM libraries
dynamic DAG mutation
controller mode
job arrays
multi-node MPI orchestration
interactive allocations
advanced srun behavior
automatic cluster module discovery
automatic environment capture of all variables
remote artifact synchronization
cross-cluster submission
cloud batch backends
container runtimes beyond passing command lines
automatic retry based on sacct state
parallel local fallback scheduling
```

These features can be added later with explicit design work.

---

## 5. Terminology

### 5.1 SLURM

The workload manager used by many HPC clusters. `loom` should interact with it
through command-line tools such as:

```text
sbatch
squeue
sacct
scancel
```

### 5.2 SBATCH Script

A shell script containing `#SBATCH` directives and a command body.

Example shape:

```bash
#!/usr/bin/env bash
#SBATCH --job-name=loom-train
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=08:00:00

loom stage-job run --run-uri file:///abs/project/runs/example --stage train --executor local
```

### 5.3 Submission Manifest

A JSON file written by `loom` that records planned dry-run jobs in v6 and
submitted jobs in v7/later.

It should include:

```text
run_id
mode
created_at
submit_host
jobs
scripts
commands
dependencies
```

The manifest should make a planned or submitted run inspectable even after the
planning or submit process exits.

### 5.4 Job ID

The identifier returned by `sbatch --parsable`.

The parser should handle common shapes:

```text
123456
123456;cluster_name
```

The stable `loom` job ID field should store the numeric job ID as a string and
preserve the raw parser output separately.

### 5.5 Dependency

A scheduler constraint that delays one job until another job reaches a required
state.

Initial dependency type:

```text
afterok
```

This means downstream jobs run only if upstream jobs complete successfully.

### 5.6 Single-Job Mode

One SLURM job runs the entire pipeline command inside one allocation. In v6, the
generated dry-run script plans this continuation command:

```bash
loom prepared-run continue --run-uri RUN_URI --executor local
```

V7 live submission can submit the same script shape.

Older designs used commands such as:

```bash
loom run CONFIG --run-dir RUN_DIR --executor local
```

or an equivalent resolved-config command. V6 rejects that shape for generated
scripts because unredacted resolved config can contain resolver outputs and
secrets.

### 5.7 Afterok Mode

One SLURM job is planned for each stage that the plan says should run. V7 can
submit those scripts and map logical job keys to scheduler job IDs.

Each stage job invokes:

```bash
loom stage-job run --run-uri RUN_URI --stage STAGE --executor local
```

Downstream jobs are submitted with `--dependency=afterok:<job_id>` options.

### 5.8 Controller Mode

A long-running controller process submits ready jobs, polls job state, and
submits downstream jobs dynamically.

This mode is explicitly deferred. It is useful but more complex because the
controller itself must be recoverable.

### 5.9 Submit Host

The machine where `loom` calls `sbatch`.

The submit host may not be the same host where jobs run.

### 5.10 Compute Node

The machine where SLURM executes a submitted job.

The compute node must be able to read the run directory, resolved config, project
code, and input artifacts needed by the job.

---

## 6. Guiding Design Principles

### 6.1 Use SLURM as a Backend, Not a New Workflow Model

SLURM should run commands that `loom` already understands.

The command body should be built from stable continuation entry points:

```text
loom prepared-run continue
loom stage-job run
```

This avoids a second path for stage construction, artifact registration, and
failure handling.

### 6.2 Scripts Are Durable Artifacts of Submission

Generated scripts should be written under the run directory before submission.

Users should be able to inspect:

```text
what command was submitted
what resources were requested
what environment setup ran
where logs were written
what dependencies were declared
```

Scripts should be deterministic enough for debugging and reproducibility.

### 6.3 No Required Python SLURM Dependency

The first implementation should use:

```text
subprocess.run(["sbatch", ...])
subprocess.run(["squeue", ...])
subprocess.run(["sacct", ...])
subprocess.run(["scancel", ...])
```

This keeps the runtime dependency policy small and works on clusters that expose
standard SLURM commands.

### 6.4 Shared Filesystem First

Initial SLURM support should assume the run directory is visible from both the
submit host and compute nodes.

This keeps the first implementation focused on:

```text
script generation
job submission
dependencies
run-store state
logs
```

instead of remote file staging.

### 6.5 Resource Metadata Is Generic First

Pipeline specs should use generic resource entries:

```text
cpu
memory
gpu
```

SLURM-specific fields should live under a nested key:

```yaml
slurm:
  partition: gpu
  account: research
  qos: normal
```

Generic `ResourceSpec` should not become SLURM-shaped.

### 6.6 Submission Must Be Inspectable After Logout

Afterok mode should not require the original Python process to remain alive.

The submission manifest should be enough to answer:

```text
which jobs were submitted?
which stage does each job run?
which job IDs are upstream dependencies?
where are scripts and logs?
what command submitted each job?
```

### 6.7 Stage Jobs Should Be Self-Contained

Each per-stage job should be able to run from durable run-store state.

The job should not need:

```text
pickled Python objects
open file handles from the submit process
in-memory planner state
live parent process coordination
```

It may need:

```text
run directory
resolved config
stage name
attempt number
project environment
```

### 6.8 Conservative Failure Semantics

If SLURM submission fails, the run should not look successfully submitted.

If a stage job fails, downstream `afterok` jobs should not start.

If a job disappears or has unknown state, `loom` should report uncertainty
rather than inventing success.

### 6.9 Cluster Portability Over Clever Defaults

SLURM clusters vary.

The design should avoid assumptions about:

```text
module systems
conda activation
GPU resource syntax
accounting configuration
job output defaults
available sacct fields
container runtime
filesystem layout
```

Prefer explicit user-provided script prelude and backend options.

---

## 7. Execution Modes

### 7.1 Mode Vocabulary

Recommended mode strings:

```text
slurm-single-job
slurm-afterok
slurm-controller, later
```

The mode should be recorded in:

```text
submission manifest
run status
stage status
executor metadata
failure metadata
```

### 7.2 Single-Job Mode

Single-job mode plans one script that runs a whole pipeline continuation
command. V7 can submit that script.

Implemented v6 command body:

```bash
loom prepared-run continue --run-uri RUN_URI --executor local
```

Rejected older shape:

```bash
loom run --resolved-config RUN_DIR/config/resolved.yaml --run-dir RUN_DIR --executor local --resume
```

Generated v6 scripts should not replay unredacted resolved config. They read
the prepared run from durable run-store state.

### 7.3 Single-Job Use Cases

Use single-job mode for:

```text
small pipelines
homogeneous resource needs
one allocation workflows
CI-like reproduction on a cluster
debugging cluster environment setup
projects that prefer one scheduler job per run
```

It is simpler than afterok mode because one process keeps normal runner
semantics.

### 7.4 Single-Job Limitations

Single-job mode is less suitable for:

```text
pipelines with mixed CPU and GPU stages
long preprocessing followed by short training
large DAGs with independent branches
stage-specific walltimes
stage-specific partitions
isolating failed stages
```

Users should choose afterok mode when stage-level resources matter.

### 7.5 Afterok Mode

Afterok mode plans one job per `RUN` stage. V7 can submit those planned jobs in
topological order.

For each runnable stage, the script body should invoke:

```bash
loom stage-job run --run-uri RUN_URI --stage STAGE_NAME --executor local
```

The v6 manifest records logical dependencies. The v7 submitter can translate
those logical keys into scheduler dependencies:

```bash
sbatch --dependency=afterok:UPSTREAM_JOB_ID script.sh
```

For multiple upstream jobs:

```bash
sbatch --dependency=afterok:JOB_A:JOB_B script.sh
```

The exact formatting should match the SLURM version in use, but this should be
the default.

### 7.6 Afterok Use Cases

Use afterok mode for:

```text
stage-specific resources
mixed CPU and GPU workflows
large experiments where the submit process should exit
scheduler-native dependency handling
isolated logs per stage
rerunning failed stages selectively
```

### 7.7 Afterok Limitations

Afterok mode has trade-offs:

```text
all jobs are submitted up front
downstream jobs may stay pending for a long time
changing the plan after submission is hard
submission can fail partway through
cancel behavior needs to traverse submitted job IDs
failure status may require job-state inspection
```

These trade-offs are acceptable for a first robust cluster mode.

### 7.8 Controller Mode

Controller mode is deferred.

It would:

```text
submit jobs as dependencies complete
poll scheduler status
support custom retry behavior
inspect artifacts before downstream submission
recover from controller restart
```

It needs a separate design because it changes lifecycle behavior substantially.

---

## 8. SLURM Configuration Model

### 8.1 Pipeline-Level Defaults

Pipeline specs may define SLURM defaults:

```yaml
pipeline:
  defaults:
    runtime:
      executor: slurm-afterok
      resources:
        entries:
          cpu:
            kind: cpu
            amount: 4
            unit: count
          memory:
            kind: memory
            amount: 16
            unit: GiB
      slurm:
        partition: normal
        account: research
        time: "02:00:00"
```

Stage-level values override defaults.

### 8.2 Stage-Level Runtime

Example:

```yaml
stages:
  - name: train
    _target_: project.stages.Train
    runtime:
      resources:
        entries:
          cpu:
            kind: cpu
            amount: 16
            unit: count
          memory:
            kind: memory
            amount: 64
            unit: GiB
          gpu:
            kind: gpu
            amount: 1
            unit: count
      slurm:
        partition: gpu
        qos: long
        time: "08:00:00"
```

The generic execution layer carries this metadata. The SLURM executor maps it to
SBATCH options.

### 8.3 SLURM-Specific Fields

Recommended nested fields:

```text
partition
account
qos
constraint
gres
nodes
ntasks
cpus_per_task
mem
mem_per_cpu
time
mail_type
mail_user
exclusive
reservation
licenses
extra_sbatch
prelude
```

Do not add every possible SLURM option as a typed top-level field immediately.
Use `extra_sbatch` for uncommon options.

### 8.4 Script Prelude

Users often need environment setup:

```bash
module load python/3.11
source .venv/bin/activate
export OMP_NUM_THREADS=1
```

Recommended config:

```yaml
slurm:
  prelude:
    - module load python/3.11
    - source .venv/bin/activate
```

Prelude lines are trusted project config. They should be written verbatim into
generated scripts after basic type validation.

### 8.5 Extra SBATCH Options

Recommended shape:

```yaml
slurm:
  extra_sbatch:
    --signal: "B:USR1@60"
    --requeue: true
```

Boolean `true` means flag without value:

```bash
#SBATCH --requeue
```

String values mean flag with value:

```bash
#SBATCH --signal=B:USR1@60
```

V0 may also accept a list of raw strings for maximum portability:

```yaml
slurm:
  extra_sbatch:
    - "--signal=B:USR1@60"
    - "--requeue"
```

### 8.6 Trust Boundary

Authored configs are trusted project code.

The SLURM executor should validate types and path safety, but it does not need
to sandbox script prelude or raw extra options.

---

## 9. Resource Mapping

### 9.1 Generic Mapping

Recommended mapping:

```text
resources.entries.cpu        -> --cpus-per-task
resources.entries.memory     -> --mem=<N>
slurm.time           -> --time
resources.entries.gpu        -> --gres=gpu:<N>, unless slurm.gres is set
```

If `slurm.cpus_per_task`, `slurm.mem`, `slurm.time`, or `slurm.gres` is set,
the explicit SLURM value should override the generic mapping.

### 9.2 CPU

Generic:

```yaml
resources:
  entries:
    cpu:
      kind: cpu
      amount: 16
      unit: count
```

SBATCH:

```text
#SBATCH --cpus-per-task=16
```

If users need `--ntasks`, they should set `slurm.ntasks`.

### 9.3 Memory

Generic:

```yaml
resources:
  entries:
    memory:
      kind: memory
      amount: 64
      unit: GiB
```

SBATCH:

```text
#SBATCH --mem=64G
```

If users need memory per CPU, they should set:

```yaml
slurm:
  mem_per_cpu: 4G
```

The executor should avoid emitting both `--mem` and `--mem-per-cpu` unless the
user explicitly requests that behavior.

### 9.4 GPU

Generic:

```yaml
resources:
  entries:
    gpu:
      kind: gpu
      amount: 1
      unit: count
```

Default SBATCH:

```text
#SBATCH --gres=gpu:1
```

Clusters vary in GPU syntax. Users may override:

```yaml
slurm:
  gres: gpu:a100:1
```

The executor should not try to infer cluster-specific GPU names.

### 9.5 Walltime

Generic:

```yaml
slurm:
  time: "08:00:00"
```

SBATCH:

```text
#SBATCH --time=08:00:00
```

The executor should validate simple string shape but avoid overfitting to every
SLURM time format.

### 9.6 Partition, Account, and QOS

SLURM-specific:

```yaml
slurm:
  partition: gpu
  account: research
  qos: long
```

SBATCH:

```text
#SBATCH --partition=gpu
#SBATCH --account=research
#SBATCH --qos=long
```

These should not appear as generic resource fields.

### 9.7 Job Name

Recommended job name:

```text
loom-<run_id>
loom-<run_id>-<stage_name>
```

Names should be sanitized:

```text
replace unsafe characters with "-"
truncate to a conservative length
preserve enough stage identity for squeue readability
```

The full run and stage identity remains in the manifest.

---

## 10. Directory Layout

### 10.1 Recommended Layout

Recommended run directory additions:

```text
run-dir/
  slurm/
    submission.json
    scripts/
      pipeline.sh
      stages/
        prepare.sh
        train.sh
        evaluate.sh
    logs/
      pipeline/
        stdout.log
        stderr.log
      stages/
        prepare/
          stdout.log
          stderr.log
        train/
          stdout.log
          stderr.log
    jobs/
      123456.json
      123457.json
```

The exact layout can be owned by `RunStore` helpers, but all SLURM state should
live under the run directory.

### 10.2 Scripts Directory

Generated scripts should be stable files:

```text
slurm/scripts/pipeline.sh
slurm/scripts/stages/<stage>.sh
```

For repeated submissions, either overwrite only when safe or include a
submission attempt directory:

```text
slurm/submissions/<submission_id>/scripts/
```

V0 may use one submission directory per call to avoid accidental overwrites.

### 10.3 Logs Directory

SBATCH output directives should point to known paths:

```text
#SBATCH --output=.../slurm/logs/stages/train/stdout.log
#SBATCH --error=.../slurm/logs/stages/train/stderr.log
```

These are SLURM wrapper logs. Stage-level `loom` logs may also exist under:

```text
stages/<stage>/logs/
```

The manifest should point to both where applicable.

### 10.4 Job State Files

Optional per-job state files:

```text
slurm/jobs/<job_id>.json
```

Recommended fields:

```text
schema_version
job_id
raw_job_id
run_id
stage_name
mode
script_path
stdout_path
stderr_path
submitted_at
dependency_job_ids
sbatch_command
state
last_checked_at
```

These files make status inspection possible without re-parsing the full
manifest.

---

## 11. Submission Manifest

### 11.1 Purpose

`submission.json` records what was submitted.

It should be useful for:

```text
debugging
status commands
cancellation
postmortem inspection
reconstructing scheduler dependencies
```

### 11.2 Recommended Fields

Recommended top-level fields:

```text
schema_version
run_id
submission_id
mode
created_at
submitted_at
submit_host
submit_user
working_dir
loom_version
plan_path
run_dir
dry_run
jobs
```

Each job entry:

```text
logical_job_name
stage_name
job_id
raw_job_id
script_path
stdout_path
stderr_path
dependency_job_ids
sbatch_command
resources
slurm_options
status
```

### 11.3 Manifest Write Timing

The executor should write a draft manifest before submission:

```text
dry_run = true or status = PREPARED
scripts generated
commands built
job IDs absent
```

During submission, update after each successful `sbatch` call:

```text
job ID recorded
dependency edges recorded
submission command recorded
```

If submission fails partway through, the manifest should preserve the partial
state.

### 11.4 Partial Submission

If a later job fails to submit, earlier jobs may already be queued.

Recommended behavior:

```text
record failed submission
mark submission status PARTIAL
surface error to CLI
offer cancellation command or API
do not silently ignore already submitted jobs
```

The CLI can tell the user which job IDs were submitted before failure.

---

## 12. Script Generation

### 12.1 Script Header

Generated scripts should start with:

```bash
#!/usr/bin/env bash
set -euo pipefail
```

`set -euo pipefail` should be configurable if a cluster or project prelude needs
different shell behavior.

### 12.2 SBATCH Directives

SBATCH directives should be generated from normalized options.

Example:

```bash
#SBATCH --job-name=loom-example-train
#SBATCH --partition=gpu
#SBATCH --account=research
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --time=08:00:00
#SBATCH --output=/runs/example/slurm/logs/stages/train/stdout.log
#SBATCH --error=/runs/example/slurm/logs/stages/train/stderr.log
```

The executor should generate directives in deterministic order.

### 12.3 Prelude

After directives:

```bash
module load python/3.11
source /path/to/project/.venv/bin/activate
```

Prelude comes from trusted config.

### 12.4 Environment Metadata

The script may export useful `loom` variables:

```bash
export LOOM_RUN_DIR=/runs/example
export LOOM_RUN_ID=example
export LOOM_STAGE_NAME=train
export LOOM_ATTEMPT=1
```

These are convenience variables. The stage worker should still receive explicit
CLI arguments.

### 12.5 Command Body

Single-job command:

```bash
loom prepared-run continue --run-uri file:///runs/example --executor local
```

Per-stage command:

```bash
loom stage-job run --run-uri file:///runs/example --stage train --executor local
```

The script should record the command in comments or metadata for debugging.

### 12.6 Path Quoting

Paths and command arguments should be shell-quoted with standard library helpers
such as `shlex.quote`.

Do not build script commands with unsafe string concatenation.

### 12.7 Script Permissions

Generated scripts should be written with user-executable permissions when
possible:

```text
0o755
```

Readability and reproducibility matter more than strict secrecy. Do not write
secrets into scripts by default.

---

## 13. Single-Job Submission Flow

### 13.1 High-Level Flow

Recommended flow:

```text
1. Resolve config and create/open run directory.
2. Build or load execution plan.
3. Write plan.json.
4. Generate one pipeline SBATCH script.
5. Write draft submission manifest.
6. Submit script with sbatch --parsable.
7. Parse job ID.
8. Update submission manifest.
9. Mark run status SUBMITTED if that status exists, or record submission metadata.
10. Return submitted run result to CLI.
```

The actual pipeline execution occurs inside the SLURM job.

### 13.2 Command Inside the Job

The generated job invokes the prepared whole-run continuation command:

```bash
loom prepared-run continue --run-uri RUN_URI --executor local
```

The inner executor should usually be local or subprocess, not another SLURM
executor, to avoid accidental recursive submission.

### 13.3 Run Status

The submit process may not know final run status.

Recommended statuses:

```text
SUBMITTED, if added to run status vocabulary
RUNNING, once the inner job starts and updates status
SUCCEEDED or FAILED, once the inner runner finalizes
```

If `SUBMITTED` is not part of v0 status vocabulary, record submission state in
SLURM metadata and let the inner job mark `RUNNING`.

### 13.4 Failure Cases

Submission failure:

```text
write failure metadata
mark submission FAILED
do not mark run as successfully submitted
return non-zero CLI exit
```

Job failure:

```text
inner loom run should write normal run failure state
SLURM logs should point to wrapper-level errors
status command may query sacct if run status is inconclusive
```

---

## 14. Afterok Submission Flow

### 14.1 High-Level Flow

Recommended flow:

```text
1. Resolve config and create/open run directory.
2. Build execution plan.
3. Persist plan.json.
4. Prepare stage attempts for all RUN stages.
5. Generate one script per RUN stage.
6. Build job dependency graph from stage dependencies.
7. Write draft submission manifest.
8. Submit jobs in topological order.
9. For each job, parse and record job ID.
10. Attach afterok dependencies for downstream jobs.
11. Mark submitted stages with job metadata.
12. Return submitted run result.
```

The submitter may exit after all jobs are submitted.

### 14.2 Stage Preparation

Before submitting a stage job, the executor should ensure durable state exists:

```text
stage directory
attempt number
inputs.json
fingerprint.json
log paths
stage status indicating submitted or pending
```

The exact status vocabulary may be:

```text
PENDING with slurm job metadata
SUBMITTED if added
```

Stage jobs should mark themselves `RUNNING` when they start.

### 14.3 Dependency Construction

For each stage:

```text
stage dependencies from the plan
only dependencies among submitted RUN jobs become SLURM dependencies
REUSE dependencies do not produce job IDs
SKIP dependencies do not produce job IDs
BLOCKED stages should not be submitted
```

If a stage depends on an upstream stage that is reused, no scheduler dependency
is needed. The artifact refs already exist in the run store.

### 14.4 Fan-In

For fan-in:

```text
report depends on train and evaluate
```

SBATCH:

```bash
sbatch --dependency=afterok:<train_job_id>:<evaluate_job_id> report.sh
```

If SLURM version or site policy requires a different separator, this should be
configurable.

### 14.5 Fan-Out

For fan-out:

```text
prepare -> train_a
prepare -> train_b
```

Both downstream jobs should depend on the same upstream job ID:

```text
train_a: afterok:<prepare_job_id>
train_b: afterok:<prepare_job_id>
```

### 14.6 Diamond Graph

For a diamond:

```text
prepare
  -> train
  -> evaluate
report depends on train and evaluate
```

The executor submits:

```text
prepare: no dependency
train: afterok:prepare
evaluate: afterok:prepare
report: afterok:train:evaluate
```

The pipeline planner owns the DAG. The SLURM executor only maps it to scheduler
dependencies.

### 14.7 Downstream Failure Behavior

With `afterok`, downstream jobs do not start when upstream jobs fail.

This is scheduler-native and desirable, but it means downstream stage status may
remain pending or submitted until inspected.

Status inspection should report:

```text
upstream job failed
downstream job dependency not satisfied
downstream stage not run
```

This may require `sacct` or manifest-based explanation.

---

## 15. Stage Worker Contract Under SLURM

### 15.1 Worker Command

Per-stage SLURM jobs should run:

```bash
loom stage-job run --run-uri RUN_URI --stage STAGE_NAME --executor local
```

This command is distinct from the parent-managed `loom stage run` command used
by `SubprocessExecutor`.

### 15.2 Worker Startup

At startup, the worker should:

```text
open run directory
load stage attempt metadata
mark stage RUNNING
record host, pid, and SLURM job ID when available
load resolved config
construct stage object
construct StageContext
load inputs
```

SLURM job ID is commonly available as:

```text
SLURM_JOB_ID
```

This should be copied into executor metadata.

### 15.3 Worker Completion

On success, the worker should:

```text
validate direct stage result enough to write result.json
write outputs or registered output refs
write worker result file
exit 0
```

Depending on final ownership decisions, either:

```text
worker commits stage outputs and status directly
```

or:

```text
worker writes result file and a collector finalizes commit
```

For afterok mode without a live parent process, the worker likely needs to commit
its own successful stage outputs using shared execution lifecycle helpers.

### 15.4 Worker Failure

On failure, the worker should:

```text
write failure.json
write traceback or log paths
mark stage FAILED
write worker result file when possible
exit non-zero
```

Downstream `afterok` jobs will not run.

### 15.5 Status Ownership Note

Generic subprocess execution can let the parent runner finalize commit after the
worker exits.

SLURM afterok mode usually cannot rely on a live parent. Therefore, the stage
worker should be able to run a self-finalizing stage lifecycle:

```text
prepare was done by submitter
worker marks RUNNING
worker runs stage
worker validates and commits outputs
worker marks SUCCEEDED or FAILED
```

This lifecycle should reuse the same execution helpers as the normal runner.

---

## 16. Job Status Inspection

### 16.1 Status Sources

Status can come from:

```text
run-store status files
submission manifest
squeue
sacct
SLURM log files
```

Preferred order:

```text
1. run-store final stage status
2. sacct final job state when available
3. squeue pending/running state when available
4. submission manifest as last known state
```

### 16.2 `squeue`

`squeue` is useful for active jobs:

```bash
squeue --job <job_id>
```

It may not show completed jobs.

### 16.3 `sacct`

`sacct` is useful for completed jobs:

```bash
sacct -j <job_id> --format=JobID,State,ExitCode
```

Some clusters disable or delay accounting data. The status command should handle
missing `sacct` information gracefully.

### 16.4 State Mapping

Recommended rough mapping:

```text
PENDING       -> submitted, waiting for resources or dependencies
RUNNING       -> running
COMPLETED     -> succeeded from scheduler perspective
FAILED        -> failed
CANCELLED     -> cancelled
TIMEOUT       -> failed with timeout reason
OUT_OF_MEMORY -> failed with resource reason
NODE_FAIL     -> failed with infrastructure reason
DEPENDENCY    -> blocked by failed dependency
```

Scheduler state does not replace `loom` stage status. It supplements it.

### 16.5 Status Command Behavior

A scheduler-aware command:

```bash
loom status RUN_URI --jobs
```

should show:

```text
stage
loom status
job ID
SLURM state
exit code
dependencies
log paths
```

The command should not import project stage code.

---

## 17. Cancellation

### 17.1 Cancel Submitted Jobs

Cancellation should use:

```bash
scancel <job_id>
```

The API should cancel jobs recorded in the submission manifest.

### 17.2 Cancellation Order

For afterok mode:

```text
cancel downstream pending jobs first when practical
cancel running jobs
record cancellation attempt results
mark run or stages cancelled where appropriate
```

SLURM handles cancellation by job ID, so order may not always matter. Recording
what happened does matter.

### 17.3 Partial Cancellation

Some `scancel` calls may fail.

Recommended behavior:

```text
record per-job cancellation result
surface partial failures
do not claim full cancellation if some jobs remain active
```

### 17.4 CLI

Implemented command:

```bash
loom cancel RUN_URI --jobs
```

The command targets the latest active submitted operation by default. Exact
submitted-operation selectors and cleanup policies are deferred.

---

## 18. Resume and Reuse

### 18.1 Resume Before Submission

Before submitting SLURM jobs, the normal planner should decide:

```text
RUN
REUSE
SKIP
BLOCKED
```

Only `RUN` stages should become SLURM jobs.

### 18.2 Reused Upstream Stages

If a stage is reused:

```text
do not submit a job
ensure artifact refs are available
allow downstream submitted jobs to start without a scheduler dependency on it
```

The dependency is semantic, not scheduler-based, because the reused result
already exists.

### 18.3 Failed Stage Resume

After a failed afterok submission, rerunning with resume should:

```text
reuse succeeded stages with matching fingerprints
rerun failed or incomplete stages as needed
resubmit downstream stages invalidated by rerun outputs
write a new submission manifest or submission attempt
preserve old job metadata
```

### 18.4 Old Submitted Jobs

If a run has old submitted jobs, a new submission should be careful.

Possible policies:

```text
fail if active old jobs exist
allow only with --force
cancel old jobs before resubmitting
open a new run directory
```

V0 should fail clearly when active old jobs are detected, unless the user
explicitly requests otherwise.

---

## 19. Failure Handling

### 19.1 Submission Failure

Submission failure examples:

```text
sbatch not found
sbatch exits non-zero
job ID cannot be parsed
script path cannot be written
invalid resource mapping
dependency job ID missing
```

The executor should raise or return a structured `SlurmSubmissionError`.

### 19.2 Job Failure

Job failure examples:

```text
stage Python exception
non-zero worker exit
timeout
out of memory
node failure
cancelled job
dependency never satisfied
```

The stage worker should write normal `loom` failure metadata when it starts and
reaches stage execution. Scheduler-level failures may need status inspection if
the worker never ran.

### 19.3 Worker Never Started

If SLURM reports failure before the worker starts:

```text
no stage RUNNING status may exist
no stage failure.json may exist
SLURM stderr may contain the only detail
```

Status inspection should synthesize a scheduler failure summary without
pretending the stage itself ran.

### 19.4 Dependency Failure

For downstream jobs blocked by failed dependencies:

```text
stage did not run
dependency job failed
stage should be reported as blocked or cancelled by dependency
```

Do not mark the downstream stage as a stage-code failure.

### 19.5 Failure Metadata

SLURM-specific failure metadata should include:

```text
job_id
raw_job_id
slurm_state
slurm_exit_code
dependency_job_ids
script_path
stdout_path
stderr_path
sbatch_command
sacct_snapshot
```

This metadata should be nested under executor metadata when written into generic
failure files.

---

## 20. Public API

### 20.1 Recommended Types

Recommended exports from `loom.pipeline.executors.slurm`:

```python
SlurmExecutor
SlurmMode
SlurmSubmission
SlurmJobRecord
SlurmResourceMapper
SlurmScriptBuilder
SlurmCommandRunner
SlurmSubmissionError
SlurmStatusError
```

The first implementation may keep helper classes internal until the public
surface is proven.

### 20.2 SlurmExecutor Interface

Recommended high-level interface:

```python
class SlurmExecutor:
    def submit(self, request: SlurmRunRequest) -> SlurmSubmission:
        ...
```

For compatibility with the generic executor protocol, per-stage synchronous
`execute` is not the main shape for afterok mode. SLURM submission is a
pipeline-level operation.

The generic execution design should therefore treat SLURM afterok as a submitted
executor or pipeline submission backend, not only as a synchronous stage
executor.

### 20.3 Single-Job API

Recommended:

```python
submission = slurm.submit_single_job(
    run_request,
    resources=resources,
    slurm_options=options,
)
```

This creates one script and submits it.

### 20.4 Afterok API

Recommended:

```python
submission = slurm.submit_afterok(
    run_request,
    plan=plan,
)
```

This creates one script per runnable stage and submits in dependency order.

### 20.5 Command Runner

Wrap SLURM commands behind a small interface:

```python
class SlurmCommandRunner:
    def sbatch(self, script: Path, *, dependency: str | None = None) -> SbatchResult:
        ...

    def squeue(self, job_ids: Sequence[str]) -> Sequence[SlurmQueueRecord]:
        ...

    def sacct(self, job_ids: Sequence[str]) -> Sequence[SlurmAccountingRecord]:
        ...

    def scancel(self, job_ids: Sequence[str]) -> Sequence[SlurmCancelResult]:
        ...
```

This makes tests independent of a real cluster.

---

## 21. CLI Integration

### 21.1 V6 Dry-Run Single Job

Implemented command:

```bash
loom run experiment.yaml \
  --run-uri file:///abs/project/runs/example \
  --executor slurm-single-job \
  --dry-run
```

The CLI prints or serializes:

```text
run URI
planning ID
manifest path
dry-run plan path
script path
wrapper stdout/stderr log paths
preflight warnings
```

The generated script calls `loom prepared-run continue --run-uri RUN_URI
--executor local`.

### 21.2 V6 Dry-Run Afterok DAG

Implemented command:

```bash
loom run experiment.yaml \
  --run-uri file:///abs/project/runs/example \
  --executor slurm-afterok \
  --dry-run
```

The CLI prints or serializes:

```text
number of planned jobs
number of logical afterok dependencies
manifest path
script directory and per-stage script paths
wrapper stdout/stderr log paths
generated command argv
preflight warnings
```

The generated scripts call `loom stage-job run --run-uri RUN_URI --stage STAGE
--executor local`. They do not call `loom stage run`.

### 21.3 V7 Submit Single Job

Implemented command:

```bash
loom run experiment.yaml \
  --run-uri file:///abs/project/runs/example \
  --executor slurm-single-job
```

The CLI prints or serializes:

```text
run directory
submission manifest path
job ID
stdout/stderr paths
status command hint
```

### 21.4 V7 Submit Afterok DAG

Implemented command:

```bash
loom run experiment.yaml \
  --run-uri file:///abs/project/runs/example \
  --executor slurm-afterok
```

The CLI prints or serializes:

```text
number of jobs submitted
root job IDs
final job IDs
submission manifest path
partial submission warning, if any
```

### 21.5 V7 Status

Implemented command:

```bash
loom status runs/example --jobs
```

It combines persisted run-store state with scheduler state from `sacct`,
`squeue`, and the manifest. Default `loom status RUN_URI` remains
persisted-state-only and does not query SLURM.

### 21.6 V7 Cancel

Implemented command:

```bash
loom cancel runs/example --jobs
```

It uses the latest active submitted-operation record and the submission manifest
to find job IDs, records per-job `scancel` results, and returns nonzero for
partial cancellation.

---

## 22. Error Model

### 22.1 SlurmError

Base error for SLURM executor failures.

### 22.2 SlurmUnavailableError

Raised when a required SLURM command is unavailable.

Example message:

```text
SLURM command "sbatch" was not found on PATH; cannot submit run "example"
```

### 22.3 SlurmSubmissionError

Raised when `sbatch` fails or returns unexpected output.

Should include:

```text
script path
command
stdout
stderr
exit code
stage name, if applicable
```

### 22.4 SlurmDependencyError

Raised when dependency construction fails.

Examples:

```text
upstream stage has no submitted job ID
plan contains BLOCKED stage selected for submission
dependency cycle appears in submitted graph
```

### 22.5 SlurmStatusError

Raised when status inspection fails unexpectedly.

Missing accounting data should usually be a warning or unknown status, not a
hard error.

### 22.6 Error Message Shape

Errors should include user-actionable paths.

Example:

```text
Failed to submit SLURM job for stage "train".
Command: sbatch --parsable /runs/example/slurm/scripts/stages/train.sh
stderr: Invalid account or account/partition combination specified
Script: /runs/example/slurm/scripts/stages/train.sh
```

---

## 23. Testing Strategy

### 23.1 Script Builder Tests

Test:

```text
single-job script generation
per-stage script generation
SBATCH directive ordering
resource mapping
script prelude insertion
path quoting
stdout/stderr directives
extra_sbatch flags
```

### 23.2 Resource Mapping Tests

Test:

```text
cpu entry to CPU scheduler option
memory entry to mem
gpu to gres
SLURM time to scheduler time option
explicit slurm overrides
invalid resource values
```

### 23.3 Job ID Parser Tests

Test:

```text
123456
123456;cluster
unexpected empty output
non-numeric output
sbatch warning plus job ID, if supported
```

### 23.4 Submission Flow Tests

Use a fake `SlurmCommandRunner`.

Test:

```text
single-job submission manifest
afterok topological submission
fan-in dependencies
fan-out dependencies
partial submission failure
dry-run no sbatch calls
```

### 23.5 Status Tests

Use fake `squeue` and `sacct` results.

Test:

```text
pending job
running job
completed job
failed job
cancelled job
timeout job
missing accounting data
dependency failure
```

### 23.6 Cancellation Tests

Test:

```text
cancel all jobs from manifest
partial cancel failure
missing job IDs
already completed jobs
manifest update after cancellation
```

### 23.7 Integration Tests

Without a real SLURM cluster:

```text
dry-run script generation for sample pipeline
fake sbatch submission for diamond DAG
fake failed stage state inspection
```

Real SLURM tests should be optional and skipped unless explicitly enabled.

---

## 24. Historical Live-Submission Implementation Sketch

The sketch below predates the v6 dry-run-first implementation plan and the v7
live-operation implementation. Treat it as historical planning context; the
implemented behavior is described in section 0 and section 21.

### 24.1 Phase 1: Data Types and Script Builder

Implement:

```text
SlurmMode
SlurmJobRecord
SlurmSubmission
SlurmOptions
SlurmScriptBuilder
SlurmResourceMapper
```

Keep these independent of a real cluster.

### 24.2 Phase 2: Command Runner

Implement:

```text
SlurmCommandRunner
sbatch wrapper
job ID parser
command error capture
dry-run path
```

Add tests with fake command output.

### 24.3 Phase 3: Single-Job Submission

Implement:

```text
single pipeline script generation
submission manifest
sbatch submission
CLI integration
basic status display from manifest
```

This is the simplest cluster path.

### 24.4 Phase 4: Afterok Submission

Implement:

```text
per-stage script generation
stage attempt preparation
dependency graph to afterok mapping
topological submission
partial submission handling
manifest updates
```

Use fake command tests before any real cluster testing.

### 24.5 Phase 5: Status and Cancel

Implement:

```text
squeue integration
sacct integration
status mapping
scancel integration
cancel command
partial cancellation reporting
```

### 24.6 Phase 6: Hardening

Add:

```text
better resume handling after partial submissions
submission attempt directories
cluster compatibility options
optional real-SLURM smoke tests
documentation examples
```

### 24.7 Deferred Phases

Defer:

```text
controller mode
job arrays
containers
automatic retries
remote stores
distributed locking
multi-node workflows
```

---

## 25. Summary

SLURM support should be a thin, inspectable submission layer over the normal
`loom` execution model.

The core contract is:

```text
planner decides which stages need work
SLURM executor generates dry-run scripts and manifests in v6
single-job mode plans one script that calls loom prepared-run continue
afterok mode plans one script per RUN stage that calls loom stage-job run
logical job keys and afterok dependencies are durable dry-run records
v7/later live submission can map logical job keys to scheduler job IDs
project code remains unaware of scheduler mechanics
```

The first implementation should prioritize durable scripts, clear manifests,
portable resource mapping, and conservative failure reporting. More dynamic
cluster behavior can come later once these basic submission modes are reliable.
