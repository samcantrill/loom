# SLURM Dry-Run Basics

This example generates SLURM dry-run artifacts for a small two-stage pipeline.
It does not call `sbatch` or execute the generated scripts.

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
