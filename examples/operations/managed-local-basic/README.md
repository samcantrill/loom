# Managed Local Basic

## Workflow

Run the deterministic embedded lifecycle:

```sh
uv run python examples/operations/managed-local-basic/run_managed_local_basic.py
```

It creates fresh roots, submits one dependency-ordered run, inspects bounded
admission list/detail views, waits for success, and stops the socket server and
supervisor through their supported paths. It then reopens the same roots to
prove the coordinator identity and completed admission survive restart while
the process epoch changes. The script fails if any worker or service process is
left alive.

## Public Python Surface

The journey deliberately mixes both supported operator styles:

```python
LocalDaemon.initialize(config)
daemon = LocalDaemon(config)
daemon.start()
server = LocalDaemonSocketServer(daemon, config.endpoint)
server.start()

client = daemon.client_view(
    LocalDaemonPrincipal("example-client", LocalDaemonRole.CLIENT)
)
status = client.status()
```

```sh
loom queue daemon-submit --endpoint DAEMON_SOCKET example-run RUN_URI
loom queue daemon-admissions --endpoint DAEMON_SOCKET --limit 10
loom queue daemon-admission --endpoint DAEMON_SOCKET ADMISSION_ID
loom queue daemon-wait --endpoint DAEMON_SOCKET example-run --timeout 15
```

Project setup uses the public managed-runtime preparation and embedded-authority
initializer. It never constructs the daemon's private execution owner or reads
its SQLite tables directly.

## Variants

Use `managed-remote-operations` for authenticated remote discovery and
controls, or `managed-ready-stage-slurm` for the explicit ready-stage route.
