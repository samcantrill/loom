# Managed Ready-Stage SLURM

## Workflow

Run the deterministic journey from the repository root:

```sh
uv run python examples/operations/managed-ready-stage-slurm/run_managed_ready_stage_slurm.py
```

The script configures one explicit ready-stage SLURM profile and uses Loom's
fake command gateway, so no cluster is required. The first `sbatch` is rejected;
the journey observes the retained rejection and physical assignment release
without falsely turning that scheduler decision into run failure. It restarts
the daemon and proves that operation is retained without resubmission. A second
run is accepted and completed through the public bootstrap view, including
registration, input readiness, grant/start fences, output transfer, result
commit, capability revocation, and release.

Operators observe the same durable assignment operation through the CLI:

```sh
loom queue daemon-operation --endpoint DAEMON_SOCKET OPERATION_ID
loom queue daemon-operation-wait \
  --endpoint DAEMON_SOCKET OPERATION_ID --timeout 15
```

An accepted scheduler submission is not terminal for this command. The wait
finishes only when the owned stage assignment is released or conflicts. The
journey also fails on an extra `sbatch`, a retained capability, or a leaked
worker/service process.

Scheduler acceptance, execution containment, Loom result commit, and physical
release are separate observations. In particular, scheduler `COMPLETED` alone
does not establish Loom success, and a successful `scancel` only acknowledges a
request; it does not prove execution has stopped. Ordinary terminal admission
waiting includes the required result settlement and provider release. Guarded
recovery can intentionally retain capacity when safe release has not been
established. See the shared [cancellation and settlement contract](../../../docs/features/queue.md#status-and-cancellation).

This journey retains its explicit Slurm preparation path. The composed-run
`prepare_managed_run()` helper currently excludes Slurm profiles. The fake
scheduler provides deterministic lifecycle evidence without claiming real
cluster acceptance coverage.

## Variants

Use the remote journey for a resident agent or the local journey for embedded
execution.
