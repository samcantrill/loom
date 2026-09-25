# MCP coordinator tools and portable skills

The optional Loom MCP adapter lets Codex call the same coordinator API as Python
and the CLI. The coordinator owns admission, preparation, scheduling and durable
state. The adapter has no job database and does not route through a worker agent.

```text
Codex --stdio--> loom-mcp --native client--> coordinator
                                              |-- local worker, if configured
                                              `-- remote fleet agents
```

On the coordinator machine, connect through its Unix socket. From a laptop,
worker host or another machine, use protected authenticated HTTPS client settings.
Only connection settings change. A worker host's MCP client is independent of its
outbound worker session. Closing Codex or the adapter leaves accepted work running.

## Install and register

Install this checkout's optional client dependencies in a dedicated client
environment. Replace every sample path with your chosen absolute path:

```sh
uv venv --python 3.12 /absolute/path/to/client-env
uv pip install --python /absolute/path/to/client-env/bin/python '/absolute/path/to/loom[mcp]'
codex mcp add loom -- /absolute/path/to/client-env/bin/loom-mcp --deployment /absolute/path/to/deployment.json
```

The protected [deployment selection](../structure.md) selects one coordinator,
source/profile and optional configured local roles. Resolve its path from the
server cwd and its references relative to the file. A connection-only selection
uses protected [native HTTPS settings](coordinator-client.md) with an expected
coordinator identity. Local creation retains the native binding across restart.
All tools use that binding; calls cannot override deployment or connection.
Optional `expected_coordinator_id` must match the protected owner.

Construction and discovery never start services. `loom_run` explicitly ensures
configured local roles; prepare, query, submit, wait and cancel only connect and
report availability. The adapter neither provisions workers nor writes secrets.

Codex stores the equivalent server configuration:

```toml
[mcp_servers.loom]
command = "/absolute/path/to/client-env/bin/loom-mcp"
args = ["--deployment", "/absolute/path/to/deployment.json"]
tool_timeout_sec = 60
```

Registration syntax and skill locations follow the
[official Codex MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
and [skill guide](https://learn.chatgpt.com/docs/build-skills). The adapter uses the
[maintained Python SDK](https://github.com/modelcontextprotocol/python-sdk),
currently locked to 2.2.0 within `mcp>=2.2,<3`.

Codex launches the stdio process. stdout contains protocol traffic; logs use
stderr. Tools register even when the coordinator is offline; a call then reports
the real native connection failure. Missing capabilities are reported as such.
An installation without the extra can import the native client and daemon;
explicit adapter invocation explains how to install `loom[mcp]`.

The client extra does not install project dependencies on the coordinator or
workers. Existing daemons, protected policies and qualified worker environments
must already be configured. Preparation uses the explicitly selected existing
profile. Its current authority is embedded; SLURM preparation profiles are not
supported. Compatible target execution follows the native scheduler's policy.

## Tool contract

Every tool accepts optional `expected_coordinator_id`. Native values and native
error details retain their meanings; the SDK supplies protocol argument handling.
Tool annotations describe read versus mutation behavior and grant no authority.

| Tool | Main inputs | Result |
| --- | --- | --- |
| `loom_run` | Native `request` | Durable run acceptance plus native cleanup evidence |
| `loom_cancel_run_operation` | `operation_id` | Native cancellation control operation |
| `loom_status` | None | Connection description plus current native status |
| `loom_prepare_run` | `operation_id`, `run_name`, `source`, `config_path`, `preparation_profile`, ordered `overlays`/`overrides`, sparse `run_options`, optional `context` | Asynchronous native operation |
| `loom_get_operation` | `operation_id` | Native operation and preparation evidence |
| `loom_wait_for_operation` | `operation_id`, `timeout_seconds=25` | TERMINAL or TIMEOUT observation |
| `loom_cancel_preparation` | `operation_id` | Preparation cancellation request/result |
| `loom_list_jobs` | `limit=20`, `cursor=null` | Native admission page, including preparation children |
| `loom_get_job` | Exactly one of `admission_id` or `queue_item_id` | Native admission detail; queue mode first resolves the ID |
| `loom_inspect_run` | `run_uri` | Native diagnostic success/failure union for an admitted run |
| `loom_run_context` | `run_uri` | Original submission, current annotations, bounded submission links and native inspection; no execution or payload download |
| `loom_patch_run_annotations` | `run_uri`, `mutation_id`, `patch` including `expected_revision` | Native CAS patch, preserving unrelated keys; omitted description differs from explicit null |
| `loom_append_run_note` | `run_uri`, `mutation_id`, `text` | Append-only native author/time; same-ID exact replay returns the original note |
| `loom_list_run_notes` | `run_uri`, `limit=50`, `cursor=null` | Up to 50 notes in native time/ID order; legacy attribution remains unknown |
| `loom_list_agents` | `limit=20`, `cursor=null` | Native agent page |
| `loom_get_agent` | `agent_id` | Native availability/freshness projection |
| `loom_submit_run` | `run_uri`, `queue_item_id`, optional explicit `retry_failed_revision` | Native admission |
| `loom_wait_for_change` | `admission_id`, `expected_revision`, `timeout_seconds=25` | Native admission change/timeout observation |
| `loom_cancel_job` | `queue_item_id` | Native cancellation acknowledgement |

Job/agent pages contain 1–100 items; note pages contain 1–50. Annotation writes
use run-scoped IDs shared across patch and note operations for each authenticated
principal. An uncertain reply must be replayed with its original ID/request;
a stale patch may be deliberately rebased only with a new ID. The tools do not
assign author identity or automatically rebase conflicts. See
[annotation semantics](coordinator-client.md#editing-annotations-and-appending-notes).

Waits accept 0–25 seconds. Adapter capacity admission
and native I/O share one 30-second request budget. Synchronous calls run outside
the SDK event loop with bounded outstanding work and reserved ordinary-call
capacity while waits are active. Codex's 60-second timeout leaves room around
that bound. A wait timeout requests no cancellation.
Artifact fetch shares this deadline across all items, inventory pages, chunks and
retries. Expiry marks unfinished selected items failed and removes owned temporary
downloads before releasing capacity; completed destinations remain successful.

`structuredContent` carries the complete native result. Short text highlights
identifiers, state and useful evidence. A well-formed call that fails uses
`isError=true` and the native classified error structure, including operation,
boundary, IDs, evidence and mutation outcome. A failed job or preparation state
is instead a successful observation. `RunInspectionFailure` remains a normal
native diagnostic union member; it is not flattened into an MCP transport error.

For prepared operations, retain `coordinator_id`, `prepared_run`,
`preflight_status` and `report_ref` in the result. The complete operation projection
is bounded to 64 KiB. A complete inline `preflight` is returned when it fits.
If it is null while status/reference are present, a larger full report remains
pinned. Reading that report requires existing authorized artifact tooling; these
tools do not introduce a separate artifact downloader.

## Preparation and reconnect

Project/user instructions own authoring, selected files, environment choice and
scientific interpretation. For example, after authoring on the coordinator,
`loom_prepare_run` takes this native request shape:

```json
{
  "operation_id": "prepare-example-01",
  "run_name": "example-01",
  "source": {
    "mode": "shared",
    "root": "projects",
    "path": "example",
    "include": ["pipeline.yaml", "config"]
  },
  "config_path": "pipeline.yaml",
  "preparation_profile": "existing-project"
}
```

Use an allowed source alias/profile from `loom_status`. For explicitly staged
preparation, set `source.mode` to `staged` in the same request shape. These files
must exist under the coordinator's configured source root. Shared mode uses a
configured shared snapshot; staged mode sends a verified bounded archive through
native assignment transfer. Neither mode uploads arbitrary laptop files or
installs the eventual target's code/data. See the finite selection, qualification,
portability and retention limits in [agent preparation](agent-preparation.md).

Prepare-only ends at its exact receipt. To prepare and run, pass the native
`RunRequest` dictionary to `loom_run`: `{"preparation": <the request above>,
"queue_item_id": "execute-example-01"}`. Native exact/reconciled intent decoders
preserve supplied invocation controls and retry policy. Returning means durable
acceptance; `applied` means admitted, then monitor the native run for completion.
The operation continues through preparation/admission if MCP exits. For a receipt
already prepared, retain `loom_submit_run`; explicit failed-revision retry uses
its native `retry_failed_revision` capability and is never inferred from replay.
Use `loom_cancel_run_operation` for unified cancellation and observe its returned
control ID; `loom_cancel_preparation` remains prepare-only. Preparation on worker B does not pin execution to B: the
scheduler may place stages on compatible C. Both existing installations must
satisfy the target requirements and have the required target code/data access.

Retain the coordinator, operation, queue item and admission IDs as they become
available. On a lost mutation reply, an SDK cancellation or disconnected session,
the mutation may have completed remotely. Reconnect with the saved coordinator
guard and query the original ID; replay only the same accepted intent when
necessary. Never choose a fresh ID to escape uncertainty. A conflict or mismatch
requires reconciliation. The adapter does not automatically submit, resubmit or
cancel. Cancellation acknowledgements do not prove native work/resource release;
observe the actual outcome.

## Install the operational skills once per user

The four directories under `skills/` are product skills, separate from contributor
roadmap workflows. Each can be copied or linked independently outside this
checkout, with no project path assumptions or references into repository docs.
To follow updates from one maintained checkout, link them once:

```sh
mkdir -p "$HOME/.agents/skills"
ln -s /absolute/path/to/loom/skills/loom-prepare "$HOME/.agents/skills/loom-prepare"
ln -s /absolute/path/to/loom/skills/loom-run "$HOME/.agents/skills/loom-run"
ln -s /absolute/path/to/loom/skills/loom-monitor "$HOME/.agents/skills/loom-monitor"
ln -s /absolute/path/to/loom/skills/loom-diagnose "$HOME/.agents/skills/loom-diagnose"
```

Inspect an existing destination instead of overwriting it. Update the same source
checkout to update linked skills; copied installations need the corresponding
individual directory refreshed. Do not duplicate them into every project.

| Skill | Use and boundary |
| --- | --- |
| `loom-prepare` | Authored inputs and explicit existing profile to a prepared receipt; prepare-only stops there |
| `loom-run` | Unified native run or exact prepared receipt, same-ID reconciliation and explicitly requested cancellation |
| `loom-monitor` | Native observations and requested bounded waits; a status question does not start indefinite monitoring |
| `loom-diagnose` | Evidence-based ownership and remedies; small inline checks or larger pinned-report routing |

The same skills support a build/checksum project and a transform/report project.
Projects supply their configs, resources, targets and environment choice. The
skills introduce no experiment object, scientific defaults, project registry,
environment creation, automatic code repair or operator recovery. A request to
prepare and run authorizes the unified native operation without an artificial approval gap.
A diagnosis request or observation timeout does not authorize cancellation.

For a complete generic conversation, see the
[MCP operations example](../../examples/operations/mcp-coordinator/README.md).

## Validation and limits

`make test-mcp-extra` uses an isolated locked SDK/config environment. The lane is
included in `make validate-pr` and `make test-summary`; base collection/imports
remain independent of the SDK. Real SDK stdio and disposable native daemon tests
cover the protocol boundary, source modes and reconnect semantics. Skills receive
separate relocated behavior trials.

Live Codex registration/discovery and physical two-machine NAS acceptance require
a configured deployment. They have not been established by loopback tests. The
phase evidence records their actual status; examples do not enroll credentials,
change real Codex sessions or launch scientific work. No remote MCP hosting,
plugin package, arbitrary source deployment, environment builder or extra state
store is part of this adapter.
