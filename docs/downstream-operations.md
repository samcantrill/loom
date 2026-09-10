# Downstream Operations

This guide is the short operational path for a Loom stage author. It describes
the current public behavior; detailed contracts remain in the linked feature
specifications.

## Stage Outputs Are Explicit References

A stage receives declared input references and returns a mapping of its declared
output names to `ArtifactRef` values. Load an input through the context rather
than reaching into a store:

```python
records = context.load_input("records", expected_type="json")
```

Use `save_artifact()` when Loom should serialize a managed value with a codec.
Use `local_output_path()` and `register_local_artifact()` when project code
writes a file and then explicitly publishes it. Both paths return an
`ArtifactRef` that belongs in the returned mapping.

```python
from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline import StageContext


class BuildReportStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        records = context.load_input("records", expected_type="json")

        draft = context.local_workspace_path("drafts", "report.txt")
        draft.write_text(f"records: {len(records)}\n", encoding="utf-8")

        report_path = context.local_output_path("report", suffix=".txt")
        report_path.write_text(draft.read_text(encoding="utf-8"), encoding="utf-8")
        report = context.register_local_artifact(
            "report",
            report_path,
            artifact_type="text",
            codec_key="text.v1",
        )
        summary = context.save_artifact(
            "summary",
            {"record_count": len(records)},
            artifact_type="json",
            codec_key="json.v1",
        )
        return {"report": report, "summary": summary}
```

The output names, artifact types, codecs, and schema versions must match the
stage's declared output contract. `local_workspace_path()` is for intermediate
or work files: leaving a file there does not publish it as an output or
artifact. A project-owned log or checkpoint file is likewise durable only when
the stage explicitly registers it and returns its reference.

The local path helpers are intentionally unavailable when a context has no
local store paths. They are not a remote writer API. Project code owns the
meaning, schema, and compatibility policy of records, reports, checkpoints,
and log contents; Loom owns the reference and registration boundary.

See [artifact contracts](features/artifacts.md), [StageContext](features/pipeline.md),
and [execution context construction](features/execution.md) for full details.

## Logs Follow Their Owner

`loom logs RUN_URI STAGE` inspects Loom's ordinary stage stdout and stderr
streams. It does not discover arbitrary project files, queue-attempt logs, or
SLURM scheduler-wrapper logs.

| Execution path | Stdout/stderr and failure evidence | What to inspect |
| --- | --- | --- |
| Local executor, default | Python streams pass through to the current process; capture is off by default. A stage exception still has Loom traceback evidence. | Terminal/process output and failure evidence; stage streams may be unavailable. |
| Local executor, `capture_stdout_stderr=True` | Loom redirects Python `sys.stdout` and `sys.stderr` to its stage stream paths. Bounded parallel local execution rejects this mode. | `loom logs` for the stage streams and failure traceback evidence. This is not native file-descriptor capture. |
| Subprocess | The child worker writes stdout/stderr to the stage request paths; its result or failure retains those paths and traceback evidence when present. | `loom logs` and the recorded failure paths. |
| Docker or Apptainer | The container worker's stdout/stderr use the stage request paths and its result/failure keeps those paths. | `loom logs` and the recorded failure paths. Container runtime setup is outside this guide. |
| SLURM | The scheduler manifest can name wrapper stdout/stderr separately from Loom stage streams. | The SLURM manifest/status for wrapper paths; do not assume `loom logs` reads them. |
| Managed queue | Queue management owns per-attempt logs separately from a run's ordinary stage log path. | Queue attempt inspection for attempt logs; `loom logs` only for ordinary stage streams when available. |

A project `logging.FileHandler` writes to the path selected by project code. It
does not become an artifact and is not automatically a `loom logs` stream.
Handlers configured before an in-process local capture can retain their original
stream; handlers configured inside a captured process or stage normally follow
that process's Python streams. Do not rely on local Python redirection to
capture native file-descriptor writes.

The dependency-free [captured logs example](../examples/operations/captured-logs/README.md)
shows local stream capture, a registered file-backed output, and a separate
workspace file.

## Lifecycle Facts

Lifecycle events describe committed runtime facts when there is a corresponding
durable state change. In particular, a fresh preparation failure commits
`FAILED` before `run.preparation_failed` is observed. Opening an already
terminal run does not rewrite that terminal state.

The currently emitted names are:

```text
run.created              stage.planned
run.opened               stage.started
run.planned              stage.completed
run.started              stage.failed
run.completed            stage.cancelled
run.failed               stage.skipped
run.cancelled            stage.reused
run.interrupted          stage.stale
run.preparation_failed   stage.blocked
```

Explicit event sinks observe these records best-effort after persistence; they
are not a notification payload format. Stage 28 owns future generic filtering
and activation mechanics. Do not treat stream text, workspace files, or project
logs as audience-safe event or notification content.

## Boundaries And Later Work

This guide does not add queue selection, resource usage observation, resume
policy, notification delivery, runtime profiles, or new validation gates.
Those concerns remain with their owning roadmap stages: queue selection (Stage
25), GPU/resource setup (Stage 27), extension mechanics (Stage 28), and daemon
or agent work (Stage 29). The [roadmap](roadmap.md) is the cross-stage index.

## Protected Coordinator And Agent Roles

Persistent managed execution has explicit check, initialization, and foreground
role commands:

```bash
chmod 600 coordinator-service.yaml coordinator-service.env outbound-agent-service.yaml outbound-agent-service.env
loom queue daemon-check coordinator-service.yaml --env-file coordinator-service.env
loom queue daemon-init coordinator-service.yaml --env-file coordinator-service.env
loom queue daemon-serve coordinator-service.yaml --env-file coordinator-service.env
loom queue agent-check outbound-agent-service.yaml --env-file outbound-agent-service.env
loom queue agent-init outbound-agent-service.yaml --env-file outbound-agent-service.env
loom queue agent-serve outbound-agent-service.yaml --env-file outbound-agent-service.env
```

The check, initialization, and serving commands consume the same explicit,
owner-protected, schema-versioned YAML document and optional explicit dotenv
file. The dotenv file is parsed without shell execution or interpolation, and
its mapping is the only environment used to resolve that role's `oc.env`
expressions; ambient shell variables neither override it nor fill omissions.
Loom does not discover either role input, read a replacement from environment
variables, or infer roots, endpoints, the Python interpreter, resident profile
identity, capacity, or credentials. The old daemon root/profile flags are
rejected. Relative paths resolve from the config file, not the process working
directory. Explicit reload retains these selected inputs and revalidates them;
it does not watch for changes.

Coordinator and agent role documents use `schema_version: 3`. A coordinator
declares `local_agent: null` when all work will execute on outbound agents. It
needs no local project, worker Python, CPU/memory/GPU inventory, agent root, or
worker supervisor. It can accept prepared work and remain healthy while waiting
for an eligible authenticated agent.

To execute on the coordinator's host, replace that null with a protected agent
file reference:

```yaml
local_agent:
  config: ./agent.yaml
  env_file: ./agent.env  # Use null for a literal agent configuration.
```

The referenced document has `kind: loom.local-agent-service`, an `agent_root`,
and exactly one `resident_profiles` entry. Every profile still requires
`descriptor`, `project_root`, `python_executable`, `environment`, `cpu_capacity`,
`memory_capacity_bytes`, and `gpu_devices`. Without agent-level `resources`,
the profile capacity declarations must agree. An agent-level `resources` block
overrides those capacity fields for shared resource accounting; executable
profiles still choose the installed Python, project, environment, and software
descriptor. The shared block owns CPU/memory capacity and the GPU allowlist. It has
`cpu_capacity`, `memory_capacity_bytes`, and `gpu: {provider: nvidia, devices:
"none" | "0,2" | "0-7" | "GPU-..."}`. Empty, duplicate, overlapping,
reversed, mixed index/UUID, and unknown selections are rejected. `none` is
CPU-only and does not run NVIDIA discovery. NVIDIA selections resolve host
indices to UUIDs with model and physical VRAM observations; a changed index
resolution changes the active resource identity and requires explicit reload.
Profiles sharing an agent use this one provider domain, so they cannot advertise
or claim the same physical card twice. Resource checks bound CPU capacity by
process affinity and readable cgroup-v2 quotas, and memory by address-space,
host-memory and readable cgroup-v2 limits. Cgroup observation follows the process
membership and its ancestors under `/sys/fs/cgroup`; other mount layouts and
cgroup v1 are not observed. These are supported capacity bounds, not current
free resources or proof of every platform constraint. JSON output from
`agent-check` and `daemon-check` includes `effective_capacity` for the selected
agent resources. A `null` CPU or memory value means no supported bound was
available; a `null` whole object means no agent-level resources were selected.
Before `daemon-check`, `agent-check`, initialization, serving, or explicit
reload offers a resident profile, Loom runs the selected worker Python with the
same cwd and allowlisted environment used for workers. A profile may add a
finite `readiness` mapping with `imports`, `distributions`, `source_roots`, and
`timeout_seconds`; defaults verify the selected Python, import `loom`, and inspect
its installed distribution.
The probe does not install packages, build a project, inherit daemon secrets, create a
deployment, or claim a GPU. Its narrow identity includes the selected Python,
declared installation facts, and declared source contents. It excludes absolute
paths and unrelated files, while the private profile binding still prevents an
initialized deployment from silently moving to another executable or project.
Failures withhold only new offers and leave retained work with its original
supervisor and descriptor.
Optional `providers` contains the
configured provider composition. These worker settings no longer belong in the
coordinator's old `embedded_profile`/`embedded_agent` fields. Outbound documents
retain `kind: loom.outbound-agent-service`, their resident profile declarations,
and the required connection, registration, and TLS configuration. Local
composition requires no outbound TLS credentials.

The agent reference resolves relative to coordinator YAML; paths inside the
agent document resolve relative to agent YAML. Its explicit env file is composed
independently, so coordinator env values cannot silently supply missing agent
values. Explicit daemon reload rereads both selected role inputs. A missing or
invalid input rejects reload without replacing retained ownership.

`daemon-init` publishes one absent deployment directory containing the bound
`coordinator` root and, when selected, its embedded `agent` root, plus a
configuration fingerprint. For local composition, `agent_root` must name that
deployment's `agent` subdirectory. The coordinator owns this combined
initialization; do not separately initialize or serve an outbound agent over the
embedded root. With `local_agent: null`, no agent subdirectory is created.
`agent-init` independently publishes one absent outbound-agent root. Each
initializer constructs and validates a private sibling staging directory and
performs one final directory rename; an existing target is never overwritten.
Startup reopens only the complete bound role and rejects a different config.
Old role schemas and populated roots are rejected; there is no root migration
or in-place profile update. Settle existing work with its compatible runtime,
then explicitly initialize fresh roots for the new configuration.

For an embedded or outbound agent, the worker supervisor is a separate local
service and remains the process owner
when the daemon application stops. Restart the daemon with the same protected
config and exact profile. Startup stays unavailable while it joins any retained
worker, imports its result, releases its claims, and publishes a fresh capacity
observation. Loom will not launch a replacement process or reuse uncertain
capacity. If the supervisor continuity or retained bundle cannot be proved,
startup fails closed. An empty supervisor may restart after a host restart; a
supervisor that has accepted a launch cannot be reconstructed from an absent
process and requires explicit recovery.

Clean daemon shutdown stops the supervisor only when the coordinator, agent
journal and supervisor prove no retained work. A refused or unavailable proof
keeps the supervisor running and writes a warning with its original exception
chain to the daemon's local log; ordinary daemon locks are still released.
These private diagnostics can include local paths and native messages. Protect
the logs, retain the deployment, and investigate the stated owner failure rather
than force-releasing uncertain work. Status availability remains a boolean view;
it does not replace the detailed shutdown diagnostic.

Managed-local preparation separately requires an explicit exact execution
requirement for every stage: project, environment, and executor fingerprints.
It never derives those identities from an authored field, a daemon profile, an
agent profile, the current process, or one run-wide default. A resident offer
is eligible only when one named profile exactly matches the prepared stage;
the selected profile is retained with the delivery. Worker processes receive a
new allowlisted environment rather than the daemon's ambient environment.
