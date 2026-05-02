# loom Container Executors Specification

## Purpose

Container executors run stages or whole pipelines inside container runtimes such
as Docker and Apptainer/Singularity.

They improve environment reproducibility and make local, CI, and HPC execution
more consistent. They should be optional executor adapters, not required core
runtime dependencies.

## Scope

This component owns:

```text
container executor configuration shape
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
building container images
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
cpus -> --cpus or --cpuset-cpus policy
memory_mb -> --memory
gpus -> --gpus
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

Potential preflight checks:

```text
docker command exists
daemon is reachable when practical
image reference is present
mount sources exist
run directory mount is writable
```

Image pulls should be explicit because they can require network access.

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

Integration tests that require real Docker or Apptainer should be optional and
skipped unless explicitly enabled.

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
image build commands
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

