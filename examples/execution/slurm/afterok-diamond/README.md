# SLURM Afterok Diamond Dry Run

The runnable script uses the existing library execution or planning primitives
directly. Ordinary runs use the [configured service lifecycle](../../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). Backend demonstrations here retain their
current process, artifact, and diagnostic assertions.

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
