# Container Example Coverage

This document tracks user-facing coverage for the installed Docker agent worker workflow. Examples stay domain-neutral, use existing library execution and public diagnostic CLI
surfaces, and keep daemon-dependent behavior outside default validation.

Ordinary managed runs use a configured deployment. These public run journeys with fake runtimes
preserve backend assertions; they do not qualify a physical container
runtime or claim physical container execution.

## Covered User-Facing Behaviors

| Behavior | Coverage | Examples |
| --- | --- | --- |
| Docker stage workers | Public run prepares and executes assignments through a stateful fake Docker daemon, then settles owned services. | `execution.containers.docker` |
| Docker adapter options | Installed agent profiles select image, environment, runtime command and daemon endpoint; standalone preflight retains authored adapter options. | `execution.containers.docker` |
| Selected-Docker preflight | `loom preflight` reports stable Docker check IDs for command, config, image, environment, filesystem, and resources without daemon, registry, pull, or network probes. | `execution.containers.docker` |
| Failure inspection | Native failed admissions and materialized worker results retain structured failure and stderr after service cleanup. | `execution.containers.docker` |
| Optional live Docker smoke | Real Docker smoke is documented as manual guidance and stays outside `make validate-pr`. | `execution.containers.docker` |

Representative e2e evidence for this feature now includes:

- `tests/e2e/test_example_journeys.py::test_e2e_example_docker_executor_smoke_and_failure_diagnostics`

## Example Coverage

| Example | Version | Status | Validation | Functionality covered | Implementation notes |
| --- | --- | --- | --- | --- | --- |
| `execution.containers.docker` | current | runnable | e2e (`tests/e2e/test_example_journeys.py::test_e2e_example_docker_executor_smoke_and_failure_diagnostics`) | Runs a two-stage synthetic pipeline through public run and the agent/supervisor Docker owner, inspects selected-Docker preflight pass/fail diagnostics, and inspects a persisted Docker failure. | Default validation binds an explicit fake daemon endpoint and a configured runtime command; container state survives individual CLI helpers. README guidance describes daemon ownership and opt-in physical qualification. |

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
- document whole-controller-in-container execution;
- require image builds, registry authentication, Compose, Kubernetes,
  Apptainer/Singularity, or SLURM-container composition;
- persist raw environment variable values in example output.

Live Docker examples must stay manual unless a future deterministic validation
path is explicitly introduced.
