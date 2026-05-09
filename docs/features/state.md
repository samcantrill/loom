# `loom.pipeline.status` and State Specification

## 1. Purpose

`loom.pipeline.status` defines the shared run and stage status vocabulary for
`loom`.

It exists so planning, execution, resume, run stores, CLI inspection, SLURM
integration, and tests all agree on what run and stage states mean.

The state layer should answer:

```text
What statuses can a run have?
What statuses can a stage have?
Which transitions are valid?
Which component owns transition decisions?
Which state is persisted?
Which state is only a planning action?
How should old RUNNING state be interpreted?
How should CLI/status commands display state?
```

It should not answer:

```text
Where are status files written?
How are writes made atomic?
How are artifacts saved?
How are fingerprints computed?
How are stage processes launched?
How are SLURM jobs submitted?
```

The core rule is:

```text
State vocabulary is shared.
State persistence belongs to RunStore.
State transitions are decided by the runner and planner.
```

### 1.1 Alignment With `loom.md`

[loom.md](../loom.md) requires stage status tracking and run directories. This
document defines the shared state vocabulary that makes those requirements
consistent across planning, execution, resume, run stores, CLI output, tests, and
optional executors.

---

## 2. Core Position

The state component sits between static pipeline specs and persisted run-store
documents.

Recommended dependency shape:

```text
ids / timestamps / serialization / errors
        |
        v
pipeline.status
        |
        v
planning / execution / run stores / resume / cli / slurm
```

It may depend on:

```text
enum
dataclasses
typing
loom.timestamps
loom.serialization
loom.errors
```

It should not depend on:

```text
loom.config
loom.pipeline.runner
loom.pipeline.executors
loom.pipeline.stores.local_runs
project code
SLURM command wrappers
```

This keeps status values and records reusable across planning, execution, and
inspection.

---

## 3. Package Boundary

### 3.1 `loom.pipeline.status`

Owns status enums and lightweight status records.

Responsibilities:

```text
RunStatus
StageStatus
StatusRecord
RunStatusRecord
StageStatusRecord
valid transition helpers
status serialization helpers
status display ordering
```

### 3.2 `loom.pipeline.execution`

Owns lifecycle transition decisions during execution.

Responsibilities:

```text
mark run RUNNING
mark stage RUNNING
mark stage SUCCEEDED only after output validation
mark stage FAILED after failure metadata is persisted
mark stage BLOCKED when a stage is not executed because a dependency or
prerequisite prevents it
finalize run status
```

### 3.3 `loom.pipeline.planning`

Owns plan actions and reuse decisions.

Responsibilities:

```text
decide RUN, REUSE, SKIP, BLOCKED, or STALE actions
inspect prior state snapshots
treat old RUNNING conservatively
propagate upstream invalidation
```

Planning actions are not always persisted statuses.

### 3.4 `loom.pipeline.stores`

Owns persisted run and stage state.

Responsibilities:

```text
write status.json
read status.json
write atomically
scan run state
detect corrupt state files
report locks and stale RUNNING state
```

V9 authority-backed runs keep `RunStatus` and `StageStatus` coarse. Attempts,
leases, submitted operations, output commits, static branch outcomes, recovery
facts, reasons, and display detail live in authoritative store records and
derived lifecycle snapshots rather than new status enum values. Human-readable
status files are not fallback active truth for new authority-backed runs.

### 3.5 `loom.cli`

Owns status presentation.

Responsibilities:

```text
format run status tables
format stage status tables
map state errors to exit codes
display scheduler state only when requested
```

### 3.6 `loom.pipeline.executors.slurm`

Owns scheduler state metadata.

Responsibilities:

```text
record job IDs
record scheduler state
combine scheduler state with loom state for inspection
```

Scheduler state supplements `loom` state. It does not replace stage status.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
RunStatus enum
StageStatus enum
RunStatusRecord
StageStatusRecord
BLOCKED stage status for durable blocked outcomes
attempt field for stages
started_at and finished_at fields
message/reason fields
owner metadata for RUNNING state
valid transition helpers
plain-data serialization
clear corrupt/invalid status errors
tests for status meanings and transitions
```

### 4.2 Should Support Soon

```text
state snapshots for planning
stage state bundles
interrupted RUNNING detection helpers
display ordering helpers
status summary/count helpers
attempt history
```

### 4.3 Should Not Support in v0

```text
database-backed state
distributed locking semantics
automatic process liveness across machines
SLURM state as primary stage status
opaque state machine framework
domain-specific stage states
automatic repair of corrupt state
```

Keep status explicit and inspectable.

---

## 5. Terminology

### 5.1 Run State

The overall state of one pipeline run.

### 5.2 Stage State

The state of one stage within a run.

### 5.3 Status

A stable enum-like value persisted in state files.

### 5.4 Transition

A movement from one status to another.

Example:

```text
PENDING -> RUNNING -> SUCCEEDED
```

### 5.5 Plan Action

A planner decision about what should happen.

Examples:

```text
RUN
REUSE
SKIP
BLOCKED
```

Plan actions are not identical to persisted statuses.

### 5.6 Scheduler State

Backend-specific state such as SLURM `PENDING`, `RUNNING`, `COMPLETED`, or
`FAILED`.

Scheduler state is metadata. `loom` status remains the primary workflow state.

---

## 6. Run Status

### 6.1 Recommended Values

```text
CREATED
PLANNED
RUNNING
SUCCEEDED
FAILED
CANCELLED
INTERRUPTED
```

### 6.2 Meanings

```text
CREATED:
  run directory exists but planning has not completed

PLANNED:
  plan and resolved config are persisted, execution has not started

RUNNING:
  one or more stages may be executing

SUCCEEDED:
  all required selected work completed successfully

FAILED:
  execution completed unsuccessfully or a stage failed

CANCELLED:
  user explicitly cancelled the run

INTERRUPTED:
  run was interrupted before clean completion
```

### 6.3 Normal Flow

```text
CREATED -> PLANNED -> RUNNING -> SUCCEEDED
```

### 6.4 Failure Flow

```text
CREATED -> PLANNED -> RUNNING -> FAILED
```

### 6.5 Cancellation Flow

```text
RUNNING -> CANCELLED
```

### 6.6 Recovery Flow

```text
RUNNING from old process -> INTERRUPTED or RUNNING with new attempt
FAILED -> RUNNING on resume
INTERRUPTED -> RUNNING on resume
```

The runner owns these transition decisions. The run store persists them.

---

## 7. Stage Status

### 7.1 Recommended Values

```text
PENDING
RUNNING
SUCCEEDED
FAILED
BLOCKED
SKIPPED
STALE
CANCELLED
```

### 7.2 Meanings

```text
PENDING:
  known but not started

RUNNING:
  currently executing or was interrupted while executing

SUCCEEDED:
  completed and outputs were validated

FAILED:
  completed unsuccessfully with failure metadata

BLOCKED:
  not executed because a dependency or prerequisite prevents execution

SKIPPED:
  excluded by selector or condition

STALE:
  previous result exists but is not reusable

CANCELLED:
  explicitly stopped before completion
```

### 7.3 Normal Flow

```text
PENDING -> RUNNING -> SUCCEEDED
```

### 7.4 Failure Flow

```text
PENDING -> RUNNING -> FAILED
```

### 7.5 Resume Flow

```text
SUCCEEDED -> SKIPPED or reused by plan
SUCCEEDED -> STALE -> RUNNING -> SUCCEEDED
FAILED -> RUNNING -> SUCCEEDED
RUNNING from old process -> STALE or RUNNING with new attempt
```

### 7.6 Reuse Is Not a Status

`REUSE` is a planner action, not necessarily a persisted stage status.

A reused stage may keep its existing:

```text
SUCCEEDED
```

status and appear as `REUSE` in the plan output.

### 7.7 Blocked Is Not a Success State

`BLOCKED` is a durable stage status for a known stage that did not execute
because a dependency or prerequisite made execution impossible. It is not a
successful or reusable result.

Downstream stages can remain:

```text
PENDING
```

or be represented in persisted state as:

```text
BLOCKED
```

Phase 4 provides the status record and status-only lifecycle writer. The v0-post
runner lifecycle now uses that writer to persist blocked descendants after the
first failed stage, so failed local runs have durable downstream `BLOCKED`
records rather than only in-memory blocked results.

---

## 8. Status Records

### 8.1 `RunStatusRecord`

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class RunStatusRecord:
    schema_version: int
    run_id: str
    status: RunStatus
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    message: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

### 8.2 `StageStatusRecord`

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class StageStatusRecord:
    schema_version: int
    run_id: str
    stage_name: str
    status: StageStatus
    attempt: int
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    message: str | None = None
    owner: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

### 8.3 Attempt

Every stage status should include an integer attempt number.

Recommended behavior:

```text
first execution attempt is 1
retry or rerun increments attempt
inputs/outputs/fingerprint files represent the latest attempt
older attempts may be archived later
```

V0 may overwrite latest state, but the failure file should at least record the
current attempt.

### 8.4 Owner Metadata

RUNNING status should include enough owner metadata to debug stale state.

Examples:

```text
host
pid
executor
slurm_job_id
started_at
command
```

Owner metadata is best-effort. It should not be required for all executors.

---

## 9. Transition Ownership

### 9.1 Runner Owns Lifecycle Transitions

The runner should be the only component that decides normal stage lifecycle
transitions.

This prevents local, subprocess, and future cluster execution from drifting into
different state semantics.

### 9.2 Executors Report Results

Executors should return structured results:

```text
SUCCEEDED-like result with outputs
FAILED-like result with failure metadata
backend error for infrastructure failure
```

Executors should not independently mark high-level state except through the
runner or a worker API designed by execution.

### 9.3 RunStore Persists Decisions

Run stores should validate and persist transitions, but should not decide resume
semantics.

### 9.4 Planner Owns Reuse Decisions

The planner decides:

```text
RUN
REUSE
SKIP
STALE
BLOCKED
```

by inspecting state snapshots, fingerprints, artifacts, and selectors.

---

## 10. Success and Failure Semantics

### 10.1 Success Requires Validated Outputs

A stage should not be marked `SUCCEEDED` merely because its Python call returned
or its process exited with code 0.

Success requires:

```text
executor completed successfully
required outputs were returned or registered
outputs are valid ArtifactRef values
required artifact files exist when local validation applies
optional checksum validation passes when enabled
outputs.json is persisted
artifact index is updated
stage status is marked SUCCEEDED
```

If any step fails, the stage should be failed or treated as incomplete.

### 10.2 Failure Requires Durable Metadata

Before marking `FAILED`, execution should persist:

```text
failure summary
exception type or exit code
log paths
traceback path when available
attempt
finished_at
```

### 10.3 Skipped Stages

`SKIPPED` is appropriate when a stage is excluded by selector or condition and
the run store tracks selected-out stages.

For v0, it is also acceptable for unselected stages to remain absent from stage
state if the plan records selection.

### 10.4 Stale Stages

`STALE` means previous state exists but should not be reused.

Examples:

```text
fingerprint changed
required output missing
upstream artifact changed
old RUNNING state cannot be verified
```

The planner may report stale without immediately rewriting persisted state.

---

## 11. State Snapshots

### 11.1 Purpose

A state snapshot is a read-only summary of persisted run state used by planning,
resume, status, and tests.

Representative structures:

```text
RunStateSnapshot
StageStateBundle
```

### 11.2 `StageStateBundle`

Should include:

```text
stage status
inputs
outputs
fingerprint
failure metadata
provenance summary
log paths
artifact refs
corrupt/missing file markers
```

### 11.3 `RunStateSnapshot`

Should include:

```text
run status
plan summary
stage bundles
artifact index summary
lock state
schema versions
corrupt state markers
```

### 11.4 Snapshot Rules

Snapshots should:

```text
be immutable
not mutate run state
represent missing/corrupt state explicitly
be safe for CLI status without importing project code
```

---

## 12. Old RUNNING State

### 12.1 Conservative Handling

A stage left in `RUNNING` from an old process should not be reused.

Recommended behavior:

```text
if owner appears live, refuse conflicting execution
if owner is not live or cannot be verified, treat as incomplete or stale
do not reuse outputs without SUCCEEDED status and matching fingerprint
preserve old metadata for debugging
```

### 12.2 No Silent Repair

Do not silently rewrite ambiguous state in v0.

Potential explicit future commands:

```text
loom repair-state RUN_DIR
loom mark-interrupted RUN_DIR STAGE
```

### 12.3 SLURM State

SLURM job state can help interpret old `RUNNING` stages.

Precedence:

```text
loom run-store state
scheduler final job state when available
scheduler queue state when available
submission manifest as last known state
```

Scheduler state remains supplementary.

---

## 13. Persistence Boundary

### 13.1 RunStore Owns Files

The status component defines shapes and transitions.

RunStore owns:

```text
status.json paths
atomic writes
locking
recovery behavior
schema checks
```

### 13.2 JSON Shapes

Status records should be plain-data compatible and versioned:

```json
{
  "schema_version": 1,
  "run_id": "example",
  "stage_name": "train",
  "status": "RUNNING",
  "attempt": 1,
  "updated_at": "2026-05-02T00:00:00Z"
}
```

### 13.3 Corrupt State

Invalid JSON, missing required fields, invalid statuses, or incompatible schema
versions should be reported as corrupt state by the run store.

The planner should treat corrupt state as not reusable unless the user
explicitly chooses a repair/rerun policy.

---

## 14. CLI and Display

### 14.1 Status Ordering

Suggested display order:

```text
FAILED
RUNNING
STALE
PENDING
SKIPPED
SUCCEEDED
CANCELLED
```

For run summaries:

```text
FAILED
RUNNING
INTERRUPTED
CANCELLED
SUCCEEDED
PLANNED
CREATED
```

### 14.2 Status Tables

CLI status should show:

```text
stage name
status
attempt
started_at
finished_at
reason/message
log paths for failed stages
```

### 14.3 Machine Output

JSON output should use the serialized status records and state snapshots rather
than parsing table strings.

---

## 15. Error Model

### 15.1 Error Types

Status-specific errors can live in `loom.pipeline.errors` or
`loom.pipeline.status`.

Recommended:

```python
class InvalidStatusError(PipelineError): ...
class InvalidStatusTransitionError(PipelineError): ...
class StatusSerializationError(PipelineError): ...
```

Run-store file errors remain run-store errors:

```text
CorruptRunStateError
StageStateNotFoundError
```

### 15.2 Error Context

Errors should include:

```text
run ID
stage name
prior status
new status
file path, when persisted state is involved
operation
```

---

## 16. Testing Strategy

### 16.1 Status Value Tests

Test:

```text
run status values
stage status values
string serialization
invalid status rejected
display ordering
```

### 16.2 Transition Tests

Test:

```text
run normal flow
run failure flow
run cancellation flow
stage normal flow
stage failure flow
resume rerun flow
invalid transitions rejected or reported
```

### 16.3 Record Tests

Test:

```text
RunStatusRecord to_dict/from_dict
StageStatusRecord to_dict/from_dict
attempt required for stage status
owner metadata plain-data compatible
schema version validation
```

### 16.4 Integration Tests

Test:

```text
runner writes RUNNING before stage execution
runner writes SUCCEEDED only after outputs/artifacts are persisted
runner writes failure metadata before FAILED
resume does not reuse old RUNNING state
CLI status reads snapshots without project imports
SLURM metadata supplements but does not replace stage status
```

---

## 17. Implementation Plan

### 17.1 Phase 1: Status Types

Create or update:

```text
src/loom/pipeline/status.py
```

Implement:

```text
RunStatus
StageStatus
RunStatusRecord
StageStatusRecord
serialization helpers
```

### 17.2 Phase 2: Transition Helpers

Implement:

```text
valid_run_transition
valid_stage_transition
ensure_run_transition
ensure_stage_transition
```

Keep helpers small. The runner still owns decisions.

### 17.3 Phase 3: Store Integration

Update RunStore to read and write the status records.

### 17.4 Phase 4: Execution Integration

Update runner lifecycle to use status helpers and records.

### 17.5 Phase 5: Planning and Resume Integration

Update planner to consume state snapshots and distinguish plan actions from
persisted statuses.

### 17.6 Phase 6: CLI Integration

Update status command formatting to use state snapshots and display helpers.

---

## 18. Open Questions

### 18.1 Should `REUSED` Be a Persisted Stage Status?

Recommended v0 answer:

```text
no
```

Use `REUSE` as a planner action and keep prior `SUCCEEDED` state.

### 18.2 Should `BLOCKED` Be Persisted?

Recommended answer:

```text
yes, as a status-only stage outcome
```

Blocked is caused by failed/skipped/upstream or prerequisite state. Persisting
it should write `stages/STAGE/status.json` with `StageStatus.BLOCKED`, not
inputs, outputs, artifacts, fingerprints, failure metadata, provenance, or logs
for a stage that did not execute.

### 18.3 Should `STALE` Be Persisted?

Recommended answer:

```text
optional
```

It is useful for inspection but not required for correctness. The planner can
report stale without mutating state.

### 18.4 Should Attempt History Be Preserved?

Recommended v0 answer:

```text
latest attempt only
```

Add attempt archives later if debugging needs justify it.

### 18.5 Should Process Liveness Be Checked?

Recommended answer:

```text
best effort only
```

Cross-machine liveness is hard. Locks and owner metadata should make ambiguity
visible rather than pretending certainty.

---

## 19. Summary

`loom.pipeline.status` should provide the shared state vocabulary and status
record shapes for runs and stages.

Its main jobs are:

```text
define RunStatus
define StageStatus
define status records
document valid transitions
separate persisted statuses from planner actions
support immutable state snapshots
make old RUNNING state conservative
support CLI/status display and JSON output
```

It should not become:

```text
a run store
an executor
a resume planner
a scheduler-state replacement
a distributed lock manager
a hidden global state registry
```

Keeping state semantics explicit lets execution, resume, stores, CLI, SLURM, and
tests agree on the same meanings without duplicating status logic.
