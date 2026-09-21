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
  "preparation_profile": "example-cpu",
  "overlays": ["configs/site.yaml"],
  "overrides": ["model.width=64"],
  "run_options": {"tags": {"experiment": "demo"}}
}
```

Save it as `prepare-request.json`. Paths in `include` and `config_path` are
relative to the selected project; `source.path` is relative to the configured
root. `.` may select the root itself. Include explicit files or directories,
including any configuration fragments composition needs. Includes are not globs.
Absolute paths, traversal, symbolic links and special files are rejected.

Ordered `overlays` name captured files relative to the selected project.
Ordered `overrides` use existing configuration override strings. Sparse
`run_options` preserve omitted fields and explicit values, and use Loom's usual
base, selected runtime profile, then explicit invocation precedence. The worker
merges these controls before preflight; publication consumes its effective
options without changing them. Selectors, reuse, reliability/timeouts, resource
settings, tags and notes remain governed by their native validators. Executor
and adapter invocation inputs are rejected; validator registries and live Python
objects are not serialized options. Preparation-profile options apply only to the
internal child. Accepted requests and published provenance retain invocation intent.

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

Staged mode supports workers without access to that shared directory. Change
`source.mode` to `staged` and use a new operation/run ID. The coordinator packs
only the explicit captured selection and its manifest into a regular tar archive,
commits it before recording the ready input receipt, and delivers it using Loom's
existing artifact relay. The worker verifies and extracts it beneath its own
assignment workspace before accepting the input. Shared storage mappings are
unnecessary for this mode; the original authoring directory must still be visible
to the coordinator. This does not upload a laptop checkout.

The archive and all other assignment inputs must together fit the existing
64 MiB transfer ceiling. Tar headers and padding count, so a selection near the
64 MiB content ceiling can fail with `input_limit_exceeded` when packed. Extraction
also enforces the captured file count/content bounds, safe unique destinations,
regular files and manifest hashes. Absolute paths, traversal, links and special
members cannot become ready inputs. The installed child uses the verified files
for composition; they do not deploy code or data to later target workers.

Protected policy and qualified worker installations must support the chosen mode.
A disallowed mode receives `unsupported` with `mutation_outcome: not_applied`
before operation reservation or capture. Earlier shared-only coordinators still
reject staged requests. Enabling a mode in configuration cannot install its
implementation, and Loom never silently falls back between modes.

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
| `input_receipt` | Null before capture; then mode, manifest digest and either a shared input reference or the staged archive's native ArtifactRef. |
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
selection or packed transfer bounds, `installation_mismatch` identifies incompatible worker software,
`preflight_failed` preserves a failed check report, `preparation_child_failed`
preserves native child failure evidence, and `publication_conflict` leaves the
conflicting target inspectable. `result_too_large` prevents an unreadable required
projection. These codes complement the native report/admission evidence; they
do not replace [client connection and mutation errors](coordinator-client.md#reconnect-and-reconcile).

The coordinator reports `installation_mismatch` when the report's profile or
per-stage software requirements differ from the accepted installation. Missing
stage requirements, a mismatched committed worker result, corrupted report bytes,
malformed native report/check/runtime values, and nonportable target paths produce `invalid_preparation_report` before
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

A staged transfer or extraction interruption also retains the same operation,
child identity and ready archive. Native transfer replay resumes the same bytes;
partial extraction never becomes ready. Restart does not recapture a recorded
archive after author edits. The operation pins the committed archive and report;
assignment scratch remains owned by the worker's terminal/release lifecycle.

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
| Resident `readiness.preparation_staged` | Require the selected Python to support the preparation stage, configuration loader and staged input handler. |
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

For a staged-only deployment, set the coordinator profile's `source_modes` to
`[staged]`; its source root needs only `path`. The worker profile needs
`readiness.preparation_staged: true` and no `preparation_shared_roots` mapping.
To offer both modes, use `[shared, staged]`, retain the shared mapping and enable
the staged readiness check. The request still chooses a mode explicitly.

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
environment or shell command. Preparation publishes through the configured
embedded or authenticated coordinator authority. A target routed to SLURM must
match a configured profile and its checked project, environment and executor
requirements. Accepted preparation retains that selected authority and those
profile bindings across recovery.

The selected worker installation must qualify the Loom preparation module and
the finite input binding, advertised as `preparation-input-v2`. Old workers can
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

An outbound agent must also include `preparation-input-v2` in its protected
`registration.capabilities`, with the same capability allowed for that agent in
the coordinator's `agent_policy.agents` entry. That declaration qualifies every
configured resident profile, because the capability belongs to the agent session.
Registration refuses the capability if any of those environments lacks successful preparation
qualification. Declare compatible existing installations before enabling it;
the request itself never installs missing modules.

For staged input, additionally allow and declare `preparation-staged-input-v1`
in the coordinator agent policy and outbound registration. Its qualification
imports `loom.queue.preparation.resolve_staged_input` in the actual selected
Python, as well as the ordinary preparation entrypoints, and reports
`packages.preparation_staged_imports`. It does not change portable software
fingerprint meaning. A shared-only installation advertising `preparation-input-v2`
cannot receive staged preparation work. Each advertised resident environment must
qualify the declared modes before registration.

The preparation child's native placement includes the selected profile's full
descriptor fingerprint and preparation capability as hard constraints. A different
profile with the same software fingerprints cannot take that child. A worker
without the capability remains eligible for ordinary compatible jobs, so waiting
preparation does not prevent other work from running. Published target stages
retain their normal software requirements and authored placement; they do not
inherit the child's preparation-only constraints.

Coordinator roots use schema 14. Child input and report schemas are version 2;
input receipts and the public preparation-operation projection remain version 1.
Older schema-13 roots are rejected before mutation: settle their retained work
with the original installation before replacing services. Outputs are not reset
or rewritten. The existing schema-12 offline upgrade remains explicit. Worker
roots and journals remain schema 12, with preparation-capable installations
advertising `preparation-input-v2`.
Then qualify participating installations, configure the allowed sources/profiles
and worker mappings, and enable preparation through the protected role settings.
Existing accepted operations retain their selected configuration after reload.

The [local](../../examples/operations/managed-local-basic/README.md) and
[remote](../../examples/operations/managed-remote-operations/README.md) examples
show how this connects to the existing submit/observe workflow. Physical NAS,
fleet and container availability must be checked on the actual deployment;
temporary-directory and loopback tests do not qualify those environments.

## Selected Authority And Pre-execution State

Both embedded and authenticated authorities publish checked targets. Preparation
retains the selected authority identity and target profile descriptors at
acceptance. Restart resolves those exact protected implementations; changed or
unavailable owners retain `preparation_unavailable` instead of selecting a new
database or current profile. Public receipts contain no factories or credentials.
Slurm routes can be checked and published when their selected profile satisfies
the preparation installation's software requirements. The preparation child still
runs in its qualified resident environment; prepare-only never dispatches Slurm.

A run starts `CREATED`, becomes `PLANNED` after publication, and becomes `RUNNING`
only on confirmed stage execution. Admission, queuing and a start grant do not
make it running. Reuse/skip-only targets can complete without a worker. Explicit
failed-admission retry returns released work to `PLANNED`, preserving the existing
failed-revision guard and attempt history; authenticated retry remains unsupported.

Publication keeps its per-run POSIX advisory lock and retained lock inode.
Qualified storage must support cross-process advisory locking. A locally partial,
corrupt or changed target remains an inspectable conflict. Once local publication
is complete, an unknown authority reply is reconciled idempotently using the same
publication identity. Successful replay returns the original target receipt.

### Separate local authority storage

For a fresh managed deployment whose run files live on shared storage, select a
local authority root in the protected coordinator role file:

```yaml
deployment_root: /local-persistent/loom/fleet/deployment
run_store_root: /shared/loom/runs
authority:
  kind: embedded
  state_root: /local-persistent/loom/fleet/run-authority
```

Before loading the role, create `state_root` on verified durable local storage,
owned by the coordinator user with mode `0700`. Relative paths resolve against
the role file's directory. Loom checks ownership and permissions; filesystem
locality and durability require operator qualification. SQLite/WAL on NFS or
other shared filesystems is unsupported. Keep the deployment's control and agent
state on suitable local storage too.

The selected factory places each canonical run's database, WAL and shared-memory
file under this root, within a deployment-specific namespace. Run URIs continue
to name the shared materializations: configurations, payloads and provenance.
The existing deployment binding retains the resolved authority placement and
owner identity; public run metadata carries only a binding digest. Workers do
not receive authority database paths.

Preparation children and target publication, coordinator inspection, execution,
restart/recovery and explicit failed-admission retry use this same factory. Use
the native coordinator inspection client for these runs; standalone commands
that infer a database beside the materialization cannot discover protected local
placement. A missing retained database fails as unavailable state, and replay
never creates a replacement ledger. Restore consistent offline backups through
operator recovery; changing or removing `state_root` on an initialized deployment
is a binding conflict. Live-root migration is unsupported.

Omitting `state_root` preserves the existing embedded layout beside each run.
That layout remains suitable for local-only runs. The separate placement option
does not itself add shared-agent execution or shared output publication.

## Protected local configuration

The default `configuration_policy: portable` retains path-free stage configuration
and factory arguments. To prepare file-using installed project stages, an operator
can set `configuration_policy: local` in an existing protected coordinator
`preparation.profiles` entry:

```yaml
preparation:
  profiles:
    example-cpu:
      resident_profile_id: installed
      allowed_source_roots: [project]
      source_modes: [shared]
      runtime_options: {executor: local}
      configuration_policy: local
```

Keep the existing `source_roots` and local-agent configuration alongside this
entry. Local policy requires that resident profile to be the coordinator's
protected embedded local agent. It applies equally to shared and staged source
capture; source mode controls capture transport, while configuration policy
controls target locality. Requests and captured YAML cannot grant this permission.

Every action, including the preparation child, receives the coordinator
`machine_id` as its hard agent target. A conflicting authored target or nonlocal
execution route fails before publication. An equally installed second agent
cannot take the work, and an unavailable selected agent cannot cause spillover.
Loom retains the selected agent and the protected launch-profile fingerprint,
covering installation, environment, container settings and shared-root bindings.
Publication, restart admission and resident assignment compare that identity.
Changed bindings require fresh preparation; old work cannot silently relocate.
This identity describes installation and binding configuration, not a checksum of
mutable dataset contents. Installed project code owns data semantics and integrity.

Local child input and reports use version 3 with an explicit `local_scope`.
Portable version-2 producers and reports remain supported. Unknown versions fail
before publication. Native action fingerprints retain locality in the reserved
`loom.local_preparation` fingerprint field; authored configuration cannot provide
that field. Remote assignment export explicitly refuses unresolved local scope,
even when a particular action contains no path-looking value.

Source containment and native preflight still apply. Local policy permits ordinary
domain fields such as `weights_ref.path`; it does not add mounts or grant filesystem
permissions. See the runnable [local file example](../../examples/execution/local-preparation/README.md).

## Installed Final Project Inspection

A protected local preparation profile can require one installed callable after
recipe expansion, ordinary overrides, effective option merging and native
preflight. The callable runs in the selected worker installation. The coordinator
receives plain data and never imports the project's processor.

Add this field to the existing protected preparation profile (alongside its
resident profile, roots, source modes and child runtime options):

```yaml
configuration_policy: local
project_processor:
  schema_version: 1
  callable: installed_project.preparation:inspect
  evidence_namespace: example
  recovery_stage: fit
```

`recovery_stage` selects one existing action's `config.recovery`; use `null` when
the integration adds only top-level `scientific_evidence`. Captured YAML and
processor results cannot choose the callable or widen those destinations. The
selection participates in protected policy identity and is retained with the
accepted invocation. It requires the local agent's protected installation and
binding identity.

The callable accepts one plain mapping with exactly these fields:

- `schema_version: 1`, `composition`, `effective_run_options`, `invocation`;
- `operation_id`, `input_manifest_digest`, `preparation_profile`,
  `profile_descriptor`, `local_scope`, `project_preparation`.

`composition` contains `resolved`, `redacted`, `manifest`, `recipe_manifest` and
`provenance`. `effective_run_options` contains the final native options, while
`invocation` preserves the selected overlays, typed override strings and sparse
explicit run options. `profile_descriptor` is the actual worker installation
evidence. `project_preparation` contains the protected `processor` declaration
and `target_run_uri`. That URI is derived by Loom from its protected run root
and the accepted exact target; it is never the child or assignment workspace.

Return a plain mapping with exactly `schema_version: 1`, `composition`,
`evidence` and `reconciliation_key`. For example, after project-specific checks:

```python
from copy import deepcopy


def inspect(request):
    checked = deepcopy(request["composition"])
    evidence, resume_fingerprint = inspect_final_science(
        checked["resolved"], request["effective_run_options"]
    )
    recovery = {
        "run_uri": request["project_preparation"]["target_run_uri"],
        "resume_fingerprint": resume_fingerprint,
        "environment_fingerprint": request["profile_descriptor"]["environment_fingerprint"],
    }
    for view in ("resolved", "redacted"):
        checked[view]["scientific_evidence"] = (
            evidence if view == "resolved" else redact_project_evidence(evidence)
        )
        fit = next(s for s in checked[view]["pipeline"]["stages"] if s["name"] == "fit")
        fit["config"]["recovery"] = dict(recovery)
    fit["config"]["recovery"]["run_uri"] = "<redacted>"
    return {
        "schema_version": 1,
        "composition": checked,
        "evidence": {"namespace": "example", "payload": evidence},
        "reconciliation_key": None,
    }
```

`inspect_final_science` and `redact_project_evidence` are project-owned operations.
Evidence must be a mapping; the resolved `scientific_evidence` must equal its
payload. The recovery mapping has exactly the three fields shown. Native
validation checks the target URI and installation fingerprint and requires a
nonempty project resume fingerprint. The redacted recovery URI must be
`<redacted>`; the project owns masking sensitive fields in its evidence. Original
redactions and all source/override provenance remain intact. Native checks parse
the augmented resolved graph, preserving diagnostic-only redactions.

For later reconciliation, an integration can return
`{"namespace": "example", "version": 1, "digest": "<64 lowercase hex characters>"}`.
The digest denotes the complete desired-state fingerprint, not a resume or
evidence-envelope fingerprint. This capability retains the key in the native
report; it does not itself enable target reconciliation or rename exact requests.

The child and coordinator compare the requested and checked compositions outside
the two declared destinations. Action parameters, graph edges, factory targets,
outputs, placement, provenance and options cannot change. The published immutable
snapshot includes the additions, and normal assignment supplies `config.recovery`
to the selected consumer. Publication also checks the exact target against the
protected current run root.

A processor exception or invalid result yields a required failed native preflight
check and retained report, with no target publication. The diagnostic retains the
exception class and a fixed message, excluding unchecked exception text. Child
inputs/reports use version 4 and private worker context version 3 for this
capability. Unsupported versions, stale processor/installation/invocation evidence,
redirected recovery and unrelated mutations fail before publication. Existing
portable version 2 and local version 3 reports without an integration still work.

## Shared Configuration And Workload Inputs

`configuration_policy: shared` permits an installed project processor and typed
shared inputs without pinning execution to the preparation agent. This differs
from `source.mode: shared`: that existing source mode selects immutable snapshot
capture; the new policy also qualifies workload locations and execution.
Portable and local policies keep their existing behavior.

Each protected resident profile declares `shared_roots`. The coordinator's
selected profile and each eligible agent retain the same logical root facts,
with that host's own absolute `host_path`. For example:

```yaml
shared_roots:
  data:
    host_path: /nas/datasets
    container_path: /loom/data
    access: ro
    challenge:
      path: qualification/shared-fixture.bin
      sha256: REPLACE_WITH_64_LOWERCASE_HEX_DIGITS
  snapshots:
    host_path: /nas/config-snapshots
    container_path: /loom/snapshots
    access: ro
    challenge:
      path: qualification/shared-fixture.bin
      sha256: REPLACE_WITH_64_LOWERCASE_HEX_DIGITS
preparation_shared_roots:
  projects: /nas/config-snapshots
```

The corresponding worker may use `/mnt/lab/datasets` and
`/mnt/lab/config-snapshots`. Challenges are operator-provided immutable regular
files of at most 64 KiB. Both mappings must read the expected bytes. The
qualification records root IDs, challenge path/digest, access and container
target, separately from software fingerprints. Host prefixes remain private.
Missing roots, changed challenge bytes, traversal, symbolic links and special
input files fail at qualification or use. Existing dataset manifests and project
integrity checks still own scientific content validation; a root challenge is
not a dataset checksum. Mount changes alter protected binding identity and need
requalification. Shared SIF software identity includes the image bytes rather
than its host filename. Container readiness source/import paths must name the
installed image namespace; source identity does not depend on the private
assignment workspace prefix.

The preparation profile selects `source_modes: [shared]`,
`configuration_policy: shared` and `shared_locations`: the explicit union of
locations its installed processor needs to inspect. Its descriptor must contain
qualified shared roots. The processor receives `shared_scope` in place of
`local_scope`; the remaining processor request/result contract is unchanged.
Loom treats `project_preparation.target_run_uri` as identity when transporting it;
a worker must not open that coordinator URI's host prefix. A project processor
can inspect typed locations in its declared fixed container namespace.

A workload configuration selects only its own inputs:

```yaml
pipeline:
  name: shared-example
  stages:
    - name: inspect
      factory:
        _target_: installed_example.shared.InputDigest
      config:
        source:
          kind: loom.shared-location
          schema_version: 1
          root_id: data
          path: selected-product/sample.bin
      outputs:
        receipt:
          artifact_type: json
          codec_key: json.v1
runtime:
  executor: local
```

Install this synthetic stage in the selected interpreter/image:

```python
from hashlib import sha256
from pathlib import Path

class InputDigest:
    def run(self, context, inputs):
        data = Path(context.stage_config["source"]).read_bytes()
        return {"receipt": context.save_artifact(
            "receipt", {"sha256": sha256(data).hexdigest()},
            artifact_type="json", codec_key="json.v1",
        )}
```

Typed locations are resolved only in stage configuration and factory arguments
at the worker boundary. Their logical values remain in the semantic fingerprint.
Ordinary strings are preserved: Loom does not replace host prefixes in user
text. Absolute workload strings are permitted only inside the selected canonical
container locations. Host execution should use typed locations. Native assignment
workspace/output paths remain owned by the worker.

Container execution mounts only the selected relative products and bounded
challenge files, read-only, plus its own assignment workspace. Preparation also
mounts exactly its immutable captured snapshot. Container targets must be under
`/loom/`; snapshot bindings must resolve below exactly one protected shared root.
Unselected dataset roots are not mounted. Do not add shared roots again as broad
container mounts. Shared container jobs use installed Python packages, clear
ambient `PYTHONPATH`, and avoid importing source from the working directory.
The Apptainer route also disables implicit host filesystems, administrator bind
paths and the host working directory; only its explicit bindings are selected.

Prepare and submit with the same `loom queue daemon-prepare`/native coordinator request
workflow above. Advertise `shared-execution-v1` in both the outbound agent
registration and protected agent policy. Installation qualification checks that
the selected interpreter/image supports that capability. Scheduling retains
per-stage root requirements; equal software with missing roots or capability
cannot receive the stage. Preparation child/report version 6 and resident
assignment version 5 explicitly identify this scope. Older formats remain valid
for their original scopes, and unsupported versions are rejected.

Configuration capture happens once; the shared route has no staged input archive
or per-agent configuration copy. Profiles without a `publication` binding retain
the existing artifact relay. The shared artifact route below is selected explicitly.
Physical NAS/container qualification must still be performed on the deployment.


## Shared artifact publication

A protected resident profile can select exactly one writable shared root for
native artifact publication. Add `publication` to that root on the coordinator
and each executing agent, using their respective host prefixes:

```yaml
shared_roots:
  outputs:
    host_path: /nas/fleet/outputs
    container_path: /loom/outputs
    access: rw
    challenge:
      path: challenge.bin
      sha256: <digest-of-the-same-bounded-challenge-file>
    publication:
      max_members: 1024
      max_payload_bytes: 268435456
      max_manifest_bytes: 1048576
```

All three limits are required positive finite integers; booleans and implicit
unlimited values are rejected. They bound data members, their total bytes and
the complete native closure receipt respectively. They are admission limits,
not reservations or evidence of free space. A larger research profile may select
100,000 members, 1,099,511,627,776 payload bytes and 33,554,432 manifest bytes.
Root qualification includes these protected limits. All agents for the admitted
scope must qualify the same output root and policy. Profiles without this object
retain their existing local/portable/shared-input relay behavior.

Native stage output APIs write directly into a root-relative mutable subtree
partitioned by stable agent-root identity, assignment and attempt. Local scratch,
SQLite and IPC stay in the private local workspace. Container workers receive
only their assigned output subtree read-write, their committed input trees
read-only, and the existing challenge/input/workspace bindings. The whole
writable shared root is never mounted into a worker.

After execution is contained, Loom describes every regular data member below the
stage artifact directory, including companions and nested checkpoint catalogs.
Each member has a relative path, byte count and SHA-256 digest; each declared
output names its primary member. Stages must keep their complete output closure
inside that directory and use relative companion references. Symbolic links,
FIFOs and external output paths are rejected. Domain manifest schemas and
scientific interpretation remain owned by the stage.

The native `.loom-publication.json` receipt begins with the attempt's ownership
identity and becomes the complete bounded closure receipt after execution. It
is metadata, excluded from the payload-member count. Resident result schema 4
carries versioned `loom.shared_publication` bindings in native output metadata:
logical root, immutable tree, publication identity, receipt digest, primary member
and admitted budgets. The receipt stays on shared storage; even large manifests
do not need an enlarged HTTP envelope or a second artifact catalog. The ordinary
64 MiB relay bound does not apply to shared payloads.

The coordinator checks its own mapping, current native fence, output association,
complete closure and bytes, fsyncs the tree, and renames it on the same filesystem
into its immutable publication location. Only then can the existing authority
commit success. Publication identity derives from the native assignment, attempt,
agent identity and fence. A lost acknowledgement replays that identity; an old
fence, partial closure or exceeded budget cannot commit success or replace a
winner. Publication errors retain inspectable ownership and bytes for native
reconciliation; they do not fabricate a successful result.

Downstream agents resolve the native binding through their own root mapping and
verify every member before direct consumption. They neither download payload
chunks nor copy companions beside each workspace. `LocalArtifactStore` validates
that same closure for local reads and native reuse/resume checks. Consumers
opening retained references from another host can pass their protected mapping as
`LocalArtifactStore(local_root, shared_roots=bindings)`; the store resolves the
native root-relative binding before accessing bytes, including candidate and
checkpoint reads. Resident workers supply this mapping automatically. A missing or
changed companion is an explicit integrity failure, even if the primary manifest
still matches its checksum. Prefix translation changes location only.

Cleanup rejects receipt-bearing staging, published trees, their members and
containing directories. Native references and settlement retain ownership; there
is no TTL, automatic eviction, or shared-root recursive recovery deletion. This
conservative policy also retains unpublished or cancelled attempts. Explicit
future reclamation must establish reference and execution settlement first.
Cache policy is unchanged: use per-machine writable caches or an immutable
prebuilt cache; this capability adds no distributed cache locking.

The integration acceptance test runs two real resident processes through native
HTTPS assignment/publication, reads a complete payload above 64 MiB and nested
companions, injects a lost publication acknowledgement, and makes relay/copy
paths fail if invoked. Its kernel root alias exercises distinct local prefixes;
it does not qualify physical NAS atomicity or a second machine. Deployment
qualification must establish the selected filesystem's rename/fsync guarantees.

### Installed per-node contracts (processor version 3)

A protected `project_processor` version 3 has exactly `schema_version`,
`callable`, `evidence_namespace`, and `target_prefix`. It omits the legacy
`recovery_stage`. Versions 1 and 2 retain their existing evidence and recovery
injection behavior. Version 3 receives `operation: prepare` with the captured
composition, effective options, invocation, input manifest, installation descriptor,
project binding and local/shared scope. Native preparation input/report envelope
version 7 carries this capability; earlier envelope versions remain readable.

The processor returns exactly `schema_version: 3`, `composition`, `evidence`,
`reconciliation_key`, and `stage_contracts`. The composition must remain equal to
the captured input, including its diagnostic view and provenance. Evidence and the
whole-target reconciliation key keep their existing namespaced shapes.
`stage_contracts` must cover exactly the captured node IDs. Each value has exactly
`semantic_key` and `payload`. The key is null or `{version: 1, digest: <64 lowercase
hex characters>}`; payload is any finite JSON-compatible plain value, including
null. Null keys decline future action reuse. No processor means no attachment.

The native wrapper stores a `project_contracts` mapping in the committed preparation
report. Each node envelope contains `schema_version: 1`, the protected `namespace`,
`semantic_key`, `payload`, and `binding_digest`. Native SHA-256 canonical JSON binds
the capture identity, node ID, normalized original factory/config/input/output
declaration and attachment fields. Capture identity includes operation, input
manifest, invocation and qualified profile. Binding digests use Loom's native
`sha256:<hex>` representation; they are distinct from project semantic keys.

The prepared-run metadata entry `loom.project_contracts` has `kind:
project_contracts` and `data` containing exactly `schema_version: 1`, `namespace`
and the native `report_ref`. Opaque payloads remain in the retained original report,
never in safe prepared-run metadata or application configuration. Existing
preparation retention pins preserve that report. The native runtime record binds
the typed reference digest (runtime record version 4 for these runs), so a missing
or replaced prepared reference fails admission instead of opting out. Workers reload and check the
reference and original declaration before assignment. A worker receives only its
node under `StageWorkerRequest.metadata["loom.project_contract"]`; the context
explicitly forwards that envelope. The private request capture digest permits
binding verification at decoding and is not forwarded into the context. Runtime
location resolution does not traverse the opaque attachment.

Native context also supplies `loom.execution_binding` with exactly
`schema_version: 1`, `origin_run_id`, `origin_node_id`, positive `attempt`,
`environment_fingerprint`, and `run_state_root`. Original identity comes from the
admitted producer and survives assignment-local `loom-agent:` URIs. Machine-local
execution uses the contained durable run directory. Container execution requires
an explicit protected writable source/target mount covering that directory;
otherwise the root is null. Remote and Slurm roots are null. Applications decide
whether the available binding meets their recovery policy; Loom supplies no
checkpoint semantics or layout.

The native run/stage admission metadata APIs reject reserved project/execution
entries. Report namespaces, finite values, exact node coverage, versions and
bindings are checked before action construction. Ordinary similarly named keys
inside application configuration carry no native authority. Project exceptions
retain the existing sanitized operational failure reporting.

Version 3 supports whole-target `verify_candidate` with request version 3 and the
existing verification response (`schema_version: 1`, native `candidate_digest`,
`verdict: verified`). The read-only candidate projects `project_contracts` from its
original report reference. Completed reuse, observing already-owned work and
`one_observed_failure` retry retain their existing lifecycle. These node contracts
are also the checked semantic input to the action-result lifecycle described below.

### Verified action results across graphs

A version 3 processor can participate in action reuse across separately submitted
native graphs. Keep submitting with `loom run` or `RunRequest`; deployment selection
still chooses managed local, persistent local, remote coordinator, or SLURM
execution. No project scheduler or second submission API is required.

Reuse requires a successful resident readiness qualification with explicit
`readiness.source_roots` covering the installed project code and runtime assets.
That qualification produces `action_reuse_qualified` in the resident descriptor.
An imports-only readiness check, missing qualification, or null node semantic key
executes normally without cross-graph action selection. The protected processor
and actual stage factory remain installed Python targets; captured configuration
cannot install executable code or register lifecycle handlers.

For a dependency-ready node, Loom combines:

- the project's namespaced semantic key;
- qualified project, environment and executor identities, the protected processor,
  and the stage's actual factory target and initialization arguments;
- each input port's original producer commit and artifact reference, including
  native publication closure identity;
- declared output contracts and the retained execution generation.

The current node alias, another node's configuration and renamed upstream edges
do not change this action identity. The application decides which configuration,
scientific data identities and other domain facts belong in its semantic key.
The ordinary capture and audit fingerprints remain unchanged and still identify
the authored graph and invocation.

Within one principal, native authority, run store and installed implementation
scope, a transactional claim selects one producer. Concurrent equivalent nodes
wait for it without allocating attempts. Once it succeeds, the waiting graph
verifies and binds the **original** commit and output facts. It does not copy them
into a new producer commit. A new downstream node can run against that binding.
A successful action remains eligible when another action makes its original
graph fail or the original graph is later cancelled.

The installed processor also implements `operation: verify_result`. The native
request has `schema_version: 3`, the current checked `contract`, an immutable
`candidate`, and `artifact_access`. The candidate contains exactly:

```text
schema_version: 1
candidate_digest: sha256:<native digest>
namespace, semantic_key, execution_key
producer: {run_uri, node_id, attempt_id, assignment_id, fencing_token}
result: {commit, artifact_facts}
output_contracts
installation
access
```

`producer` and `result` always name the original producer. The candidate digest
binds every other candidate field. `artifact_access` is the private read view:
`{mode: read_only, outputs: {output_port: <ArtifactRef data>}}`. Read the refs in
this view; a remote verifier must not interpret an original coordinator URI as
an agent-local path. Loom uses its existing regular-file materialization or
protected shared-publication namespace. Original identities stay in the
candidate even when materialization changes a local URI. Projects with companion
files use their declared native shared closure when verification crosses machines;
a primary JSON file alone is not a transferable declaration of arbitrary files.

The processor checks domain content and returns only one of these exact shapes:

```python
# Domain-specific checks use the current contract and authorized artifact refs.
return {
    "schema_version": 1,
    "candidate_digest": request["candidate"]["candidate_digest"],
    "verdict": "verified",
}

# Or, for a content/contract mismatch:
return {
    "schema_version": 1,
    "candidate_digest": request["candidate"]["candidate_digest"],
    "verdict": "rejected",
    "reason": {"code": "line_count_mismatch", "output_port": "text"},
}
```

A reason code is a bounded lowercase ASCII identifier, not a Loom-maintained
domain enum. `output_port` is null or one declared output. Rejection is retained
with the project namespace and original producer/artifact evidence. Exceptions,
malformed responses, candidate-digest mismatches and attempted lifecycle
instructions fail verification. They are not converted into cache misses.
Loom verifies native authority, checksums/shared closure, scope and retention
before and after the installed callback, then commits a revision-guarded binding.
The callback cannot publish commits, choose producers, authorize retries or alter
cancellation state. Its preparation child uses the existing native dispatch,
committed report and cleanup machinery; it never republishes a target graph.
Native preparation envelope 8 carries fresh generations; envelope 9 carries the
separate action verification request/report. Earlier envelopes remain readable.

To request a new realization deliberately, name the current graph node:

```bash
loom run pipeline.yaml --deployment deployment.yaml --reconcile \
  --operation-id new-realization --fresh-stage author
```

```python
from dataclasses import replace

# request is an ordinary configured RunRequest.
fresh_request = replace(request, fresh_stages=("author",))
```

Each selected node gets a retained native generation before preparation can be
retried. Replaying the same operation ID preserves that generation; a new
operation ID requests another one. Unknown or duplicate nodes fail instead of
silently doing ordinary reuse. This does not change the project's scientific key
or seed. Descendants see the new original input commit, even if its bytes match
the previous result. The previous default-generation result stays available to
ordinary future submissions. Existing `force_stages` and native same-realization
retry retain their separate meanings.

Cancellation detaches a graph's demands. If another live graph still needs a
producer, the exact original attempt remains authorized through the original
run's cancellation barrier; unrelated work receives ordinary cancellation.
The original graph can remain `CANCELLING` while this physical work settles.
When the last demand disappears, settlement is irrevocable: no new waiter can
revive the claim. Native containment and release evidence still govern capacity.
Restart reconstructs these decisions before retained workers resume, and remote
and SLURM grant/start/control paths use the same exact-attempt decision.
If fail-fast terminates a graph with a prepared producer that never started,
Loom records that exact stage and attempt as failed and settles its claim.
Waiters fail explicitly, and native retry can prepare a consistent successor.
A failed shared producer is an explicit failure for waiters; only the existing
native authorized retry/resume may continue that realization. Fresh execution is
the explicit way to request an independent one.

Claims and bindings retain original run evidence through existing preparation
pins. Native shared-publication receipts already protect their primary and
companion closure. Cleanup rechecks these protections before deletion. There is
no automatic action-cache expiry or eviction API in this interface.

An authorized agent control with `cancel_active` is administrative containment:
it revokes continuation for that agent's exact affected attempts even when other
graphs still need them. Those consumers observe the unsuccessful producer; Loom
does not silently replace it. This differs from cancelling one graph's demand.
