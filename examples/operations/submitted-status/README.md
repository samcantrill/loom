# Submitted Status

This internal demo is kept for regression coverage of synthetic submitted
status records. It is not part of the primary user-facing catalog because it
seeds submitted-operation state directly instead of showing a real scheduler or
full live-submission workflow.

It creates a synthetic submitted run under an explicit authority supervisor and
inspects it with ordinary `loom status`. It demonstrates the v7 submitted
lifecycle without querying a scheduler.

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
