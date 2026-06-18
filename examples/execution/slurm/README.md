# SLURM Execution Examples

These examples show SLURM-oriented execution behavior without requiring a
cluster for runnable examples.

## Catalog

| Example | Demonstrates |
| --- | --- |
| `execution.slurm.dry-run-basics` | Public `slurm-single-job` and `slurm-afterok` dry-runs that generate reviewable scripts and manifests without scheduler submission. |
| `execution.slurm.afterok-diamond` | Afterok dependency planning for a diamond DAG, stage-level SLURM options/resources, generated continuation commands, and secret-safe dry-run artifacts. |
| `execution.slurm.live` | Manual live SLURM submit/status/cancel commands for `slurm-single-job` and `slurm-afterok` on a shared cluster filesystem. |

Run from the repository root:

```sh
uv run python examples/execution/slurm/dry-run-basics/run_dry_run_basics.py
uv run python examples/execution/slurm/afterok-diamond/run_afterok_diamond.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to redirect generated
run directories.
