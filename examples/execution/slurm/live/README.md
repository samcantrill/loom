# SLURM Live Operations Example

This example is a small template for a real SLURM cluster. It assumes the run
directory is on a shared filesystem visible to both the submit host and compute
nodes.

Run commands from this directory so the `stages.py` module is importable by the
submitted jobs.

## Preflight

Check the configuration and SLURM command availability from the submit host:

```sh
uv run loom preflight pipeline.yaml \
  --executor slurm-afterok
```

Missing `sbatch` is a live-submission error. Missing `squeue`, `sacct`, or
`scancel` may still allow submission, but later status or cancellation commands
will report operation-specific failures if the required command is unavailable.

## Dry Run

Generate scripts, logs, and a submission manifest without calling `sbatch`:

```sh
uv run loom run pipeline.yaml \
  --run-uri file:///shared/loom-runs/slurm-live-example \
  --executor slurm-afterok \
  --dry-run
```

## Live Submit

Submit one SLURM job per runnable stage:

```sh
uv run loom run pipeline.yaml \
  --run-uri file:///shared/loom-runs/slurm-live-example \
  --executor slurm-afterok
```

For one allocation that runs the whole pipeline, use:

```sh
uv run loom run pipeline.yaml \
  --run-uri file:///shared/loom-runs/slurm-live-single \
  --executor slurm-single-job
```

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
