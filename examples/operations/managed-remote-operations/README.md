# Managed Remote Operations

## Workflow

Run the complete local demonstration from the repository root:

```sh
uv run python examples/operations/managed-remote-operations/run_managed_remote_operations.py
```

The script generates a one-use CA and server/agent certificates, writes
owner-protected schema-v2 configs, initializes both role roots, and starts the
real `daemon-serve` and `agent-serve` commands. It discovers the authenticated
agent with bounded list/detail commands, copies the returned session and config
revision fences into guarded drain/resume requests, and reads each durable
operation through detail and wait.

The generated credentials are for this localhost journey only. The example
stops both services with their supported interrupt path and fails if either
service or any supervised child remains alive.

The central discover-then-control flow is:

```sh
loom queue daemon-agents --endpoint DAEMON_SOCKET --limit 10
loom queue daemon-agent --endpoint DAEMON_SOCKET machine-B
loom queue daemon-agent-drain \
  --endpoint DAEMON_SOCKET --operation-id maintenance-1 \
  --agent-id machine-B --session-id SESSION --config-revision CONFIG_REVISION \
  --pool default --reason maintenance
loom queue daemon-operation-wait \
  --endpoint DAEMON_SOCKET maintenance-1 --timeout 15
```

## Variants

Use the embedded lifecycle for one machine, or the SLURM journey for an
explicit ready-stage route.
