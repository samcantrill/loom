# loom Container Executors Specification

## Purpose

Container executors run stages or whole pipelines inside container runtimes such
as Docker and Apptainer/Singularity.

They improve environment reproducibility and make local, CI, and HPC execution
more consistent. They should be optional executor adapters, not required core
runtime dependencies.

## Current Support

Loom provides Docker and Apptainer/Singularity executor paths with inspectable
command and provenance records. Their external runtimes remain optional and are
validated before live execution.

## Quick Start

Run the hermetic fake-Apptainer walkthrough:

```sh
uv run python examples/execution/containers/slurm-apptainer/run_apptainer_pipeline.py
```

## GPU Admission

An attribute-free exclusive `gpu` count automatically enables Apptainer or
Singularity `--nv`. For a positive request, direct execution requires exactly
that many unique opaque `CUDA_VISIBLE_DEVICES` tokens on the invoking host and
passes the validated value through `--cleanenv`. Project container options must
not author `CUDA_VISIBLE_DEVICES` for that managed request.

For SLURM `afterok` jobs, the same per-stage resource produces `--gres=gpu:N`
and `--nv`. The generated script performs the visibility check only inside the
allocation, then forwards the scheduler value through both
`APPTAINERENV_CUDA_VISIBLE_DEVICES` and `SINGULARITYENV_CUDA_VISIBLE_DEVICES`.
Loom does not choose physical devices or persist their tokens. A zero or absent
GPU request leaves container options and visibility untouched.

## Deferred

Managed external image-build services, image publishing, Kubernetes, and Docker
Compose are not container-executor features.

## Scope

This component owns:

```text
container executor configuration shape
shared container build target configuration shape
local foreground build/reuse records and redacted evidence
container image identity recording
command construction contract
mount and working directory rules
environment variable handoff
resource mapping where supported
log and exit-code capture
Docker executor behavior
Apptainer/Singularity executor behavior
preflight checks for container runtimes
```

This component does not own:

```text
external or site-managed build services
publishing images
cloud container orchestration
Kubernetes
Docker Compose
domain-specific dependency management
artifact serialization
pipeline graph logic
```

## Design Goals

Container execution should:

```text
preserve the same stage execution contract as other executors
work with local run directories and artifact stores
record image and runtime provenance
avoid requiring Docker or Apptainer for normal local use
support HPC-friendly Apptainer workflows
keep command construction inspectable
```

## Executor Types

Recommended executor names:

```text
docker
apptainer
singularity
```

`singularity` may be an alias for the Apptainer executor if the installed
command is `singularity`.

The core runtime should resolve these through the executor registry, ideally as
optional plugins or optional built-ins with no Python SDK dependency.

## Container Configuration

Example:

```yaml
executor: docker

container:
  image: ghcr.io/example/project:2026-05-03
  workdir: /workspace
  mounts:
    - source: .
      target: /workspace
      mode: ro
    - source: runs
      target: /workspace/runs
      mode: rw
  environment:
    LOOM_ENV: production
```

The exact config ownership may live in executor-specific profile sections. The
shared concepts should remain stable.

## Image Identity

Container provenance should record:

```text
image reference from config
resolved digest when available
container runtime name
container runtime version
pull policy
```

Example:

```json
{
  "runtime": "docker",
  "image": "ghcr.io/example/project:2026-05-03",
  "digest": "sha256:..."
}
```

Tags are mutable. When possible, resolved digests should be recorded.

## Execution Contract

The container should run a `loom` command or a stage wrapper command with the
same inputs that a non-container executor would use.

Conceptual command:

```bash
loom stage run --run-dir /workspace/runs/RUN_ID --stage train
```

The exact command may differ, but it should satisfy:

```text
stage ID is explicit
run directory is explicit
configuration or resolved run metadata is available in the container
artifacts are accessible through mounted paths or configured stores
logs are captured outside or inside a known run log path
exit code maps to stage attempt status
```

## Whole-Pipeline vs Per-Stage

Container executors may support two modes:

```text
whole-pipeline: one container runs the controller and all stages
per-stage: controller launches one container per stage attempt
```

Per-stage execution aligns better with existing executor contracts and SLURM
submission. Whole-pipeline execution is useful for local reproducibility and CI.

The initial design should prioritize per-stage execution for executor parity.

## Mounts

Mounts connect host paths to container paths.

Required mounts usually include:

```text
project source or installed package
run directory
artifact store root for local stores
temporary directory when needed
```

Mount rules:

```text
source path must be explicit
target path must be absolute inside the container
mode is ro or rw
run directory must be writable for executing stages
read-only source mounts are preferred for project code
```

Preflight should check mount source paths where possible.

## Working Directory

The container working directory should be explicit.

Recommended default:

```text
/workspace
```

The working directory should contain either:

```text
the project source tree
an installed project package
a run metadata directory with enough information to execute the stage
```

Do not depend on the host current working directory implicitly.

## Environment

Environment variables may come from:

```text
runtime options
executor profile
selected safe host variables
plugin configuration
```

The executor should avoid passing the full host environment by default. It
should pass only known variables or variables explicitly requested by config.

Secrets may be passed by the runtime environment, but they should not be written
to run metadata.

## Resources

Resource requests may be mapped to container runtime flags when supported.

Docker examples:

```text
cpu entries -> CPU limit or CPU-set policy
memory entries -> memory limit
gpu entries -> GPU access policy
```

Apptainer examples:

```text
resource control often comes from the outer scheduler
GPU access may use --nv or --rocm
```

SLURM plus Apptainer should usually let SLURM enforce CPU, memory, and wall
time while Apptainer provides the filesystem/runtime environment.

## Docker Executor

Docker executor responsibilities:

```text
find docker command
construct docker run command
apply mounts
apply working directory
apply selected environment variables
apply resource flags when configured
capture stdout/stderr
record container exit code
record image digest when available
```

The executor should use the Docker CLI initially rather than requiring the
Docker Python SDK.

Stage 17 implements Docker as a per-stage executor. The controller remains on
the host, prepares one stage attempt in the normal run store, and launches the
prepared worker command through `docker run`. It does not implement
whole-controller-in-container execution.

Implemented Stage 17 config uses runtime or profile adapter options:

```yaml
runtime_profiles:
  docker-default:
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

The shared `container` namespace owns image, workdir, mounts, explicit
environment handoff, and resource intent. The `docker` namespace owns
Docker-specific command flags such as `network`, `platform`, `user`,
`hostname`, and `remove`.

Stage 17 requires path parity for local run directories and local artifact
roots: the host path and container-visible path must match. The executor adds
required read-write mounts for those paths and fails closed when an authored
mount conflicts with them.

Failure inspection uses the same surfaces as other executors:

```sh
loom status RUN_URI --format json
loom logs RUN_URI STAGE --stream stderr --format json
```

Executor metadata records the redacted Docker command, image reference,
container option summary, path-parity summary, return code, and bounded
stdout/stderr facts. It must not persist raw environment values.

Potential preflight checks:

```text
docker command exists
image reference is present
mount sources exist
run directory mount is writable
artifact root is visible through a path-parity mount
required environment variable names are present
CPU and memory mapping is supported
GPU requests fail because Stage 17 does not map GPUs
```

Image pulls should be explicit because they can require network access.
Default Stage 17 preflight is cheaper than daemon health: it checks command
availability through `PATH` and never pulls images, contacts registries, probes
networks, or requires a live daemon.

## Shared Build Targets

Stage 18 adds an executor-owned `container_build` adapter namespace for reusable
local build targets. A target describes a Docker image or Apptainer SIF output,
its authored source, a local build/reuse policy, build arguments, and redacted
metadata. The namespace is replaced as a whole when runtime/profile options are
merged; Loom does not deep-merge individual targets in this stage.

Example Apptainer SIF target:

```yaml
runtime:
  adapter_options:
    container_build:
      targets:
        analysis-env:
          name: analysis-env
          runtime: apptainer
          source:
            kind: definition_file
            path: containers/analysis.def
          output:
            kind: apptainer_sif
            path: .loom/containers/analysis-env.sif
          policy:
            mode: if_stale
```

Local builders run in the foreground and return `built`, `reused`, `failed`, or
`skipped` results with redacted command/evidence summaries. Build output refs
are facts, not authoritative stage outputs. The default implementation does not
publish images, authenticate to registries, maintain a global cache, or run an
external build service.

For direct Docker or Apptainer execution, configure
`adapter_options.container.image.reference` with the image ref or SIF path the
executor should use. SLURM plus Apptainer can additionally resolve
`adapter_options.container.target` from a configured Apptainer build target
before script rendering or live submission.

## Apptainer Executor

Apptainer executor responsibilities:

```text
find apptainer or singularity command
construct apptainer exec command
apply bind mounts
apply working directory where supported
apply selected environment variables
record image path or URI
capture stdout/stderr
record exit code
```

Apptainer is important for HPC systems because Docker daemons are often
unavailable on compute nodes.

Potential preflight checks:

```text
apptainer or singularity command exists
image path or URI is present
bind source paths exist
run directory bind is writable
GPU flags are valid for the selected profile
```

Implemented Stage 18 direct Apptainer/Singularity execution uses the same
prepared-worker contract as subprocess and Docker: the controller prepares one
stage attempt, injects required read-write binds for the local run directory and
artifact root, and launches the worker through `apptainer exec` or
`singularity exec`.

Implemented config uses runtime or profile adapter options:

```yaml
runtime_profiles:
  apptainer-default:
    executor: apptainer
    adapter_options:
      container:
        image:
          reference: .loom/containers/analysis-env.sif
        workdir: /workspace
        mounts:
          - source: /workspace
            target: /workspace
            mode: ro
        environment:
          variables:
            LOOM_CONTAINER_EXAMPLE: apptainer-pipeline
          required_host_variables:
            - LOOM_INPUT_ROOT
      apptainer:
        cleanenv: true
        nv: false
        rocm: false
```

`cleanenv` defaults to true. Explicit variables and selected required host
variables are projected with values redacted from persisted metadata. GPU
exposure is explicit through `nv` or `rocm`; scheduler allocation remains owned
by the outer scheduler when SLURM is selected.

## SLURM Integration

SLURM and containers can be composed in two ways:

```text
SLURM submits a wrapper that runs Apptainer inside the allocation
controller runs locally and submits containerized stage jobs
```

The second form should reuse existing SLURM submission design:

```text
stage attempt metadata is created by the controller
submission script invokes container runtime
container command runs the stage wrapper
SLURM records job ID and scheduler status
container executor records image and exit code
```

Avoid creating a separate containerized SLURM path that bypasses normal executor
state records.

Stage 18 composes existing `slurm-single-job` and `slurm-afterok` modes with
Apptainer by wrapping generated `loom prepared-run continue` or
`loom stage-job run` commands in deterministic Apptainer exec argv. Build
target resolution runs on the submit/controller side before dry-run artifacts
are rendered or `sbatch` is called. Generated batch scripts contain Apptainer
execution commands and never hide Docker or Apptainer build commands.

Example SLURM plus Apptainer profile:

```yaml
runtime_profiles:
  slurm-apptainer:
    executor: slurm-afterok
    dry_run: true
    adapter_options:
      container:
        target: analysis-env
      container_build:
        targets:
          analysis-env:
            name: analysis-env
            runtime: apptainer
            source:
              kind: definition_file
              path: containers/analysis.def
            output:
              kind: apptainer_sif
              path: .loom/containers/analysis-env.sif
      apptainer:
        cleanenv: true
        no_home: true
      slurm:
        launcher_argv: ["loom"]
```

## Artifacts

Containerized stages must use the same artifact store contracts as other
stages.

For local artifact stores:

```text
host artifact root must be mounted into the container
container path must match the path used by stage execution metadata or be mapped explicitly
atomic writes should commit on the host-visible filesystem
```

For remote artifact stores:

```text
container must have backend dependencies installed
credentials must be available through the environment or mounted files
preflight should report missing backend capabilities when possible
```

## Logs

Container executors should capture:

```text
host-side command line with secrets redacted
stdout
stderr
container runtime exit code
stage wrapper exit code if distinguishable
started_at
finished_at
duration_seconds
```

Logs should be written under the run directory using the same log conventions as
other executors.

## Security

Container execution should be explicit about trust.

Rules:

```text
authored configs are trusted project code
image references come from trusted config
do not pass all host environment variables by default
redact secrets in recorded commands
avoid privileged containers by default
avoid mounting host root paths by default
reject unsafe mount targets
```

Container isolation should not be documented as a security sandbox for
untrusted project code unless a separate threat model is written.

## Preflight Integration

Preflight should check:

```text
container runtime command availability
image reference presence
mount source existence
run directory writability through the configured mount
required environment variables
resource mapping support
selected executor plugin availability
```

Checks that require pulling images or contacting registries should be opt-in.
Implemented Stage 18 preflight checks are cheap by default. They parse
`container`, `container_build`, `docker`, `apptainer`, `singularity`, and
`slurm` adapter namespaces, check runtime command availability through `PATH`,
inspect local paths, summarize build target readiness, and report required host
environment variable names. They do not run real containers, pull images,
contact registries, submit jobs, or probe fakeroot.

## Error Handling

Container executor errors should distinguish:

```text
runtime command not found
image not found
image pull failed
mount source missing
container startup failed
stage command failed
timeout
permission denied
unsupported resource mapping
```

Where possible, errors should include the redacted command and log paths.

## Testing

Core tests should use fake commands and command builders.

Tests should cover:

```text
Docker command construction
Apptainer command construction
mount validation
environment filtering
resource flag mapping
redaction
missing runtime preflight
container exit code mapping
SLURM wrapper composition shape
```

Integration tests that require real Docker, Apptainer/Singularity, SIF build,
or SLURM should be optional and skipped unless explicitly enabled.

Stage 17 example smoke tests use a fake `docker` command that executes the
prepared worker command locally while exercising the public Docker executor and
CLI path. A manual live Docker smoke is useful only when the selected image can
import `loom` and the example project code at the same paths used by the host.

## Implementation Plan

1. Define shared container config models.
2. Add command builders for Docker and Apptainer.
3. Add fake-command unit tests for command construction.
4. Add preflight checks for runtime availability and mounts.
5. Add Docker executor using the CLI.
6. Add Apptainer executor using the CLI.
7. Compose Apptainer with SLURM submission scripts.
8. Record image/runtime provenance in attempt metadata.

## Deferred Work

Deferred container features:

```text
image lock files
registry authentication helpers
Kubernetes executor
Docker Compose integration
container layer caching policy
automatic image pull in preflight
rootless Docker-specific behavior
advanced GPU mapping
```

Container execution should remain optional until local and SLURM execution are
stable.
