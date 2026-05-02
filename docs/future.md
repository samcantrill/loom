# Loom Missing Features / Future Functionality Backlog

## 1. Purpose

This document outlines the functionality that is not currently assumed to be implemented in `loom`, based on the feature set discussed so far. It is written as a planning document rather than a final implementation spec.

`loom` is treated here as the domain-agnostic core library for reproducible, configurable, artifact-based research pipelines. Domain-specific packages such as `rphys` should build on top of it.

The document separates missing functionality into:

```text
must-have infrastructure
important near-term features
useful later features
explicitly deferred or out-of-scope features
```

The goal is to identify what is missing without turning `loom` into a heavyweight workflow platform.

---

## 2. Assumptions

This backlog assumes `loom` is intended to provide:

```text
configuration composition
recursive importlib construction
named recipes
pipeline DAGs
stages
artifact references
artifact stores
run stores
stage status
fingerprints
resume logic
executors
sweeps
provenance
```

However, many of these may exist only as designs/specifications rather than implemented code.

This document is therefore organized as a feature checklist. Each feature includes:

```text
what it is
why it matters
suggested priority
implementation notes
```

---

## 3. Priority Levels

Suggested priority labels:

```text
P0
  Required for a useful first working version.

P1
  Important for serious research use, especially long-running pipelines.

P2
  Useful once the core model is stable.

P3
  Nice-to-have or advanced functionality.

Out of scope for now
  Should not be implemented until a concrete need appears.
```

---

## 4. Core Configuration Features

## 4.1 Recursive `_target_` importlib instantiation

Priority: P0

Status: Not assumed implemented.

Description:

Support recursive construction of Python objects from config blocks containing `_target_`.

Example:

```yaml
model:
  _target_: my_pkg.models.ModularModel
  backbone:
    _target_: my_pkg.models.Backbone
    channels: 64
  head:
    _target_: my_pkg.models.Head
```

Why it matters:

```text
enables full experimental flexibility
avoids universal factories
supports experiment-local packages
allows deeply nested object graphs
```

Implementation notes:

```text
support dotted and colon import paths
support nested lists and mappings
support `_args_` for positional args
support `_partial_` or explicit builder classes
provide path-aware errors
```

---

## 4.2 Named `_recipe_` expansion

Priority: P0

Status: Not assumed implemented.

Description:

Support high-level named recipes that expand into explicit lower-level config graphs.

Example:

```yaml
data:
  _recipe_: ubfc_physnet_128
  root: /data/ubfc
  cache_dir: /scratch/ubfc
```

Why it matters:

```text
keeps authored configs shallow
hides repetitive dataset/config complexity
provides typed public knobs
avoids unreadable YAML graphs
```

Implementation notes:

```text
Recipe protocol with expand()
RecipeCatalog
strict recipe field validation
recipe provenance
optional entry-point discovery later
```

---

## 4.3 Overlay files

Priority: P0

Status: Not assumed implemented.

Description:

Support layering one or more overlay config files over a base experiment config.

Example:

```bash
loom run experiment.yaml --overlay overlays/small_model.yaml
```

Why it matters:

```text
simple ablations
named experiment variants
cleaner than duplicating whole experiment files
```

Implementation notes:

```text
use deterministic merge policy
mappings deep-merge
scalars replace
lists replace by default
avoid advanced list patching initially
```

---

## 4.4 CLI dot-path overrides

Priority: P0

Status: Not assumed implemented.

Description:

Allow command-line overrides into config values.

Example:

```bash
loom run experiment.yaml model.hidden_channels=32 optimizer.lr=1e-4
```

Why it matters:

```text
quick ablations
sweep generation
debugging
reproducible command-line changes
```

Implementation notes:

```text
parse int/float/bool/null/list/string values
apply after overlays
record in provenance
save overrides.yaml
```

---

## 4.5 Resolved config export

Priority: P0

Status: Not assumed implemented.

Description:

Write the final composed, expanded, resolved config for every run.

Required output:

```text
config/resolved.yaml
config/overlays.yaml
config/cli_overrides.yaml
config/provenance.json
```

Why it matters:

```text
reproducibility
debugging
sweep comparison
artifact lineage
```

Implementation notes:

```text
resolve interpolation before writing
redact secrets
include recipe expansion records
include source config paths
```

---

## 4.6 Secret redaction

Priority: P1

Status: Not assumed implemented.

Description:

Prevent secrets from being written into resolved configs or logs.

Why it matters:

```text
safe config persistence
cloud/object-store credentials
shared run directories
```

Implementation notes:

```text
redact keys matching token/password/secret/api_key/credential
support explicit secret markers later
prefer environment variable references
```

---

## 4.7 Config schema versioning

Priority: P1

Status: Not assumed implemented.

Description:

Support `schema_version` in config files and fail clearly on unsupported versions.

Why it matters:

```text
future migration safety
old experiment reproducibility
clear breaking-change handling
```

Implementation notes:

```text
v0 only needs version detection and error messages
migrations can be deferred
```

---

## 5. Core Artifact and Record Features

## 5.1 Generic `ResourceRef`

Priority: P0

Status: Not assumed implemented.

Description:

A generic serializable pointer to stored resources.

Example fields:

```text
uri
resource_type
codec_key
schema_version
checksum
metadata
```

Why it matters:

```text
manifests need lightweight references
resources should be lazy-loaded
core must remain domain-agnostic
```

---

## 5.2 Generic `Record`

Priority: P0

Status: Not assumed implemented.

Description:

A generic record containing resources, metadata, annotations, and provenance.

Example:

```python
Record(
    record_id="...",
    resources={"video": ResourceRef(...)},
    metadata={"subject_id": "s01"},
)
```

Why it matters:

```text
dataset-independent indexing
domain packages can attach arbitrary resources
supports filtering and manifest materialization
```

---

## 5.3 Generic `Manifest`

Priority: P0

Status: Not assumed implemented.

Description:

A persisted/indexable collection of records.

Why it matters:

```text
reproducible datasets
lazy scans can be materialized
pipeline stages can pass manifest artifacts
```

Implementation notes:

```text
initial storage can be JSONL or simple directory
Parquet support can be domain/package-specific or later core optional
```

---

## 5.4 `ManifestView` and simple filters

Priority: P1

Status: Not assumed implemented.

Description:

Lazy filtered view over a manifest.

Useful filters:

```text
HasResource
MetadataEquals
MetadataIn
MetadataRegex
```

Why it matters:

```text
subset selection
experiment splits
lazy exploration
training index construction
```

Implementation notes:

```text
keep generic
domain-specific filters should live outside loom
```

---

## 5.5 Generic `ArtifactRef`

Priority: P0

Status: Not assumed implemented.

Description:

A reference to a pipeline output.

Example fields:

```text
uri
artifact_type
schema_version
checksum
fingerprint
producer_stage
metadata
```

Why it matters:

```text
stage isolation
pipeline resume
artifact passing
SLURM/container boundaries
lineage tracking
```

---

## 6. Pipeline DAG Features

## 6.1 `PipelineSpec`

Priority: P0

Status: Not assumed implemented.

Description:

Static representation of a pipeline DAG.

Should contain:

```text
pipeline name
stage specs
global config references
runtime defaults
```

Why it matters:

```text
single source of truth for execution graph
supports planning and validation
```

---

## 6.2 `StageSpec`

Priority: P0

Status: Not assumed implemented.

Description:

Static representation of one pipeline stage.

Suggested fields:

```text
name
target
inputs
outputs
config
resources
runtime
retry
condition
```

Why it matters:

```text
stage construction
artifact binding
executor planning
resource scheduling
```

---

## 6.3 DAG validation

Priority: P0

Status: Not assumed implemented.

Validation should check:

```text
stage names are unique
input references point to existing upstream outputs
no cycles
outputs are uniquely named within each stage
stage targets are syntactically valid
required stages exist
```

Why it matters:

```text
fail before expensive execution
safe planning
clear errors for config mistakes
```

---

## 6.4 Topological execution planning

Priority: P0

Status: Not assumed implemented.

Description:

Compute execution order and input bindings from the DAG.

Why it matters:

```text
local runner
SLURM dependency generation
resume planning
pipeline visualization
```

---

## 6.5 Branching/forked pipelines

Priority: P0

Status: Not assumed implemented.

Description:

Support one stage output being consumed by multiple downstream stages.

Example:

```text
train.best_checkpoint
  -> evaluate_a
  -> evaluate_b
  -> evaluate_c
```

Why it matters:

```text
multiple evaluation protocols
multiple datasets
multiple analyses from same artifact
```

This should fall naturally out of DAG support.

---

## 7. Stage Execution Features

## 7.1 Stage protocol

Priority: P0

Status: Not assumed implemented.

Required interface:

```python
class Stage(Protocol):
    def run(self, context, inputs) -> dict[str, ArtifactRef]:
        ...
```

Why it matters:

```text
domain packages can provide arbitrary stages
loom remains domain-agnostic
importlib targets can be checked structurally
```

---

## 7.2 Stage context

Priority: P0

Status: Not assumed implemented.

Stage context should provide:

```text
run_dir
stage_dir
resolved_config
stage_config
artifact_store
run_store
logger
provenance
seed
runtime info
```

Why it matters:

```text
consistent stage APIs
no global state
stage isolation
```

---

## 7.3 Stage command interface

Priority: P0

Status: Not assumed implemented.

Command:

```bash
loom stage run --run-dir RUN_DIR --stage STAGE_NAME --resume
```

Why it matters:

```text
subprocess execution
SLURM execution
container execution
debugging individual stages
resuming specific stages
```

---

## 7.4 Stage output validation

Priority: P1

Status: Not assumed implemented.

Description:

Validate that stage returned all declared outputs and that artifact refs match expected types.

Why it matters:

```text
prevents silent partial stages
improves resume correctness
catches stage bugs early
```

---

## 7.5 Arbitrary stage internals

Priority: P0 design requirement

Status: Not a specific feature, but a required policy.

Description:

A stage should be arbitrary Python. It may internally run training, call external tools, launch subprocesses, or process many records.

Policy:

```text
loom schedules stages
stage implementations own their internal work
```

Do not initially build nested task scheduling inside stages.

---

## 8. Run Store and State Features

## 8.1 Run directory creation

Priority: P0

Status: Not assumed implemented.

Required layout:

```text
runs/<name>/<timestamp_or_run_id>/
  config/
  stages/
  artifacts.json
  status.json
```

Why it matters:

```text
standardized artifacts
debugging
resume
inspection
```

---

## 8.2 Stage status files

Priority: P0

Status: Not assumed implemented.

Each stage should have:

```text
status.json
inputs.json
outputs.json
fingerprint.json
logs/
```

Stage states:

```text
PENDING
RUNNING
SUCCEEDED
FAILED
SKIPPED
STALE
CANCELLED
```

Why it matters:

```text
resume
debugging
SLURM job isolation
failure handling
```

---

## 8.3 Run locking

Priority: P1

Status: Not assumed implemented.

Description:

Prevent multiple processes from modifying the same run directory simultaneously.

Why it matters:

```text
avoids corrupted status files
avoids duplicated stage execution
important for resume and controller modes
```

Implementation notes:

```text
simple lock file initially
stale lock detection
force-unlock command
```

---

## 8.4 Atomic stage writes

Priority: P0

Status: Not assumed implemented.

Pattern:

```text
write temporary output
validate output
move to final path
write outputs.json
write fingerprint.json
mark SUCCEEDED
```

Why it matters:

```text
safe interruption handling
resume correctness
prevents partial artifacts being treated as valid
```

---

## 8.5 Artifact index

Priority: P0

Status: Not assumed implemented.

A run-level `artifacts.json` should map logical names to artifact refs.

Example:

```json
{
  "train.best_checkpoint": "...",
  "evaluate.metrics": "..."
}
```

Why it matters:

```text
downstream artifact lookup
inspection CLI
pipeline branching
analysis stages
```

---

## 9. Fingerprint and Resume Features

## 9.1 Stage fingerprints

Priority: P0

Status: Not assumed implemented.

A stage fingerprint should include:

```text
stage target
stage config
input artifact checksums/fingerprints
relevant resolved config subtree
code version
runtime/container metadata when available
```

Why it matters:

```text
cache invalidation
resume correctness
skip/rerun decisions
```

---

## 9.2 Resume entire pipeline

Priority: P0

Status: Not assumed implemented.

Command:

```bash
loom run experiment.yaml --resume
```

Behavior:

```text
skip valid succeeded stages
rerun failed/incomplete/stale stages
rerun downstream stages if upstream artifacts changed
```

Why it matters:

```text
long-running jobs fail
preprocessing/training may take hours or days
users need safe restart
```

---

## 9.3 Resume from any stage

Priority: P1

Status: Not assumed implemented.

Commands:

```bash
loom run experiment.yaml --from-stage train
loom run experiment.yaml --only-stage preprocess
loom run experiment.yaml --force-stage train
loom run experiment.yaml --skip-stage analyze
```

Why it matters:

```text
debugging
partial reruns
expensive pipeline control
workflow iteration
```

---

## 9.4 Downstream invalidation

Priority: P1

Status: Not assumed implemented.

Description:

If an upstream stage output changes, downstream stages should be marked stale.

Why it matters:

```text
prevents using outputs generated from old inputs
keeps artifact lineage correct
```

---

## 9.5 Separate pipeline resume and internal stage resume

Priority: P0 design requirement

Status: Not a specific implementation, but must be documented.

Example:

```text
loom pipeline resume:
  skip/rerun stages

training-stage resume:
  resume from last checkpoint inside train stage
```

Loom should not implement domain-specific checkpoint loading. It should allow stages to implement their own internal resume behavior.

---

## 10. Executor Features

## 10.1 Local executor

Priority: P0

Status: Not assumed implemented.

Description:

Runs stages in the current process.

Why it matters:

```text
unit tests
local development
small pipelines
CI smoke tests
```

---

## 10.2 Subprocess executor

Priority: P0

Status: Not assumed implemented.

Description:

Runs stages through `loom stage run` as subprocesses.

Why it matters:

```text
stage isolation
closer to SLURM/container behavior
independent logs
failure isolation
```

---

## 10.3 Whole-pipeline monolithic execution

Priority: P1

Status: Not assumed implemented.

Description:

Run an entire pipeline inside one process, container, or SLURM job.

Why it matters:

```text
simple reproduction
CI
small experiments
single allocation workflows
one-container execution
```

Modes:

```text
local-monolithic
subprocess-monolithic
slurm-single-job
container-single-job
```

---

## 10.4 Per-stage execution

Priority: P1

Status: Not assumed implemented.

Description:

Each stage runs as an independent job/process/container.

Why it matters:

```text
stage-specific resources
CPU preprocessing then GPU training
better retries
stage isolation
large HPC workflows
```

---

## 10.5 SLURM afterok executor

Priority: P1

Status: Not assumed implemented.

Description:

Submit one job per stage and use SLURM dependencies such as `afterok`.

Why it matters:

```text
scheduler-native dependency handling
no long-running controller
survives logout
simple HPC integration
```

Implementation notes:

```text
generate one script per stage
submit with sbatch --parsable
chain dependencies from DAG
write submission manifest
```

---

## 10.6 SLURM single-job mode

Priority: P1

Status: Not assumed implemented.

Description:

Submit one SLURM job that runs the entire pipeline.

Why it matters:

```text
simple cluster execution
one allocation for all stages
useful for small pipelines or homogeneous resources
```

---

## 10.7 SLURM controller mode

Priority: P2

Status: Not assumed implemented.

Description:

A Python controller submits ready stages, polls status, and submits downstream stages dynamically.

Why it matters:

```text
custom retry logic
more dynamic scheduling
avoids large dependency chains
can inspect artifacts before deciding downstream submission
```

Trade-off:

```text
controller must keep running
controller failure must be recoverable
polling logic adds complexity
```

Recommended after afterok mode is stable.

---

## 10.8 Docker executor

Priority: P2

Status: Not assumed implemented.

Description:

Run stages or whole pipelines inside Docker containers.

Why it matters:

```text
local reproducibility
deployment testing
environment isolation
```

---

## 10.9 Apptainer executor

Priority: P2

Status: Not assumed implemented.

Description:

Run stages or whole pipelines inside Apptainer/Singularity containers.

Why it matters:

```text
HPC compatibility
reproducible cluster execution
legacy environment isolation
```

---

## 10.10 Runtime and resource profiles

Priority: P1

Status: Not assumed implemented.

Description:

Allow per-stage resource/runtime declarations.

Example:

```yaml
resources:
  cpu: 16
  memory_gb: 64
  gpu: 1
  walltime: "08:00:00"
  slurm:
    partition: gpu
```

Why it matters:

```text
SLURM submission
resource planning
mixed CPU/GPU pipelines
container selection
```

---

## 11. Planning and Inspection Features

## 11.1 Dry-run / plan command

Priority: P1

Status: Not assumed implemented.

Command:

```bash
loom plan experiment.yaml --resume
```

Expected output:

```text
index       SKIP   fingerprint match
format      RUN    missing output
train       RUN    upstream changed
evaluate    RUN    upstream train changed
```

Why it matters:

```text
trust
cost avoidance
debugging
resume transparency
```

---

## 11.2 Status command

Priority: P1

Status: Not assumed implemented.

Command:

```bash
loom status RUN_DIR
```

Should show:

```text
stage statuses
failed stages
artifact counts
start/end times
executor information
```

---

## 11.3 Logs command

Priority: P1

Status: Not assumed implemented.

Command:

```bash
loom logs RUN_DIR train
```

Why it matters:

```text
debugging local and SLURM stages
reduces manual path hunting
```

---

## 11.4 Artifact query commands

Priority: P1

Status: Not assumed implemented.

Commands:

```bash
loom artifacts list RUN_DIR
loom artifacts show RUN_DIR train.best_checkpoint
loom artifacts path RUN_DIR evaluate.metrics
```

Why it matters:

```text
inspection
manual analysis
stage debugging
artifact reuse
```

---

## 11.5 Graph rendering

Priority: P3

Status: Not assumed implemented.

Command:

```bash
loom graph experiment.yaml --format dot
```

Why it matters:

```text
documentation
complex DAG debugging
visual inspection
```

Not essential early.

---

## 12. Sweep Features

## 12.1 Grid sweeps

Priority: P1

Status: Not assumed implemented.

Description:

Expand a base experiment into multiple trial configs using axes.

Example:

```yaml
axes:
  model.hidden_channels: [32, 64, 96]
  optimizer.lr: [1e-4, 3e-4]
  run.seed: [1, 2, 3]
```

Why it matters:

```text
ablation studies
hyperparameter exploration
repeatable multi-run experiments
```

---

## 12.2 Sweep directory structure

Priority: P1

Status: Not assumed implemented.

Recommended layout:

```text
sweeps/<sweep_name>/
  sweep.yaml
  trials.csv
  trial_0001/
  trial_0002/
```

Why it matters:

```text
trial organization
status aggregation
result collection
```

---

## 12.3 Sweep status and collection

Priority: P2

Status: Not assumed implemented.

Commands:

```bash
loom sweep status SWEEP_DIR
loom sweep collect SWEEP_DIR --artifact metrics
```

Why it matters:

```text
summarize many runs
collect metrics
compare ablations
```

---

## 12.4 Random/Bayesian sweeps

Priority: P3

Status: Not assumed implemented.

Recommendation:

Do not implement early. Start with grid/list sweeps. More advanced search strategies can be external.

---

## 13. Reliability Features

## 13.1 Retry policy

Priority: P2

Status: Not assumed implemented.

Example:

```yaml
retry:
  max_attempts: 2
```

Why it matters:

```text
transient filesystem failures
cluster preemption
occasional executor failure
```

Keep simple initially.

---

## 13.2 Timeout policy

Priority: P2

Status: Not assumed implemented.

Description:

Allow stages to declare timeouts.

Why it matters:

```text
hung jobs
cluster scheduling limits
automated cleanup
```

---

## 13.3 Failure recovery metadata

Priority: P1

Status: Not assumed implemented.

Failed stage status should include:

```text
exception type
message
traceback path
executor
exit code
log paths
failed_at timestamp
```

Why it matters:

```text
debugging
controller recovery
postmortem reports
```

---

## 13.4 Temporary file cleanup

Priority: P2

Status: Not assumed implemented.

Command:

```bash
loom clean RUN_DIR --failed-temp
```

Why it matters:

```text
failed atomic writes leave temp directories
large artifacts consume disk
```

---

## 13.5 Garbage collection

Priority: P3

Status: Not assumed implemented.

Command:

```bash
loom gc runs/ --older-than 30d
```

Why it matters:

```text
large experiment directories
cluster scratch cleanup
```

Not essential early.

---

## 14. Conditional and Dynamic Behavior

## 14.1 Simple conditional stages

Priority: P2

Status: Not assumed implemented.

Example:

```yaml
- name: analyze
  when: analysis.enabled
```

Why it matters:

```text
optional analysis
optional formatting
optional evaluation branches
```

Implementation notes:

```text
support simple boolean config path only
avoid arbitrary expression language
```

---

## 14.2 Dynamic DAG mutation

Priority: Out of scope for now

Status: Not implemented.

Description:

Stages generate new stages at runtime.

Recommendation:

Defer. It complicates planning, SLURM submission, resume, and provenance. Use explicit DAGs first.

---

## 14.3 Stage-internal subtask graphs

Priority: Out of scope for now

Status: Not implemented.

Description:

Nested task scheduling within one stage.

Recommendation:

Defer. A stage may run arbitrary internal code, but loom should not initially schedule subtasks inside stages.

---

## 15. Environment and Provenance Features

## 15.1 Environment capture

Priority: P1

Status: Not assumed implemented.

Capture:

```text
python version
platform
hostname
command
selected environment variables
package versions
git commit
git dirty state
container image/digest
SLURM job ID if applicable
```

Why it matters:

```text
reproducibility
debugging
paper artifacts
run comparison
```

---

## 15.2 Code provenance helpers

Priority: P1

Status: Not assumed implemented.

Helpers to collect:

```text
git commit
git branch
git dirty state
package version map
```

Implementation notes:

```text
keep failures non-fatal
not all code will be in git
```

---

## 15.3 Run export/import

Priority: P3

Status: Not assumed implemented.

Commands:

```bash
loom export RUN_DIR run.tar.zst
loom inspect run.tar.zst
```

Why it matters:

```text
sharing completed runs
archiving
reviewing artifacts elsewhere
```

Not essential early.

---

## 16. Artifact Store Features

## 16.1 Local artifact store

Priority: P0

Status: Not assumed implemented.

Description:

Filesystem-backed store for artifacts.

Why it matters:

```text
v0 execution
local runs
SLURM shared filesystem runs
```

---

## 16.2 Artifact type validation

Priority: P1

Status: Not assumed implemented.

Description:

Ensure loaded artifact type matches expected type.

Why it matters:

```text
prevents stage miswiring
clear downstream errors
```

---

## 16.3 Checksum validation

Priority: P1

Status: Not assumed implemented.

Description:

Optionally verify artifact checksums before loading or skipping stages.

Why it matters:

```text
corruption detection
resume safety
reproducibility
```

---

## 16.4 Remote artifact stores

Priority: P3

Status: Not implemented.

Examples:

```text
S3ArtifactStore
GCSArtifactStore
MLflowArtifactStore
```

Recommendation:

Defer until local filesystem behavior is stable.

---

## 17. CLI Features

## 17.1 Core commands

Priority: P0/P1 depending on command

Missing commands likely include:

```bash
loom run EXPERIMENT
loom stage run --run-dir RUN_DIR --stage STAGE
loom plan EXPERIMENT
loom status RUN_DIR
loom logs RUN_DIR STAGE
loom artifacts list RUN_DIR
loom sweep SWEEP_FILE
loom submit EXPERIMENT --executor slurm
```

Why it matters:

```text
users need operational access without writing Python
SLURM stages need command-line entry points
```

---

## 17.2 Python API parity

Priority: P0

Status: Not assumed implemented.

Every CLI action should be backed by a Python API.

Example:

```python
from loom.pipeline import PipelineRunner
from loom.config import compose_experiment

cfg = compose_experiment("experiment.yaml")
PipelineRunner().run(cfg)
```

Why it matters:

```text
notebook/programmatic control
unit tests
integration with external tools
```

---

## 18. Testing Infrastructure

## 18.1 Dummy stages

Priority: P0

Status: Not assumed implemented.

Need dummy stages for tests:

```text
stage that writes artifact
stage that fails
stage that sleeps
stage that reads upstream artifact
stage that returns missing output
```

Why it matters:

```text
pipeline tests without domain packages
```

---

## 18.2 Synthetic pipelines

Priority: P0

Status: Not assumed implemented.

Test pipeline shapes:

```text
linear DAG
branching DAG
diamond DAG
cycle error
missing input error
resume skip
forced rerun
failed stage resume
```

---

## 18.3 Executor tests

Priority: P1

Status: Not assumed implemented.

Test:

```text
local executor
subprocess executor
SLURM script generation without submitting
SLURM dependency graph generation
```

---

## 19. Features to Explicitly Avoid Initially

Avoid building these too early:

```text
general-purpose distributed task scheduler
web dashboard
database-backed orchestration service
Airflow/Prefect/Dagster clone
runtime DAG mutation
complex expression language
advanced config inheritance system
advanced list patching
automatic cloud execution abstraction
built-in Bayesian optimization
domain-specific data/model logic
```

Reason:

```text
these features add large maintenance burden
many can be integrated externally later
loom should remain a small reliable pipeline kernel
```

---

## 20. Recommended Implementation Roadmap

## Phase 1: Minimal local pipeline kernel

Priority: P0

Implement:

```text
ResourceRef
Record
ArtifactRef
PipelineSpec
StageSpec
Stage protocol
StageContext
LocalArtifactStore
RunStore
LocalExecutor
basic runner
resolved config export
recursive _target_ instantiation
```

Goal:

```text
run a simple linear pipeline locally with artifact passing
```

---

## Phase 2: Resume-safe execution

Priority: P0

Implement:

```text
stage status files
fingerprints
atomic writes
resume
force/only/from-stage selectors
artifact index
basic logs
```

Goal:

```text
interrupt and safely resume local pipelines
```

---

## Phase 3: Config usability

Priority: P0/P1

Implement:

```text
recipes
overlays
CLI overrides
secret redaction
path-aware config errors
recipe provenance
```

Goal:

```text
usable experiment configs without unreadable YAML graphs
```

---

## Phase 4: Operational CLI

Priority: P1

Implement:

```text
loom plan
loom status
loom logs
loom artifacts list/show/path
loom stage run
```

Goal:

```text
operational debugging and inspection
```

---

## Phase 5: SLURM support

Priority: P1

Implement:

```text
SubprocessExecutor
SlurmAfterokExecutor
SlurmSingleJobExecutor
resource specs
submission manifest
script generation
```

Goal:

```text
run each stage as a separate SLURM job or entire pipeline as one SLURM job
```

---

## Phase 6: Sweeps

Priority: P1/P2

Implement:

```text
grid sweep expansion
trial directories
sweep status
metric collection
SLURM sweep submission integration
```

Goal:

```text
repeatable ablations and multi-run experiments
```

---

## Phase 7: Containers and advanced execution

Priority: P2

Implement:

```text
DockerExecutor
ApptainerExecutor
stage-level runtime profiles
SLURM + Apptainer scripts
```

Goal:

```text
per-stage isolated environments
```

---

## Phase 8: Hardening and convenience

Priority: P2/P3

Implement:

```text
retry/timeouts
conditional stages
cleanup
graph rendering
run export/import
remote artifact stores
SLURM controller mode
```

Goal:

```text
more robust long-term research operations
```

---

## 21. Most Important Missing Features

The highest-value missing features to prioritize are:

```text
1. Resume-safe stage execution.
2. Run directory and stage status model.
3. ArtifactRef passing and artifact index.
4. Stage fingerprints and downstream invalidation.
5. Stage command interface.
6. Dry-run/planning command.
7. Single-job and per-stage execution modes.
8. SLURM afterok executor.
9. Named recipes for config usability.
10. Artifact/status/log inspection CLI.
```

These are not over the top. They are the minimum needed for a serious research pipeline library.

---

## 22. Final Summary

`loom` should not aim to be a full workflow platform. It should be a compact, reliable kernel for artifact-based research pipelines.

The important missing functionality is mostly operational rather than domain-specific:

```text
safe resume
stage status
artifact indexing
execution planning
stage isolation
SLURM submission
single-job and per-stage execution
sweeps
inspection commands
resource/runtime profiles
```

The central abstraction should remain:

```text
Stage consumes ArtifactRefs.
Stage produces ArtifactRefs.
Executor decides where and how the stage runs.
RunStore records what happened.
ArtifactStore records what was produced.
```

Everything else should support that abstraction without making `loom` a domain-specific or heavyweight orchestration framework.
