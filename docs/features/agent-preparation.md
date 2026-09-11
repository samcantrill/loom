# Prepare Runs Through The Coordinator

Preparation turns authored configuration into a canonical Loom run without
executing its target stages. The coordinator accepts the request, schedules a
fixed preparation child in the specified existing worker environment, and
publishes the checked result. The caller then decides whether to submit it.

Use the same [native client](coordinator-client.md) on one machine or a fleet.
The coordinator host can use its Unix socket; other clients use authenticated
HTTPS directly. A submitting client does not need a worker service. Workers
retain their existing outbound connection to the coordinator.

## Select Inputs And An Existing Environment

Write configuration with your editor or project tooling into a directory the
coordinator can read. Preparation does not edit projects, install packages or
create environments. An operator configures allowed source roots and preparation
profiles; the request names those aliases rather than arbitrary host paths.

This request selects `configs` within `example-project` under the allowed
`projects` root and checks `configs/experiment.yaml` in profile `example-cpu`:

```json
{
  "operation_id": "prepare-demo-001",
  "run_name": "demo-001",
  "source": {
    "mode": "shared",
    "root": "projects",
    "path": "example-project",
    "include": ["configs"]
  },
  "config_path": "configs/experiment.yaml",
  "preparation_profile": "example-cpu"
}
```

Save it as `prepare-request.json`. Paths in `include` and `config_path` are
relative to the selected project; `source.path` is relative to the configured
root. `.` may select the root itself. Include explicit files or directories,
including any configuration fragments composition needs. Includes are not globs.
Absolute paths, traversal, symbolic links and special files are rejected.

The selection permits at most 100 includes, 4,096 captured regular files and
64 MiB of selected file bytes. The configuration must be in that selected
closure. Large datasets and environment directories belong outside the capture.
Installed project code remains part of the selected environment, with its
existing installation and source-identity checks.

Shared mode uses one coordinator-published snapshot visible to eligible workers.
An agent can mount it under a different prefix: its protected root mapping
resolves the reference. The worker verifies the captured manifest and bytes
before composition. No per-worker project copy is needed. Each snapshot has a
Loom-owned `manifest.json` beside a `files/` directory containing the selected
project files. An authored file named `manifest.json` is preserved under `files/`.

The captured manifest identifies the exact consumed bytes. A mutable project
directory is not an atomic Git snapshot; detected changes during capture fail
explicitly. Wait for `input_receipt` before editing the selected files again,
or provide a stable source directory. Once capture is recorded, retries and
restart use those bytes even if the authored project changes.

Shared is the supported source mode in this release. A well-formed `staged`
request receives `unsupported` with `mutation_outcome: not_applied` before any
operation reservation, capture, child dispatch or target creation. Enabling a
mode in configuration cannot install its implementation, and Loom never silently
falls back between modes.

## Request, Observe, Then Submit

With an existing protected client connection file:

```sh
loom queue daemon-prepare --connection client.yaml --request prepare-request.json --format json
loom queue daemon-operation --connection client.yaml prepare-demo-001 --format json
loom queue daemon-operation-wait --connection client.yaml prepare-demo-001 --timeout 25 --format json
```

On the coordinator host, replace `--connection client.yaml` with
`--endpoint /run/loom/coordinator.sock`. Use the endpoint from your deployment.
The new Python methods are `CoordinatorClient.prepare_run(PrepareRunRequest)`
and `cancel_preparation(operation_id)`. Both return the existing
`LocalDaemonOperation`; `operation()` and `wait_operation()` observe its progress.

The same request file can be used from Python:

```python
import json
from pathlib import Path

from loom.coordinator import CoordinatorClient, PrepareRunRequest

request = PrepareRunRequest.from_dict(
    json.loads(Path("prepare-request.json").read_text())
)
with CoordinatorClient.from_connection_file("client.yaml") as client:
    coordinator_id = client.describe_connection().coordinator_id
    operation = client.prepare_run(
        request, expected_coordinator_id=coordinator_id
    )
    observation = client.wait_operation(
        operation.operation_id,
        timeout_seconds=25,
        expected_coordinator_id=coordinator_id,
    )
    print(observation.to_dict())
```

This makes one bounded observation. Its timeout is not a request to stop or
resubmit preparation. The file paths in the example select your existing client
configuration and authored request.

Keep the operation ID and `result.coordinator_id`. On reconnect, pass
`--expected-coordinator-id` or the corresponding Python keyword. The coordinator
checks this guard before lookup or mutation. An operation wait timeout leaves
work running, and closing the client does not cancel it.

| Operation state | Meaning |
| --- | --- |
| `pending` | Accepted; capture, child work or cancellation reconciliation remains. |
| `applying` | The coordinator durably claimed final publication; completion or recovery remains. |
| `applied` | Canonical publication completed and the full prepared receipt is available. |
| `failed` | Capture, checks, child work or publication failed; read the code and evidence. |
| `cancelled` | Publication was excluded and native evidence proves the child cannot continue. |
| `conflict` | Retained intent, ownership or target state prevents this preparation. |

A successful initial call means durable acceptance. A successful child means
its report is available. Only `applied` means the target run is prepared.
Read `result.prepared_run`, whose fields are `run_uri`, `plan_digest`,
`runtime_digest` and `stage_names`. Submit that URI explicitly when ready:

```sh
loom queue daemon-submit --connection client.yaml demo-job-001 PREPARED_RUN_URI --format json
loom queue daemon-wait --connection client.yaml demo-job-001 --timeout 25 --format json
```

Replace `PREPARED_RUN_URI` with the receipt's exact value. It names coordinator
state; a remote client does not need to open that path. Preparation never
automatically submits the target.

Preparing on worker B does not pin execution to B. Worker C may execute target
stages when its installed software, resource/placement policy and existing input
bindings satisfy the prepared requirements. The capture serves composition only:
target stages must use portable resolved values and supported runtime data
bindings. A scratch path on B is not implicitly delivered to C.

## What Is Checked And Retained

The ordinary managed child uses the selected worker's actual Python. It explicitly
loads the installation's `loom.recipes` entry points into a fresh recipe catalog,
using Loom's strict plugin loader. Missing recipes, duplicate registrations or
plugin import failures remain native child failures; the coordinator does not
install or import these plugins. It composes the configuration once, then checks
that same object with
`run_preflight_composed`. Its configuration, pipeline, selector and runtime
checks do not execute scientific workloads. Installation readiness stays with
the existing resident profile checks; coordinator store/authority checks do not
run against the worker's scratch directory.

The child commits its checked composition, manifest, recipe/provenance evidence,
exact per-stage software requirements and complete native preflight result as a
report. The coordinator verifies the child/input/profile identities and required
checks, then calls the existing managed publisher with that composition. It
does not compose again or import the project's recipes. Nonempty recipe evidence
survives fresh publication and exact replay.

An operation result contains its coordinator ID, input receipt, child admission
ID, preflight status, optional complete preflight, report reference, optional
prepared receipt and bounded evidence references. Read the child admission for
execution details. A failed operation or failed preflight is a successful read
of native evidence, rather than a client transport error.

The existing operation envelope keeps `operation_id`, `kind`, `state`, `code`
and `result`. For `kind: prepare_run`, the result fields are:

| Field | Available evidence |
| --- | --- |
| `schema_version` | Integer `1`. |
| `coordinator_id` | Stable coordinator identity for reconnect guards. |
| `input_receipt` | Null before capture; then mode, manifest digest and shared input reference. |
| `preparation_admission_id` | Null before the internal child is admitted; otherwise its native admission ID. |
| `preflight_status` | Null before a report exists; otherwise its native aggregate check status. |
| `preflight` | A complete native result when it fits, otherwise null. |
| `report_ref` | Null before a report exists; otherwise its pinned committed artifact reference. |
| `prepared_run` | Null before publication; otherwise the complete native prepared receipt. |
| `evidence_refs` | Bounded existing references; empty before evidence is recorded. |

The complete operation projection is limited to 64 KiB. Required identities,
references and the full prepared receipt take priority. Large preflight details
are omitted as one complete unit; `preflight_status` and `report_ref` retain the
result and its location. If the mandatory prepared receipt cannot fit, preparation
fails with `result_too_large` before writing the target. No receipt is truncated.

Full reports remain available through existing authorized run/artifact-store
inspection and loading. The client adds no arbitrary file-download interface.
Captured inputs, report references and linked preparation evidence remain pinned
while the operation is retained. Cleanup refuses to remove evidence needed for
replay. Automatic expiration and operation deletion are not provided; failed and
cancelled operations can also retain captured bytes.

Retention pins live in a protected `.loom-preparation-pins` directory beside the
capture or run. They identify its coordinator and operation without modifying a
complete prepared run. Cleanup rejects a pinned directory, its descendants, and
an ancestor whose deletion would remove those pins, with
`retained_preparation_evidence`. Cleanup checks this again when executing a
previously approved preview. There is no supported manual unpin procedure.

Stable operation codes identify the failing boundary: `source_unavailable` and
`source_changed` describe capture, `input_limit_exceeded` describes the finite
selection bounds, `installation_mismatch` identifies incompatible worker software,
`preflight_failed` preserves a failed check report, `preparation_child_failed`
preserves native child failure evidence, and `publication_conflict` leaves the
conflicting target inspectable. `result_too_large` prevents an unreadable required
projection. These codes complement the native report/admission evidence; they
do not replace [client connection and mutation errors](coordinator-client.md#reconnect-and-reconcile).

The coordinator reports `installation_mismatch` when the report's profile or
per-stage software requirements differ from the accepted installation. Missing
stage requirements, a mismatched committed worker result, corrupted report bytes,
and nonportable target paths produce `invalid_preparation_report` before
publication. The linked child admission retains the original execution evidence.
An unavailable required check also prevents publication, even when other passing
checks keep the native aggregate status at `PASS`; inspect the individual check's
`SKIP` status and required applicability. Warnings and inapplicable skips remain
visible without preventing an otherwise valid publication.

`preparation_unavailable` on a pending or applying operation means reconciliation
will retry from its retained state. In particular, a missing reply or temporarily
unavailable report after the publication claim cannot establish that publication
failed: the target may already exist. Keep observing that same operation instead
of submitting a replacement request with another ID.

## Retry And Cancel

Retry the same explicit request with the same operation ID and principal after
a lost response. An ID reused with changed intent conflicts. The first acceptance
freezes the selected protected profile/source configuration; retry does not
reinterpret it after configuration reload. Another principal cannot take over
the operation by submitting its ID.

The coordinator retains one child identity and target reservation. Restart
rejoins that child and its authoritative capture/report. A durable publication
claim is replayed through the same native publisher. A matching complete target
is read-only replay; a partial or changed target stays an inspectable conflict.
If a child admission reply was lost, the durable dispatch claim lets recovery
rejoin the same admission even if that child has already finished. Recovery does
not prepare or execute a second child.
After a capture receipt has been recorded, editing the authored files does not
change that operation's input. Interrupted temporary captures are scoped to both
the coordinator and operation, so recovery does not remove another coordinator's
in-progress copy on shared storage. Protected configuration changes still use
the existing coordinator reload procedure before restart; accepted operations
retain the selection made before that reload.

```sh
loom queue daemon-cancel-preparation --connection client.yaml prepare-demo-001 --format json
loom queue daemon-operation-wait --connection client.yaml prepare-demo-001 --timeout 25 --format json
```

Before the publication claim, cancellation excludes target publication and
requests child cancellation. The operation stays pending until no-dispatch or
native terminal/release evidence proves cancellation. An acknowledgement, lost
worker or exited root process alone does not prove containment.

After the claim, reconciliation reports the actual publication outcome, which
may be `applied`. Cancellation does not delete or roll back a published target.
Repeated cancellation of a terminal operation returns that outcome. Cancelling
preparation also never submits a target or cancels an independently submitted job.

## Operator Configuration And Rollout

The optional `preparation` section in the protected schema-3 coordinator file
contains `source_roots` and `profiles`. Omission or an empty configuration disables
preparation without changing existing deployment identity.

| Setting | Meaning |
| --- | --- |
| `source_roots.<alias>.path` | Coordinator-visible authoring root. |
| `source_roots.<alias>.shared_snapshot_root` | Protected snapshot location required for shared mode. |
| `profiles.<alias>.resident_profile_id` | Exactly one qualified existing local or remote software profile. |
| `profiles.<alias>.allowed_source_roots` | Explicit allowed root aliases. |
| `profiles.<alias>.source_modes` | Allowed modes, intersected with installed implementation support. |
| `profiles.<alias>.runtime_options` | Existing native resource/placement options for the managed child. |
| Resident `preparation_shared_roots` | Root alias to worker-visible snapshot directory, retained with the private launch binding. |

For example, merge this section into the protected coordinator file, replacing
paths and `qualified-project-profile` with your deployment's observed values:

```yaml
preparation:
  source_roots:
    projects:
      path: /nas/projects
      shared_snapshot_root: /nas/loom-preparation
  profiles:
    example-cpu:
      resident_profile_id: qualified-project-profile
      allowed_source_roots: [projects]
      source_modes: [shared]
      runtime_options:
        executor: local
```

This uses the existing embedded managed execution family. `local` is the native
executor setting for that family; the selected compatible agent still owns the
child process. It does not require execution on the coordinator host.

Add the mapping to each participating resident profile in its protected agent
file, alongside its existing descriptor, Python, project and readiness settings:

```yaml
preparation_shared_roots:
  projects: /mounted/nas/loom-preparation
```

The two snapshot paths must expose the same shared directory. Protect and reload
these role inputs through the existing deployment workflow; do not copy private
interpreter paths or credentials into the request JSON. For the example request
above, authoring reads `/nas/projects/example-project/configs/experiment.yaml`;
the worker reads the verified capture through its own mapping.

Configure the mapping before initializing a new worker root. An existing root
retains its private launch binding, so adding or changing a mapping follows the
existing worker replacement procedure after retained work settles. Coordinator
policy reload can change allowed aliases while accepted operations retain their
original selections; it cannot reinterpret a worker's retained input mapping.
The coordinator-only upgrade does not rewrite or recreate worker roots.

The profile chooses an existing installation, with no inferred default
environment or shell command. Preparation requires embedded coordinator
authority and rejects services with configured SLURM profiles. This restriction
does not remove ordinary coordinator control of existing jobs.

The selected worker installation must qualify the Loom preparation module and
the finite input binding, advertised as `preparation-input-v1`. Old workers can
continue compatible ordinary jobs; they cannot receive a preparation child whose
capability or profile they lack. The coordinator advertises
`agent-preparation-v1` and safe source/profile aliases only when the capability
is installed and enabled. This describes support, not a capacity reservation.

A nonempty `preparation_shared_roots` mapping requests a bounded import check for
`loom.preparation.PreparationStage` and `weave.compose_config` in the profile's
selected Python. `readiness.preparation: true` requests the same check explicitly.
Its finding is `packages.preparation_imports`; it does not compose a project or
change the declared members used to calculate portable software fingerprints.
Adding a shared-root mapping alone therefore does not make a previously compatible
execution environment incompatible.

An outbound agent must also include `preparation-input-v1` in its protected
`registration.capabilities`, with the same capability allowed for that agent in
the coordinator's `agent_policy.agents` entry. That declaration qualifies every
configured resident profile, because the capability belongs to the agent session.
Registration refuses the capability if any of those environments lacks successful preparation
qualification. Declare compatible existing installations before enabling it;
the request itself never installs missing modules.

The preparation child's native placement includes the selected profile's full
descriptor fingerprint and preparation capability as hard constraints. A different
profile with the same software fingerprints cannot take that child. A worker
without the capability remains eligible for ordinary compatible jobs, so waiting
preparation does not prevent other work from running. Published target stages
retain their normal software requirements and authored placement; they do not
inherit the child's preparation-only constraints.

For an existing coordinator root at schema 12, follow the explicit
[offline upgrade procedure](../downstream-operations.md#upgrade-a-retained-coordinator-root)
before restarting with schema 13. Worker roots and journals stay at schema 12.
Then qualify participating installations, configure the allowed sources/profiles
and worker mappings, and enable preparation through the protected role settings.
Existing accepted operations retain their selected configuration after reload.

The [local](../../examples/operations/managed-local-basic/README.md) and
[remote](../../examples/operations/managed-remote-operations/README.md) examples
show how this connects to the existing submit/observe workflow. Physical NAS,
fleet and container availability must be checked on the actual deployment;
temporary-directory and loopback tests do not qualify those environments.
