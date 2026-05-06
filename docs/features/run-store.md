# `loom.pipeline.stores.run_store` Specification

## 1. Purpose

The run store is the persistent state layer for `loom` pipeline runs.

It exists to make runs inspectable, resumable, debuggable, and safe under
interruption. It should define the run directory layout, stage state files,
status transitions, input and output records, fingerprints, logs, execution
plans, artifact indexes, append-only event records, conservative local run
locks, and atomic write behavior.

The run store should not know how to execute stages. It should not know how to
load domain data. It should not own artifact serialization or artifact object
storage beyond recording `ArtifactRef` metadata.

The central boundary is:

```text
RunStore:
  persistent run and stage state

ArtifactStore:
  artifact bytes, object save/load, and ArtifactRef creation

PipelineRunner:
  execution lifecycle and state transitions

Stage implementations:
  concrete work and domain-specific outputs
```

The local filesystem run store is the v0 implementation. Its files should be
plain and human-inspectable so users can debug failed cluster jobs without
special tooling.

### 1.1 V2 Run URI Migration

The v0 sections below use `run_id` as the run-scoped identifier because that is
the local-kernel contract. The v2 CLI-core implementation plan intentionally
hard-swaps public, protocol, and persisted run identity to `run_uri`.

After the v2 migration:

```text
public/protocol/persisted run identity: run_uri
local implementation detail: resolved file:// URI -> local run directory
```

V2 does not need to preserve compatibility with old v0 run documents that only
contain `run_id`. `ArtifactRef` remains physical artifact metadata; cross-run
artifact identity uses `ArtifactAddress(run_uri, artifact_id)`.

### 1.2 Alignment With `loom.md`

This document turns the run directory, status tracking, artifact index, and
resume-inspection goals from [loom.md](../loom.md) into a persistence contract.
`loom` should favor local, plain, schema-versioned files in v0 so config,
pipeline, execution, provenance, and resume state can be inspected without
domain tooling.

---

## 2. Core Position

Use this architecture:

```text
Pipeline runner:
  decides what should happen

Run store:
  records what did happen and what state is reusable

Artifact store:
  persists and verifies artifacts

CLI:
  presents run state to users
```

This means the run store is not a scheduler, a database-backed orchestration
service, or an artifact codec system. It is a structured persistence layer for
pipeline state.

The first implementation should be conservative:

```text
plain files
atomic writes
simple JSON/YAML documents
stable paths
clear schema versions
no required database
```

Databases, remote stores, and richer indexes can be added later only if the local
file layout remains an understandable source of truth.

---

## 3. Package Boundary

### 3.1 `loom.pipeline`

Owns orchestration.

Responsibilities:

```text
build execution plans
compute stage actions
invoke executors
validate stage outputs
decide status transitions
decide resume behavior
```

The pipeline runner should call the run store instead of hard-coding filesystem
paths.

### 3.2 `loom.pipeline.stores.run_store`

Owns the run-state protocol.

Responsibilities:

```text
create and open runs
prepare runtime directories through local helpers only
read and write run documents
read and write run user metadata
read and write run status
read and write execution plans
read and write stage status
append and read run event records
acquire, read, and release run locks
read and write stage inputs
read and write stage outputs
read and write stage fingerprints
read and write stage failure metadata
read and write artifact indexes
provide local log/path helpers
provide recovery scans
```

### 3.3 `loom.pipeline.stores.local_runs`

Owns the local filesystem implementation of `RunStore`.

Responsibilities:

```text
directory creation
path normalization
JSON/YAML file persistence
atomic file replacement
local log paths
local event logs
local lock files
interrupted-run inspection
```

### 3.4 `loom.pipeline.stores.artifact_store`

Owns artifact persistence.

Responsibilities:

```text
save artifacts
load artifacts
allocate artifact refs
verify artifact existence
verify checksums when supported
```

The run store may record artifact refs and artifact indexes, but it should not
own object-to-bytes conversion.

### 3.5 `loom.config`

Owns config composition and resolved config export.

Responsibilities:

```text
raw config snapshot
overlay snapshot
CLI override snapshot
recipe manifest
resolved config
config provenance
secret redaction
```

The run store provides paths and persistence helpers for these files, but config
semantics remain in `loom.config`.

### 3.6 `loom.cli`, Post-v0

Owns command-line presentation.

Responsibilities:

```text
loom status
loom logs
loom artifacts list
loom artifacts show
loom plan
exit codes and terminal formatting
```

The CLI should read through public APIs, not by duplicating path logic.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
LocalRunStore
run directory creation
opening existing run directories
stable local run layout
run document file
run user metadata section
run status file
execution plan file
config snapshot paths
stage directory creation
stage status files
stage inputs files
stage outputs files
stage fingerprint files
stage failure files
stage log path helpers
run-level artifact index
atomic JSON writes
safe directory creation
basic stale RUNNING detection
path-aware store errors
schema version fields in persisted documents
append-only events.jsonl
conservative local lock.json
```

V0 should support this lifecycle:

```text
create run
persist config snapshot
persist plan
mark stage RUNNING
write inputs
run stage
write outputs
write fingerprint
update artifact index
mark stage SUCCEEDED
open run later
reconstruct state for resume
```

### 4.2 Should Not Support in v0

```text
required database backend
remote run stores
distributed locking
automatic schema migrations
content-addressed artifact storage
large artifact garbage collection
web dashboard indexing
full audit log event sourcing
cloud object store synchronization
multi-writer controller mode
```

The first implementation should prioritize correct local behavior. Cluster
support can still use the local run store on a shared filesystem.

---

## 5. Terminology

### 5.1 Run

One attempted or completed execution of a resolved pipeline configuration.

A run may contain succeeded, failed, skipped, stale, or pending stages.

### 5.2 Run ID

A stable identifier for a run.

The run ID should be safe as a path component and stable across resume attempts.

### 5.3 Run Directory

The root directory containing all persisted state for one run.

Example:

```text
runs/example/20260502-153000/
```

or:

```text
runs/20260502-153000-example/
```

The exact naming policy can be configurable, but the internal layout should be
stable.

### 5.4 Stage Directory

The directory containing persisted state for one stage invocation within a run.

Example:

```text
runs/RUN_ID/stages/train/
```

### 5.5 Run Status

The overall state of a run.

Recommended values:

```text
CREATED
PLANNED
RUNNING
SUCCEEDED
FAILED
CANCELLED
INTERRUPTED
```

### 5.6 Stage Status

The persisted state of one stage.

Recommended values:

```text
PENDING
RUNNING
SUCCEEDED
FAILED
SKIPPED
STALE
CANCELLED
```

### 5.7 Stage Inputs File

A persisted mapping of stage input names to upstream `ArtifactRef`s.

This file records exactly which artifacts were presented to a stage.

### 5.8 Stage Outputs File

A persisted mapping of stage output names to returned `ArtifactRef`s.

This file records exactly which artifacts a successful stage produced.

### 5.9 Artifact Index

A run-level mapping from logical artifact names to `ArtifactRef`s.

Example:

```text
train.best_checkpoint -> ArtifactRef(...)
evaluate.metrics -> ArtifactRef(...)
```

The artifact index supports downstream binding and inspection without scanning
every stage directory.

### 5.10 Fingerprint File

A persisted record of a stage fingerprint and the structured inputs used to
compute it.

The planner uses this file to decide whether previous outputs are reusable.

### 5.11 Failure File

A persisted record of failure metadata for a failed stage.

It should include exception or exit information, timestamps, and log paths.

---

## 6. Guiding Design Principles

### 6.1 Inspectable Without Python

Users should be able to inspect a run with ordinary shell tools.

Prefer:

```text
run.json
status.json
plan.json
inputs.json
outputs.json
fingerprint.json
failure.json
artifacts.json
stdout.log
stderr.log
```

Avoid opaque-only databases in v0.

### 6.2 Separate State from Artifacts

Run state files describe execution. Artifact files are outputs produced by
stages.

Keep these separate:

```text
stages/train/status.json:
  execution state

artifacts/train/best.ckpt:
  produced artifact bytes

stages/train/outputs.json:
  ArtifactRefs pointing to produced artifacts
```

### 6.3 Atomic State Writes

Run and stage state files should be replaced atomically.

Recommended pattern:

```text
write to temporary file in same directory
flush and fsync when practical
rename into final path
never update JSON files in place
```

This matters because interrupted writes are normal on laptops and clusters.

### 6.4 Conservative Reuse

The run store should make stale or incomplete state visible. It should not decide
semantic reuse by itself.

Recommended rule:

```text
run store reports persisted state
planner decides whether persisted state is reusable
```

The run store may provide helpers such as `stage_has_complete_success_record`,
but the planner owns resume policy.

### 6.5 Stable Paths Are Part of the Contract

The local layout should be treated as a user-facing contract once released.

Internal code can move. Run files from old experiments should remain readable for
as long as practical.

### 6.6 Path Safety

Run IDs and stage names must not allow path traversal.

Reject:

```text
empty names
absolute paths
names containing slash or backslash
.
..
control characters
```

Normalize only if the normalization is documented and collision-safe.

### 6.7 Minimal Global State

The run store should not rely on process-global current run state.

Good:

```python
run_store.write_stage_status(run_id, stage_name, status)
```

Avoid:

```python
set_current_run(run_id)
write_stage_status(stage_name, status)
```

Explicit identifiers make subprocess and SLURM behavior easier.

---

## 7. Local Run Directory Layout

### 7.1 Recommended Layout

```text
runs/RUN_ID/
  run.json
  status.json
  plan.json
  artifacts.json

  config/
    raw.yaml
    overlays.yaml
    cli_overrides.yaml
    recipe_manifest.json
    resolved.yaml
    resolved.redacted.yaml

  provenance/
    environment.json
    git.json
    command.json
    dependencies.json

  stages/
    STAGE_NAME/
      status.json
      inputs.json
      outputs.json
      fingerprint.json
      failure.json
      provenance.json
      logs/
        stdout.log
        stderr.log

  artifacts/
    STAGE_NAME/
      ...
```

V0 does not need every file to exist for every run. The layout should reserve
these locations so later features do not require churn.

Future sidecar files may include:

```text
annotations.json:
  user/project tags, notes, owner, and other human-oriented run metadata

input_inventory.json:
  external inputs resolved for the run, such as source paths, discovered files,
  checksums, and project-supplied source metadata

events.jsonl:
  append-friendly lifecycle events for inspection and later external
  notification tools

lock.json:
  conservative local run lock with token and owner metadata
```

These files are created only when the corresponding capability is used. Event
records are audit facts rather than the source of current state, and lock state
is local coordination state rather than distributed truth. V0 should not require
a global run catalog, but the local layout should make one easy to rebuild by
scanning run directories.

### 7.2 Required v0 Files

For a successful local run:

```text
run.json
status.json
plan.json
artifacts.json
config/resolved.yaml
stages/STAGE_NAME/status.json
stages/STAGE_NAME/inputs.json
stages/STAGE_NAME/outputs.json
stages/STAGE_NAME/fingerprint.json
```

For a failed stage:

```text
stages/STAGE_NAME/status.json
stages/STAGE_NAME/failure.json
stages/STAGE_NAME/logs/stdout.log
stages/STAGE_NAME/logs/stderr.log
```

### 7.3 File Formats

Recommended:

```text
YAML:
  authored and resolved configs

JSON:
  machine-written state, indexes, statuses, fingerprints, provenance records

Plain text:
  stdout and stderr logs
```

JSON is preferred for state because it is easy to parse, deterministic, and
language-neutral.

### 7.4 Directory Creation

Directory creation should be idempotent.

Required behavior:

```text
creating a new run fails if the target run directory already exists unless resume/open is requested
opening an existing run validates that required root files are well formed when present
creating a stage directory fails on unsafe stage names
missing optional directories are created as needed
```

---

## 8. Persisted Documents

### 8.1 Common Document Fields

All machine-written JSON documents should include:

```text
schema_version
created_at or updated_at
loom_version when available
```

For example:

```json
{
  "schema_version": 1,
  "updated_at": "2026-05-02T05:30:00Z",
  "status": "RUNNING"
}
```

### 8.2 `run.json`

Purpose: stable run metadata.

Recommended fields:

```text
schema_version
run_id
name
created_at
run_dir
pipeline_name
config_hash
loom_version
metadata
```

`run.json` should not be rewritten frequently. Use `status.json` for changing
run state.

Human-oriented run tags, notes, and owner fields may live under `metadata` in
v0-compatible documents. If they become large or frequently edited later, move
them to an optional `annotations.json` sidecar rather than rewriting core status
files.

### 8.3 Root `status.json`

Purpose: current run status.

Recommended fields:

```text
schema_version
run_id
status
started_at
updated_at
finished_at
stage_counts
current_stage
failure_stage
message
```

`stage_counts` can be derived, but storing it makes CLI status fast and simple.

### 8.4 `plan.json`

Purpose: execution plan used for the current run attempt.

Recommended fields:

```text
schema_version
run_id
created_at
resume
selectors
stage_plans
reasons
pipeline_hash
```

The plan file should be overwritten when a new run attempt replans the same run
directory.

### 8.5 Root `artifacts.json`

Purpose: run-level artifact index.

Recommended fields:

```text
schema_version
run_id
updated_at
artifacts
```

Where `artifacts` maps logical names to serialized `ArtifactRef`s:

```json
{
  "schema_version": 1,
  "run_id": "example",
  "updated_at": "2026-05-02T05:30:00Z",
  "artifacts": {
    "train.best_checkpoint": {
      "artifact_id": "train/best_checkpoint",
      "uri": "file:///runs/example/artifacts/train/best.ckpt",
      "artifact_type": "checkpoint",
      "schema_version": 1,
      "checksum": "sha256:..."
    }
  }
}
```

The exact `ArtifactRef` fields should be defined in `artifacts.md`.

Future local run catalogs should be derived from `run.json`, `status.json`,
`plan.json`, `artifacts.json`, and optional annotation/inventory sidecars. The
run store should not require a database-backed catalog before local directory
semantics are stable.

### 8.6 Stage `status.json`

Purpose: current stage status.

Recommended fields:

```text
schema_version
run_id
stage_name
status
attempt
started_at
updated_at
finished_at
executor
pid
host
slurm_job_id
message
```

Not all fields apply to every executor. Unknown executor metadata should live in
a nested `executor_metadata` mapping if needed.

### 8.7 Stage `inputs.json`

Purpose: exact bound inputs for a stage attempt.

Recommended fields:

```text
schema_version
run_id
stage_name
attempt
created_at
inputs
```

Where `inputs` maps input names to serialized `ArtifactRef`s.

### 8.8 Stage `outputs.json`

Purpose: exact outputs returned by a successful stage.

Recommended fields:

```text
schema_version
run_id
stage_name
attempt
created_at
outputs
```

Where `outputs` maps output names to serialized `ArtifactRef`s.

### 8.9 Stage `fingerprint.json`

Purpose: persisted stage fingerprint.

Recommended fields:

```text
schema_version
run_id
stage_name
attempt
created_at
algorithm
fingerprint
inputs_summary
```

`inputs_summary` should be enough to explain reuse decisions without dumping
large configs into every stage directory.

### 8.10 Stage `failure.json`

Purpose: persisted failure metadata.

Recommended fields:

```text
schema_version
run_id
stage_name
attempt
failed_at
executor
exception_type
message
traceback
traceback_path
exit_code
stdout_path
stderr_path
```

For subprocess and SLURM execution, `exit_code` and log paths may be more
important than Python exception fields.

### 8.11 Stage `provenance.json`

Purpose: stage-specific provenance.

Recommended fields:

```text
schema_version
run_id
stage_name
created_at
target
input_artifacts
output_artifacts
fingerprint
executor_metadata
stage_metadata
```

Detailed provenance policy should live in `provenance.md`. The run store only
defines where this file belongs and how it is written.

---

## 9. RunStore Protocol

The v0-oriented protocol sketch below uses `run_id`. For v2, the same public
and protocol methods should hard-swap that argument and serialized field to
`run_uri`. Local store implementations may derive private path components from a
resolved local `file://` run URI, but callers should not pass or receive
`run_id`.

### 9.1 Recommended Interface

```python
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Protocol

from loom.artifacts import ArtifactRef
from loom.pipeline.events import PipelineEvent, PipelineEventRecord
from loom.pipeline.locks import RunLockRecord
from loom.pipeline.status import RunStatusRecord, StageStatusRecord
from loom.serialization import PlainData

class RunLifecycleStore(Protocol):
    def create_run(self, run_id: str, *, metadata: Mapping[str, PlainData] | None = None) -> None: ...
    def open_run(self, run_id: str) -> None: ...

class RunDocumentStore(Protocol):
    def read_run_document(self, run_id: str) -> dict[str, PlainData]: ...
    def read_run_user_metadata(self, run_id: str) -> dict[str, PlainData]: ...
    def write_run_user_metadata(self, run_id: str, metadata: Mapping[str, PlainData]) -> None: ...

class RunStatusStore(Protocol):
    def read_run_status(self, run_id: str) -> RunStatusRecord | None: ...
    def write_run_status(self, run_id: str, status: RunStatusRecord) -> None: ...

class RunPlanStore(Protocol):
    def read_plan(self, run_id: str) -> dict[str, PlainData] | None: ...
    def write_plan(self, run_id: str, plan: Mapping[str, PlainData]) -> None: ...

class RunArtifactIndexStore(Protocol):
    def read_artifact_index(self, run_id: str) -> dict[str, ArtifactRef]: ...
    def write_artifact_index(self, run_id: str, index: Mapping[str, ArtifactRef]) -> None: ...

class RunConfigStore(Protocol):
    def read_config_snapshot(self, run_id: str, name: str) -> str | None: ...
    def write_config_snapshot(self, run_id: str, name: str, content: str) -> None: ...
    def read_recipe_manifest(self, run_id: str) -> tuple[dict[str, PlainData], ...] | None: ...
    def write_recipe_manifest(self, run_id: str, records: Sequence[Mapping[str, PlainData]]) -> None: ...

class RunProvenanceStore(Protocol):
    def read_provenance_document(self, run_id: str, name: str) -> dict[str, PlainData] | None: ...
    def write_provenance_document(self, run_id: str, name: str, document: Mapping[str, PlainData]) -> None: ...

class RunEventStore(Protocol):
    def append_event(self, run_id: str, event: PipelineEvent) -> PipelineEventRecord: ...
    def read_events(self, run_id: str) -> tuple[PipelineEventRecord, ...]: ...

class RunLockStore(Protocol):
    def acquire_run_lock(self, run_id: str, *, owner: Mapping[str, PlainData] | None = None) -> RunLockRecord: ...
    def read_run_lock(self, run_id: str) -> RunLockRecord | None: ...
    def release_run_lock(self, run_id: str, token: str) -> None: ...

class StageStateStore(Protocol):
    def read_stage_status(self, run_id: str, stage_name: str) -> StageStatusRecord | None: ...
    def write_stage_status(self, run_id: str, stage_name: str, status: StageStatusRecord) -> None: ...
    def read_stage_inputs(self, run_id: str, stage_name: str) -> dict[str, ArtifactRef] | None: ...
    def write_stage_inputs(self, run_id: str, stage_name: str, inputs: Mapping[str, ArtifactRef], *, attempt: int) -> None: ...
    def read_stage_outputs(self, run_id: str, stage_name: str) -> dict[str, ArtifactRef] | None: ...
    def write_stage_outputs(self, run_id: str, stage_name: str, outputs: Mapping[str, ArtifactRef], *, attempt: int) -> None: ...
    def read_stage_fingerprint(self, run_id: str, stage_name: str) -> dict[str, PlainData] | None: ...
    def write_stage_fingerprint(self, run_id: str, stage_name: str, fingerprint: Mapping[str, PlainData], *, attempt: int) -> None: ...
    def read_stage_failure(self, run_id: str, stage_name: str) -> dict[str, PlainData] | None: ...
    def write_stage_failure(self, run_id: str, stage_name: str, failure: Mapping[str, PlainData], *, attempt: int) -> None: ...
    def read_stage_provenance(self, run_id: str, stage_name: str) -> dict[str, PlainData] | None: ...
    def write_stage_provenance(self, run_id: str, stage_name: str, provenance: Mapping[str, PlainData], *, attempt: int) -> None: ...

class StageLogStore(Protocol):
    def read_stage_log(self, run_id: str, stage_name: str, stream: str) -> str | None: ...
    def write_stage_log(self, run_id: str, stage_name: str, stream: str, content: str) -> None: ...

class StageWorkspaceStore(Protocol):
    def prepare_stage_workspace(self, run_id: str, stage_name: str) -> None: ...

class RunStore(
    RunLifecycleStore,
    RunDocumentStore,
    RunStatusStore,
    RunPlanStore,
    RunArtifactIndexStore,
    RunConfigStore,
    RunProvenanceStore,
    RunEventStore,
    RunLockStore,
    StageStateStore,
    StageLogStore,
    StageWorkspaceStore,
    Protocol,
):
    ...

class LocalRunStorePaths(Protocol):
    def local_run_dir(self, run_id: str) -> Path: ...
    def local_stage_dir(self, run_id: str, stage_name: str) -> Path: ...
    def local_artifact_root(self, run_id: str) -> Path: ...
    def local_stage_artifact_dir(self, run_id: str, stage_name: str) -> Path: ...
    def local_config_path(self, run_id: str, name: str) -> Path: ...
    def local_provenance_path(self, run_id: str, name: str) -> Path: ...
    def local_stage_log_path(self, run_id: str, stage_name: str, stream: str) -> Path: ...
    def local_stage_workspace_dir(self, run_id: str, stage_name: str) -> Path: ...
```

The aggregate protocol remains small and explicit: run-scoped state and metadata
operations without implicit local path return values.

### 9.2 Local Path Helpers (Explicit)

Recommended helpers:

```python
def local_run_dir(self, run_id: str) -> Path: ...
def local_stage_dir(self, run_id: str, stage_name: str) -> Path: ...
def local_artifact_root(self, run_id: str) -> Path: ...
def local_stage_artifact_dir(self, run_id: str, stage_name: str) -> Path: ...
def local_config_path(self, run_id: str, name: str) -> Path: ...
def local_provenance_path(self, run_id: str, name: str) -> Path: ...
def local_stage_log_path(self, run_id: str, stage_name: str, stream: str) -> Path: ...
def local_stage_workspace_dir(self, run_id: str, stage_name: str) -> Path: ...
```

These helpers are explicit local helpers on `LocalRunStorePaths`, not generic
protocol obligations for all store implementations.

### 9.3 Recovery Helpers

Recommended helpers:

```python
def list_stages(self, run_id: str) -> tuple[str, ...]: ...
def read_stage_state_bundle(self, run_id: str, stage_name: str) -> StageStateBundle: ...
def scan_run_state(self, run_id: str) -> RunStateSnapshot: ...
```

These can be added once the basic read/write methods are stable.

---

## 10. State Transitions

### 10.1 Run Status Transitions

Recommended normal flow:

```text
CREATED -> PLANNED -> RUNNING -> SUCCEEDED
```

Failure flow:

```text
CREATED -> PLANNED -> RUNNING -> FAILED
```

Cancellation flow:

```text
RUNNING -> CANCELLED
```

Recovery flow:

```text
RUNNING from old process -> INTERRUPTED or RUNNING with new attempt
FAILED -> RUNNING on resume
INTERRUPTED -> RUNNING on resume
```

The runner owns transition decisions. The run store should persist them.

### 10.2 Stage Status Transitions

Recommended normal flow:

```text
PENDING -> RUNNING -> SUCCEEDED
```

Failure flow:

```text
PENDING -> RUNNING -> FAILED
```

Resume flow:

```text
SUCCEEDED -> SKIPPED or reused by plan
SUCCEEDED -> STALE -> RUNNING -> SUCCEEDED
FAILED -> RUNNING -> SUCCEEDED
RUNNING from old process -> STALE or RUNNING with new attempt
```

`REUSE` is a planner action, not necessarily a persisted stage status. A reused
stage may keep its existing `SUCCEEDED` status.

### 10.3 Attempts

Every stage status should include an integer attempt number.

Recommended behavior:

```text
first execution attempt is 1
retry or rerun increments attempt
inputs/outputs/fingerprint files represent the latest attempt
older attempts may be archived later, but v0 may overwrite latest state
```

Archiving every attempt can be deferred. The failure file should at least record
the current attempt.

---

## 11. Artifact Index

### 11.1 Responsibilities

The artifact index should:

```text
map logical artifact names to ArtifactRefs
support downstream input binding
support CLI artifact inspection
support resume planning
avoid scanning all stage outputs for common lookups
```

### 11.2 Update Policy

After a stage succeeds:

```text
read current artifact index
replace entries for that stage's declared outputs
write updated index atomically
```

Logical names should use:

```text
STAGE_NAME.OUTPUT_NAME
```

### 11.3 Stale Entries

If a stage is marked stale or rerun:

```text
entries for that stage may remain for debugging
planner must not treat them as reusable without matching stage status and fingerprint
```

For v0, keep the index simple and let the planner validate reuse. Later, stale
entries can be explicitly marked or moved to history.

### 11.4 Consistency Checks

The run store can provide consistency checks:

```text
artifact index entry has matching stage outputs file
stage outputs file includes declared output
ArtifactRef local path exists when checkable
duplicate logical names are rejected
```

These checks should be used by tests and by post-v0 `loom status` /
`loom plan --resume` commands.

---

## 12. Atomic Writes

### 12.1 Required Helpers

Implement low-level helpers in `pipeline/stores/atomic.py`:

```text
atomic_write_json
atomic_write_text
atomic_write_bytes
replace_file
ensure_dir
```

### 12.2 JSON Writes

Recommended behavior:

```text
serialize with deterministic key order where practical
write newline-terminated JSON
write temp file in same directory
flush file object
fsync file when practical
rename temp path to final path
fsync parent directory when practical
remove temp file on failure
```

### 12.3 Partial Writes

On reading state files:

```text
missing optional file returns None
missing required file raises RunStoreError
invalid JSON raises CorruptRunStateError
empty file raises CorruptRunStateError
```

The planner should treat corrupt state as not reusable unless the user explicitly
asks to repair or ignore it.

---

## 13. Locking

### 13.1 V0 Locking Policy

V0 includes a conservative local run-level lock capability. It is intended to
prevent obvious same-run concurrent local writers, not to provide distributed
coordination.

Purpose:

```text
prevent two local processes from modifying the same run directory
prevent duplicate stage execution during resume
make interrupted runs easier to detect
```

`RunLockStore` is backend-neutral and does not expose local paths. The local
implementation stores the lock at `<run_dir>/lock.json`.

### 13.2 Lock File

Current `lock.json` content:

```json
{
  "schema_version": 1,
  "run_id": "run-1",
  "token": "<uuid4 hex>",
  "acquired_at": "2026-01-01T00:00:00Z",
  "owner": {
    "pid": 12345,
    "hostname": "host",
    "metadata": {}
  }
}
```

### 13.3 Stale Locks

Recommended behavior:

```text
missing lock: release fails clearly
token mismatch: release fails clearly and keeps the lock
corrupt lock: read/release fails clearly and does not remove the file
stale-owner detection: deferred
force-unlock command: deferred
```

Do not implement distributed locking in v0.

### 13.4 Stage-Level Locks

Stage-level locks are deferred until concurrent execution or controller modes
need them.

The local layout should not make stage-level locks impossible later.

---

## 14. Recovery and Inspection

### 14.1 Opening Existing Runs

When opening a run, the store should be able to report:

```text
run document plus user metadata
run status
known stage directories
stage statuses
missing state files
corrupt state files
artifact index entries
lock state when lock.json exists
```

Lock state should be reported as conservative local coordination state. It must
not be treated as proof that a remote or distributed owner is alive.

### 14.2 Interrupted RUNNING State

A stage with status `RUNNING` from an old process should not be reused.

Recommended planner behavior:

```text
if status is RUNNING, mark incomplete or stale and refuse reuse
```

The run store should expose enough metadata for the planner to make this
decision.

### 14.3 Repair

Automated repair should be limited initially.

Safe repairs:

```text
rebuild artifact index from successful stage outputs
mark old RUNNING stages as interrupted with explicit user command
remove stale lock with explicit user command, post-v0
```

Do not silently rewrite ambiguous state.

---

## 15. Public API

Recommended API:

```python
from loom.pipeline.stores import RunStore, LocalRunStore
from loom.pipeline.stores import RunStoreError, CorruptRunStateError
```

Example:

```python
run_store = LocalRunStore(root="runs")
run_dir = run_store.create_run("example", metadata={"name": "example"})

run_store.write_run_status(
    "example",
    {
        "schema_version": 1,
        "run_id": "example",
        "status": "RUNNING",
    },
)
```

Pipeline code should usually interact through higher-level runner APIs. Direct
run store usage is mainly for tests, inspection tools, and advanced integrations.

---

## 16. Post-v0 CLI Integration

When functional CLI behavior is added, the run store should support CLI commands
without becoming CLI-specific. V0 exposes public Python APIs and import-safe CLI
stubs only.

### 16.1 `loom status RUN_URI`

Should read:

```text
run.json
status.json
plan.json
stages/*/status.json
artifacts.json
failure.json files for failed stages
```

Should show:

```text
run status
stage status table
failed stage details
current or last stage
artifact counts
log paths
```

### 16.2 `loom logs RUN_URI STAGE`

Should resolve:

```text
stages/STAGE/logs/stdout.log
stages/STAGE/logs/stderr.log
```

It should not guess paths independently from the run store.

### 16.3 `loom artifacts list RUN_URI`

Should read `artifacts.json` and show logical artifact names, types, and URIs.

### 16.4 `loom inspect RUN_URI`

Can later run consistency checks:

```text
missing outputs
corrupt JSON
stale RUNNING statuses
artifact refs with missing local files
artifact index mismatch
```

---

## 17. Error Model

Recommended hierarchy:

```python
class RunStoreError(PipelineError): ...
class RunAlreadyExistsError(RunStoreError): ...
class RunNotFoundError(RunStoreError): ...
class StageStateNotFoundError(RunStoreError): ...
class CorruptRunStateError(RunStoreError): ...
class UnsafeRunPathError(RunStoreError): ...
class RunLockError(RunStoreError): ...
class RunLockConflictError(RunLockError): ...
class RunLockReleaseError(RunLockError): ...
class AtomicWriteError(RunStoreError): ...
```

### 17.1 Corrupt State Error Example

```text
Could not read stage status.

Run:
  example

Stage:
  train

Path:
  runs/example/stages/train/status.json

Reason:
  invalid JSON at line 1 column 12
```

### 17.2 Lock Error Example

```text
Run directory is locked.

Run:
  example

Lock:
  runs/example/lock.json

Owner:
  host=login01 pid=12345

Reason:
  another process may be modifying this run
```

### 17.3 Unsafe Path Error Example

```text
Unsafe stage name.

Stage:
  ../train

Reason:
  stage names cannot contain path separators or parent-directory references
```

---

## 18. Testing Strategy

### 18.1 Layout Tests

Test:

```text
create run directory
open existing run directory
reject duplicate create
create stage directory
reject unsafe run IDs
reject unsafe stage names
expected config/stage/artifact paths
```

### 18.2 State File Tests

Test:

```text
write/read run metadata
write/read run status
write/read plan
write/read stage status
write/read inputs
write/read outputs
write/read fingerprint
write/read failure metadata
write/read artifact index
missing optional files
corrupt JSON errors
```

### 18.3 Atomic Write Tests

Test:

```text
successful atomic JSON write
temp file cleanup on serialization failure
existing file preserved on write failure
newline-terminated JSON
parent directory creation
```

Fault injection can be simple in v0. Full filesystem crash simulation is not
needed.

### 18.4 Recovery Tests

Test:

```text
old RUNNING stage is reported
missing outputs for SUCCEEDED stage are reported
artifact index can be rebuilt from outputs
```

### 18.5 Runner Integration Tests

Use dummy stages to verify:

```text
runner writes expected files
failed stage writes failure.json
successful stage updates artifacts.json
resume can read previous state
force rerun updates attempt/status/fingerprint
```

---

## 19. Initial Implementation Plan

Build in this order:

1. Define run and stage status constants or enums.
2. Implement path validation helpers for run IDs and stage names.
3. Implement atomic JSON/text write helpers.
4. Implement `RunStore` protocol.
5. Implement `LocalRunStore` directory creation and path helpers.
6. Implement run-document and run-user-metadata read/write.
7. Implement plan read/write.
8. Implement stage status, inputs, outputs, and fingerprint read/write.
9. Implement failure metadata read/write.
10. Implement artifact index read/write and update helpers.
11. Add scan/recovery helpers for existing runs.
12. Connect `PipelineRunner` to `RunStore`.
13. Add CLI-backed status/log/artifact inspection later.
14. Add append-only run events and conservative local run-level locks.

Each step should include tests before higher-level pipeline code depends on it.

---

## 20. Summary

The run store should be the plain, reliable state layer for `loom` runs.

It should support:

```text
stable local run directories
human-inspectable state files
run and stage status persistence
inputs and outputs records
fingerprint records
failure metadata
artifact indexes
atomic writes
interrupted-run recovery
path-aware errors
CLI inspection
```

It should avoid:

```text
owning stage execution
owning artifact serialization
opaque database-only state
silent repair of ambiguous failures
distributed locking in v0
run-level locking before atomic/interruption tests prove it necessary
remote run stores before local behavior is stable
domain-specific assumptions
```

This gives `loom.pipeline` a durable operational foundation without turning the
runtime into a heavyweight orchestration service.
