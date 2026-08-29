# loom Preflight Specification

## Purpose

Preflight checks catch obvious run problems before expensive execution begins.

They are especially useful when a run will be submitted to a cluster, launched
inside a container, or executed against large artifact directories. A preflight
command should fail fast on configuration and environment issues while being
clear about checks it could not perform.

Preflight is best-effort validation. It is not a substitute for normal runtime
checks.

Queue service preflight is documented in [queue.md](queue.md). The command
`loom queue preflight CONFIG` checks queue config loading, SQLite repository
reachability, authority configuration evidence, managed-pool reconciliation
readiness, SLURM command availability for delegated pools, and the delegated
shared-workspace assumptions without submitting work or mutating authority
resource limits.

Pool status is a read-only operation and likewise does not refresh durable lease
acquisition evidence or turn a preflight result into live process proof.

NVIDIA local GPU observation is deliberately outside default queue preflight.
An operator explicitly imports `loom.queue.gpu.nvidia`, calls discovery once,
then explicitly prepares authority limits before constructing a runtime. This
avoids command execution while loading config, importing Loom, or performing a
generic preflight check.

## Scope

Preflight owns:

```text
assembling pre-run diagnostics
validating pipeline graph construction
validating runtime option consistency
checking run directory writability
checking local artifact paths when statically known
checking executor availability
checking optional command availability such as sbatch
checking plugin and codec registration
reporting warnings and skipped checks
returning a machine-readable result
```

Preflight does not own:

```text
executing stages
loading domain artifacts
submitting jobs
creating final run state
modifying existing runs
guaranteeing future filesystem availability
guaranteeing cluster scheduling success
```

## Command Shape

Current CLI command:

```bash
loom preflight experiment.yaml --run-uri file:///runs/example --check runtime
```

Useful options:

```text
--run-uri URI
--profile PROFILE
--executor EXECUTOR
--dry-run
--resume
--from-stage STAGE
--only-stage STAGE
--force-stage STAGE
--skip-stage STAGE
--tag KEY=VALUE
--note TEXT
--check GROUP
--strict
--format json
```

The CLI layer owns argument parsing. The preflight component owns the checks and
result model.

## Result Model

Recommended dataclasses:

```python
@dataclass(frozen=True)
class PreflightResult:
    status: PreflightStatus
    checks: tuple[PreflightCheckResult, ...]

@dataclass(frozen=True)
class PreflightCheckResult:
    check_id: str
    severity: PreflightSeverity
    status: PreflightCheckStatus
    message: str
    details: Mapping[str, object] = field(default_factory=dict)
```

Recommended statuses:

```text
PASS
WARN
FAIL
SKIP
```

Recommended severities:

```text
INFO
WARNING
ERROR
```

The overall result fails when any `ERROR` check fails. In `--strict` mode,
warnings may also produce a nonzero exit.

## Check Identity

Each check should have a stable ID.

Examples:

```text
config.load
pipeline.graph
selectors.validate
runtime.options
runtime.profile
runtime.stage_options
run_uri.resolve
artifact_store.available
artifact_backends.registry
artifact_backends.handlers
artifact_backends.capabilities
artifact_backends.materialization
codec_registry.available
executor.local
executor.resolve
executor.capabilities
executor.subprocess.python
executor.subprocess.worker
resources.capabilities
filesystem.input_exists
cleanup.candidates.safety
cleanup.targets.support
cleanup.retention.policy
```

Stable IDs make JSON output useful for external tooling and tests.

## Configuration Checks

Configuration checks should verify:

```text
config files can be loaded
includes and overlays can be resolved
schema validation passes
trusted Python config hooks can be imported if the project uses them
runtime profile selection is valid
required config keys are present
```

Preflight should report the resolved config summary where practical, but should
not expose secrets in CLI output.

## Pipeline Checks

Pipeline checks should verify:

```text
pipeline spec can be constructed
stage IDs are unique
stage input and output names are valid
artifact references parse correctly
upstream stages exist
upstream outputs exist
the stage graph is acyclic
selected stages exist
forced stages exist
```

These checks should use the same validation and graph modules that execution
uses. For execution-planning diagnostics, preflight should call into
`plan_pipeline()` and `explain_plan()` rather than duplicating selector,
invalidation, or resume logic.

## Runtime Checks

Runtime checks should verify:

```text
runtime options normalize through RunOptions
runtime profile can be applied
exact-stage runtime options target known stage IDs
executor name is known
executor capability diagnostics can be reported
resource capability diagnostics can be reported
reliability retry and timeout capability diagnostics can be reported
resume, dry-run, selector, tag, and note options are normalized
```

Runtime checks should avoid executor-specific assumptions unless the selected
executor is known.

## Filesystem Checks

Filesystem checks may verify:

```text
run directory parent exists or can be created
run directory does not conflict with an incompatible existing run
artifact store root is readable
artifact store root is writable when needed
log directory can be created
temporary directory can be created
known external input paths exist
basic disk-space warnings when practical
```

These checks should be careful with side effects.

Allowed side effects:

```text
creating and deleting a temporary probe file in a target directory
reading metadata from existing loom files
checking command availability
```

Avoid:

```text
creating final run state
creating artifact records
deleting user files
locking a run directory for real execution
```

## Artifact Checks

Artifact checks should verify:

```text
artifact store configuration is valid
registered artifact codecs are available
declared input artifact references can be resolved when statically known
expected output locations do not collide with incompatible existing artifacts
checksum settings are valid
```

Preflight should not load large artifact payloads by default.

Checksum validation of existing artifacts may be available behind an explicit
option because it can be expensive.

## Cleanup Checks

Stage 21 adds optional cleanup preflight checks for callers that provide explicit
cleanup targets. These checks are read-only. They call cleanup planning APIs to
warn about unsafe candidates, unsupported remote/external targets, unsupported
retention hints, and missing managed-root or ownership evidence.

Cleanup preflight must not:

```text
append cleanup report or result facts
delete files
dispatch cleanup events
load provider plugins
treat run catalog paths as deletion authority
```

Stage 15 backend checks are explicit and metadata-only. They run only for
configured `ArtifactBackendPreflightTarget` values supplied by the caller and
report separate registry, handler, and capability results:

```text
artifact_backends.registry
artifact_backends.handlers
artifact_backends.capabilities
```

Default artifact backend checks must not discover plugins, import backend SDKs,
contact tracking systems, probe credentials, call `handler.check()`, perform
lookup, or materialize payloads. Generic Stage 14 plugin metadata/list/load
results never satisfy Stage 15 backend availability or run-readiness checks.

Stage 16 adds `artifact_backends.materialization` for selected artifact backend
targets that request payload operations such as materialize, upload, download,
publish, or checksum verification. The default check is still cheap: it verifies
that a configured handler implements the store-owned payload protocol and that
declared capabilities are present, but it does not call `payload_operation()`,
move bytes, contact a service, or validate credentials. Expensive probes remain
a future explicit option.

## Executor Checks

Executor checks should verify:

```text
selected executor can be resolved
required local commands are available
executor profile fields are valid
resource requests can be mapped
required environment variables are present when declared
```

Examples:

```text
local executor requires no external command
subprocess executor requires executable commands to be resolvable
SLURM dry-run checks warn when sbatch is missing
SLURM live checks fail when sbatch is missing and warn on missing squeue/sacct/scancel
Docker executor requires docker
Apptainer executor requires apptainer or singularity
```

Preflight should report executor availability as a check result, not as an
unstructured exception.

Current subprocess checks run only when `subprocess` is the selected executor.
They verify that the current Python executable is available and that the public
`loom stage run` worker command can be resolved through `loom.cli.main` without
launching user stage code. Missing Python or worker command availability is
reported as selected-executor availability failure, distinct from an unknown
executor name.

Reliability timeout checks are capability diagnostics, not process probes. A
selected timeout policy reports whether the executor support level is
`enforced`, `delegated`, `observed`, or `unsupported`. Subprocess timeout
support is reported as enforced; local in-process timeout support is reported
as unsupported. Enabled retry policy is reported as runner-owned runtime
behavior because executors still run one attempt at a time while the controller
persists retry decisions before scheduling another attempt.

After execution, unsupported timeout facts are also visible through read-only
status/backend inspection as timeout outcomes. Preflight remains the place to
explain capability support before a run starts.

## SLURM Checks

For SLURM runs, preflight checks:

```text
executor mode is supported
structured SLURM options and profile shape are valid
launcher argv is non-empty and shell-safe
generic CPU, memory, and GPU resources can map to SBATCH directives
generated script/log paths remain under the run directory
generated path parents are writable
shared/local run URI assumptions are satisfied
active submitted SLURM work is not present for the selected run URI
sbatch availability, warning for dry-runs and failure for live submission
squeue, sacct, and scancel availability as live-operation warnings
```

SLURM dry-runs must not fail only because `sbatch` is missing. Live submission
requires `sbatch`. Missing `squeue`, `sacct`, or `scancel` remains a warning in
preflight because `loom status RUN_URI --jobs` and
`loom cancel RUN_URI --jobs` enforce their operation-time requirements.
Preflight does not submit a test job unless explicitly requested by a future
option.

Stable SLURM check IDs include:

```text
runtime.slurm.options
run_uri.slurm.local
run_uri.slurm.active_submission
executor.slurm.mode
executor.slurm.launcher
executor.slurm.sbatch
executor.slurm.squeue
executor.slurm.sacct
executor.slurm.scancel
resources.slurm.mapping
filesystem.slurm.generated_paths
filesystem.slurm.generated_writable
```

## Container Checks

For container runs, preflight may check:

```text
container runtime command exists
image reference is present
configured bind mounts exist
run directory mount is writable
working directory inside the container is configured
required environment variables are available
```

Preflight should not pull large images by default. Image existence checks should
be explicit because they may require network access.

Implemented Stage 17 Docker checks run only when Docker is the selected
executor. Stable Docker check IDs are:

```text
executor.docker.command
executor.docker.container_options
executor.docker.image
executor.docker.environment
filesystem.docker.mount_sources
filesystem.docker.mount_targets
filesystem.docker.run_dir_writable
filesystem.docker.artifact_root_visible
resources.docker.mapping
resources.docker.gpu
```

These checks are daemon-free by default. They verify `docker` command presence
on `PATH`, parse the `container` and `docker` adapter namespaces, check image
reference presence, summarize required host environment variable names, inspect
authored mount source paths, verify Stage 17 path-parity targets, and report
CPU/memory or unsupported GPU resource mapping. They do not run
`docker version`, inspect images, pull images, contact registries, or read raw
environment values.

Stage 18 adds cheap selected checks for shared build targets,
Apptainer/Singularity execution, and SLURM plus Apptainer composition.

Stable container build and Apptainer check IDs include:

```text
runtime.container_build.options
executor.container_build.targets
executor.apptainer.command
executor.apptainer.container_options
executor.apptainer.image
executor.apptainer.environment
resources.apptainer.mapping
resources.apptainer.gpu
resources.slurm.container_compatibility
filesystem.container_build.sources
filesystem.container_build.outputs
filesystem.apptainer.bind_sources
filesystem.apptainer.bind_targets
filesystem.apptainer.run_dir_writable
filesystem.apptainer.artifact_root_visible
```

These checks parse `container_build`, `container`, `apptainer`, `singularity`,
and `slurm` adapter namespaces, verify required local paths where statically
knowable, summarize build target output refs and policies, and inspect command
availability through `PATH`. They do not run `docker`, `apptainer`,
`singularity`, or `sbatch` beyond command lookup; they do not build SIF files,
pull images, contact registries, submit scheduler jobs, read raw environment
values, or probe fakeroot.

`executor.apptainer.command` fails for direct Apptainer/Singularity execution
when the selected command is missing. For SLURM dry-run plus Apptainer it warns
instead, matching the dry-run behavior for missing `sbatch`. Live SLURM plus
Apptainer treats missing runtime or scheduler commands as run-time blockers.

## Plugin Checks

Plugin checks should verify:

```text
plugin entrypoints can be discovered
requested codecs are registered
requested recipes are registered
requested event sink plugins can register into a scratch EventSinkRegistry
listing-only plugin groups are reported without importing targets
plugin-provided config schema can be loaded
```

A plugin import failure should identify the plugin and the capability being
loaded. Event sink preflight stays observe-only: it may import explicitly
selected trusted sink targets and register them into a scratch registry, but it
must not dispatch events, create runs, or write callback-failure or
observer-link facts.

## Environment Checks

Environment checks may capture:

```text
Python version
loom version
current working directory
selected executor
selected profile
git metadata availability
```

Environment capture should not make a run fail unless required information is
missing for the selected execution mode.

## Stage 29 Daemon, Agent, And Ready-Stage SLURM Preflight Direction

Stage 29 adds deployment preflight for the persistent coordinator and agent
composition. It validates configured evidence without admitting a run,
publishing capacity, changing a session, or launching a process:

```text
coordinator and agent state roots are explicit and distinct after resolution
roots are owner-permissioned local filesystem state, not shared/NFS signalling
SQLite schema, writable durability/locking behavior, and storage headroom pass
stable role identity and current process-lock expectations are coherent
requested state-root operation is explicit initialize or open-only start
initialize target is verified absent/empty, or open target is readable and identity-bound
coordinator accepted-time source/high-water is coherent or reports degraded
coordinator/authority endpoint and expected service/workspace are configured
mTLS trust, credential references, principal roles, and pool scopes are present
configured resource planner/provider/claim contracts and retained descriptors
can be reconstructed
configured manageable resources exclude capacity the provider cannot account for
resident project/environment/executor fingerprints are configured
agent restart begins at zero availability and names the intended session path
agent configuration declares outbound coordinator connectivity and no inbound scheduler
coordinator principal policy intersects agent identity, pools, capabilities, and contracts
each enabled SLURM profile has stable identity/fingerprint and authorized callers
profile account/partition/QoS/directive mappings are allowlisted protected config
every supported canonical hard request maps completely without weakening
submit/status/cancel and exact operation-ID discovery capabilities are configured
resident bootstrap project/environment and coordinator data path are compatible
assignment-scoped bootstrap credential delivery is protected and secret-safe
profile outstanding/inspection/retention/message bounds are valid
secret values are protected references and excluded from job/worker configuration
```

Where portable code cannot prove the filesystem type, preflight reports the
requirement and rejects a root configured or detected as shared/unsupported; it
does not claim a universal remote-mount detector. Alias, permission, lock,
schema, fsync/rename, and high-water failures are definite failures for
production role state. Required-store failure never suggests an in-memory
fallback. A configured existing role whose expected root is missing, corrupt, or
identity-mismatched is reported as lost-state recovery; it is not initialized as
an empty service. Only an explicit initialization operation may create a
verified absent/empty target and durably establish a new stable role identity.

Preflight does not require a particular inter-service start order. It reports
the recommended authority -> coordinator -> agents quiet path, while validating
the configured behavior for other orders: agent-before-coordinator reconnect at
zero availability, coordinator-before-authority `PENDING_AUTHORITY` admission,
and coordinator-before-agent no-capacity waiting. It never treats a reachable
TCP endpoint as readiness, a fresh connection as a session, or an old retained
offer as current capacity. The supported role commands consume one explicit
owner-protected v1 coordinator or outbound-agent YAML path for both initialize
and serve; preflight must not discover a replacement or apply environment
overrides. Examples may name endpoint/trust/certificate/key/policy references
but never show or persist private key material.

Ready-stage SLURM preflight is distinct from historical whole-run live/dry-run
checks. For every enabled named profile it validates the concrete fakeable
command adapter, strict resource/hard-rule mapper, deterministic fixed-bootstrap
script capability, scheduler-visible stable submission identity, restricted
bootstrap authentication, artifact relay/backend compatibility, exact status/
cancel handle support, and retained-profile reconstruction. Authored stage data
may select an authorized alias only; raw commands, directives, submit hosts,
credential providers, or secret bytes fail before admission.

An unavailable profile does not require the whole coordinator to stop. The
profile is marked unavailable/degraded and explicitly routed stages remain
visibly waiting or blocked without falling back. Preflight must distinguish
configuration/schema/security failures from temporary command/gateway/
scheduler reachability. It never submits a probe job by default, treats queue
state as Loom capacity, or uses successful `scancel`/missing accounting as a
containment test. Opt-in real-cluster validation may submit a bounded bootstrap
receipt only under an explicit acceptance-test configuration.

Preflight may authenticate a no-mutation capability/identity handshake when the
operator explicitly enables a connectivity check. It does not adopt a rotated
authority generation, retire/replace an agent session, reconcile outbox events,
discover unconfigured hardware, fetch code, perform artifact transfer, or
reserve a resource/profile slot, invoke `sbatch`, or mint a bootstrap grant.
Those operations require their runtime owners and durable expected-state
transitions.

## Output

Human output should be compact. For v6 SLURM dry-runs, missing `sbatch` is a
warning rather than a failure:

```text
PASS config.load
PASS pipeline.graph
WARN disk_space.warning: only 8 GB available under runs/
WARN executor.slurm.sbatch: sbatch not found on PATH
```

JSON output should include structured fields:

```json
{
  "status": "FAIL",
  "checks": [
    {
      "check_id": "executor.slurm.sbatch",
      "severity": "WARNING",
      "status": "WARN",
      "message": "sbatch not found on PATH"
    }
  ]
}
```

## Exit Codes

Recommended exit behavior:

```text
0 all required checks pass
1 one or more required checks fail
2 preflight command usage error
```

Warnings should not fail the command unless `--strict` is enabled.

## Integration With Run

The normal `loom run` path may perform a minimal preflight subset before
execution:

```text
config load
pipeline validation
run directory safety
executor resolution
```

The explicit `loom preflight` command can perform broader checks and emit a
full report.

Execution should still validate critical assumptions at the time it acts.
Preflight can become stale between check time and run time.

## Testing

Tests should cover:

```text
successful minimal preflight
pipeline graph failure
invalid runtime option
unwritable run directory using a temporary permission-controlled path when practical
missing executor command via controlled PATH
plugin registry failure with a fake plugin
event sink plugin registration with a fake scratch registry
JSON output shape
strict mode warning behavior
selected stage validation
known input path exists and missing cases
```

Tests should avoid requiring real SLURM, Docker, Apptainer, or network access.

## Implementation Plan

1. Define preflight result and check result models.
2. Implement config, pipeline, runtime, filesystem, and executor check groups.
3. Wire `loom preflight` to the check runner.
4. Add JSON output and stable check IDs.
5. Reuse a minimal subset from `loom run`.
6. Extend executor-specific checks as executor support grows.

## Deferred Work

Deferred features:

```text
cluster test submission
container image pull verification
remote artifact store credential probing
large checksum scans
preflight policy files
organization-specific required checks
```

These should remain opt-in because they can be slow, environment-specific, or
network-dependent.
