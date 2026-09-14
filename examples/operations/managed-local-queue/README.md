# Managed Local Daemon

This example prepares a normal persisted Loom run through
`prepare_managed_local_run()` and embeds the supported single-machine daemon. The client submits only a queue identity and run URI.
The daemon reloads the plan, resolves dependency-ready stages, reserves local
CPU capacity, and runs the existing assignment saga.

```sh
uv run python examples/operations/managed-local-queue/run_managed_local_queue.py
```

The Python example remains useful for embedding and tests. Production role
processes use the supported protected config surface shown by
[`coordinator-service.yaml`](coordinator-service.yaml) and
[`outbound-agent-service.yaml`](outbound-agent-service.yaml):

```sh
chmod 600 examples/operations/managed-local-queue/*-service.yaml
loom queue daemon-init examples/operations/managed-local-queue/coordinator-service.yaml
loom queue agent-init examples/operations/managed-local-queue/outbound-agent-service.yaml

loom queue daemon-serve examples/operations/managed-local-queue/coordinator-service.yaml
loom queue agent-serve examples/operations/managed-local-queue/outbound-agent-service.yaml
```

Replace the illustrative TLS files and certificate fingerprint first. The
coordinator and agent documents deliberately repeat the same remote resident
profile identity; a mismatch makes the offer ineligible. The coordinator's
policy maps the verified client certificate to the site-owned logical agent ID,
pools, and capabilities. The agent cannot grant itself any of those values.
Paths are resolved relative to each config file.
The resident `python_executable` entry is made absolute without resolving its
final symlink, because invoking a virtual-environment launcher by that entry
path is what selects the configured environment.

## Public Python Surface

The example uses the public preparation helper and local-daemon types from
`loom.queue`. Its runner generates protected embedded-local role configuration
for fresh temporary directories. Loading that configuration checks the selected
Python and project source and derives the resident software descriptor. The
same role configuration controls both preparation and daemon setup.

`pipeline.yaml` declares the two project-owned stages. Preparation owns the
plan, configuration provenance, runtime record, and embedded authority setup.
Repeating identical preparation returns the same receipt without rewriting the
run. A partial or changed preparation conflicts and preserves existing evidence;
use a fresh run name for changed inputs. Preparation does not submit work.

A same-host managed-local assignment preserves project-authored stage config,
including local filesystem paths that the resident worker can resolve on that
host. This does not make those values remotely portable: remote-agent delivery
continues to reject path- or URI-bearing fingerprint, runtime, and worker
metadata and uses its protected agent-local paths and bounded artifact relay.

The important public flow is:

```python
from loom.queue import (
    LocalDaemon, LocalDaemonAdmissionRequest,
    LocalDaemonPrincipal, LocalDaemonRole, prepare_managed_local_run,
)
from loom.queue.deployment import load_coordinator_service_config

config = load_coordinator_service_config(coordinator_config).daemon
LocalDaemon.initialize_deployment(config)  # fresh deployment bundle only
receipt = prepare_managed_local_run(
    coordinator_config, pipeline_config, "embedded-example"
)
daemon = LocalDaemon(config)
daemon.start()
try:
    client = daemon.client_view(
        LocalDaemonPrincipal("local-client", LocalDaemonRole.CLIENT)
    )
    client.submit(LocalDaemonAdmissionRequest("queue-1", receipt.run_uri))
    result = client.wait("queue-1", timeout_seconds=15)
finally:
    daemon.stop()
```

By default, the runner creates a fresh directory below the system temporary
directory, keeping Unix socket paths short. Set `LOOM_EXAMPLE_OUTPUT_ROOT` to
choose another short output path.

The runner checks identical preparation replay, terminal success, and the final
report text `consumed {'value': 42}`. The illustrative TLS role files above remain
a separate deployment example; the embedding runner generates its own
embedded-local role files and needs no TLS credentials.

Initialization creates the coordinator execution store and local-agent journal
alongside the private control roots and independent worker supervisor. Use the
same roots and exact resident profile after stopping and restarting the daemon.
If a worker is still running, `daemon.start()` waits for that same supervised
process and replays its result before the daemon becomes available; it never
starts a replacement worker or advertises that capacity early.

These stores are retained owner truth: a missing or unreadable expected store
makes start fail closed, and a live loss degrades status and prevents new
scheduling work. Status joins owner snapshots rather than inferring health from
empty collections; each scheduling, assignment, and agent axis reports its
owner, aggregate state, revision, observation time, and freshness.

There is no compatibility adapter for `loom.queue.managed_local`, its
whole-run requests, or its old roots. Existing state is rejected without being
read, changed, migrated, cancelled, or deleted. Delegated whole-run Slurm is a
separate owner and is unchanged.

## Deployment Choice

Persistent managed agents and ready-stage SLURM require the coordinator on a
site-permitted stable host. A ready-stage bootstrap must reach its authenticated
endpoint while active. The foreground commands do not require that host to be
an HPC login node. Sites that prohibit persistent services there can use an
allowed reachable service host, or retain the separate service-less historical
whole-run queue SLURM, single-job, and `afterok` modes. Those whole-run owners do
not become Stage 29 managed-stage scheduling merely by using the same project.
