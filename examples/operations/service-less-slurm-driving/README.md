# Service-Less SLURM Driving

Project code first prepares each ordinary run with either
`slurm-single-job` or `slurm-afterok`, then enqueues a closed
`loom.slurm-prepared-run.v1` reference. The queue record carries only that
reference; the run-local SLURM manifest remains the only job inventory.

Run the cluster-free mixed-mode example from the repository root:

```sh
uv run python examples/operations/service-less-slurm-driving/run_service_less_slurm.py
```

It uses fake scheduler commands and in-process authority stores to show two
short-lived driver lifetimes sharing one durable queue and run root. The first
driver submits one single-job run, the reopened driver reconciles it and
submits a two-stage `afterok` run, and a final reopen observes Loom terminal
results without requiring live accounting or any network service.

On a login host with the project environment and shared run root available:

```sh
loom queue drive-slurm-foreground queue.yaml --pool slurm --run-root runs
```

The command runs bounded foreground cycles and exits when no local transition
is ready. It does not wait for SLURM jobs. Re-run it after driver loss or to
admit the next protected page; use `--once` for one cycle and `--format json`
for stable counts and diagnostics.

Before using this route, the site operator must confirm all of the following:

- Site policy permits short-lived foreground commands on the submission host;
  no long-running login-node Loom process is required.
- The submission host provides `sbatch`, `squeue`, `sacct`, and `scancel`.
- Compute nodes see the configured run root, generated scripts, project
  environment, and any input/output paths under the same usable names.
- Project code records that site attestation in each prepared queue launch as
  `delegated_verification={"shared_workspace": True}` (or a plain
  `{"status": "proven"}` value). Loom does not mount, copy, or probe a
  compute node to establish it.
- Queue reconciliation and dispatch bounds suit local login-node policy.
- Only one foreground driver operates a queue database at a time; concurrent
  driver takeover and coordinator high availability are not provided.
- `sacct` retains allocation comments long enough to recover a response lost
  after scheduler acceptance.
- Operators let the foreground command exit at local quiescence and rerun it
  after interruption or when later queued work should be admitted.

Cancellation uses retained scheduler handles. Exact scheduler-call markers let
a reopen repair one uniquely discovered lost response. Zero matches remain
unknown and multiple matches become a conflict; neither case is blindly
resubmitted. Old completed runs remain successful only when their Loom
authority result is terminal; SLURM `COMPLETED` alone is still settling, never
scientific success.

This is intentionally not a replacement for the Stage 29 coordinator route.
It provides no dynamic ready-stage coordination, array dispatch, remote byte
transfer, remote log retrieval, or real-time webhook/report delivery. Projects
that need those features should use an allowed Stage 29 coordinator deployment
or keep downstream dynamic logic inside one whole-run job.
