# `loom.serialization` Specification

## 1. Purpose

`loom.serialization` is the boundary between Python objects and plain structured
data.

It exists so the rest of `loom` can persist, fingerprint, validate, and exchange
generic runtime state without each subsystem inventing its own object-to-dict
rules.

The package should answer:

```text
How does a core object become JSON/YAML-safe plain data?
How does persisted plain data become a validated core object again?
How do fingerprints get deterministic bytes from semantic inputs?
How do persisted documents declare and check schema versions?
How are serialization failures reported with useful paths?
```

It should not answer:

```text
Where does a file live?
Which URI scheme should be used?
Which codec loads a domain artifact?
How should a run store atomically write status files?
How should authored configs be composed or interpolated?
```

Those belong to `loom.io`, `loom.pipeline.stores`, and `loom.config`.

---

## 2. Core Position

The recommended dependency shape is:

```text
ids / refs / records / artifacts / provenance / timestamps
        |
        v
serialization
        |
        v
io / config / pipeline / stores / fingerprints / cli
```

`loom.serialization` is foundational, but it is not the lowest-level domain
model. It depends on the public primitive vocabulary, and higher-level
subsystems depend on it when they need deterministic plain data.

It should be possible to import:

```python
from loom.serialization import to_plain_data, stable_json_dumps
```

without importing:

```text
OmegaConf
PyYAML, unless YAML helpers are explicitly imported
pipeline executors
SLURM support
artifact stores
project code
```

This makes serialization safe inside subprocess workers, SLURM stage workers,
unit tests, and low-level model helpers.

---

## 3. Package Boundary

### 3.1 `loom.serialization`

Owns generic conversion and schema helpers.

Responsibilities:

```text
plain-data validation
plain-data normalization
dataclass-to-plain-data conversion
stable JSON encoding
human-readable JSON encoding
optional YAML read/write helpers
schema version extraction and checking
path-aware serialization errors
```

### 3.2 `loom.refs`, `loom.records`, `loom.artifacts`, `loom.provenance`

Own public data types.

Responsibilities:

```text
define stable fields
validate structural invariants
provide explicit to_dict/from_dict methods when useful
remain domain-neutral
```

These modules may either implement their own explicit conversions or delegate to
serialization helpers. They should not grow independent JSON/YAML writers.

### 3.3 `loom.fingerprints`

Owns semantic hashing policy.

Responsibilities:

```text
choose hash algorithms
decide which semantic inputs belong in a fingerprint
turn canonical serialization output into digest strings
```

It may call `stable_json_dumps` or a lower-level canonical byte helper, but it
should not own the generic plain-data conversion rules.

### 3.4 `loom.io`

Owns bytes, URIs, sources, and codecs.

Responsibilities:

```text
resolve and normalize URIs
open local and remote resources
convert stored bytes/text into application objects through codecs
select codecs by key
```

`loom.io` may use serialization helpers inside generic JSON codecs. Serialization
must not import I/O sources, I/O codecs, or URI backends.

### 3.5 `loom.pipeline.stores`

Owns run and artifact persistence layout.

Responsibilities:

```text
choose filenames
write files atomically
manage locks
record run status
record artifact indexes
recover interrupted writes
```

Run stores can use serialization helpers to encode documents, but atomic file
behavior stays in the stores package.

### 3.6 `loom.config`

Owns authored config composition and object construction.

Responsibilities:

```text
load base config files
apply overlays and CLI overrides
resolve interpolation
expand recipes
instantiate `_target_` object graphs
redact secrets
record config provenance
```

Serialization can provide YAML and JSON helpers. It should not implement config
merge policy, override parsing, recipe expansion, or runtime injection.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
plain data type definition
plain data validation
plain data normalization
dataclass conversion to plain data
explicit reconstruction helpers for known dataclasses
canonical JSON dumps for fingerprints
pretty JSON dumps for persisted files
JSON loads with path-aware errors
optional JSON file helpers
schema version extraction
schema version checks
serialization-specific exceptions
```

### 4.2 Should Support Soon

```text
YAML helpers behind optional dependencies
redaction marker preservation
strict unknown-field checking helpers
small compatibility helpers for schema evolution
```

### 4.3 Should Not Support in v0

```text
arbitrary object graph pickling
automatic reconstruction of arbitrary `_target_` classes
global serializers for every project object
domain-specific artifact schemas
run-store locking or atomic write policy
remote I/O
codec registries
full migration framework
schema inference for arbitrary classes
security sandboxing for untrusted payloads
```

The most important constraint:

```text
serialization converts structured data;
it does not execute, load resources, or interpret domain semantics.
```

---

## 5. Terminology

### 5.1 Plain Data

Plain data is the small recursive value set that can be safely represented in
JSON and YAML.

Allowed leaves:

```text
None
bool
int
float
str
```

Allowed containers:

```text
list[plain]
dict[str, plain]
```

Mapping keys must be strings.

### 5.2 Structured Object

A structured object is an ordinary Python object with a known conversion to
plain data.

Examples:

```text
ResourceRef
Record
ArtifactRef
RunProvenance
StageProvenance
dataclass instances with plain-data fields
```

### 5.3 Serialization

Serialization is conversion from a structured object into plain data or a stable
text representation.

In this document:

```text
object -> plain data
plain data -> JSON string
plain data -> YAML string
```

are serialization operations.

### 5.4 Deserialization

Deserialization is conversion from parsed plain data back into a validated
structured object or document.

In this document:

```text
JSON string -> plain data
plain data -> ResourceRef
plain data -> status document
```

are deserialization operations.

### 5.5 Canonical JSON

Canonical JSON is a deterministic JSON representation used for hashing and
fingerprints.

It should be:

```text
sorted by mapping key
minimal whitespace
UTF-8 encodable
stable across platforms
stable across Python process runs
```

Canonical JSON is not optimized for human readability.

### 5.6 Pretty JSON

Pretty JSON is a stable enough representation for persisted human-readable
documents.

It should use:

```text
sorted keys when useful
consistent indentation
trailing newline
clear error behavior
```

Pretty JSON may not be byte-identical to canonical JSON.

### 5.7 Schema Version

A schema version is an integer associated with a persisted representation.

It should answer:

```text
Which version of this document shape is this?
```

It should not be confused with:

```text
resource schema version
artifact payload schema version
project data schema version
```

When ambiguity exists, use explicit field names.

Examples:

```text
document_schema_version
artifact_schema_version
resource_schema_version
```

---

## 6. Guiding Design Principles

### 6.1 Serialization Is Not I/O

The package can turn plain data into JSON text. It should not decide whether that
text belongs in:

```text
run.json
status.json
artifacts.json
fingerprint.json
resolved.yaml
a local file
a remote URI
an artifact store
```

That ownership stays with the caller.

### 6.2 Prefer Explicit Schemas Over Magic

For public `loom` types, use explicit conversion code.

Good:

```python
ResourceRef.from_dict(data)
ArtifactRef.to_dict()
```

Risky:

```python
deserialize_any(data)
```

Automatic conversion is useful for dataclasses with plain-data fields, but
persisted public types should not rely on surprising reconstruction rules.

### 6.3 Keep Plain Data Deterministic

Fingerprinting depends on deterministic representations.

Serialization should normalize:

```text
mapping key order
dataclass field order
path-like values
optional numeric representations where possible
```

Serialization should reject values that cannot be represented deterministically
unless an explicit conversion is supplied.

### 6.4 Preserve Data, Do Not Interpret Domains

Metadata fields are project-owned.

Serialization can validate that metadata is plain-data compatible. It should not
validate domain meanings such as:

```text
split names
dataset IDs
model families
metric names
subject identifiers
```

### 6.5 Errors Must Be Path-Aware

Serialization failures often happen deep inside nested documents.

Errors should include a path such as:

```text
records[3].resources["video"].metadata["fps"]
pipeline.stages[2].outputs["manifest"]
```

This is more useful than:

```text
Object of type PosixPath is not JSON serializable
```

### 6.6 Support Trusted Project Code, Not Untrusted Payloads

`loom` treats authored configs as trusted project code. Serialization should
still avoid unsafe behavior.

Do not use:

```text
pickle
eval
exec
yaml unsafe loaders
```

Deserialization should construct only known `loom` types through explicit code
paths.

### 6.7 Keep Optional Dependencies Optional

JSON support uses the standard library.

YAML support may use an optional dependency through config extras. Importing
plain-data or JSON helpers should not require YAML dependencies.

---

## 7. Plain Data Model

### 7.1 Type Definition

The package should define a public type alias for plain data.

Representative shape:

```python
from __future__ import annotations

from typing import TypeAlias

PlainData: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | list["PlainData"]
    | dict[str, "PlainData"]
)
```

Depending on supported Python versions and type-checker behavior, the actual
implementation may use a less compact alias.

### 7.2 Valid Plain Data

Valid plain data:

```python
{
    "record_id": "sample-001",
    "metadata": {
        "split": "train",
        "fold": 0,
        "weights": [0.1, 0.2, 0.7],
    },
}
```

Invalid plain data:

```python
{
    "path": Path("data/input.jsonl"),
    "created": datetime.now(),
    123: "non-string key",
    "factory": lambda: None,
}
```

### 7.3 Numeric Values

JSON supports numbers, but fingerprints require care.

Recommended v0 policy:

```text
int:
  allowed

float:
  allowed only if finite

NaN:
  rejected

Infinity:
  rejected

Decimal:
  rejected unless explicitly converted by caller
```

Reason:

```text
NaN and Infinity do not have universally safe JSON behavior.
Decimal formatting can change semantics unless policy is explicit.
```

### 7.4 Mapping Keys

Mapping keys must be strings.

Recommended behavior:

```text
dict[str, plain]:
  allowed

Mapping[str, plain]:
  normalized to dict

non-string keys:
  error by default
```

Do not silently convert non-string keys to strings. This can hide bugs such as:

```python
{1: "train", "1": "validation"}
```

### 7.5 Sequences

Recommended behavior:

```text
list:
  allowed

tuple:
  normalized to list

Sequence:
  normalized to list if concrete and safe

set/frozenset:
  rejected by default
```

Sets are rejected because their order is not semantic unless the caller defines a
sorting policy.

### 7.6 Path-Like Values

Recommended v0 policy:

```text
Path objects are not plain data.
```

Callers should convert paths explicitly to strings at schema boundaries.

Reason:

```text
path normalization is context-dependent
absolute vs relative behavior matters
URI conversion belongs to io/uris.py
fingerprints should not silently depend on platform-specific path reprs
```

### 7.7 Datetime Values

Recommended v0 policy:

```text
datetime objects are not plain data.
```

Callers should use timestamp helpers to create stable strings before
serialization.

Reason:

```text
timezone policy must be explicit
timestamp precision must be consistent
naive datetimes are ambiguous
```

### 7.8 Bytes

Bytes are not plain data.

Callers should use:

```text
checksums for persisted bytes identity
URIs for stored byte locations
base64 only in rare explicit schemas
```

Serialization should not hide bytes inside JSON by default.

---

## 8. Public API

### 8.1 Recommended Imports

```python
from loom.serialization import (
    PlainData,
    SerializationError,
    DeserializationError,
    SchemaVersionError,
    PlainDataError,
    ensure_plain_data,
    is_plain_data,
    to_plain_data,
    stable_json_dumps,
    json_dumps_pretty,
    json_loads,
    get_schema_version,
    require_schema_version,
)
```

### 8.2 `serialization/__init__.py`

Recommended exports:

```python
from loom.serialization.plain import (
    PlainData,
    ensure_plain_data,
    is_plain_data,
    to_plain_data,
)
from loom.serialization.json import (
    stable_json_dumps,
    json_dumps_pretty,
    json_loads,
)
from loom.serialization.schema import (
    get_schema_version,
    require_schema_version,
    check_supported_schema,
)
from loom.serialization.errors import (
    SerializationError,
    DeserializationError,
    SchemaVersionError,
    PlainDataError,
)
```

The public surface should stay small. Deep helpers can remain in submodules.

---

## 9. `serialization/plain.py`

### 9.1 Purpose

`plain.py` owns plain-data validation and normalization.

Recommended functions:

```text
is_plain_data
ensure_plain_data
to_plain_data
normalize_mapping
normalize_sequence
format_path
```

### 9.2 `is_plain_data`

Representative signature:

```python
def is_plain_data(value: object) -> bool: ...
```

Behavior:

```text
return True when value is already valid plain data
return False otherwise
do not mutate input
do not raise for ordinary invalid values
```

Use cases:

```text
fast assertions in tests
validation of metadata fields
guarding generic document writers
```

### 9.3 `ensure_plain_data`

Representative signature:

```python
def ensure_plain_data(value: object, *, path: str = "$") -> PlainData: ...
```

Behavior:

```text
return value typed as PlainData when valid
raise PlainDataError when invalid
include path in the error
```

Example error:

```text
Expected plain data at $.records[0].metadata["created_at"], got datetime.
```

### 9.4 `to_plain_data`

Representative signature:

```python
def to_plain_data(value: object, *, path: str = "$") -> PlainData: ...
```

Supported conversions:

```text
plain data:
  returned as normalized plain data

dataclass instance:
  converted field-by-field

object with to_dict():
  converted through to_dict(), then validated

Mapping:
  normalized to dict[str, plain]

tuple:
  normalized to list
```

Rejected by default:

```text
Path
datetime
bytes
set
callable
arbitrary object without explicit conversion
```

### 9.5 Conversion Precedence

Recommended precedence:

```text
1. already-valid plain leaf
2. mapping
3. list/tuple
4. public to_dict method
5. dataclass instance
6. error
```

This order keeps plain containers straightforward and avoids accidentally
calling methods on mapping-like objects before validating their contents.

### 9.6 Path Formatting

Paths should be readable and stable.

Recommended format:

```text
$
$.field
$.items[0]
$.resources["video"]
```

Rules:

```text
identifier-like mapping keys use dot notation
other mapping keys use bracket notation with repr-like quoting
sequence indexes use brackets
```

### 9.7 Mutation Policy

Normalization should return new containers.

It should not mutate input mappings, lists, dataclasses, or metadata fields.

Reason:

```text
callers may reuse objects after serialization
mutation during fingerprinting creates hard-to-debug state changes
```

---

## 10. `serialization/dataclasses.py`

### 10.1 Purpose

`dataclasses.py` contains helpers for dataclass instances used by core `loom`
types.

Recommended functions:

```text
is_dataclass_instance
dataclass_to_dict
dataclass_from_dict
field_names
check_required_fields
check_unknown_fields
```

### 10.2 Dataclass to Dict

Representative signature:

```python
def dataclass_to_dict(value: object, *, path: str = "$") -> dict[str, PlainData]: ...
```

Behavior:

```text
require dataclass instance
read declared fields in dataclass order
skip ClassVar and InitVar fields
convert each field through to_plain_data
return dict[str, plain]
```

### 10.3 Frozen and Slots Dataclasses

Core types should prefer:

```python
@dataclass(frozen=True, slots=True)
```

Serialization helpers should work with frozen and slots dataclasses.

They should not require `__dict__`.

### 10.4 Reconstructing Dataclasses

Generic reconstruction is useful only with explicit targets.

Representative helper:

```python
def dataclass_from_dict(
    cls: type[T],
    data: Mapping[str, object],
    *,
    path: str = "$",
    allow_unknown: bool = False,
) -> T: ...
```

Behavior:

```text
check that data is a mapping
check required fields
reject unknown fields by default
call cls(**kwargs)
wrap constructor failures in DeserializationError
```

### 10.5 Nested Types

Generic dataclass reconstruction should not attempt full runtime type
interpretation for every annotation in v0.

Preferred v0 pattern for public types:

```python
@classmethod
def from_dict(cls, data: Mapping[str, object]) -> Self:
    return cls(
        uri=require_str(data, "uri"),
        resource_type=require_str(data, "resource_type"),
        codec_key=require_str(data, "codec_key"),
        metadata=ensure_plain_mapping(data.get("metadata", {})),
    )
```

This keeps error policy explicit for persisted public schemas.

### 10.6 Field Metadata

Do not create a large custom schema language in dataclass field metadata in v0.

Small metadata markers may be useful later:

```text
redact
omit_if_none
schema_version
```

Add them only when a real call site needs them.

---

## 11. `serialization/json.py`

### 11.1 Purpose

`json.py` owns JSON string conversion for plain data.

Recommended functions:

```text
stable_json_dumps
json_dumps_pretty
json_loads
read_json
write_json
```

The file helpers are convenience helpers only. Atomic writes belong to stores or
execution helpers.

### 11.2 `stable_json_dumps`

Representative signature:

```python
def stable_json_dumps(value: object) -> str: ...
```

Behavior:

```text
convert value to plain data
sort mapping keys
use compact separators
disallow NaN and Infinity
return a string without trailing newline
```

Representative implementation policy:

```python
json.dumps(
    to_plain_data(value),
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
)
```

### 11.3 Canonical Bytes

Fingerprinting may need bytes.

Recommended helper:

```python
def stable_json_bytes(value: object) -> bytes:
    return stable_json_dumps(value).encode("utf-8")
```

The package can expose this helper if callers repeatedly need it.

### 11.4 `json_dumps_pretty`

Representative signature:

```python
def json_dumps_pretty(value: object, *, sort_keys: bool = True) -> str: ...
```

Behavior:

```text
convert value to plain data
indent with two spaces
disallow NaN and Infinity
include trailing newline
```

Use cases:

```text
run.json
plan.json
status.json
artifacts.json
fingerprint.json
human-readable debug exports
```

### 11.5 `json_loads`

Representative signature:

```python
def json_loads(text: str, *, path: str = "<string>") -> PlainData: ...
```

Behavior:

```text
parse JSON
validate parsed value is plain data
raise DeserializationError for invalid JSON
raise PlainDataError for invalid plain data shape
```

Although Python's JSON parser emits plain-compatible values, this validation
still matters for consistent numeric policy and future hooks.

### 11.6 `read_json`

Representative signature:

```python
def read_json(path: str | Path) -> PlainData: ...
```

This helper is acceptable as a convenience for tests and simple code paths.

Boundary rule:

```text
read_json may open a local file path;
it should not know about run-store layout, URI schemes, locks, or recovery.
```

### 11.7 `write_json`

Representative signature:

```python
def write_json(path: str | Path, value: object) -> None: ...
```

Behavior:

```text
write pretty JSON
create parent directories only if explicitly requested
do not claim atomicity
raise SerializationError for encoding failure
raise OSError or wrap I/O errors consistently
```

Run stores should usually use their own atomic writer instead of this helper.

### 11.8 JSON and ASCII

The source code can remain ASCII. JSON output should be UTF-8 and may preserve
non-ASCII data values through `ensure_ascii=False`.

Reason:

```text
project metadata may include non-ASCII strings
forcing escapes hurts readability
UTF-8 is the expected modern text encoding
```

---

## 12. `serialization/yaml.py`

### 12.1 Purpose

`yaml.py` provides optional YAML helpers for human-authored and human-readable
documents.

Recommended functions:

```text
yaml_available
yaml_loads
yaml_dumps
read_yaml
write_yaml
```

### 12.2 Optional Dependency Policy

Importing `loom.serialization` should not require a YAML library.

Recommended behavior:

```text
from loom.serialization import stable_json_dumps:
  succeeds without YAML dependencies

from loom.serialization.yaml import read_yaml:
  succeeds only if optional YAML dependency is installed,
  or raises a clear missing-extra error when called
```

### 12.3 Safe Loading

YAML loading must use a safe loader.

Do not use behavior that constructs arbitrary Python objects from YAML tags.

Rejected:

```text
yaml.load(..., Loader=yaml.Loader)
```

Required:

```text
safe_load-style behavior
```

### 12.4 Relationship to Config

YAML helpers parse and dump YAML. They do not compose configs.

They should not implement:

```text
overlay order
dot-path overrides
interpolation
recipe expansion
target instantiation
secret redaction policy
```

`loom.config` owns those.

### 12.5 YAML Output Policy

Resolved configs may be easier to inspect as YAML.

Recommended behavior:

```text
convert through to_plain_data first
sort keys only where readability is not harmed
preserve mapping order if caller passes an ordered document
include trailing newline
```

Exact formatting can remain implementation-specific in v0.

---

## 13. `serialization/schema.py`

### 13.1 Purpose

`schema.py` contains small helpers for schema-versioned persisted documents.

Recommended functions:

```text
get_schema_version
require_schema_version
check_supported_schema
ensure_mapping
require_field
optional_field
```

The goal is clear failure, not a full schema-validation framework.

### 13.2 Version Field Names

Use explicit names where ambiguity exists.

Recommended field names:

```text
schema_version
document_schema_version
run_schema_version
status_schema_version
artifact_index_schema_version
```

Avoid overloading:

```text
ResourceRef.schema_version
```

if that field means resource payload schema rather than `ResourceRef` object
shape.

### 13.3 `get_schema_version`

Representative signature:

```python
def get_schema_version(
    data: Mapping[str, object],
    *,
    field: str = "schema_version",
    path: str = "$",
) -> int: ...
```

Behavior:

```text
require mapping input
require field to exist
require integer value
require positive value
raise SchemaVersionError with path when invalid
```

### 13.4 `require_schema_version`

Representative signature:

```python
def require_schema_version(
    data: Mapping[str, object],
    expected: int,
    *,
    field: str = "schema_version",
    path: str = "$",
) -> None: ...
```

Behavior:

```text
raise SchemaVersionError if actual != expected
include expected and actual values
```

### 13.5 `check_supported_schema`

Representative signature:

```python
def check_supported_schema(
    data: Mapping[str, object],
    *,
    supported: Container[int],
    field: str = "schema_version",
    path: str = "$",
) -> int: ...
```

Behavior:

```text
return actual version if supported
raise SchemaVersionError otherwise
```

### 13.6 Migrations

Do not build full migration machinery in v0.

Recommended v0 policy:

```text
read exactly supported schema versions
fail clearly for newer unsupported versions
add small one-step compatibility conversions only when needed
```

Future migration support can add:

```text
Migration protocol
MigrationRegistry
document-specific migration chains
CLI inspection commands
```

---

## 14. `serialization/errors.py`

### 14.1 Purpose

Serialization failures should be distinguishable from configuration, I/O, and
pipeline failures.

Recommended hierarchy:

```python
class SerializationError(LoomError): ...
class DeserializationError(SerializationError): ...
class PlainDataError(SerializationError): ...
class SchemaVersionError(DeserializationError): ...
```

If `LoomError` does not exist yet, these can inherit from `Exception` initially
and be adjusted when shared errors are implemented.

### 14.2 Error Fields

Errors should carry:

```text
message
path
expected, when useful
actual, when useful
source, when useful
```

Example:

```text
Invalid plain data at $.metadata.created_at.
Expected one of: None, bool, int, float, str, list, dict[str, plain].
Actual type: datetime.
```

### 14.3 Wrapping Lower-Level Errors

Recommended policy:

```text
JSON parse errors:
  wrap in DeserializationError

schema version errors:
  raise SchemaVersionError

plain-data validation errors:
  raise PlainDataError

OSError from optional file helpers:
  either propagate or wrap with source path;
  choose consistently
```

### 14.4 Do Not Hide Causes

Use exception chaining when wrapping:

```python
raise DeserializationError(...) from exc
```

This preserves useful debugging context while giving callers a stable exception
type.

---

## 15. Core Type Integration

### 15.1 `ResourceRef`

Recommended persisted shape:

```json
{
  "uri": "file:///data/project/input.jsonl",
  "resource_type": "jsonl",
  "codec_key": "jsonl.v1",
  "schema_version": 1,
  "checksum": null,
  "metadata": {
    "split": "train"
  }
}
```

Conversion policy:

```text
uri:
  required string

resource_type:
  required string

codec_key:
  required string

schema_version:
  required or defaulted by ResourceRef constructor

checksum:
  optional string or None

metadata:
  dict[str, plain], default empty
```

### 15.2 `Record`

Recommended persisted shape:

```json
{
  "record_id": "sample-001",
  "resources": {
    "input": {
      "uri": "file:///data/project/sample-001.json",
      "resource_type": "json",
      "codec_key": "json.v1",
      "schema_version": 1,
      "checksum": null,
      "metadata": {}
    }
  },
  "metadata": {
    "split": "train"
  },
  "annotations": {},
  "provenance": {}
}
```

Conversion policy:

```text
resources:
  mapping from resource key to ResourceRef plain data

metadata:
  dict[str, plain]

annotations:
  dict[str, plain]

provenance:
  dict[str, plain]
```

### 15.3 `InMemoryManifest`

Recommended persisted shape:

```json
{
  "schema_version": 1,
  "records": [
    {
      "record_id": "sample-001",
      "resources": {},
      "metadata": {}
    }
  ]
}
```

Conversion policy:

```text
records are serialized in manifest order
duplicate record IDs are rejected during reconstruction
manifest-level metadata can be added later if needed
```

### 15.4 `ArtifactRef`

Recommended persisted shape is specified in `docs/artifacts.md`.

Serialization should support:

```text
artifact_id
uri
artifact_type
codec_key
schema_version
checksum
fingerprint
metadata
```

### 15.5 Provenance Types

Provenance documents should be plain-data compatible.

Recommended policy:

```text
timestamps are serialized as stable strings
environment data is mapping/list/string/number/bool/None
code identity fields are strings
unknown project metadata remains plain data
```

`loom.provenance` owns which fields are recorded. Serialization owns how those
fields become plain data.

---

## 16. Relationship to Fingerprints

### 16.1 Fingerprints Need Canonical Serialization

`loom.fingerprints` should call serialization for deterministic JSON.

Representative flow:

```text
stage semantic input mapping
  -> to_plain_data
  -> stable_json_dumps
  -> UTF-8 bytes
  -> hash digest
```

### 16.2 What Serialization Does Not Decide

Serialization should not decide which values belong in a fingerprint.

That belongs to:

```text
pipeline planning
resume logic
stage specs
artifact stores
fingerprints module
```

Serialization only guarantees that once the caller has selected semantic inputs,
the representation is deterministic.

### 16.3 Canonical JSON Policy

Canonical JSON for hashing should use:

```text
sort_keys=True
separators=(",", ":")
allow_nan=False
ensure_ascii=False
UTF-8 encoding
```

This makes the following equivalent mappings produce the same digest:

```python
{"b": 2, "a": 1}
{"a": 1, "b": 2}
```

### 16.4 Stable Floats

Python's JSON float representation is stable enough for v0 for ordinary finite
floats.

If research use later requires stricter numeric reproducibility, add an explicit
numeric normalization policy rather than silently changing fingerprint behavior.

Possible future policy:

```text
Decimal encoded as string
float rounding by configured precision
arrays hashed through binary checksums rather than JSON
```

---

## 17. Relationship to Run Stores

### 17.1 Store Documents

Run stores need serialized documents such as:

```text
run.json
status.json
plan.json
artifacts.json
stages/<stage>/inputs.json
stages/<stage>/outputs.json
stages/<stage>/fingerprint.json
```

Serialization provides:

```text
plain-data validation
JSON encoding
schema checks
```

Run stores provide:

```text
document paths
write ordering
atomic writes
locks
recovery rules
status transition policy
```

### 17.2 Atomicity Boundary

Do not put run-store atomic write policy in `serialization/json.py`.

Bad:

```text
stable_json_dumps writes a temp file and renames into run directory
```

Good:

```text
RunStore creates temp path
RunStore asks serialization for JSON text
RunStore fsyncs/renames according to its policy
```

### 17.3 Schema Checks at Store Boundaries

When reading persisted store documents:

```text
parse JSON
ensure plain data
ensure mapping
check document schema version
convert to internal objects
```

This sequence keeps corrupted files and incompatible versions from being
silently accepted.

---

## 18. Relationship to Config

### 18.1 Authored Configs

Authored configs are trusted project code and may contain `_target_` import paths
and recipe references.

Serialization should not execute those targets or recipes.

### 18.2 Resolved Config Export

`loom.config` may use serialization to persist:

```text
resolved.full.yaml
resolved.redacted.yaml
config.provenance.json
cli_overrides.yaml
overlays.yaml
```

`loom.config` owns:

```text
what gets redacted
where files are written
which config stages are persisted
```

Serialization owns:

```text
plain-data conversion
JSON/YAML formatting
path-aware encoding errors
```

### 18.3 Redaction Marker Preservation

If config redaction uses marker values such as:

```text
"<redacted>"
```

serialization should preserve those strings like any other plain data.

It should not independently search for:

```text
token
password
secret
api_key
credential
```

Those patterns belong to `loom.config.redaction`.

---

## 19. Relationship to I/O and Codecs

### 19.1 JSON Codec

`loom.io.codecs.json_codec` can use `loom.serialization.json`.

Example:

```text
JsonCodec.encode(obj)
  -> to_plain_data(obj)
  -> json_dumps_pretty(...)
  -> bytes
```

### 19.2 Domain Codecs

Domain packages may define codecs for:

```text
images
videos
arrays
model checkpoints
tables
reports
```

Serialization should not know about these formats.

### 19.3 Resource Loading

`ResourceRef` can be serialized as plain data, but loading the referenced
resource belongs to I/O.

Example boundary:

```text
serialization:
  ResourceRef(uri="file:///data/a.json", codec_key="json.v1") -> dict

io:
  resolve file URI, read bytes, choose json.v1 codec, decode payload
```

---

## 20. Document Shapes

### 20.1 Generic Versioned Document

Recommended wrapper shape for documents that are likely to evolve:

```json
{
  "schema_version": 1,
  "kind": "loom.run_status",
  "data": {}
}
```

Use wrappers when:

```text
the document is persisted independently
future compatibility matters
the document may be inspected by CLI tools
```

### 20.2 Small Inline Objects

For small inline objects, wrappers may be too verbose.

Example:

```json
{
  "uri": "file:///data/input.jsonl",
  "resource_type": "jsonl",
  "codec_key": "jsonl.v1"
}
```

Inline objects can rely on their containing document's schema version when the
object shape is not independently versioned.

### 20.3 Document Kind

`kind` is useful for persisted top-level documents.

Examples:

```text
loom.run
loom.run_status
loom.plan
loom.artifact_index
loom.stage_fingerprint
loom.manifest
```

Recommended policy:

```text
include kind in top-level persisted documents
do not require kind on every nested object
```

### 20.4 Unknown Fields

Recommended default:

```text
known loom documents:
  reject unknown fields by default

metadata fields:
  allow arbitrary string keys with plain-data values

future extension fields:
  place under explicit metadata or extensions mapping
```

This catches misspellings without blocking project metadata.

---

## 21. Validation Helpers

### 21.1 Required Fields

Recommended helper:

```python
def require_field(
    data: Mapping[str, object],
    key: str,
    *,
    expected_type: type[T] | tuple[type[Any], ...] | None = None,
    path: str = "$",
) -> T: ...
```

Behavior:

```text
raise DeserializationError when missing
raise DeserializationError when type is wrong
return value otherwise
```

### 21.2 Optional Fields

Recommended helper:

```python
def optional_field(
    data: Mapping[str, object],
    key: str,
    default: T,
    *,
    expected_type: type[Any] | tuple[type[Any], ...] | None = None,
    path: str = "$",
) -> T: ...
```

### 21.3 Plain Mapping Fields

Recommended helper:

```python
def require_plain_mapping(
    data: Mapping[str, object],
    key: str,
    *,
    path: str = "$",
) -> dict[str, PlainData]: ...
```

Use cases:

```text
metadata
annotations
provenance
extensions
```

### 21.4 Unknown Field Checks

Recommended helper:

```python
def reject_unknown_fields(
    data: Mapping[str, object],
    allowed: Collection[str],
    *,
    path: str = "$",
) -> None: ...
```

Example error:

```text
Unknown field at $.resources["input"]: codec.
Did you mean codec_key?
```

Spelling suggestions are useful but not required in v0.

---

## 22. Examples

### 22.1 Serializing a Resource Reference

```python
from loom.refs import ResourceRef
from loom.serialization import to_plain_data, stable_json_dumps

ref = ResourceRef(
    uri="file:///data/project/input.jsonl",
    resource_type="jsonl",
    codec_key="jsonl.v1",
    metadata={"split": "train"},
)

plain = to_plain_data(ref)
text = stable_json_dumps(plain)
```

Expected plain shape:

```python
{
    "uri": "file:///data/project/input.jsonl",
    "resource_type": "jsonl",
    "codec_key": "jsonl.v1",
    "schema_version": 1,
    "checksum": None,
    "metadata": {"split": "train"},
}
```

### 22.2 Fingerprinting a Stage Input

```python
from loom.fingerprints import hash_text
from loom.serialization import stable_json_dumps

payload = {
    "stage": "build_index",
    "target": "project.stages.BuildIndexStage",
    "config": {"min_count": 3},
    "inputs": {
        "manifest": {
            "artifact_id": "load_data/output_manifest",
            "fingerprint": "sha256:abc123",
        }
    },
}

fingerprint = hash_text(stable_json_dumps(payload))
```

Serialization makes the payload deterministic. Pipeline planning decides what
belongs in the payload.

### 22.3 Reading a Versioned Status Document

```python
from loom.serialization import json_loads, require_schema_version

data = json_loads(status_text, path="status.json")
require_schema_version(data, expected=1, path="status.json")
```

Actual store code should then convert `data` into its own status model.

### 22.4 Rejecting Non-Plain Metadata

```python
from datetime import datetime

metadata = {"created_at": datetime.now()}
to_plain_data(metadata)
```

Expected error:

```text
Invalid plain data at $.created_at.
Actual type: datetime.
```

Callers should convert timestamps explicitly:

```python
metadata = {"created_at": utc_now_iso()}
```

---

## 23. Implementation Notes

### 23.1 Start Small

Implement only the helpers needed by core objects, fingerprints, and store
documents.

Initial files:

```text
src/loom/serialization/__init__.py
src/loom/serialization/plain.py
src/loom/serialization/dataclasses.py
src/loom/serialization/json.py
src/loom/serialization/schema.py
src/loom/serialization/errors.py
```

YAML can be added when config implementation needs it.

### 23.2 Avoid Circular Imports

Serialization may import:

```text
dataclasses
json
math
pathlib, only for optional file helpers
typing
```

Serialization should avoid importing:

```text
loom.config
loom.pipeline
loom.io
loom.pipeline.stores
project packages
```

Core types may import narrow serialization helpers if needed, but avoid cycles:

```text
refs.py -> serialization.plain
serialization.plain -> dataclasses and protocols, not refs.py
```

If cycles appear, prefer explicit `to_dict` methods in core types and keep
serialization generic.

### 23.3 Object With `to_dict`

`to_plain_data` may support objects with a public `to_dict` method.

Recommended constraints:

```text
method must take no required arguments
return value must validate as plain data
method failures should be wrapped with path context
```

Do not support arbitrary methods such as:

```text
serialize
as_json
model_dump
dict
```

unless a concrete need appears. Each extra convention increases ambiguity.

### 23.4 Pydantic Objects

Do not add special Pydantic support in v0.

Reason:

```text
pydantic should remain optional
core serialization should stay dependency-light
project objects can expose to_dict if needed
```

If Pydantic becomes common in `loom.config`, add optional helpers in a separate
module that is imported only when installed.

### 23.5 NumPy and Arrays

Do not add NumPy-specific serialization in v0.

Arrays should usually be artifacts with checksums and codec metadata, not large
JSON values.

Domain codecs can handle arrays through artifact stores.

### 23.6 Ordering

For canonical JSON:

```text
sort mapping keys
preserve sequence order
preserve dataclass field order before key sorting
```

For human-readable JSON:

```text
sort keys by default for stability
allow callers to disable sorting when document order matters
```

---

## 24. Testing Strategy

### 24.1 Plain Data Tests

Test:

```text
valid leaves
valid nested lists and dicts
non-string mapping keys rejected
Path rejected
datetime rejected
bytes rejected
set rejected
NaN rejected
Infinity rejected
path-aware errors
no mutation of input containers
```

### 24.2 Dataclass Tests

Test:

```text
frozen dataclass conversion
slots dataclass conversion
nested dataclass conversion
default values
unknown fields rejected during reconstruction
missing fields reported with paths
constructor errors wrapped
```

### 24.3 JSON Tests

Test:

```text
stable_json_dumps sorts keys
stable_json_dumps uses compact separators
stable_json_dumps rejects NaN
stable_json_dumps is deterministic across repeated calls
json_dumps_pretty includes trailing newline
json_loads wraps invalid JSON
json_loads validates parsed values
```

### 24.4 Schema Tests

Test:

```text
missing schema version
non-integer schema version
zero or negative schema version
unsupported schema version
custom field names
clear path in error message
```

### 24.5 Integration Tests

Test with public types:

```text
ResourceRef round trip
Record round trip
InMemoryManifest round trip
ArtifactRef round trip
status document serialization
fingerprint payload determinism
```

### 24.6 Dependency Tests

Test import boundaries:

```text
import loom.serialization does not import loom.pipeline
import loom.serialization does not import loom.config
import loom.serialization.plain does not require YAML dependencies
```

These can start as lightweight unit tests and later become import-linter rules.

---

## 25. Error Examples

### 25.1 Non-String Key

```text
Invalid mapping key at $.metadata.
Expected str key.
Actual key type: int.
Actual key: 1.
```

### 25.2 Unsupported Object

```text
Cannot convert value to plain data at $.stage.config.model.
Expected plain data, mapping, sequence, dataclass, or object with to_dict().
Actual type: ProjectModel.
```

### 25.3 Unsupported Schema

```text
Unsupported schema version at status.json.
Field: schema_version.
Supported versions: [1].
Actual version: 3.
```

### 25.4 Invalid JSON

```text
Could not parse JSON document status.json.
Line 12, column 4: Expecting property name enclosed in double quotes.
```

---

## 26. Implementation Plan

### 26.1 Phase 1: Error Types

Create:

```text
src/loom/serialization/errors.py
```

Define:

```text
SerializationError
DeserializationError
PlainDataError
SchemaVersionError
```

Keep constructors simple. Add richer fields only if tests need them.

### 26.2 Phase 2: Plain Data

Create:

```text
src/loom/serialization/plain.py
```

Implement:

```text
PlainData type alias
is_plain_data
ensure_plain_data
to_plain_data
path formatting helpers
finite float validation
```

### 26.3 Phase 3: Dataclass Helpers

Create:

```text
src/loom/serialization/dataclasses.py
```

Implement:

```text
is_dataclass_instance
dataclass_to_dict
basic field validation helpers
```

Only add `dataclass_from_dict` when a public type needs it.

### 26.4 Phase 4: JSON Helpers

Create:

```text
src/loom/serialization/json.py
```

Implement:

```text
stable_json_dumps
stable_json_bytes
json_dumps_pretty
json_loads
read_json
write_json
```

Document that file helpers are not atomic.

### 26.5 Phase 5: Schema Helpers

Create:

```text
src/loom/serialization/schema.py
```

Implement:

```text
get_schema_version
require_schema_version
check_supported_schema
required/optional field helpers if needed
```

### 26.6 Phase 6: Public Exports

Create:

```text
src/loom/serialization/__init__.py
```

Export the stable public helpers. Keep advanced helpers private until needed.

### 26.7 Phase 7: Core Integration

Update core types to use serialization consistently:

```text
ResourceRef.to_dict/from_dict
Record.to_dict/from_dict
InMemoryManifest.to_dict/from_dict
ArtifactRef.to_dict/from_dict
provenance document conversion
```

### 26.8 Phase 8: Fingerprint Integration

Update `loom.fingerprints` so canonical serialization is centralized.

Target behavior:

```text
hash_mapping(mapping) uses stable_json_dumps(mapping)
stable_json_dumps lives in serialization/json.py
fingerprints.py owns digest algorithms
```

---

## 27. Open Questions

### 27.1 Should `read_json` and `write_json` Exist?

They are convenient for tests and small scripts, but they blur the
serialization/I/O boundary.

Recommended answer for v0:

```text
include them as local-path convenience helpers
document that they are not atomic and not URI-aware
```

If they become confusing, move them to a small `serialization.files` module or
keep them internal to tests.

### 27.2 Should Paths Auto-Convert to Strings?

Recommended answer for v0:

```text
no
```

Callers should choose relative path, absolute path, or URI string explicitly.

### 27.3 Should Dataclass Reconstruction Interpret Type Hints?

Recommended answer for v0:

```text
no, except for narrow helpers needed by known public types
```

Full runtime type interpretation is easy to get subtly wrong. Public objects
should own explicit `from_dict` behavior.

### 27.4 Should YAML Be Part of Core Serialization?

Recommended answer:

```text
YAML helpers can live under serialization,
but YAML dependencies should remain optional.
```

JSON remains the stable machine format for fingerprints and store documents.

---

## 28. Summary

`loom.serialization` should be a small, strict, domain-neutral layer for
converting between public `loom` objects and plain structured data.

Its main jobs are:

```text
plain-data validation
dataclass conversion
stable JSON for fingerprints
pretty JSON for persisted documents
schema-version checks
clear serialization errors
```

It should not become:

```text
an I/O backend
a codec registry
a config composer
a migration framework
a pickle replacement
a domain object serializer
```

Keeping this boundary sharp makes the rest of `loom` simpler. Core primitives can
stay lightweight, run stores can focus on persistence semantics, fingerprints can
focus on semantic identity, and I/O can focus on resources and codecs.
