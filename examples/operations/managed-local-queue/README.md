# Managed Local Queue Status

This dependency-free example runs three short Python commands through a managed
local queue with two generic static slots. It prints the redacted pool status
while work is active, including slot labels and queue-relative log paths.

## Workflow

```sh
uv run python examples/operations/managed-local-queue/run_managed_local_queue.py
```

The configured active limit is controller-local; static-slot authority leases
are the exclusivity boundary. The output intentionally does not display command
arguments, environment bindings, fencing tokens, or provider-private data.

## Variants

Inspect a persisted queue configuration with the CLI using:

```sh
loom queue status queue.yaml --pool local-pool --format json
```
