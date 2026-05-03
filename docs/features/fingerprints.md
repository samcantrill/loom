# `loom.fingerprints` Specification

## 1. Purpose

`loom.fingerprints` provides deterministic hashing helpers and shared digest
terminology for `loom`.

It exists so configuration, pipeline planning, artifacts, run stores, resume
logic, and provenance all use the same vocabulary when they talk about:

```text
checksums
fingerprints
hash algorithms
digest string formats
stable structured-data hashing
fingerprint record metadata
fingerprint comparison
```

The package should answer:

```text
How do we hash bytes?
How do we hash text?
How do we hash plain structured data deterministically?
What does a digest string look like?
How do we validate a stored digest string?
How do checksums differ from fingerprints?
What metadata should accompany a persisted fingerprint?
```

It should not answer:

```text
Should this stage be reused?
Which exact pipeline fields affect this stage's outputs?
Should a project include git dirty state in every fingerprint?
Should a missing artifact be an error or a rerun?
How should a stage resume from an internal checkpoint?
```

Those decisions belong to `loom.pipeline.planning.resume`, stage specs, project
code, and user-selected policy.

### 1.1 Alignment With `loom.md`

[loom.md](../loom.md) identifies fingerprints as the basis for resume logic and
provenance. This document narrows that into deterministic hashing utilities and
digest records; it deliberately leaves policy decisions about which stage fields
matter to pipeline planning, stage specs, and project code.

---

## 2. Core Position

`loom.fingerprints` sits above plain structured data serialization and below
pipeline resume policy.

Recommended dependency shape:

```text
ids / errors / serialization
        |
        v
fingerprints
        |
        v
artifacts / run stores / pipeline planning / provenance / cli
```

It may depend on:

```text
hashlib
hmac, if constant-time comparison is useful
re
typing
loom.serialization
loom.errors, when shared errors exist
```

It should not depend on:

```text
loom.pipeline.runner
loom.pipeline.executors
loom.pipeline.stores
loom.config
loom.io.sources
project packages
large optional dependencies
```

This keeps hash helpers cheap to import and safe to use in low-level objects,
subprocess workers, and tests.

---

## 3. Package Boundary

### 3.1 `loom.fingerprints`

Owns deterministic digest helpers and shared formats.

Responsibilities:

```text
hash bytes
hash text
hash plain data through canonical serialization
validate digest strings
parse digest strings
format digest strings
compare digest strings
define small fingerprint record helpers
provide algorithm allow-list and defaults
document checksum versus fingerprint terminology
```

### 3.2 `loom.serialization`

Owns canonical representation of structured data.

Responsibilities:

```text
convert objects to plain data
produce stable JSON text or bytes
reject non-deterministic values
provide path-aware serialization errors
```

`loom.fingerprints` should call serialization for structured data. It should not
implement an independent object-to-dict system.

### 3.3 `loom.artifacts`

Owns artifact references and artifact identity metadata.

Responsibilities:

```text
store artifact checksum fields
store artifact fingerprint fields when supplied
validate ArtifactRef shape
explain artifact checksum/fingerprint semantics
```

Artifacts may carry checksum and fingerprint strings. `loom.fingerprints` owns
their digest format and validation helpers.

### 3.4 `loom.pipeline.planning.resume`

Owns stage reuse decisions.

Responsibilities:

```text
choose stage fingerprint inputs
compare current and previous fingerprints
decide RUN, REUSE, STALE, BLOCKED, or SKIP
explain invalidation
apply strict checksum policy
handle selectors such as force-stage and from-stage
```

The resume planner can use `loom.fingerprints` helpers to hash selected inputs,
but it owns the policy for selecting those inputs.

### 3.5 `loom.pipeline.stores`

Owns persistence of fingerprint records.

Responsibilities:

```text
write stages/<stage>/fingerprint.json
read previous fingerprint records
write atomically
preserve attempt history when implemented
recover or reject corrupt fingerprint files
```

Stores should not decide semantic equivalence. They persist and return records.

### 3.6 `loom.io`

Owns byte access.

Responsibilities:

```text
open files and URIs
stream resource bytes
provide source metadata
optionally verify resource or artifact checksums
```

I/O may call byte hash helpers. `loom.fingerprints` should not open URIs.

### 3.7 `loom.provenance`

Owns provenance capture.

Responsibilities:

```text
code identity
environment identity
dependency versions
config provenance
stage execution metadata
```

Provenance data may become fingerprint inputs when pipeline policy chooses it.
`loom.fingerprints` should not directly inspect git or the environment.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
default sha256 digest generation
hash_bytes
hash_text
hash_plain_data
hash_mapping
digest string formatting
digest string validation
digest string parsing
constant-shape comparison helper
Checksum and Fingerprint type aliases
clear checksum versus fingerprint documentation
stable JSON based structured-data hashing
fingerprint record shape documentation
path-aware errors when structured data cannot be hashed
```

### 4.2 Should Support Soon

```text
file checksum helper for local regular files
streaming hash update helper
stage fingerprint record dataclass
fingerprint input summary helper
fingerprint diff helper for CLI explanations
algorithm policy object
tree checksum design for directories
```

### 4.3 Should Not Support in v0

```text
Python built-in hash()
pickle hashing
automatic hashing of arbitrary objects by repr()
automatic git inspection
automatic dependency scanning
automatic environment-variable capture
remote URI reading
artifact-store persistence
pipeline reuse decisions
domain-specific semantic hashing
array/video/model checkpoint hashing in loom core
content-defined chunking
cryptographic signing
```

The most important v0 rule:

```text
hash only explicit, deterministic inputs.
```

---

## 5. Terminology

### 5.1 Hash Algorithm

A hash algorithm transforms bytes into a fixed-size digest.

V0 default:

```text
sha256
```

Allowed algorithms should be explicit. Do not accept every algorithm exposed by
`hashlib` unless there is a concrete reason.

### 5.2 Digest

A digest is the raw output of a hash algorithm, usually represented as
hexadecimal text.

Example:

```text
2cf24dba5fb0a30e26e83b2ac5b9e29e...
```

### 5.3 Digest String

A digest string is an algorithm-prefixed digest.

Recommended format:

```text
sha256:<hex>
```

This makes persisted values self-describing.

### 5.4 Checksum

A checksum is a digest of stored bytes.

It answers:

```text
are these bytes the same as before?
did this artifact file change?
is this resource content still intact?
```

Example:

```text
sha256:9f86d081884c7d659a2feaa0c55ad015...
```

### 5.5 Fingerprint

A fingerprint is a digest of semantic production inputs.

It answers:

```text
would rerunning this stage under the documented policy produce equivalent outputs?
did relevant config, inputs, code identity, or environment identity change?
```

Fingerprints may include checksums as inputs, but they are not checksums.

### 5.6 Stage Fingerprint

A stage fingerprint is a fingerprint for one pipeline stage invocation.

Typical inputs:

```text
stage name
stage target import path
stage config
input artifact references
input artifact fingerprints
input artifact checksums
declared outputs
relevant runtime resources
relevant code provenance
loom contract version
project-provided extra fields
```

The exact list is policy-owned by pipeline planning and project configuration.

### 5.7 Fingerprint Policy

A fingerprint policy defines which semantic inputs are included and how they are
normalized before hashing.

Examples:

```text
include git commit
include git dirty state
include container image digest
include executor mode only when it affects outputs
exclude run directory
exclude wall-clock time
```

### 5.8 Fingerprint Record

A fingerprint record is the persisted document that stores a fingerprint plus
metadata needed for comparison and explanation.

It should include:

```text
fingerprint
algorithm
algorithm_version
policy_name or policy_version
inputs_summary
created_at
loom_version
```

---

## 6. Guiding Design Principles

### 6.1 Checksums and Fingerprints Are Different

Use this rule throughout the codebase:

```text
checksum:
  identity of stored bytes

fingerprint:
  identity of semantic production inputs
```

Example:

```text
A JSON artifact can be pretty-printed differently while representing the same
semantic data. Its checksum changes. A downstream stage fingerprint may or may
not change depending on whether the downstream policy uses checksum, semantic
artifact fingerprint, or parsed content identity.
```

### 6.2 Persist Algorithm Names

Every persisted digest should identify its algorithm.

Good:

```text
sha256:abc123...
```

Bad:

```text
abc123...
```

Reason:

```text
algorithm changes should not silently compare old and new values
debugging is easier when the digest format is self-describing
future algorithms remain possible
```

### 6.3 Use Stable Serialization for Structured Data

Do not hash Python object representations.

Bad:

```python
hash_text(repr(stage_config))
```

Good:

```python
hash_plain_data(stage_config)
```

Structured data should be converted through `loom.serialization` and canonical
JSON before hashing.

### 6.4 No Hidden Inputs

Fingerprint input selection should be explicit.

Avoid helpers that secretly include:

```text
current time
hostname
process ID
temporary path
environment variables
git status
installed packages
```

Those values can be included by policy when they affect outputs.

### 6.5 Be Conservative About Reuse

If a fingerprint cannot be computed or validated, resume should not reuse prior
outputs as if everything matched.

The fingerprints module should fail clearly. The resume planner decides whether
that failure becomes a rerun, stale status, or user-facing error.

### 6.6 Keep Hash Helpers Pure

Most helpers should be deterministic and side-effect free:

```text
input bytes -> digest string
input text -> digest string
input plain data -> digest string
```

File and stream helpers are useful but should remain explicit because they touch
external state.

### 6.7 Make Explanations Possible

Fingerprint records should preserve enough structured input summary for `loom
plan --resume --explain` to show why a stage reran.

Do not store only an opaque hash when a small summary can be retained.

---

## 7. Public API

### 7.1 Recommended Imports

```python
from loom.fingerprints import (
    Checksum,
    Fingerprint,
    Digest,
    hash_bytes,
    hash_text,
    hash_plain_data,
    hash_mapping,
    parse_digest,
    validate_digest,
    compare_digests,
    format_digest,
)
```

### 7.2 Type Aliases

Recommended aliases:

```python
Digest = str
Checksum = str
Fingerprint = str
HashAlgorithm = str
```

Start with aliases rather than wrapper classes. Wrappers can be added later if
confusion becomes common.

### 7.3 Optional Dataclasses

Once persisted fingerprint records are implemented, add:

```python
@dataclass(frozen=True, slots=True)
class FingerprintRecord:
    fingerprint: Fingerprint
    algorithm: str
    algorithm_version: int
    policy: str
    policy_version: int
    inputs_summary: Mapping[str, PlainData]
    created_at: str
    loom_version: str | None = None
```

This dataclass should remain generic. Pipeline-specific fields can live in
pipeline planning if needed.

---

## 8. Digest Format

### 8.1 Standard Format

Recommended digest string:

```text
algorithm:hex
```

Examples:

```text
sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e...
blake2b:786a02f742015903c6c6fd852552d272...
```

### 8.2 Default Algorithm

V0 default:

```text
sha256
```

Reasons:

```text
standard library support
widely understood
stable across platforms
adequate for integrity and reproducibility
```

### 8.3 Algorithm Allow-List

Recommended v0 allow-list:

```text
sha256
```

Possible later additions:

```text
sha512
blake2b
blake2s
```

Avoid weak or surprising algorithms unless there is a specific compatibility
need.

### 8.4 Hex Case

Persist lowercase hex.

Validation can accept uppercase hex and normalize it to lowercase, or reject it
strictly. Recommended v0:

```text
accept lowercase only for persisted loom-generated values
provide normalize_digest for user-supplied values if needed
```

### 8.5 Kind Prefixes

Avoid encoding policy kind into the digest string unless necessary.

Preferred:

```json
{
  "kind": "loom.stage_fingerprint",
  "fingerprint": "sha256:abc123...",
  "policy": "stage.v1"
}
```

Less preferred:

```text
stage-v1:sha256:abc123...
```

Reason:

```text
digest strings stay reusable
policy and document metadata stay structured
```

---

## 9. Hash Helpers

### 9.1 `hash_bytes`

Representative signature:

```python
def hash_bytes(data: bytes, *, algorithm: str = "sha256") -> Digest: ...
```

Behavior:

```text
validate algorithm
hash data with hashlib
return algorithm-prefixed lowercase hex digest
```

Example:

```python
hash_bytes(b"hello")
```

Result:

```text
sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e...
```

### 9.2 `hash_text`

Representative signature:

```python
def hash_text(
    text: str,
    *,
    algorithm: str = "sha256",
    encoding: str = "utf-8",
) -> Digest: ...
```

Behavior:

```text
encode text using UTF-8 by default
delegate to hash_bytes
return algorithm-prefixed digest
```

Do not use platform default encoding.

### 9.3 `hash_plain_data`

Representative signature:

```python
def hash_plain_data(value: object, *, algorithm: str = "sha256") -> Digest: ...
```

Behavior:

```text
convert value to plain data through loom.serialization
serialize with stable_json_dumps
encode as UTF-8
hash bytes
```

This is the main helper for stage fingerprint inputs and structured metadata.

### 9.4 `hash_mapping`

Representative signature:

```python
def hash_mapping(
    mapping: Mapping[str, object],
    *,
    algorithm: str = "sha256",
) -> Digest: ...
```

`hash_mapping` can be a convenience wrapper around `hash_plain_data` that checks
the top-level input is a mapping.

### 9.5 `hash_stream`

Future helper:

```python
def hash_stream(
    stream: BinaryIO,
    *,
    algorithm: str = "sha256",
    chunk_size: int = 1024 * 1024,
) -> Digest: ...
```

Use cases:

```text
large local artifact checksum
resource checksum verification
streaming remote data later
```

This helper touches external state through the stream supplied by the caller, but
it does not open files itself.

### 9.6 `hash_file`

Future helper:

```python
def hash_file(path: str | Path, *, algorithm: str = "sha256") -> Checksum: ...
```

Boundary note:

```text
hash_file can be convenient for local artifact stores,
but I/O still owns URI opening and remote source behavior.
```

If added, it should be documented as local-filesystem-only.

---

## 10. Digest Validation and Parsing

### 10.1 `validate_digest`

Representative signature:

```python
def validate_digest(value: str, *, algorithms: Container[str] | None = None) -> str: ...
```

Behavior:

```text
require string
require algorithm prefix
require supported algorithm
require hex digest
require expected digest length for known algorithms
return normalized digest string
```

### 10.2 `parse_digest`

Representative signature:

```python
@dataclass(frozen=True, slots=True)
class ParsedDigest:
    algorithm: str
    hex: str

def parse_digest(value: str) -> ParsedDigest: ...
```

Use cases:

```text
validation
error messages
algorithm migration
display in CLI
```

### 10.3 `format_digest`

Representative signature:

```python
def format_digest(algorithm: str, hexdigest: str) -> Digest: ...
```

Behavior:

```text
validate algorithm
validate hex
normalize to lowercase
return "algorithm:hex"
```

### 10.4 `compare_digests`

Representative signature:

```python
def compare_digests(left: str | None, right: str | None) -> bool: ...
```

Behavior:

```text
return False if either value is None
validate both values
compare normalized strings
```

Using `hmac.compare_digest` is reasonable, though this is not primarily a
security boundary.

### 10.5 Invalid Digest Errors

Invalid digest errors should include:

```text
value, redacted or truncated if very long
expected format
algorithm
path, when supplied by caller
```

Example:

```text
Invalid digest at artifact.checksum.
Expected format "sha256:<64 lowercase hex characters>".
Actual value: "sha256:not-hex".
```

---

## 11. Structured Data Hashing

### 11.1 Canonical Flow

Recommended flow:

```text
object
  -> loom.serialization.to_plain_data
  -> loom.serialization.stable_json_dumps
  -> UTF-8 bytes
  -> hash_bytes
```

### 11.2 Canonical JSON Policy

The serialization layer owns the exact JSON behavior. Fingerprints rely on:

```text
mapping keys sorted
compact separators
finite floats only
UTF-8 encoding
no Python object repr fallback
```

### 11.3 Floats

V0 can use Python's standard JSON finite-float representation.

Do not silently round floats inside fingerprint helpers.

If stricter numeric behavior becomes necessary, add an explicit policy:

```text
float precision policy
Decimal-as-string policy
array checksum policy
numeric schema-specific normalization
```

Changing float behavior changes fingerprints and should require a policy/version
change.

### 11.4 Paths and URIs

Fingerprint helpers should not normalize paths by themselves.

Callers should decide whether to include:

```text
relative path
absolute path
file URI
logical artifact ID
content checksum
```

Reason:

```text
path identity can be semantic in some contexts and noise in others
```

### 11.5 Non-Plain Values

Non-plain values should fail through serialization errors.

Rejected unless explicitly converted before hashing:

```text
Path
datetime
bytes inside structured data
set
callable
arbitrary object without to_dict
NaN
Infinity
```

---

## 12. Checksums

### 12.1 Checksum Scope

Checksums identify stored bytes.

Examples:

```text
local artifact file bytes
resource file bytes
encoded JSON artifact bytes
raw binary artifact bytes
```

### 12.2 Checksum Ownership

The digest helpers belong in `loom.fingerprints`.

The decision to compute a checksum belongs to the component with access to bytes:

```text
LocalArtifactStore computes checksums for files it writes.
LocalFileSystemSource can compute checksums for local resources when requested.
Resume strict mode can request checksum verification.
Project code can supply checksums for external resources.
```

### 12.3 Directories

Do not invent directory checksums in v0.

Directory identity needs a documented tree policy:

```text
which files are included
how names are normalized
how symlinks are handled
how permissions are handled
whether mtimes are ignored
how empty directories are represented
```

Until then, directory artifacts may omit checksums or provide project-supplied
checksums.

### 12.4 Compressed Files

Compressed files illustrate the checksum/fingerprint split.

Example:

```text
same logical table
different gzip timestamp in header
different checksum
possibly same semantic fingerprint
```

Do not treat checksum equality as the only form of semantic equality.

---

## 13. Fingerprints

### 13.1 Fingerprint Scope

Fingerprints identify semantic production inputs.

For pipeline stages, the question is:

```text
Would this stage invocation produce equivalent outputs under the documented
policy?
```

### 13.2 Recommended Stage Inputs

Pipeline planning should consider:

```text
stage name
stage target import path
stage constructor identity when available
stage config
declared inputs
input artifact refs
input artifact fingerprints when available
input artifact checksums when available
declared outputs
selected resolved config subtree
selected runtime resources that affect outputs
relevant code provenance
loom version or pipeline contract version
project-provided extra fingerprint fields
```

### 13.3 Values to Avoid

Avoid noisy values unless explicitly output-affecting:

```text
wall-clock timestamp
run ID
run directory
temporary directory
log path
hostname
process ID
random seed generated after planning
executor job ID
SLURM allocation ID
```

### 13.4 Resource References

When a stage consumes a `ResourceRef`, policy can choose among:

```text
resource URI
resource type
codec key
resource schema version
resource checksum
resource metadata
```

If a resource has no checksum, a URI-only fingerprint may miss content changes.
This is acceptable only when the policy documents that limitation or the source
is immutable by convention.

### 13.5 Artifact References

When a stage consumes an `ArtifactRef`, policy should usually include:

```text
artifact ID
artifact type
artifact URI or logical ID
artifact fingerprint when present
artifact checksum when present
artifact schema version
producer stage identity when present
```

Prefer upstream artifact fingerprint when it captures semantic production
identity. Use checksum for strict integrity validation or when semantic
fingerprint is unavailable.

### 13.6 Runtime Resources

Runtime fields should be included only when they can affect outputs.
V0 excludes `StageSpec.resources` from semantic stage fingerprints by default;
future runtime/resource phases may add explicit opt-in fields after typed
resource semantics exist.

Examples usually included:

```text
random seed
container image digest
precision mode
device type when numerical outputs differ
thread count only when algorithms are not deterministic across counts
```

Examples usually excluded:

```text
memory request
walltime request
queue name
log directory
executor job name
```

### 13.7 User Extensions

Stages or specs should allow explicit extra fingerprint inputs.

Example:

```yaml
pipeline:
  stages:
    - name: train
      fingerprint:
        extra:
          algorithm_family: deterministic-v2
          preprocessing_contract: project-preprocess-v4
```

These values must be plain-data compatible.

---

## 14. Fingerprint Records

### 14.1 Persisted Shape

Recommended `fingerprint.json` shape:

```json
{
  "schema_version": 1,
  "kind": "loom.stage_fingerprint",
  "stage": "build_manifest",
  "fingerprint": "sha256:abc123...",
  "algorithm": "sha256",
  "algorithm_version": 1,
  "policy": "loom.stage.v1",
  "policy_version": 1,
  "inputs_summary": {},
  "created_at": "2026-05-02T00:00:00Z",
  "loom_version": "0.1.0"
}
```

### 14.2 Fingerprint Value

The `fingerprint` field should be the digest string generated from the canonical
input payload.

It should not include:

```text
created_at
run ID
attempt number
fingerprint file path
```

unless those values genuinely affect outputs.

### 14.3 Algorithm Version

`algorithm` is the hash function.

`algorithm_version` is the implementation policy version for hashing mechanics.

Examples that may require algorithm version changes:

```text
canonical serialization behavior changes
float normalization policy changes
digest format changes
input payload wrapper changes in a way that affects bytes
```

### 14.4 Policy Version

`policy` and `policy_version` describe which semantic fields were included.

Examples that may require policy version changes:

```text
adding git dirty state to stage fingerprints
removing run-specific paths
switching from artifact checksum to artifact fingerprint
adding container image digest
changing path normalization
```

### 14.5 Input Payload

The full canonical input payload can be large.

Recommended v0:

```text
persist inputs_summary
optionally persist inputs_full for debugging if not too large
hash the exact payload before summarizing
```

The summary should be enough to explain common reruns.

### 14.6 Redaction

Fingerprint input summaries should avoid leaking secrets.

Policy:

```text
config redaction owns which paths are secret
fingerprint hashing may include secret values if they affect outputs
persisted summaries should use redacted representations
```

This creates a subtle split:

```text
hash payload:
  may include full semantic values

persisted explanation summary:
  should be redacted when needed
```

If this is too risky for v0, require callers to supply already-redacted
fingerprint input summaries.

---

## 15. Fingerprint Payloads

### 15.1 Payload Wrapper

Hash a wrapper object, not a bare config subtree.

Recommended:

```python
payload = {
    "kind": "loom.stage_fingerprint_input",
    "schema_version": 1,
    "policy": "loom.stage.v1",
    "stage": {
        "name": "build_manifest",
        "target": "project.stages.BuildManifest",
    },
    "config": {...},
    "inputs": {...},
    "outputs": {...},
    "runtime": {...},
}
```

Reason:

```text
wrappers prevent accidental collisions between different document kinds
policy is explicit
future schema changes are clearer
```

### 15.2 Namespacing

Use stable keys:

```text
kind
schema_version
policy
stage
config
inputs
outputs
runtime
provenance
extra
```

Avoid unstructured top-level bags that make future diffs hard.

### 15.3 Minimal Payload for Simple Stage

Example:

```python
{
    "kind": "loom.stage_fingerprint_input",
    "schema_version": 1,
    "policy": "loom.stage.v1",
    "stage": {
        "name": "summarize",
        "target": "project.stages.SummarizeStage",
    },
    "config": {
        "max_items": 100,
    },
    "inputs": {
        "manifest": {
            "artifact_id": "build_manifest/output",
            "fingerprint": "sha256:111...",
            "checksum": "sha256:222...",
        }
    },
    "outputs": {
        "summary": {
            "artifact_type": "json",
            "codec_key": "json.v1",
        }
    },
    "runtime": {},
    "extra": {},
}
```

### 15.4 Hashing the Payload

Recommended:

```python
fingerprint = hash_mapping(payload)
```

`hash_mapping` delegates to serialization and stable JSON.

---

## 16. Comparison Semantics

### 16.1 Digest Equality

Two fingerprints match when:

```text
both are present
both validate
normalized digest strings are equal
algorithm and policy metadata are compatible
```

Digest equality alone is not enough if policy metadata changed.

### 16.2 Missing Fingerprint

A missing fingerprint should not compare equal.

Resume policy can treat this as:

```text
RUN
STALE
ERROR in strict modes
```

### 16.3 Invalid Fingerprint

An invalid persisted fingerprint should fail validation.

The resume planner can decide whether to:

```text
rerun stage
mark prior state corrupt
raise an error
```

### 16.4 Algorithm Mismatch

If current and prior fingerprints use different algorithms:

```text
do not silently compare as equal
```

Recommended behavior:

```text
mark as stale with reason "fingerprint algorithm changed"
```

### 16.5 Policy Mismatch

If policy or policy version changed:

```text
do not silently compare as equal
```

Recommended behavior:

```text
mark as stale with reason "fingerprint policy changed"
```

---

## 17. Fingerprint Diffs and Explanations

### 17.1 Purpose

Users need to understand why a stage reran.

The fingerprints module can provide generic diff helpers for plain-data
summaries, or the resume planner can own diffing directly.

### 17.2 Recommended V0

Keep diffing in pipeline planning initially.

`loom.fingerprints` can provide:

```text
validate fingerprint records
normalize summary mappings
small compare result type, if useful
```

### 17.3 Explanation Inputs

Useful explanation fields:

```text
stage target changed
stage config key changed
input artifact fingerprint changed
input artifact checksum changed
runtime setting changed
policy version changed
previous fingerprint missing
```

### 17.4 Redacted Summaries

CLI explanations should use persisted summaries, not raw secret-bearing hash
payloads.

If summaries are absent, the CLI can still explain high-level reasons:

```text
fingerprint mismatch
previous fingerprint: sha256:...
current fingerprint: sha256:...
```

---

## 18. Relationship to Resume

### 18.1 Resume Flow

Recommended flow:

```text
planner validates current pipeline
planner builds current fingerprint payload for each stage
planner calls hash_mapping(payload)
planner reads prior fingerprint record from RunStore
planner compares digest plus policy metadata
planner checks required artifacts exist
planner optionally verifies checksums in strict mode
planner chooses action and reason
```

### 18.2 Fingerprints Module Role

`loom.fingerprints` provides:

```text
hashing
validation
formatting
comparison primitives
record conversion helpers
```

### 18.3 Resume Module Role

`loom.pipeline.planning.resume` provides:

```text
which fields to include
how to handle missing fields
how to propagate upstream changes
how selectors affect reuse
how strict checksum mode behaves
how explanations are produced
```

### 18.4 Stage-Internal Resume

Stage-internal resume is separate.

Example:

```text
pipeline fingerprint matches current stage invocation
stage finds checkpoint in its work directory
stage resumes training internally
stage still writes outputs compatible with current fingerprint
```

`loom.fingerprints` does not load checkpoints or decide internal resume
behavior.

---

## 19. Relationship to Artifacts

### 19.1 Artifact Checksums

Artifact checksums identify stored artifact bytes.

They are useful for:

```text
corruption detection
strict resume validation
debugging artifact replacement
artifact store integrity checks
```

### 19.2 Artifact Fingerprints

Artifact fingerprints identify semantic production identity when known.

They are useful for:

```text
downstream stage fingerprint inputs
lineage tracking
semantic reuse
provenance inspection
```

### 19.3 ArtifactRef Fields

`ArtifactRef` may include both:

```text
checksum
fingerprint
```

They should be validated with the same digest format helpers but interpreted
differently.

### 19.4 Registering External Artifacts

When registering an external artifact, project code may supply:

```text
checksum if bytes are known
fingerprint if semantic production identity is known
metadata explaining source
```

`loom` should not fabricate semantic fingerprints for external artifacts without
explicit inputs.

---

## 20. Relationship to Provenance

### 20.1 Provenance as Fingerprint Input

Provenance can affect fingerprints when it changes outputs.

Examples:

```text
git commit
container image digest
dependency lockfile digest
project code version
data source version
```

### 20.2 Provenance as Explanation

Even when provenance is not included in a fingerprint, it can help explain a
run.

Example:

```text
same stage fingerprint
different host
same outputs reused because host is not part of policy
```

### 20.3 Ownership

`loom.provenance` captures facts.

`loom.pipeline.planning.resume` chooses which facts become fingerprint inputs.

`loom.fingerprints` hashes the selected facts.

---

## 21. Relationship to Config

### 21.1 Resolved Config

Stage fingerprints should usually use resolved config values, not raw authored
config.

Reason:

```text
overlays, CLI overrides, interpolation, and recipes all affect the actual stage
invocation
```

### 21.2 Selected Config Subtrees

Do not automatically hash the entire resolved config for every stage.

Recommended:

```text
hash the stage spec
hash relevant stage config
hash pipeline-level defaults that affect this stage
hash selected global config values declared as dependencies
```

Hashing the whole config can cause noisy reruns when unrelated settings change.

### 21.3 Redacted Config

Fingerprint payloads may need full values if secrets affect outputs.

Persisted summaries should be redacted.

Config redaction owns redaction policy. Fingerprint code should accept already
prepared payloads and summaries.

---

## 22. Relationship to I/O

### 22.1 Byte Access

`loom.fingerprints` can hash bytes supplied by callers.

It should not open:

```text
file paths
file URIs
s3 URIs
http URLs
artifact store paths
```

unless a local-only convenience helper is explicitly added.

### 22.2 Local File Helper

If `hash_file` is added:

```text
document it as local path only
use chunked reading
return checksum digest string
do not resolve non-file URI schemes
```

Remote checksum computation belongs to I/O sources or artifact stores.

### 22.3 Streaming

For large files, prefer streaming:

```text
source.open(uri, "rb")
hash_stream(stream)
```

This keeps memory bounded and source-specific behavior outside the fingerprints
module.

---

## 23. Error Model

### 23.1 Error Types

Recommended hierarchy:

```python
class FingerprintError(LoomError): ...
class UnsupportedHashAlgorithmError(FingerprintError): ...
class InvalidDigestError(FingerprintError): ...
class FingerprintInputError(FingerprintError): ...
class FingerprintComparisonError(FingerprintError): ...
```

If `LoomError` does not exist yet, start with `Exception` and move under the
shared base later.

### 23.2 Error Context

Errors should include:

```text
path
algorithm
digest
expected format
operation
```

Example:

```text
Could not hash fingerprint input at $.config.created_at.
Reason: datetime is not plain data.
```

### 23.3 Serialization Errors

When structured input cannot be converted to plain data, preserve the original
serialization error and wrap only if doing so adds fingerprint context.

Use exception chaining:

```python
raise FingerprintInputError(...) from exc
```

### 23.4 Unsupported Algorithm

Unsupported algorithm errors should list supported algorithms.

Example:

```text
Unsupported hash algorithm "md5".
Supported algorithms: sha256.
```

---

## 24. Examples

### 24.1 Hashing Bytes

```python
from loom.fingerprints import hash_bytes

checksum = hash_bytes(b"hello")
```

Result:

```text
sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e...
```

### 24.2 Hashing Text

```python
from loom.fingerprints import hash_text

digest = hash_text("stage output\n")
```

The text is encoded as UTF-8 before hashing.

### 24.3 Hashing Structured Data

```python
from loom.fingerprints import hash_mapping

payload = {
    "stage": "build_manifest",
    "config": {"pattern": "*.json"},
    "inputs": {},
}

fingerprint = hash_mapping(payload)
```

The mapping is serialized deterministically before hashing.

### 24.4 Stage Fingerprint Payload

```python
payload = {
    "kind": "loom.stage_fingerprint_input",
    "schema_version": 1,
    "policy": "loom.stage.v1",
    "stage": {
        "name": "evaluate",
        "target": "project.stages.Evaluate",
    },
    "config": {
        "metrics": ["accuracy", "loss"],
    },
    "inputs": {
        "predictions": {
            "artifact_id": "predict/predictions",
            "fingerprint": "sha256:111...",
            "checksum": "sha256:222...",
        }
    },
    "outputs": {
        "metrics": {
            "artifact_type": "metrics",
            "codec_key": "json.v1",
        }
    },
    "runtime": {},
    "extra": {},
}

fingerprint = hash_mapping(payload)
```

### 24.5 Validating Artifact Checksum

```python
from loom.fingerprints import validate_digest

checksum = validate_digest(ref.checksum)
```

The caller still decides whether checksum mismatch means rerun, warning, or
error.

---

## 25. Testing Strategy

### 25.1 Hash Helper Tests

Test:

```text
hash_bytes returns algorithm-prefixed digest
hash_text uses UTF-8
hash_text delegates deterministically
hash_plain_data sorts mapping keys through serialization
hash_mapping rejects non-mapping top-level input
same structured data with different dict insertion order hashes equally
different structured data hashes differently
```

### 25.2 Digest Format Tests

Test:

```text
valid sha256 digest accepted
missing algorithm rejected
unknown algorithm rejected
non-hex digest rejected
wrong digest length rejected
uppercase behavior matches policy
format_digest normalizes or rejects consistently
parse_digest returns algorithm and hex
```

### 25.3 Comparison Tests

Test:

```text
matching digests compare true
different digests compare false
None compares false
invalid digest raises or returns false according to documented policy
algorithm mismatch compares false
```

### 25.4 Structured Input Tests

Test:

```text
Path rejected unless caller converts it
datetime rejected unless caller converts it
NaN rejected
Infinity rejected
set rejected
object repr is not used
path-aware serialization errors are preserved
```

### 25.5 Fingerprint Record Tests

Test:

```text
record to_dict/from_dict
missing fingerprint rejected
invalid fingerprint rejected
missing policy version rejected
inputs_summary must be plain data
created_at is string
unknown fields rejected by default
```

### 25.6 Integration Tests

Test:

```text
pipeline planning can hash stage payload
resume detects fingerprint match
resume detects fingerprint mismatch
artifact checksum validation uses digest helper
run store persists and reads fingerprint record
CLI explanation can show summary fields
```

### 25.7 Import Boundary Tests

Test:

```text
import loom.fingerprints does not import loom.pipeline
import loom.fingerprints does not import loom.config
import loom.fingerprints does not import loom.io
import loom.refs does not import pipeline through fingerprints
```

---

## 26. Implementation Plan

### 26.1 Phase 1: Basic Types and Errors

Create or update:

```text
src/loom/fingerprints.py
```

Implement:

```text
Digest
Checksum
Fingerprint
FingerprintError
UnsupportedHashAlgorithmError
InvalidDigestError
```

### 26.2 Phase 2: Hash Helpers

Implement:

```text
hash_bytes
hash_text
hash_plain_data
hash_mapping
```

Use:

```text
hashlib
loom.serialization.stable_json_dumps
```

### 26.3 Phase 3: Digest Parsing and Validation

Implement:

```text
ParsedDigest
format_digest
parse_digest
validate_digest
compare_digests
```

Keep the v0 algorithm allow-list to `sha256`.

### 26.4 Phase 4: Checksum Integration

Update core/artifact validation to use digest helpers for:

```text
ResourceRef.checksum
ArtifactRef.checksum
ArtifactRef.fingerprint
```

Do not make checksum fields required.

### 26.5 Phase 5: Fingerprint Record

Add a small record type if needed by run stores:

```text
FingerprintRecord
FingerprintRecord.to_dict
FingerprintRecord.from_dict
```

Alternatively, define this under pipeline planning if it remains stage-specific.

### 26.6 Phase 6: Resume Integration

Update resume planning to:

```text
build explicit stage fingerprint payload
hash payload with hash_mapping
persist record through RunStore
compare current and prior records
explain mismatch reasons
```

### 26.7 Phase 7: CLI Explanation

Expose summary data to:

```text
loom plan --resume
loom plan --resume --explain STAGE
loom status
```

Keep CLI logic thin. It should display planner results, not compute fingerprints
itself.

---

## 27. Open Questions

### 27.1 Should `hash_file` Live Here or in I/O?

Recommended answer:

```text
put byte hashing primitives here;
put URI/file access in I/O or artifact stores.
```

A local-only `hash_file` convenience helper is acceptable if clearly documented.

### 27.2 Should FingerprintRecord Be Top-Level?

Recommended v0 answer:

```text
start with generic digest helpers;
add FingerprintRecord where the first persisted use appears.
```

If only pipeline stages use it, `loom.pipeline.planning` may own the stage record.
If artifacts and provenance also use it, a top-level generic record makes sense.

### 27.3 Should Full Fingerprint Inputs Be Persisted?

Recommended answer:

```text
persist summaries by default;
make full payload persistence optional.
```

Full payloads are useful for debugging but may be large or contain sensitive
values.

### 27.4 Should md5 Be Supported for Compatibility?

Recommended answer:

```text
no in v0
```

Use `sha256` unless a concrete external compatibility need appears.

### 27.5 Should Checksums Use Same Validation as Fingerprints?

Recommended answer:

```text
yes for digest string syntax;
no for semantic interpretation.
```

Both can use `validate_digest`. Callers decide whether the digest is a checksum
or fingerprint.

---

## 28. Summary

`loom.fingerprints` should be a small, deterministic, domain-neutral hashing
layer.

Its main jobs are:

```text
hash bytes
hash text
hash plain structured data
format and validate digest strings
compare digests safely
keep checksum and fingerprint terminology clear
provide optional record helpers for persisted fingerprints
```

It should not become:

```text
a resume planner
an artifact store
a URI reader
a provenance scanner
a config redactor
a domain-specific semantic equivalence engine
```

Keeping this boundary sharp lets pipeline planning own reuse policy, artifact
stores own byte integrity, serialization own stable representation, and project
code own domain semantics.
