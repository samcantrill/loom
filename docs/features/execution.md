# Native execution

Loom executes runs through one coordinator and installed agent workers. The
coordinator owns durable admission, dependency readiness, attempts, retries,
output acceptance and cancellation. Agents own process containment, local
capacity, assignment workspaces and retained results. Authored stage code runs
only after a fenced native start permit. The client may disconnect without
cancelling accepted work.

Use [`loom.run`, `loom.start_run` and `CoordinatorClient`](coordinator-client.md)
with an explicit [deployment and preparation selection](agent-preparation.md).
CLI, Python, sweeps and MCP share this owner. A run request carries source and
profile selection plus normalized options; installed deployment configuration
owns interpreters, roots, credentials, resource providers and launch policy.

## Lifecycle and deployment choices

| Deployment | Service lifetime | Work ownership |
| --- | --- | --- |
| Cold local | The run session starts and settles its configured coordinator and local agent | One native run admission; cleanup is reported separately |
| Persistent local | A site process manager retains the coordinator and local agent | Several admissions share the same authority, scheduler and capacity |
| Connected fleet | Persistent coordinator plus separately managed authenticated agents | Offers, claims and permits select one installed eligible worker per attempt |
| Mixed workers and SLURM | Persistent coordinator with connected workers and explicitly configured SLURM profiles | One readiness owner; the selected route owns execution and settlement |

Detach closes the observation session. Reconnect with the same request and
operation identities to recover acceptance after a lost response. Exact replay
returns the retained admission; changed intent conflicts. Explicit cancellation
is an asynchronous operation whose result is separate from process settlement.
Do not infer that cancelling a client or closing its socket stopped a worker.

Two runs sharing a persistent deployment retain distinct admissions, attempts,
artifacts and cancellation controls. Capacity is shared at the agent owner.
Restart the coordinator using the same protected root and retained identity;
do not erase state to recover a run. An ambiguous process, grant, scheduler
submission or authority result remains blocked until its owner has evidence.

The planner determines RUN, REUSE, SKIP and blocked dependency decisions.
Execution preserves selectors, fingerprints, bindings, resource demand and
reliability policy. Accepted output commits name the exact attempt and fencing
identity. A local payload, worker success record or scheduler exit alone does
not make output reusable. Downstream work uses accepted predecessor commits.

The authored parallel failure policy defaults to `stop_on_first_failure`.
After a terminal stage failure, no new unrelated work starts, and already
accepted assignments settle before the run fails. `continue_independent`
allows unrelated branches to finish; descendants of a failed branch remain
blocked without invented attempts. An explicit retry retains its existing
attempt and output predecessor rules. These policies do not turn an ordinary
request replay into an implicit retry.

## Workers, artifacts and diagnostics

`execute_resident_stage_worker_request` is an internal execution-only worker
primitive. It returns stage outputs and failures without accepting authority
commits or becoming a run engine. `LocalExecutor` remains a stage invocation
primitive used by resident workers. Container command and containment helpers
serve installed native Docker/Apptainer profiles. There is no public direct
worker command, standalone pipeline runner or whole-run queue executor.

Artifact references retain producer, codec, checksum and fingerprint meaning.
Declared outputs are validated and transferred through the current native
artifact owner. Project workspace files remain in the retained assignment
workspace unless explicitly declared as outputs; they are not automatically
published as run artifacts.

`loom status`, artifact inspection and backend diagnostics read the existing
embedded per-run authority by default when present. An explicitly selected
service remains authoritative and its failure does not trigger local fallback.
Inspection never creates or mutates authority state. Historical evidence is
readable through its existing record/import owners.

`loom logs` reads a local projected log or the retained native worker log path.
Tail limits, paths-only output and unavailable content remain explicit. Recorded
paths do not provide remote log transport: content is available only when the
inspecting host can read that local path. Damaged optional projection records
must not conceal valid authority status. Agent assignment retention determines
how long those paths remain available.

Lifecycle observers are selected once in protected coordinator configuration.
See [reliability](reliability.md) for committed event identity, retained observer
failures, factory trust, synchronous callback latency and best-effort crash
tradeoffs. Status reads do not replay callbacks.

## Incompatible version cutover

Settle old-version work before switching versions or roots. Preserve its
records, artifacts and audit evidence. The new coordinator does not resume an
old runner, whole-run queue item, offline executor or generated SLURM
continuation. There is no live migration, compatibility shim, root reset or
artifact deletion procedure. Read-only historical records and imports remain
available independently of execution.

## Qualification

Synthetic native journeys exercise admission, replay, branching, cancellation,
restart and retained output/observer behavior. They do not qualify a physical
fleet, container installation or SLURM site. Follow the deployment and SLURM
qualification records for site prerequisites and unavailable cases. Allocation-
native worker deployment remains deferred; do not advertise it as delivered.
