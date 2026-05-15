# `loom.artifacts` and `ArtifactStore` Specification

## 1. Purpose

Artifacts are the persistent outputs that connect `loom` pipeline stages.

`loom.artifacts` should define `ArtifactRef`, a serializable handle to a produced
pipeline output. `loom.pipeline.stores.artifact_store` should define the storage
interface used to save, register, load, locate, and validate artifacts.

Artifacts are the main boundary between stages:

```text
upstream stage:
  produces ArtifactRefs

pipeline runner:
  validates and records ArtifactRefs

run store:
  indexes ArtifactRefs and records stage inputs/outputs

downstream stage:
  receives ArtifactRefs as inputs

artifact store:
  loads or verifies the referenced artifact when requested
```

The design should keep artifact metadata generic. `loom` should know that an
artifact has a URI, type label, optional codec, checksum, producer, and metadata.
It should not know what a checkpoint, metrics file, video, report, model, or
dataset-specific object means.

### 1.1 Alignment With `loom.md`

This document specializes the artifact portion of the generic runtime described
in [loom.md](../loom.md). It inherits the package-wide rule that `loom` records and
passes artifact references, while project code owns domain artifact schemas,
payload meaning, and specialized readers or writers. The v0 emphasis should stay
on local, inspectable artifact state that supports provenance and conservative
resume.

---

## 2. Core Position

Use this architecture:

```text
ArtifactRef:
  immutable serializable pointer to a produced output

ArtifactStore:
  persistence and retrieval interface for artifact content

RunStore:
  stage state, stage outputs, and run-level artifact index

Pipeline:
  artifact binding, validation, provenance, and resume decisions

Project code:
  concrete artifact schemas and domain-specific readers/writers
```

This means an `ArtifactRef` should not load data directly. Loading belongs to an
artifact store or a codec.

The initial implementation should support local filesystem artifacts well. Remote
artifact stores, content-addressed storage, and artifact registry services should
be deferred until local behavior is stable.

Stage 15 adds metadata-first external artifact contracts without changing that
boundary. `ArtifactStoreRef`, `ArtifactLocationSummary`,
`ExternalArtifactDeclaration`, `PublishedArtifactRecord`,
`ImmutableArtifactLookupRequest`, and `ImmutableArtifactLookupResult` are strict
plain-data records for external immutable inputs, published immutable outputs,
multi-location summaries, and explicit lookup outcomes. They are adjacent to
`ArtifactRef`; they do not make `ArtifactRef` load bytes, probe credentials, or
own provider-specific schemas.

Use these records when a project needs to preserve facts such as a redacted
object-store URI, a tracking-system run artifact URI, checksum evidence, reuse
keys, or unsupported-materialization context. Payload movement remains a later
materialization concern.

---

## 3. Package Boundary

### 3.1 `loom.artifacts`

Owns artifact value objects.

Responsibilities:

```text
ArtifactRef
artifact serialization helpers
artifact identity helpers
artifact validation helpers that do not require I/O
```

Avoid:

```text
loading artifact bytes
importing pipeline execution
domain-specific artifact subclasses
closed artifact type enums
```

### 3.2 `loom.pipeline.stores.artifact_store`

Owns the artifact store protocol.

Responsibilities:

```text
save Python objects as artifacts through codecs
register already-written artifacts
load artifacts through codecs
check artifact existence
verify checksums when supported
allocate local artifact paths
construct ArtifactRefs
```

### 3.3 `loom.pipeline.stores.local_artifacts`

Owns the local filesystem artifact store.

Responsibilities:

```text
path allocation under run artifact directories
file URI creation
local existence checks
checksum calculation
generic JSON/text/bytes artifact saves
safe local path resolution
```

### 3.4 `loom.pipeline.stores.run_store`

Owns artifact indexing and stage output records.

Responsibilities:

```text
write stages/STAGE/outputs.json
write stages/STAGE/inputs.json
update artifacts.json
read artifact refs for planning and inspection
```

The run store records refs. It does not load artifact payloads.

### 3.5 `loom.io.codecs`

Owns object-to-bytes behavior.

Responsibilities:

```text
resolve codec keys
save supported Python objects
load supported artifacts
provide generic JSON/text/bytes codecs
allow project codecs to be registered
```

Artifacts and codecs are related but separate. `ArtifactRef.codec_key` identifies
how to load or save an artifact when managed loading is requested.

### 3.6 Project Code

Owns domain-specific artifact meaning.

Responsibilities:

```text
checkpoint formats
metrics schemas
dataset-specific manifests
plots and reports
model files
domain codecs
stage-specific validation
```

Project code may attach metadata to artifacts, but `loom` should not interpret it
unless the key is documented as a generic `loom` key.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
ArtifactRef dataclass
plain-data serialization for ArtifactRef
artifact URI, type, codec, checksum, fingerprint, producer, metadata fields
ArtifactStore protocol
LocalArtifactStore
local file URI support
artifact path allocation under run artifacts directory
register already-written local files as artifacts
save/load via generic codecs for JSON, text, and bytes
existence checks
optional checksum calculation on save/register
artifact type validation on load or validation
checksum verification helper
stage output validation against OutputSpec
run-store artifact index compatibility
path-aware artifact errors
```

V0 should support both common artifact production styles:

```text
managed save:
  stage asks ArtifactStore to save an object and receives an ArtifactRef

manual write/register:
  stage writes a file itself, then registers it as an ArtifactRef
```

The second path is important for model checkpoints, reports, external tools, and
large binary outputs that should not pass through a generic object serializer.

### 4.2 Should Not Support in v0

```text
remote artifact stores
content-addressed storage as the only layout
artifact garbage collection
artifact deduplication
artifact migration
database-backed artifact catalogs
automatic schema inference
domain-specific artifact classes
large binary streaming APIs
partial artifact materialization
distributed artifact locking
```

Do not add a heavyweight artifact framework before the local pipeline kernel is
stable.

---

## 5. Terminology

### 5.1 Artifact

A persistent output produced by a pipeline stage.

Examples:

```text
manifest JSON
metrics JSON
model checkpoint
HTML report
plot image
processed dataset shard
plain text summary
```

### 5.2 ArtifactRef

A serializable reference to an artifact.

It should be lightweight enough to store in JSON, pass between stages, include in
fingerprints, and record in provenance.

`ArtifactRef` is run-local in its identity. A cross-run artifact reference is
`ArtifactAddress`.

```python
from loom.artifacts import ArtifactAddress

_ = ArtifactAddress(
    run_uri="file:///abs/project/runs/run-2026-05-04",
    artifact_id="train/metrics",
)
```

### 5.3 Artifact URI

The location of an artifact.

V0 should support `file://` URIs. Other URI schemes can be introduced with remote
artifact stores later.

### 5.4 Artifact ID

A stable identifier for an artifact within a run or artifact store.

Recommended local shape:

```text
STAGE_NAME/OUTPUT_NAME
```

or, when needed:

```text
STAGE_NAME/OUTPUT_NAME/ATTEMPT
```

`artifact_id` is intentionally run-local.
Cross-run ownership is explicit via `ArtifactAddress`:

```text
ArtifactAddress(run_uri, artifact_id)
```

### 5.6 ArtifactAddress

`ArtifactAddress` is a minimal cross-run artifact handle used when artifact
lineage, deduplication, or cataloging spans multiple runs.

```python
@dataclass(frozen=True, slots=True)
class ArtifactAddress:
    run_uri: str
    artifact_id: str
```

Both fields are required and plain-data compatible.

### 5.7 Logical Artifact Name

The graph-level name used by pipeline specs and run indexes.

Example:

```text
train.best_checkpoint
```

Logical artifact names are owned by the pipeline and run store. Artifact IDs are
owned by the artifact store.

### 5.8 Artifact Type

An open string label describing the broad kind of artifact.

Examples:

```text
manifest
metrics.json
checkpoint
report.html
image.png
directory
```

`loom` should not make this a closed enum.

### 5.9 Codec Key

The key used to resolve a codec for managed save/load.

Examples:

```text
json.v1
text.v1
bytes.v1
project.checkpoint.v1
```

Artifacts may omit a codec key when loading is handled entirely by project code.

### 5.10 Checksum

The identity of stored bytes.

Example:

```text
sha256:4f9d...
```

Checksums help detect corruption and support stricter resume validation.

### 5.11 Fingerprint

The identity of the production recipe for an artifact or stage.

Fingerprints are distinct from checksums:

```text
checksum:
  what bytes are stored

fingerprint:
  how the artifact was produced
```

### 5.12 Producer Stage

The stage that produced the artifact.

The producer should be a stage name, not a Python class name. Target information
belongs in stage provenance and fingerprints.

---

## 6. Guiding Design Principles

### 6.1 References, Not Loaded Objects

Stages should pass `ArtifactRef`s across stage boundaries.

Good:

```python
def run(context, inputs):
    checkpoint_ref = inputs["checkpoint"]
    model = context.load_input("checkpoint")
```

Avoid:

```text
upstream stage returns a live model object
downstream stage consumes that object directly
```

Artifact refs make subprocess, SLURM, resume, and provenance practical.

### 6.2 Open Types, Explicit Validation

`artifact_type` should be an open string. Validation should compare declared
types where available.

This gives core enough safety to catch miswired stages without forcing
domain-specific schemas into `loom`.

### 6.3 Managed Save and Manual Registration Both Matter

Not every artifact should flow through a generic serializer.

Support:

```text
save object through codec
register path/URI produced by stage-specific code
```

This keeps `loom` useful for both small structured artifacts and large files
written by external libraries.

### 6.4 Local Files First

The v0 artifact store should be local filesystem backed.

That is enough for:

```text
local development
CI synthetic pipelines
shared-filesystem SLURM runs
debuggable run directories
```

Remote stores should come later and preserve the same `ArtifactRef` contract.

### 6.5 Checksums Are Optional but Structured

V0 should be able to compute checksums for local files when practical, but it
should not require every artifact to have one.

Recommended behavior:

```text
small and regular local files can get checksums on save/register
directories may omit checksums or use a documented tree checksum later
external URIs may omit checksums unless supplied by the stage
```

### 6.6 Artifact Metadata Is Generic

Use `metadata` for project-specific details.

Examples:

```text
split: validation
epoch: 42
metric_name: rmse
format_version: project-v2
```

Core should preserve this metadata but avoid interpreting it.

### 6.7 Artifact Paths Must Be Safe

Local artifact paths allocated by `loom` should stay under the run artifact
directory by default.

Reject:

```text
absolute output paths unless explicitly allowed
parent-directory traversal
unsafe stage names
unsafe output names
```

Stages may intentionally register external artifacts later, but that should be
explicit.

---

## 7. ArtifactRef

### 7.1 Recommended Fields

```python
from dataclasses import dataclass, field
from typing import Any, Mapping

@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    uri: str
    artifact_type: str
    codec_key: str | None = None
    schema_version: int = 1
    checksum: str | None = None
    fingerprint: str | None = None
    producer_stage: str | None = None
    created_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

Suggested meanings:

```text
artifact_id:
  stable store/run-scoped identifier

uri:
  physical or logical location of artifact content

artifact_type:
  open generic type label

codec_key:
  optional codec for managed load/save

schema_version:
  artifact schema version, not ArtifactRef schema version

checksum:
  optional stored-byte identity

fingerprint:
  optional production identity

producer_stage:
  stage name that produced this artifact

created_at:
  creation timestamp

metadata:
  generic project/user metadata
```

### 7.2 Serialization

`ArtifactRef` should serialize to plain structured data:

```python
{
    "artifact_id": "train/best_checkpoint",
    "uri": "file:///runs/example/artifacts/train/best.ckpt",
    "artifact_type": "checkpoint",
    "codec_key": None,
    "schema_version": 1,
    "checksum": "sha256:...",
    "fingerprint": "stage-fingerprint:...",
    "producer_stage": "train",
    "created_at": "2026-05-02T05:30:00Z",
    "metadata": {"epoch": 42},
}
```

The serialized shape must be stable because it appears in:

```text
stages/STAGE/inputs.json
stages/STAGE/outputs.json
artifacts.json
fingerprint input summaries
provenance records
```

### 7.3 Immutability

`ArtifactRef` should be immutable.

If checksum, fingerprint, or metadata changes, create a new ref rather than
mutating an existing one. This keeps fingerprints and provenance easier to
reason about.

### 7.4 What ArtifactRef Should Not Do

Avoid:

```text
load()
save()
delete()
open()
domain-specific methods
implicit filesystem checks during construction
```

Those behaviors belong to stores, codecs, or project code.

---

## 8. Artifact Identity and Naming

### 8.1 Logical Names

The pipeline graph refers to artifacts as:

```text
STAGE_NAME.OUTPUT_NAME
```

The run store records this mapping in `artifacts.json`.

### 8.2 Artifact IDs

Recommended local artifact IDs:

```text
STAGE_NAME/OUTPUT_NAME
```

If multiple attempts need to be preserved later:

```text
STAGE_NAME/OUTPUT_NAME/attempt-0002
```

V0 may overwrite latest attempt outputs or write to stable paths. Attempt history
can be added later if needed.

`artifact_id` stays run-local. Use `ArtifactAddress(run_uri, artifact_id)` for
cross-run artifact identity in external catalogs and result tables.

### 8.3 Output Names

Output names should be:

```text
unique within a stage
safe as path components after validation
stable across reruns
clear in inspection output
```

Avoid dots in output names for v0 because `STAGE.OUTPUT` uses dot syntax.

### 8.4 URI Normalization

V0 should normalize local paths to `file://` URIs.

Recommended behavior:

```text
absolute local path -> file URI
relative allocated path -> resolved under artifact root, then file URI
existing file URI -> normalized if possible
non-file URI -> preserve but remote verification may be unsupported
```

---

## 9. Artifact Types and Schemas

### 9.1 Artifact Type Policy

`artifact_type` is a generic label, not a schema registry.

Good examples:

```text
manifest
metrics.json
checkpoint
report.html
image.png
directory
```

Avoid core-specific closed enums such as:

```text
MODEL_CHECKPOINT
TRAINING_METRICS
REMOTE_PHYS_VIDEO
```

### 9.2 Schema Version

`schema_version` identifies the schema version of the artifact content.

It should be interpreted by whichever code understands `artifact_type` and
`codec_key`.

Core validation can check that expected and actual schema versions match when an
`OutputSpec` declares one.

### 9.3 Type Validation

When an `OutputSpec` declares an expected artifact type:

```text
returned ArtifactRef.artifact_type must match
```

When loading through StageContext:

```python
context.load_artifact(ref, expected_type="metrics.json")
```

should fail clearly if `ref.artifact_type` differs.

### 9.4 Schema Validation

Core should not validate arbitrary domain schemas in v0.

Future extension points:

```text
artifact validators registered by artifact_type
codec-level schema validation
project-owned validation hooks
```

Do not add this before simple artifact type and checksum validation are stable.

---

## 10. Codecs and Loading

### 10.1 Codec Role

Codecs bridge Python objects and stored bytes/text.

`ArtifactStore` may use a codec to:

```text
save object -> file/URI -> ArtifactRef
load ArtifactRef -> object
```

### 10.2 Generic v0 Codecs

V0 should support:

```text
json.v1:
  plain structured data

text.v1:
  UTF-8 text

bytes.v1:
  raw bytes
```

Project packages can register additional codecs.

### 10.3 Missing Codec Key

An artifact may omit `codec_key`.

This means:

```text
ArtifactStore can verify existence/checksum when supported
ArtifactStore cannot generically load the artifact unless a codec is provided explicitly
project code may load it using its own logic
```

This is common for model checkpoints and external tool outputs.

### 10.4 Codec Errors

Loading should fail clearly when:

```text
codec_key is missing and no explicit codec is supplied
codec_key is unknown
artifact type does not match expected type
artifact URI scheme is unsupported
codec fails to parse content
```

---

## 11. ArtifactStore Protocol

### 11.1 Recommended Interface

```python
from typing import Any, Mapping, Protocol

class ArtifactStore(Protocol):
    def save(
        self,
        obj: Any,
        *,
        stage_name: str,
        name: str,
        artifact_type: str,
        codec_key: str,
        schema_version: int = 1,
        metadata: Mapping[str, Any] | None = None,
        fingerprint: str | None = None,
    ) -> ArtifactRef: ...

    def register(
        self,
        uri: str,
        *,
        stage_name: str,
        name: str,
        artifact_type: str,
        codec_key: str | None = None,
        schema_version: int = 1,
        metadata: Mapping[str, Any] | None = None,
        fingerprint: str | None = None,
        checksum: str | None = None,
        allow_external: bool = False,
    ) -> ArtifactRef: ...

    def load(
        self,
        ref: ArtifactRef,
        *,
        expected_type: str | None = None,
        codec_key: str | None = None,
    ) -> Any: ...

    def exists(self, ref: ArtifactRef) -> bool: ...
    def verify_checksum(self, ref: ArtifactRef) -> bool: ...
```

`register()` accepts URI strings at the generic protocol level. `LocalArtifactStore`
may accept local paths as a convenience, but the protocol remains URI-based.

`ArtifactStore` is deliberately run-scoped: all `save()` and `register()`
operations are invoked by an already-run-bound store instance.

This can be narrowed during implementation. The important distinction is between
`save()` for managed serialization and `register()` for files produced directly
by stage code.

### 11.2 Save

`save()` should:

```text
resolve codec
allocate artifact path
write object through codec
compute checksum when possible
return ArtifactRef
```

Use cases:

```text
metrics JSON
manifest JSON
small text report
small binary payload
```

### 11.3 Register

`register()` should:

```text
validate URI/path
compute checksum when possible and not supplied
construct ArtifactRef
not rewrite artifact content
```

Use cases:

```text
model checkpoint written by training library
directory produced by external tool
HTML report written by project code
large file copied into artifact directory
external immutable artifact URI
```

### 11.4 Load

`load()` should:

```text
validate expected artifact type
resolve codec key
check existence when supported
verify checksum when present and locally readable
return decoded object
```

Loading should not update run state. The run store owns state updates.

### 11.5 Existence and Checksum

`exists()` should answer whether the artifact target can be found.

For v0:

```text
file URI:
  check local path

directory artifact:
  check directory existence

remote URI:
  return False or raise unsupported unless a remote store handles it
```

`verify_checksum()` should return `True` only when the checksum exists and can be
verified.

---

## 12. LocalArtifactStore

### 12.1 Root Layout

The local artifact store should write under the run directory:

```text
runs/RUN_ID/
  artifacts/
    STAGE_NAME/
      OUTPUT_NAME
      OUTPUT_NAME.json
      OUTPUT_NAME.txt
      OUTPUT_NAME.bin
      ...
```

The run store owns the run directory. The artifact store may receive either:

```text
run artifact root path
run store path helper
```

Avoid duplicating run layout logic where possible.

### 12.2 Path Allocation

Post-v0 path-template behavior:

```text
if OutputSpec.path is provided, use it under artifacts/STAGE_NAME/
otherwise derive a filename from output name and codec/artifact type
ensure parent directories exist
reject paths outside stage artifact directory by default
```

V0 does not include `OutputSpec.path`. Physical artifact paths are allocated by
`LocalArtifactStore`, or stages may write files under the stage artifact
directory and register them explicitly. Authored output `path` fields should
fail validation clearly until path templates are added.

Examples:

```text
metrics + json.v1 -> artifacts/evaluate/metrics.json
summary + text.v1 -> artifacts/report/summary.txt
checkpoint + manual path best.ckpt -> artifacts/train/best.ckpt
```

### 12.3 Directories as Artifacts

Some stages produce directories.

V0 policy:

```text
allow artifact_type="directory"
exists() checks directory existence
checksum may be omitted
load() requires a project codec or returns path-like data only if explicitly designed
```

Tree checksums can be added later.

### 12.4 External Paths

By default, local artifact registration should require artifacts to live under
the run artifact directory.

Allowing external artifact paths should be explicit:

```text
allow_external=True
```

Reason:

```text
external paths can break reproducibility if moved or deleted
```

### 12.5 File URI Handling

Local refs should use `file://` URIs rather than raw paths.

This keeps the ref shape compatible with future remote stores.

---

## 13. Stage Integration

### 13.1 Managed Save Example

```python
class EvaluateStage:
    def run(self, context, inputs):
        metrics = {"accuracy": 0.91}
        ref = context.save_artifact(
            metrics,
            stage_name=context.stage_name,
            name="metrics",
            artifact_type="metrics.json",
            codec_key="json.v1",
        )
        return {"metrics": ref}
```

### 13.2 Manual Register Example

```python
class TrainStage:
    def run(self, context, inputs):
        checkpoint_path = context.local_output_path("best.ckpt")
        train_model(output_path=checkpoint_path)
        ref = context.register_local_artifact(
            "best_checkpoint",
            checkpoint_path,
            stage_name=context.stage_name,
            artifact_type="checkpoint",
        )
        return {"best_checkpoint": ref}
```

### 13.3 Runner Responsibilities

After a stage returns outputs, the runner should:

```text
validate result is a mapping
validate required outputs are present
validate each value is an ArtifactRef
validate artifact_type matches OutputSpec
validate codec_key matches OutputSpec when declared
validate existence when supported
write outputs.json through RunStore
update artifacts.json through RunStore
include refs in provenance and downstream fingerprints
```

The runner should not load artifact contents as part of normal output
validation.

---

## 14. Validation

### 14.1 ArtifactRef Validation

Validate:

```text
artifact_id is not empty
uri is not empty and parseable
artifact_type is not empty
schema_version is positive
checksum format is recognized when present
producer_stage matches current stage when validating outputs
metadata is plain-data-compatible
```

### 14.2 Stage Output Validation

For each declared output:

```text
returned ref exists
ref.artifact_type matches declared artifact_type
ref.codec_key matches declared codec_key when declared
ref.schema_version matches declared schema_version when declared
artifact exists when local/checkable
checksum verifies when present and locally readable
```

### 14.3 Input Binding Validation

For each downstream input:

```text
logical artifact name exists in artifact index
upstream stage status is reusable under planner policy
ArtifactRef type matches any declared input expectation, if input specs are added later
artifact exists when local/checkable
```

Input type specs can be added later. V0 can validate output declarations and
artifact existence.

### 14.4 Metadata Validation

Metadata should be plain-data-compatible:

```text
null
bool
int
float
string
list
mapping with string keys
```

Do not allow arbitrary Python objects in persisted artifact metadata.

---

## 15. Checksums and Integrity

### 15.1 Checksum Format

Recommended format:

```text
sha256:HEX_DIGEST
```

Keep the algorithm prefix so future algorithms can coexist.

### 15.2 When to Compute

Recommended v0 behavior:

```text
compute sha256 for regular local files saved by ArtifactStore
compute sha256 for regular local files registered by path
omit checksum for directories unless supplied
preserve supplied checksum for external URIs
```

### 15.3 Validation

V0 checksum validation verifies local readable artifacts by default whenever a
checksum is present.

```text
normal mode:
  require existence for local artifacts
  verify checksum when present and the store can read the URI
```

Future strict modes are useful for extra policies such as:

```text
remote checksum verification
directory checksum policies
archival validation
run inspection
debugging suspected corruption
```

---

## 16. Provenance and Lineage

Artifact refs should participate in provenance but not contain all provenance
themselves.

`ArtifactRef` should include:

```text
producer_stage
fingerprint
created_at
metadata
```

Stage provenance should include:

```text
stage target
stage config
input artifact refs
output artifact refs
environment/code provenance
executor metadata
```

Run provenance should include the artifact index and stage provenance summaries.

This keeps `ArtifactRef` lightweight while preserving lineage elsewhere.

### 16.1 Retention Metadata

Future artifact stores may support retention intent as metadata.

Examples:

```text
keep:
  final outputs, reports, metrics, and review artifacts

temporary:
  scratch outputs and intermediates that can be regenerated

archive:
  selected artifacts intended for export or long-term review
```

Retention metadata should not delete files by itself. Cleanup commands should be
explicit, conservative, and inspect the run store before removing artifacts.

---

## 17. Remote Stores

Remote artifact stores are out of scope for v0.

Future store examples:

```text
S3ArtifactStore
GCSArtifactStore
HTTPArtifactStore
MLflowArtifactStore
```

Requirements before adding remote stores:

```text
local ArtifactStore protocol is stable
ArtifactRef URI semantics are stable
checksum policy is clear
credential redaction policy is clear
run-store artifact indexes do not assume local paths
```

Remote stores should not require changing the `ArtifactRef` shape.

---

## 18. Public API

Recommended API:

```python
from loom.artifacts import ArtifactRef

from loom.pipeline.stores import ArtifactStore, LocalArtifactStore
```

Example:

```python
store = LocalArtifactStore(root=run_path / "artifacts")

ref = store.save(
    {"loss": 0.1},
    stage_name="evaluate",
    name="metrics",
    artifact_type="metrics.json",
    codec_key="json.v1",
)

metrics = store.load(ref, expected_type="metrics.json")
```

The high-level user path should normally be through `StageContext`:

```python
context.save_artifact(...)
context.register_local_artifact(...)
```

---

## 19. CLI Integration

The artifact layer should support CLI inspection without owning CLI formatting.

### 19.1 `loom artifacts list RUN_URI`

Should read the run-store artifact index and show:

```text
logical name
artifact type
URI
checksum presence
producer stage
```

### 19.2 `loom artifacts show RUN_URI NAME`

Should show the serialized `ArtifactRef` for a logical artifact name.

### 19.3 `loom artifacts path RUN_URI NAME`

Should print a local path only when:

```text
URI is file://
path can be resolved safely
```

For remote URIs, print the URI instead or fail with a clear message depending on
the command contract.

### 19.4 `loom artifacts verify RUN_URI`

Can be added later to:

```text
check artifact existence
verify checksums
compare outputs.json with artifacts.json
report missing local files
```

---

## 20. Error Model

Recommended hierarchy:

```python
class ArtifactError(LoomError): ...
class ArtifactValidationError(ArtifactError): ...
class ArtifactNotFoundError(ArtifactError): ...
class ArtifactTypeError(ArtifactError): ...
class ArtifactChecksumError(ArtifactError): ...
class ArtifactCodecError(ArtifactError): ...
class UnsupportedArtifactURIError(ArtifactError): ...
class UnsafeArtifactPathError(ArtifactError): ...
```

### 20.1 Type Error Example

```text
Artifact type mismatch.

Artifact:
  evaluate.metrics

Expected:
  metrics.json

Received:
  checkpoint
```

### 20.2 Missing Artifact Example

```text
Artifact does not exist.

Artifact:
  train.best_checkpoint

URI:
  file:///runs/example/artifacts/train/best.ckpt
```

### 20.3 Codec Error Example

```text
Cannot load artifact.

Artifact:
  evaluate.metrics

Codec:
  project.metrics.v2

Reason:
  codec is not registered
```

### 20.4 Unsafe Path Example

```text
Unsafe artifact path.

Stage:
  train

Output:
  best_checkpoint

Path:
  ../../best.ckpt

Reason:
  artifact paths must stay under the stage artifact directory
```

---

## 21. Testing Strategy

### 21.1 ArtifactRef Tests

Test:

```text
construction
plain-data serialization
roundtrip deserialization
metadata validation
checksum format validation
immutability
```

### 21.2 LocalArtifactStore Tests

Test:

```text
path allocation
managed JSON save/load
managed text save/load
managed bytes save/load
manual file registration
directory registration
file URI creation
existence checks
checksum calculation
checksum verification
unsafe path rejection
external path policy
```

### 21.3 Codec Integration Tests

Test:

```text
unknown codec errors
missing codec key errors
explicit codec override
codec load failure paths
project codec registration with a dummy codec
```

### 21.4 Pipeline Integration Tests

Use dummy stages:

```text
stage saves JSON artifact
stage registers manual file artifact
stage returns wrong artifact type
stage returns missing local file
downstream stage loads upstream artifact
```

Test:

```text
outputs.json contains ArtifactRefs
artifacts.json contains logical names
resume sees artifact refs
strict validation catches checksum mismatch
```

### 21.5 CLI-Oriented Tests

Test API helpers that will back:

```text
artifacts list
artifacts show
artifacts path
artifacts verify, later
```

---

## 22. Initial Implementation Plan

Build in this order:

1. Define `ArtifactRef`.
2. Add plain-data serialization/deserialization helpers for `ArtifactRef`.
3. Add artifact validation helpers.
4. Define `ArtifactStore` protocol.
5. Implement local file URI/path helpers.
6. Implement checksum helpers for regular local files.
7. Implement `LocalArtifactStore.register()`.
8. Implement generic JSON/text/bytes codec integration.
9. Implement `LocalArtifactStore.save()` and `load()`.
10. Implement existence and checksum verification.
11. Connect stage output validation to `ArtifactRef` and `OutputSpec`.
12. Connect runner success path to run-store `outputs.json` and `artifacts.json`.
13. Add artifact inspection API helpers.
14. Add CLI wrappers later.

Each step should include focused tests before pipeline execution depends on it.

---

## 23. Summary

Artifacts should be the explicit, serializable boundary between `loom` stages.

The artifact layer should support:

```text
ArtifactRef value objects
open artifact type labels
optional codec keys
local filesystem artifact storage
managed save through codecs
manual artifact registration
existence checks
checksum calculation and verification
stage output validation
run-store artifact indexing
CLI inspection support
path-aware errors
```

It should avoid:

```text
domain-specific artifact classes
loading directly from ArtifactRef
closed artifact type enums
remote stores in v0
opaque artifact catalogs before local stores are stable
forcing all artifacts through generic serialization
```

This keeps artifact passing explicit and reproducible while leaving concrete
artifact semantics in project code.
