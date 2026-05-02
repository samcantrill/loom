# loom.pipeline.runtime and resources Specification

## Purpose

`loom.pipeline.runtime` and `loom.pipeline.resources` define the runtime control
surface for executing a pipeline without mixing operational choices into the
pipeline's semantic definition.

The pipeline spec describes what the work is. Runtime options describe how this
particular invocation should run.

Resource requests describe what a stage says it needs. Executors decide how
much of that request they can enforce.

## Scope

This component owns:

```text
stage resource request data structures
runtime run options
resume options
execution options
runtime profiles
normalization of option values
validation of scheduler-neutral resource fields
translation-ready metadata for executors
```

This component does not own:

```text
actual stage execution
SLURM submission scripts
container command construction
artifact storage
resume decision algorithms
pipeline graph construction
CLI argument parsing
```

CLI and config layers may construct these objects, but the runtime/resources
layer defines their canonical meaning.

## Design Goals

The design should:

```text
keep pipeline specs portable across executors
avoid embedding SLURM-specific fields into core stage definitions
provide enough resource information for local, SLURM, and future container execution
separate semantic inputs from operational invocation options
make dry-run and preflight paths use the same normalized options as execution
```

## Resource Requests

`ResourceRequest` is the scheduler-neutral declaration of resources requested
by a stage.

Recommended shape:

```python
@dataclass(frozen=True)
class ResourceRequest:
    cpus: int | None = None
    memory_mb: int | None = None
    gpus: int | None = None
    wall_time_seconds: int | None = None
    custom: Mapping[str, object] = field(default_factory=dict)
```

Field names should remain generic.

Avoid names such as:

```text
partition
account
qos
gres
sbatch_args
```

Those belong in executor-specific profiles or custom metadata interpreted by a
specific executor.

## Resource Field Semantics

`cpus`:

```text
number of CPU cores or logical worker slots requested for the stage
positive integer when provided
```

`memory_mb`:

```text
total memory requested for the stage in megabytes
positive integer when provided
```

`gpus`:

```text
number of GPUs requested
zero or positive integer when provided
```

`wall_time_seconds`:

```text
expected or requested maximum runtime for the stage
positive integer when provided
```

`custom`:

```text
structured extension metadata for executors or plugins
must be JSON-serializable
must not affect core fingerprinting unless explicitly included by policy
```

## Resource Defaults

Missing resource fields mean:

```text
no explicit request was made
```

They do not mean:

```text
one CPU
unlimited memory
zero memory
default queue
```

Executor adapters may choose defaults, but those defaults should be documented
by the executor and included in submission metadata when relevant.

## Runtime Options

`RunOptions` captures invocation-level choices for one run.

Recommended shape:

```python
@dataclass(frozen=True)
class RunOptions:
    run_id: str | None = None
    run_dir: Path | None = None
    executor: str | None = None
    dry_run: bool = False
    selected_stages: frozenset[str] | None = None
    tags: Mapping[str, str] = field(default_factory=dict)
    notes: str | None = None
    resume: ResumeOptions = field(default_factory=ResumeOptions)
    execution: ExecutionOptions = field(default_factory=ExecutionOptions)
```

The exact model can be adjusted to existing code, but runtime options should
stay separate from pipeline specs.

## Resume Options

`ResumeOptions` captures skip, force, and recovery behavior.

Recommended shape:

```python
@dataclass(frozen=True)
class ResumeOptions:
    enabled: bool = False
    force_stages: frozenset[str] = frozenset()
    from_stage: str | None = None
    reuse_successful: bool = True
    require_fingerprint_match: bool = True
```

Examples:

```text
resume=True
force={"train"}
from_stage="evaluate"
```

Resume options are interpreted by resume planning. They should not change the
pipeline graph itself.

## Execution Options

`ExecutionOptions` captures execution behavior that applies across stages.

Recommended shape:

```python
@dataclass(frozen=True)
class ExecutionOptions:
    max_parallel_stages: int | None = None
    fail_fast: bool = True
    capture_logs: bool = True
    environment: Mapping[str, str] = field(default_factory=dict)
    profile: str | None = None
```

Fields should be added only when multiple executors need the same concept.

Executor-specific options belong in profiles.

## Runtime Profiles

A runtime profile is a named collection of operational defaults.

Example:

```yaml
runtime_profiles:
  local:
    executor: local
    execution:
      max_parallel_stages: 2

  cluster:
    executor: slurm
    slurm:
      partition: compute
      account: project-a
```

Profiles are useful because the same pipeline may be run locally, on a shared
filesystem, or on a cluster.

Core runtime objects should preserve unknown profile sections for executor
adapters, but should validate core sections strictly.

## Configuration Boundary

Runtime options may come from:

```text
CLI flags
project config
runtime profile selection
environment defaults
programmatic API arguments
```

Precedence should be explicit and documented by the config/CLI layer.

The runtime/resources layer should receive already-merged options and validate
their shape.

## Fingerprint Boundary

Pipeline semantic fingerprints should not include invocation-only runtime
options by default.

Generally not semantic:

```text
run_dir
run_id
dry_run
max_parallel_stages
executor
SLURM account
log capture setting
```

Potentially semantic only by explicit policy:

```text
container image
environment variables
resource-controlled nondeterminism
executor-specific runtime configuration
```

The default should be conservative: operational choices are provenance facts,
not semantic inputs, unless a design explicitly marks them otherwise.

## Executor Mapping

Executors consume normalized runtime/resource objects.

Local executor:

```text
may ignore most resources
may use max_parallel_stages
records requested resources in provenance
```

Subprocess executor:

```text
may pass environment variables
may enforce timeout if configured
records command and exit code
```

SLURM executor:

```text
maps cpus to --cpus-per-task or equivalent
maps memory_mb to --mem
maps wall_time_seconds to --time
maps gpus through executor-specific policy
uses profiles for partition/account/qos
```

Container executors:

```text
map environment and mounts
may map resource fields when the container runtime supports them
record image identity and command
```

## Validation

Resource validation should check:

```text
numeric fields are integers
numeric fields are in accepted ranges
custom metadata is structured and serializable
unknown core fields are rejected
```

Runtime option validation should check:

```text
selected stages exist
force stages exist
from_stage exists
max_parallel_stages is positive when provided
executor name is known or plugin-resolvable
profile name is known when profile selection is used
```

Validation that requires filesystem access belongs in preflight.

## Serialization

Runtime and resource objects should serialize to plain dictionaries.

Example:

```json
{
  "executor": "slurm",
  "dry_run": false,
  "execution": {
    "max_parallel_stages": null,
    "fail_fast": true,
    "capture_logs": true
  },
  "resources": {
    "train": {
      "cpus": 8,
      "memory_mb": 32768,
      "gpus": 1,
      "wall_time_seconds": 7200
    }
  }
}
```

Persisted runtime records should describe what was requested and what executor
defaults were applied.

## Preflight Integration

Preflight should use runtime/resource objects to check:

```text
selected executor exists
required executor commands are available
resource fields can be mapped by the selected executor
profile-specific required fields are present
run directory and artifact paths are writable
```

Unsupported resource fields should usually be warnings unless execution would
definitely fail.

## Testing

Unit tests should cover:

```text
valid resource request construction
invalid negative resources
invalid zero values where not allowed
custom metadata serialization
runtime option defaults
resume option normalization
selected stage validation
force stage validation
profile merge behavior if implemented in this layer
executor mapping smoke tests in executor-specific packages
```

Tests should avoid requiring SLURM, Docker, or Apptainer.

## Implementation Plan

1. Define resource and runtime dataclasses.
2. Add validation helpers that do not touch the filesystem.
3. Wire config and CLI option parsing into the runtime objects.
4. Record normalized runtime options in run metadata.
5. Teach executor adapters to consume the shared objects.
6. Add preflight checks that use the same normalized objects.

## Deferred Work

Deferred runtime/resource features:

```text
rich accelerator descriptions
per-stage container images
executor-specific schema plugins
queue time estimates
adaptive resource retry policies
resource usage measurement
resource recommendation reports
```

These should be added after the basic local and SLURM mappings are stable.

