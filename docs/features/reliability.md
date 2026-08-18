# loom Reliability Policies Specification

## Purpose

Reliability policies describe how `loom` records, responds to, and cleans up
runtime failures.

Managed-local queue status preserves acquisition-time safe evidence, including
queue-relative logs, but does not claim that persisted lease expiry or process
facts are currently live. A living same-session adapter may label an observation;
controller death and process reattachment remain outside that guarantee.

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
automatically within the same run. Retry is disabled by default and is owned by
the runner/controller, not by executors.

Current Stage 19 shape:

```python
@dataclass(frozen=True)
class RetryPolicy:
    enabled: bool = False
    max_attempts: int = 1
```

YAML example:

```yaml
runtime:
  reliability:
    retry:
      enabled: true
      max_attempts: 2
```

`max_attempts` includes the first attempt. `max_attempts: 1` means no automatic
retry.

The runner persists a `RetryDecisionRecord` after each failed or cancelled
stage attempt that reaches the retry gate. It schedules another attempt only
after an allowed decision has been written. Denied decisions remain inspectable
with stable reasons such as `retry.disabled`, `retry.max_attempts_exhausted`,
`retry.cancelled`, `retry.non_retriable_failure`,
`retry.transaction_missing`, and `retry.unsafe_transaction_state`.

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

Current automatic retry is conservative: retriable failure classifications are
limited to stage exceptions and executor infrastructure failures, and any
attempt that reached staged, committed, or commit-failed output transaction
state is denied as unsafe. Executors report one attempt result at a time and do
not schedule retries. Advanced backoff, retry windows, cross-run budgets, and
resource-aware escalation remain future policy work.

Stage 17 Docker failures record process and worker facts but do not introduce
Docker-specific retry policy. A Docker failure remains inspectable through the
normal failure record, status view, log paths, executor name, exit code or
signal when available, redacted command metadata, and bounded process output.
Stage 19 owns any shared retry, timeout, or failure-category policy that uses
those facts.

## Timeout Policy

Timeout policy controls maximum runtime for a stage attempt.

Current Stage 19 shape:

```python
@dataclass(frozen=True)
class TimeoutPolicy:
    enabled: bool = True
    duration_seconds: float | None = None
```

YAML example:

```yaml
runtime:
  reliability:
    timeout:
      enabled: true
      duration_seconds: 300
```

`duration_seconds` lives under `runtime.reliability.timeout` or an exact-stage
`runtime.stage_options.<stage>.reliability.timeout` override. It is not a
`ResourceRequest` field, an executor resource request, a resource admission wait
timeout, or an authority-client operational timeout. Authored resource fields
such as `timeout`, `timeout_seconds`, and `wall_time_seconds` remain rejected so
callers do not assume resource admission will enforce reliability policy.

## Timeout Enforcement

Timeout enforcement depends on executor capability.

Subprocess:

```text
the executor passes duration_seconds to the worker subprocess boundary
timeout expiry returns a structured failed attempt
the timeout outcome is persisted as a reliability fact
```

Local:

```text
in-process stage code is not interrupted
execution records an unsupported timeout outcome when policy is selected
preflight and capability diagnostics warn that timeout is unsupported
```

SLURM:

```text
timeout intent can be delegated to scheduler submission where possible
controller may observe scheduler timeout facts after the attempt
```

Containers:

```text
timeout may wrap the container runtime command in a future adapter
container runtime-specific stop behavior should be recorded
```

Stage 17 records Docker process timeout fields when supplied by the command
runner, but it does not add a user-facing timeout policy.

Executor descriptors classify timeout support as `enforced`, `delegated`,
`observed`, or `unsupported`. Attempt outcomes use `enforced`, `delegated`,
`observed`, `unsupported`, or `timed_out`. If an executor cannot enforce or
observe a timeout, preflight or execution should warn and record that the
timeout was not enforced.

## Temporary File Cleanup

Temporary file cleanup removes known cleanup candidates recorded by Loom, such
as temporary files or directories left by failed or interrupted operations.

Implemented command:

```bash
loom clean RUN_URI
loom clean RUN_URI --older-than 7d --delete --yes
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

Implemented command options include:

```text
--older-than DURATION
--recorded-before TIMESTAMP
--recorded-after TIMESTAMP
--candidate-kind KIND
--reason CODE
--retention-mode MODE
--stage STAGE
--artifact-id ID
--artifact-type TYPE
--tag TAG
--metadata KEY=VALUE
--delete
--yes
```

Interactive confirmation belongs in CLI. Programmatic APIs should default to
dry-run unless called with explicit delete intent.

## Garbage Collection

Garbage collection handles candidate-level cleanup across run collections.

Implemented command:

```bash
loom gc runs/ --older-than 30d
loom gc runs/ --retention-mode temporary --delete --yes
```

Initial GC is metadata-driven and conservative.

Candidates:

```text
temporary files from completed runs
failed attempt temp directories
logs older than a policy threshold when explicitly selected
artifacts marked temporary by retention policy
```

Garbage collection does not delete whole run directories in Stage 21. A future
whole-run deletion mode needs separate terminal-state, lease/submission,
reference, marker, retention, dry-run, and tombstone/result-record gates.

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

The first implementation records retention metadata and exposes inspection and
selection support. Actual deletion is explicit through cleanup commands and
cleanup APIs; retention hints do not trigger automatic deletion.

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

Event records expose structured lifecycle facts for inspection and future
external tools. The strict event model and local `events.jsonl` persistence use
append-only audit records, not current-state records. The local runner emits
lifecycle events for run planning/start/completion/failure and stage
planned/started/completed, failed, skipped, reused, and blocked outcomes.
Explicit event sink registries can observe committed runtime events, and
plugin-discovered event sinks can be loaded only through `loom.plugins` into a
supplied registry.

Events:

```text
run.created
run.opened
run.planned
run.started
run.completed
run.failed
stage.planned
stage.started
stage.completed
stage.failed
stage.skipped
stage.reused
stage.blocked
```

Core `loom` emits or references generic event records before dispatching
registered callbacks. Event sinks are observe-only callbacks. They receive
committed runtime facts and must not mutate plans, configs, artifacts, stage
outputs, status transitions, retry decisions, or store records.

Plugin-discovered event sinks are owned by `loom.plugins`; this document owns
event names, event payloads, persistence policy, and callback failure behavior.
Core `loom` should not ship service-specific notification backends initially.

## Event Record Shape

Current persisted foundation shape:

```python
@dataclass(frozen=True)
class PipelineEventRecord:
    schema_version: int
    event_id: str
    run_uri: str
    sequence: int
    occurred_at: str
    event_type: str
    primary_resource: EventResourceRef
    related_resources: tuple[EventResourceRef, ...]
    payload: Mapping[str, PlainData] = field(default_factory=dict)
    causal_predecessor: EventResourceRef | EventReference | None = None
```

Schema-version 2 records use `occurred_at` and resource references. Existing
schema-version 1 records with `timestamp` and `scope` remain readable through
compatibility projection; reading an old `events.jsonl` does not rewrite it.
Event payloads must be plain-data mappings. Local stores allocate contiguous
per-run sequence numbers and append one JSON object per line to
`<run_dir>/events.jsonl`.

Event sink callback failures and observer links are event-adjacent facts, not
ordinary runtime events. Local stores persist them in separate JSONL sidecars:
`event_sink_failures.jsonl` and `event_observer_links.jsonl`. They reference
the triggering event identity and remain read-only observer evidence.

## Notification Boundary

Core should not include direct Slack, email, Teams, PagerDuty, or webhook
delivery in v0.

Instead, it should support:

```text
event records in run metadata
append-only local events.jsonl
programmatic callbacks
optional plugin hooks
CLI commands that stream or inspect event records
```

Service-specific delivery belongs in plugins or external wrappers.

Programmatic callback registration should be available before entry point
discovery. Plugin discovery uses the `loom.event_sinks` entry point group for
observe-only sinks and remains an explicit setup action.

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

Local event persistence is available as a run-store capability. When event sinks
are configured, event persistence is enabled by default unless the caller
explicitly disables it. Disabled persistence dispatches non-durable event
references with warning metadata rather than fabricating durable event
sequences.

State transitions must remain atomic enough that a controller crash leaves a
recoverable record.

Failed local runs also persist status-only blocked records for downstream
planned descendants. These records live at `stages/<stage>/status.json` with
`StageStatus.BLOCKED`; they do not create inputs, outputs, fingerprints,
failure metadata, provenance, or logs for stages that never executed. Automatic
retry, timeout enforcement, cleanup, retention, and service-specific event sink
delivery remain deferred.

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

Callback failures should be recorded and execution should continue by default.
A future strict mode may treat callback failures as fatal for audit-heavy
workflows, but observer failure must not silently alter run correctness.

## Read-Only Inspection

Current Stage 19 reliability facts are inspectable through authoritative read
models and existing status/backend diagnostics.

`loom status RUN_URI` includes compact per-stage reliability summaries when
facts exist:

```text
selected reliability policy
status detail count
stage-attempt transaction count and latest state
retry decision count and latest decision reason
timeout outcome count and unsupported timeout diagnostics
```

`loom backend inspect RUN_URI --format json` exposes the raw authoritative
snapshot fields for reliability policy facts, status details, transactions,
retry decisions, and timeout outcomes. Text output reports compact counts.

Inspection is read-only. It must not allocate attempts, schedule retries,
clean files, delete artifacts, emit external events, or contact notification
services. Stage 20 may project these facts into events. Stage 21 may consume
transaction and timeout evidence for cleanup and retention planning, but Stage
19 does not perform deletion.

## Testing

Tests should cover:

```text
failure record serialization
retry max_attempts behavior
retry disabled behavior
non-retryable validation failures
timeout policy normalization
executor timeout unsupported warning
status/backend reliability inspection
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

1. Define reliability policy and record models.
2. Persist failure metadata for every failed stage attempt.
3. Record stage-attempt transactions, timeout outcomes, and retry decisions.
4. Add timeout support where the selected executor can enforce it.
5. Expose read-only reliability facts through diagnostics and CLI status.
6. Add cleanup dry-run reporting for known temporary paths in later work.
7. Add conservative deletion behind explicit CLI flags in later work.
8. Add retention metadata before adding automatic deletion behavior.
9. Add plugin callback hooks on top of generic event records.

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
