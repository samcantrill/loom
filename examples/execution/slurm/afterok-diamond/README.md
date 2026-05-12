# SLURM Afterok Diamond Dry Run

This example generates SLURM `afterok` dry-run artifacts for a diamond-shaped
pipeline:

```text
extract -> features -> report
        -> train    ->
```

## Workflow

This workflow uses:

- `loom run CONFIG --executor slurm-afterok --dry-run`

## Variants

Canonical afterok dry-run:

```sh
uv run loom run examples/execution/slurm/afterok-diamond/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/slurm-afterok-diamond \
  --executor slurm-afterok \
  --dry-run
```

Explicit co-located authority selection:

```sh
uv run loom run examples/execution/slurm/afterok-diamond/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/slurm-afterok-diamond \
  --executor slurm-afterok \
  --dry-run \
  --authority-backend co_located_service \
  --authority-profile co_located
```

JSON dry-run output for manifest inspection:

```sh
uv run loom run examples/execution/slurm/afterok-diamond/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/slurm-afterok-diamond \
  --executor slurm-afterok \
  --dry-run \
  --format json
```

Run from the repository root:

```sh
uv run python examples/execution/slurm/afterok-diamond/run_afterok_diamond.py
```

The script inspects generated artifacts instead of submitting work. It prints
logical dependency edges, generated continuation command targets, per-stage
SBATCH directives, wrapper log paths, and a secret-boundary check.
