# loom.pipeline.runtime and resources Specification

## Purpose

`loom.pipeline.runtime` and `loom.pipeline.resources` define the runtime control
surface for executing a pipeline without mixing operational choices into the
pipeline's semantic definition.

The pipeline spec describes what the work is. Runtime options describe how this
particular invocation should run.

Resource requests describe what a stage says it needs. Executors decide how
much of that request they can enforce.

V11 queue managed pools use authority-owned resource limits and leases at
dispatch time, but they do not provision or mutate those limits. Queue config
reconciliation is read-only and is described in [queue.md](queue.md).

## Scope

Current alignment:

```text
StageSpec stores authored stage resources as frozen plain data and validates
them through ResourceRequest, with no executor-specific semantics and no
default fingerprint impact
ResourceRequest uses typed entries keyed by resource kind
the removed fixed fields are rejected instead of treated as aliases
the runtime package supports a local-only RuntimeRequest foundation for programmatic/runtime
vocabulary, not authored stage runtime selection
Python planning supports selector fields from_stage, only_stages,
force_stages, and skip_stages
RunOptions, ExecutionOptions, StageRuntimeOptions, and run/stage environment
request models are public Python invocation models
runtime profiles and deterministic base/profile/explicit merge helpers are
public Python invocation APIs
executor descriptors and capability validation are public Python metadata APIs
under the import-light runtime boundary
preflight, CLI/config mapping, runner handoff, persisted runtime metadata, and
executor-specific resource mapping are later runtime phases
```

The sections below describe the intended stable direction for the runtime and
resource surface. Implementations should not introduce the full option model
unless a later phase explicitly expands scope.

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

Current behavior:

```text
StageSpec stores resources as recursively immutable plain data
StageSpec.resource_request returns the typed ResourceRequest inspection view
unsupported executor, retry, timeout, scheduler, container, environment, and
remote-store fields are rejected instead of preserved as honored metadata
```

Current resource shape:

```python
@dataclass(frozen=True)
class ResourceEntry:
    kind: str
    amount: int | float
    unit: str | None = None
    attributes: Mapping[str, object] = field(default_factory=dict)

@dataclass(frozen=True)
class ResourceRequest:
    entries: Mapping[str, ResourceEntry] = field(default_factory=dict)
```

Built-in resource kinds remain generic.

Avoid names such as:

```text
partition
account
qos
gres
sbatch_args
```

Those belong in executor-specific profiles or adapter metadata interpreted by a
specific executor.

## Resource Field Semantics

`cpu`:

```text
number of CPU cores or logical worker slots requested for the stage
positive integer amount
unit omitted or count
attributes empty
```

`memory`:

```text
total memory requested for the stage
positive integer or finite positive numeric amount
unit must be one of B, KiB, MiB, GiB, TiB
attributes empty
```

`gpu`:

```text
number of GPUs requested
zero or positive integer amount
unit omitted or count
attributes empty
```

`wall_time_seconds`:

```text
expected or requested maximum runtime for the stage
deferred; rejected in v0 so callers do not assume timeout behavior is honored
```

Qualified resource kinds:

```text
future adapters or plugins may use qualified kinds such as slurm.gres
callers must provide a composed validator registry before validation
unregistered kinds fail validation
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

Current behavior:

```text
v0 has a local-only RuntimeRequest foundation with kind=LOCAL, resources, and
plain metadata
authored stage runtime/executor fields remain rejected
RunOptions is the canonical Python invocation-policy aggregate for run_uri,
executor, dry_run, profile name, tags, notes, selector/resume adapter inputs,
execution settings, exact stage runtime options, environment requests, and
adapter options
RunOptions can serialize to and from plain data and adapt to planning-owned
PlanSelectors and ResumeOptions without owning graph or resume semantics
RunRequest carries normalized RunOptions as its canonical invocation-policy
field while legacy run_uri, selectors, and resume fields normalize into options
when they do not conflict
StageExecutionRequest carries a typed ResolvedStageRuntimeOptions handoff for
executor-facing per-stage runtime data
```

Current public shape:

```python
@dataclass(frozen=True)
class RunOptions:
    run_uri: str | None = None
    executor: str | None = None
    dry_run: bool = False
    profile: str | None = None
    tags: Mapping[str, str] = field(default_factory=dict)
    notes: Sequence[str] = ()
    selectors: PlanSelectors = field(default_factory=PlanSelectors)
    resume: ResumeOptions = field(default_factory=ResumeOptions)
    execution: ExecutionOptions = field(default_factory=ExecutionOptions)
    stage_options: Mapping[str, StageRuntimeOptions] = field(default_factory=dict)
    environment: RunEnvironmentRequest = field(default_factory=RunEnvironmentRequest)
    adapter_options: Mapping[str, object] = field(default_factory=dict)
```

Runtime options stay separate from pipeline specs and are not wired into the
local runner's semantic fingerprints. Config, CLI, and Python API inputs
normalize into `RunOptions`; the runner passes resolved per-stage runtime data
to executors and writes safe run-level runtime metadata as `runtime.json`.

`runtime.json` is an observability record, not the executor handoff. It is
schema-versioned and stores safe summaries such as executor name, selected
profile, tags, notes, selector/resume summaries, resource entry summaries, and
adapter namespace names/counts. It does not persist environment variable names
or values, and it does not persist raw adapter payloads.

## Resume Options

`ResumeOptions` captures skip, force, and recovery behavior.

Recommended shape:

```python
@dataclass(frozen=True)
class ResumeOptions:
    enabled: bool = False
    force_stages: frozenset[str] = frozenset()
    from_stage: str | None = None
    only_stages: frozenset[str] = frozenset()
    skip_stages: frozenset[str] = frozenset()
    reuse_successful: bool = True
    require_fingerprint_match: bool = True
```

Examples:

```text
resume=True
force_stages={"train"}
from_stage="evaluate"
```

Resume options are interpreted by resume planning. They should not change the
pipeline graph itself.

## Execution Options

`ExecutionOptions` captures strict plain-data execution settings that can apply
at run or stage scope.

Current behavior:

```text
ExecutionOptions stores plain settings only
no retry, timeout, wall-time, subprocess, parallel scheduling, preflight policy,
or executor descriptor semantics are defined here
```

Current public shape:

```python
@dataclass(frozen=True)
class ExecutionOptions:
    settings: Mapping[str, object] = field(default_factory=dict)
```

Fields should be added only when multiple executors need the same concept.

Executor-specific options belong in profiles.

## Stage Runtime Options And Environment Requests

`StageRuntimeOptions` carries exact-stage runtime data:

```python
@dataclass(frozen=True)
class StageRuntimeOptions:
    resources: ResourceRequest = field(default_factory=ResourceRequest)
    execution: ExecutionOptions = field(default_factory=ExecutionOptions)
    environment: StageEnvironmentRequest = field(default_factory=StageEnvironmentRequest)
    adapter_options: Mapping[str, object] = field(default_factory=dict)
```

Stage option keys are exact stage identifiers. Runtime models validate basic
identifier shape and expose a helper that checks supplied known-stage sets, but
they do not implement profile merge, glob/tag/group matching, graph
reachability checks, preflight IDs/groups, config loading, CLI behavior, or
runner wiring. Executor capability validation is a separate runtime helper over
normalized `RunOptions`.

Run and stage environment request models carry future isolated-executor
environment additions and removals. They do not apply local process environment
changes. Safe metadata summaries record only counts and inheritance mode, never
environment variable names or values.

## Runtime Profiles

A runtime profile is a named collection of operational defaults.

Current behavior:

```text
RuntimeProfile stores strict sparse runtime defaults as immutable plain data
RuntimeProfileCollection owns named profile selection and deterministic
serialization
merge_run_options combines config-shaped base data, the selected profile, and
explicit invocation data into a normalized RunOptions
profile merge does not import config, CLI, diagnostics, execution runners,
executor descriptors, plugins, or optional backend packages
```

Example:

```yaml
runtime_profiles:
  local:
    executor: local
    execution:
      settings:
        max_parallel_stages: 2

  cluster:
    executor: slurm
    slurm:
      partition: compute
      account: project-a

  docker:
    executor: docker
    adapter_options:
      container:
        image:
          reference: python:3.12-slim
        environment:
          variables:
            LOOM_CONTAINER_EXAMPLE: docker-pipeline
      docker:
        network: none
```

Profiles are useful because the same pipeline may be run locally, on a shared
filesystem, or on a cluster.

Core runtime profile sections use the existing `RunOptions`,
`ExecutionOptions`, `StageRuntimeOptions`, resource, selector/resume, and
environment parsers. They validate strictly. Non-core top-level profile
sections are preserved as adapter namespace payloads and folded into
`RunOptions.adapter_options`; if a profile supplies the same namespace through
`adapter_options` and a non-core top-level section, profile parsing fails.

Merge precedence is deterministic:

```text
config-shaped base < selected runtime profile < explicit invocation options
```

Sparse mapping inputs preserve field absence. Typed `RunOptions` inputs are
fully supplied sources. Scalars and sequences replace lower-precedence values.
Mappings merge shallowly with no deletion syntax. Stage options merge only by
exact stage ID. Stage resource requests merge by `ResourceRequest.entries`
kind, replacing the whole `ResourceEntry` for a conflicting kind. Adapter
namespaces are opaque plain data; a higher-precedence namespace replaces the
whole lower-precedence payload.

Container executor profiles should keep generic image, mount, workdir,
environment, and resource intent under `adapter_options.container`. Docker
flags such as `network`, `platform`, `user`, `hostname`, and `remove` belong
under `adapter_options.docker`. Semantic pipeline stage specs should not gain
Docker-specific fields.

`merge_run_options` can run the existing known-stage validation helper after
merge when callers supply canonical stage IDs. It does not implement glob,
tag, group, graph reachability, preflight, config loader, CLI, local
environment application, runner handoff, or persisted `runtime.json` behavior.

## Executor Descriptors And Capability Validation

Executor descriptors are scheduler-neutral metadata. They describe what a named
executor claims, ignores, or rejects without importing or constructing concrete
executor implementations.

Current behavior:

```text
ExecutorDescriptor records a stripped non-empty executor name
ResourceCapability records support level, enforcement expectation, severity,
and plain details for one resource kind
ExecutorDescriptorRegistry is immutable, explicit, serializes deterministically,
and rejects duplicate stripped executor names
DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY contains only the metadata-only local
descriptor
resolve_executor_descriptor resolves None to local for validation helpers
validate_executor_capabilities returns plain capability diagnostics and does
not import diagnostics or preflight models
```

The built-in `local` descriptor claims `cpu`, `memory`, and `gpu` as ignored,
not enforced, warning-level resource capabilities. It claims no adapter
namespaces. This describes the current local behavior without changing local
execution, scheduling, or resource enforcement.

Capability validation operates on already parsed `RunOptions` and
`ResourceRequest` objects:

```text
unknown selected executors emit executor.unknown error diagnostics
registered resource entries are checked against the selected descriptor
omitted resource capabilities use the descriptor fallback, unsupported/error by
default
unregistered resource kinds remain resource schema errors before capability
validation
run-level and stage-level adapter option namespaces are checked only by
ownership
unclaimed adapter namespaces emit adapter_namespace.unclaimed warnings
adapter payload values are not inspected or schema-validated
```

Capability diagnostics are not preflight results. They carry runtime-local
codes such as `executor.unknown`, `resource.ignored`, `resource.unsupported`,
and `adapter_namespace.unclaimed`. Diagnostics/preflight maps those records
into stable check IDs and strict-mode behavior without moving descriptor logic
into this layer.

## Configuration Boundary

Runtime options may come from:

```text
CLI flags
project config
runtime profile selection
environment defaults
programmatic API arguments
```

The runtime/resources layer defines the base/profile/explicit merge contract.
The runtime config adapter extracts optional top-level `runtime` and
`runtime_profiles` sections from a resolved config mapping and delegates to the
same merge helper. CLI layers build sparse explicit runtime dictionaries for
flags such as `--profile`, `--executor`, `--run-uri`, `--dry-run`, selector
flags, `--resume`, repeated `--tag KEY=VALUE`, and repeated `--note TEXT`.
These adapters must not duplicate runtime field semantics.

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
maps CPU entries to the scheduler CPU-count flag or equivalent
maps memory entries to --mem
maps wall_time_seconds to --time
maps gpu entries through executor-specific policy
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
entry kinds use the lowercase dotted identifier syntax
entry mapping keys match each entry kind
amounts and units satisfy the validator for each registered kind
attributes are structured and serializable
unknown or unregistered resource kinds are rejected
```

Runtime option validation should check:

```text
selected stages exist
force stages exist
from_stage exists
max_parallel_stages is positive when provided
profile name is known when profile selection is used
```

Capability validation should check:

```text
selected executor is known to the supplied descriptor registry
requested registered resource kinds are supported, advisory, ignored, or
unsupported according to the selected descriptor
unclaimed adapter namespaces are reported without inspecting payloads
```

Validation that requires filesystem access belongs in preflight.

## Serialization

Runtime and resource objects should serialize to plain dictionaries.

Current foundation examples:

```json
{
  "schema_version": 2,
  "entries": {
    "cpu": {
      "kind": "cpu",
      "amount": 8,
      "unit": "count",
      "attributes": {}
    },
    "memory": {
      "kind": "memory",
      "amount": 32,
      "unit": "GiB",
      "attributes": {}
    },
    "gpu": {
      "kind": "gpu",
      "amount": 1,
      "unit": "count",
      "attributes": {}
    }
  }
}
```

```json
{
  "schema_version": 1,
  "kind": "LOCAL",
  "resources": {
    "schema_version": 2,
    "entries": {}
  },
  "metadata": {}
}
```

Persisted runtime records should describe what was requested and what executor
defaults were applied.

## Preflight Integration

Preflight uses normalized runtime/resource objects to check:

```text
runtime option normalization
runtime profile selection
exact-stage runtime option targets
selected executor exists
local executor availability
executor capability diagnostics such as unclaimed adapter namespaces
resource capability diagnostics such as ignored or unsupported resource kinds
run directory and artifact paths are writable
```

Unsupported resource fields should usually be warnings unless execution would
definitely fail.

Stable runtime-related preflight IDs are grouped as follows:

```text
runtime:
  runtime.options
  runtime.profile
  runtime.stage_options
executor:
  executor.local
  executor.resolve
  executor.capabilities
resources:
  resources.capabilities
```

`--strict` keeps the existing CLI behavior: warning results still serialize as
`WARN`, but the command exits with the pipeline failure code.

## Testing

Unit tests should cover:

```text
valid resource request construction
invalid negative resources
invalid zero values where not allowed
rejection of deferred timeout, retry, executor, scheduler, container, and
remote-store fields
extension attribute serialization
local-only runtime request defaults
resume option normalization
selected stage validation
force stage validation
profile merge behavior if implemented in this layer
executor descriptor registry behavior
resource capability diagnostics
adapter namespace ownership warnings
executor mapping smoke tests in executor-specific packages
```

Tests should avoid requiring SLURM, Docker, or Apptainer.

## Implementation Plan

1. Define foundation resource and runtime dataclasses.
2. Add validation helpers that do not touch the filesystem.
3. Keep authored stage runtime/executor policy rejected until a later phase
   owns execution semantics.
4. Wire config and CLI option parsing into broader runtime option objects later.
5. Record normalized runtime options in run metadata later.
6. Teach executor adapters to consume the shared objects later.
7. Add preflight checks that use the same normalized objects later.

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

These should be added after post-v0 runtime/resource mappings are stable.
