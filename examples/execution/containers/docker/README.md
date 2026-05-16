# Docker Container Executor Example

This example demonstrates Stage 17 Docker execution with domain-neutral stages:

1. Run a normal Loom pipeline with `loom run --executor docker`.
2. Inspect selected-Docker preflight pass and fail diagnostics.
3. Run a failing Docker stage, then inspect persisted status and stderr logs.
4. Review the prepared-stage `docker run` command shape used by the executor.

Default validation uses a small fake `docker` command on `PATH`. It runs the
prepared worker command locally while preserving the Docker executor, command
builder, preflight, status, log, and provenance paths. It does not require a
Docker daemon, image pull, registry, network access, or Docker SDK.

Docker can improve environment reproducibility, but this example does not make
Docker a security sandbox for untrusted project code or untrusted images.

## Workflow

This workflow uses:

- `loom run CONFIG --run-uri RUN_URI --executor docker`
- `loom preflight CONFIG --check executor --check filesystem --check resources`
- `loom status RUN_URI`
- `loom logs RUN_URI STAGE --stream stderr`

## Variants

Canonical Docker executor command:

```sh
uv run loom run examples/execution/containers/docker/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/docker-pipeline \
  --executor docker
```

Explicit co-located authority selection:

```sh
uv run loom run examples/execution/containers/docker/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/docker-pipeline \
  --executor docker \
  --authority-backend co_located_service \
  --authority-profile co_located
```

Focused selected-Docker preflight:

```sh
uv run loom preflight examples/execution/containers/docker/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/docker-preflight \
  --check executor \
  --check filesystem \
  --check resources \
  --format json
```

The JSON output includes stable Docker check IDs such as
`executor.docker.command`, `executor.docker.container_options`,
`executor.docker.image`, `filesystem.docker.artifact_root_visible`,
`resources.docker.mapping`, and `resources.docker.gpu`.

Run from the repository root:

```sh
uv run python examples/execution/containers/docker/run_docker_pipeline.py
uv run python examples/execution/containers/docker/run_preflight.py
uv run python examples/execution/containers/docker/run_failure_diagnostics.py
```

The scripts write run state under `examples/execution/containers/docker/runs/`
by default. Set `LOOM_EXAMPLE_OUTPUT_ROOT=/tmp/loom-examples` or
`LOOM_EXAMPLE_RUN_ROOT=/tmp/loom-example-runs` to write somewhere else.

## Prepared Stage Shape

The Docker executor still runs one prepared stage attempt at a time. The parent
runner prepares the run-store state, then Docker launches the same public worker
command a subprocess executor would use:

```sh
docker run --rm \
  --network none \
  --env LOOM_CONTAINER_EXAMPLE=[redacted] \
  --mount type=bind,src=/tmp/loom-example-runs/docker-pipeline,target=/tmp/loom-example-runs/docker-pipeline \
  python:3.12-slim \
  python -c "from loom.cli.main import main; raise SystemExit(main())" \
  stage run --run-uri file:///tmp/loom-example-runs/docker-pipeline \
  --stage seed \
  --attempt 1 \
  --format json
```

Actual run-directory and artifact-root mounts are added by the executor with
Stage 17 path parity: the host path and container path must match.

## Optional Live Docker Smoke

Default validation intentionally stays daemon-free. For a manual live smoke,
use an image that already contains `loom`, its optional config dependencies, and
the example stage module, or mount the repository at the same absolute path in
the container. Then run the canonical command above in an environment where
`docker run` can access the selected run directory and artifact root through
path-parity mounts.

Image builds, registry authentication, automatic pulls, Docker Compose,
Kubernetes, Apptainer/Singularity, and controller-in-container workflows are
outside Stage 17.
