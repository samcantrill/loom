# `loom.io` Specification

## 1. Purpose

`loom.io` is the resource access and codec layer for `loom`.

It provides generic mechanisms for:

```text
parsing and normalizing URIs
opening resources from storage backends
checking existence and metadata for resources
registering source backends by URI scheme
encoding Python objects into stored bytes/text through codecs
decoding stored bytes/text back into Python objects through codecs
resolving codec keys carried by ResourceRef and ArtifactRef
```

It should not contain application-specific data interpretation. The generic
package can provide local filesystem support and simple JSON/text/bytes codecs.
Project packages provide codecs for domain formats such as arrays, videos,
images, model checkpoints, tables, reports, or other research artifacts.

The central boundary is:

```text
loom.io:
  bytes, files, URIs, source backends, codec dispatch

loom.serialization:
  Python objects <-> plain structured data

loom.pipeline.stores:
  run/artifact directory layout, atomic writes, locks, indexes

project packages:
  domain-specific codecs and resource semantics
```

### 1.1 Alignment With `loom.md`

This document details the resource access and codec mechanisms implied by
[loom.md](../loom.md). It keeps the dependency policy narrow: local files and simple
JSON/text/bytes codecs are generic `loom` concerns, while heavy storage clients
and domain formats belong in optional integrations or project packages.

---

## 2. Core Position

The recommended dependency shape is:

```text
ids / refs / artifacts / serialization / errors
        |
        v
io
        |
        v
artifact stores / pipeline stages / config recipes / project code
```

`loom.io` is above the core model and serialization layer. It can use
`ResourceRef`, `ArtifactRef`, and serialization helpers, but those lower-level
types should not import I/O.

Good:

```text
loom.io.codecs.json_codec imports loom.serialization.json
loom.pipeline.stores.local_artifacts imports loom.io.codecs.registry
project recipe code imports loom.io.sources.local
```

Bad:

```text
loom.refs imports loom.io
loom.serialization imports loom.io.sources
loom.io imports loom.pipeline.runner
loom.io imports project-specific codec modules eagerly
```

This keeps the primitive model serializable without making every import pull in
filesystem or backend behavior.

---

## 3. Package Boundary

### 3.1 `loom.io`

Owns the public I/O API.

Responsibilities:

```text
re-export stable source and codec interfaces
provide URI helpers
provide local filesystem source
provide generic JSON/text/bytes codecs
provide source and codec registries
define I/O-specific errors
```

### 3.2 `loom.io.uris`

Owns URI parsing and conversion.

Responsibilities:

```text
parse URI strings
extract schemes
convert local paths to file URIs
convert file URIs to paths
normalize URI strings where safe
raise clear unsupported URI errors
```

It should not open files or choose codecs.

### 3.3 `loom.io.sources`

Owns storage backend access.

Responsibilities:

```text
define DataSource protocol
implement LocalFileSystemSource
optionally route URI schemes to sources
open resources as bytes/text streams
glob or list resources where backend supports it
check resource existence
return basic stat metadata
```

Sources should not decode domain objects.

### 3.4 `loom.io.codecs`

Owns conversion between stored bytes/text and Python values.

Responsibilities:

```text
define Codec protocol
implement JSONCodec
implement TextCodec
implement BytesCodec
register codecs by key
load objects through a source and ResourceRef or ArtifactRef
save objects through a source or writable target when appropriate
```

Codecs should not own artifact-store layout.

### 3.5 `loom.serialization`

Owns object-to-plain-data conversion and stable JSON helpers.

`loom.io` may use serialization inside generic codecs:

```text
JSONCodec.encode(obj)
  -> to_plain_data(obj)
  -> json_dumps_pretty(...)
  -> UTF-8 bytes
```

Serialization must not import `loom.io`.

### 3.6 `loom.pipeline.stores`

Owns persistence policy for runs and artifacts.

Responsibilities:

```text
choose artifact paths
write files atomically
compute and record checksums
record ArtifactRef indexes
load artifacts through codec registries when requested
```

Artifact stores may call I/O codecs. I/O codecs should not know about run
directory layout or stage status.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
file URI parsing and normalization
local path to file URI conversion
file URI to local path conversion
scheme extraction
LocalFileSystemSource
DataSource protocol
SourceRegistry, if more than one source is needed
Codec protocol
CodecRegistry
JSONCodec for plain-data-compatible values
TextCodec for UTF-8 text
BytesCodec for raw bytes
I/O-specific error hierarchy
clear missing resource errors
clear unknown codec errors
```

### 4.2 Should Support Soon

```text
checksum helpers for local files
streaming copy helpers
source stat metadata normalization
extension-to-codec suggestions
entry point discovery for project codecs
read-only package resource source
HTTP read-only source
```

### 4.3 Should Not Support in v0

```text
remote write backends
S3/GCS/Azure dependencies
fsspec hard dependency
database-backed resources
automatic domain codec inference
dataframe/array/video/image codecs in loom core
atomic artifact-store writes
run directory locking
general caching layer
transparent decompression for every format
security sandboxing for untrusted resources
```

Remote and specialized support can be added later through optional packages,
plugin entry points, or project code once the local and codec interfaces are
stable.

---

## 5. Terminology

### 5.1 URI

A URI is a string location for a resource or artifact.

Examples:

```text
file:///data/project/input.jsonl
/data/project/input.jsonl
relative/path/input.json
s3://bucket/key
https://example.org/data.json
```

`loom` should represent stored resource locations as strings. URI parsing should
be explicit and centralized in `loom.io.uris`.

### 5.2 Scheme

The scheme is the leading URI component before `:`.

Examples:

```text
file
s3
gs
https
```

Local paths may have no scheme. V0 should treat no-scheme paths as local
filesystem paths where the caller context permits that.

### 5.3 Source

A source is a backend capable of accessing bytes or text at a URI.

Examples:

```text
local filesystem
HTTP server
S3 bucket
read-only mounted dataset
package resources
```

Sources answer storage questions:

```text
does this resource exist?
can this resource be opened?
what basic metadata does the backend expose?
which resources match this pattern?
```

They do not answer domain questions.

### 5.4 Codec

A codec converts between Python values and stored bytes/text for a format.

Examples:

```text
json.v1
text.v1
bytes.v1
project.video.mp4.v1
project.ndarray.npy.v1
```

Codecs answer representation questions:

```text
how should bytes be decoded?
how should an object be encoded?
which schema is expected?
what object type is returned?
```

### 5.5 ResourceRef

`ResourceRef` is a serializable pointer to input/source data.

It stores:

```text
uri
resource_type
codec_key
schema_version
checksum
metadata
```

It does not load the resource. I/O sources and codecs load it.

### 5.6 ArtifactRef

`ArtifactRef` points to a produced output.

It may include:

```text
uri
artifact_type
codec_key
checksum
fingerprint
producer metadata
```

Artifact stores own how artifacts are saved and indexed. I/O codecs may be used
for managed load/save operations.

### 5.7 Checksum

A checksum is a digest of stored bytes.

It answers:

```text
are these stored bytes intact or identical?
```

It is not the same as a fingerprint, which answers whether a semantic production
recipe is equivalent.

---

## 6. Guiding Design Principles

### 6.1 Keep I/O Domain-Neutral

`loom.io` should not contain:

```text
ImageCodec
VideoCodec
TensorCodec
PhysiologyCodec
Dataset-specific readers
model checkpoint assumptions
metric table schemas
```

The generic package can provide only broadly useful codecs:

```text
JSON
text
bytes
```

### 6.2 Use Protocols, Not Inheritance Frameworks

Downstream packages should be able to provide source and codec classes by
structural compatibility.

Good:

```python
class MyCodec:
    key = "project.array.npy.v1"

    def load(self, ref, *, source): ...
    def save(self, obj, uri, *, source, metadata=None): ...
```

No subclassing should be required.

### 6.3 Separate Storage From Representation

Sources know how to access bytes. Codecs know how to interpret bytes.

Good flow:

```text
ResourceRef
  -> SourceRegistry chooses source from URI
  -> source.open(uri, "rb")
  -> CodecRegistry chooses codec from codec_key
  -> codec.decode(bytes or stream)
```

Avoid:

```text
LocalFileSystemSource decodes JSON into dicts
JSONCodec decides where run artifacts should be stored
ResourceRef opens files directly
```

### 6.4 Make Local Files Excellent First

V0 should make local filesystem behavior reliable and clear.

This includes:

```text
path normalization
file URI conversion
relative path policy
existence checks
basic stat metadata
safe errors for missing files
UTF-8 text defaults
binary access
```

Remote sources can be added later without disturbing the local API.

### 6.5 Avoid Heavy Dependencies in Core I/O

The base I/O layer should use the standard library.

Optional backends can live behind extras:

```toml
[project.optional-dependencies]
s3 = ["s3fs"]
gcs = ["gcsfs"]
http = ["httpx"]
```

Do not make these dependencies required for importing `loom.io`.

### 6.6 Fail Clearly on Missing Registrations

Unknown scheme and unknown codec errors should be actionable.

Bad:

```text
KeyError: "json"
```

Good:

```text
No codec registered for key "json.v1".
Registered codecs: bytes.v1, json.v1, text.v1.
```

### 6.7 Do Not Guess Too Much

V0 should avoid automatic codec selection from file extensions except as an
optional helper.

Reason:

```text
extensions are ambiguous
resource_type and codec_key are explicit in ResourceRef/ArtifactRef
project formats often share extensions but differ by schema
```

---

## 7. Public API

### 7.1 Recommended Imports

```python
from loom.io import (
    DataSource,
    LocalFileSystemSource,
    SourceRegistry,
    Codec,
    CodecRegistry,
    JSONCodec,
    TextCodec,
    BytesCodec,
    parse_uri,
    normalize_uri,
    path_to_file_uri,
    uri_to_path,
)
```

### 7.2 `io/__init__.py`

Recommended exports:

```python
from loom.io.uris import (
    ParsedURI,
    parse_uri,
    get_uri_scheme,
    is_file_uri,
    path_to_file_uri,
    uri_to_path,
    normalize_uri,
)
from loom.io.sources.base import DataSource
from loom.io.sources.local import LocalFileSystemSource
from loom.io.sources.registry import SourceRegistry
from loom.io.codecs.base import Codec
from loom.io.codecs.registry import CodecRegistry
from loom.io.codecs.json_codec import JSONCodec
from loom.io.codecs.text_codec import TextCodec
from loom.io.codecs.bytes_codec import BytesCodec
from loom.io.errors import LoomIOError
```

Avoid importing optional remote backends from `io/__init__.py`.

---

## 8. `io/uris.py`

### 8.1 Purpose

`uris.py` provides shared URI parsing and local path conversion.

Recommended functions:

```text
parse_uri
get_uri_scheme
is_file_uri
is_local_uri
path_to_file_uri
uri_to_path
normalize_uri
join_uri
```

### 8.2 Parsed URI Type

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class ParsedURI:
    raw: str
    scheme: str | None
    path: str
    authority: str | None = None
    query: str | None = None
    fragment: str | None = None
```

This type should remain simple. It is not a replacement for the standard
library URL parser.

### 8.3 Scheme Extraction

Representative signature:

```python
def get_uri_scheme(uri: str) -> str | None: ...
```

Behavior:

```text
"file:///tmp/a.txt" -> "file"
"s3://bucket/key" -> "s3"
"/tmp/a.txt" -> None
"relative/a.txt" -> None
```

Windows drive-letter behavior can be handled later if the project needs Windows
support.

### 8.4 File URI Policy

V0 should support:

```text
file:///absolute/path
/absolute/path
relative/path
```

Recommended behavior:

```text
file URI:
  parse as local filesystem path

absolute path with no scheme:
  treat as local path

relative path with no scheme:
  preserve relative path until caller resolves it against a base
```

Do not silently convert every relative path to an absolute path at parse time.
The correct base directory is caller-owned.

### 8.5 `path_to_file_uri`

Representative signature:

```python
def path_to_file_uri(path: str | Path) -> str: ...
```

Behavior:

```text
expand user only if explicitly requested
resolve absolute path only if explicitly requested
return file URI with safe quoting
```

Recommended default:

```text
absolute paths -> file:///...
relative paths -> file:relative/path is avoided;
                  either raise or require caller to resolve first
```

Simpler v0 policy:

```text
path_to_file_uri requires an absolute local path
```

### 8.6 `uri_to_path`

Representative signature:

```python
def uri_to_path(uri: str) -> Path: ...
```

Behavior:

```text
file URI -> Path
absolute local path -> Path
relative local path -> Path
unsupported scheme -> UnsupportedURIError
```

Remote schemes should not be converted to paths.

### 8.7 `normalize_uri`

Representative signature:

```python
def normalize_uri(uri: str, *, base_dir: str | Path | None = None) -> str: ...
```

Behavior:

```text
strip surrounding whitespace? no, reject instead
normalize local path separators where safe
resolve relative local paths against base_dir only when provided
preserve remote URIs without lossy rewriting
```

Do not normalize away meaningful remote URI details such as query strings.

### 8.8 URI Joining

Joining is backend-specific. A small helper can support simple hierarchical URIs:

```python
def join_uri(base: str, *parts: str) -> str: ...
```

Use cases:

```text
local file artifact paths
s3-like path joins later
source-local relative paths
```

V0 can defer this helper if artifact stores already own path joining.

---

## 9. `io/errors.py`

### 9.1 Purpose

I/O errors should be distinguishable from serialization, config, and pipeline
errors.

Recommended hierarchy:

```python
class LoomIOError(LoomError): ...
class UnsupportedURIError(LoomIOError): ...
class DataSourceError(LoomIOError): ...
class CodecError(LoomIOError): ...
class ChecksumError(LoomIOError): ...
```

If `LoomError` is not implemented yet, these can initially inherit from
`Exception` and later move under the shared base error.

### 9.2 Error Context

Errors should include useful fields when practical:

```text
uri
scheme
codec_key
source_name
operation
path
```

Example:

```text
Cannot open resource file:///data/missing.json.
Source: local filesystem.
Operation: open rb.
Reason: file does not exist.
```

### 9.3 Error Boundaries

Recommended wrapping policy:

```text
OSError from local source:
  wrap as DataSourceError or SourceNotFoundError with URI context

JSON parse error in JSONCodec:
  wrap as CodecError or propagate DeserializationError with codec context

unknown URI scheme:
  UnsupportedURIError

unknown codec key:
  CodecRegistrationError or UnknownCodecError
```

Use exception chaining to preserve low-level details.

---

## 10. `io/sources/base.py`

### 10.1 Purpose

`base.py` defines the source protocol.

Representative protocol:

```python
class DataSource(Protocol):
    name: str

    def supports(self, uri: str) -> bool: ...
    def resolve(self, path: str) -> str: ...
    def open(self, uri: str, mode: str = "rb") -> BinaryIO | TextIO: ...
    def exists(self, uri: str) -> bool: ...
    def stat(self, uri: str) -> Mapping[str, object]: ...
    def glob(self, pattern: str) -> Iterable[str]: ...
```

The exact signatures can be narrowed during implementation. The key property is
that a source accesses bytes or text without interpreting domain data.

### 10.2 Required Operations

V0 should require:

```text
supports
open
exists
stat
```

`glob` can be optional or raise `UnsupportedOperationError` for sources that do
not support listing.

### 10.3 Open Modes

Recommended supported modes:

```text
rb
rt
wb, only for writable sources
wt, only for writable sources
```

Do not support arbitrary Python file modes initially.

For text modes, default encoding should be UTF-8 unless the source method takes
an explicit encoding parameter.

### 10.4 Source Metadata

`stat(uri)` should return plain-data-compatible metadata where possible.

Suggested keys:

```text
uri
exists
size_bytes
mtime
checksum, if cheap and explicitly requested later
backend
```

Avoid returning raw `os.stat_result` objects from public APIs.

### 10.5 Read-Only and Writable Sources

Most resource sources can start read-only. Writable behavior matters mainly for
artifact stores.

Recommended policy:

```text
LocalFileSystemSource supports writes.
Remote read sources can be read-only.
Write attempts on read-only sources raise DataSourceError.
```

### 10.6 Streaming

Sources should allow streaming where possible.

For large resources:

```text
source.open(uri, "rb") returns a binary stream
codec can decode from stream or bytes
caller can copy stream without loading whole file
```

V0 generic codecs can be simple, but the protocol should not force all resources
into memory.

---

## 11. `io/sources/local.py`

### 11.1 Purpose

`LocalFileSystemSource` is the v0 storage backend.

It supports:

```text
absolute local paths
relative paths resolved against an optional root
file URIs
open
exists
stat
glob
basic writes
```

### 11.2 Representative Constructor

```python
@dataclass(frozen=True, slots=True)
class LocalFileSystemSource:
    root: Path | None = None
    name: str = "local"
```

`root` is optional. When provided, relative paths are resolved against it.

### 11.3 Path Resolution

Recommended behavior:

```text
file:///absolute/path:
  use absolute path

/absolute/path:
  use absolute path

relative/path with root:
  root / relative/path

relative/path without root:
  Path(relative/path)
```

Do not silently restrict paths to `root` in v0 unless a security requirement is
introduced. Authored configs are trusted project code.

### 11.4 File URI Conversion

`LocalFileSystemSource.resolve(path)` should return a normalized local URI or
path according to the API chosen by implementation.

Recommended public output:

```text
file:///absolute/path
```

Reason:

```text
ResourceRef and ArtifactRef use URI strings
file URIs distinguish persisted references from process-relative paths
```

### 11.5 Glob

Representative signature:

```python
def glob(self, pattern: str) -> Iterable[str]: ...
```

Behavior:

```text
patterns are source-local when root is set
return normalized URI strings
sort results for deterministic manifests
raise DataSourceError for invalid patterns
```

Sorting matters because manifests and fingerprints should be reproducible.

### 11.6 Stat

Recommended stat output:

```python
{
    "uri": "file:///data/project/input.jsonl",
    "backend": "local",
    "exists": True,
    "size_bytes": 12345,
    "mtime": "2026-05-02T12:00:00Z",
}
```

Use stable timestamp helpers when available. Avoid returning platform-specific
objects.

### 11.7 Missing Files

`exists` should return `False`.

`open` should raise a source-specific error with URI/path context:

```text
SourceNotFoundError
```

This lets callers choose between preflight checks and direct open attempts.

### 11.8 Writes

Local writes are useful for artifact stores and simple codec tests.

Recommended policy:

```text
LocalFileSystemSource.open(uri, "wb") can create or truncate files.
It does not perform atomic writes.
It does not create parent directories unless explicitly requested by helper.
Artifact stores own production-safe atomic writes.
```

---

## 12. `io/sources/registry.py`

### 12.1 Purpose

`SourceRegistry` maps URI schemes to source implementations.

This lets callers resolve a `ResourceRef.uri` without hard-coding every backend.

Representative structure:

```python
class SourceRegistry:
    def register(self, scheme: str | None, source: DataSource) -> None: ...
    def get(self, uri: str) -> DataSource: ...
    def supports(self, uri: str) -> bool: ...
```

### 12.2 Scheme Mapping

Suggested mappings:

```text
None -> LocalFileSystemSource
file -> LocalFileSystemSource
s3 -> S3Source, later
gs -> GCSSource, later
https -> HTTPSource, later
```

The `None` scheme represents no-scheme local paths.

### 12.3 Default Registry

Avoid hidden mutable global state where possible.

Recommended v0 options:

```text
provide create_default_source_registry()
allow callers to pass explicit registry
avoid import-time plugin discovery
```

Example:

```python
registry = create_default_source_registry()
source = registry.get(ref.uri)
```

### 12.4 Registration Errors

Registration should fail clearly when:

```text
scheme is already registered and replace=False
source does not satisfy DataSource protocol at runtime, if checked
scheme string is invalid
```

### 12.5 Deferred Until Needed

If v0 only supports local files, `SourceRegistry` can be very small or deferred.

Still, the design should avoid baking local-only assumptions into codecs and
artifact stores.

---

## 13. `io/sources/errors.py`

### 13.1 Purpose

Source-specific errors make source failures actionable.

Recommended hierarchy:

```python
class DataSourceError(LoomIOError): ...
class SourceNotFoundError(DataSourceError): ...
class SourcePermissionError(DataSourceError): ...
class UnsupportedSourceSchemeError(DataSourceError): ...
class SourceRegistrationError(DataSourceError): ...
class UnsupportedSourceOperationError(DataSourceError): ...
```

### 13.2 Example Messages

Missing file:

```text
Resource does not exist: file:///data/input.jsonl.
Source: local.
Operation: open rb.
```

Unsupported scheme:

```text
No data source registered for URI scheme "s3".
URI: s3://bucket/key.
Registered schemes: file, <local path>.
```

Unsupported operation:

```text
Source "http" does not support glob().
Pattern: https://example.org/data/*.json.
```

---

## 14. `io/codecs/base.py`

### 14.1 Purpose

`base.py` defines the codec protocol.

A codec converts between stored bytes/text and Python values.

Representative protocol:

```python
class Codec(Protocol):
    key: str

    def load(
        self,
        ref: ResourceRef | ArtifactRef,
        *,
        source: DataSource,
    ) -> object: ...

    def save(
        self,
        obj: object,
        uri: str,
        *,
        source: DataSource,
        metadata: Mapping[str, object] | None = None,
    ) -> ResourceRef | ArtifactRef | str: ...
```

The exact save return type may differ depending on whether codecs are used by
resource builders or artifact stores. The core contract is:

```text
codec reads/writes content;
caller owns reference construction policy.
```

### 14.2 Preferred Narrower Interface

To keep codecs independent from reference construction, v0 may prefer:

```python
class Codec(Protocol):
    key: str

    def decode(self, data: bytes, *, metadata: Mapping[str, object] | None = None) -> object: ...
    def encode(self, obj: object, *, metadata: Mapping[str, object] | None = None) -> bytes: ...
```

Then higher-level helpers perform:

```text
source.open(uri).read()
codec.decode(bytes)
```

This is simpler to test and keeps references out of codec internals.

### 14.3 Recommended V0 Decision

Use the narrow encode/decode interface for generic codecs.

Provide registry helpers for load/save:

```python
registry.load(ref, sources=source_registry)
registry.save(obj, uri, codec_key="json.v1", source=source)
```

Reason:

```text
codecs stay representation-focused
source selection remains explicit
artifact stores can control writes and reference construction
```

### 14.4 Metadata

Codec metadata should be optional and plain-data-compatible.

Examples:

```text
encoding for text
schema name for JSON
array dtype for project array codec
compression setting for project codec
```

Do not use metadata for hidden runtime dependencies.

### 14.5 Streaming Codecs

Some codecs may need streams for large files.

Future extension:

```python
class StreamingCodec(Protocol):
    key: str
    def decode_stream(self, stream: BinaryIO, *, metadata: Mapping[str, object] | None = None) -> object: ...
    def encode_stream(self, obj: object, stream: BinaryIO, *, metadata: Mapping[str, object] | None = None) -> None: ...
```

Do not require this in v0.

---

## 15. `io/codecs/json_codec.py`

### 15.1 Purpose

`JSONCodec` handles generic JSON payloads.

It should use `loom.serialization` for plain-data conversion and JSON parsing.

### 15.2 Codec Key

Recommended key:

```text
json.v1
```

Aliases such as `json` can be supported later, but stable authored configs should
prefer explicit versioned keys.

### 15.3 Encode

Representative behavior:

```text
input object
  -> serialization.to_plain_data
  -> serialization.json_dumps_pretty
  -> UTF-8 bytes
```

Output should be deterministic enough for persisted small documents.

### 15.4 Decode

Representative behavior:

```text
UTF-8 bytes
  -> text
  -> serialization.json_loads
  -> plain data
```

`JSONCodec` should not reconstruct arbitrary Python objects. Callers that need a
specific type should call explicit `from_dict` methods after loading.

### 15.5 Errors

Encoding errors should include:

```text
codec key
operation
plain-data path when available
```

Decoding errors should include:

```text
codec key
source URI when caller provides it
JSON parse location
schema context when caller provides it
```

---

## 16. `io/codecs/text_codec.py`

### 16.1 Purpose

`TextCodec` handles plain text.

Recommended key:

```text
text.v1
```

### 16.2 Encoding

Default encoding:

```text
UTF-8
```

Accepted input:

```text
str
```

V0 should reject non-string objects rather than silently calling `str(obj)`.

Reason:

```text
silent conversion can hide bugs and create unstable output
```

### 16.3 Decoding

Return:

```text
str
```

Default behavior:

```text
decode bytes as UTF-8
raise CodecError on UnicodeDecodeError
```

Optional metadata:

```text
encoding
errors
```

Keep the default strict.

---

## 17. `io/codecs/bytes_codec.py`

### 17.1 Purpose

`BytesCodec` is a pass-through codec for raw bytes.

Recommended key:

```text
bytes.v1
```

### 17.2 Encoding

Accepted inputs:

```text
bytes
bytearray, normalized to bytes
memoryview, normalized to bytes
```

Reject arbitrary objects.

### 17.3 Decoding

Return:

```text
bytes
```

This codec is useful for:

```text
generic binary artifacts
tests
project codecs that want to wrap raw bytes
small binary metadata
```

Large binary resources should usually be streamed or handled by specialized
project codecs.

---

## 18. `io/codecs/registry.py`

### 18.1 Purpose

`CodecRegistry` maps codec keys to codec implementations.

Representative structure:

```python
class CodecRegistry:
    def register(self, codec: Codec, *, replace: bool = False) -> None: ...
    def get(self, key: str) -> Codec: ...
    def keys(self) -> tuple[str, ...]: ...
    def encode(self, key: str, obj: object, *, metadata: Mapping[str, object] | None = None) -> bytes: ...
    def decode(self, key: str, data: bytes, *, metadata: Mapping[str, object] | None = None) -> object: ...
```

### 18.2 Default Registry

Recommended helper:

```python
def create_default_codec_registry() -> CodecRegistry:
    registry = CodecRegistry()
    registry.register(JSONCodec())
    registry.register(TextCodec())
    registry.register(BytesCodec())
    return registry
```

Avoid a mutable global registry as the only path.

### 18.3 Project Codec Registration

Project code should be able to register codecs explicitly:

```python
registry = create_default_codec_registry()
registry.register(ProjectArrayCodec())
registry.register(ProjectVideoCodec())
```

Config recipes or pipeline setup code can pass this registry into artifact
stores or stage contexts.

### 18.4 Entry Point Discovery

Future support:

```toml
[project.entry-points."loom.codecs"]
array_npy_v1 = "project.codecs:ArrayNpyCodec"
video_mp4_v1 = "project.codecs:VideoMp4Codec"
```

Recommended policy:

```text
entry point discovery is explicit
not performed on import loom.io
errors identify failing entry point and package
duplicates require deterministic conflict policy
```

### 18.5 Unknown Codec

Unknown codec errors should include available keys.

Example:

```text
No codec registered for key "video.mp4.v1".
Registered codecs: bytes.v1, json.v1, text.v1.
```

If many codecs are registered, truncate the list and include the count.

### 18.6 Save and Load Helpers

Registry-level helpers can combine source and codec behavior.

Representative signatures:

```python
def load_resource(
    ref: ResourceRef,
    *,
    sources: SourceRegistry,
    codecs: CodecRegistry,
) -> object: ...

def load_artifact(
    ref: ArtifactRef,
    *,
    sources: SourceRegistry,
    codecs: CodecRegistry,
) -> object: ...
```

These helpers should stay thin:

```text
validate codec_key exists
resolve source from URI
read bytes
decode bytes
return object
```

They should not update run-store status or artifact indexes.

---

## 19. `io/codecs/errors.py`

### 19.1 Purpose

Codec errors should identify representation failures.

Recommended hierarchy:

```python
class CodecError(LoomIOError): ...
class CodecRegistrationError(CodecError): ...
class UnknownCodecError(CodecError): ...
class CodecEncodeError(CodecError): ...
class CodecDecodeError(CodecError): ...
class UnsupportedCodecOperationError(CodecError): ...
```

### 19.2 Example Messages

Unknown codec:

```text
No codec registered for key "jsonl.v1".
Registered codecs: bytes.v1, json.v1, text.v1.
```

Encode failure:

```text
Codec "json.v1" could not encode object at $.metrics.created_at.
Reason: datetime is not plain data.
```

Decode failure:

```text
Codec "text.v1" could not decode bytes as UTF-8.
URI: file:///runs/example/artifacts/report.txt.
```

---

## 20. Resource Loading Flow

### 20.1 Loading a ResourceRef

Recommended flow:

```text
ResourceRef(uri, codec_key)
  -> ensure codec_key is present
  -> SourceRegistry.get(uri)
  -> source.open(uri, "rb")
  -> CodecRegistry.get(codec_key)
  -> codec.decode(bytes, metadata=ref.metadata)
  -> return Python object
```

### 20.2 Missing Codec Key

Some resources are tracked but not generically loadable by `loom`.

If `codec_key` is `None`:

```text
load_resource(ref) should raise MissingCodecError or CodecError
message should explain that caller must provide a codec explicitly
```

Do not guess from `resource_type` in v0.

### 20.3 Missing Source

If no source supports the URI:

```text
raise UnsupportedURIError or UnsupportedSourceSchemeError
```

The error should include:

```text
uri
scheme
registered schemes
```

### 20.4 Missing Resource

If the source exists but the resource does not:

```text
raise SourceNotFoundError
```

Callers that need optional resources can call `exists` first.

### 20.5 Metadata Passing

Codec metadata should combine:

```text
ref.metadata
explicit caller metadata overrides
codec defaults
```

Recommended precedence:

```text
explicit caller metadata overrides ref metadata
ref metadata overrides codec defaults
```

Keep this policy simple and documented.

---

## 21. Artifact Loading and Saving

### 21.1 Loading ArtifactRef

Artifact loading through I/O should be symmetrical with resource loading:

```text
ArtifactRef(uri, codec_key)
  -> ensure codec_key is present or explicit codec provided
  -> resolve source
  -> read bytes
  -> decode object
```

Artifact stores may provide this as:

```python
artifact_store.load(ref)
```

Internally, the store can delegate to codec registries.

### 21.2 Saving Artifacts

Artifact stores own saving policy.

They decide:

```text
artifact ID
target URI
temporary path
atomic move
checksum calculation
ArtifactRef fields
index update
```

Codecs only encode object content.

Good:

```text
LocalArtifactStore chooses file path
LocalArtifactStore calls codec.encode(obj)
LocalArtifactStore writes bytes atomically
LocalArtifactStore computes checksum
LocalArtifactStore returns ArtifactRef
```

Bad:

```text
JSONCodec decides artifact ID
JSONCodec writes artifacts.json
JSONCodec updates run status
```

### 21.3 Saving Resources

Some config recipes may create resource files, but v0 can treat resources as
external inputs.

Generic resource saving is lower priority than artifact saving.

---

## 22. Checksums

### 22.1 Purpose

I/O is a natural place for byte checksum helpers, but checksum policy spans
artifact stores and core references.

Recommended helpers:

```text
hash_file
hash_bytes
compute_uri_checksum
verify_checksum
```

These can live in `loom.fingerprints`, `loom.io.checksums`, or top-level
checksum helpers depending on implementation.

### 22.2 Recommended V0 Policy

For v0:

```text
artifact stores compute checksums for local files they write
sources may expose size/mtime cheaply
generic I/O does not checksum every resource automatically
```

Reason:

```text
large resources can be expensive to hash
remote resources may charge or be slow
checksums should be explicit when they affect resume or integrity
```

### 22.3 Verification

When a `ResourceRef` or `ArtifactRef` includes a checksum, callers may verify it:

```text
resolve source
read bytes or stream chunks
compute digest
compare with expected
raise ChecksumError on mismatch
```

V0 can limit verification to local files.

---

## 23. URI and Path Policy

### 23.1 Persisted References

Persisted references should prefer URI strings.

Recommended:

```text
file:///absolute/path/to/artifact.json
```

Acceptable in authored configs:

```text
relative/path/input.json
/absolute/path/input.json
```

When persisting run outputs, stores should normalize to stable URIs where
possible.

### 23.2 Relative Paths

Relative path base is caller-owned.

Examples:

```text
config loader may resolve relative to config file directory
run store may resolve relative to run directory
local source may resolve relative to its root
project code may resolve relative to project root
```

`loom.io.uris` should not guess the base globally.

### 23.3 User Home Expansion

Recommended policy:

```text
do not expand ~ unless a caller explicitly requests it
```

Reason:

```text
persisted references should not silently depend on the current user's home
directory
```

Authored configs can use absolute paths or project-level variables.

### 23.4 Environment Variables

`loom.io` should not expand environment variables in URIs by default.

Config interpolation owns environment expansion if supported.

---

## 24. Registries and Configuration

### 24.1 Explicit Registry Construction

Use explicit constructors:

```python
from loom.io import create_default_codec_registry

codecs = create_default_codec_registry()
codecs.register(ProjectCodec())
```

This is easier to test than global mutation.

### 24.2 Config-Driven Registration

Config can instantiate codecs through `_target_`:

```yaml
io:
  codecs:
    - _target_: project.codecs.ArrayNpyCodec
    - _target_: project.codecs.VideoCodec
```

`weave` instantiates objects. `loom.io` registers them.

### 24.3 Recipe-Driven Registration

Recipes may provide standard codec sets for a project:

```yaml
io:
  _recipe_: project_default_io
```

The recipe expands into explicit codec/source configuration. I/O should not know
the recipe system.

### 24.4 Entry Point Discovery

Entry point discovery should be opt-in:

```python
registry.discover_entry_points(group="loom.codecs")
```

Do not discover project code at import time.

---

## 25. Security and Trust

### 25.1 Trusted Configs

Authored configs are trusted project code. A config may register a codec that
imports and executes project code.

Document this clearly:

```text
Do not load untrusted loom configs.
```

### 25.2 Resource Content Is Not Trusted Automatically

Even if configs are trusted, resource bytes can be malformed.

Codecs should:

```text
validate expected format
raise clear decode errors
avoid unsafe loaders
avoid pickle in generic codecs
```

### 25.3 Generic Codecs Avoid Code Execution

Generic codecs should not use:

```text
pickle
eval
exec
unsafe YAML loaders
dynamic imports from resource content
```

Project codecs can make project-specific decisions, but generic `loom` codecs
should stay conservative.

---

## 26. Examples

### 26.1 Loading JSON Resource

```python
from loom.io import (
    LocalFileSystemSource,
    create_default_codec_registry,
    create_default_source_registry,
    load_resource,
)
from loom.refs import ResourceRef

sources = create_default_source_registry(root="/data/project")
codecs = create_default_codec_registry()

ref = ResourceRef(
    uri="file:///data/project/input.json",
    resource_type="json",
    codec_key="json.v1",
)

payload = load_resource(ref, sources=sources, codecs=codecs)
```

Expected result:

```text
payload is plain data loaded from JSON
```

### 26.2 Registering a Project Codec

```python
class ArrayNpyCodec:
    key = "project.ndarray.npy.v1"

    def encode(self, obj, *, metadata=None) -> bytes:
        ...

    def decode(self, data: bytes, *, metadata=None):
        ...


codecs = create_default_codec_registry()
codecs.register(ArrayNpyCodec())
```

The codec can then be referenced by:

```python
ResourceRef(
    uri="file:///data/array.npy",
    resource_type="array",
    codec_key="project.ndarray.npy.v1",
)
```

### 26.3 Local Glob for Manifest Construction

```python
source = LocalFileSystemSource(root="/data/project")

uris = list(source.glob("records/*.json"))
```

Expected behavior:

```text
results are sorted
results are returned as normalized URI strings
```

### 26.4 Artifact Store Delegating to Codec

```python
codec = codecs.get("json.v1")
payload = codec.encode({"accuracy": 0.91})

artifact_ref = artifact_store.write_bytes(
    artifact_id="evaluate/metrics",
    data=payload,
    artifact_type="metrics",
    codec_key="json.v1",
)
```

The artifact store chooses the URI and computes checksum. The codec only encodes
content.

---

## 27. Testing Strategy

### 27.1 URI Tests

Test:

```text
scheme extraction
file URI parsing
absolute path handling
relative path handling
unsupported scheme errors
path_to_file_uri requires absolute path, if selected
uri_to_path rejects remote schemes
normalization is deterministic
```

### 27.2 Local Source Tests

Test:

```text
open existing binary file
open existing text file as UTF-8
missing file exists returns False
missing file open raises SourceNotFoundError
stat returns plain-data-compatible metadata
glob returns sorted URI strings
relative paths resolve against root
file URIs resolve correctly
write modes work when explicitly used
```

### 27.3 Source Registry Tests

Test:

```text
None scheme resolves to local source
file scheme resolves to local source
unknown scheme raises clear error
duplicate registration rejected by default
replace=True replaces existing source
registered schemes are listed deterministically
```

### 27.4 Codec Tests

Test:

```text
JSONCodec encodes plain data
JSONCodec rejects non-plain data with path
JSONCodec decodes JSON into plain data
TextCodec encodes only strings
TextCodec decodes UTF-8
BytesCodec passes bytes through
BytesCodec accepts bytearray and memoryview if implemented
codec errors include codec key
```

### 27.5 Codec Registry Tests

Test:

```text
default registry contains json.v1, text.v1, bytes.v1
register project codec
duplicate codec rejected by default
replace=True replaces codec
unknown codec error lists available keys
encode/decode dispatches to selected codec
```

### 27.6 Integration Tests

Test:

```text
ResourceRef JSON load through source and codec registries
ArtifactRef JSON load through source and codec registries
LocalArtifactStore delegates content encoding to codec
config-instantiated codec can be registered
manifest construction from LocalFileSystemSource.glob is deterministic
```

### 27.7 Dependency Tests

Test import boundaries:

```text
import loom.io does not import loom.pipeline
import loom.io does not import remote optional backends
import loom.refs does not import loom.io
import loom.serialization does not import loom.io
```

---

## 28. Implementation Plan

### 28.1 Phase 1: URI Helpers and Errors

Create:

```text
src/loom/io/__init__.py
src/loom/io/uris.py
src/loom/io/errors.py
```

Implement:

```text
get_uri_scheme
is_file_uri
uri_to_path
path_to_file_uri
normalize_uri
LoomIOError
UnsupportedURIError
```

### 28.2 Phase 2: Source Protocol and Local Source

Create:

```text
src/loom/io/sources/__init__.py
src/loom/io/sources/base.py
src/loom/io/sources/local.py
src/loom/io/sources/errors.py
```

Implement:

```text
DataSource protocol
LocalFileSystemSource
local open/exists/stat/glob
source-specific errors
```

### 28.3 Phase 3: Codec Protocol and Generic Codecs

Create:

```text
src/loom/io/codecs/__init__.py
src/loom/io/codecs/base.py
src/loom/io/codecs/json_codec.py
src/loom/io/codecs/text_codec.py
src/loom/io/codecs/bytes_codec.py
src/loom/io/codecs/errors.py
```

Implement:

```text
Codec protocol
JSONCodec
TextCodec
BytesCodec
codec error hierarchy
```

### 28.4 Phase 4: Registries

Create:

```text
src/loom/io/sources/registry.py
src/loom/io/codecs/registry.py
```

Implement:

```text
SourceRegistry
CodecRegistry
create_default_source_registry
create_default_codec_registry
unknown source/codec errors
```

### 28.5 Phase 5: Load Helpers

Add thin helpers:

```text
load_resource
load_artifact
read_uri_bytes
write_uri_bytes, only if useful
```

Keep these helpers independent from pipeline status and store indexes.

### 28.6 Phase 6: Store Integration

Update artifact store implementation to:

```text
use CodecRegistry for managed save/load
use SourceRegistry or LocalFileSystemSource for local reads
compute checksums at store boundary
return ArtifactRef with codec_key and checksum
```

### 28.7 Phase 7: Config Integration

Update config recipes or top-level setup to allow:

```text
instantiating project codecs
registering project codecs
passing registries into pipeline runtime or StageContext
```

---

## 29. Open Questions

### 29.1 Should Codec Methods Accept Bytes or Streams?

Recommended v0 answer:

```text
bytes for simple generic codecs
streaming protocol later
```

This keeps JSON/text/bytes codecs simple while leaving room for large project
artifacts.

### 29.2 Should SourceRegistry Be Required in v0?

Recommended answer:

```text
implement a small registry if load_resource exists;
otherwise allow LocalFileSystemSource to be passed directly
```

Do not let v0 APIs assume local files so strongly that remote sources become a
breaking change later.

### 29.3 Should Codec Keys Be Versioned?

Recommended answer:

```text
yes for stable persisted refs
```

Examples:

```text
json.v1
text.v1
bytes.v1
project.ndarray.npy.v1
```

Versioned keys make old manifests and artifact indexes easier to understand.

### 29.4 Should File Extensions Infer Codecs?

Recommended v0 answer:

```text
no for automatic loading
optional helper only
```

Explicit `codec_key` is more reproducible.

### 29.5 Should Remote Backends Use fsspec?

Recommended answer:

```text
defer
```

If multiple remote backends become necessary, evaluate an optional fsspec-backed
source. Do not add it as a hard dependency before then.

---

## 30. Summary

`loom.io` should be a small, explicit, domain-neutral layer for resource access
and codec dispatch.

Its main jobs are:

```text
URI parsing and normalization
local filesystem access
source backend protocols
codec protocols
generic JSON/text/bytes codecs
source and codec registries
clear I/O errors
thin ResourceRef and ArtifactRef loading helpers
```

It should not become:

```text
a domain data library
an artifact-store layout manager
a run-store atomic write system
a config composer
a remote storage platform too early
a global plugin system with import-time side effects
```

Keeping this boundary clear lets `ResourceRef` and `ArtifactRef` remain passive,
lets stores own persistence semantics, lets serialization own stable structured
data, and lets project packages bring the domain codecs they actually need.
