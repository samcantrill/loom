# Managed Local Basic

This directory is a copyable single-machine starter. Edit `stages.py` and
`pipeline.yaml`, then run the lifecycle runner from the copied directory:

```sh
python run_managed_local_basic.py
```

The runner writes one protected local-only coordinator configuration for its
fresh output root, initializes it once with `loom queue daemon-init`, and calls
`prepare_managed_local_run` for `starter-run`. Preparation persists the normal
run evidence and embedded authority, but never starts the daemon or submits
work. Repeating preparation is an exact no-write replay; change the run name
after a partial or changed preparation.

## Public Python Surface

```python
from loom.queue import prepare_managed_local_run

receipt = prepare_managed_local_run(
    "coordinator-service.yaml", "pipeline.yaml", "starter-run"
)
```

It then starts the foreground service with `loom queue daemon-serve`, submits
the run, waits for terminal success, observes it through `loom inspect-run
--endpoint`, and reads the known local report file directly. Finally it stops
and restarts the same service roots to show stable coordinator identity, a new
epoch, and retained terminal admission state. The runner checks that its
foreground service processes have exited.

The generated protected config deliberately has mode `0600`; it names the
copied project and its installed Python environment. It is not a remote-agent,
TLS, SLURM, content-relay, or process-manager installation example. For those
advanced routes, see `managed-remote-operations` and
`managed-ready-stage-slurm`.
