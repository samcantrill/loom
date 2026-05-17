# Execution Examples

Execution examples cover how `loom` runs authored work: local in-process
execution, subprocess workers, Docker stage workers, SLURM dry-run planning,
manual live SLURM templates, runtime profiles, normalized run options, explicit
offline-first evidence import, artifact storage, provenance snapshots, and
same-run resume behavior.

Future executor examples should live here too. Docker examples should use
`examples/execution/containers/docker/`, and containerized SLURM plus Apptainer
examples should use `examples/execution/containers/slurm-apptainer/`.

## CLI Workflows

| Example | Demonstrates |
| --- | --- |
| `execution.subprocess` | Running the same synthetic pipeline locally and with subprocess workers, inspecting subprocess failure diagnostics, and invoking a prepared stage through `loom stage run`. |
| `execution.containers.docker` | Running stage attempts through `loom run --executor docker`, selected-Docker preflight diagnostics, Docker failure inspection, and optional live Docker smoke guidance. |
| `execution.runtime-profile` | Configured runtime profile, CLI tags/notes, resource diagnostics, local run, and safe `runtime.json`. |
| `execution.offline-first-import` | Explicit `--offline-first` execution, pre-import status behavior, authority import, and post-import authoritative status. |
| `execution.slurm.dry-run-basics` | Public `slurm-single-job` and `slurm-afterok` dry-runs that generate reviewable scripts and manifests without scheduler submission. |
| `execution.slurm.afterok-diamond` | Afterok dependency planning for a diamond DAG, stage-level SLURM options/resources, generated continuation commands, and secret-safe dry-run artifacts. |
| `execution.slurm.live` | Manual live SLURM submit/status/cancel commands for `slurm-single-job` and `slurm-afterok` on a shared cluster filesystem. |

## Public Python API Workflows

| Example | Demonstrates |
| --- | --- |
| `execution.local` | Composing a static pipeline config, running a two-stage local pipeline, writing artifacts through the local store, recording provenance/fingerprints, and reusing unchanged stages from the same run directory. |
| `execution.python-run-options` | Public Python construction, merge, stage validation, and capability diagnostics for `RunOptions`. |

## Run

Run from the repository root:

```sh
uv run python examples/execution/local/run_pipeline.py
uv run python examples/execution/subprocess/run_subprocess_pipeline.py
uv run python examples/execution/subprocess/run_failure_diagnostics.py
uv run python examples/execution/subprocess/run_direct_worker.py
uv run python examples/execution/containers/docker/run_docker_pipeline.py
uv run python examples/execution/containers/docker/run_preflight.py
uv run python examples/execution/containers/docker/run_failure_diagnostics.py
uv run python examples/execution/runtime-profile/run_runtime_profile.py
uv run python examples/execution/python-run-options/run_options_api.py
uv run python examples/execution/offline-first-import/run_offline_first_import.py
uv run python examples/execution/slurm/dry-run-basics/run_dry_run_basics.py
uv run python examples/execution/slurm/afterok-diamond/run_afterok_diamond.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to redirect generated
run directories.
