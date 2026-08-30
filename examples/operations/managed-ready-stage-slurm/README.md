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

## Variants

Use the remote journey for a resident agent or the local journey for embedded
execution.
