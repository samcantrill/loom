# Managed Remote Operations

## Workflow

Copy the coordinator and outbound-agent templates, then set each machine's
protected environment file. The real YAML and `.env` files are ignored by Git:

```sh
cp coordinator.yaml.example coordinator.yaml
cp coordinator.env.example coordinator.env
cp agent.yaml.example agent.yaml
cp agent.env.example agent.env
chmod 600 coordinator.yaml coordinator.env agent.yaml agent.env
```

Run the complete local demonstration from the repository root:

```sh
uv run python examples/operations/managed-remote-operations/run_managed_remote_operations.py
```

The script generates a one-use CA and server/agent certificates, copies
owner-protected schema-v3 role templates and explicit environment files, checks
the selected agent installation, then records its observed portable descriptor
in the copied coordinator input's `remote_profiles`.
It then initializes both role roots and starts the
real `daemon-serve` and `agent-serve` commands. It discovers the authenticated
agent with bounded list/detail commands, copies the returned session and config
revision fences into guarded drain/resume requests, and reads each durable
operation through detail and wait.

The coordinator has `local_agent: null`; this journey uses the separate outbound
agent. Its selected Python must already contain Loom from an existing uv or pip
installation. No environment is created or installed by the check or either
service. The observed descriptor is the coordinator's compatibility evidence;
do not author project, environment, executor, VRAM, or GPU-fingerprint
placeholders into the shared template.

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

Use the same explicit files for role lifecycle commands. `daemon-check` and
`agent-check` inspect readiness without initialization; the optional IO and GPU
probes have their own stated lifecycle and a skipped or deferred probe does not
qualify hardware.

```sh
loom queue agent-check agent.yaml --env-file agent.env
loom queue daemon-check coordinator.yaml --env-file coordinator.env
loom queue daemon-init coordinator.yaml --env-file coordinator.env
loom queue agent-init agent.yaml --env-file agent.env
loom queue daemon-serve coordinator.yaml --env-file coordinator.env
loom queue agent-serve agent.yaml --env-file agent.env
```

## Variants

Use the embedded lifecycle for one machine, or the SLURM journey for an
explicit ready-stage route.


Optional GPU qualification is a maintenance operation. After initializing a GPU
agent with a declared Torch runtime, and before starting its owning service, run
`loom queue agent-check agent.yaml --probe-gpu`.
Use the role files produced or copied for your deployment. A running or retained
agent defers the probe; only a `resources.gpu_compute` PASS proves computation and
cleanup. The existing agent journal retains any uncertain claim across restart.
The configured NVIDIA occupancy check defers an externally busy GPU and reports
failed qualification when availability cannot be established. Other selected
devices can still be tested; a later free observation never clears an uncertain claim.
The CPU journey does not provide physical GPU evidence. See the
[GPU qualification lifecycle](../../../docs/features/queue.md#optional-gpu-compute-qualification).
