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
uv sync --locked --no-dev --extra config
. .venv/bin/activate
# Alternatively, using pip from a Python 3.12 virtualenv:
# python3.12 -m venv .venv
# . .venv/bin/activate
# python -m pip install 'weave @ git+https://github.com/samcantrill/weave.git@388377b61cffbb225057082365f03cb0738996fd'
# python -m pip install -e '.[config]'
```

Return to the copied example directory with that environment activated. The
`LOOM_PROJECT_ROOT` value in `agent.env` is this directory (containing `stages.py`),
while `LOOM_PYTHON` is the environment's absolute `.venv/bin/python` path. The env
files are inputs to Loom's loader; they are not shell scripts to source.

Run the lifecycle runner using the role files you just edited:

```sh
python run_managed_local_basic.py --coordinator-config coordinator.yaml --env-file coordinator.env
```

The runner uses those files without rewriting them, checks the selected
installation, and derives its software descriptor. For an automatic disposable
demo, omit both flags: it copies all four templates and fills in a fresh root
and the current Python for you. It initializes
once with `loom queue daemon-init` and calls `prepare_managed_local_run` for separate
`cancelled-example` and `starter-run` runs. Preparation persists the normal
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
copied project and its installed Python environment. The actual role files are
ignored by Git. It is not a remote-agent,
TLS, SLURM, content-relay, or process-manager installation example. For those
advanced routes, see `managed-remote-operations` and
`managed-ready-stage-slurm`.

To practice each operation separately, use fresh roots in your env files
instead of roots already initialized by the runner. Stay in the copied project
with the selected environment activated in every terminal. These commands use
the same role files:

```sh
loom queue daemon-check coordinator.yaml --env-file coordinator.env
loom queue daemon-init coordinator.yaml --env-file coordinator.env
# Use the LOOM_DEPLOYMENT_ROOT value in coordinator.env.
LOOM_ENDPOINT=/secure/loom/managed-local/deployment/coordinator/daemon.sock
python - <<'PY'
from loom.queue import prepare_managed_local_run

receipt = prepare_managed_local_run(
    "coordinator.yaml", "pipeline.yaml", "starter-run", env_file="coordinator.env"
)
print(receipt.run_uri)
PY
# Set RUN_URI to the printed value.
loom queue daemon-check coordinator.yaml --env-file coordinator.env --probe-io
```

In terminal A, leave the service running in the foreground:

```sh
loom queue daemon-serve coordinator.yaml --env-file coordinator.env
```

In terminal B, set `LOOM_ENDPOINT` and `RUN_URI` as above, then:

```sh
loom queue daemon-submit --endpoint "$LOOM_ENDPOINT" starter-run "$RUN_URI"
loom queue daemon-status --endpoint "$LOOM_ENDPOINT"
loom queue daemon-wait --endpoint "$LOOM_ENDPOINT" starter-run --timeout 15
loom inspect-run "$RUN_URI" --endpoint "$LOOM_ENDPOINT"
# Stop the service and repeat daemon-serve with the same protected inputs to restart.
```

For cancellation practice, issue `loom queue daemon-cancel --endpoint
"$LOOM_ENDPOINT" starter-run` after submitting and before waiting. This tiny job
may finish first; an already terminal run stays terminal. A cancellation request
is not proof that its worker stopped or that capacity is free. Wait and inspect
the resulting state. Stop terminal A with Ctrl-C, then run the same serve command
to practice restarting with retained state.

The IO probe creates and removes a small file under the configured execution
roots. A passing result qualifies that test directory's operation, not another
filesystem. The CPU example declares one CPU and zero GPUs; readiness reports
declared capacity separately from hardware observations.

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
