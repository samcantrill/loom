# loom Preflight Specification

## Purpose

Preflight checks catch obvious run problems before expensive execution begins.

They are especially useful when a run will be submitted to a cluster, launched
inside a container, or executed against large artifact directories. A preflight
command should fail fast on configuration and environment issues while being
clear about checks it could not perform.

Preflight is best-effort validation. It is not a substitute for normal runtime
checks.

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
codec_registry.available
executor.local
executor.resolve
executor.capabilities
executor.subprocess.python
executor.subprocess.worker
resources.capabilities
filesystem.input_exists
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
SLURM dry-run checks warn when sbatch is missing; live squeue/sacct checks are v7/later
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

## SLURM Checks

For SLURM runs, preflight may check:

```text
executor mode is a supported v6 dry-run mode
structured SLURM options and profile shape are valid
launcher argv is non-empty and shell-safe
generic CPU, memory, and GPU resources can map to SBATCH directives
generated script/log paths remain under the run directory
shared/local run URI assumptions are satisfied
sbatch availability, reported as warning/info for v6 dry-runs
```

V6 SLURM dry-runs must not fail only because `sbatch` is missing. Live
submission, `squeue`, `sacct`, and `scancel` checks are v7/later behavior.
Preflight should not submit a test job unless explicitly requested by a future
option.

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

## Plugin Checks

Plugin checks should verify:

```text
plugin entrypoints can be discovered
requested executor plugin is registered
requested artifact store plugin is registered
requested codecs are registered
plugin-provided config schema can be loaded
```

A plugin import failure should identify the plugin and the capability being
loaded.

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
