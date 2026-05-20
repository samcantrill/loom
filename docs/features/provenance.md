# `loom.provenance` Specification

## 1. Purpose

`loom.provenance` defines generic provenance structures and lightweight capture
helpers for `loom`.

It exists so a completed or failed run can answer:

```text
What config was used?
Which code version produced this output?
Which Python/runtime environment was visible?
Which command launched the run?
Which stage produced each artifact?
Which inputs, outputs, fingerprints, and executor metadata were recorded?
Which facts were captured automatically, and which were supplied by project code?
```

Provenance should make runs debuggable and reproducible without making `loom`
depend on domain-specific frameworks.

The central boundary is:

```text
loom.provenance:
  generic facts about code, environment, command, run, stages, and artifacts

weave:
  config composition provenance, recipe expansion provenance, redaction policy

loom.pipeline:
  stage lifecycle, execution events, input/output binding, fingerprint policy

loom.pipeline.stores:
  where provenance files are written and how they are written atomically

project code:
  domain-specific metadata and interpretation
```

### 1.1 Alignment With `loom.md`

This document expands the provenance capture goal from [loom.md](../loom.md):
recording enough generic config, code, environment, command, fingerprint, input,
output, and executor context to make runs reproducible and inspectable. Project
code may add metadata, but `loom.provenance` must not interpret domain-specific
meaning.

---

## 2. Core Position

`loom.provenance` is shared by config, pipeline, run stores, artifacts, and
fingerprints.

Recommended dependency shape:

```text
ids / timestamps / serialization / fingerprints / artifacts
        |
        v
provenance
        |
        v
config / pipeline / stores / cli
```

It may depend on:

```text
platform
socket
subprocess, for explicit git capture
sys
importlib.metadata
os, for selected environment facts
loom.serialization
loom.timestamps
loom.fingerprints
```

It should not depend on:

```text
loom.pipeline.runner
loom.pipeline.executors
loom.pipeline.stores
weave.compose
loom.io.sources
project packages
ML frameworks
heavy package inspection libraries
```

The capture layer should be cheap, explicit, and safe to import in workers.

---

## 3. Package Boundary

### 3.1 `loom.provenance`

Owns generic provenance value objects and capture helpers.

Responsibilities:

```text
RunProvenance
StageProvenance
CodeProvenance
GitProvenance
EnvironmentProvenance
DependencyProvenance
CommandProvenance
ArtifactLineage
provenance capture options
plain-data conversion
provenance validation
```

### 3.2 `weave.provenance`

Owns config-specific provenance.

Responsibilities:

```text
raw config paths
overlay paths
Python API override strings
interpolation provenance
recipe expansion records
target import paths discovered during instantiate
artifact-safe manifest/source/fingerprint records
redacted config view metadata
```

Top-level `loom.provenance` may aggregate config provenance summaries, but it
should not implement config composition or recipe expansion.

V1 `weave` returns config provenance, manifest, source artifact, raw
snapshot availability, and fingerprint records to the caller. It does not write
run provenance, choose run-store paths, persist full resolved configs, or own
CLI display.

### 3.3 `loom.pipeline`

Owns runtime events that become provenance.

Responsibilities:

```text
stage start and finish times
stage status
executor metadata
input artifact binding
output artifact binding
fingerprint records
stage runtime metadata supplied by StageContext
```

Pipeline code should build `StageProvenance` records. Provenance objects should
not run stages.

### 3.4 `loom.pipeline.stores`

Owns persistence of provenance documents.

Responsibilities:

```text
write run-level provenance files
write stage-level provenance files
write atomically
read provenance for CLI/status commands
recover or reject corrupt provenance files
```

Run stores do not decide which facts are semantically important. They persist
the facts supplied by provenance and pipeline code.

### 3.5 `loom.fingerprints`

Owns hashing helpers and digest formats.

Responsibilities:

```text
hash selected provenance facts
validate fingerprint and checksum strings
format digest strings
```

Provenance captures facts. Resume planning decides which facts become
fingerprint inputs.

### 3.6 `loom.artifacts`

Owns artifact references.

Responsibilities:

```text
ArtifactRef
artifact IDs
artifact URIs
artifact checksums
artifact fingerprints
producer stage fields
artifact metadata
```

Provenance can refer to artifact refs and summarize lineage. Artifact refs
should not contain the full provenance document themselves.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
generic provenance value objects
run provenance document shape
stage provenance document shape
code provenance capture from git when available
environment provenance capture from standard library facts
selected package version capture through importlib.metadata
command provenance capture from argv/cwd
artifact input/output lineage summaries
plain-data conversion
schema version fields
clear provenance errors
redaction boundary documentation
```

### 4.2 Should Support Soon

```text
dependency lockfile digest capture
container build target/output facts and executor command metadata
container image/digest capture from environment variables
config provenance aggregation
stage event timeline
provenance diff helpers for CLI
selected environment variable capture
project-supplied provenance providers
input/source inventory records
run comparison summaries
lightweight lifecycle event records
```

Stage 18 records container facts through executor and submitted-operation
metadata rather than by making provenance own container runtime behavior.
Docker, Apptainer/Singularity, and SLURM plus Apptainer paths may provide:

```text
selected image or SIF reference
container build target name and output ref
build result status and redacted command/evidence summary
container runtime command name
redacted exec argv
bind/mount summaries and path-parity facts
clean environment flag and environment variable names only
runtime/device flags such as nv or rocm
scheduler/container resource ownership summary
```

These are factual execution records. They do not make build outputs
authoritative stage artifacts, do not imply image immutability, and do not claim
container isolation is a security boundary for untrusted project code.

### 4.3 Should Not Support in v0

```text
full SBOM generation
automatic import graph scanning
automatic package version capture for every installed package
deep ML framework environment reports
cloud metadata discovery
distributed tracing
cryptographic signatures
attestation formats
database-backed provenance stores
automatic domain metadata interpretation
untrusted-code sandboxing
```

The v0 target is enough structured context to debug and reproduce local
in-process pipeline runs. SLURM, subprocess, and container provenance are
post-v0 executor concerns that should reuse the same generic document shapes.

---

## 5. Terminology

### 5.1 Provenance

Provenance is structured information describing how an output or run was
produced.

In `loom`, provenance can include:

```text
code identity
config identity
environment identity
command identity
stage execution metadata
input and output artifact references
fingerprint records
project-supplied metadata
```

### 5.2 Code Provenance

Facts about source code used for a run.

Examples:

```text
git repository root
git commit
git branch
git dirty flag
untracked file policy
project package version
```

### 5.3 Environment Provenance

Facts about the runtime environment.

Examples:

```text
Python version
platform
machine
processor
hostname
user name, optional
selected environment variables
container identity
```

### 5.4 Dependency Provenance

Facts about installed packages or dependency lockfiles.

Examples:

```text
loom version
selected project package versions
Python package versions
lockfile checksum
requirements file checksum
```

### 5.5 Command Provenance

Facts about how the run was launched.

Examples:

```text
argv
cwd
launcher
run command
process environment summary
```

### 5.6 Stage Provenance

Facts about one stage execution or reuse decision.

Examples:

```text
stage name
stage target
stage status
attempt number
started_at
finished_at
duration_seconds
input artifacts
output artifacts
fingerprint record
executor metadata
stage metadata
```

### 5.7 Run Provenance

Facts about the whole run.

Examples:

```text
run ID
run directory
created_at
command provenance
config provenance summary
code provenance
environment provenance
dependency provenance
stage summaries
artifact index summary
```

### 5.8 Project Metadata

Project metadata is domain-specific information supplied by downstream code.

It must be plain-data compatible, but `loom` should not interpret its meaning.

---

## 6. Guiding Design Principles

### 6.1 Provenance Is Evidence, Not Policy

Provenance records facts.

Other components decide policy:

```text
resume decides reuse
fingerprints decide digest mechanics
config decides redaction and composition
stores decide persistence
project code decides domain semantics
```

### 6.2 Keep Capture Explicit

Automatic capture should be narrow and predictable.

Good:

```text
capture git state for the configured project root
capture Python version from sys.version_info
capture selected package versions by name
capture selected environment variables by allow-list
```

Avoid:

```text
scan the whole filesystem for repos
record every environment variable
record every installed package by default
import heavy frameworks to ask for versions
```

### 6.3 Keep Records Plain-Data Compatible

Provenance documents are persisted as JSON/YAML-compatible data.

All metadata should be:

```text
None
bool
int
float
str
list[plain]
dict[str, plain]
```

Use `loom.serialization` for conversion and validation.

### 6.4 Prefer Stable Identifiers

Use stable strings where possible:

```text
git commit hash
package version
container digest
artifact ID
stage name
fingerprint digest
checksum digest
```

Avoid unstable values unless they are explicitly useful as context:

```text
process ID
hostname
temporary path
wall-clock time
```

Wall-clock time is useful for audit/debugging, but should usually not be a
fingerprint input.

### 6.5 Separate Full and Redacted Views

Some provenance can contain secrets:

```text
command-line overrides
environment variables
config values
URIs with embedded tokens
project metadata
```

Recommended policy:

```text
capture full data only when safe and local
persist public summaries in redacted form
let config redaction own secret path/key policy
```

### 6.6 Preserve Unknown Project Metadata

Project code should be able to attach metadata to:

```text
run provenance
stage provenance
artifact lineage
records and resources
```

`loom` should validate shape but not interpret domain-specific keys.

### 6.7 Do Not Make Provenance Capture Fragile

A missing git command or unavailable package version should not crash every run
by default.

Recommended behavior:

```text
capture unavailable fact as None or status="unavailable"
record error summaries when useful
allow strict mode for users who require complete provenance
```

---

## 7. Public API

### 7.1 Recommended Imports

```python
from loom.provenance import (
    RunProvenance,
    StageProvenance,
    CodeProvenance,
    GitProvenance,
    EnvironmentProvenance,
    DependencyProvenance,
    CommandProvenance,
    ArtifactLineage,
    ProvenanceCaptureOptions,
    capture_run_provenance,
    capture_code_provenance,
    capture_environment_provenance,
    capture_dependency_provenance,
    capture_command_provenance,
)
```

### 7.2 Initial Package Shape

Start with a package because provenance is expected to grow separate model,
capture, git, environment, dependency, and error helpers:

```text
src/loom/provenance/
  __init__.py
  models.py
  capture.py
  git.py
  environment.py
  packages.py
  errors.py
```

Keep imports stable:

```python
from loom.provenance import RunProvenance, StageProvenance
```

---

## 8. Provenance Models

### 8.1 Common Model Policy

Recommended dataclass settings:

```python
@dataclass(frozen=True, slots=True)
```

Each model should support:

```text
to_dict
from_dict, when persisted and read back
validate
schema_version
metadata
```

### 8.2 Timestamp Policy

Use UTC timestamp strings.

Recommended format:

```text
2026-05-02T00:00:00Z
```

Use shared timestamp helpers when implemented.

### 8.3 Metadata Policy

Every broad provenance record may include:

```text
metadata: Mapping[str, PlainData]
```

Metadata is project-owned and optional.

---

## 9. `GitProvenance`

### 9.1 Purpose

`GitProvenance` records source repository identity when available.

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class GitProvenance:
    schema_version: int = 1
    repository_root: str | None = None
    commit: str | None = None
    branch: str | None = None
    is_dirty: bool | None = None
    has_untracked: bool | None = None
    remote_url: str | None = None
    capture_error: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

### 9.2 Capture Policy

Capture should be explicit:

```python
capture_git_provenance(path: str | Path, *, include_remote: bool = False)
```

Recommended commands:

```text
git rev-parse --show-toplevel
git rev-parse HEAD
git rev-parse --abbrev-ref HEAD
git status --porcelain
git config --get remote.origin.url, only if include_remote
```

### 9.3 Missing Git

If git is unavailable or `path` is not in a repository:

```text
return GitProvenance(capture_error="...")
```

or:

```text
return None
```

Choose one policy and keep it consistent. Recommended v0: return a record with
`capture_error` so the absence is visible.

### 9.4 Dirty State

Dirty state should be represented separately from commit.

Fields:

```text
is_dirty:
  tracked files changed

has_untracked:
  untracked files present, if captured
```

Do not include full diffs in v0.

### 9.5 Remote URLs

Remote URLs can contain tokens.

Recommended default:

```text
do not capture remote_url unless explicitly requested
redact credentials when captured
```

---

## 10. `CodeProvenance`

### 10.1 Purpose

`CodeProvenance` groups code identity facts.

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class CodeProvenance:
    schema_version: int = 1
    git: GitProvenance | None = None
    package_name: str | None = None
    package_version: str | None = None
    source_paths: tuple[str, ...] = ()
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

### 10.2 Project Package Version

If a project package name is supplied, capture:

```text
importlib.metadata.version(package_name)
```

Do not import the package just to get its version.

### 10.3 Source Paths

Source paths can help debugging, but they can also make provenance machine-local.

Recommended v0:

```text
record explicit source roots supplied by caller
do not scan sys.path automatically
```

### 10.4 Multiple Repositories

Some projects use multiple repos.

V0 can support:

```text
primary git repo
metadata for additional repos supplied by project code
```

Later support:

```text
git_repositories: list[GitProvenance]
```

---

## 11. `EnvironmentProvenance`

### 11.1 Purpose

`EnvironmentProvenance` records generic runtime environment facts.

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class EnvironmentProvenance:
    schema_version: int = 1
    python_version: str
    python_executable: str | None = None
    platform: str | None = None
    machine: str | None = None
    processor: str | None = None
    hostname: str | None = None
    user: str | None = None
    selected_env: Mapping[str, str] = field(default_factory=dict)
    container: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

### 11.2 Standard Library Facts

Capture from:

```text
sys.version
sys.executable
platform.platform()
platform.machine()
platform.processor()
socket.gethostname()
getpass.getuser(), only if enabled
```

### 11.3 Selected Environment Variables

Do not record all environment variables by default.

Recommended API:

```python
capture_environment_provenance(env_keys=("CUDA_VISIBLE_DEVICES", "SLURM_JOB_ID"))
```

Only record allow-listed keys.

### 11.4 Secret Redaction

Environment variables can contain secrets.

Recommended behavior:

```text
redact values for keys matching token/secret/password/api_key/credential
allow caller to disable or customize only with explicit local/full provenance mode
```

### 11.5 Container Metadata

Stage 17 Docker provenance records executor metadata as factual run evidence,
not as semantic stage identity. Docker facts may include the executor name,
image reference, redacted command projection, selected option summaries,
path-parity summaries, return code, bounded stdout/stderr facts, and timing
facts.

Raw environment values must not be persisted. Container environment metadata
should record variable names and redacted values only. Image references are
recorded as authored facts; digest resolution remains best-effort and must not
pull images or contact registries by default.

Container identity may come from environment variables or explicit runtime
metadata.

Suggested fields:

```text
image
digest
runtime
```

Do not try to detect every container runtime in v0.

---

## 12. `DependencyProvenance`

### 12.1 Purpose

`DependencyProvenance` records package and lockfile identity.

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class DependencyProvenance:
    schema_version: int = 1
    packages: Mapping[str, str] = field(default_factory=dict)
    lockfiles: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

### 12.2 Package Capture

Capture only selected packages by default:

```python
capture_dependency_provenance(packages=["loom", "project-package"])
```

Use:

```text
importlib.metadata.version(name)
```

Do not import packages for version capture.

### 12.3 Missing Packages

Recommended behavior:

```text
record missing package as None? no, packages maps to strings
record missing package in metadata or errors list
```

Possible shape:

```json
{
  "packages": {
    "loom": "0.1.0"
  },
  "missing_packages": ["project-package"]
}
```

### 12.4 Lockfile Digests

Lockfile digests are often more reproducible than long package lists.

Examples:

```text
uv.lock
requirements.txt
poetry.lock
conda-lock.yml
```

Use `loom.fingerprints.hash_bytes` for file contents when caller supplies
lockfile paths.

### 12.5 Full Environment Freeze

Do not run `pip freeze` automatically in v0.

Reasons:

```text
can be slow
can be noisy
may include unrelated packages
can leak local paths
```

Add an explicit option later if needed.

---

## 13. `CommandProvenance`

### 13.1 Purpose

`CommandProvenance` records how the run was launched.

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class CommandProvenance:
    schema_version: int = 1
    argv: tuple[str, ...] = ()
    cwd: str | None = None
    launcher: str | None = None
    command_string: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

### 13.2 Argv

Capture:

```text
sys.argv
```

or explicit argv passed by CLI.

### 13.3 Command String

Command strings are useful for display but can be ambiguous and secret-bearing.

Recommended default:

```text
record argv as structured data
derive command string for display only when safe
```

### 13.4 Working Directory

Record current working directory for debugging.

Do not use cwd as a fingerprint input by default unless path identity affects
outputs.

---

## 14. `ArtifactLineage`

### 14.1 Purpose

`ArtifactLineage` summarizes how artifacts relate to stages.

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class ArtifactLineage:
    schema_version: int = 1
    artifact_id: str
    artifact_type: str | None = None
    uri: str | None = None
    producer_stage: str | None = None
    producer_fingerprint: str | None = None
    checksum: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

### 14.2 Input Artifacts

Stage provenance should record input artifacts as serialized `ArtifactRef`
summaries or `ArtifactLineage` entries.

Include:

```text
logical input name
artifact ID
artifact URI
artifact type
checksum
fingerprint
producer stage
```

### 14.3 Output Artifacts

Stage provenance should record output artifacts after stage completion.

Include:

```text
logical output name
artifact ID
artifact URI
artifact type
checksum
fingerprint
schema version
```

### 14.4 ArtifactRef Boundary

`ArtifactRef` remains the lightweight reference.

Provenance can aggregate:

```text
which stage produced the ref
which inputs were consumed
which executor ran the stage
which fingerprint was active
```

---

## 15. `StageProvenance`

### 15.1 Purpose

`StageProvenance` records facts about a stage attempt, success, failure, or reuse
decision.

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class StageProvenance:
    schema_version: int = 1
    run_uri: str
    stage_name: str
    status: str
    attempt: int
    target: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    fingerprint: Mapping[str, PlainData] | None = None
    input_artifacts: Mapping[str, PlainData] = field(default_factory=dict)
    output_artifacts: Mapping[str, PlainData] = field(default_factory=dict)
    executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    code: CodeProvenance | None = None
    environment: EnvironmentProvenance | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

### 15.2 Status Values

Use the same status vocabulary as pipeline status.

Examples:

```text
PENDING
RUNNING
SUCCEEDED
FAILED
SKIPPED
INTERRUPTED
```

Do not define a separate provenance-only status vocabulary unless necessary.
V0 does not persist a separate reuse stage status. Resume planning may emit a
`REUSE` decision for a valid prior result; the prior `SUCCEEDED` stage state is
retained, while `SKIPPED` remains reserved for selector or condition exclusion.

### 15.3 Attempts

Stage provenance should include the attempt number when available.

If only latest attempt is persisted in v0, the stage provenance file represents
the latest known attempt.

Future:

```text
attempts/<attempt>/provenance.json
stage summary references latest attempt
```

### 15.4 Executor Metadata

Executor metadata is generic plain data.

Examples:

```text
executor name
subprocess pid
return code
SLURM job ID
SLURM array task ID
allocated node list
log paths
container image
```

Do not make `StageProvenance` depend on a specific executor type.

### 15.5 Stage Metadata

Stages may emit metadata through `StageContext`.

Examples:

```text
number of records processed
number of artifacts written
project-specific summary metrics
warnings
```

Keep it plain-data compatible.

---

## 16. `RunProvenance`

### 16.1 Purpose

`RunProvenance` records whole-run facts.

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class RunProvenance:
    schema_version: int = 1
    run_uri: str
    created_at: str
    command: CommandProvenance | None = None
    code: CodeProvenance | None = None
    environment: EnvironmentProvenance | None = None
    dependencies: DependencyProvenance | None = None
    config: Mapping[str, PlainData] = field(default_factory=dict)
    stages: Mapping[str, PlainData] = field(default_factory=dict)
    artifacts: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

### 16.2 Run-Level Versus Stage-Level Facts

Run-level facts should include context shared by the run:

```text
launch command
working directory
primary git state
Python version
selected dependency versions
config provenance summary
```

Stage-level facts should include execution-specific context:

```text
stage status
stage attempt
stage target
stage inputs/outputs
executor metadata
stage fingerprint
```

### 16.3 Shared Versus Per-Stage Environment

In local execution, run-level environment may be enough.

In subprocess, SLURM, or container execution, stage-level environment can differ.

Recommended policy:

```text
record run-level environment at planning/launch time
record stage-level environment when executor supplies distinct metadata
```

### 16.4 Input/Source Inventory

A run may record the external inputs that were discovered or resolved before
execution.

Examples:

```text
source URI or path
discovered file list
checksums or version identifiers when available
resolution time
project-supplied source metadata
```

This inventory is provenance evidence. It should help users detect that mounted
datasets or external resources changed, but it should not force `loom` to
understand domain-specific dataset semantics.

---

## 17. Capture Options

### 17.1 Purpose

Capture options make automatic provenance explicit and testable.

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class ProvenanceCaptureOptions:
    capture_git: bool = True
    git_root: str | None = None
    include_git_remote: bool = False
    capture_environment: bool = True
    env_keys: tuple[str, ...] = ()
    include_user: bool = False
    capture_dependencies: bool = True
    packages: tuple[str, ...] = ("loom",)
    lockfiles: tuple[str, ...] = ()
    strict: bool = False
```

### 17.2 Strict Mode

Strict mode can fail if requested provenance cannot be captured.

Examples:

```text
git repository missing
requested package version missing
requested lockfile missing
```

Default mode should record capture errors and continue.

### 17.3 Defaults

Recommended default capture:

```text
git state for current/project root, best effort
Python/platform facts
loom package version when available
argv/cwd from CLI
no remote URL
no full environment dump
no full package freeze
```

---

## 18. Capture Helpers

### 18.1 `capture_git_provenance`

Representative signature:

```python
def capture_git_provenance(
    path: str | Path,
    *,
    include_remote: bool = False,
    strict: bool = False,
) -> GitProvenance: ...
```

Use subprocess with bounded commands and clear timeouts if needed.

### 18.2 `capture_code_provenance`

Representative signature:

```python
def capture_code_provenance(
    *,
    project_root: str | Path | None = None,
    package_name: str | None = None,
    include_git_remote: bool = False,
    strict: bool = False,
) -> CodeProvenance: ...
```

### 18.3 `capture_environment_provenance`

Representative signature:

```python
def capture_environment_provenance(
    *,
    env_keys: Iterable[str] = (),
    include_user: bool = False,
) -> EnvironmentProvenance: ...
```

### 18.4 `capture_dependency_provenance`

Representative signature:

```python
def capture_dependency_provenance(
    *,
    packages: Iterable[str] = ("loom",),
    lockfiles: Iterable[str | Path] = (),
    strict: bool = False,
) -> DependencyProvenance: ...
```

### 18.5 `capture_command_provenance`

Representative signature:

```python
def capture_command_provenance(
    *,
    argv: Sequence[str] | None = None,
    cwd: str | Path | None = None,
    launcher: str | None = None,
) -> CommandProvenance: ...
```

### 18.6 `capture_run_provenance`

Representative signature:

```python
def capture_run_provenance(
    *,
    run_uri: str,
    options: ProvenanceCaptureOptions | None = None,
    command: CommandProvenance | None = None,
    config: Mapping[str, PlainData] | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> RunProvenance: ...
```

This helper should aggregate other capture helpers. It should not write files.

---

## 19. Persistence Layout

### 19.1 Run Store Layout

The run store owns paths such as:

```text
runs/RUN_ID/
  run.json
  provenance/
    environment.json
    git.json
    dependencies.json
    command.json
  stages/
    STAGE_NAME/
      provenance.json
```

The exact layout can be chosen by `RunStore`, but provenance document shapes
should be stable.

### 19.2 Top-Level `run.json`

The top-level `run.json` contains run metadata, a summary, and links to detailed
provenance files.

Avoid duplicating large provenance payloads in multiple files unless there is a
clear reason.

### 19.3 Stage `provenance.json`

Stage provenance should be written after:

```text
stage starts, with RUNNING status
stage finishes, with SUCCEEDED or FAILED status
stage is selector-skipped, with SKIPPED status
```

If v0 only writes at completion, status files still track live state.
When resume planning emits `REUSE`, v0 should keep the prior `SUCCEEDED` stage
status/provenance and record the reuse as a planning decision rather than a new
persisted status.

### 19.4 Atomic Writes

Provenance writers should ask serialization for plain data/JSON text.

Run stores should own:

```text
temporary file path
fsync policy
rename policy
locking
recovery
```

---

## 20. Document Shapes

### 20.1 Run Provenance Document

Example:

```json
{
  "schema_version": 1,
  "kind": "loom.run_provenance",
  "run_uri": "file:///abs/project/runs/example",
  "created_at": "2026-05-02T00:00:00Z",
  "command": {
    "argv": ["loom", "run", "experiment.yaml"],
    "cwd": "/work/project"
  },
  "code": {
    "git": {
      "commit": "abc123",
      "branch": "main",
      "is_dirty": false
    }
  },
  "environment": {
    "python_version": "3.12.0",
    "platform": "Linux"
  },
  "dependencies": {
    "packages": {
      "loom": "0.1.0"
    }
  },
  "metadata": {}
}
```

### 20.2 Stage Provenance Document

Example:

```json
{
  "schema_version": 1,
  "kind": "loom.stage_provenance",
  "run_uri": "file:///abs/project/runs/example",
  "stage_name": "build_manifest",
  "status": "SUCCEEDED",
  "attempt": 1,
  "target": "project.stages.BuildManifest",
  "started_at": "2026-05-02T00:00:00Z",
  "finished_at": "2026-05-02T00:00:10Z",
  "duration_seconds": 10.0,
  "fingerprint": {
    "fingerprint": "sha256:abc123",
    "policy": "loom.stage.v1"
  },
  "input_artifacts": {},
  "output_artifacts": {},
  "executor_metadata": {},
  "metadata": {}
}
```

### 20.3 Config Provenance Summary

Future run provenance may include a summary owned by the runner/run store:

```json
{
  "config": {
    "manifest": "config/composition_manifest.json",
    "recipe_manifest": "config/recipe_manifest.json",
    "provenance": "run.json metadata.config_provenance",
    "default_resolved_config": null,
    "default_raw_source_snapshots": null,
    "overlays": null,
    "overrides": null
  }
}
```

For current v1 composed configs, `PipelineRunner` persists the composition
manifest, recipe manifest, and artifact-safe config provenance metadata as plain
data. It does not persist `config/resolved.yaml`,
`config/resolved.redacted.yaml`, resolver outputs, or raw source bytes by
default.

V1 `weave` returns artifact-safe records to the caller and does not write
the files above.

`weave` owns detailed contents.

---

## 21. Redaction

### 21.1 Sources of Secrets

Provenance can include secrets through:

```text
argv
environment variables
remote URLs
config paths or values
artifact URIs
project metadata
```

### 21.2 Redaction Ownership

`weave.redaction` owns key/path redaction policy for config values.

`loom.provenance` should provide simple helpers for provenance-specific strings:

```text
redact_url_credentials
redact_env_values_by_key
redact_command_args, if CLI passes policy
```

Avoid building a second full redaction framework.

### 21.3 Full Versus Public Provenance

Recommended persistence:

```text
full provenance:
  local-only, optional, may include sensitive values

redacted provenance:
  default for logs, CLI summaries, bug reports
```

If only one view is persisted in v0, persist redacted-safe fields by default.

For v1 config composition, the default config artifact view is artifact-safe:
it records authored resolver expressions and source metadata/hashes, but not
resolved resolver outputs, raw source bytes, or full resolved config contents.

### 21.4 Fingerprint Payloads

Fingerprint hash payloads may include full semantic values. Provenance summaries
should usually include redacted summaries.

Do not log unredacted fingerprint inputs unless explicitly requested.

---

## 22. Relationship to Fingerprints

### 22.1 Provenance as Input

Some provenance facts can become fingerprint inputs:

```text
git commit
git dirty state
dependency lockfile digest
container image digest
project package version
selected environment variables
```

### 22.2 Provenance as Context

Other provenance facts are context only:

```text
hostname
process ID
run command
working directory
wall-clock timestamps
SLURM job ID
```

They are useful for debugging but usually should not force reruns.

### 22.3 Ownership

Use this division:

```text
provenance captures facts
pipeline planning selects fingerprint inputs
fingerprints hash selected inputs
resume compares fingerprints
```

---

## 23. Relationship to Config

### 23.1 Config Provenance

Config provenance should include:

```text
raw config path
overlay paths
Python API override strings
recipe expansion records
artifact-safe config fingerprint records
manifest and source artifact references
raw source snapshot availability
resolver-expression metadata
target import paths
```

`weave` owns detailed capture because it knows composition order. In v1,
that capture is returned as plain artifact data; persistence and run-level
aggregation belong to callers such as future run stores.

### 23.2 Aggregation

Run provenance can aggregate the resulting config provenance summary.

Recommended:

```text
store detailed config provenance under runs/RUN_ID/config/
store summary links in run provenance
```

This is future run-store guidance. V1 config composition itself is
persistence-free.

### 23.3 Authored Config Trust

Authored configs are trusted project code.

Provenance records which targets and recipes were used, but it does not sandbox
them.

---

## 24. Relationship to Pipeline Execution

### 24.1 Stage Lifecycle

Pipeline execution should update provenance at important lifecycle points:

```text
planned
started
finished
failed
skipped
```

V0 can persist a final stage provenance record and rely on status files for live
state.
V0 records valid reuse as a planner `REUSE` decision, not as a distinct
provenance status.

### 24.2 Executor Metadata

Executors should supply generic metadata:

```text
executor name
command
return code
stdout path
stderr path
SLURM job ID
resource requests
container image
```

Provenance should store this without depending on executor implementations.

### 24.3 StageContext Metadata

`StageContext` can expose a method for project code:

```python
context.record_metadata({"records_processed": 123})
```

Pipeline can merge this into `StageProvenance.metadata`.

### 24.4 Failure Provenance

For failed stages, record:

```text
status FAILED
started_at
finished_at
duration_seconds
executor return code when available
error type/message summary
input artifacts
fingerprint candidate when available
log paths
```

Do not persist full tracebacks in structured provenance if logs already contain
them, unless a short summary is useful.

### 24.5 Lifecycle Event Records

Future execution layers may emit a lightweight event stream for:

```text
run started
stage started
stage succeeded
stage failed
run finished
submission created
```

These events should be generic plain data. Core `loom` may persist them for
inspection, while notification backends such as chat, email, or monitoring
systems should live outside the core package.

### 24.6 Run Comparison Support

Run comparison should use provenance as context, not as domain interpretation.

Useful comparison inputs:

```text
run command and config provenance summaries
environment and dependency summaries
stage provenance and fingerprint summaries
input/source inventory records
artifact lineage summaries
```

Comparison should not require loading domain artifact payloads by default.

---

## 25. Relationship to Artifacts

### 25.1 Output Lineage

Every output artifact should be traceable to:

```text
run ID
stage name
stage attempt
stage fingerprint
artifact ID
artifact checksum
artifact URI
```

### 25.2 Input Lineage

Stage provenance should record input artifacts so downstream debugging can
answer:

```text
which exact upstream output was consumed?
which checksum/fingerprint was visible?
which producer stage produced it?
```

### 25.3 Artifact Index

The artifact index is not a full provenance document.

Recommended split:

```text
artifact index:
  current known artifact refs for lookup

provenance:
  production and consumption context
```

---

## 26. Error Model

### 26.1 Error Types

Recommended hierarchy:

```python
class ProvenanceError(LoomError): ...
class ProvenanceCaptureError(ProvenanceError): ...
class ProvenanceValidationError(ProvenanceError): ...
class ProvenanceRedactionError(ProvenanceError): ...
```

If `LoomError` does not exist yet, start with `Exception` and move under the
shared base later.

### 26.2 Best-Effort Capture

Default capture should not fail a run for missing optional provenance.

Recommended behavior:

```text
record capture_error field
continue
```

Strict mode may raise `ProvenanceCaptureError`.

### 26.3 Validation Errors

Validation errors should include:

```text
document kind
field path
expected type or shape
actual value/type
```

Example:

```text
Invalid StageProvenance at $.input_artifacts.train.
Expected plain-data-compatible artifact summary.
Actual type: ArtifactStore.
```

---

## 27. Examples

### 27.1 Capturing Run Provenance

```python
from loom.provenance import (
    ProvenanceCaptureOptions,
    capture_run_provenance,
)

provenance = capture_run_provenance(
    run_uri="file:///abs/project/runs/example",
    options=ProvenanceCaptureOptions(
        git_root=".",
        packages=("loom", "project-package"),
        env_keys=("CUDA_VISIBLE_DEVICES",),
    ),
)
```

The returned object is plain-data serializable and can be written by `RunStore`.

### 27.2 Stage Provenance

```python
from loom.provenance import StageProvenance

stage_provenance = StageProvenance(
    run_uri="file:///abs/project/runs/example",
    stage_name="build_manifest",
    status="SUCCEEDED",
    attempt=1,
    target="project.stages.BuildManifest",
    input_artifacts={},
    output_artifacts={"manifest": manifest_ref.to_dict()},
    fingerprint=fingerprint_record,
)
```

### 27.3 Project Metadata

```python
context.record_metadata(
    {
        "records_processed": 1000,
        "warnings": [],
    }
)
```

`loom` stores this metadata but does not interpret the keys.

---

## 28. Testing Strategy

### 28.1 Model Tests

Test:

```text
RunProvenance to_dict/from_dict
StageProvenance to_dict/from_dict
GitProvenance unavailable state
EnvironmentProvenance plain-data compatibility
DependencyProvenance selected packages
CommandProvenance argv/cwd
unknown fields rejected by default
metadata must be plain data
```

### 28.2 Capture Tests

Test:

```text
git capture in a temporary repository
git capture outside a repository records capture_error
environment capture records Python version
selected env var capture
secret-like env var redaction
dependency capture for known package
missing dependency behavior
command capture from explicit argv
```

### 28.3 Redaction Tests

Test:

```text
remote URL credentials redacted
token/password/api_key env keys redacted
argv redaction when policy is supplied
metadata redaction does not mutate original input
```

### 28.4 Integration Tests

Test:

```text
run store writes run provenance
run store writes stage provenance
pipeline records input/output artifact refs
failed stage records error summary
same-run-directory reuse records a REUSE planning decision and retains prior
SUCCEEDED stage state
fingerprint input can include selected provenance facts
CLI status can read provenance summary
```

### 28.5 Import Boundary Tests

Test:

```text
import loom.provenance does not import loom.pipeline
import loom.provenance does not import weave
import loom.provenance does not import heavy optional packages
import loom.refs does not import provenance
```

---

## 29. Implementation Plan

### 29.1 Phase 1: Models and Errors

Create:

```text
src/loom/provenance/
  __init__.py
  models.py
  errors.py
```

Implement:

```text
ProvenanceError
GitProvenance
CodeProvenance
EnvironmentProvenance
DependencyProvenance
CommandProvenance
ArtifactLineage
RunProvenance
StageProvenance
```

Add plain-data conversion and validation.

### 29.2 Phase 2: Environment and Command Capture

Implement:

```text
capture_environment_provenance
capture_command_provenance
```

Keep these standard-library-only.

### 29.3 Phase 3: Git Capture

Implement:

```text
capture_git_provenance
capture_code_provenance
```

Use best-effort behavior by default and strict mode when requested.

### 29.4 Phase 4: Dependency Capture

Implement:

```text
capture_dependency_provenance
selected package versions
lockfile checksums
```

Use `importlib.metadata` and `loom.fingerprints.hash_bytes`.

### 29.5 Phase 5: RunStore Integration

Update run stores to write:

```text
run provenance
stage provenance
environment/git/dependency summaries when separate files are useful
```

Run stores own atomic writes.

### 29.6 Phase 6: Pipeline Integration

Update pipeline execution to:

```text
capture run-level provenance at run start
build stage provenance during execution
record executor metadata
record input/output artifact refs
record fingerprint records
record failure summaries
```

### 29.7 Phase 7: Future CLI Integration

When functional CLI behavior exists, expose persisted provenance in:

```text
loom status
loom inspect-run
loom inspect-stage
loom plan --resume --explain
```

The CLI should display persisted provenance, not recalculate it.

---

## 30. Open Questions

### 30.1 Should Provenance Be One Module or a Package?

Recommended v0 answer:

```text
start as src/loom/provenance/
re-export stable public models and helpers from src/loom/provenance/__init__.py
```

Keep public imports stable.

### 30.2 Should Full Package Versions Be Captured?

Recommended v0 answer:

```text
no
```

Capture selected packages and optional lockfile digests. Full environment export
can be an explicit later feature.

### 30.3 Should Git Dirty State Affect Fingerprints?

Recommended answer:

```text
capture it as provenance;
include it in fingerprints only by selected policy
```

Some workflows want dirty state to force reruns. Others need exploratory local
runs without noisy invalidation.

### 30.4 Should Hostname Be Captured?

Recommended answer:

```text
capture as context by default;
do not include in fingerprints by default
```

It helps debugging distributed runs but usually should not affect reuse.

### 30.5 Should Remote URLs Be Captured?

Recommended answer:

```text
not by default
```

They can leak credentials. Capture only when explicitly requested and redacted.

---

## 31. Summary

`loom.provenance` should be a generic, lightweight record of how runs and
artifacts were produced.

Its main jobs are:

```text
define run and stage provenance records
capture code facts
capture environment facts
capture selected dependency facts
capture command facts
summarize artifact lineage
provide plain-data conversion and validation
support redacted, debuggable persisted records
```

It should not become:

```text
a resume planner
a config composer
a run store
a package manager
a cloud metadata crawler
a domain-specific experiment tracker
a heavyweight observability system
```

Keeping provenance factual and generic lets resume policy, fingerprint policy,
artifact storage, config composition, and project-specific metadata each remain
in their own layer.
