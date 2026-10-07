# Fleet configuration and read-only administration

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
never select tmux automatically. These commands perform no SSH or installation,
start no native role or workload, and do not initialize/read private native SQL.
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
CLI/configuration errors remain nonzero. Self-test, setup and upgrade are separate
operations and are not provided by this command set.

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
