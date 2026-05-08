# Execution Examples

Execution examples cover how `loom` runs authored work: local in-process
execution, subprocess workers, runtime profiles, normalized run options,
artifact storage, provenance snapshots, and same-run resume behavior.

Future executor examples should live here too. Docker examples should use
`examples/execution/containers/docker/`, and SLURM plus Apptainer examples
should use `examples/execution/containers/slurm-apptainer/`.

## Catalog

| Example | Demonstrates |
| --- | --- |
| `execution.local` | Composing a static pipeline config, running a two-stage local pipeline, writing artifacts through the local store, recording provenance/fingerprints, and reusing unchanged stages from the same run directory. |
| `execution.subprocess` | Running the same synthetic pipeline locally and with subprocess workers, inspecting subprocess failure diagnostics, and invoking a prepared stage through `loom stage run`. |
| `execution.runtime-profile` | Configured runtime profile, CLI tags/notes, resource diagnostics, local run, and safe `runtime.json`. |
| `execution.python-run-options` | Public Python construction, merge, stage validation, and capability diagnostics for `RunOptions`. |
| `execution.slurm-live` | Manual live SLURM submit/status/cancel commands for `slurm-single-job` and `slurm-afterok` on a shared cluster filesystem. |

## Run

Run from the repository root:

```sh
uv run python examples/execution/local/run_pipeline.py
uv run python examples/execution/subprocess/run_subprocess_pipeline.py
uv run python examples/execution/subprocess/run_failure_diagnostics.py
uv run python examples/execution/subprocess/run_direct_worker.py
uv run python examples/execution/runtime-profile/run_runtime_profile.py
uv run python examples/execution/python-run-options/run_options_api.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to redirect generated
run directories.
