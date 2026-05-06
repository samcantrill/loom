# `loom` Core Model Specification

## 1. Purpose

The `loom` core model defines the small set of domain-neutral objects that other
subsystems share.

It provides the public vocabulary for:

```text
resource references
records
manifests
manifest views
record filters
identifier aliases
timestamps
fingerprint and checksum terminology
small structural protocols
shared validation expectations
```

These concepts sit below config, pipeline, stores, execution, and provenance.
They should be stable, serializable, lightweight, and free of application
semantics.

The core model should answer:

```text
How does loom refer to data without loading it?
How does loom represent a generic indexed unit of data?
How does loom pass collections of records between stages?
Which identifiers and timestamp formats are shared across subsystems?
Which vocabulary is safe for downstream packages to rely on?
```

### 1.1 Alignment With `loom.md`

This document expands the foundational public vocabulary named in
[loom.md](../loom.md): resource references, records, manifests, artifact references,
fingerprints, timestamps, protocols, and shared errors. The same package-wide
boundary applies here most strongly: these types must stay lightweight,
domain-neutral, serializable, and safe to import from any subsystem or downstream
package.

---

## 2. Core Position

The core model is the lowest-level user-facing vocabulary in `loom`.

Recommended dependency shape:

```text
ids / refs / records / timestamps / fingerprints / protocols / errors
  depend on standard library only

serialization
  knows how to convert core objects to and from plain data

io / config / pipeline / stores / provenance
  use core objects
```

The core model should not import:

```text
loom.config
loom.pipeline
loom.io.sources
loom.io.codecs
loom.pipeline.stores
project code
domain packages
large optional dependencies
```

This keeps the primitive layer easy to test and safe to import in any execution
context, including subprocess and SLURM workers.

---

## 3. Package Boundary

### 3.1 `loom.ids`

Owns semantic aliases for common string identifiers.

Responsibilities:

```text
RecordID
ResourceKey
CodecKey
ArtifactID
ArtifactType
RunURI
StageID
Fingerprint
Checksum
```

These should start as aliases, not wrapper classes.

### 3.2 `loom.refs`

Owns `ResourceRef`.

Responsibilities:

```text
point to source or external resources
carry generic resource metadata
serialize to plain data
validate required fields
remain immutable
```

It should not load resources.

### 3.3 `loom.records`

Owns records, manifests, manifest views, and simple filters.

Responsibilities:

```text
Record
Manifest protocol
InMemoryManifest
ManifestView
RecordFilter protocol
generic filters such as HasResource and MetadataEquals
```

It should not know about domain-specific dataset structure.

### 3.4 `loom.artifacts`

Owns `ArtifactRef`.

`ArtifactRef` is adjacent to the core model and is already specified in
`docs/features/artifacts.md`.

The core model should document the distinction:

```text
ResourceRef:
  points to input or source resources

ArtifactRef:
  points to pipeline outputs
```

The artifact store, not the core model, owns artifact save/load behavior.

### 3.5 `loom.fingerprints`

Owns deterministic hashing helpers and terminology.

Responsibilities:

```text
stable plain-data hashing
hash_text
hash_bytes
hash_mapping
checksum and fingerprint formatting helpers
```

It should not decide stage fingerprint policy. That belongs to resume/planning.

### 3.6 `loom.timestamps`

Owns UTC timestamp helpers.

Responsibilities:

```text
utc_now
utc_timestamp
parse_timestamp
safe_timestamp_for_path
```

It should not implement scheduling or broad timezone logic.

### 3.7 `loom.protocols`

Owns only package-wide structural protocols that are genuinely generic.

Examples:

```text
Validatable
Fingerprintable
PlainSerializable, if needed
```

Subsystem protocols such as `Stage`, `Codec`, `DataSource`, `ArtifactStore`, and
`RunStore` should remain in their subsystem packages.

### 3.8 `loom.errors`

Owns broad shared error roots.

Responsibilities:

```text
LoomError
ValidationError
ContractError
ConfigError
PipelineError
ArtifactError
ResourceError
SerializationError root, if desired
```

Specific errors should live near the subsystem that raises them.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
string identifier aliases
immutable ResourceRef
immutable Record
Manifest protocol
InMemoryManifest
ManifestView
basic record filters
plain-data conversion hooks
required field validation
generic metadata fields
UTC timestamp helpers
deterministic hashing helpers
clear checksum versus fingerprint terminology
stable public imports
standard-library-only primitive imports
```

The initial implementation should be small. The goal is to establish stable
interfaces, not a database-backed dataset system.

### 4.2 Should Not Support in v0

```text
domain-specific reference classes
dataset-specific metadata schemas
database-backed manifests
remote manifest services
Parquet as a required dependency
Pandas as a required dependency
automatic media loading
automatic resource validation by opening files
complex query languages
schema inference for arbitrary metadata
mutable record updates
strong ID wrapper classes
global registries for record types
```

Downstream packages can build richer domain adapters on top of these primitives.

---

## 5. Terminology

### 5.1 Identifier

A stable string that names an entity within a scope.

Examples:

```text
record_id
resource key
artifact_id
run_uri
stage_id
```

Identifiers should be human-readable where possible, but code should not assume
they carry domain meaning.

### 5.2 Resource

An input or source object outside the pipeline output boundary.

Examples:

```text
local JSONL file
remote object URI
image directory
manifest file
database export
```

`loom` represents resources with `ResourceRef`.

### 5.3 ResourceRef

A serializable pointer to a resource.

It answers:

```text
where is the resource?
what broad type label describes it?
which codec key can load it, if known?
which schema version does it use?
what checksum identifies its bytes, if known?
what generic metadata should travel with it?
```

It does not load the resource.

### 5.4 Record

A generic indexed unit of data.

A record groups:

```text
record_id
resource refs
metadata
annotations
provenance
```

It may represent a sample, item, row, subject, document, clip, sequence, or any
other project-owned concept. `loom` does not define the domain meaning.

### 5.5 Manifest

A collection of records with stable iteration and lookup behavior.

Manifests are useful because stages often pass collections rather than individual
resources.

### 5.6 ManifestView

A filtered or transformed view over another manifest.

The view should preserve lazy behavior where practical and should avoid copying
records unless materialization is explicitly requested.

### 5.7 RecordFilter

A predicate over records.

Generic filters can inspect:

```text
resource keys
metadata values
annotation keys
record IDs
```

Domain-specific filters should live outside `loom`.

### 5.8 Checksum

A hash of stored bytes.

Use checksums to answer:

```text
are these bytes the same as before?
did this artifact file change?
is this resource content still intact?
```

Recommended format:

```text
sha256:<hex>
```

### 5.9 Fingerprint

A hash of semantic production inputs.

Use fingerprints to answer:

```text
would rerunning this stage produce the same logical output?
did config, inputs, code identity, or relevant environment change?
```

Fingerprints may include checksums, but they are not the same thing.

### 5.10 Plain Data

JSON/YAML-compatible structured data:

```text
None
bool
int
float
str
list
dict with string keys
```

Core objects should have stable conversion to plain data.

---

## 6. Guiding Design Principles

### 6.1 Keep the Vocabulary Domain-Neutral

The core model should not contain names such as:

```text
Subject
Trial
VideoRef
SignalRef
ModelCheckpoint
DatasetSplit
ExperimentGroup
```

Those can exist in project code.

The generic layer should provide:

```text
Record
ResourceRef
ArtifactRef
metadata
annotations
provenance
```

### 6.2 References Do Not Load Data

`ResourceRef` and `ArtifactRef` should be references, not active loaders.

Avoid methods such as:

```text
load()
open()
save()
delete()
exists()
```

Loading belongs to I/O sources, codecs, artifact stores, or project code.

### 6.3 Metadata Is Open but Must Be Plain

Metadata should allow project-specific keys.

It should still be:

```text
plain-data compatible
deterministically serializable
safe to write into JSON/YAML
small enough for indexes and status files
```

Large binary values, arrays, data frames, and loaded objects should not be placed
in metadata.

### 6.4 Immutability by Default

Core dataclasses should be frozen where practical.

Benefits:

```text
safer hashing and fingerprinting
clear provenance
fewer accidental shared-state bugs
better behavior across execution boundaries
```

To change a record or ref, create a new value.

### 6.5 Stable Serialization Is Part of the Contract

Core objects appear in:

```text
manifest files
stage inputs
stage outputs
artifact indexes
fingerprint summaries
provenance records
status files
```

Their serialized shape must be deliberate and versioned where needed.

### 6.6 Start With In-Memory Manifests

`InMemoryManifest` should be enough for v0.

Filesystem-backed or database-backed manifests can be added later if real usage
requires them.

The protocol should leave room for larger implementations without forcing them
into v0.

### 6.7 Use Protocols for Extension Points

Manifests and filters should be structural where possible.

Downstream packages should not need to subclass a heavy base class just to supply
records.

### 6.8 Keep Imports Cheap

Importing core modules should not:

```text
import optional config libraries
import ML frameworks
touch the filesystem
read environment state
register plugins
start logging configuration
```

Cheap imports matter for CLI responsiveness, tests, and subprocess workers.

### 6.9 Prefer Explicit Conversion Over Magic

Core objects can support:

```text
to_dict
from_dict
```

or equivalent serialization helpers.

Avoid magical reconstruction of arbitrary objects from metadata or resource
types. The `codec_key` tells I/O which codec to use; it does not instantiate
domain objects by itself.

---

## 7. Identifier Aliases

### 7.1 Recommended Aliases

Recommended `loom.ids` contents:

```python
RecordID = str
ResourceKey = str
ResourceType = str
CodecKey = str
ArtifactID = str
ArtifactType = str
RunURI = str
StageID = str
Fingerprint = str
Checksum = str
```

Aliases improve readability without runtime complexity.

Example:

```python
def get_record(record_id: RecordID) -> Record:
    ...
```

### 7.2 Why Not Wrapper Classes Initially

Avoid:

```python
@dataclass(frozen=True)
class RecordID:
    value: str
```

until there is a demonstrated problem that aliases cannot solve.

Wrapper IDs increase friction in:

```text
serialization
config authoring
JSON status files
CLI arguments
downstream code
```

### 7.3 Validation

Aliases do not validate by themselves.

Validation should happen at object boundaries:

```text
ResourceRef validates uri/resource_type/codec_key shape
Record validates record_id and resource keys
Manifest validates duplicate record IDs
Pipeline validates stage IDs
RunStore validates run IDs and path safety
```

### 7.4 Path Safety

Some IDs become path components.

Path safety should be enforced by the subsystem using the ID as a path, usually:

```text
run store
artifact store
pipeline stage validation
```

The core model may provide helper predicates, but should not assume every ID is
a filesystem path segment.

---

## 8. ResourceRef

### 8.1 Recommended Fields

Recommended dataclass:

```python
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ResourceRef:
    uri: str
    resource_type: str
    codec_key: str | None = None
    schema_version: int = 1
    checksum: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

`codec_key` may be optional if the resource is only being tracked or passed
through. If a caller wants `loom` to load it generically, a codec key should be
available.

### 8.2 Field Meanings

```text
uri:
  physical or logical resource location

resource_type:
  open generic type label such as "jsonl", "image-dir", or "manifest"

codec_key:
  optional key used by I/O codec registries

schema_version:
  version of the referenced resource schema

checksum:
  optional byte checksum, usually "sha256:<hex>"

metadata:
  small plain-data mapping with project-owned details
```

### 8.3 URI Policy

`ResourceRef.uri` should be a string.

Examples:

```text
file:///data/project/input.jsonl
s3://bucket/key
https://example.org/data.json
relative/path.json
```

URI parsing and scheme-specific behavior belong to `loom.io`.

The core model should not reject unknown schemes unless the string is empty or
not a string.

### 8.4 Resource Type Policy

`resource_type` is an open label.

Examples:

```text
json
jsonl
csv
manifest
directory
image
text
binary
```

It should not be a closed enum. Domain packages may use labels that make sense
for their project.

### 8.5 Codec Key Policy

`codec_key` identifies how generic I/O should decode or encode the resource.

Examples:

```text
json.v1
jsonl.v1
text.utf8
bytes
project.custom_manifest.v1
```

The core model stores the key but does not resolve it.

### 8.6 Metadata Policy

Metadata is useful for:

```text
split labels
source names
small dimensions
creation hints
project-specific grouping keys
```

Metadata should not contain:

```text
loaded arrays
binary blobs
open file handles
unserializable objects
large tables
```

### 8.7 Serialization

Recommended serialized shape:

```python
{
    "uri": "file:///data/project/input.jsonl",
    "resource_type": "jsonl",
    "codec_key": "jsonl.v1",
    "schema_version": 1,
    "checksum": "sha256:...",
    "metadata": {"split": "train"},
}
```

All keys should be present unless a deliberate compact format is defined.

### 8.8 Validation

Validation should check:

```text
uri is non-empty string
resource_type is non-empty string
codec_key is None or non-empty string
schema_version is positive integer
checksum is None or recognized "algorithm:value" string
metadata is plain-data compatible mapping
```

Validation should not:

```text
open the URI
check file existence by default
resolve codec keys
validate domain-specific metadata
```

### 8.9 Domain Helpers

Downstream packages can provide helpers:

```python
def image_resource(uri: str, *, width: int, height: int) -> ResourceRef:
    return ResourceRef(
        uri=uri,
        resource_type="image",
        codec_key="image.v1",
        metadata={"width": width, "height": height},
    )
```

These helpers should live outside `loom` unless they are genuinely generic.

---

## 9. Record

### 9.1 Recommended Fields

Recommended dataclass:

```python
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Record:
    record_id: str
    resources: Mapping[str, ResourceRef] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    annotations: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
```

### 9.2 Field Meanings

```text
record_id:
  stable identifier within a manifest

resources:
  mapping from resource key to ResourceRef

metadata:
  generic project-owned descriptive values

annotations:
  optional labels or derived values

provenance:
  small plain-data details about where the record came from
```

### 9.3 Resource Keys

Resource keys are manifest-local labels.

Examples:

```text
input
target
metadata
image
mask
features
```

Keys should be strings and should be unique within a record.

`loom` should not require specific keys.

### 9.4 Metadata Versus Annotations

Recommended distinction:

```text
metadata:
  descriptive facts about the record or source

annotations:
  labels, targets, ratings, tags, or derived values used by experiments
```

The distinction is for organization. `loom` should not enforce domain semantics.

### 9.5 Provenance

Record provenance can include:

```text
source manifest
discovery pattern
created_at
conversion tool
small source metadata
```

Detailed run and stage provenance belongs in `loom.provenance`.

### 9.6 Convenience Methods

Recommended methods:

```python
def has_resource(self, key: str) -> bool:
    ...

def get_resource(self, key: str, default: Any = None) -> ResourceRef | Any:
    ...

def require_resource(self, key: str) -> ResourceRef:
    ...
```

`require_resource` should raise a clear validation or lookup error that includes
the record ID and missing resource key.

### 9.7 Serialization

Recommended serialized shape:

```python
{
    "record_id": "sample-001",
    "resources": {
        "input": {
            "uri": "file:///data/sample-001.json",
            "resource_type": "json",
            "codec_key": "json.v1",
            "schema_version": 1,
            "checksum": None,
            "metadata": {},
        }
    },
    "metadata": {"split": "train"},
    "annotations": {},
    "provenance": {},
}
```

The serialized shape should be stable because records may be persisted in
manifest artifacts.

### 9.8 Validation

Validation should check:

```text
record_id is non-empty string
resource keys are non-empty strings
resource values are ResourceRef values or valid serialized refs
metadata is plain-data compatible mapping
annotations is plain-data compatible mapping
provenance is plain-data compatible mapping
```

Validation should not enforce:

```text
required resource names
dataset split vocabulary
subject/session/trial structure
domain annotation schemas
```

### 9.9 Record Identity

Within one manifest, `record_id` should be unique.

Across manifests, the same `record_id` may occur with different meaning unless
the project defines a stronger namespace.

If global identity is needed, projects can include namespace metadata:

```python
metadata={"dataset": "example", "split": "train"}
```

---

## 10. Manifest Protocol

### 10.1 Purpose

A manifest is a collection of records.

It should support:

```text
iteration
length when known
record lookup by ID when supported
plain-data serialization for in-memory manifests
filter/view construction
```

### 10.2 Recommended Protocol

```python
from typing import Iterable, Protocol


class Manifest(Protocol):
    def __iter__(self) -> Iterable[Record]:
        ...

    def __len__(self) -> int:
        ...

    def get(self, record_id: str) -> Record | None:
        ...

    def require(self, record_id: str) -> Record:
        ...
```

If `__len__` is expensive or unavailable for future lazy manifests, a separate
protocol may be introduced later. V0 can keep `InMemoryManifest` simple.

### 10.3 Ordering

Manifest iteration order should be stable.

For `InMemoryManifest`, order should match input order unless explicitly sorted.

Stable order matters for:

```text
reproducible splits
deterministic fingerprints
predictable tests
human inspection
```

### 10.4 Lookup

Lookup by `record_id` should be supported by `InMemoryManifest`.

Duplicate IDs should fail at construction unless an explicit duplicate policy is
introduced later.

### 10.5 Serialization

Small in-memory manifests can serialize as:

```python
{
    "schema_version": 1,
    "records": [
        {...},
        {...},
    ],
    "metadata": {},
}
```

For larger manifests, JSONL can be supported by I/O or artifact codecs.

The core model should define the record shape; the I/O layer should define file
formats and codecs.

### 10.6 Manifest Metadata

Manifest-level metadata can include:

```text
name
description
created_at
source
record_count
project-owned keys
```

It should remain plain-data compatible.

---

## 11. InMemoryManifest

### 11.1 Purpose

`InMemoryManifest` is the v0 concrete manifest implementation.

It should be enough for:

```text
unit tests
small datasets
pipeline examples
manifest artifacts loaded into memory
simple filtering
```

### 11.2 Recommended Fields

```python
@dataclass(frozen=True, slots=True)
class InMemoryManifest:
    records: tuple[Record, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

The constructor may accept any iterable and normalize to a tuple.

### 11.3 Index

An internal record ID index is useful:

```text
record_id -> Record
```

Because the dataclass is frozen, build the index in `__post_init__` with
`object.__setattr__` or compute lazily.

### 11.4 Duplicate IDs

Duplicate IDs should raise a clear error.

Example:

```text
Duplicate record_id "sample-001" in manifest
```

### 11.5 Materialization

`InMemoryManifest` is already materialized.

For a `ManifestView`, a method such as:

```python
view.materialize() -> InMemoryManifest
```

can produce a concrete manifest.

### 11.6 Plain Data

Recommended methods:

```python
def to_dict(self) -> dict[str, Any]:
    ...

@classmethod
def from_dict(cls, data: Mapping[str, Any]) -> "InMemoryManifest":
    ...
```

These methods should use `Record` and `ResourceRef` conversion helpers.

---

## 12. ManifestView

### 12.1 Purpose

`ManifestView` represents a filtered view over a manifest.

It should avoid copying records unless materialized.

### 12.2 Recommended Fields

```python
@dataclass(frozen=True, slots=True)
class ManifestView:
    source: Manifest
    filters: tuple[RecordFilter, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

### 12.3 Iteration

Iteration applies filters in order:

```python
for record in source:
    if all(filter(record) for filter in filters):
        yield record
```

Filters should be deterministic and side-effect free.

### 12.4 Length

`len(view)` may require scanning the source.

V0 can implement it by materializing or counting. If this becomes expensive,
future lazy manifest protocols can separate known and unknown length.

### 12.5 Lookup

`view.get(record_id)` should return the record only if it exists in the source
and passes all filters.

### 12.6 Chaining

Recommended helper:

```python
def filter(self, predicate: RecordFilter) -> "ManifestView":
    ...
```

This should return a new view with the predicate appended.

### 12.7 Serialization

Serializing a view can mean two different things:

```text
view definition:
  source plus filter definitions

materialized view:
  records that pass the filters
```

V0 should prefer materialized serialization unless filter definitions are
explicitly made serializable.

This avoids needing a filter expression language too early.

---

## 13. Record Filters

### 13.1 RecordFilter Protocol

Recommended protocol:

```python
class RecordFilter(Protocol):
    def __call__(self, record: Record) -> bool:
        ...
```

Filters should be pure predicates.

### 13.2 HasResource

```python
@dataclass(frozen=True, slots=True)
class HasResource:
    key: str

    def __call__(self, record: Record) -> bool:
        return record.has_resource(self.key)
```

### 13.3 MetadataEquals

```python
@dataclass(frozen=True, slots=True)
class MetadataEquals:
    key: str
    value: Any

    def __call__(self, record: Record) -> bool:
        return record.metadata.get(self.key) == self.value
```

### 13.4 MetadataIn

```python
@dataclass(frozen=True, slots=True)
class MetadataIn:
    key: str
    values: frozenset[Any]

    def __call__(self, record: Record) -> bool:
        return record.metadata.get(self.key) in self.values
```

### 13.5 MetadataRegex

`MetadataRegex` is useful but can be deferred to P1.

If included, it should convert the metadata value to a string explicitly and
document that behavior.

### 13.6 Filter Serialization

V0 does not need serializable filters.

If needed later, use explicit filter specs:

```python
{
    "type": "metadata_equals",
    "key": "split",
    "value": "train",
}
```

Do not serialize arbitrary Python callables.

### 13.7 Domain Filters

Domain-specific filters belong outside `loom`.

Examples:

```text
SubjectIn
HasFrameRate
SignalDurationAtLeast
LabelBalanceFilter
```

These can be composed with generic manifest views without being part of the core
model.

---

## 14. Checksums and Fingerprints

### 14.1 Checksum Format

Recommended format:

```text
<algorithm>:<hex>
```

Examples:

```text
sha256:abc123...
blake2b:def456...
```

V0 should support `sha256` first.

### 14.2 Fingerprint Format

Fingerprints can use the same general format:

```text
sha256:<hex>
```

or a prefixed policy format:

```text
stage-v1:sha256:<hex>
```

The resume design owns stage fingerprint policy. The core model only provides
stable hashing helpers.

### 14.3 Stable JSON

Hashing structured data requires stable serialization:

```python
json.dumps(data, sort_keys=True, separators=(",", ":"))
```

All values should be converted to plain data before hashing.

### 14.4 Hash Helpers

Recommended helpers:

```python
def hash_bytes(data: bytes, *, algorithm: str = "sha256") -> str:
    ...

def hash_text(text: str, *, algorithm: str = "sha256") -> str:
    ...

def hash_mapping(mapping: Mapping[str, Any], *, algorithm: str = "sha256") -> str:
    ...
```

Return values should include the algorithm prefix.

### 14.5 What Not To Hash

Avoid hashing:

```text
Python object repr values
dict iteration order without sorting
absolute temporary paths unless semantically relevant
timestamps unless semantically relevant
process IDs
memory addresses
```

Stage fingerprint policy should be explicit about every included value.

### 14.6 Checksum Versus Fingerprint

Use this rule:

```text
checksum:
  identity of stored bytes

fingerprint:
  identity of semantic production inputs
```

Example:

```text
A compressed file may have different bytes but equivalent semantic data.
Its checksum changes. A stage fingerprint may or may not change depending on
the policy.
```

---

## 15. Timestamps

### 15.1 Timestamp Policy

Use UTC by default.

Recommended serialized format:

```text
2026-05-02T05:30:00Z
```

Avoid local-time-dependent persisted timestamps.

### 15.2 Helpers

Recommended helpers:

```python
def utc_now() -> datetime:
    ...

def utc_timestamp() -> str:
    ...

def parse_timestamp(value: str) -> datetime:
    ...

def safe_timestamp_for_path(value: datetime | None = None) -> str:
    ...
```

### 15.3 Path-Safe Timestamps

Path-safe timestamps can use:

```text
20260502T053000Z
```

or another stable filename-safe format.

Use these for:

```text
run directory names
submission IDs
snapshot names
temporary diagnostics
```

### 15.4 Clock Injection

Core helpers can use real time.

Higher-level systems such as execution and stores should allow clock injection
in tests where deterministic timestamps matter.

### 15.5 What To Avoid

Avoid:

```text
timezone conversion helpers beyond UTC parsing
business calendar logic
scheduling abstractions
sleep/retry timing helpers
```

Those belong elsewhere if needed.

---

## 16. Plain Data and Serialization Boundary

### 16.1 Core Objects Convert to Plain Data

Core objects should be convertible to:

```text
dict[str, plain]
list[plain]
str/int/bool/None leaves
```

This allows status files, manifests, and artifact indexes to use JSON/YAML.

### 16.2 Serialization Package Owns Generic Conversion

The detailed serialization helpers belong in `loom.serialization`.

The core model can provide explicit methods such as:

```text
ResourceRef.to_dict
ResourceRef.from_dict
Record.to_dict
Record.from_dict
InMemoryManifest.to_dict
InMemoryManifest.from_dict
```

or delegate to serialization helpers.

### 16.3 Schema Versioning

Types with persisted representations should include schema version fields when
the schema is likely to evolve.

For `ResourceRef`:

```text
schema_version means referenced resource schema version
```

If the `ResourceRef` object schema itself needs versioning later, use a separate
field or wrapper document:

```text
ref_schema_version
```

Avoid overloading one version field with two meanings.

### 16.4 Missing and Unknown Fields

Deserialization should be strict enough to catch mistakes.

Recommended v0 policy:

```text
missing required fields:
  error

unknown fields:
  error by default for core object constructors

metadata keys:
  open and project-owned
```

Lenient compatibility can be added later when real migrations exist.

---

## 17. Validation

### 17.1 Validation Level

Core validation should enforce structural correctness.

It should not enforce domain correctness.

Examples of structural checks:

```text
required strings are non-empty
mapping keys are strings
metadata is plain-data compatible
schema versions are positive integers
checksums have valid shape
duplicate record IDs are rejected
```

Examples of domain checks to avoid:

```text
split must be train/val/test
record must have image and label resources
video fps must be positive
subject ID must match a project pattern
```

### 17.2 Construction-Time Validation

For frozen dataclasses, construction-time validation can happen in
`__post_init__`.

Keep validation simple and deterministic.

### 17.3 Explicit Validate Methods

Objects may also expose:

```python
def validate(self) -> None:
    ...
```

This is useful when construction from trusted internal code should be cheap but
external input needs explicit validation.

V0 should choose one clear approach and apply it consistently.

### 17.4 Error Context

Validation errors should include paths.

Examples:

```text
records[3].record_id must be a non-empty string
records["sample-001"].resources["input"].uri must be a non-empty string
metadata["split"] is not plain-data serializable
```

Path-aware messages make config and manifest debugging much easier.

---

## 18. Relationship to Other Design Documents

### 18.1 Config

`loom.config` may construct core objects from authored or resolved config.

The config layer owns:

```text
YAML loading
overlays
CLI overrides
recipe expansion
target instantiation
```

The core model owns the resulting object contracts.

### 18.2 I/O

`loom.io` owns:

```text
URI interpretation
source opening
codec lookup
resource loading
manifest file formats
```

The core model stores `uri` and `codec_key` but does not resolve them.

### 18.3 Artifacts

Artifacts are pipeline outputs and have a dedicated design.

The core distinction is:

```text
ResourceRef:
  source or external input

ArtifactRef:
  produced output from a stage
```

Both should be serializable references.

### 18.4 Pipeline

Pipeline stages can accept and produce manifests and artifact refs.

The pipeline layer owns:

```text
stage specs
stage context
input/output binding
DAG validation
execution planning
```

The core model owns record and manifest vocabulary used inside those artifacts.

### 18.5 Resume

Resume uses fingerprints and artifact refs.

The core model provides:

```text
stable hash helpers
checksum terminology
plain-data requirements
```

The resume planner decides which values go into a stage fingerprint.

### 18.6 Provenance

Core records can carry small provenance mappings.

Detailed provenance capture deserves a separate design for:

```text
code state
environment
run command
stage inputs and outputs
package versions
```

---

## 19. Public API

### 19.1 Recommended Imports

The following should be stable:

```python
from loom.refs import ResourceRef
from loom.records import Record, Manifest, InMemoryManifest, ManifestView
from loom.records import HasResource, MetadataEquals, MetadataIn
from loom.fingerprints import hash_bytes, hash_text, hash_mapping
from loom.timestamps import utc_timestamp, safe_timestamp_for_path
```

### 19.2 Top-Level Package Exports

`loom.__init__` may re-export the most common types:

```python
from loom.refs import ResourceRef
from loom.records import Record, InMemoryManifest
from loom.artifacts import ArtifactRef
```

Keep top-level exports small. Too many exports make the public surface harder to
stabilize.

### 19.3 Stable Imports During Refactors

Whether records are implemented in a single module or a package, preserve:

```python
from loom.records import Record
from loom.records import InMemoryManifest
```

Internal layout can change without breaking downstream packages.

### 19.4 Optional Dependencies

Core model imports should require only the standard library.

Optional dependencies can be used by:

```text
config extras
I/O codecs
remote stores
testing tools
```

but not by `loom.refs`, `loom.records`, `loom.ids`, or `loom.timestamps`.

---

## 20. Error Model

### 20.1 CoreModelError

Optional base error for core model failures.

It should inherit from `LoomError`.

### 20.2 ResourceRefError

Raised for invalid resource refs.

Examples:

```text
empty uri
empty resource_type
invalid checksum shape
metadata is not plain data
```

### 20.3 RecordError

Raised for invalid records.

Examples:

```text
empty record_id
resource key is not a string
missing required resource in require_resource
resource value is not ResourceRef
```

### 20.4 ManifestError

Raised for invalid manifest operations.

Examples:

```text
duplicate record ID
record not found
manifest data has invalid shape
filter failed with invalid record state
```

### 20.5 FingerprintError

Raised when a value cannot be converted into deterministic hash input.

Examples:

```text
non-plain metadata
unsupported hash algorithm
invalid checksum string
```

### 20.6 Error Message Shape

Errors should be concise and path-aware.

Example:

```text
Invalid ResourceRef at records[2].resources["input"]:
uri must be a non-empty string
```

---

## 21. Testing Strategy

### 21.1 ResourceRef Tests

Test:

```text
valid construction
required field validation
metadata plain-data validation
checksum validation
to_dict/from_dict round trip
immutability
unknown serialized fields
```

### 21.2 Record Tests

Test:

```text
valid construction
resource helper methods
missing resource error
metadata/annotation/provenance validation
to_dict/from_dict round trip
immutability
```

### 21.3 Manifest Tests

Test:

```text
stable iteration order
lookup by record ID
duplicate ID rejection
manifest metadata validation
to_dict/from_dict round trip
materialization
```

### 21.4 ManifestView Tests

Test:

```text
filter application
filter chaining
lookup respects filters
length behavior
materialization order
empty views
```

### 21.5 Filter Tests

Test:

```text
HasResource
MetadataEquals
MetadataIn
missing metadata keys
plain-data filter specs if added later
```

### 21.6 Fingerprint Tests

Test:

```text
stable hash for reordered mappings
different hash for changed values
algorithm prefix
unsupported algorithm errors
hash_bytes and hash_text behavior
checksum format validation
```

### 21.7 Timestamp Tests

Test:

```text
UTC suffix
parse round trip
path-safe format
deterministic formatting with injected datetime
no local timezone dependence
```

### 21.8 Import Tests

Test that core imports do not require optional dependencies:

```text
import loom.refs
import loom.records
import loom.fingerprints
import loom.timestamps
```

These tests protect the low-level dependency boundary.

---

## 22. Initial Implementation Plan

### 22.1 Phase 1: Identifier and Timestamp Helpers

Implement:

```text
loom.ids aliases
loom.timestamps helpers
basic timestamp tests
```

Keep this standard-library only.

### 22.2 Phase 2: ResourceRef

Implement:

```text
ResourceRef dataclass
validation
to_dict/from_dict
checksum shape helper
tests
```

### 22.3 Phase 3: Record

Implement:

```text
Record dataclass
resource helper methods
validation
to_dict/from_dict
tests
```

### 22.4 Phase 4: Manifest and InMemoryManifest

Implement:

```text
Manifest protocol
InMemoryManifest
duplicate ID checks
lookup
serialization
tests
```

### 22.5 Phase 5: ManifestView and Filters

Implement:

```text
RecordFilter protocol
HasResource
MetadataEquals
MetadataIn
ManifestView
materialize
tests
```

### 22.6 Phase 6: Fingerprints

Implement:

```text
stable JSON hashing
hash_bytes
hash_text
hash_mapping
fingerprint/checksum helpers
tests
```

### 22.7 Phase 7: Public API Cleanup

Implement:

```text
__all__ exports
stable package imports
error hierarchy roots
import-boundary tests
```

---

## 23. Summary

The core model should remain small, stable, and domain-neutral.

The essential contracts are:

```text
ResourceRef points to source resources without loading them
Record groups generic resources and metadata under a stable ID
Manifest collects records with stable iteration and lookup
ManifestView filters manifests without inventing a query engine
checksums identify bytes
fingerprints identify semantic production inputs
timestamps are UTC and stable
primitive imports stay cheap and standard-library only
```

This layer should give config, pipeline, artifacts, resume, execution, and
provenance a shared vocabulary without turning `loom` into a domain-specific data
model.
