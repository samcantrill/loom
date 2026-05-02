# Scalable Source Directory and Architecture Plan for `corelib` / `loom`

This document describes a scalable source-tree design for a generic experiment infrastructure package. The package name `loom` is used throughout for concreteness. If the project keeps the name `corelib`, substitute `corelib` for `loom` in all import paths and directory names.

The central design boundary is:

```text
loom/corelib knows how to describe, configure, construct, run, resume, and track artifact-based workflows.

Domain packages know what the workflows actually do.
```

For the Remote Phys project, that means:

```text
rphys-lib may depend on loom/corelib.
loom/corelib must never depend on rphys-lib.
```

If the generic infrastructure package imports `rphys`, the boundary has failed.

This document expands the proposed package structure with a stronger emphasis on long-term extensibility. It describes the purpose of each file, why it exists, what should go inside it, what should stay out of it, and the design decisions that keep the project scalable.

---

## 1. Design Principles

### 1.1 Keep the public vocabulary near the top level

The foundational types should be easy to import and easy to recognize:

```python
from loom.refs import ResourceRef
from loom.records import Record
from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_mapping
```

These concepts are not internal implementation details. They are the public vocabulary used by configuration, pipeline stages, artifact stores, downstream packages, tests, and documentation.

Therefore, do not hide them under a generic directory such as:

```python
from loom.primitives.refs import ResourceRef
```

A `primitives/` directory reflects an internal layering model, not the way users think about the package.

### 1.2 Split subsystems that will grow multiple implementations

A file should become a package when it is expected to grow multiple implementations, internal helpers, protocols, registries, and errors.

Examples that deserve subpackages:

```text
io/
config/recipes/
config/instantiate/
pipeline/executors/
pipeline/stores/
pipeline/sweep/
pipeline/planning/
pipeline/execution/
```

Examples that should usually remain top-level modules initially:

```text
refs.py
records.py
artifacts.py
fingerprints.py
provenance.py
errors.py
```

### 1.3 Serialization is not I/O

Use this boundary:

```text
serialization = Python objects <-> plain structured data
io            = bytes, files, URIs, sources, codecs, external storage
```

Serialization should not know where bytes live. I/O should not own every object-to-dict conversion. Codecs are the bridge between the two.

Recommended dependency shape:

```text
refs / records / artifacts / provenance
        ↓
serialization

io / config / pipeline / stores
        ↓
serialization
```

Avoid:

```text
refs / records / artifacts / provenance
        ↓
io.serialization
```

That would make `io` too foundational and would force unrelated layers to depend on the I/O subsystem.

### 1.4 Use explicit names over clever names

Use `serialization`, not `serde`, for the public module/package name.

`serde` is concise, but it is less Pythonic and less obvious to new contributors. This project already has enough conceptual load: recipes, targets, artifacts, stores, fingerprints, provenance, stages, sweeps, executors, and run directories. Prefer names that explain themselves.

### 1.5 Keep the CLI thin

The CLI should call Python APIs. It should not contain business logic.

Good:

```text
cli/run.py -> calls loom.pipeline.execution.PipelineRunner
cli/plan.py -> calls loom.pipeline.planning.PipelinePlanner
```

Bad:

```text
cli/run.py directly validates DAGs, writes status files, instantiates targets, and handles resume logic.
```

### 1.6 Make the system extensible through protocols and registries, not inheritance-heavy frameworks

The package should favor structural interfaces:

```python
class Stage(Protocol): ...
class Codec(Protocol): ...
class DataSource(Protocol): ...
class ArtifactStore(Protocol): ...
class RunStore(Protocol): ...
```

Downstream packages should be able to provide arbitrary classes through `_target_` construction without subclassing a specific base class.

Use registries where names need to resolve into implementations:

```text
_recipe_ name -> recipe class
codec_key     -> codec implementation
source scheme -> data source implementation
executor name -> executor implementation, later
```

### 1.7 Preserve stable public imports even when files become packages

Start small, but design for refactors.

For example, `records.py` can later become:

```text
records/
  __init__.py
  base.py
  manifest.py
  views.py
  filters.py
```

As long as this remains true:

```python
from loom.records import Record, Manifest, ManifestView
```

A scalable source tree is not just about folders. It is also about protecting downstream users from internal refactors.

---

## 2. Recommended Scalable Source Tree

This is the recommended long-term layout. Not every file needs to be fully implemented in v0. Empty or placeholder modules should be avoided unless they clarify the public API or are needed by tests. The structure is a target architecture.

```text
src/loom/
  __init__.py
  py.typed

  ids.py
  refs.py
  records.py
  artifacts.py
  provenance.py
  fingerprints.py
  protocols.py
  errors.py
  timestamps.py

  serialization/
    __init__.py
    plain.py
    dataclasses.py
    json.py
    yaml.py
    schema.py
    errors.py

  io/
    __init__.py
    uris.py
    errors.py

    sources/
      __init__.py
      base.py
      local.py
      registry.py
      errors.py

    codecs/
      __init__.py
      base.py
      json_codec.py
      text_codec.py
      bytes_codec.py
      registry.py
      errors.py

  config/
    __init__.py
    api.py
    load.py
    compose.py
    merge.py
    overrides.py
    interpolation.py
    validation.py
    redaction.py
    provenance.py
    errors.py

    recipes/
      __init__.py
      base.py
      catalog.py
      expansion.py
      errors.py

    instantiate/
      __init__.py
      targets.py
      recursive.py
      injection.py
      errors.py

  pipeline/
    __init__.py
    specs.py
    stage.py
    context.py
    status.py
    validation.py
    selectors.py
    resources.py
    runtime.py
    errors.py

    graph/
      __init__.py
      dag.py
      topology.py
      bindings.py

    planning/
      __init__.py
      plan.py
      planner.py
      resume.py
      invalidation.py

    execution/
      __init__.py
      runner.py
      lifecycle.py
      atomic.py
      logs.py

    executors/
      __init__.py
      base.py
      local.py
      subprocess.py
      slurm.py
      registry.py
      errors.py

    stores/
      __init__.py
      artifact_store.py
      run_store.py
      indexes.py
      local_artifacts.py
      local_runs.py
      atomic.py
      locking.py
      errors.py

    sweep/
      __init__.py
      spec.py
      grid.py
      manual.py
      trials.py
      runner.py
      errors.py

  plugins/
    __init__.py
    entrypoints.py
    errors.py

  cli/
    __init__.py
    main.py
    validate.py
    plan.py
    run.py
    stage.py
    sweep.py
```

---

## 3. Top-Level Package Files

### 3.1 `src/loom/__init__.py`

Purpose: define the smallest convenient public surface of the package.

Recommended contents:

```python
from loom.refs import ResourceRef
from loom.records import Record, InMemoryManifest, ManifestView
from loom.artifacts import ArtifactRef
from loom.fingerprints import Fingerprint, hash_mapping

__all__ = [
    "ResourceRef",
    "Record",
    "InMemoryManifest",
    "ManifestView",
    "ArtifactRef",
    "Fingerprint",
    "hash_mapping",
]
```

Why it is necessary:

- Gives users a clear package-level API.
- Communicates which objects are first-class public concepts.
- Makes documentation examples simpler.

What to avoid:

- Do not import config composition, pipeline runners, SLURM executors, or optional-dependency modules here.
- Do not trigger plugin discovery on import.
- Do not import expensive modules.

Reason: importing `loom` should be cheap and safe.

---

### 3.2 `src/loom/py.typed`

Purpose: marker file for PEP 561 typed packages.

Recommended contents: empty file.

Why it is necessary:

- Tells type checkers that `loom` ships type information.
- Helps downstream packages rely on typed APIs.

What to avoid:

- No runtime code.
- No comments required.

---

### 3.3 `ids.py`

Purpose: define simple semantic aliases for common identifiers.

Recommended contents:

```python
RecordID = str
ResourceKey = str
CodecKey = str
ArtifactID = str
ArtifactType = str
RunID = str
StageID = str
```

Why it is necessary:

- Improves readability of signatures.
- Avoids premature wrapper classes.
- Keeps v0 simple.

Example:

```python
def load_stage_outputs(run_id: RunID, stage_id: StageID) -> dict[str, ArtifactRef]: ...
```

What to avoid:

- Do not create `NewType` or wrapper dataclasses until confusion between IDs is a demonstrated problem.
- Do not add domain-specific IDs such as `SubjectID`, `TrialID`, or `DatasetName`.

---

### 3.4 `refs.py`

Purpose: define `ResourceRef`, a serializable pointer to an input/source resource.

Recommended contents:

```python
@dataclass(frozen=True, slots=True)
class ResourceRef:
    uri: str
    resource_type: str
    codec_key: str
    schema_version: int = 1
    checksum: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

Why it is necessary:

- Represents external data without loading it.
- Allows manifests and records to point to arbitrary resources.
- Keeps resource loading codec-driven and generic.

What it should answer:

```text
where is the resource?
what broad type of resource is it?
which codec can load it?
what schema version does it use?
what metadata helps interpret it?
what checksum identifies its bytes, if known?
```

What to avoid:

- No `VideoRef`, `SignalRef`, `ImageRef`, `BVPRef`, or `PPGRef`.
- No decoding logic.
- No dataset-specific metadata assumptions.

Downstream packages can provide helpers:

```python
def video_resource(uri: str, *, codec_key: str, fps: float | None = None) -> ResourceRef:
    metadata = {}
    if fps is not None:
        metadata["fps"] = fps
    return ResourceRef(uri=uri, resource_type="video", codec_key=codec_key, metadata=metadata)
```

---

### 3.5 `records.py`

Purpose: define generic dataset-like records and manifests.

Recommended contents:

```text
Record
Manifest protocol
InMemoryManifest
ManifestView
RecordFilter protocol
HasResource
MetadataEquals
MetadataIn
```

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class Record:
    record_id: str
    resources: Mapping[str, ResourceRef] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    annotations: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def has_resource(self, key: str) -> bool: ...
    def get_resource(self, key: str, default: Any = None) -> ResourceRef | Any: ...
    def require_resource(self, key: str) -> ResourceRef: ...
```

Why it is necessary:

- Gives all domains a generic unit of indexed data.
- Keeps heavy data unloaded.
- Allows domain packages to build dataset adapters that emit a common representation.

What to avoid:

- No domain-specific metadata fields.
- No subject/session/trial-specific helpers in this package.
- No media loading.

Scalability note:

If this file grows too large, convert it into a package while preserving the public import path:

```text
records/
  __init__.py
  base.py
  manifest.py
  views.py
  filters.py
  errors.py
```

---

### 3.6 `artifacts.py`

Purpose: define `ArtifactRef`, a serializable handle to a persistent pipeline output.

Recommended contents:

```python
@dataclass(frozen=True, slots=True)
class ArtifactRef:
    uri: str
    artifact_type: str
    schema_version: int = 1
    checksum: str | None = None
    fingerprint: str | None = None
    producer_stage: str | None = None
    created_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

Why it is necessary:

- Enables stages to pass outputs without loading them.
- Supports resume logic, lineage, run inspection, and cluster execution.
- Decouples stage execution from in-memory chaining.

Important distinction:

```text
ResourceRef = pointer to an external or source resource.
ArtifactRef = pointer to a produced pipeline output.
```

What to avoid:

- Do not make `artifact_type` a closed enum.
- Do not encode domain schemas here.
- Do not load artifacts from this class directly.

Artifact loading belongs to `ArtifactStore`.

---

### 3.7 `provenance.py`

Purpose: define generic provenance structures.

Recommended contents:

```text
CodeProvenance
EnvironmentProvenance
RunProvenance
StageProvenance
```

Typical fields:

```text
git commit
git branch
git dirty flag
package versions
Python version
platform
hostname
container image
container digest
run command
seed
stage inputs
stage outputs
start/finish timestamps
metadata
```

Why it is necessary:

- Reproducibility depends on knowing how outputs were produced.
- Resume decisions often need code/environment identity.
- Debugging failed runs requires context.

What to avoid:

- No domain-specific provenance fields.
- No assumptions about ML frameworks.
- No automatic import of heavy version-reporting libraries.

Scalability note:

If provenance capture grows, split later into:

```text
provenance/
  __init__.py
  models.py
  git.py
  environment.py
  packages.py
  capture.py
```

Keep `from loom.provenance import RunProvenance` stable.

---

### 3.8 `fingerprints.py`

Purpose: deterministic hashing for semantic production inputs.

Recommended contents:

```text
Fingerprint
stable_json_dumps
hash_bytes
hash_text
hash_mapping
```

Definitions:

```text
checksum    = hash of stored bytes
fingerprint = hash of semantic production inputs
```

Why it is necessary:

- Resume logic depends on whether stage inputs/config/code/environment changed.
- Fingerprints allow stages to be skipped safely.
- Stable hashing makes tests reproducible.

Representative implementation:

```python
def stable_json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def hash_mapping(mapping: Mapping[str, Any], *, algorithm: str = "sha256") -> str:
    return hash_text(stable_json_dumps(mapping), algorithm=algorithm)
```

What to avoid:

- Do not use Python's built-in `hash()` for persisted fingerprints.
- Do not include non-deterministic representations unless normalized first.
- Do not silently ignore important inputs such as upstream artifact fingerprints.

---

### 3.9 `protocols.py`

Purpose: define package-wide structural protocols that are genuinely generic.

Recommended contents:

```python
class Validatable(Protocol):
    def validate(self) -> None: ...

class Fingerprintable(Protocol):
    def fingerprint(self) -> str: ...
```

Why it is necessary:

- Supports structural typing without inheritance.
- Keeps reusable contracts available across subsystems.

What to avoid:

- Do not put `Stage`, `Codec`, `DataSource`, `ConfigRecipe`, `ArtifactStore`, or `RunStore` here.
- Those belong in their subsystem packages.

---

### 3.10 `errors.py`

Purpose: define stable top-level error classes.

Recommended contents:

```python
class LoomError(Exception): ...
class ValidationError(LoomError): ...
class ContractError(LoomError): ...
class ArtifactError(LoomError): ...
class ConfigError(LoomError): ...
class PipelineError(LoomError): ...
class IOErrorBase(LoomError): ...
```

Why it is necessary:

- Gives downstream users broad exception classes to catch.
- Keeps subsystem errors rooted in a shared hierarchy.

What to avoid:

- Do not put every concrete error here.
- Keep specific errors next to the subsystem that raises them.

Example:

```text
loom.config.errors.TargetInstantiationError
loom.pipeline.errors.StageExecutionError
loom.io.codecs.errors.CodecNotFoundError
```

---

### 3.11 `timestamps.py`

Purpose: provide consistent timestamp helpers.

Recommended contents:

```text
utc_now
utc_timestamp
safe_timestamp_for_path
parse_timestamp
```

Why `timestamps.py` instead of `time.py`:

- `timestamps.py` is more specific.
- It avoids visual confusion with the standard-library `time` module.
- It communicates that the file is not a general time abstraction.

Why it is necessary:

- Runs, artifacts, provenance records, and status files need consistent timestamps.
- Path-safe timestamps are useful for run directories.

What to avoid:

- Do not implement broad scheduling/timezone logic here.
- Do not make timestamps local-time-dependent.

Use UTC by default.

---

## 4. `serialization/`

The serialization package handles conversion between Python objects and plain structured data. It does not own files, streams, URIs, codecs, or sources.

Use this package when writing:

```text
ArtifactRef -> dict
Record -> dict
RunProvenance -> dict
dataclass -> JSON-compatible structure
schema-versioned payload -> plain data
```

Do not use it for:

```text
opening files
resolving URIs
selecting codecs
loading remote resources
writing to artifact stores
```

### 4.1 `serialization/__init__.py`

Purpose: re-export the public serialization API.

Recommended contents:

```python
from loom.serialization.plain import to_plain_data
from loom.serialization.json import stable_json_dumps, read_json, write_json
```

Why it is necessary:

- Keeps imports clean.
- Allows internal file layout to change later.

---

### 4.2 `serialization/plain.py`

Purpose: convert objects into JSON/YAML-safe plain data.

Recommended contents:

```text
to_plain_data
is_plain_data
normalize_mapping
normalize_sequence
```

Expected output types:

```text
None
bool
int
float
str
list[plain]
dict[str, plain]
```

Why it is necessary:

- Fingerprints need deterministic serializable objects.
- Status files and artifact indexes need plain data.
- Dataclasses need to be persisted safely.

What to avoid:

- Do not write files here.
- Do not import I/O sources or codecs.

---

### 4.3 `serialization/dataclasses.py`

Purpose: dataclass conversion helpers.

Recommended contents:

```text
dataclass_to_dict
dataclass_from_dict, if needed
is_dataclass_instance
```

Why it is necessary:

- Many core types are dataclasses.
- Conversion behavior should be consistent.

What to avoid:

- Avoid magical reconstruction of arbitrary classes unless there is a clear schema.
- Prefer explicit constructors for public types.

---

### 4.4 `serialization/json.py`

Purpose: stable JSON serialization helpers.

Recommended contents:

```text
stable_json_dumps
json_dumps_pretty
read_json
write_json
```

Why it is necessary:

- JSON is likely the default format for status, inputs, outputs, fingerprints, and artifact indexes.
- Stable dumps are needed for hashing.

What to avoid:

- Do not encode domain objects directly unless they first convert to plain data.
- Do not bury filesystem-specific atomic writes here; those belong in store/execution atomic helpers.

---

### 4.5 `serialization/yaml.py`

Purpose: YAML helpers, if YAML support is enabled.

Recommended contents:

```text
read_yaml
write_yaml
yaml_available
```

Why it is necessary:

- Authored configs are often YAML.
- Resolved configs may be persisted as YAML for readability.

Dependency policy:

- YAML support may depend on optional config extras.
- Avoid making PyYAML/OmegaConf mandatory for primitive use.

What to avoid:

- Do not implement config composition here.
- Do not implement interpolation here.

---

### 4.6 `serialization/schema.py`

Purpose: schema-version helpers.

Recommended contents:

```text
require_schema_version
get_schema_version
check_supported_schema
SchemaVersionError
```

Why it is necessary:

- Refs, artifacts, records, status files, and indexes may evolve.
- Schema checking prevents silently misreading old files.

What to avoid:

- Do not implement full migration machinery too early.
- Start by checking and failing clearly.

---

### 4.7 `serialization/errors.py`

Purpose: serialization-specific errors.

Recommended contents:

```text
SerializationError
DeserializationError
SchemaVersionError
PlainDataError
```

Why it is necessary:

- Serialization failures should be distinguishable from file I/O failures.

---

## 5. `io/`

The I/O package handles resource access and codec mechanics. It is separate from serialization because it deals with bytes, files, URIs, and backends.

Long-term, `io` may grow support for:

```text
local filesystem
HTTP
S3
GCS
Azure Blob
fsspec-backed sources
package resources
read-only mounted datasets
```

The generic package may provide local and simple codecs. Domain packages provide domain codecs.

### 5.1 `io/__init__.py`

Purpose: expose the public I/O API.

Recommended contents:

```python
from loom.io.sources.base import DataSource
from loom.io.sources.local import LocalFileSystemSource
from loom.io.codecs.base import Codec
from loom.io.codecs.registry import CodecRegistry
```

Why it is necessary:

- Gives downstream packages stable import paths.

What to avoid:

- Do not instantiate global registries unless needed.
- Do not import optional remote backends eagerly.

---

### 5.2 `io/uris.py`

Purpose: URI parsing and normalization.

Recommended contents:

```text
parse_uri
is_file_uri
uri_to_path
path_to_file_uri
normalize_uri
get_uri_scheme
```

Why it is necessary:

- `ResourceRef` and `ArtifactRef` both use URIs.
- Sources need a shared way to reason about schemes.

What to avoid:

- Do not load resources here.
- Do not encode codec behavior here.

---

### 5.3 `io/errors.py`

Purpose: package-level I/O errors.

Recommended contents:

```text
LoomIOError
UnsupportedURIError
SourceError
CodecError
```

Why it is necessary:

- Shared root for source and codec errors.

---

## 6. `io/sources/`

Sources know how to access bytes or file-like objects. They do not know how to interpret domain data.

### 6.1 `io/sources/__init__.py`

Purpose: public source exports.

Recommended contents:

```python
from loom.io.sources.base import DataSource
from loom.io.sources.local import LocalFileSystemSource
```

---

### 6.2 `io/sources/base.py`

Purpose: define the `DataSource` protocol.

Recommended contents:

```python
class DataSource(Protocol):
    def glob(self, pattern: str) -> Iterable[str]: ...
    def open(self, uri: str, mode: str = "rb"): ...
    def exists(self, uri: str) -> bool: ...
    def stat(self, uri: str) -> Mapping[str, Any]: ...
    def resolve(self, path: str) -> str: ...
```

Why it is necessary:

- Allows different storage backends to be used without changing records or stages.

What to avoid:

- Do not include codec logic.
- Do not require subclassing.

---

### 6.3 `io/sources/local.py`

Purpose: local filesystem source implementation.

Recommended contents:

```text
LocalFileSystemSource
path normalization
file URI support
safe open/exists/stat/glob
```

Why it is necessary:

- Local filesystem is the v0 backend.
- It is standard-library-only.

What to avoid:

- Do not handle artifact-store-specific layout here.
- Do not treat local paths as domain resources.

---

### 6.4 `io/sources/registry.py`

Purpose: optional registry for source backends.

Recommended contents:

```text
SourceRegistry
register_scheme
get_source_for_uri
```

Why it is necessary:

- Future `s3://`, `gs://`, `http://`, or `file://` support can route by URI scheme.

V0 note:

- This can be deferred until more than one source exists.

---

### 6.5 `io/sources/errors.py`

Purpose: source-specific errors.

Recommended contents:

```text
DataSourceError
SourceNotFoundError
SourceRegistrationError
UnsupportedSourceSchemeError
```

---

## 7. `io/codecs/`

Codecs know how to convert between Python objects and stored bytes/text for a particular format. They bridge serialization and I/O.

### 7.1 `io/codecs/__init__.py`

Purpose: public codec exports.

Recommended contents:

```python
from loom.io.codecs.base import Codec
from loom.io.codecs.registry import CodecRegistry
from loom.io.codecs.json_codec import JSONCodec
from loom.io.codecs.text_codec import TextCodec
from loom.io.codecs.bytes_codec import BytesCodec
```

---

### 7.2 `io/codecs/base.py`

Purpose: define the `Codec` protocol.

Recommended contents:

```python
class Codec(Protocol):
    key: str

    def save(self, obj: Any, uri: str, *, metadata: Mapping[str, Any] | None = None) -> ResourceRef: ...
    def load(self, ref: ResourceRef) -> Any: ...
```

Why it is necessary:

- Resource refs identify data by codec key.
- Downstream packages can register custom codecs.

What to avoid:

- Do not require codecs to inherit from a base class.
- Do not put domain-specific codecs in the generic package.

---

### 7.3 `io/codecs/json_codec.py`

Purpose: JSON codec for generic structured data.

Recommended contents:

```text
JSONCodec
save plain-data-compatible objects
load JSON into plain data
```

Why it is necessary:

- Generic manifests, indexes, metrics, and small metadata payloads often fit JSON.

What to avoid:

- Do not attempt to reconstruct arbitrary Python objects without explicit schema.

---

### 7.4 `io/codecs/text_codec.py`

Purpose: text codec.

Recommended contents:

```text
TextCodec
encoding handling, default UTF-8
```

Why it is necessary:

- Logs, reports, and small text artifacts are common.

---

### 7.5 `io/codecs/bytes_codec.py`

Purpose: raw bytes codec.

Recommended contents:

```text
BytesCodec
```

Why it is necessary:

- Provides a generic fallback for byte artifacts.

---

### 7.6 `io/codecs/registry.py`

Purpose: map codec keys to codec implementations.

Recommended contents:

```text
CodecRegistry
register
get
load
save, optional
```

Why it is necessary:

- `ResourceRef.codec_key` must resolve to concrete behavior.
- Domain packages can register codecs without changing core code.

Scalability note:

Later, support entry point discovery:

```toml
[project.entry-points."loom.codecs"]
video_mp4_v1 = "rphys.codecs.video:MP4VideoCodec"
```

---

### 7.7 `io/codecs/errors.py`

Purpose: codec-specific errors.

Recommended contents:

```text
CodecNotFoundError
CodecRegistrationError
CodecLoadError
CodecSaveError
UnsupportedCodecObjectError
```

---

## 8. `config/`

The config package turns authored config into resolved config and optionally constructed Python objects.

V0 should support only two major mechanisms:

```text
_target_ importlib instantiation
_recipe_ named recipe expansion
```

Avoid too much Hydra-like complexity early:

```text
no advanced include graph in v0
no registry aliases in v0
no advanced list patching in v0
no dynamic DAG generation in v0
```

### 8.1 `config/__init__.py`

Purpose: expose the public config API.

Recommended contents:

```python
from loom.config.api import compose_config, instantiate, register_recipe
```

Why it is necessary:

- Users should not need to know the internal config package layout.

---

### 8.2 `config/api.py`

Purpose: public facade for config operations.

Recommended contents:

```text
compose_config
load_config
instantiate
register_recipe
```

Why it is necessary:

- Provides a stable API.
- Keeps internal orchestration details private.

What to avoid:

- Do not make users import from `compose.py`, `recipes.catalog`, or `instantiate.recursive` for common operations.

---

### 8.3 `config/load.py`

Purpose: load raw config files.

Recommended contents:

```text
load_yaml
load_json
load_config_file
```

Why it is necessary:

- Separates file loading from composition.

What to avoid:

- Do not merge overlays here.
- Do not expand recipes here.

---

### 8.4 `config/compose.py`

Purpose: implement the composition pipeline.

Recommended contents:

```text
load base config
load overlay configs
merge overlays
apply CLI overrides
resolve interpolation
validate top-level shape
expand recipes
resolve interpolation again
check missing values
redact secrets
capture config provenance
return ComposedConfig
```

Why it is necessary:

- This is the main authored-config to resolved-config flow.

Recommended return object:

```python
@dataclass(frozen=True)
class ComposedConfig:
    resolved: Mapping[str, Any]
    redacted: Mapping[str, Any]
    provenance: ConfigProvenance
    fingerprint: str
```

---

### 8.5 `config/merge.py`

Purpose: deterministic config merge behavior.

Recommended contents:

```text
merge_mapping
merge_sequence
merge_config
```

Recommended policy:

```text
mappings: recursive merge
scalars: replace
lists: replace entirely
null: explicit null
advanced operators: not supported in v0
```

Why it is necessary:

- Merge behavior must be predictable.
- Tests need deterministic behavior.

What to avoid:

- Do not implement list append/delete/patch operators until real need appears.

---

### 8.6 `config/overrides.py`

Purpose: parse and apply CLI dot-path overrides.

Recommended contents:

```text
parse_override
parse_overrides
apply_override
parse_scalar_value
set_by_dot_path
```

Example:

```bash
loom run experiment.yaml model.hidden_dim=64 optimizer.lr=1e-4
```

Why it is necessary:

- Experiments need simple CLI changes without editing YAML.

Design concern:

- Be explicit about types. String parsing can create surprising results.
- Consider a strict mode for ambiguous values.

---

### 8.7 `config/interpolation.py`

Purpose: resolve interpolation expressions.

Recommended contents:

```text
resolve_interpolation
check_unresolved
register_resolvers, if needed
```

Why it is necessary:

- Configs often need values such as `runs/${name}/${timestamp}`.

Dependency concern:

- If using OmegaConf, wrap it here so the rest of the package does not become OmegaConf-specific.

---

### 8.8 `config/validation.py`

Purpose: validate generic config shape.

Recommended contents:

```text
validate_schema_version
validate_reserved_keys
validate_pipeline_section
validate_no_missing_values
validate_config_shape
```

Why it is necessary:

- Bad configs should fail before running stages.

What to avoid:

- No domain validation.
- No assumptions about datasets, models, optimizers, losses, or metrics.

---

### 8.9 `config/redaction.py`

Purpose: remove secrets before persisted config output.

Recommended contents:

```text
redact_config
is_secret_key
redact_mapping
redact_value
```

Typical secret key fragments:

```text
token
password
secret
api_key
credential
private_key
```

Why it is necessary:

- Resolved configs are written to run directories.
- Users should not accidentally persist credentials.

Design concern:

- Redaction should happen before writing persisted config/provenance.
- Redaction should be recursive.
- Users may need to configure additional secret patterns.

---

### 8.10 `config/provenance.py`

Purpose: record how config was produced.

Recommended contents:

```text
ConfigProvenance
source config path
overlay paths
CLI overrides
recipe expansions
resolved config hash
created timestamp
```

Why it is necessary:

- Reproducibility requires knowing the exact composition inputs.

---

### 8.11 `config/errors.py`

Purpose: config-specific errors.

Recommended contents:

```text
ConfigLoadError
ConfigMergeError
OverrideParseError
InterpolationError
ConfigValidationError
RecipeExpansionError
TargetInstantiationError
```

Why it is necessary:

- Config failures are common and need precise diagnostics.

---

## 9. `config/recipes/`

Recipes expand compact authored config into explicit resolved config. The generic package provides the mechanism; downstream packages provide actual recipes.

### 9.1 `config/recipes/__init__.py`

Purpose: public recipe exports.

Recommended contents:

```python
from loom.config.recipes.base import ConfigRecipe, RecipeModel
from loom.config.recipes.catalog import RecipeCatalog
from loom.config.recipes.expansion import expand_recipes
```

---

### 9.2 `config/recipes/base.py`

Purpose: define recipe contracts.

Recommended contents:

```python
class ConfigRecipe(Protocol):
    def expand(self) -> dict[str, Any]: ...
```

Optional with config extras:

```python
class RecipeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    def expand(self) -> dict[str, Any]: ...
```

Why it is necessary:

- Recipes provide typed public knobs for repeated configuration patterns.

What to avoid:

- No domain recipes in the generic package.

---

### 9.3 `config/recipes/catalog.py`

Purpose: resolve recipe names to recipe classes.

Recommended contents:

```text
RecipeCatalog
register
get
list
load_entry_points, later
```

Why it is necessary:

- `_recipe_: name` needs a lookup mechanism.

Design concern:

- Keep default/global registry behavior explicit. Hidden global state can make tests brittle.

---

### 9.4 `config/recipes/expansion.py`

Purpose: recursively expand recipe blocks.

Recommended contents:

```text
expand_recipe_block
expand_recipes
track_expansion_provenance
detect_nested_recipe_errors
```

Why it is necessary:

- Expansion should be isolated from loading and merging.

---

### 9.5 `config/recipes/errors.py`

Purpose: recipe-specific errors.

Recommended contents:

```text
UnknownRecipeError
InvalidRecipeError
RecipeExpansionError
RecipeValidationError
```

---

## 10. `config/instantiate/`

Instantiation turns `_target_` config blocks into Python objects.

### 10.1 `config/instantiate/__init__.py`

Purpose: public instantiation exports.

Recommended contents:

```python
from loom.config.instantiate.recursive import instantiate
from loom.config.instantiate.targets import import_target
```

---

### 10.2 `config/instantiate/targets.py`

Purpose: import target objects from strings.

Recommended contents:

```text
import_target
validate_target_path
resolve_callable
```

Supported forms:

```text
package.module.ClassName
package.module:function_name
```

Why it is necessary:

- `_target_` values must resolve into Python callables/classes.

Security concern:

- Dynamic import can execute arbitrary code.
- Treat configs as trusted code.
- Add allow-list mode later if needed.

---

### 10.3 `config/instantiate/recursive.py`

Purpose: recursively construct objects from config.

Recommended contents:

```text
instantiate
instantiate_mapping
instantiate_sequence
handle_target_block
handle_args
handle_partial
```

Reserved keys:

```text
_target_
_args_
_partial_
_context_
_recipe_
```

Why it is necessary:

- Experiment config often describes object graphs.

What to avoid:

- Do not implement a parallel registry system in v0.
- Do not silently ignore unknown reserved keys.

---

### 10.4 `config/instantiate/injection.py`

Purpose: runtime dependency injection.

Recommended contents:

```text
resolve_injections
apply_injections
validate_injection_keys
```

Why it is necessary:

Some values cannot belong in YAML:

```text
artifact_store
run_store
stage inputs
model parameters
runtime context
```

Design concern:

- Static config should not directly encode runtime objects.
- Injection should be explicit and testable.

---

### 10.5 `config/instantiate/errors.py`

Purpose: instantiation-specific errors.

Recommended contents:

```text
TargetImportError
TargetInstantiationError
InjectionError
ReservedKeyError
InvalidTargetConfigError
```

---

## 11. `pipeline/`

The pipeline package models and runs DAGs of stages. It does not know what stages do internally.

The central contract:

```text
Every stage consumes ArtifactRefs and produces ArtifactRefs.
```

### 11.1 `pipeline/__init__.py`

Purpose: public pipeline exports.

Recommended contents:

```python
from loom.pipeline.specs import PipelineSpec, StageSpec
from loom.pipeline.stage import Stage
from loom.pipeline.context import StageContext
```

Potentially also:

```python
from loom.pipeline.execution.runner import PipelineRunner
```

But avoid importing heavy optional executor dependencies.

---

### 11.2 `pipeline/specs.py`

Purpose: typed pipeline and stage specifications.

Recommended contents:

```text
StageSpec
PipelineSpec
parse_stage_spec
parse_pipeline_spec
```

Representative shape:

```python
@dataclass(frozen=True, slots=True)
class StageSpec:
    name: str
    target: Mapping[str, Any]
    inputs: Mapping[str, str] = field(default_factory=dict)
    outputs: Mapping[str, str] = field(default_factory=dict)
    config: Mapping[str, Any] = field(default_factory=dict)
    resources: Mapping[str, Any] = field(default_factory=dict)
    runtime: Mapping[str, Any] = field(default_factory=dict)
```

Why it is necessary:

- Config dictionaries need to become typed pipeline descriptions.

---

### 11.3 `pipeline/stage.py`

Purpose: define the `Stage` protocol.

Recommended contents:

```python
class Stage(Protocol):
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]: ...
```

Why it is necessary:

- Downstream packages implement this protocol.
- No inheritance required.

What to avoid:

- No domain stage implementations.
- No training/preprocessing/evaluation behavior.

---

### 11.4 `pipeline/context.py`

Purpose: define `StageContext`.

Recommended contents:

```text
StageContext
```

Typical fields:

```text
run_id
stage_name
run_dir
stage_dir
resolved_config
artifact_store
run_store
provenance
metadata
```

Why it is necessary:

- Stages need controlled runtime access.
- Avoids global state.

Design concern:

- Keep context generic.
- Avoid putting domain conveniences here.

---

### 11.5 `pipeline/status.py`

Purpose: status enums and status records.

Recommended contents:

```text
StageStatus
RunStatus
StatusRecord
```

Stage statuses:

```text
PENDING
RUNNING
SUCCEEDED
FAILED
SKIPPED
STALE
CANCELLED
```

Why it is necessary:

- Resume, failure handling, and inspection depend on explicit states.

---

### 11.6 `pipeline/validation.py`

Purpose: generic pipeline validation.

Recommended contents:

```text
validate_unique_stage_names
validate_inputs_reference_existing_outputs
validate_declared_outputs
validate_no_cycles
validate_selected_stages
validate_pipeline_spec
```

Why it is necessary:

- Invalid DAGs should fail before execution.

---

### 11.7 `pipeline/selectors.py`

Purpose: select pipeline subsets.

Recommended contents:

```text
StageSelector
parse_selectors
apply_only
apply_from
apply_skip
apply_force
```

Why it is necessary:

- Users need partial execution and rerun controls.

Examples:

```text
--only train
--from preprocess
--skip report
--force train
```

---

### 11.8 `pipeline/resources.py`

Purpose: scheduler-neutral resource requests.

Recommended contents:

```text
ResourceRequest
CPU/memory/GPU/time fields
custom scheduler metadata
```

Why it is necessary:

- Stages need to declare resource needs without becoming SLURM-specific.

What to avoid:

- Do not make this only about SLURM.
- Do not encode domain hardware assumptions.

---

### 11.9 `pipeline/runtime.py`

Purpose: runtime options separate from pipeline specification.

Recommended contents:

```text
RunOptions
ResumeOptions
ExecutionOptions
```

Why it is necessary:

- The pipeline spec describes what the pipeline is.
- Runtime options describe how this invocation should behave.

Examples:

```text
resume=True
force={"train"}
executor="local"
dry_run=True
```

---

### 11.10 `pipeline/errors.py`

Purpose: pipeline-level errors.

Recommended contents:

```text
PipelineValidationError
StageExecutionError
StageContractError
StageOutputError
PlanningError
ExecutorError
```

---

## 12. `pipeline/graph/`

This package contains pure graph mechanics. It should not execute stages or access stores.

### 12.1 `pipeline/graph/__init__.py`

Purpose: public graph exports, if any.

Recommended contents:

```python
from loom.pipeline.graph.topology import topological_sort
from loom.pipeline.graph.bindings import parse_artifact_reference
```

---

### 12.2 `pipeline/graph/dag.py`

Purpose: construct and inspect the stage graph.

Recommended contents:

```text
build_stage_graph
upstream_of
downstream_of
transitive_upstream
transitive_downstream
```

Why it is necessary:

- Planning and validation need graph relationships.

---

### 12.3 `pipeline/graph/topology.py`

Purpose: topological sorting and cycle detection.

Recommended contents:

```text
topological_sort
detect_cycles
CycleError, or use pipeline errors
```

Why it is necessary:

- Execution order depends on a valid DAG.

---

### 12.4 `pipeline/graph/bindings.py`

Purpose: resolve symbolic input references.

Recommended contents:

```text
parse_artifact_reference
resolve_input_bindings
bind_stage_inputs
```

Example:

```text
train.training_index -> output named training_index from stage train
```

Why it is necessary:

- Stage specs contain symbolic references.
- Execution needs concrete `ArtifactRef` inputs.

---

## 13. `pipeline/planning/`

Planning decides what should run, skip, or be invalidated. It should not execute stages.

### 13.1 `pipeline/planning/__init__.py`

Purpose: public planning exports.

Recommended contents:

```python
from loom.pipeline.planning.plan import ExecutionPlan, StagePlan
from loom.pipeline.planning.planner import PipelinePlanner
```

---

### 13.2 `pipeline/planning/plan.py`

Purpose: dataclasses representing the planner output.

Recommended contents:

```text
ExecutionPlan
StagePlan
SkipReason
RunDecision
```

Why it is necessary:

- Planning should be inspectable.
- `loom plan CONFIG` can display this structure.

---

### 13.3 `pipeline/planning/planner.py`

Purpose: central planning algorithm.

Recommended contents:

```text
PipelinePlanner
plan_pipeline
```

Inputs:

```text
PipelineSpec
RunStore
resume flag
force stages
only/from/skip selectors
current fingerprints
existing statuses
```

Outputs:

```text
topological execution order
stage input bindings
stages to skip
stages to run
invalidated downstream stages
executor plan
```

Why it is necessary:

- Keeps runner focused on execution.

---

### 13.4 `pipeline/planning/resume.py`

Purpose: determine whether prior outputs are reusable.

Recommended contents:

```text
is_stage_complete
can_skip_stage
compare_fingerprint
validate_existing_outputs
```

A stage is complete only if:

```text
status == SUCCEEDED
outputs.json exists
all declared outputs exist
fingerprint matches
checksums validate if available
```

Why it is necessary:

- Resume behavior must be reliable and heavily tested.

---

### 13.5 `pipeline/planning/invalidation.py`

Purpose: propagate stale state downstream.

Recommended contents:

```text
find_invalidated_downstream_stages
mark_downstream_stale
propagate_changes
```

Why it is necessary:

- If an upstream stage changes, downstream outputs may no longer be valid.

---

## 14. `pipeline/execution/`

Execution performs a plan. It coordinates lifecycle, stores, executors, logging, and failure handling.

### 14.1 `pipeline/execution/__init__.py`

Purpose: public execution exports.

Recommended contents:

```python
from loom.pipeline.execution.runner import PipelineRunner
```

---

### 14.2 `pipeline/execution/runner.py`

Purpose: high-level pipeline runner.

Recommended contents:

```text
PipelineRunner
run_pipeline
```

Responsibilities:

```text
create run directory
write resolved config
validate pipeline
compute plan
execute stages through executor
update status files
write artifact index
handle failures
```

Why it is necessary:

- This is the main Python API for execution.

What to avoid:

- Do not put all planner, lifecycle, status, and store logic here.
- Keep it as coordinator, not dumping ground.

---

### 14.3 `pipeline/execution/lifecycle.py`

Purpose: consistent stage lifecycle transitions.

Recommended contents:

```text
prepare_stage
mark_stage_running
mark_stage_succeeded
mark_stage_failed
mark_stage_skipped
finalize_stage
```

Why it is necessary:

- Local, subprocess, and SLURM execution should share consistent status semantics.

---

### 14.4 `pipeline/execution/atomic.py`

Purpose: execution-level atomicity and transactions.

Recommended contents:

```text
stage_output_transaction
commit_stage_outputs
rollback_stage_outputs
```

Why it is necessary:

- A stage should not appear successful if only half its outputs were written.

Difference from `pipeline/stores/atomic.py`:

```text
stores/atomic.py    = low-level atomic file writes
execution/atomic.py = stage-level transaction semantics
```

---

### 14.5 `pipeline/execution/logs.py`

Purpose: execution log path and capture helpers.

Recommended contents:

```text
stage_log_paths
capture_stdout_stderr
write_log_metadata
```

Why it is necessary:

- Debugging failed runs requires consistent logs.

---

## 15. `pipeline/executors/`

Executors run stages using different backends.

### 15.1 `pipeline/executors/__init__.py`

Purpose: public executor exports.

Recommended contents:

```python
from loom.pipeline.executors.base import Executor, ExecutionResult
from loom.pipeline.executors.local import LocalExecutor
```

Avoid importing SLURM eagerly if it has optional behavior.

---

### 15.2 `pipeline/executors/base.py`

Purpose: executor protocol and result types.

Recommended contents:

```text
Executor protocol
ExecutionResult
SubmittedJob, optional
```

Why it is necessary:

- Runner should not care whether execution is local, subprocess, or cluster-based.

---

### 15.3 `pipeline/executors/local.py`

Purpose: run stage in current Python process.

Recommended contents:

```text
LocalExecutor
```

Why it is necessary:

- Simplest v0 executor.
- Best for unit tests and small workflows.

---

### 15.4 `pipeline/executors/subprocess.py`

Purpose: run stage through a subprocess command.

Recommended contents:

```text
SubprocessExecutor
command construction
subprocess result capture
exit code handling
```

Example command:

```bash
loom stage run --run-dir RUN_DIR --stage STAGE_NAME --resume
```

Why it is necessary:

- Tests process isolation.
- Prepares for SLURM/container execution.

---

### 15.5 `pipeline/executors/slurm.py`

Purpose: SLURM executor scaffolding.

Recommended contents:

```text
SlurmExecutor
SBATCH script generation
resource mapping
job dependency chaining
sbatch submission
job id parsing
```

Why it is necessary:

- Cluster execution is important for research pipelines.

Dependency policy:

- Use shell/subprocess-based interaction.
- Do not require a Python SLURM dependency.

What to avoid:

- Do not make generic `ResourceRequest` SLURM-specific.

---

### 15.6 `pipeline/executors/registry.py`

Purpose: optional executor registry.

Recommended contents:

```text
ExecutorRegistry
register_executor
get_executor
```

Why it is necessary:

- Allows `executor: local`, `executor: slurm`, or downstream executors later.

V0 note:

- Can be deferred until more executors exist.

---

### 15.7 `pipeline/executors/errors.py`

Purpose: executor-specific errors.

Recommended contents:

```text
ExecutorError
ExecutorRegistrationError
SubprocessExecutionError
SlurmSubmissionError
```

---

## 16. `pipeline/stores/`

Stores manage persistent artifact and run state.

This package deserves a subdirectory because storage will expand into local stores, remote stores, content-addressed storage, locking, indexes, migrations, and recovery.

### 16.1 `pipeline/stores/__init__.py`

Purpose: public store exports.

Recommended contents:

```python
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.pipeline.stores.run_store import RunStore
from loom.pipeline.stores.local_artifacts import LocalArtifactStore
from loom.pipeline.stores.local_runs import LocalRunStore
```

---

### 16.2 `pipeline/stores/artifact_store.py`

Purpose: define `ArtifactStore` protocol.

Recommended contents:

```python
class ArtifactStore(Protocol):
    def save(
        self,
        obj: Any,
        *,
        artifact_type: str,
        stage_name: str,
        name: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRef: ...

    def load(self, ref: ArtifactRef, *, expected_type: str | None = None) -> Any: ...
    def exists(self, ref: ArtifactRef) -> bool: ...
```

Why it is necessary:

- Stages should save/load artifacts through a stable interface.

---

### 16.3 `pipeline/stores/run_store.py`

Purpose: define `RunStore` protocol.

Recommended contents:

```text
create_run
get_run_dir
get_stage_dir
read_status
write_status
read_inputs
write_inputs
read_outputs
write_outputs
read_fingerprint
write_fingerprint
```

Why it is necessary:

- Run-state management is separate from artifact data storage.

---

### 16.4 `pipeline/stores/indexes.py`

Purpose: run and artifact indexes.

Recommended contents:

```text
ArtifactIndex
StageIndex
RunIndex
read_artifact_index
write_artifact_index
```

Why it is necessary:

- Run inspection should not require scanning the whole directory tree every time.

---

### 16.5 `pipeline/stores/local_artifacts.py`

Purpose: local filesystem artifact store.

Recommended contents:

```text
LocalArtifactStore
artifact path allocation
artifact save/load
checksum calculation
ArtifactRef creation
```

Why it is necessary:

- V0 needs a concrete artifact store.

What to avoid:

- No domain codecs unless registered externally.

---

### 16.6 `pipeline/stores/local_runs.py`

Purpose: local filesystem run store.

Recommended contents:

```text
LocalRunStore
run directory creation
stage directory creation
status file management
input/output/fingerprint file management
log directory helpers
```

Expected layout:

```text
runs/<run_id>/
  config/
    resolved.yaml
    provenance.json
  stages/
    <stage_name>/
      status.json
      inputs.json
      outputs.json
      fingerprint.json
      logs/
      artifacts/
  artifacts.json
  status.json
```

Why it is necessary:

- Run state must be inspectable and resumable.

---

### 16.7 `pipeline/stores/atomic.py`

Purpose: low-level atomic write helpers.

Recommended contents:

```text
atomic_write_json
atomic_write_text
atomic_write_bytes
replace_file
ensure_dir
```

Why it is necessary:

- Interrupted writes should not create corrupt status/output files.

---

### 16.8 `pipeline/stores/locking.py`

Purpose: optional local locking helpers.

Recommended contents:

```text
FileLock
acquire_run_lock
release_run_lock
```

Why it is necessary:

- Concurrent runs or retries can corrupt state without locking.

V0 note:

- Can be deferred, but plan for it.

---

### 16.9 `pipeline/stores/errors.py`

Purpose: store-specific errors.

Recommended contents:

```text
StoreError
ArtifactNotFoundError
RunNotFoundError
CorruptRunStoreError
ArtifactValidationError
LockError
```

---

## 17. `pipeline/sweep/`

Sweeps execute many trials from a base config.

V0 should support:

```text
grid sweeps
manual/list trials
```

Defer:

```text
random search
Bayesian optimization
population-based training
conditional search spaces
```

### 17.1 `pipeline/sweep/__init__.py`

Purpose: public sweep exports.

Recommended contents:

```python
from loom.pipeline.sweep.spec import SweepSpec
from loom.pipeline.sweep.runner import SweepRunner
```

---

### 17.2 `pipeline/sweep/spec.py`

Purpose: typed sweep specification.

Recommended contents:

```text
SweepSpec
SweepAxis
SweepMode
parse_sweep_spec
```

Why it is necessary:

- Sweep config should be parsed into a stable structure.

---

### 17.3 `pipeline/sweep/grid.py`

Purpose: grid expansion.

Recommended contents:

```text
expand_grid
cartesian_product_axes
```

Why it is necessary:

- Grid expansion is a distinct, testable algorithm.

---

### 17.4 `pipeline/sweep/manual.py`

Purpose: manual/list trial expansion.

Recommended contents:

```text
expand_manual_trials
```

Why `manual.py` instead of `list.py`:

- Avoids visually shadowing the built-in `list` type.
- More clearly communicates that trials are explicitly authored.

---

### 17.5 `pipeline/sweep/trials.py`

Purpose: trial-level structures.

Recommended contents:

```text
TrialSpec
TrialResult
make_trial_id
trial_overrides
trial_metadata
```

Why it is necessary:

- Each sweep trial becomes an independently resolved run.

---

### 17.6 `pipeline/sweep/runner.py`

Purpose: execute sweeps.

Recommended contents:

```text
SweepRunner
create_trials
run_trials
collect_results
```

Why it is necessary:

- Coordinates trial expansion and delegates each trial to `PipelineRunner`.

---

### 17.7 `pipeline/sweep/errors.py`

Purpose: sweep-specific errors.

Recommended contents:

```text
SweepConfigError
SweepExpansionError
TrialExecutionError
```

---

## 18. `plugins/`

The plugin package is optional, but useful for long-term extensibility. It centralizes entry point discovery so every registry does not invent its own plugin loading behavior.

### 18.1 `plugins/__init__.py`

Purpose: public plugin exports, if any.

Recommended contents:

```python
from loom.plugins.entrypoints import load_entry_points
```

---

### 18.2 `plugins/entrypoints.py`

Purpose: discover package entry points.

Recommended contents:

```text
load_entry_points
load_recipe_entry_points
load_codec_entry_points
load_executor_entry_points, later
```

Potential entry point groups:

```toml
[project.entry-points."loom.recipes"]
ubfc_physnet_128 = "rphys.recipes:UBFCPhysNetRecipe"

[project.entry-points."loom.codecs"]
json_v1 = "loom.io.codecs.json_codec:JSONCodec"
```

Why it is necessary:

- Downstream packages can extend the system without modifying generic source code.

Design concern:

- Entry point discovery should be explicit, not automatic on every import.
- Automatic discovery can slow imports and make tests less deterministic.

---

### 18.3 `plugins/errors.py`

Purpose: plugin-specific errors.

Recommended contents:

```text
PluginError
PluginLoadError
DuplicatePluginError
InvalidPluginError
```

---

## 19. `cli/`

The CLI should be a thin layer over the Python API.

### 19.1 `cli/__init__.py`

Purpose: package marker and optional exports.

Recommended contents: minimal.

---

### 19.2 `cli/main.py`

Purpose: command entry point.

Recommended contents:

```text
argument parser setup
subcommand registration
main function
```

Example command:

```bash
loom run experiment.yaml
```

Why it is necessary:

- Provides a generic command for debugging and low-level execution.

Design concern:

- Keep CLI generic. Domain packages can expose their own CLI wrappers.

---

### 19.3 `cli/validate.py`

Purpose: implement config validation command.

Command:

```bash
loom validate CONFIG
```

Responsibilities:

```text
load/compose config
validate shape
validate pipeline spec
print errors clearly
```

---

### 19.4 `cli/plan.py`

Purpose: inspect execution plan.

Command:

```bash
loom plan CONFIG
```

Responsibilities:

```text
compose config
build pipeline spec
compute plan
print stages to run/skip/force/rerun
```

Why it is necessary:

- Users should see what will happen before launching expensive jobs.

---

### 19.5 `cli/run.py`

Purpose: run a pipeline.

Command:

```bash
loom run CONFIG
```

Responsibilities:

```text
compose config
create runner
execute pipeline
return appropriate exit code
```

What to avoid:

- Do not implement runner logic here.

---

### 19.6 `cli/stage.py`

Purpose: run one stage independently.

Command:

```bash
loom stage run --run-dir RUN_DIR --stage STAGE_NAME
```

Why it is necessary:

- Subprocess and SLURM executors need stage-level entry points.

Responsibilities:

```text
load run metadata
load resolved config
construct stage
resolve inputs
execute stage
write outputs/status
```

---

### 19.7 `cli/sweep.py`

Purpose: run a sweep.

Command:

```bash
loom sweep SWEEP_CONFIG
```

Responsibilities:

```text
load sweep config
expand trials
execute or submit trials
summarize results
```

---

## 20. Design Considerations That Are Easy to Miss

### 20.1 Import direction must be enforced

Recommended dependency direction:

```text
primitives
  ↑
serialization
  ↑
io / config / pipeline subpackages
  ↑
cli
```

More specifically:

```text
refs.py, records.py, artifacts.py should not import pipeline.
pipeline should not import cli.
config should not import domain packages.
io should not import pipeline unless absolutely necessary.
serialization should not import io.
```

Use import-linter or custom tests later to enforce this.

### 20.2 Public API stability matters more than internal layout

Internal files can move. Public imports should remain stable.

Good public imports:

```python
from loom.refs import ResourceRef
from loom.pipeline import PipelineSpec, StageSpec
from loom.config import compose_config, instantiate
```

Avoid making users depend on deep internals unless necessary:

```python
from loom.pipeline.planning.resume import can_skip_stage
```

Deep imports are fine for advanced users, but the main API should stay shallow.

### 20.3 Treat configs as code

Dynamic `_target_` import can execute arbitrary Python code.

V0 should document this clearly:

```text
Do not run untrusted configs.
Treat configs as trusted project code.
```

Future hardening options:

```text
allow-listed modules
recipe-only mode
disabled importlib mode
signed configs
restricted execution environments
```

### 20.4 Make stages idempotent where possible

Stages should be written so rerunning them with the same inputs does not corrupt state.

Good behavior:

```text
write temporary outputs
validate outputs
atomically move to final paths
write outputs.json
write fingerprint.json
mark SUCCEEDED
```

Bad behavior:

```text
write final outputs directly
mark success before validation
leave partial outputs after failure
```

### 20.5 Fingerprints need a clear policy

A fingerprint should include enough information to determine semantic equivalence.

Typical stage fingerprint inputs:

```text
stage name
stage target
stage config
input artifact URI/checksum/fingerprint
code provenance
container/environment identity
relevant runtime options
```

Do not include noisy values unless they genuinely affect outputs:

```text
wall-clock timestamp
log path
temporary directory path
random run ID, unless it affects output
```

### 20.6 Checksums and fingerprints are different

Keep the distinction visible throughout the codebase:

```text
checksum    = stored bytes identity
fingerprint = production recipe identity
```

A file can have the same fingerprint but a different checksum if serialization changed. A file can have the same checksum but not enough provenance to know whether the stage should be skipped.

### 20.7 Runtime injection should be explicit

Do not encode runtime-only objects into static YAML.

Bad:

```yaml
artifact_store: <some Python object>
```

Good:

```python
instantiate(cfg.stage, inject={"artifact_store": artifact_store})
```

This matters for reproducibility and serializability.

### 20.8 Stores should be inspectable without Python

The run directory should be human-inspectable.

Prefer files like:

```text
status.json
inputs.json
outputs.json
fingerprint.json
artifacts.json
resolved.yaml
provenance.json
```

Avoid opaque-only databases in v0. A database can be added later as an index/cache, but the filesystem layout should remain understandable.

### 20.9 Plan for interrupted runs

Interrupted runs are normal on clusters.

Design for:

```text
RUNNING stages from old processes
missing outputs.json
partial artifact directories
stale locks
failed subprocesses
cancelled SLURM jobs
```

The planner should treat incomplete or inconsistent stage state as not reusable.

### 20.10 Think about concurrency before needing it

Even if v0 is single-process, the storage layer should not make future concurrency impossible.

Plan for:

```text
run-level locks
stage-level locks
atomic writes
unique temp paths
safe retries
```

Do not overbuild distributed locking early, but do not ignore local locking semantics.

### 20.11 Make errors path-aware

Config, pipeline, and serialization errors should include useful paths:

```text
config path: pipeline.stages[2].target._target_
stage: train
artifact: train.best_checkpoint
file: runs/example/stages/train/outputs.json
```

Generic errors without paths will become expensive to debug.

### 20.12 Separate authored config from resolved config

Authored config can be compact and recipe-based.

Resolved config should be explicit and saved.

This prevents recipes from becoming opaque magic. Users should be able to inspect exactly what ran.

### 20.13 Do not make `loom` a general workflow engine too early

Avoid early implementation of:

```text
conditional DAG generation
remote dashboards
advanced schedulers
Bayesian sweeps
DVC/Snakemake export
distributed artifact locking
schema migrations
container orchestration
```

The goal is controlled reproducible research pipelines, not replacing mature workflow systems.

### 20.14 Optional dependencies should stay optional

Suggested extras:

```toml
[project.optional-dependencies]
config = ["omegaconf>=2.3", "pydantic>=2"]
slurm = []
dev = ["pytest", "ruff", "mypy"]
```

Avoid hard dependencies on:

```text
torch
numpy
pandas
opencv-python
zarr
h5py
lightning
wandb
matplotlib
rphys-lib
```

### 20.15 Do not let registries become a second framework

Registries are useful, but they can become hidden global state.

Use them for genuine name-to-implementation resolution:

```text
recipes
codecs
sources
executors, later
```

Do not add registry aliases for every configurable object in v0. Full `_target_` construction is enough.

### 20.16 Use contract tests for extension points

Every protocol should have test helpers or dummy implementations.

Examples:

```text
DummyStage
WriteNumberStage
AddNumberStage
MultiplyNumberStage
JSONCodec roundtrip
LocalArtifactStore roundtrip
LocalRunStore status transitions
```

Downstream packages should be able to reuse some of these tests for their own stages/codecs/stores.

---

## 21. Recommended Public API

The public API should be small.

### 21.1 Primitive API

```python
from loom.refs import ResourceRef
from loom.records import Record, InMemoryManifest, ManifestView
from loom.artifacts import ArtifactRef
from loom.fingerprints import Fingerprint, hash_mapping
from loom.provenance import RunProvenance, StageProvenance
```

### 21.2 Config API

```python
from loom.config import compose_config, instantiate, register_recipe
```

Example:

```python
composed = compose_config(
    path="experiment.yaml",
    overlays=["overlays/small.yaml"],
    overrides=["model.hidden_dim=64"],
)

model = instantiate(composed.resolved["model"])
```

### 21.3 Pipeline API

```python
from loom.pipeline import PipelineSpec, StageSpec, StageContext
from loom.pipeline.execution import PipelineRunner
```

Example:

```python
runner = PipelineRunner()
runner.run(composed.resolved)
```

### 21.4 Store API

```python
from loom.pipeline.stores import ArtifactStore, RunStore, LocalArtifactStore, LocalRunStore
```

### 21.5 I/O API

```python
from loom.io.sources import DataSource, LocalFileSystemSource
from loom.io.codecs import Codec, CodecRegistry, JSONCodec, TextCodec, BytesCodec
```

---

## 22. Implementation Phases

Do not implement the entire target tree at once. Build in phases.

### Phase 0: package skeleton

Implement:

```text
pyproject.toml
src/loom/__init__.py
src/loom/py.typed
basic tests
ruff/mypy/pytest setup
```

### Phase 1: primitives and serialization

Implement:

```text
ids.py
refs.py
records.py
artifacts.py
provenance.py
fingerprints.py
protocols.py
errors.py
timestamps.py
serialization/plain.py
serialization/json.py
serialization/dataclasses.py
serialization/errors.py
```

### Phase 2: I/O basics

Implement:

```text
io/uris.py
io/sources/base.py
io/sources/local.py
io/codecs/base.py
io/codecs/json_codec.py
io/codecs/text_codec.py
io/codecs/bytes_codec.py
io/codecs/registry.py
```

### Phase 3: config composition

Implement:

```text
config/load.py
config/merge.py
config/overrides.py
config/interpolation.py
config/validation.py
config/redaction.py
config/provenance.py
config/compose.py
config/api.py
```

### Phase 4: recipes and instantiation

Implement:

```text
config/recipes/base.py
config/recipes/catalog.py
config/recipes/expansion.py
config/instantiate/targets.py
config/instantiate/recursive.py
config/instantiate/injection.py
```

### Phase 5: stores and local pipeline execution

Implement:

```text
pipeline/specs.py
pipeline/stage.py
pipeline/context.py
pipeline/status.py
pipeline/validation.py
pipeline/graph/*
pipeline/stores/artifact_store.py
pipeline/stores/run_store.py
pipeline/stores/local_artifacts.py
pipeline/stores/local_runs.py
pipeline/stores/atomic.py
pipeline/planning/plan.py
pipeline/planning/planner.py
pipeline/planning/resume.py
pipeline/executors/base.py
pipeline/executors/local.py
pipeline/execution/runner.py
pipeline/execution/lifecycle.py
```

### Phase 6: subprocess and CLI

Implement:

```text
pipeline/executors/subprocess.py
cli/main.py
cli/validate.py
cli/plan.py
cli/run.py
cli/stage.py
```

### Phase 7: SLURM

Implement:

```text
pipeline/executors/slurm.py
SLURM resource mapping
SBATCH generation
job dependency chaining
```

### Phase 8: sweeps

Implement:

```text
pipeline/sweep/spec.py
pipeline/sweep/grid.py
pipeline/sweep/manual.py
pipeline/sweep/trials.py
pipeline/sweep/runner.py
cli/sweep.py
```

### Phase 9: hardening

Implement or improve:

```text
path-aware errors
store locking
interrupted run recovery
artifact checksum validation
entry point plugin loading
schema compatibility checks
more provenance capture
redaction tests
contract tests for extension points
```

---

## 23. Testing Strategy

### 23.1 Primitive tests

```text
test_refs.py
test_records.py
test_artifacts.py
test_provenance.py
test_fingerprints.py
test_serialization.py
```

Test:

```text
ResourceRef serialization
Record helpers
ManifestView filters
ArtifactRef construction
fingerprint determinism
provenance serialization
```

### 23.2 I/O tests

```text
test_io_uris.py
test_local_source.py
test_codecs_json.py
test_codecs_registry.py
```

Test:

```text
file URI normalization
local source open/exists/stat/glob
JSON/Text/Bytes codec roundtrips
unknown codec errors
```

### 23.3 Config tests

```text
test_config_load.py
test_config_merge.py
test_config_overrides.py
test_config_compose.py
test_config_recipes.py
test_config_instantiate.py
test_config_redaction.py
```

Test:

```text
base config loading
overlay merge policy
CLI overrides
interpolation
recipe expansion
nested target instantiation
runtime injection
bad target errors
secret redaction
config provenance
```

### 23.4 Pipeline tests

```text
test_pipeline_specs.py
test_pipeline_validation.py
test_pipeline_graph.py
test_pipeline_planner.py
test_pipeline_runner.py
test_stage_lifecycle.py
```

Test:

```text
DAG validation
topological order
input binding
stage status transitions
resume skip
force stage
invalidated downstream stages
failure status writes
```

### 23.5 Store tests

```text
test_artifact_store.py
test_run_store.py
test_store_atomic.py
test_store_locking.py
```

Test:

```text
artifact save/load
status file writes
outputs file writes
atomic write behavior
corrupt store detection
```

### 23.6 Executor tests

```text
test_local_executor.py
test_subprocess_executor.py
test_slurm_script_generation.py
```

Test:

```text
local stage execution
subprocess command construction
subprocess failure capture
SBATCH script generation without actual cluster submission
```

### 23.7 End-to-end synthetic pipeline

Use dummy stages:

```text
WriteNumberStage
AddNumberStage
MultiplyNumberStage
ReportStage
```

Pipeline:

```text
write -> add -> multiply -> report
```

This proves the package works without any domain dependency.

---

## 24. Recommended v0 Minimal Source Tree

The scalable target structure is useful, but v0 should not overbuild. A practical v0 source tree is:

```text
src/loom/
  __init__.py
  py.typed
  ids.py
  refs.py
  records.py
  artifacts.py
  provenance.py
  fingerprints.py
  protocols.py
  errors.py
  timestamps.py

  serialization/
    __init__.py
    plain.py
    dataclasses.py
    json.py
    errors.py

  io/
    __init__.py
    uris.py
    errors.py
    sources/
      __init__.py
      base.py
      local.py
    codecs/
      __init__.py
      base.py
      json_codec.py
      text_codec.py
      bytes_codec.py
      registry.py

  config/
    __init__.py
    api.py
    load.py
    compose.py
    merge.py
    overrides.py
    validation.py
    redaction.py
    errors.py

  pipeline/
    __init__.py
    specs.py
    stage.py
    context.py
    status.py
    validation.py
    errors.py
    graph/
      __init__.py
      dag.py
      topology.py
      bindings.py
    stores/
      __init__.py
      artifact_store.py
      run_store.py
      local_artifacts.py
      local_runs.py
      atomic.py
    planning/
      __init__.py
      plan.py
      planner.py
      resume.py
    execution/
      __init__.py
      runner.py
      lifecycle.py
    executors/
      __init__.py
      base.py
      local.py
```

Defer initially:

```text
plugins/
cli/
config/recipes/
config/instantiate/
pipeline/sweep/
pipeline/executors/subprocess.py
pipeline/executors/slurm.py
pipeline/stores/locking.py
pipeline/planning/invalidation.py
serialization/yaml.py
serialization/schema.py
```

The first major milestone should be a fully working local synthetic pipeline with artifact save/load and resume behavior.

---

## 25. Final Recommendations

Use this structure because it balances present simplicity with future expansion:

```text
Top-level modules for public foundational concepts.
Subpackages for systems that will grow multiple implementations.
Top-level serialization package, separate from io.
I/O split into sources and codecs.
Pipeline split into graph, planning, execution, executors, stores, and sweep.
Specific errors live next to the subsystem that raises them.
CLI remains thin.
Plugins are explicit and optional.
```

Most important constraints:

```text
loom/corelib must remain useful and testable without importing domain packages.
Every pipeline stage consumes ArtifactRefs and produces ArtifactRefs.
V0 config supports full _target_ instantiation and named _recipe_ expansion only.
Resolved config and provenance must always be persisted.
Resume logic must be fingerprint-based, not just file-existence-based.
```

This gives the project a clean infrastructure kernel that can grow without turning into a domain-specific framework or a general-purpose workflow engine too early.
