# Submitted Status

This example creates a synthetic submitted run and inspects it with ordinary
`loom status`. It demonstrates the v7 submitted lifecycle without querying a
scheduler.

Run from the repository root:

```sh
uv run python examples/operations/submitted-status/run_submitted_status.py
```

The script writes a local run with `SUBMITTED` run and stage status plus a
submitted-operation registry record. It then calls:

```sh
loom status RUN_URI --format json
```

It intentionally does not use `--jobs`, `sbatch`, `squeue`, `sacct`, or
`scancel`.
