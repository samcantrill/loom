# SLURM Afterok Diamond Dry Run

This example generates SLURM `afterok` dry-run artifacts for a diamond-shaped
pipeline:

```text
extract -> features -> report
        -> train    ->
```

Run from the repository root:

```sh
uv run python examples/execution/slurm/afterok-diamond/run_afterok_diamond.py
```

The script inspects generated artifacts instead of submitting work. It prints
logical dependency edges, generated continuation command targets, per-stage
SBATCH directives, wrapper log paths, and a secret-boundary check.
