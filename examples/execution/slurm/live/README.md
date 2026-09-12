# SLURM Live Operations Example

## Workflow

This example is a small template for a real SLURM cluster. It assumes the run
directory is on a shared filesystem visible to both the submit host and compute
nodes.

Run commands from this directory so the `stages.py` module is importable by the
submitted jobs.

## Current Qualification

This is a retained site-configuration and operations template. The previous
ordinary-run Slurm submission flags were removed. Complete managed submission
and this live journey require the Slurm phase and qualified site evidence; the
cluster-free planning demonstrations do not provide that qualification.

From the repository root, inspect the existing library planning examples:

```sh
uv run python examples/execution/slurm/dry-run-basics/run_dry_run_basics.py
uv run python examples/execution/slurm/afterok-diamond/run_afterok_diamond.py
```

The unchanged physical Slurm acceptance hook remains available to its owning
phase. The operations below apply to already-submitted work.

## Status

Persisted status does not query SLURM:

```sh
uv run loom status file:///shared/loom-runs/slurm-live-example
```

Scheduler-aware job status is explicit:

```sh
uv run loom status file:///shared/loom-runs/slurm-live-example --jobs
```

The job view records safe scheduler snapshots under the run directory and
reports uncertainty when `sacct` or `squeue` cannot prove a final state.

The live manifest is written under:

```text
slurm/submissions/<submission_id>/manifest.json
```

Inspect it for logical job keys, scheduler job IDs, dependency job IDs, wrapper
log paths, status snapshots, failed submissions, and cancellation attempts.

## Cancel

Cancel the latest active submitted operation:

```sh
uv run loom cancel file:///shared/loom-runs/slurm-live-example --jobs
```

Cancellation records one attempt per job ID. Partial cancellation returns a
nonzero exit code and leaves the manifest available for inspection.

Do not submit again into the same run URI while active submitted work remains.
Cancel or choose a new run URI first.

## Site Options

Put site-specific options under `runtime.adapter_options.slurm` in
`pipeline.yaml`, for example:

```yaml
runtime:
  adapter_options:
    slurm:
      partition: short
      account: research
      qos: normal
      time: "00:05:00"
```

Do not put secrets or resolved environment values in pipeline configs. Prefer
site modules, activation commands, or scheduler-managed environment setup in
trusted project code.

## Variants

The scripts preserve their existing library/backend demonstrations. Ordinary
managed execution uses a protected deployment selection, with backend and
lifetime policy owned by that selection. Existing status and log commands can
inspect a matching retained run. For a run created with co-located service
authority, pass `--authority-backend co_located_service` and
`--authority-profile co_located` to those diagnostic commands; these are not
ordinary-run overrides.
