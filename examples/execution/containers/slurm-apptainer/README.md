# Apptainer Container Executor

This example runs one prepared stage through `loom run --executor apptainer`.
Default validation installs a fake `apptainer` executable on `PATH`, logs the
safe command shape, and executes the worker locally. It proves Loom's command
integration, not container isolation or an HPC installation.

## Workflow

The runner calls:

- `loom run CONFIG --run-uri RUN_URI --executor apptainer`
- `apptainer exec --cleanenv --nv IMAGE WORKER_COMMAND`

## Variants

Run the hermetic default journey:

```sh
uv run python examples/execution/containers/slurm-apptainer/run_apptainer_pipeline.py
```

For an optional live preflight, install `apptainer` or `singularity`, provide a
locally available SIF containing Loom and the example's stage module, and use
a run directory visible inside the container:

```sh
uv run loom preflight examples/execution/containers/slurm-apptainer/pipeline.yaml \
  --check executor --check filesystem --format json
```

On a real SLURM cluster, use the same image and path-parity mounts in an
existing `slurm-single-job` or `slurm-afterok` runtime profile. SLURM owns the
allocation; Apptainer owns the worker environment. Live scheduler and
container execution remain site-specific manual work.
