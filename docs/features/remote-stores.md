# loom Remote Artifact Stores Specification

## Purpose

Remote artifact stores let `loom` record and retrieve artifacts outside the
local filesystem while keeping the core artifact-store contract stable.

Examples include S3, GCS, Azure Blob, HTTP-backed read-only stores, and external
tracking systems such as MLflow.

Remote stores are intentionally deferred until local filesystem behavior is
stable. This document defines the boundary so the local design does not block
future remote backends.

Stage 15 implements the generic metadata interface layer. Core now has
backend-neutral store references, backend descriptors/factories/handlers,
capability records, explicit immutable lookup results, preflight capability
checks, and metadata-preserving run exchange. It does not include first-party
S3, GCS, Azure, HTTP, MLflow, DVC, W&B, or tracking-system adapters, and it does
not import their SDKs.

Stage 16 adds explicit payload-operation records and fake backend conformance
for publish, materialize, upload, download, and checksum verification. This is
still not a real backend selection: provider adapters, credential chains,
network operations, retry policy, and cleanup policy remain future work.

Adapter examples in this document are contract shapes. A future optional package
can map an MLflow-like tracking URI or object-store prefix into the same
generic records, but core `loom` does not perform provider upload, download,
materialization, deletion, credential refresh, or network probing unless an
explicit caller-supplied handler implements the store-owned payload protocol.

Two fake adapter shapes are used in contract tests:

- A tracking-system-style backend reports a descriptor kind such as
  `tracking-system`, accepts redacted `runs:` or `tracking:` URIs, supports
  read and explicit lookup, and can resolve a tracking URI to an object-store
  payload location through the same payload result shape.
- An object-store-style backend reports a descriptor kind such as
  `object-store`, accepts redacted `s3:` or `gs:` URIs, supports read and
  checksum-oriented metadata, and can fake upload, download, materialize, or
  checksum verification without importing a provider SDK.

Both examples preserve only plain summaries and operation evidence in run
exchange metadata. They are not supported first-party adapters.

## Stage 16 No-Backend Boundary

Core `loom` intentionally ends Stage 16 with no real backend family selected.
User-facing handles should therefore be explicit about the difference between:

```text
metadata preservation:
  record and inspect redacted refs, checksums, and unsupported context

local materialization:
  copy local file payloads only when the caller asks for copy

fake payload operations:
  prove the public request/result/protocol shape without provider SDKs

future real adapters:
  return unsupported or not-implemented results until an optional backend exists
```

Revisit this boundary only when a concrete backend is selected, fake
object-store/tracking behavior cannot represent the needed operation shape, or a
downstream workflow requires a provider SDK behind an optional plugin package.

## Scope

This component owns:

```text
remote artifact store capability requirements
URI scheme conventions
credential handling boundaries
checksum and manifest expectations
local staging and cache behavior
consistency and atomicity limitations
plugin backend model
testing strategy for remote-like stores
```

This component does not own:

```text
core artifact serialization formats
domain artifact semantics
remote run catalog services
cloud account provisioning
credential storage
network retry libraries as required dependencies
```

## Design Goals

The design should:

```text
preserve the ArtifactStore protocol
avoid hard cloud SDK dependencies in core
make local filesystem behavior the reference implementation
record enough metadata for reproducibility
handle eventual consistency explicitly
avoid hiding credential and network failures
support metadata-only workflows when payload access is unavailable
```

## Store Protocol

Remote stores should implement the same logical artifact-store protocol as the
local store.

Conceptual operations:

```text
put artifact payload and metadata
get artifact payload and metadata
check whether artifact identity exists
list artifacts for a run or logical namespace
verify checksum when supported
open a read stream
open a write transaction or staged writer
```

If the existing artifact design names these methods differently, remote stores
should follow the existing names rather than creating a parallel protocol.

## URI Schemes

Artifact locations should use explicit URI schemes.

Examples:

```text
file:///abs/path/to/artifacts
s3://bucket/prefix
gs://bucket/prefix
az://container/prefix
http://example.com/artifacts
https://example.com/artifacts
mlflow://tracking-server/experiment/run
```

Core should not treat every string with `://` as writable. Store capability
checks should say whether a URI is readable, writable, listable, and
transaction-capable.

## Store Configuration

Example config shape:

```yaml
artifact_store:
  kind: s3
  uri: s3://my-bucket/loom/artifacts
  options:
    region: us-east-1
```

Core should validate:

```text
kind is present
uri is present
kind can be resolved to a registered backend
options are structured
```

Backend-specific schema validation belongs to the backend plugin.

In Stage 15, backend plugins register into a caller-supplied
`ArtifactStoreBackendRegistry`. Generic plugin discovery may list entry point
metadata, but configured backend readiness comes from explicit registry/handler
objects and capability admission, not from import success alone.

## Credentials

Core `loom` should not store cloud credentials in run metadata.

Credential sources should be backend-specific and environment-native:

```text
environment variables
cloud SDK default credential chains
mounted credential files
workload identity
profile names
```

Run metadata may record non-secret credential context:

```text
backend kind
URI with secret components redacted
profile name if not secret
region
resolved account identity if backend exposes it safely
```

Preflight should redact secrets from diagnostics.

## Atomicity

Local filesystem stores can use atomic rename patterns. Many remote stores
cannot provide the same semantics.

Remote store backends must document their commit behavior:

```text
single-object atomic write
manifest-last commit
multipart upload commit
eventual consistency after write
no atomic overwrite support
```

The artifact layer should prefer manifest-last commits:

```text
upload payload objects
upload metadata objects
verify checksums where possible
write the final manifest or committed marker last
```

Readers should treat the final manifest as the commit point.

## Checksums

Remote stores should record checksums in `loom` artifact metadata even when the
backend has its own checksum or ETag.

Recommended fields:

```text
sha256
size_bytes
backend_checksum
backend_generation
verified_at
```

Backend ETags are not always content hashes, especially for multipart uploads.
They should be recorded as backend metadata, not used as a universal checksum.

## Consistency

Remote stores may be eventually consistent for listing or metadata reads.

Backends should declare:

```text
read-after-write behavior
listing consistency behavior
overwrite behavior
delete visibility behavior
```

Core planning should avoid relying on immediate list results after writes when
a direct manifest location is known.

## Staging

Remote writes often need local staging.

Staging may be used for:

```text
serializing an artifact before upload
computing checksums
compressing payloads
multipart uploads
manifest assembly
```

Staging paths should be recorded as temporary paths so reliability cleanup can
remove them if a run fails.

## Local Cache

A local cache may reduce repeated downloads.

Cache behavior should be explicit:

```text
disabled by default or clearly configured
keyed by artifact identity and checksum
safe under concurrent reads
never treated as authoritative without checksum validation
eligible for explicit cleanup
```

The cache should not change artifact identity.

## Read-Only Stores

Some remote stores may be read-only.

Read-only stores can support:

```text
external input artifacts
shared reference artifacts
metadata inspection
checksum verification
```

They cannot support:

```text
recording new run outputs
committing stage output manifests
cleanup of owned artifacts
```

Preflight should fail if a selected run needs writes to a read-only store.

## Remote Store Capabilities

Recommended capability model:

```python
@dataclass(frozen=True)
class ArtifactStoreCapabilities:
    readable: bool
    writable: bool
    listable: bool
    supports_atomic_commit: bool
    supports_checksum_verification: bool
    supports_delete: bool
```

Capabilities let preflight and reliability policies produce precise warnings.

## Plugin Model

Remote backends should be plugins.

Core can include:

```text
ArtifactStore protocol
local filesystem implementation
backend registry
configuration handoff
redaction helpers
payload operation request/result protocols
test fakes
```

Plugins can provide:

```text
S3ArtifactStore
GCSArtifactStore
AzureBlobArtifactStore
MLflowArtifactStore
backend-specific preflight checks
backend-specific config schemas
```

This avoids making every install pay for cloud SDK dependencies.

## Error Handling

Remote store errors should distinguish:

```text
authentication failure
authorization failure
not found
network timeout
checksum mismatch
partial upload
unsupported operation
backend throttling
```

The core error model should preserve backend details without exposing secrets.

Retry behavior for network failures belongs in backend implementation or a
future reliability policy. It should be visible in attempt metadata.

## Preflight Integration

Preflight may check:

```text
backend plugin is installed
URI parses
credentials are available
root or bucket exists when backend supports cheap checks
write permission when the run needs writes
read permission for known input artifacts
delete permission when cleanup policy requires it
```

Potentially expensive or network-heavy checks should be optional.

## Run Export Integration

Run export should support remote stores through:

```text
metadata-only export
payload export with explicit download
manifest entries that preserve remote URIs
checksum verification when requested
```

The default should avoid unexpectedly downloading large remote payloads.

Stage 16 exposes the explicit payload materialization path at the Python API
boundary: bundle export can request materialization only when the caller passes
`RunBundleExportOptions(materialize_payloads=True)` and a payload handler. CLI
bundle export remains metadata-only for remote refs because core has no
first-party backend registry or credential surface to resolve providers.

## Security

Remote store code must guard against:

```text
secret leakage in metadata
secret leakage in logs
path traversal when staging downloaded objects
writing outside configured prefixes
confusing external read-only artifacts with loom-owned outputs
```

Authored configs are trusted project code, but persisted run metadata may be
shared for review and should not contain credentials.

## Testing

Core tests should cover:

```text
URI parsing
capability model
redaction helpers
read-only capability failures
fake remote store put/get/list behavior
manifest-last commit behavior with a fake backend
checksum mismatch handling
preflight missing plugin
preflight unsupported operation
metadata-only export with remote URIs
explicit fake materialization in bundle export
not-implemented real-backend payload handles without optional SDK imports
```

Backend plugin tests may use cloud SDK fakes or optional integration tests, but
core tests should not require network access.

## Implementation Plan

1. Keep the local filesystem store as the reference implementation.
2. Confirm the artifact store protocol is backend-neutral.
3. Add capability reporting to artifact stores.
4. Add URI parsing and backend registry hooks.
5. Add a fake remote store for tests.
6. Add preflight checks for backend availability and capabilities.
7. Implement real remote backends as optional plugins.

## Deferred Work

Deferred remote store features:

```text
S3 backend
GCS backend
Azure Blob backend
MLflow backend
distributed artifact cache
credential refresh management
remote garbage collection
cross-region replication awareness
signed artifact manifests
```

Remote stores should remain P3 until local artifact semantics, checksums, and
run export behavior are stable.
