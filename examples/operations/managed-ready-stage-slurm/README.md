# Managed Ready-Stage SLURM

## Workflow

Run the deterministic journey from the repository root:

```sh
uv run python examples/operations/managed-ready-stage-slurm/run_managed_ready_stage_slurm.py
```

The script configures one explicit ready-stage SLURM profile and uses Loom's
fake command gateway and a fixture-only positive containment helper, so no
cluster is required. The assigned co-located agent owns the scheduler journal
and calls; the coordinator projects its acknowledged evidence. The first `sbatch` is rejected;
the journey observes the retained rejection and physical assignment release
without falsely turning that scheduler decision into run failure. It restarts
the daemon and proves that operation is retained without resubmission. A second
run registers through the bootstrap view, receives the input-ready grant/start
fence, then publishes output bytes and a manifest to the configured shared
result root. Its original submit agent ingests the result through the existing
authority finalizer. Cleanup follows the final acknowledgement; capability
revocation and execution containment remain separate release obligations.
The fixture configures a finite 256 MiB retention quota, reserving 65 MiB per
attempt while retaining the 64 MiB aggregate artifact transfer ceiling.

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

This fixture keeps explicit preparation to expose the individual boundaries;
ordinary configured runs use the unified preparation/run path. The fake scheduler
provides deterministic lifecycle evidence without qualifying a real submit host,
shared filesystem, installed worker or container runtime. The compute-exit/outage
regression and separate site qualification requirements are described in the
[Slurm feature contract](../../../docs/features/slurm.md#durable-ready-stage-results).

## Variants

Use the remote journey for a resident agent or the local journey for embedded
execution.
