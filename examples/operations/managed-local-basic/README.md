# Managed Local Basic

## Workflow

Run the deterministic embedded lifecycle:

```sh
uv run python examples/operations/managed-local-basic/run_managed_local_basic.py
```

It creates fresh roots, submits one dependency-ordered run, observes its
terminal admission, and stops the supervisor through the normal daemon path.

## Public Python Surface

The journey uses `LocalDaemon`, `LocalDaemonAdmissionRequest`, and the typed
client view from `loom.queue`; it does not construct a private execution owner.

## Variants

Use `managed-remote-operations` for authenticated remote discovery and
controls, or `managed-ready-stage-slurm` for the explicit ready-stage route.
