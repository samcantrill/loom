# Managed Local Daemon

This example creates a normal persisted Loom plan and starts the supported
single-machine daemon. The client submits only a queue identity and run URI.
The daemon reloads the plan, resolves dependency-ready stages, reserves local
CPU capacity, and runs the existing assignment saga.

```sh
uv run python examples/operations/managed-local-queue/run_managed_local_queue.py
```

## Public Python Surface

The example uses Loom's public local-daemon types from `loom.queue`. Project
code persists the plan, resolved config, and exact managed-local runtime record
first; daemon clients then submit only the queue item identity and `run_uri`.
`runtime.json` is safe observability metadata and is not executable input.

The important public flow is:

```python
config = LocalDaemonConfig(
    coordinator_root=Path(".loom/coordinator"),
    agent_root=Path(".loom/agent"),
    run_store_root=Path("runs"),
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

There is no compatibility adapter for `loom.queue.managed_local`, its
whole-run requests, or its old roots. Existing state is rejected without being
read, changed, migrated, cancelled, or deleted. Delegated whole-run Slurm is a
separate owner and is unchanged.
