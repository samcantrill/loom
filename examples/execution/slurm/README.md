# SLURM Execution Examples

These examples show SLURM-oriented execution behavior without requiring a
cluster for runnable examples.

## Catalog

| Example | Demonstrates |
| --- | --- |
| `execution.slurm.dry-run-basics` | Pure dependency graph planning without scheduler submission or generated commands. |
| `execution.slurm.afterok-diamond` | Afterok dependency planning for a diamond DAG, stage-level SLURM options/resources, generated continuation commands, and secret-safe dry-run artifacts. |
| `execution.slurm.live` | Manual connected native SLURM admission, status and cancellation on a qualified site. |

Run from the repository root:

```sh
uv run python examples/execution/slurm/dry-run-basics/run_dry_run_basics.py
uv run python examples/execution/slurm/afterok-diamond/run_afterok_diamond.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to redirect generated
run directories.
