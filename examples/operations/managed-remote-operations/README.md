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

Install Loom and the copied project before setting `LOOM_PYTHON`; either
environment style is supported and Loom never creates or updates it while
checking or running a stage:

```sh
# From the Loom checkout (not this example subdirectory), choose one style.
uv sync --locked --no-dev --extra config
. .venv/bin/activate
# Alternatively, using pip from a Python 3.12 virtualenv:
# python3.12 -m venv .venv
# . .venv/bin/activate
# python -m pip install 'weave @ git+https://github.com/samcantrill/weave.git@388377b61cffbb225057082365f03cb0738996fd'
# python -m pip install -e '.[config]'
```

The automatic demo below creates a fresh temporary deployment; it does not use
previously edited machine files. It runs a CPU stage, verifies its relayed JSON report on the
coordinator, exercises authenticated drain/resume, restarts the agent during supervised work, and finally shuts
down both services. It needs OpenSSL for disposable localhost certificates.
Run it from the repository root:

```sh
uv run --locked --extra config python examples/operations/managed-remote-operations/run_managed_remote_operations.py
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

For the manual route, return to this example directory with the selected
environment activated. Set `LOOM_PROJECT_ROOT` to the directory containing this
example's `stages.py`; use the same source and compatible installation on the
agent machine. The coordinator needs Loom's configuration extra for preparation,
but no CPU/GPU execution capacity. Supply existing TLS certificates/keys for your
hosts and protect their files. `LOOM_AGENT_HOST=localhost` listens only on the
coordinator machine; set an appropriate bind address and matching trusted server
URL/certificate for a separate host. No second physical host is qualified by the
localhost demo.

Enroll observations before starting either service. `agent-check` reports the complete `execution.identity` descriptor;
copy that exact five-field object into the protected coordinator YAML's
`remote_profiles` list. Put the SHA-256 fingerprint of the protected agent
certificate in its `agent_server.credential_fingerprints` mapping with value
`remote-agent-certificate`. These are observed compatibility and TLS identity
facts, not placeholders to author into the shared templates. To print the exact
lowercase SHA-256 key for an existing PEM certificate:

```sh
python - /secure/loom/tls/agent.crt <<'PY'
import hashlib
from pathlib import Path
import ssl
import sys

print(hashlib.sha256(ssl.PEM_cert_to_DER_cert(Path(sys.argv[1]).read_text())).hexdigest())
PY
```

Use `loom queue agent-check agent.yaml --env-file agent.env --format json` for the full
observed descriptor in the `execution.identity` check. Edit only the protected
coordinator copy to enroll that descriptor and certificate; shared templates
retain empty observation slots.

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
loom queue agent-check agent.yaml --env-file agent.env --probe-io
```

Run each foreground service in its own terminal (and on its own host for a
network deployment), using that role's protected files:

```sh
# Coordinator terminal
loom queue daemon-serve coordinator.yaml --env-file coordinator.env
# Separate agent terminal
loom queue agent-serve agent.yaml --env-file agent.env
```

In another coordinator terminal with the same environment activated, and after
the authenticated agent is available, prepare the CPU dummy through the
existing public preparation owner, then submit, inspect, wait, and cancel with
the same explicit role inputs. Replace `RUN_URI` with the receipt's value:

```sh
# Use the LOOM_DEPLOYMENT_ROOT value in coordinator.env.
LOOM_ENDPOINT=/secure/loom/remote-coordinator/deployment/coordinator/daemon.sock
python - <<'PY'
from loom.pipeline.orchestration import ExecutionRequirement
from loom.queue import prepare_managed_run
from loom.queue.deployment import load_coordinator_service_config
from weave import compose_config

service = load_coordinator_service_config("coordinator.yaml", env_file="coordinator.env")
profile = service.daemon.remote_profiles[0]
receipt = prepare_managed_run(
    service,
    compose_config("pipeline.yaml"),
    "remote-lifecycle",
    execution_requirements={
        "work": ExecutionRequirement(
            profile.project_fingerprint,
            profile.environment_fingerprint,
            profile.executor_fingerprint,
        )
    },
)
print(receipt.run_uri)
PY
loom queue daemon-submit --endpoint "$LOOM_ENDPOINT" remote-lifecycle "$RUN_URI"
loom queue daemon-status --endpoint "$LOOM_ENDPOINT"
loom queue daemon-wait --endpoint "$LOOM_ENDPOINT" remote-lifecycle --timeout 40
loom inspect-run "$RUN_URI" --endpoint "$LOOM_ENDPOINT"
# Stop the two services and use the same daemon-serve/agent-serve commands to restart.
```

The JSON report is relayed to the coordinator and contains `value: 42`.
For cancellation, issue `loom queue daemon-cancel --endpoint "$LOOM_ENDPOINT"
remote-lifecycle` before waiting. A fast job may already have finished; a request
alone does not establish process termination or resource release. Use wait and
inspection, then Ctrl-C each service and restart with the same roots.

The optional IO probe qualifies only the selected temporary execution roots.
Unrun GPU checks and deferred busy-device probes provide no compute evidence.

## Active-work restart

After guarded resume, the runner submits the prepared run. `WorkStage` simulates
20 seconds of bounded work before writing a JSON report. The duration is in
`pipeline.yaml`; it leaves time for foreground stop/restart. Readiness uses
bounded public inspections rather than a fixed startup delay. The journey fails
if it misses the running stage and retained-work window.

Once `loom inspect-run` reports the stage and run as `RUNNING`, the runner sends
`SIGINT` to the foreground agent and confirms its exit. It checks that the same
attempt, assignment, and claim remain active, then starts `agent-serve` again
with the same configuration and persistent root.

Stopping the foreground application preserves supervised work, journals,
fences, and resource claims. It does not cancel the run or retire the agent
session. Startup can reconcile retained work before the agent advertises normal
availability, so the example waits for run completion directly after restart.

The final checks require success through the original attempt and assignment,
the relayed report value `42`, and assignment state `released`. Public
`daemon-admission` details supply attempt and claim identity. The current managed
`inspect-run` response reports stage states but can omit attempt numbers and
artifact locations. On this coordinator host, the runner reads the committed
snapshot through the configured `CoordinatorAuthorityStore.open_run` and loads
its artifact reference with `LocalArtifactStore.load`, which checks the checksum
and decodes the JSON. The report also
records the worker PID for final process cleanup checks. Dedicated supervisor
regressions cover unchanged worker process identity and duplicate-launch
prevention. See the shared [resident agent lifecycle](../../../docs/features/queue.md#cli-operation)
and [cancellation and settlement contract](../../../docs/features/queue.md#status-and-cancellation).

The artifact read uses the authority selected by that same service configuration:

```python
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore

authority = service.daemon.coordinator_authority_factory(receipt.run_uri)
snapshot = authority.open_run(receipt.run_uri)
(stage,) = snapshot.stages
(fact,) = stage.artifact_facts
artifacts = LocalArtifactStore(
    LocalRunStore(run_store_root).local_artifact_root(receipt.run_uri)
)
report = artifacts.load(fact.artifact, expected_type="json")
```

## Variants

Use the embedded lifecycle for one machine, or the SLURM journey for an
explicit ready-stage route.


Optional GPU qualification is a maintenance operation. After initializing a GPU
agent with a declared Torch runtime, and before starting its owning service, run
`loom queue agent-check agent.yaml --env-file agent.env --probe-gpu`.
Use the role files produced or copied for your deployment. A running or retained
agent defers the probe; only a `resources.gpu_compute` PASS proves computation and
cleanup. The existing agent journal retains any uncertain claim across restart.
The configured NVIDIA occupancy check defers an externally busy GPU and reports
failed qualification when availability cannot be established. Other selected
devices can still be tested; a later free observation never clears an uncertain claim.
The CPU journey does not provide physical GPU evidence. See the
[GPU qualification lifecycle](../../../docs/features/queue.md#optional-gpu-compute-qualification).
