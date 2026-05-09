# SLURM Live Job Operations

This manual example shows how to inspect and cancel live SLURM jobs for a run
that was submitted with `slurm-single-job` or `slurm-afterok`.

It requires a real SLURM cluster and a run directory on a shared filesystem
visible to both the submit host and compute nodes.

## Inspect Persisted State

Ordinary status reads persisted Loom state and does not query SLURM:

```sh
uv run loom status file:///shared/loom-runs/slurm-live-example
```

This view should show the run or stages as `SUBMITTED` while scheduler work is
pending or running.

## Inspect Scheduler Jobs

Scheduler-aware status is explicit:

```sh
uv run loom status file:///shared/loom-runs/slurm-live-example --jobs
```

This command discovers the latest submitted operation, queries available SLURM
status commands, records scheduler snapshots in the manifest, and reports
uncertainty when `sacct` or `squeue` cannot prove a final state.

## Inspect Manifest Records

The submission manifest is under the run directory:

```text
slurm/submissions/<submission_id>/manifest.json
```

Review it for logical job keys, scheduler job IDs, dependency job IDs, wrapper
stdout/stderr paths, status snapshots, failed submissions, and cancellation
attempts.

## Cancel Active Jobs

Cancel the latest active submitted operation:

```sh
uv run loom cancel file:///shared/loom-runs/slurm-live-example --jobs
```

Cancellation records one result per job ID. Partial cancellation returns a
nonzero exit code and leaves the manifest available for follow-up inspection.

## Operational Notes

- Do not resubmit into a run URI with active submitted work.
- Use `loom status RUN_URI --jobs` after cancellation to check scheduler
  visibility and uncertainty.
- Preserve the run directory until wrapper logs and artifacts have been
  inspected.
