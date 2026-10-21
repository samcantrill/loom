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
  env_file: machines/control.env  # optional
agents:
  gpu01:
    host: GPU_SSH_ALIAS
    config: roles/gpu01.yaml
    env_file: machines/gpu01.env  # optional, distinct machine values
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

Each optional `env_file` references an existing owner-protected native environment
file, resolved relative to the inventory (absolute paths are also supported).
The coordinator and each agent use their own file, including coordinator policy
and agent certificate binding, SSH requests, self-tests and service/workload
maintenance. Entries without a binding retain command-level `--env-file` behavior.
An explicit global file that differs from a declared binding refuses before
observation dispatch or effects; it never substitutes another host's values.
Administrative operations retain these selected files and hashes in their existing
intent: changing a bound file or its inventory reference blocks mutation replay.
Version 1 inventories without the optional field remain compatible; older strict
Fleet parsers reject the new key, so consumers must upgrade before adding it.

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

Build a bundle from a clean Loom Git checkout and its existing lock:

```sh
loom fleet build-release --source /CLEAN/LOOM --output /RELEASES/new-release
```

Run with Python 3.12 on a builder matching the deployment platform. The output
parent must exist; the output directory must be new. The helper exports the
locked Fleet dependency closure, builds real wheels (including pinned VCS
dependencies), and writes exact hashed requirements. It then installs the bundle
offline into a new environment, checks dependencies and imports the native host
entry point before publishing `release.json`. Point the inventory's
`runtime_release` at that descriptor. It does not install or restart a fleet.

`build-receipt.json` records the source commit/tree/lock, platform, packaging
tools, release hashes and offline installation result. Use published source
revisions for deployment. Different build toolchains may produce different wheel
bytes; the retained hashes identify this exact build. A failed build retains its
private log and partial artifacts without a successful receipt or published
descriptor. Select a new output directory when retrying.

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

GPU qualification has two explicitly different scopes. Set the optional
top-level fleet inventory field to use a minimal capability check:

```yaml
gpu_qualification: nonexclusive
```

This policy applies to newly created self-tests and upgrade operations. It runs
the fixed 2×2 CUDA matrix multiplication in the selected resident runtime on one
healthy declared GPU, even when that device is occupied. The device UUID,
numerical result and process containment must match. It neither acquires nor
modifies scheduler GPU claims. Busy GPUs do not cause a capacity wait; allocation,
driver, timeout and cleanup failures still fail the check. The receipt explicitly
reports `exclusive_scheduling: not_tested`.

CPU and storage checks still use native scheduled jobs. Normal workload resource
policies and external-process occupancy handling are unchanged. Use
`gpu_qualification: exclusive` (also the default when omitted) to exercise GPU
assignment, execution and release through the scheduler. Retained operations
keep their original policy; editing the inventory does not reinterpret existing
receipts. Install a service release supporting this field before enabling it.
The policy qualifies capability, not performance or spare GPU memory.

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
post-release offer without the probe's reflected claim. Native terminal success
alone is insufficient. If fresh native resource status shows that an external
process subsequently occupied the exact released GPU, the completed check can
pass while that GPU remains unavailable for scheduling. Unknown observations,
retained claims and unproven release still wait.
An operator can explicitly defer execution checks for selected upgrade agents:

```sh
loom fleet operation defer-checks image-upgrade-1 --fleet lab \
  --agent-id busy-worker --reason "Operator defers this host until GPU capacity returns"
```

For a new upgrade, use `upgrade --apply --defer-checks-for busy-worker
--qualification-reason "..."` with the normal target arguments. The protected
operation retains the selected agents and reason against its original intent;
exact replay is supported, conflicting changes are refused. The default still
checks every consuming agent. This exception skips only execution qualification:
installation/source checks, ownership, promotion, native settlement and policy
restoration remain required. It does not cancel any previously admitted probe.
Cancel that exact probe through the existing native run cancellation command
when needed, then resume the same upgrade after its effects settle.

Completion with an exception reports `qualification.state: partial`, including
the deferred agents and reason. Prior passing/failed/cancelled check evidence
remains unchanged; deferred checks are never reported as passed. Follow-up
qualification uses the ordinary explicit self-test command. An upgrade exception
is not an automatic scheduling exclusion; place jobs on qualified agents.
Deferral is unavailable once a runtime upgrade has bound a separate workload
repair; it is rejected explicitly rather than changing a parent policy that
would leave the repair's checks unchanged.

Upgrade qualification selects a GPU probe when either the resident profile or
the retained native resource inventory declares GPUs, including NVIDIA provider
discovery. Occupancy before execution prevents dispatch until capacity is available.
GPU observations are limited
to infrastructure and cannot establish scientific accuracy or throughput.

Protected receipts live beside the inventory in `checks/<operation-id>` outside
selected source captures. Temporary artifact downloads use the operator's system
temporary directory (honoring `TMPDIR`) and are removed after verification.
That temporary filesystem must support Linux atomic non-replacing directory
publication; the receipt directory may reside on NFS independently.
Immutable native requests and dispatch markers are
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

The coordinator and separate resident agents may share an SSH host. Give each
role a distinct configuration, credentials and non-overlapping native root;
Fleet retains separate installations, locks, service ownership and operation
receipts for those roots. Declare non-overlapping resource budgets and GPU
devices when multiple agents share a machine: Fleet does not partition physical
capacity between independent agents. Use the same SSH alias for colocated roles
so setup can reject overlapping roots before dispatch.

For setup select `service_manager: tmux` or `systemd-user` explicitly. Fleet uses only configured
SSH aliases and their existing authentication/host-key policy; aliases cannot
contain SSH options or shell syntax. Each host must already provide Python 3.12,
uv, OpenSSL, findmnt and the selected service manager. Native state and IPC must be on a supported local
filesystem; a directory beneath an NFS home is insufficient. Workload software,
shared mounts and the selected resident Python or SIF profile must already exist.
For tmux, the generated socket path must fit Linux's 107-byte pathname limit.
Tmux keeps services detached from the operator connection and promises **no boot
startup**. Systemd setup uses the managed lifetimes below; runtime/profile changes
require their explicit lifecycle paths. The completed setup result reports
`boot_start: true` for retained systemd-user selections and `false` for tmux.
This describes configured boot-start wiring; it is not evidence of physical
boot or reboot qualification.

Service startup retains one launch attempt under the host operation. Its first
observation waits up to twenty seconds; a process still starting returns
`waiting` with `service_starting`, without publishing a completed host receipt.
Continuing the same operation observes that launch rather than starting another.
The three-minute readiness deadline is retained against the Linux boot and
monotonic clock, so restarting the operator does not extend it. Tmux binds the
session marker and process start identity; systemd binds the unit invocation and
native process identity. A failed launch, changed owner/boot or expired readiness
deadline blocks with an explicit reason. Inspect the protected service log and
native ownership before recovery; continuation never silently replaces a failed
launch. Systemd's configured service restart policy remains its own responsibility.

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

Select the service manager when creating a fresh installation. Existing bindings
must keep their selected backend. Backend changes require a fresh installation;
there is no service-manager conversion command.

Physical support requires `tests/fleet_acceptance/test_managed_services.py` on
explicitly selected disposable hosts. Controlled software tests do not qualify
installed systemd/cgroup, logout or reboot behavior. No installed versions or
physical lifecycle cases are qualified by the implementation itself. The
installed owner records versions, exact identities, cgroup separation and
owned-process cleanup. Operator SSH logout and disappearance of a last logind
session are recorded distinctly when host PAM policy does not create sessions.

## Unsupported installations

Fleet manages fresh installations and current-format retained installations.
Historical installation adoption and inventory conversion are unsupported.
Settle work with the installation that owns it, verify release and containment,
stop its services, and preserve its roots and receipts. Create fresh roots with
the current runtime and regenerate client bindings. Qualify current CPU/storage
and declared GPU behavior before enabling submissions. The new runtime does not
read or convert the retired installation's operational state.

## Whole-fleet service runtime upgrades

`loom fleet upgrade --fleet lab --runtime-release releases/next.yaml --plan`
previews the whole declared fleet. Omission of `--apply` is read-only. Explicit
`--apply --operation-id upgrade-018` prepares isolated immutable candidates on
every host, closes native admission, waits for admitted pipelines and settlement,
conditionally drains agents, replaces services offline, and runs native checks
before restoring the previous drain policy and reopening. Accepted later DAG
stages continue before drain. Timeout detaches; it never cancels or force-kills.
Partial/rolling upgrades and post-replacement rollback are unsupported.

When a communication-runtime defect prevents publication of an already
successful worker result, `--recover-retained-results` explicitly selects a
bounded alternative sequence for a runtime upgrade. It closes admission and
acknowledges conditional drains first. Each resident agent must prove its
retained deliveries have durable successful results, matching session/fence and
supervisor launch identity, positive containment and successful exit, unchanged
worker-result bytes, and completed temporary-storage cleanup. Pending polls,
controls, diagnostic probes, live or pre-result workers, and Slurm roots refuse.
The coordinator matches every outstanding remote assignment/reference against
that cohort; preparation, cancellation and startup mutations also refuse.

The operation retains that exact cohort before any stop. Native stop and locked
replacement recheck it; a later new or changed result cannot join the operation.
This is recovery eligibility, **not settlement**: claims and journals remain
intact for ordinary startup replay. Both communication runtimes are replaced
without changing workload source, profiles, images or native roots. Agents stay
drained until their retained results settle, then resume to finish already
admitted downstream stages. Global settlement and the usual native checks are
still required before policy restoration and admission reopening. Resume the
same operation after interruption. Ordinary upgrades retain their strict
settled-work sequence.

The stopped-role guard accepts only the current v6 supervisor journal. It
verifies identity, host, containment and clean-shutdown evidence without
rewriting the journal. Older journals are rejected before contacting their
supervisor; they cannot be opened or upgraded by the current runtime. Settle
work with the original owner, retain its receipts and create fresh current
roots. Current v6 roots retain their identity across service replacement.

Supply `--deployment` (connection-only shared-source selection), `--connection`
(protected operator connection), and source-relative `--config` for checks.
Retained completed setup bindings can supply the first two. Every agent uses its
single declared profile. CPU/storage checks are mandatory; profiles declaring
GPUs additionally run GPU checks. The source must support
`maintenance-admission-v1`, `operator-observations-v1` and
`conditional-agent-control-v1`. Candidate capability is separately checked after
offline installation and before gate closure. Preview reports that installation
as outstanding; it never qualifies uninstalled bytes. Candidate storage/profile
and image checks are repeated at mutable boundaries. Fleet never updates a live
environment in place or overwrites retained installation evidence.

Use `loom fleet operation status upgrade-018 --fleet lab` to inspect retained
intent, or `resume` to continue it. Resume accepts no retargeting options. An
interrupted request keeps its ID and native mutation outcome; observation or
exact replay resolves it. A failed check remains failed on ordinary resume.
After correcting its cause without changing the target, explicitly select a
successor with:

```sh
loom fleet operation retry-check upgrade-018 --fleet lab \
  --failed-check check-017 --operation-id check-019
loom fleet operation resume upgrade-018 --fleet lab
```

The predecessor must be a confirmed native terminal failure with no outstanding
native effects. The successor is appended to the same maintenance history and
receives exact operator authorization before dispatch. Prior failure evidence
remains. Another active successor, different target/owner or unsettled prior
attempt refuses. Only the latest explicitly selected settled pass satisfies a
slot, and all slots must pass before the gate reopens.

New upgrades prepare each selected CPU/storage/GPU probe in its candidate
installation before closing admission. This uses the real captured source,
preparation policy and installed project hook, including a candidate profile that
has not yet been advertised. It does not execute the workload or publish a target
run. The probe's report is temporary; bounded compatibility evidence is retained
in the existing exact host-operation receipts and reused on continuation.
Check selection considers preparation aliases for the selected resident profile;
submitted-container aliases may coexist and are excluded from that selection.
An explicit matching alias takes precedence. Otherwise there must be exactly one
matching resident alias; a missing or ambiguous selection still refuses.
Shared container preflight mounts the selected immutable capture, declared
read-only locations and root challenges, using the same namespace projection as
ordinary preparation. An incompatible profile or malformed recipe leaves
admission open and services unchanged. Abort that unactivated operation, correct
the selection/source and start a new operation; captured evidence is immutable.

If an older runtime upgrade has already replaced its services but cannot select a check
preparation profile, or its selected project preparation rejects a generic
probe, correct that selection explicitly before checks or after all prepared
checks have confirmed terminal failures and their native effects have settled:

```sh
loom fleet operation repair-check-selection upgrade-018 --fleet lab \
  --deployment /shared/current-infrastructure-checks.json
```

The new deployment must equal the original parsed selection except for its
preparation profile, which must match every upgraded agent's declared resident
profile. The operation retains the original intent and native maintenance gate,
binds the candidate bytes in one immutable repair receipt, and resumes ordinary
checks and policy restoration. It refuses changed source/connection/timing,
conflicting repair replay, an unowned or unsettled gate, and active or successful
prepared checks. Failed check intents, results and deployment selections remain
unchanged; repaired successors use a separate retained selection. After repairing
a failed check, explicitly use `retry-check` as above to authorize its successor.
The repair does not promote workload source/images or waive qualification.

If the installed runtime has changed its preparation-report contract, an older
workload image may be unable to pass those checks. Keep admission closed and
build a compatible immutable image separately. After a confirmed native check
failure, the existing runtime operation can promote that image inside its own
maintenance window:

```sh
loom fleet operation repair-workload upgrade-018 --fleet lab \
  --workload-profile analysis --image /shared/images/analysis-v2.sif
# Add --workload-inventory /PRIVATE/candidate/fleet.json to promote source too.
loom fleet operation resume upgrade-018 --fleet lab
```

This bounded recovery requires all declared services to be live on the exact
runtime target, unchanged native roots, settled work and the original gate owner.
The selected profile must cover every upgraded agent. It retains a separate
immutable workload intent under the parent operation's `workload-repair/`
directory; the runtime intent and failed check evidence are preserved. The old
settled-check authorization is revoked before promotion, without erasing results.
The maintenance gate stays closed under its original owner. Ordinary
native workload promotion owns source publication and interruption recovery.
Fresh CPU/storage and declared GPU checks qualify the resulting service/image
combination. Only their settlement permits restoration of the policy from before
the runtime upgrade and reopening of the original gate. No report-format fallback,
new service replacement, rollback or temporary admission opening occurs.

Repeat `repair-workload` only with the same target, or use ordinary parent
`resume`. Once bound, parent `retry-check` and `retry-control` address the repair's
checks and controls. Existing abort restrictions still apply after service
replacement. A narrower selected-profile repair and changing a retained repair
target are unsupported.

A resume control can also fail with `retained_work`. Resolve the underlying
native recovery first and keep the maintenance gate closed. Ordinary operation
resume replays the failed control; it does not erase that result. Select a new
conditional control explicitly:

```sh
loom fleet operation retry-control upgrade-018 --fleet lab \
  --failed-control upgrade-018-worker-checks-capacity \
  --operation-id upgrade-018-worker-resume-recovered
```

This requires an acknowledged `retained_work` failure belonging to the operation,
the same drained agent/session/configuration and latest policy control, and
settled coordinator and host effects. It preserves the failed intent and receipt.
The successor atomically requires that failed control as its predecessor; an
independent policy edit refuses it. Repeat the exact retry command after a lost
reply, or use ordinary operation resume once the successor is retained. No role
restart, runtime retargeting or work cancellation is performed by this command.

Upgrade qualification dispatches all eligible host/check attempts before observing
their results, using at most three independent controller workers. Native resource
claims still determine execution concurrency. Pending checks do not prevent other
eligible hosts from progressing, and failed attempts still require explicit retry.
Exact check-retry replay recognizes the retained successor after completion even
when ordinary admission has already reopened.

Upgrade continuations observe checks without waiting for each run to finish;
each observation has a bounded transport budget. Standalone self-tests retain
their waiting behavior. A failed check can therefore be reported while another
already-dispatched check is still running. Retry and repair still require native
settlement, and explicit deferral preserves every dispatched attempt's history.

Independent candidate installations, qualification probes, check preparation,
agent stops and agent replacements use a pool of at most three host transports. All requests are retained
before dispatch, and the controller alone publishes their receipts. Workload
staging completes across eligible agents before native promotion. The current
promotion owner requires global control settlement, so each promotion must be
acknowledged before another is submitted. A pending promotion returns waiting;
it must not cause a refused speculative submission to another agent. Coordinator
publication and revision-sensitive controls keep their ordering. Lost replies
resume the same retained requests. Concurrent promotion would require a separate
change to that native authorization contract; host transport concurrency does
not grant it. Runtime replacement waits for all agents to stop before stopping
the coordinator, establishes coordinator readiness, then dispatches independent
agent replacements. All required agents must be ready before check capacity is
enabled. A pending or failed host preserves successful peers' receipts; continuation
uses the same requests and retained startup deadlines.

Initial drain and check-capacity resume controls are submitted to independent
agents before waiting for all acknowledgements. Each retains native session and
predecessor conditions. A pending acknowledgement does not prevent another agent's
control submission; a substantive failure still blocks progression. All required
acknowledgements and current policy observations form a barrier before the next
phase. Restoration still respects intervening operator policy, and promotions
retain their stronger global-settlement ordering.

Candidate qualification is retained against the upgrade intent. Waiting
continuations inspect current roots, owners, capabilities and declarations without
repeating full preparation. Runtime replacement and workload activation still
verify their mutable inputs. Successful self-tests retain verified artifact
contents for the exact publication; current assignment/agent and release evidence
is reobserved. A new publication or attempt requires fresh verification, including
the complete 65 MiB storage payload.

An apply invocation can retain its own preview qualification only when the
bound intent matches its host, root, declaration, runtime, profile and image
inputs. Current ownership, composed inputs and activation checks remain required.
An external preview followed by a later apply does not carry this transient proof.
Routine automation may omit the standalone preview: apply performs its own
qualification before maintenance. Select a runtime upgrade only for a changed
service runtime, and a workload upgrade for a changed execution image/profile.

The candidate host qualifies an agent configuration once per replacement action,
derives native preflight findings from that same service object, and passes it to
the native replacement guard. Its observed image digest is reused within that
boundary. The guard rereads protected declarations and refuses changes since
qualification. No qualified object crosses a process boundary. Later startup,
promotion and resume still perform their own qualification; staging/activation
still detect changed image bytes. This is not a persistent qualification cache.

Pending check results reuse native run explanations and retain their owner facts.
`waiting_for_capacity` requires current scheduling evidence; preparation, running
assignments, durable results awaiting publication, and cleanup have distinct codes.
Missing or stale evidence yields `check_pending_unknown`, never a capacity claim.
These are observed states, not measured execution or publication durations. A native
`BLOCKED` admission is a failed check requiring explicit repair/retry, not an endless
capacity wait. Successful observations reuse their existing admission detail instead
of making the same owner query twice.

Best-effort action diagnostics append to `timings.jsonl` in the native fleet
operation directory. Records identify an invocation, action, host when known,
UTC start, monotonic duration and outcome. They expose qualification, startup,
RPC and artifact-transfer costs without changing the existing progress schema.
They do not authorize transitions or replace operation receipts. Parallel/nested
spans overlap; their sum is not deployment wall time, and a missing diagnostic
record does not prove that no work occurred.

Qualification additionally exposes `interpreter_probe`, `installation_probe` and
`qualification_image_hash`. `signal_to_exit` measures actual termination separately
from preceding qualification. `launch_to_readiness` spans the retained dispatch
through first observed readiness across continuations, without resetting its
deadline or relaunching. Older retained launches without dispatch timestamps omit
this diagnostic. Queue qualification within a host action joins its existing trace;
standalone service processes write bounded `loom.phase_timings` JSON diagnostics to
stderr. `control_application` and its nested probes include the existing control
operation ID. These diagnostics contain no request bodies or environment values,
and observation/write failures do not change native outcomes or acknowledgements.

Operator RPC spans identify both host and native action (`rpc_<action>`). The
classified span is nested inside `host_rpc`; it must not be added to the aggregate
as extra elapsed time. Request bodies and credentials are not recorded.

Python release drivers use `Inventory.environment_files(override=None)` for
the same environment selection as native commands, without repeating host
qualification. `operation_status(inventory, operation_id, missing_ok=True)`
returns `None` only before a native intent exists; its default remains strict.
`loom.fleet.ssh_operations.operation_evidence(inventory, operation_id)` exposes
read-only diagnostic timings, close/open maintenance receipts, and retained
check result receipts. Missing receipts remain absent; partial diagnostic lines
are reported in `issues`. This non-atomic evidence never authorizes an upgrade,
recovery or qualification decision. Native status and self-test APIs own those
decisions. Consumers must not parse private receipt paths or import private
helpers to obtain this evidence.

Resident workers retain bounded `native_timings` in executor metadata before the
first immutable worker-result write. Input/preparation materialization and worker
execution are measured in their owning process. Native spans use integer
`elapsed_nanoseconds`, a UTC `started_at`, an action and outcome; the agent event
protocol does not admit floating-point numeric values. A `dropped_spans` count
identifies bounded capture loss. Nested spans overlap.

Current execution reports retain the redacted container command even when its
bind and environment options exceed 64 arguments. The flat string list at
`executor_metadata.command` uses the existing 64 KiB message budget; other
executor metadata keeps its existing collection and nesting limits. This also
applies when an execution report travels through the Slurm relay.

Output retention appends separate `native_timing` workspace events, transported by
the existing event stream. Repeating output retention preserves the exact terminal
report and worker-result bytes. Assignment observations expose the worker spans and
up to 256 retained publication timing events, with explicit limit evidence. These
events include output retention, output declaration/transfer and terminal
acknowledgement. The remote assignment owner measures the actual cooperative work
and flushes its timing events after commit, before provider release. Shared outputs
need no payload upload; their declaration still crosses the transfer boundary.
Durations include network/cooperative waits on the agent clock and do not represent
CPU busy time. Diagnostic write failure does not change the native result.

Maintenance mutation receipts retain coordinator UTC `applied_at` on first
application. Exact replay and coordinator restart preserve that timestamp, allowing
a release report to join matching close/open controls without using driver process
uptime. Old receipts can lack it; consumers must leave that interval unavailable.
Native upgrade results also expose concise current `check_observations` and the
current `reason_code`. A release driver can associate its measured backoff with
those reasons without claiming the native state persisted throughout the interval.

Coordinator action resolution emits best-effort deferred `stage.reuse_timing`
events for contract loading, lookup, artifact verification, authority reads/binding
and installed-verifier observation. They are appended after revision-guarded work.
The event links the exact installed verifier operation and child run, whose worker
result carries the actual materialization/execution durations. A pending verifier
observation is not a measurement of the child's execution. Missing timing evidence
does not change native acceptance or justify inventing a zero duration.

`operation abort` restores only controls still owned by that operation, using
native atomic expected-predecessor guards. An independent applied control
conflicts even if its drain value matches. Before closure abort has no native
effect. During settlement/drain it unwinds reversible owned changes and opens
the gate; after the first retained stop/replacement intent it refuses automatic
rollback. A lost restoration reply replays the original acceptance without
reapplying policy over later controls. Completed operations report completion.

### Current storage and source capabilities

Runtime replacement requires coordinator schema 19, agent schema 12 and complete
current tables; the supervisor requires schema 6. The candidate refuses old or
incomplete roots before schema repair or role-lock creation. There is no offline
schema upgrader, installation adoption or manual intermediate-version bridge.
The source must already supply the required maintenance and conditional-control
capabilities. Unsupported installations follow the fresh-root procedure above.

Current compatible replacement preserves native identity and retained work. The
host verifies candidate bytes, native owner and settlement, then holds
`service_replacement_guard(service, expected_root_id)` while replacing its binding.
The guard retains supervisor clean-stop/containment checks and refuses unsettled
work. It performs no schema conversion. The existing runtime upgrade owns
qualification, conditional policy restoration and admission reopening.

### Selected workload image upgrades

`loom fleet upgrade --fleet lab --workload-profile analysis --image /shared/images/analysis-v2.sif --plan`
qualifies the exact immutable image bytes and native profile on every consuming
agent. Supply the absolute existing SIF path; Fleet never builds or deletes it.
The current coordinator and consuming agent processes must advertise
`quiescent-profile-promotion-v2` as well as maintenance and conditional-control
support. If they do not, first complete a separate explicit `--runtime-release`
upgrade. Workload promotion preserves that exact service descriptor.

Add `--apply --operation-id image-upgrade-1` with the existing `--deployment`,
`--connection`, and `--config` selection. Fleet closes ordinary admission, waits
for admitted work and native settlement, conditionally drains consumers, stages
qualified candidate sources, and asks native promotion to change the selected
binding. Native intent owns canonical source publication and interrupted binding
recovery. Original roots, credentials, retained runs and launch history remain.
The coordinator publishes a new preparation generation, and native CPU/storage
checks (plus declared GPU checks) use a new connection-only deployment exported
inside the operation directory. The result's `deployment` is the new selection.
The old selection remains readable and refuses new submissions after promotion.

Use `loom fleet operation resume image-upgrade-1 --fleet lab` to continue the
same immutable operation after a lost reply or stopped service. An abort is
available before the first selected source/promotion intent. Later interruptions
require continuation; no automatic image rollback occurs. Failed terminal checks
use the same explicit `operation retry-check` successor interface as service
upgrades. Repeating a completed operation returns its retained result.

### Selected workload source promotion

Image-only promotion keeps the authored project and source paths. To select
retained source directories as well, add a protected candidate inventory:

```sh
loom fleet upgrade --fleet lab --workload-profile analysis \
  --image /shared/images/analysis-v2.sif \
  --workload-inventory /PRIVATE/candidate/fleet.json \
  --deployment /PRIVATE/current-client.json \
  --connection /PRIVATE/operator.json --config pipeline.yaml --plan
```

Apply the same selection with `--apply --operation-id source-upgrade-1`.
The candidate uses the ordinary Fleet inventory and native role formats. Its
role files must be separate siblings of the current role files, preserving the
relative path frame. Keep host aliases, native roots, explicit environment files,
runtime release and service backend unchanged. Copy unselected agent declarations
unchanged. The candidate is input to the current installation's operation; it
does not create another installed fleet.

For the selected agent profile, choose the retained `project_root`, readiness
requirements and container bindings using native configuration. Resource capacity,
GPU declarations and preparation snapshot mappings stay fixed. The coordinator
may select new preparation source paths while retaining source aliases, snapshot
mappings and preparation policies. Fleet derives the new qualified descriptors,
preparation generation and versioned client. Other coordinator policy stays fixed.

A read-only shared root may move to a new `host_path` only when its alias,
challenge, access, container path and publication policy are unchanged. Writable
root relocation and logical-root replacement are refused. Native agent promotion
and coordinator reload require settled closed maintenance before activating the
move. The coordinator and selected agents must advertise
`quiescent-source-promotion-v1`; upgrade their service runtime first if needed.

The site must copy and verify historical source bytes before relocating a root,
and retain old relative paths for historical consumers. Root qualification proves
the declared challenge, not whole-tree equivalence. A useful layout retains the
old source namespace and adds new immutable release directories beneath it;
select the new release as the project/preparation path. Fleet never copies
project trees or certifies application semantics.

Preview qualifies agents and the fully derived coordinator configuration on their
owning hosts without changing the running installation. Apply rechecks that
qualification before closing admission or promoting a profile. The operation
retains candidate inventory, role and environment input hashes and composed role
declarations; changes to included role files also refuse continuation. Source
selection contributes to the new preparation
generation even when image bytes are unchanged. Resume, failed-check successor,
abort and historical-observation behavior match ordinary workload promotion.

The following installed acceptance hook covers image-only promotion. A site
source relocation also needs physical qualification of its retained source
layout and workload. Installed acceptance is opt-in:
`LOOM_RUN_FLEET_ACCEPTANCE=1 LOOM_FLEET_ACCEPTANCE_CONFIG=/protected/workload.json`
with `tests/fleet_acceptance/test_workload_upgrade.py`. Its protected JSON selection
has `schema_version: 1`, `disposable: true`, `kind: "workload-upgrade"`, and fields
`fleet`, `workload_profile`, `image`, `image_sha256`, `deployment`,
`operator_connection`, `config`, `operation_id`, `roots` (role-to-native-ID map),
`service_descriptor` (the already installed capable release digest), `old_run`,
`old_run_uri`, `old_profile` (full native descriptor), `history`, `report`, and
`timeout_seconds` (1–1800); `env_file` is optional. `history` pins exactly `source`,
`profile`, and `result`, each with an existing native evidence `path` and exact
`sha256`. The profile evidence must contain the old profile revision. Paths are
relative to the selection file; the report must be new. The owner records native
old-run observation, unchanged historical evidence, checks and settlement,
service identities throughout promotion, old-client refusal, and exact replay.

### Live upgrade diagnostics

Add `--progress json` to `fleet upgrade --apply`, or to `fleet operation resume`,
`abort`, `retry-check`, or `retry-control` for a retained runtime/workload upgrade.
The default `--progress none` is quiet. Preview/plan and non-upgrade operations
refuse JSON progress before mutation; status and other commands do not accept
this flag. Activation is explicit in both text and JSON final-output modes.

```sh
loom fleet upgrade --fleet lab --runtime-release /PRIVATE/release/runtime.json \
  --apply --operation-id maintenance-a --progress json --format json \
  > result.json 2> progress.jsonl
loom fleet operation resume maintenance-a --fleet lab --progress json --format json
loom fleet operation retry-check maintenance-a --fleet lab \
  --failed-check failed-check-a --operation-id replacement-check-a --progress json
```

Stdout and exit codes keep their existing meaning: one final JSON object with
`--format json`; complete/aborted/preview exit 0, pending/running/waiting exit 2,
and blocked outcomes exit 1. Early validation errors retain native error behavior.
Progress is best-effort JSONL on stderr, with phase changes and at most one
heartbeat every five seconds. A blocking native/SSH call keeps its phase while
elapsed time advances. Fast phases may coalesce; this is not an audit history.
Redirecting stderr is optional and Loom creates no progress artifact itself.

Every diagnostic record has exactly these fields:

| Field | Values |
| --- | --- |
| `schema_version` | `1` |
| `event` | `phase`, `heartbeat`, `result` |
| `kind` | `runtime-upgrade`, `workload-upgrade`, or `unknown` before binding |
| `action` | `apply`, `resume`, `abort`, `retry-check`, `retry-control` |
| `phase` | `preparing`, `closing_admission`, `settling`, `draining`, `replacing`, `checking`, `restoring`, `reopening_admission`, `recovering`, `finished` |
| `state` | `running`, then native `complete`, `aborted`, `waiting`, `blocked`; `interrupted`/`error` when no native result returns |
| `reason_code` | `none`, `settlement_pending`, `acknowledgement_pending`, `check_failed`, `host_unavailable`, `coordinator_unavailable`, `native_refusal`, `input_invalid`, `unknown` |
| `elapsed_seconds` | Local monotonic seconds since invocation entry |
| `phase_elapsed_seconds` | Seconds since the latest phase change |
| `preparation_seconds` | Accumulated initial validation and pre-close candidate preparation seconds |
| `admission_closed_seconds` | Observed closed interval seconds, or `null` without a matching live observation |

Records are limited to 1 KiB including newline. Durations are finite and
nonnegative. No IDs, host labels, paths, credentials, arguments, native replies,
exception messages, or child output appear in this stream. Native protected
status/results remain the source of detailed failure and recovery information.
Waiting/blocked records retain the causal executing phase; successful terminal
records may use `finished`.

All clocks restart on each invocation, including resume. Preparation includes
actual candidate rechecks, excludes post-close staging/promotion, and may overlap
an already observed closed interval. These durations must not be added as
disjoint portions of total time. Admission timing starts only at an existing
live observation proving this operation owns the closed gate, never from a
retained close request, lost reply, or historical mutation receipt. It ends at
an existing live open observation or a successful open request first dispatched
in this invocation. An old replayed open receipt cannot stop a new interval.
Without an observed end, the interval continues to the invocation's final
snapshot. Completed replay does not reconstruct prior timings; cross-invocation
elapsed time and operator gaps remain unknown.

Admission closure prevents new ordinary admissions while existing work may
continue. This interval is **not service downtime**, stop-to-ready time, GPU
availability, or scientific success. Progress changes no sampling, processing,
checks, native requests, recovery eligibility, or operation ownership.

Python callers can pass `upgrade(..., progress=callback)` to receive the same
allowlisted snapshot dictionaries on an invocation-local reporting thread.
Callbacks are diagnostic outputs, never policy inputs. A slow/broken sink can
lose records, including the terminal record, but cannot delay native execution
indefinitely or replace its result/exception. There is one latest snapshot and
no event backlog. A healthy reporter stops on completion, error or interruption;
a callback blocked indefinitely may leave a daemon thread until process exit.
Interruption preserves native recovery; resume uses the same retained operation
and fresh local clocks. No additional observation RPC or SSH child is started
for a heartbeat.
