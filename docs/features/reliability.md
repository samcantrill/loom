# loom Reliability Policies Specification

## Purpose

Reliability policies describe how `loom` records, responds to, and cleans up
runtime failures.

The initial runtime should be conservative: record enough information to debug
and resume safely, avoid surprising deletion, and keep retry/cleanup behavior
explicit.

This document collects retry, timeout, failure metadata, cleanup, garbage
collection, event hook, and artifact retention behavior into one design surface.

## Scope

This component owns:

```text
retry policy data model
timeout policy data model
failure recovery metadata requirements
temporary file cleanup semantics
garbage collection command semantics
event hook record shape
artifact retention policy metadata
conservative deletion rules
```

This component does not own:

```text
executor-specific process control internals
artifact serialization
run-store atomic write implementation
remote notification services
cluster preemption handling details
dashboard delivery
```

Executor and store implementations enforce parts of the policy, but the policy
model should stay shared.

## Design Goals

Reliability behavior should:

```text
prefer explicit records over implicit assumptions
make failures inspectable after the controller exits
support safe resume after partial failures
avoid deleting user data by default
avoid retrying non-idempotent work unless policy allows it
keep core notification support generic
```

## Failure Metadata

Every failed stage attempt should record:

```text
stage_id
attempt
status
exception type when available
message
traceback path when available
executor
exit code when available
signal when available
stdout log path when available
stderr log path when available
started_at
failed_at
duration_seconds
temporary paths when known
```

This is P1 because it directly affects debugging and controller recovery.

## Failure Record Shape

Recommended shape:

```python
@dataclass(frozen=True)
class FailureRecord:
    stage_id: str
    attempt: int
    failed_at: str
    executor: str
    message: str
    exception_type: str | None = None
    traceback_path: str | None = None
    exit_code: int | None = None
    signal: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
```

The exact model should align with state and run-store records.

## Retry Policy

Retry policy controls whether a failed stage may be attempted again
automatically within the same run.

Recommended shape:

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    retry_on_exit_codes: frozenset[int] | None = None
    retry_on_exception_types: frozenset[str] | None = None
    backoff_seconds: float | None = None
```

YAML example:

```yaml
retry:
  max_attempts: 2
```

`max_attempts` includes the first attempt. `max_attempts: 1` means no automatic
retry.

## Retry Boundaries

Automatic retry is safe only when stage execution is idempotent with respect to
its declared outputs.

The runtime should support retry only when:

```text
the previous attempt has a clear failed status
partial output writes were not committed
the stage output transaction can be retried safely
the retry policy allows another attempt
```

The runtime should not retry:

```text
validation failures
pipeline graph failures
missing stage definitions
artifact type mismatches
user cancellation unless explicitly designed
```

Executor-specific transient failures can be added later through structured
failure categories.

## Timeout Policy

Timeout policy controls maximum runtime for a stage attempt.

Recommended shape:

```python
@dataclass(frozen=True)
class TimeoutPolicy:
    wall_time_seconds: int | None = None
    grace_seconds: int | None = None
```

`wall_time_seconds` may be sourced from `ResourceRequest.wall_time_seconds` or
from an explicit reliability policy. The design should avoid two conflicting
ways to express the same timeout.

## Timeout Enforcement

Timeout enforcement depends on executor capability.

Local/subprocess:

```text
controller can terminate the child process after the timeout
logs and exit status should record timeout as the failure reason
```

SLURM:

```text
wall time maps to scheduler submission where possible
controller may observe scheduler timeout after the fact
```

Containers:

```text
timeout may wrap the container runtime command
container runtime-specific stop behavior should be recorded
```

If an executor cannot enforce a timeout, preflight or execution should warn and
record that the timeout was not enforced.

## Temporary File Cleanup

Temporary file cleanup removes known temporary directories left by failed or
interrupted operations.

Potential command:

```bash
loom clean RUN_DIR --failed-temp
```

Cleanup should target only paths recorded by `loom`.

Examples:

```text
artifact atomic-write temp directories
staged container working directories
executor wrapper temp files
partial bundle export directories
```

Cleanup should not scan arbitrary directories and guess.

## Cleanup Safety

Cleanup must be conservative.

Rules:

```text
only delete paths under a configured run/artifact/temp root
only delete paths recorded in loom metadata or matching a loom-owned marker
support dry-run output
do not follow symlinks for deletion
make deletion failures visible
```

Recommended command options:

```text
--dry-run
--failed-temp
--older-than DURATION
--yes
```

Interactive confirmation belongs in CLI. Programmatic APIs should default to
dry-run unless called with explicit delete intent.

## Garbage Collection

Garbage collection handles larger cleanup across run collections.

Potential command:

```bash
loom gc runs/ --older-than 30d
```

Initial GC should be metadata-driven and conservative.

Candidates:

```text
temporary files from completed runs
failed attempt temp directories
logs older than a policy threshold when explicitly selected
artifacts marked temporary by retention policy
entire run directories only with explicit flags
```

Garbage collection is P3 and should not block core runtime work.

## Artifact Retention Policy

Artifact retention policy lets a run describe which artifacts are intended to be
kept, archived, or treated as temporary.

Recommended shape:

```python
@dataclass(frozen=True)
class RetentionPolicy:
    mode: str = "keep"
    delete_after_success: bool = False
    archive: bool = False
    ttl_seconds: int | None = None
```

Example:

```yaml
artifacts:
  intermediates:
    retention:
      mode: temporary
      delete_after_success: true
```

The first implementation should record retention metadata and expose inspection
support. Actual deletion should be explicit.

## Retention Modes

Recommended modes:

```text
keep
temporary
archive
external
```

Meanings:

```text
keep       preserve by default
temporary  eligible for explicit cleanup
archive    should be included in archive/export workflows
external   tracked by metadata but not owned for deletion
```

These are policy hints. They do not replace artifact store ownership checks.

## Event Hooks

Event hooks expose structured lifecycle events for external tools.

Events:

```text
run_started
stage_started
stage_succeeded
stage_failed
run_finished
submission_created
retry_scheduled
cleanup_performed
```

Core `loom` should emit generic event records or call registered callbacks. It
should not ship service-specific notification backends initially.

## Event Record Shape

Recommended shape:

```python
@dataclass(frozen=True)
class RuntimeEvent:
    event_type: str
    recorded_at: str
    run_id: str
    stage_id: str | None = None
    attempt: int | None = None
    severity: str = "info"
    details: Mapping[str, object] = field(default_factory=dict)
```

Event details must be JSON-serializable.

## Notification Boundary

Core should not include direct Slack, email, Teams, PagerDuty, or webhook
delivery in v0.

Instead, it should support:

```text
event records in run metadata
programmatic callbacks
optional plugin hooks
CLI commands that stream or inspect event records
```

Service-specific delivery belongs in plugins or external wrappers.

## Run Store Integration

The run store should persist:

```text
attempt records
failure records
retry decisions
timeout outcomes
cleanup records
retention metadata
event records when event persistence is enabled
```

State transitions must remain atomic enough that a controller crash leaves a
recoverable record.

## Executor Integration

Executors should report:

```text
attempt started
attempt finished
attempt failed
exit code
signal
timeout status
submission ID where applicable
log paths
temporary paths
```

Executors should not decide high-level retry policy. They report facts; the
runtime policy decides whether another attempt is allowed.

## Preflight Integration

Preflight may warn about:

```text
retry policy not supported by selected executor
timeout policy not enforceable by selected executor
cleanup paths outside managed roots
retention policy that cannot be enforced by selected artifact store
event hook registration failures
```

Warnings should be explicit because reliability features are often
environment-dependent.

## Testing

Tests should cover:

```text
failure record serialization
retry max_attempts behavior
retry disabled behavior
non-retryable validation failures
timeout policy normalization
executor timeout unsupported warning
cleanup dry-run reports candidates
cleanup rejects paths outside managed roots
cleanup does not follow symlinks
retention metadata serialization
event record serialization
event callback failure handling
```

Executor-specific timeout tests should use fake executors unless an integration
test environment explicitly provides real commands.

## Implementation Plan

1. Define reliability policy and event models.
2. Persist failure metadata for every failed stage attempt.
3. Add retry planning around atomic output transactions.
4. Add timeout support where the selected executor can enforce it.
5. Add cleanup dry-run reporting for known temporary paths.
6. Add conservative deletion behind explicit CLI flags.
7. Add retention metadata before adding automatic deletion behavior.
8. Add generic event records and plugin callback hooks.

## Deferred Work

Deferred reliability features:

```text
automatic cluster preemption retry classification
service-specific notifications
distributed event streaming
automatic retention deletion
advanced exponential backoff
retry budgets across runs
resource-aware retry escalation
full run collection garbage collection
```

These should be added after local and SLURM failure records are stable.

