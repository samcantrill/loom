# SLURM Dry-Run Basics

This example generates SLURM dry-run artifacts for a small two-stage pipeline.
It does not call `sbatch` or execute the generated scripts.

## Workflow

This workflow uses:

- `loom run CONFIG --executor slurm-single-job --dry-run`
- `loom run CONFIG --executor slurm-afterok --dry-run`

## Variants

Canonical single-job dry-run:

```sh
uv run loom run examples/execution/slurm/dry-run-basics/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/slurm-single-job \
  --executor slurm-single-job \
  --dry-run
```

Afterok dry-run variant:

```sh
uv run loom run examples/execution/slurm/dry-run-basics/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/slurm-afterok \
  --executor slurm-afterok \
  --dry-run
```

Explicit co-located authority selection:

```sh
uv run loom run examples/execution/slurm/dry-run-basics/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/slurm-afterok \
  --executor slurm-afterok \
  --dry-run \
  --authority-backend co_located_service \
  --authority-profile co_located
```

Run from the repository root:

```sh
uv run python examples/execution/slurm/dry-run-basics/run_dry_run_basics.py
```

The script runs both supported dry-run modes:

- `slurm-single-job`, which creates one whole-run script that calls
  `loom prepared-run continue`;
- `slurm-afterok`, which creates one script per runnable stage that calls
  `loom stage-job run`.

The output lists the generated manifest, scripts, wrapper log paths, warning
codes, and whether scheduler job IDs are absent from the dry-run manifest.
