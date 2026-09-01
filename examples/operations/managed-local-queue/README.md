# Managed Local Daemon

This example creates a normal persisted Loom plan and starts the supported
single-machine daemon. The client submits only a queue identity and run URI.
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

The example uses Loom's public local-daemon types from `loom.queue`. Project
code persists the plan, resolved config, and exact managed-local runtime record
first; daemon clients then submit only the queue item identity and `run_uri`.
`runtime.json` is safe observability metadata and is not executable input.

A same-host managed-local assignment preserves project-authored stage config,
including local filesystem paths that the resident worker can resolve on that
host. This does not make those values remotely portable: remote-agent delivery
continues to reject path- or URI-bearing fingerprint, runtime, and worker
metadata and uses its protected agent-local paths and bounded artifact relay.

The important public flow is:

```python
config = LocalDaemonConfig(
    coordinator_root=Path(".loom/coordinator"),
    agent_root=Path(".loom/agent"),
    run_store_root=Path("runs"),
    resident_worker_launch_profile=ResidentWorkerLaunchProfile(
        project_root=Path.cwd(),
        python_executable=Path(sys.executable),
        descriptor={
            "profile_id": "local-default",
            "revision": "v1",
            "project_fingerprint": "my-project",
            "environment_fingerprint": "my-environment",
            "executor_fingerprint": "local",
        },
    ),
)
LocalDaemon.initialize(config)  # fresh roots only
daemon = LocalDaemon(config)
daemon.start()

client = daemon.client_view(
    LocalDaemonPrincipal("local-client", LocalDaemonRole.CLIENT)
)
client.submit(LocalDaemonAdmissionRequest("queue-1", run_uri))
result = client.wait("queue-1", timeout_seconds=120)
```

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
