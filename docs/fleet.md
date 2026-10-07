# Fleet configuration, administration and self-tests

Install `loom[fleet]` in the operator's Python 3.12 environment. Fleet is generic:
service software, workload profiles and site declarations have separate owners.
`import loom` and Fleet help do not load administration, YAML or workload stacks.

```sh
loom fleet init lab
loom fleet status --fleet lab --connection /PRIVATE/operator.yaml --format json
loom fleet plan --fleet lab --hosts coordinator,gpu01
loom fleet preflight --fleet lab --hosts gpu01 --profile compute
```

`init` creates owner-only directories and owner-readable/writable placeholders at
`$XDG_CONFIG_HOME/loom/fleets/lab` (default `~/.config/loom/fleets/lab`). Complete
the choices before preflight. Repeating init preserves populated files. A
conflicting name/service manager or an unrelated populated destination refuses.
Known local source captures must be supplied with repeatable
`--capture-root /PATH/TO/CAPTURE`: overlap in either direction refuses before any
write. Init has no selected workload and cannot discover remote capture roots;
the shell working directory is not a capture declaration. Keep private files
outside every captured source tree.

The protected `fleet.yaml` contains only selection information:

```yaml
schema_version: 1
name: lab
runtime_release: releases/loom-service.yaml
service_manager: systemd-user
coordinator:
  host: CONTROL_SSH_ALIAS
  config: roles/coordinator.yaml
agents:
  gpu01:
    host: GPU_SSH_ALIAS
    config: roles/gpu01.yaml
```

Paths resolve relative to the inventory. `--fleet` also accepts an explicit
inventory path. `--hosts` accepts comma-separated inventory keys; `coordinator`
is reserved. SSH aliases are not native identities. Agent keys must match
`agent_policy.agents[].agent_id` in the coordinator role. The certificate's DER
fingerprint must map through the native listener's credential map to that
policy. An absent local certificate is unavailable evidence, never a match.
Native role declarations own capacity, devices, concurrency, state/storage paths,
profiles, registration and trust. Fleet does not copy those policies. Native
protected Weave composition and explicit `--env-file` resolution apply; there is
no second template language or implicit shell-environment expansion.

`systemd-user` and `tmux` are explicit choices. Missing systemd prerequisites
never select tmux automatically. Status and preflight perform no SSH or installation, start no native role or
workload, and do not initialize/read private native SQL. Tmux plan and explicit
apply use the SSH setup path described below.
They consume native operator projections. Select an existing protected
`loom.coordinator-client` file with operator credentials and a pinned coordinator
ID using `--connection`. An ordinary client is not granted operator privileges.
Capability/authentication failures retain native error codes and details.

Status separates declarations, native session/capacity, service manager, owner,
installation and storage. Each native observation retains its owner, timestamp,
revision, freshness and availability. There is no atomic fleet snapshot. Without
a connection, status reports unavailable native observations, not an empty fleet.
It can exit successfully while hosts are unhealthy. Status and plan never hash
release wheels or workload images; plan is a preview, not a reservation.

Preflight validates locally accessible protected declarations and immutable
release bytes. It does not call role qualification, construct trusted providers,
or infer remote installation/storage/OS readiness from operator-local paths.
Host prerequisites, service ownership, exact installation/profile compatibility
and remote storage remain explicitly unavailable until target-host tooling
supplies those observations. This phase therefore never reports ready: preflight
returns **2** for failed local validation and **3** for incomplete evidence even
when all local checks pass. Parse the versioned JSON facts for details; ordinary
CLI/configuration errors remain nonzero. Deliberate self-tests use the native
execution path described below. Setup uses the explicit SSH operation described below. Upgrade automation is a
separate lifecycle operation.

## Immutable service bundles

The operator prepares a complete Python 3.12 bundle using ordinary package build
and lock tooling, independently of a research checkout. A descriptor is literal
YAML; its paths must remain inside its directory, including symlink resolution:

```yaml
schema_version: 1
kind: loom.service-release
release_id: service-001
python: "3.12"
requirements:
  path: requirements.txt
  sha256: EXACT_REQUIREMENTS_SHA256
wheelhouse:
  path: wheels
  manifest: wheels.sha256
  sha256: EXACT_MANIFEST_SHA256
```

Use exact `package==version --hash=sha256:...` requirements, including
`loom[fleet]` and every transitive dependency for the selected target. Multiple
hashes and backslash continuations are accepted. Editable, VCS, URL, nested
requirements and installer-option lines are refused. Standard `sha256sum` lines
in `wheels.sha256` name files relative to `wheels/`; every selected wheel must
match its digest and hashed requirement, and the directory must contain exactly
those wheels. Preflight retains the descriptor, requirements and manifest
digests in its result. A release label alone is never immutable identity.

Prepare/build wheels before hashing and freeze all selected bytes. Bundle
verification does not resolve dependencies or prove wheel installation; the
producer must supply the full transitive target lock. A later offline,
hash-enforcing installer checks dependency compatibility using Python 3.12 and
uv on the host. Host Python/uv/OS services are prerequisites; Fleet does not
install drivers, use sudo, resolve packages over the network or update a live
environment. Workload Python/SIF profiles and their source/environment/image
identity remain native configuration, separate from this service bundle.

To compare against a retained local release descriptor, pass
`preflight --previous-release /RETAINED/release.yaml`. Equal labels with different
immutable bytes refuse. Fleet has no release registry; without a retained
comparison input it cannot know whether a label was used elsewhere.

## Connection-only client export

Export from an existing protected native selection once its connection,
preparation source and profile are bound:

```sh
loom fleet export-deployment --fleet lab --hosts gpu01 \
  --deployment /PRIVATE/selected-deployment.json \
  --output /PRIVATE/clients/compute-v1.json \
  --capture-root /PATH/TO/CAPTURE
```

The output directory must already exist and be owner-only. The selected native
role must declare the preparation profile. The existing `loom.deployment` codec
writes a new protected file containing only the pinned connection, unchanged
source/profile binding and timing policy. It omits coordinator/agent launch
roles and creation bindings, so the exported selection cannot bootstrap roles.
A `loom.coordinator-client` file remains a connection file, not a deployment
selection. Old selections are never overwritten: choose a new versioned output
for a new source/profile binding. Export is an explicit local write; it does not
prove remote profile installation, qualification or authorization.

## Deliberate infrastructure self-tests

`self-test` runs finite native jobs against an explicitly selected existing agent
and shared workload profile. It starts no service and performs no installation.
The profile's workload must contain `loom.fleet.probes.ProbeStage` (and Torch with
CUDA UUID properties for the optional GPU check), support native preparation,
and declare shared publication storage. For container execution, the captured
snapshot root must lie beneath exactly one declared shared root so native
preparation can mount it. Its source must contain a minimal `fleet-check.yaml`
with `pipeline` and `runtime` mappings. Fleet replaces those
mappings with the fixed probe configuration using ordinary captured overrides.
A project preparation processor, when configured, must accept those generic
stages. Normal native policy and maintenance admission remain authoritative.

```sh
loom fleet self-test --fleet lab --agent gpu01 \
  --deployment /PRIVATE/client-deployment.yaml \
  --connection /PRIVATE/operator-connection.yaml --checks cpu,storage,gpu
loom fleet self-test --fleet lab --operation-id check-RETURNED-ID
```

The deployment and operator connection must pin the same coordinator. They use
separate client and operator credentials; self-tests grant no new privileges.
The profile comes from the deployment's explicit native preparation binding.
Multiple inventory agents require `--agent`. Default manual checks are CPU and
storage; GPU is explicit and requires declared GPUs. A subset only establishes
the requested checks, never fleet-wide readiness or scientific qualification.

CPU sums integers 0 through 9999, expecting 49,995,000. Storage publishes exactly
65 MiB with byte `i` equal to `i % 251`. The operator fetches the complete native
shared declaration and independently checks all bytes and the complete digest.
GPU multiplies float32 matrices `[[1,2],[3,4]]` and `[[5,6],[7,8]]` on CUDA device
zero, synchronizes, and expects `[[19,22],[43,50]]`. Its observed CUDA UUID must
match the actual native parent-owned launch binding. Torch imports only inside
the workload function. Missing Torch or UUID observation yields
`unsupported_check`; environment/model-name assertions cannot qualify a GPU.

Success also requires matching run, stage, agent, session and immutable profile,
native terminal acknowledgement, exact provider-release proof, and a current
post-release offer. Native terminal success alone is insufficient. External
GPU occupancy or retained claims report waiting. GPU observations are limited
to infrastructure and cannot establish scientific accuracy or throughput.

Protected receipts live beside the inventory in `checks/<operation-id>` outside
selected source captures. Immutable native requests and dispatch markers are
fsynced before sending. Reconnection observes the exact IDs; if the native owner
has no accepted request, it replays only the retained identical request under
native idempotency. Selected requests are dispatched before result downloads,
so a storage download deadline cannot prevent another check from reaching the
native queue. Native admission and capacity still govern when each job runs.
A confirmed failed result stays failed. An explicit new
attempt uses `--retry-of check-FAILED-ID` together with the original selection
arguments and receives new identities linked to that failure. It does not retry
old work. A changed session/profile cannot qualify an old operation.

`--timeout` bounds observation and detaches without cancellation or replacement.
Each stage uses the native 120-second execution timeout; timeout does not prove
process death or release. Keep the printed IDs to observe remaining work.
Version-one JSON and text report `passed`, `failed`, `waiting`, `unsupported`, or
`not_requested` for each check, with native failure codes and the next action.
Exit codes are 0 (requested checks passed), 1 (confirmed failure), 2
(waiting/unknown), and 3 (unsupported). `ready` remains false because these checks
alone do not qualify a complete installation.

Older native reports without parent-owned launch UUID evidence remain
incomplete. Current reports carry this optional evidence through the existing
native result channel; the operator projection never substitutes requested
resources or reads worker-authored metadata as native allocation proof.

## SSH setup and continuation

For setup select `service_manager: tmux` or `systemd-user` explicitly. Fleet uses only configured
SSH aliases and their existing authentication/host-key policy; aliases cannot
contain SSH options or shell syntax. Each host must already provide Python 3.12,
uv, OpenSSL, findmnt and the selected service manager. Native state and IPC must be on a supported local
filesystem; a directory beneath an NFS home is insufficient. Workload software,
shared mounts and the selected resident Python or SIF profile must already exist.
Tmux keeps services detached from the operator connection and promises **no boot
startup**. Systemd setup uses the managed lifetimes below; runtime/profile changes
require their explicit lifecycle paths. The completed setup result reports
`boot_start: true` for retained systemd-user selections and `false` for tmux.
This describes configured boot-start wiring; it is not evidence of physical
boot or reboot qualification.

Setup requires an immutable offline service bundle and an explicit native
`loom.deployment` selection for the synthetic probe source/profile. For a fresh
coordinator, use its native automatic-creation selection with the inventory's
coordinator role and an explicit binding path. Fleet only reads that selection;
it never launches its roles on the operator. Select the base probe config with
`--config`. Existing fleets use an already pinned connection-only deployment
and a separate pinned operator `--connection`.

```sh
loom fleet plan --fleet lab --issuer /LOCAL/PRIVATE/issuer
loom fleet apply --fleet lab --operation-id setup-001 \
  --issuer /LOCAL/PRIVATE/issuer --deployment /PRIVATE/probe-selection.json \
  --config fleet-check.yaml
loom fleet operation status setup-001 --fleet lab --format json
loom fleet operation resume setup-001 --fleet lab
```

The issuer path belongs to the **coordinator host**. It explicitly selects its
protected `ca.crt` and `ca.key`; Fleet never guesses the CA key from a certificate
path. Only genuinely fresh unbound setup can create new signing material.
Add-host issuance must match the existing client CA. Missing bound keys/roots
block recovery rather than being regenerated. With complete preissued matching
credentials, no issuer is needed for steps that require no issuance.

Fresh client and operator leaf identities must select already-authored native
principals with those respective roles. Unique choices are selected directly;
use `--client-credential-id` and `--operator-credential-id` when ambiguous. Setup
adds only their certificate fingerprints, preserving every declared scope.
Their private keys remain in protected operator-local files; workers generate
and keep their own keys; the CA key stays coordinator-local. Only public CSRs and
certificates cross SSH. Pending fresh bindings are shown honestly in plan; the
completed native declaration is validated before initialization. After native
initialization, Fleet exports versioned connection-only selections pinned to the
actual coordinator ID and reports their paths.

To add an inventory entry, select it explicitly and reuse the exported deployment
and operator connection. The coordinator is an explicit preview dependency for
enrollment/reload even when only the worker is selected:

```sh
loom fleet apply --fleet lab --hosts gpu02 --operation-id add-gpu02 \
  --issuer /LOCAL/PRIVATE/issuer --deployment /PRIVATE/EXPORTED/deployment.json \
  --connection /PRIVATE/EXPORTED/operator.json --config fleet-check.yaml
```

Plan is read-only and reserves nothing. Apply verifies the exact offline bundle,
retains protected intent and dispatch markers in `operations/<operation-id>`, and
rechecks inputs before mutations. Native roots, resource ceilings, GPU selection,
profiles and scheduling reload identities retain their native meanings. An
unknown SSH reply leaves the operation waiting. Resume observes retained host
receipts and native identity before continuing; it never allocates replacement
self-tests. Confirmed failed or unsupported checks block completion. Inventory
removal does not retire or uninstall a host.

Status reads retained administrative evidence without contacting or repairing a
host. Operation outcomes use `pending`, `running`, `waiting`, `blocked`, and
`complete`; CLI exits are 0 for complete, 2 for pending/running/waiting, and 1 for
blocked. Changed inputs require a new reviewed intent; a missing bound database
requires explicit recovery. Completed receipts remain inspectable. Setup is
complete only after fresh native resources and the relevant existing CPU,
storage and GPU self-tests pass. This is infrastructure evidence, not scientific
qualification. One operator and one active writer per operation are supported.


## Managed native service lifetimes

`systemd-user` requires a running current-user manager and approved lingering.
Fleet checks these prerequisites and discovers the owner-protected
`/run/user/<uid>` bus for SSH sessions without `XDG_RUNTIME_DIR`. Missing policy,
manager, local state or required shared resources refuses without selecting
another backend. Fleet never enables linger, invokes sudo or provisions mounts.
An administrator must supply missing manager/linger and mount prerequisites.

A pure coordinator gets one unit. An agent gets distinct agent and native
supervisor units, with distinct control groups. The agent waits for the native
supervisor's readiness notification and uses `queue agent-serve
--external-supervisor`. It cannot spawn a replacement supervisor or stop the
supervisor on application exit. Agent failures may restart automatically; the
supervisor has no automatic same-boot restart. Its existing authenticated
protocol, launch identities, containment and shutdown rules remain authoritative.
Units use normal control-group killing; they never use `KillMode=none`.

`queue agent-supervisor-serve ROLE [--env-file ENV]` is the foreground native
supervisor entry point for an already initialized resident agent. Startup holds
native ownership locks, checks existing state, and refuses missing databases.
Positive changed Linux boot/root evidence permits native reboot containment;
same-boot owner loss cannot adopt a PID or declare clean continuity. Interrupted
work does not become success. The agent reconciles retained sessions, results
and claims before advertising new capacity. Supervisor/service replacement
requires native settlement and a clean stop. Service-manager forced termination
can leave uncertain ownership and must be recovered through native operations.

Fleet retains one protected `service.json` under the host administrative root
and immutable unit files under its `units/` directory. These bind backend,
role/configuration paths and expected root/coordinator IDs; native databases
continue to own assignments and execution. Enabled user-unit links target these
files. Removing inventory entries does not remove units or their retained state.
The boot readiness command checks bound roots and declared resource paths before
native startup; it never initializes an empty replacement. A missing resource
leaves readiness failed, requiring the resource to be restored and startup
retried explicitly.

A retained tmux deployment migrates only after native admission/work is drained,
pending polls settled, and the communication services and tmux sessions stopped.
Choose `systemd-user` in the inventory, then run:

```sh
loom fleet migrate-services --fleet lab --operation-id service-migration-001
loom fleet operation status service-migration-001 --fleet lab
loom fleet operation resume service-migration-001 --fleet lab
```

The migration retains expected native IDs and per-host request receipts. Live,
retained or uncertain ownership refuses; a timeout never escalates to killing a
service. It does not retire sessions, reset roots or change runtime/profile
bindings. A repeated intent resumes the same selection; changing inventory or
role inputs conflicts. Ordinary apply never performs an implicit migration.

Physical support requires `tests/fleet_acceptance/test_managed_services.py` on
explicitly selected disposable hosts. Controlled software tests do not qualify
installed systemd/cgroup, logout or reboot behavior. No installed versions or
physical lifecycle cases are qualified by the implementation itself. The
installed owner records versions, exact identities, cgroup separation and
owned-process cleanup. Operator SSH logout and disappearance of a last logind
session are recorded distinctly when host PAM policy does not create sessions.
