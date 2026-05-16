# Container Example Coverage

This document tracks user-facing coverage for the implemented v17 Docker
container executor workflow. Examples stay domain-neutral, use public CLI
surfaces, and keep daemon-dependent behavior outside default validation.

## Covered User-Facing Behaviors

| Behavior | Coverage | Examples |
| --- | --- | --- |
| Docker stage workers | `loom run CONFIG --executor docker` runs normal Loom pipelines whose selected stage attempts launch through Docker. | `execution.containers.docker` |
| Docker adapter options | Runtime profiles use `adapter_options.container` for image and environment handoff plus `adapter_options.docker` for Docker-owned flags. | `execution.containers.docker` |
| Selected-Docker preflight | `loom preflight` reports stable Docker check IDs for command, config, image, environment, filesystem, and resources without daemon, registry, pull, or network probes. | `execution.containers.docker` |
| Failure inspection | Docker failures are visible through existing `loom status` and `loom logs` surfaces. | `execution.containers.docker` |
| Optional live Docker smoke | Real Docker smoke is documented as manual guidance and stays outside `make validate-pr`. | `execution.containers.docker` |

## Example Coverage

| Example | Version | Status | Validation | Functionality covered | Implementation notes |
| --- | --- | --- | --- | --- | --- |
| `execution.containers.docker` | v17 | runnable | smoke | Runs a two-stage synthetic pipeline through `loom run --executor docker`, inspects selected-Docker preflight pass/fail diagnostics, and inspects a persisted Docker failure. | Default validation installs a fake `docker` command on `PATH` so the public Docker executor path is exercised without a daemon. README guidance covers prepared-stage command shape and optional live Docker smoke. |

## Example Coverage Checks

Runnable container examples should have:

- an `example.yaml` manifest with `status: runnable`;
- a README that names the supported public command being demonstrated;
- one or more Python entrypoints covered by the docs/example harness;
- deterministic output suitable for local CI;
- `LOOM_EXAMPLE_OUTPUT_ROOT` and `LOOM_EXAMPLE_RUN_ROOT` support when writing
  generated output or run directories;
- no requirement for real Docker, network access, registries, image pulls, or
  Docker SDKs in default validation.

Docker examples must not:

- document Docker as a security sandbox for untrusted project code;
- document whole-controller-in-container execution as Stage 17 behavior;
- require image builds, registry authentication, Compose, Kubernetes,
  Apptainer/Singularity, or SLURM-container composition;
- persist raw environment variable values in example output.

Live Docker examples must stay manual unless a future deterministic validation
path is explicitly introduced.
