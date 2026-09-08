# Managed Local Basic

This directory is a copyable single-machine starter. Edit `stages.py` and
`pipeline.yaml`, then run the lifecycle runner from the copied directory:

```sh
python run_managed_local_basic.py
```

The runner writes protected schema-v3 coordinator and referenced local-agent
configurations for its fresh output root. The agent selects the runner's installed
Python and copied project directory; role loading checks that installation and
derives its software descriptor. It initializes once with `loom queue daemon-init` and calls
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


Optional GPU qualification is a maintenance operation. After initializing a GPU
agent with a declared Torch runtime, and before starting its owning service, run
`loom queue daemon-check coordinator-service.yaml --probe-gpu`.
Use the role files produced or copied for your deployment. A running or retained
agent defers the probe; only a `resources.gpu_compute` PASS proves computation and
cleanup. The existing agent journal retains any uncertain claim across restart.
The configured NVIDIA occupancy check defers an externally busy GPU and reports
failed qualification when availability cannot be established. Other selected
devices can still be tested; a later free observation never clears an uncertain claim.
The CPU journey does not provide physical GPU evidence. See the
[GPU qualification lifecycle](../../../docs/features/queue.md#optional-gpu-compute-qualification).
