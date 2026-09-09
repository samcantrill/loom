# Managed Local Basic

This directory is a copyable single-machine CPU dummy starter. Copy the four
role templates, set the machine values in the two `.env` files, and protect the
actual files before editing `stages.py` and `pipeline.yaml`:

```sh
cp coordinator.yaml.example coordinator.yaml
cp coordinator.env.example coordinator.env
cp agent.yaml.example agent.yaml
cp agent.env.example agent.env
chmod 600 coordinator.yaml coordinator.env agent.yaml agent.env
```

`LOOM_PYTHON` must name an already-installed uv or pip environment that contains
Loom and this copied project. Loom does not create an environment, run `uv sync`,
install packages, or pull source. Preserve `.venv/bin/python` when that is the
selected interpreter; resolving it can select the wrong environment.

For a project checkout at `/work/loom`, create that selected environment before
setting `LOOM_PYTHON`:

```sh
# Choose one installation style; both install Loom into the selected environment.
cd /work/loom
uv venv .venv
uv pip install -e .
# Or: python3.12 -m venv .venv && .venv/bin/python -m pip install -e .
```

Run the lifecycle runner from the copied directory:

```sh
python run_managed_local_basic.py
```

The runner copies the maintained schema-v3 coordinator and referenced local-agent
templates into a fresh output root, writes protected machine env files, checks
the selected installation, and derives its software descriptor. It initializes
once with `loom queue daemon-init` and calls `prepare_managed_local_run` for
`starter-run`. Preparation persists the normal
run evidence and embedded authority, but never starts the daemon or submits
work. Repeating preparation is an exact no-write replay; change the run name
after a partial or changed preparation.

## Public Python Surface

```python
from loom.queue import prepare_managed_local_run

receipt = prepare_managed_local_run(
    "coordinator.yaml", "pipeline.yaml", "starter-run", env_file="coordinator.env"
)
```

It then starts the foreground service with `loom queue daemon-serve`, submits
the run, waits for terminal success, observes it through `loom inspect-run
--endpoint`, and reads the known local report file directly. Finally it stops
and restarts the same service roots to show stable coordinator identity, a new
epoch, and retained terminal admission state. The runner checks that its
foreground service processes have exited.

The generated protected config deliberately has mode `0600`; it names the
copied project and its installed Python environment. The actual role files are
ignored by Git. It is not a remote-agent,
TLS, SLURM, content-relay, or process-manager installation example. For those
advanced routes, see `managed-remote-operations` and
`managed-ready-stage-slurm`.

For an operator-run lifecycle, use the same explicit inputs for every command:

```sh
loom queue daemon-check coordinator.yaml --env-file coordinator.env
loom queue daemon-init coordinator.yaml --env-file coordinator.env
# Use the LOOM_DEPLOYMENT_ROOT value in coordinator.env.
LOOM_ENDPOINT=/secure/loom/managed-local/deployment/coordinator/daemon.sock
"$LOOM_PYTHON" - <<'PY'
from loom.queue import prepare_managed_local_run

receipt = prepare_managed_local_run(
    "coordinator.yaml", "pipeline.yaml", "starter-run", env_file="coordinator.env"
)
print(receipt.run_uri)
PY
# Set RUN_URI to the printed value, then serve in a separate terminal.
loom queue daemon-check coordinator.yaml --env-file coordinator.env --probe-io
loom queue daemon-serve coordinator.yaml --env-file coordinator.env
loom queue daemon-submit --endpoint "$LOOM_ENDPOINT" starter-run "$RUN_URI"
loom queue daemon-status --endpoint "$LOOM_ENDPOINT"
loom queue daemon-wait --endpoint "$LOOM_ENDPOINT" starter-run --timeout 15
loom inspect-run "$RUN_URI" --endpoint "$LOOM_ENDPOINT"
loom queue daemon-cancel --endpoint "$LOOM_ENDPOINT" starter-run
# Stop the service and repeat daemon-serve with the same protected inputs to restart.
```


Optional GPU qualification is a maintenance operation. After initializing a GPU
agent with a declared Torch runtime, and before starting its owning service, run
`loom queue daemon-check coordinator.yaml --env-file coordinator.env --probe-gpu`.
Use the role files produced or copied for your deployment. A running or retained
agent defers the probe; only a `resources.gpu_compute` PASS proves computation and
cleanup. The existing agent journal retains any uncertain claim across restart.
The configured NVIDIA occupancy check defers an externally busy GPU and reports
failed qualification when availability cannot be established. Other selected
devices can still be tested; a later free observation never clears an uncertain claim.
The CPU journey does not provide physical GPU evidence. See the
[GPU qualification lifecycle](../../../docs/features/queue.md#optional-gpu-compute-qualification).
