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
`prepare_managed_local_run` for separate `cancelled-example` and `starter-run` runs. Preparation persists the normal
run evidence and embedded authority, but never starts the daemon or submits
work. Repeating preparation is an exact no-write replay; change the run name
after a partial or changed preparation. Existing evidence is preserved for inspection.

## Public Python Surface

```python
from loom.queue import prepare_managed_local_run

receipt = prepare_managed_local_run(
    "coordinator-service.yaml", "pipeline.yaml", "starter-run"
)
```

It starts the foreground service with `loom queue daemon-serve` and runs
`pipeline-cancel.yaml` first. Its `StopEarlyStage` requests controlled cancellation:

```python
context.stop_early("This example intentionally cancels the run.")
```

This cancels the run. The runner waits for the admission to report `CANCELLED`,
then uses `loom inspect-run --endpoint` to check the authority run and stopping
stage are also `CANCELLED`. The dependent stage never starts or writes its output.
Never-ready stages do not need an execution attempt to become cancelled.

For ordinary completion and cancellation, terminal admission waiting includes
required result settlement and provider release. The local agent has one CPU
slot, and every stage requests that slot. Running the original successful
pipeline immediately afterward demonstrates that cancelled work has released
usable capacity. Its report still contains `consumed {'value': 42}`.

Finally the runner stops and restarts the same service roots to show stable
coordinator identity, a new epoch, and retained terminal admission state. All
observed service and worker processes must exit at final cleanup. This restart
happens after the work settles. If local work is still running during startup,
the coordinator joins that retained work before its normal management service
becomes available; it does not advertise capacity early.

See the shared [cancellation and settlement contract](../../../docs/features/queue.md#status-and-cancellation)
for the guarded recovery exception that can intentionally retain capacity.

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
