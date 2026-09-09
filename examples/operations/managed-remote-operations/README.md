# Managed Remote Operations

## Workflow

Run the complete local demonstration from the repository root:

```sh
uv run python examples/operations/managed-remote-operations/run_managed_remote_operations.py
```

The script generates a one-use CA and server/agent certificates, writes
owner-protected schema-v3 configs, checks the selected agent installation and
copies its observed portable descriptor into the coordinator's `remote_profiles`.
It then initializes both role roots and starts the
real `daemon-serve` and `agent-serve` commands. It discovers the authenticated
agent with bounded list/detail commands, copies the returned session and config
revision fences into guarded drain/resume requests, and reads each durable
operation through detail and wait. It then submits real supervised work and
restarts the foreground agent while that work is running.

The coordinator has `local_agent: null`; this journey uses the separate outbound
agent. Its selected Python must already contain Loom. No environment is created
or installed by the check or either service.

The generated credentials are for this localhost journey only. The example
stops both services with their supported interrupt path and fails if either
observed service or worker remains alive after the run settles. The worker is
expected to survive the intermediate foreground stop.

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

## Public Python Surface

The runner prepares a composed pipeline with the descriptor returned by its
`agent-check` call. The checked installation includes this directory's `stages.py`:

```python
from weave import compose_config
from loom.queue import ExecutionRequirement, prepare_managed_run
from loom.queue.deployment import load_coordinator_service_config

requirement = ExecutionRequirement(
    descriptor["project_fingerprint"],
    descriptor["environment_fingerprint"],
    descriptor["executor_fingerprint"],
)
service = load_coordinator_service_config(coordinator_config)
receipt = prepare_managed_run(
    service,
    compose_config(pipeline_config),
    "remote-lifecycle",
    execution_requirements={"work": requirement},
)
```

Preparation records the run and exact worker requirements; it neither starts a
service nor discovers a live offer. Worker paths stay in the protected agent
configuration. The pipeline contains only the importable stage and portable
parameters.

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
`loom queue agent-check agent.yaml --probe-gpu`.
Use the role files produced or copied for your deployment. A running or retained
agent defers the probe; only a `resources.gpu_compute` PASS proves computation and
cleanup. The existing agent journal retains any uncertain claim across restart.
The configured NVIDIA occupancy check defers an externally busy GPU and reports
failed qualification when availability cannot be established. Other selected
devices can still be tested; a later free observation never clears an uncertain claim.
The CPU journey does not provide physical GPU evidence. See the
[GPU qualification lifecycle](../../../docs/features/queue.md#optional-gpu-compute-qualification).
