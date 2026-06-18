# Phase 2 Expanded Plan: Primitives And Serialization

## Metadata

- Status: final expanded plan.
- Branch: `codex/add-primitives-serialization`.
- Worktree: `/home/samcantrill/work/loom-worktrees/add-primitives-serialization`.
- Expanded plan path: `docs/roadmap/stage-0/phases/add-primitives-serialization.md`.
- Full plan: `docs/roadmap/stage-0/implementation-plan.md`.
- Source phase: `Phase 2 - Primitives And Serialization`.
- Base branch: local `develop` at `af9bb3ebe64943343425735d2b84c0ba6a0c0cc7` (`docs: update implementation roadmap numbering`).
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no remaining blockers are recorded in the canonical v0 plan.
- Setup limitation: `git fetch origin` was unavailable in the sandbox because it could not write `.git/FETCH_HEAD`; manager preflight also recorded that pushing local `develop` to origin is unavailable because SSH public-key authentication is not configured. Per the planning prompt and manager instruction, this branch and worktree were created from local `develop`.
- Original checkout note: the source checkout has unrelated uncommitted documentation changes, including `docs/features/config.md`; this phase worktree was created from committed local `develop` and must not rely on or modify those uncommitted changes.
- Blockers: none.

## Objective

Implement the generic, domain-neutral primitives and serialization helpers used by later config, I/O, provenance, artifact store, pipeline, planning, execution, and resume phases.

The phase should replace Phase 1 skeleton exports with real low-level behavior for refs, artifacts, records/manifests, provenance value objects, stable fingerprints, package-wide generic protocols, and JSON/plain-data serialization. It must keep serialization separate from I/O, preserve cheap imports, and make checksum and fingerprint semantics visibly distinct.

## Full-Plan Context

The v0 plan builds `loom` as a source-tree-first, typed Python package with empty runtime dependencies until config implementation begins in Phase 4. Phase 1 already created import-safe package skeletons, broad error roots, simple ID aliases, UTC timestamp helpers, package import tests, and unsupported config stubs.

Phase 2 is the first behavior-bearing foundation phase. Later phases depend on these public objects:

- Config and recipes need stable plain-data conversion and fingerprints for resolved config/provenance.
- I/O and stores need `ResourceRef`, `ArtifactRef`, checksums, and JSON helpers without serialization importing I/O.
- Pipeline planning and execution need `Record`, manifests, provenance records, and semantic fingerprint helpers.
- Resume needs deterministic structured-data hashing, but the policy for selecting stage fingerprint inputs remains out of scope until pipeline planning/resume phases.

Controlling constraints:

- Keep `loom` domain-neutral; metadata is open but must be plain-data compatible.
- Keep `loom.__init__` cheap; only re-export implemented cheap primitives named by the canonical plan.
- Keep runtime dependencies empty and standard-library only in this phase.
- Keep import direction aligned with `docs/structure.md`: primitives and serialization must not import config, pipeline runners, CLI, plugin discovery, I/O sources/codecs, stores, or downstream project packages.
- Serialization converts Python objects to/from plain structured data and JSON strings; it must not perform filesystem writes, atomic writes, URI resolution, codec selection, or resource loading.
- Treat feature documents as detailed guidance where they do not widen the approved Phase 2 scope.

## Source Phase Summary

From `docs/roadmap/stage-0/implementation-plan.md`, Phase 2 is `Status: pending` with branch `codex/add-primitives-serialization` and PR `pending`.

Goal:

- Implement the generic value objects and serialization helpers used by every later subsystem.

Required scope:

- Add public primitives: `ResourceRef`, `ArtifactRef`, `Record`, `InMemoryManifest`, `ManifestView`, generic record filters, provenance models, package-wide generic protocols, and stable fingerprint helpers.
- Add serialization helpers for plain data, dataclass conversion, stable JSON, and schema-version checks.
- Preserve checksum and fingerprint as distinct concepts.

Required checkpoints:

- `ResourceRef` and `ArtifactRef` are frozen typed dataclasses with URI, type/key, schema version, checksum, fingerprint/provenance metadata where applicable, and no loading methods.
- `Record` is a frozen typed dataclass with generic resources, metadata, annotations, and provenance; it must not grow domain fields.
- `InMemoryManifest` rejects duplicate record IDs and preserves deterministic iteration.
- `ManifestView` supports lazy generic filters such as `HasResource`, `MetadataEquals`, and `MetadataIn`.
- Provenance models cover code, environment, run, and stage context without heavy dependency inspection.
- Lightweight provenance capture helpers cover git state when available, standard-library environment facts, selected package versions through `importlib.metadata`, command argv/cwd, and artifact input/output lineage.
- Provenance capture degrades to explicit unavailable or unknown values rather than requiring git, network access, or heavyweight dependency inspection.
- Fingerprint helpers use stable JSON and cryptographic hashes; never use Python built-in `hash()` for persisted identities.
- Serialization emits only plain structured data and keeps filesystem atomic writes out of this layer.

Acceptance criteria:

- Frozen typed primitives have deterministic equality and plain-data conversion.
- `ResourceRef.codec_key` round-trips when set, omitted, or explicitly `None`.
- Manifests reject duplicate record IDs and preserve deterministic iteration.
- Manifest views support generic filtering without domain semantics.
- Fingerprints are deterministic across mapping insertion order.
- Serialization outputs only plain structured data.
- Serialization does not import the I/O subsystem.

## In-Scope Work

- Add `src/loom/refs.py` with `ResourceRef` as a frozen slots dataclass.
  - Fields are exactly `uri`, `resource_type`, `codec_key`, `schema_version`, `checksum`, and `metadata`, with defaults documented below.
  - `ResourceRef` does not have a `fingerprint` field in Phase 2. Resource checksums identify referenced bytes; later stage fingerprint policy decides how to hash resource refs as semantic inputs.
  - `codec_key` deserialization must accept set, omitted, and explicit `None` inputs while normalizing the object field to `None` for omitted/null cases. Canonical serialization always emits the `codec_key` key.
  - Provide explicit `to_dict` and `from_dict` helpers that validate required fields and plain metadata.
  - Do not add `load`, `open`, `exists`, `save`, URI parsing, or codec behavior.
- Add `src/loom/artifacts.py` with `ArtifactRef` as a frozen slots dataclass.
  - Fields are exactly `artifact_id`, `uri`, `artifact_type`, `codec_key`, `schema_version`, `checksum`, `fingerprint`, `producer_stage`, `created_at`, and `metadata`, with defaults documented below.
  - Preserve checksum as stored-byte identity and fingerprint as semantic production-input identity.
  - Provide explicit `to_dict` and `from_dict` helpers only; stores/codecs own save/load behavior.
- Expand `src/loom/ids.py` with exactly these additional aliases: `ResourceType`, `Checksum`, and `Fingerprint`. Keep aliases as `str`; do not introduce `NewType` or wrapper IDs.
- Add `src/loom/fingerprints.py`.
  - Provide `Digest`, `Checksum`, `Fingerprint`, `HashAlgorithm`, `ParsedDigest`, `hash_bytes`, `hash_text`, `hash_plain_data`, `hash_mapping`, `parse_digest`, `validate_digest`, `format_digest`, and `compare_digests`.
  - Use `sha256` as the default and only required v0 algorithm.
  - Use `hashlib` and canonical JSON from `loom.serialization`; never use Python `hash()`, `repr()` fallbacks, current time, git state, environment, path normalization, or hidden inputs.
  - Keep file/stream hashing out of Phase 2; I/O and store phases own file access.
- Add `src/loom/protocols.py`.
  - Include only tiny package-wide protocols that are genuinely generic: `Validatable` and `Fingerprintable`.
  - Defer `PlainSerializable`; public object conversion remains explicit through `to_dict`/`from_dict` methods in this phase.
  - Keep subsystem protocols such as `Stage`, `Codec`, `DataSource`, `ArtifactStore`, `RunStore`, and `Executor` out of this module.
- Replace `src/loom/records/__init__.py` skeleton exports with real records package exports.
  - Expected files: `base.py`, `manifest.py`, `views.py`, `filters.py`, and `errors.py`.
  - Implement frozen `Record` with `record_id`, `resources`, `metadata`, `annotations`, and `provenance`.
  - Implement a structural manifest protocol, `InMemoryManifest`, `ManifestView`, `RecordFilter`, `HasResource`, `MetadataEquals`, and `MetadataIn`.
  - Preserve deterministic iteration, reject duplicate IDs, and avoid domain-specific filter semantics.
- Replace `src/loom/provenance/__init__.py` skeleton exports with generic provenance exports.
  - Expected files: `models.py`, `capture.py`, `git.py`, `environment.py`, `packages.py`, and `errors.py`.
  - Implement frozen provenance models for git/code, environment, dependencies, command, artifact lineage, stage provenance, and run provenance.
  - Include schema-version fields and plain-data-compatible metadata.
  - Implement lightweight capture helpers for explicit paths/package names/argv/cwd; capture helpers may call `git` through `subprocess` but must degrade to an explicit `capture_error` or missing/unknown field.
  - Default remote URL capture to off to avoid token leakage.
- Replace `src/loom/serialization/__init__.py` skeleton exports with plain-data, dataclass, JSON, schema, and error helpers.
  - Expected files: `plain.py`, `dataclasses.py`, `json.py`, `schema.py`, and `errors.py`.
  - Define `PlainData`, `is_plain_data`, `ensure_plain_data`, `to_plain_data`, dataclass conversion helpers, `stable_json_dumps`, `stable_json_bytes`, `json_dumps_pretty`, `json_loads`, `get_schema_version`, `require_schema_version`, and `check_supported_schema`.
  - Allow only JSON/YAML-compatible plain data: `None`, `bool`, finite `int`/`float`, `str`, `list`, and `dict[str, plain]`.
  - Normalize tuples to lists and mappings to dicts only when keys are strings.
  - Reject non-finite floats, non-string mapping keys, sets, bytes, `Path`, `datetime`, callables, and arbitrary objects without explicit conversion.
  - Provide path-aware errors.
  - Do not add write helpers in Phase 2. Local file reads are not required either; JSON string parsing/dumping is sufficient for this phase and avoids blurring the I/O boundary.
- Update `src/loom/errors.py` only as needed for Phase 2 root error names.
  - Add `ResourceError`, `SerializationError`, `FingerprintError`, and `ProvenanceError`.
  - Keep concrete subsystem exceptions near their modules and rooted in the broad hierarchy.
- Update `src/loom/__init__.py` only with cheap, implemented public primitive exports allowed by the canonical plan.
  - Expected exports after Phase 2: `__version__`, `ResourceRef`, `InMemoryManifest`, `ManifestView`, `Record`, `ArtifactRef`, `Fingerprint`, and `hash_mapping`.
  - Do not import config, pipeline, I/O, stores, CLI, plugins, or optional dependencies from `loom.__init__`.
- Add focused package and unit tests for all new behavior and import boundaries.
- Keep implementation and tests domain-neutral.

## Out-of-Scope Work

- No I/O sources, URI parsers, codec registries, JSON/text/bytes codecs, local file sources, artifact stores, run stores, filesystem writes, or atomic write helpers.
- No config composition, recipe expansion, target instantiation, validation of authored config files, redaction policy, or hard config dependencies.
- No pipeline specs, graph validation, stage protocols, stage contexts, execution, planning, resume policy, selectors, stores, executors, sweeps, plugins, or functional CLI behavior.
- No schema migrations; Phase 2 schema helpers validate versions only.
- No domain-specific resource classes, artifact classes, manifest filters, metadata schemas, dataset adapters, model/report/checkpoint helpers, or downstream fixtures.
- No strong ID wrapper classes, closed enums for resource/artifact types, or global registries for records/resources/artifacts.
- No file hashing helper that opens paths, no stream hashing, no remote URI reading, and no filesystem-backed manifests.
- No automatic dependency scanning, `pip freeze`, SBOM generation, full import graph scanning, environment-variable dumps, remote metadata discovery, network access, or heavy provenance inspection.
- No YAML helpers requiring optional dependencies in this phase. If a YAML module stub is added to preserve package shape, importing core serialization must not require YAML dependencies and no YAML behavior should be tested as Phase 2 acceptance.
- No broad refactors, roadmap/status updates, PR body creation, full validation, or PR opening during this planning stage.

## Assumptions

- The local `develop` commit `af9bb3ebe64943343425735d2b84c0ba6a0c0cc7` is the manager-approved Phase 2 base because remote synchronization is unavailable in this environment.
- Public primitives should use `@dataclass(frozen=True, slots=True)` unless the executor discovers a Python typing limitation; if so, the executor must stop and report the blocker rather than silently changing public shapes.
- Public persisted shapes should use explicit `to_dict`/`from_dict` methods rather than generic magic reconstruction.
- `schema_version` on `ResourceRef` and `ArtifactRef` describes the referenced resource/artifact payload schema, not the document schema for the ref object itself.
- Provenance model `schema_version` fields describe the provenance document shape.
- Metadata, annotations, and provenance extension fields are project-owned but must be plain-data compatible.
- `ResourceRef.codec_key` should serialize with a `codec_key` key whose value may be `None`; `from_dict` should also accept older or author-supplied data where `codec_key` is absent and treat it as `None`. Omission is not preserved after canonical serialization.
- `Record.resources` should be keyed by `ResourceKey` and hold `ResourceRef` values. `Record.from_dict` must reconstruct serialized resource dicts explicitly through `ResourceRef.from_dict`.
- `Record.provenance` can remain generic plain-data metadata in Phase 2 rather than depending on full `RunProvenance` or `StageProvenance`; later pipeline phases decide which provenance records are attached to runtime records.
- `InMemoryManifest` iteration preserves constructor input order after normalization to a tuple. It must not sort records by `record_id`; tests must prove input order is preserved and duplicate IDs fail.
- `ManifestView` composes filters lazily over an underlying manifest iterable and preserves source iteration order for passing records. It must provide `materialize() -> InMemoryManifest`; `to_dict()` serializes the materialized manifest, and serializable filter definitions are out of scope.
- Provenance capture helpers are allowed to execute local `git` commands through `subprocess` because they gather explicit local facts, but they must not require git to be installed and must not access the network.
- `loom.fingerprints` may import `loom.serialization`; `loom.serialization` must not import `loom.fingerprints` to avoid cycles.
- Existing Phase 1 config stubs remain unsupported and unchanged except for any import-boundary tests that need to verify they still do not load new primitive modules eagerly.

## Decision-Complete Public Contract

The executor must treat this section as the implementation contract. If a needed public shape conflicts with this section, stop and report the blocker instead of widening the phase.

### Module Layout And Exports

- `src/loom/refs.py`
  - Public `__all__`: `["ResourceRef", "ResourceRefError"]`.
- `src/loom/artifacts.py`
  - Public `__all__`: `["ArtifactRef", "ArtifactValidationError"]`.
- `src/loom/fingerprints.py`
  - Public `__all__`: `["Digest", "Checksum", "Fingerprint", "HashAlgorithm", "ParsedDigest", "FingerprintError", "UnsupportedHashAlgorithmError", "InvalidDigestError", "FingerprintInputError", "FingerprintComparisonError", "hash_bytes", "hash_text", "hash_plain_data", "hash_mapping", "parse_digest", "validate_digest", "format_digest", "compare_digests"]`.
- `src/loom/protocols.py`
  - Public `__all__`: `["Validatable", "Fingerprintable"]`.
- `src/loom/records/__init__.py`
  - Public `__all__`: `["Record", "Manifest", "InMemoryManifest", "ManifestView", "RecordFilter", "HasResource", "MetadataEquals", "MetadataIn", "RecordError", "RecordNotFoundError", "ManifestError", "DuplicateRecordError"]`.
- `src/loom/provenance/__init__.py`
  - Public `__all__`: `["GitProvenance", "CodeProvenance", "EnvironmentProvenance", "DependencyProvenance", "CommandProvenance", "ArtifactLineage", "StageProvenance", "RunProvenance", "ProvenanceCaptureOptions", "ProvenanceError", "ProvenanceCaptureError", "ProvenanceValidationError", "ProvenanceRedactionError", "capture_git_provenance", "capture_code_provenance", "capture_environment_provenance", "capture_dependency_provenance", "capture_command_provenance", "capture_artifact_lineage", "capture_run_provenance"]`.
- `src/loom/serialization/__init__.py`
  - Public `__all__`: `["PlainData", "SerializationError", "DeserializationError", "PlainDataError", "SchemaVersionError", "is_plain_data", "ensure_plain_data", "to_plain_data", "dataclass_to_dict", "dataclass_from_dict", "stable_json_dumps", "stable_json_bytes", "json_dumps_pretty", "json_loads", "get_schema_version", "require_schema_version", "check_supported_schema"]`.
- `src/loom/__init__.py`
  - Public `__all__`: `["__version__", "ResourceRef", "InMemoryManifest", "ManifestView", "Record", "ArtifactRef", "Fingerprint", "hash_mapping"]`.
  - These top-level imports must stay cheap and must not import config, pipeline, CLI, I/O, stores, plugins, or optional dependencies.

### Error Hierarchy

- Update `loom.errors` to export exactly:
  `LoomError`, `ValidationError`, `ContractError`, `ResourceError`, `ArtifactError`, `ConfigError`, `SerializationError`, `FingerprintError`, `PipelineError`, `ExecutionError`, `ProvenanceError`, and `IOErrorBase`.
- Keep `IOErrorBase` for Phase 1 compatibility; do not rename it to `LoomIOError` in Phase 2.
- Do not implement the richer `ErrorContext` design in this phase. Path-aware errors must be expressed through concise messages; local error attributes are allowed only when a unit test asserts them.
- Concrete Phase 2 errors:
  - `ResourceRefError(ResourceError, ValidationError)` in `loom.refs`.
  - `ArtifactValidationError(ArtifactError, ValidationError)` in `loom.artifacts`.
  - `RecordError(ValidationError)`, `RecordNotFoundError(RecordError)`, `ManifestError(RecordError)`, and `DuplicateRecordError(ManifestError)` in `loom.records.errors`.
  - `loom.serialization.errors` re-exports the shared `SerializationError` root and defines `DeserializationError(SerializationError)`, `PlainDataError(SerializationError)`, and `SchemaVersionError(DeserializationError)`. Do not create a second incompatible `SerializationError` class.
  - `loom.fingerprints` re-exports the shared `FingerprintError` root and defines `UnsupportedHashAlgorithmError(FingerprintError)`, `InvalidDigestError(FingerprintError)`, `FingerprintInputError(FingerprintError)`, and `FingerprintComparisonError(FingerprintError)`.
  - `loom.provenance.errors` re-exports the shared `ProvenanceError` root and defines `ProvenanceCaptureError(ProvenanceError)`, `ProvenanceValidationError(ProvenanceError)`, and `ProvenanceRedactionError(ProvenanceError)`.

### Primitive Dataclasses And Serialized Shapes

- Use `@dataclass(frozen=True, slots=True)` for public value objects. If a Python typing limitation makes that impossible, stop and report the blocker instead of changing the public shape.
- Validate structural invariants during construction and deserialization. Copy incoming mappings/sequences into new containers so later caller mutation cannot alter object state. Deep-freezing nested plain data is not required unless the implementation chooses it consistently.
- `ResourceRef` fields and defaults:
  - `uri: str` required, non-empty.
  - `resource_type: ResourceType` required, non-empty.
  - `codec_key: CodecKey | None = None`; if present it must be a non-empty string.
  - `schema_version: int = 1`; must be a positive integer and means referenced resource payload schema, not the `ResourceRef` object schema.
  - `checksum: Checksum | None = None`; if present it must pass digest validation.
  - `metadata: Mapping[str, PlainData] = field(default_factory=dict)`.
- `ResourceRef.to_dict()` canonical shape always includes every key:

```python
{
    "uri": "file:///data/project/input.jsonl",
    "resource_type": "jsonl",
    "codec_key": "jsonl.v1",
    "schema_version": 1,
    "checksum": "sha256:<64 lowercase hex>",
    "metadata": {"split": "train"},
}
```

- `ResourceRef.from_dict()` rejects unknown fields, requires `uri` and `resource_type`, accepts missing optional/default fields, and specifically handles:
  - set `codec_key`: returns the string and `to_dict()` emits the string.
  - explicit `{"codec_key": None}`: returns `codec_key is None` and `to_dict()` emits `"codec_key": None`.
  - omitted `codec_key`: returns `codec_key is None` and `to_dict()` emits canonical `"codec_key": None`; omission is accepted for compatibility but not preserved.
- `ArtifactRef` fields and defaults:
  - `artifact_id: ArtifactID` required, non-empty.
  - `uri: str` required, non-empty. Do not parse or normalize URIs in Phase 2.
  - `artifact_type: ArtifactType` required, non-empty.
  - `codec_key: CodecKey | None = None`.
  - `schema_version: int = 1`; must be positive and means artifact payload schema, not the `ArtifactRef` object schema.
  - `checksum: Checksum | None = None`; stored-byte identity.
  - `fingerprint: Fingerprint | None = None`; semantic production identity.
  - `producer_stage: StageID | None = None`.
  - `created_at: str | None = None`; if present, validate with existing UTC timestamp parsing.
  - `metadata: Mapping[str, PlainData] = field(default_factory=dict)`.
- `ArtifactRef.to_dict()` canonical shape always includes every key:

```python
{
    "artifact_id": "train/best_checkpoint",
    "uri": "file:///runs/example/artifacts/train/best.ckpt",
    "artifact_type": "checkpoint",
    "codec_key": None,
    "schema_version": 1,
    "checksum": "sha256:<64 lowercase hex>",
    "fingerprint": "sha256:<64 lowercase hex>",
    "producer_stage": "train",
    "created_at": "2026-05-02T05:30:00Z",
    "metadata": {"epoch": 42},
}
```

- `ArtifactRef.from_dict()` rejects unknown fields, accepts missing optional/default fields, validates checksum and fingerprint with the same digest syntax, and keeps their field names and assertions separate.
- `Record` fields and defaults:
  - `record_id: RecordID` required, non-empty.
  - `resources: Mapping[ResourceKey, ResourceRef] = field(default_factory=dict)`.
  - `metadata: Mapping[str, PlainData] = field(default_factory=dict)`.
  - `annotations: Mapping[str, PlainData] = field(default_factory=dict)`.
  - `provenance: Mapping[str, PlainData] = field(default_factory=dict)`.
- `Record.to_dict()` canonical shape:

```python
{
    "record_id": "sample-001",
    "resources": {"input": ResourceRef(...).to_dict()},
    "metadata": {"split": "train"},
    "annotations": {},
    "provenance": {},
}
```

- `Record.from_dict()` rejects unknown fields, reconstructs resources only through `ResourceRef.from_dict()`, and supports helper methods `has_resource(key)`, `get_resource(key, default=None)`, and `require_resource(key)`.
- `InMemoryManifest` fields:
  - `records: Iterable[Record]` accepted by construction and normalized to `tuple[Record, ...]`.
  - `metadata: Mapping[str, PlainData] = field(default_factory=dict)`.
  - It rejects duplicate `record_id` values at construction with `DuplicateRecordError`.
  - Iteration order is constructor/serialized record order, not sorted order.
  - `get(record_id)` returns `Record | None`; `require(record_id)` raises `RecordNotFoundError`; `__len__` returns record count.
- `InMemoryManifest.to_dict()` canonical shape:

```python
{
    "schema_version": 1,
    "records": [record.to_dict(), ...],
    "metadata": {},
}
```

- `InMemoryManifest.from_dict()` requires supported `schema_version == 1`, rejects unknown fields, reconstructs records in listed order, and rejects duplicate IDs.
- `ManifestView` fields:
  - `source: Manifest`.
  - `filters: tuple[RecordFilter, ...] = ()`.
  - `metadata: Mapping[str, PlainData] = field(default_factory=dict)`.
  - Iteration applies filters in order and preserves source order for records that pass.
  - `filter(predicate)` returns a new `ManifestView` with the predicate appended.
  - `get(record_id)` returns the matching source record only if it passes filters; `require(record_id)` raises `RecordNotFoundError`; `__len__` may count by scanning.
  - `materialize()` returns an `InMemoryManifest` with passing records in view order and view metadata.
  - `to_dict()` serializes the materialized manifest. Do not implement serializable filter definitions.
- Record filters:
  - `RecordFilter` is a structural protocol with `__call__(record: Record) -> bool`.
  - `HasResource(key: str)` validates a non-empty key and checks resource presence.
  - `MetadataEquals(key: str, value: PlainData)` validates a non-empty key and plain value, then compares `record.metadata.get(key) == value`.
  - `MetadataIn(key: str, values: Iterable[PlainData])` validates a non-empty key, normalizes values to `tuple[PlainData, ...]`, and uses equality membership. Use a tuple instead of a set so unhashable plain data remains valid and ordering is deterministic.

### Serialization Contract

- `PlainData` includes only `None`, `bool`, finite `int`/`float`, `str`, `list[PlainData]`, and `dict[str, PlainData]`.
- `to_plain_data` conversion precedence is: already-valid plain leaves, mappings, lists/tuples, objects with public zero-argument `to_dict()`, dataclass instances, then error. Return new containers and never mutate inputs.
- Reject non-string mapping keys, non-finite floats, sets/frozensets, bytes/bytearray, `Path`, `datetime`, callables, arbitrary objects without `to_dict()`, and all NumPy/Pydantic-specific special cases.
- `stable_json_dumps(value)` must call `to_plain_data`, use `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, `allow_nan=False`, and return no trailing newline.
- `stable_json_bytes(value)` encodes `stable_json_dumps(value)` as UTF-8.
- `json_dumps_pretty(value, *, sort_keys=True)` must call `to_plain_data`, use two-space indentation, `ensure_ascii=False`, `allow_nan=False`, and include one trailing newline.
- `json_loads(text, *, path="<string>")` parses JSON text only, wraps invalid JSON in `DeserializationError`, and validates through `ensure_plain_data`.
- Do not implement `read_json`, `write_json`, YAML helpers, path opening, URI handling, or atomic writes in Phase 2.
- Schema helpers:
  - `get_schema_version(data, *, field="schema_version", path="$") -> int` requires mapping input, present integer field, and positive value.
  - `require_schema_version(data, expected, *, field="schema_version", path="$") -> None` raises `SchemaVersionError` when actual differs.
  - `check_supported_schema(data, *, supported, field="schema_version", path="$") -> int` returns the actual version only when it is in `supported`.
  - No migrations or compatibility rewriting.

### Digest And Fingerprint Contract

- Type aliases: `Digest = str`, `Checksum = str`, `Fingerprint = str`, and `HashAlgorithm = str`.
- `ParsedDigest` is a frozen slots dataclass with fields `algorithm: str` and `hexdigest: str`.
- Persisted digest syntax is exactly `sha256:<64 lowercase hex characters>` for Phase 2.
- Supported algorithms are exactly `{"sha256"}`. `sha256` is the default.
- `validate_digest(value, *, algorithms=None)` requires a string, algorithm prefix, supported algorithm, lowercase hex, and the expected length for sha256; it returns the unchanged normalized digest string.
- `parse_digest(value)` validates then returns `ParsedDigest(algorithm="sha256", hexdigest="<hex>")`.
- `format_digest(algorithm, hexdigest)` validates supported algorithm and hex length, normalizes algorithm and hex to lowercase, and returns canonical `algorithm:hex`.
- `compare_digests(left, right)` returns `False` when either side is `None`, validates both non-`None` values, and compares canonical strings with `hmac.compare_digest`.
- `hash_bytes(data, *, algorithm="sha256")` accepts `bytes` only and returns a canonical digest.
- `hash_text(text, *, algorithm="sha256", encoding="utf-8")` requires `str`, encodes with the explicit encoding, and delegates to `hash_bytes`.
- `hash_plain_data(value, *, algorithm="sha256")` uses `stable_json_bytes(value)` and `hash_bytes`.
- `hash_mapping(mapping, *, algorithm="sha256")` first requires a top-level mapping, then delegates to `hash_plain_data`.
- Do not add `hash_file` or `hash_stream` in Phase 2.

### Provenance Contract

- Provenance models are frozen slots dataclasses with explicit `to_dict()` and `from_dict()` where persisted.
- Every provenance model `to_dict()` emits `schema_version`, `kind`, and all public fields. Every `from_dict()` requires supported `schema_version == 1`, validates the exact `kind`, rejects unknown fields, and reconstructs nested provenance models explicitly.
- Provenance `kind` values are exactly `loom.git_provenance`, `loom.code_provenance`, `loom.environment_provenance`, `loom.dependency_provenance`, `loom.command_provenance`, `loom.artifact_lineage`, `loom.stage_provenance`, and `loom.run_provenance`.
- Provenance timestamp fields such as `created_at`, `started_at`, and `finished_at` must be UTC metadata strings accepted by `parse_timestamp`.
- Model fields:
  - `GitProvenance`: `repository_root: str | None = None`, `commit: str | None = None`, `branch: str | None = None`, `is_dirty: bool | None = None`, `has_untracked: bool | None = None`, `remote_url: str | None = None`, `capture_error: str | None = None`, `metadata: Mapping[str, PlainData] = field(default_factory=dict)`, `schema_version: int = 1`.
  - `CodeProvenance`: `git: GitProvenance | None = None`, `package_name: str | None = None`, `package_version: str | None = None`, `source_paths: tuple[str, ...] = ()`, `metadata: Mapping[str, PlainData] = field(default_factory=dict)`, `schema_version: int = 1`.
  - `EnvironmentProvenance`: `python_version: str` required, `python_executable: str | None = None`, `platform: str | None = None`, `machine: str | None = None`, `processor: str | None = None`, `hostname: str | None = None`, `user: str | None = None`, `selected_env: Mapping[str, str] = field(default_factory=dict)`, `container: Mapping[str, PlainData] = field(default_factory=dict)`, `metadata: Mapping[str, PlainData] = field(default_factory=dict)`, `schema_version: int = 1`.
  - `DependencyProvenance`: `packages: Mapping[str, str] = field(default_factory=dict)`, `missing_packages: tuple[str, ...] = ()`, `metadata: Mapping[str, PlainData] = field(default_factory=dict)`, `schema_version: int = 1`. Do not add lockfile reading in Phase 2.
  - `CommandProvenance`: `argv: tuple[str, ...] = ()`, `cwd: str | None = None`, `launcher: str | None = None`, `command_string: str | None = None`, `metadata: Mapping[str, PlainData] = field(default_factory=dict)`, `schema_version: int = 1`. Capture does not derive `command_string`; callers may supply it later through explicit construction.
  - `ArtifactLineage`: `artifact_id: ArtifactID` required, `artifact_type: ArtifactType | None = None`, `uri: str | None = None`, `artifact_schema_version: int | None = None`, `producer_stage: StageID | None = None`, `producer_fingerprint: Fingerprint | None = None`, `checksum: Checksum | None = None`, `metadata: Mapping[str, PlainData] = field(default_factory=dict)`, `schema_version: int = 1`.
  - `StageProvenance`: `run_id: RunID` required, `stage_name: StageID` required, `status: str` required, `attempt: int` required and positive, `target: str | None = None`, `started_at: str | None = None`, `finished_at: str | None = None`, `duration_seconds: float | None = None`, `fingerprint: Mapping[str, PlainData] | None = None`, `input_artifacts: Mapping[str, PlainData] = field(default_factory=dict)`, `output_artifacts: Mapping[str, PlainData] = field(default_factory=dict)`, `executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)`, `code: CodeProvenance | None = None`, `environment: EnvironmentProvenance | None = None`, `metadata: Mapping[str, PlainData] = field(default_factory=dict)`, `schema_version: int = 1`.
  - `RunProvenance`: `run_id: RunID` required, `created_at: str` required, `run_dir: str | None = None`, `command: CommandProvenance | None = None`, `code: CodeProvenance | None = None`, `environment: EnvironmentProvenance | None = None`, `dependencies: DependencyProvenance | None = None`, `config: Mapping[str, PlainData] = field(default_factory=dict)`, `stages: Mapping[str, PlainData] = field(default_factory=dict)`, `artifacts: Mapping[str, PlainData] = field(default_factory=dict)`, `metadata: Mapping[str, PlainData] = field(default_factory=dict)`, `schema_version: int = 1`.
  - `ProvenanceCaptureOptions`: `capture_git: bool = True`, `git_root: str | None = None`, `include_git_remote: bool = False`, `capture_environment: bool = True`, `env_keys: tuple[str, ...] = ()`, `include_user: bool = False`, `capture_dependencies: bool = True`, `packages: tuple[str, ...] = ("loom",)`, `capture_command: bool = True`, `strict: bool = False`.
- `capture_git_provenance(path, *, include_remote=False, strict=False)` may run bounded local `git` subprocess commands only. It must not fetch, push, contact remotes, or require git. Missing git, non-repository paths, command failures, and timeouts return `GitProvenance(capture_error=...)` unless `strict=True`, in which case they raise `ProvenanceCaptureError`.
- Dirty-state policy: `is_dirty` is `True` when `git status --porcelain` has tracked-file changes; `has_untracked` is `True` when any porcelain line starts with `??`. Do not persist full diffs.
- Remote URL policy: default `remote_url` is `None`. Capture `remote.origin.url` only when `include_remote=True`, and redact credentials before storing.
- `capture_code_provenance(project_root=None, package_name=None, include_git_remote=False, strict=False)` captures git only when `project_root` is supplied, captures package version only with `importlib.metadata.version(package_name)`, never imports the package, and records a missing package as `package_version=None` plus metadata/capture context unless strict mode raises.
- `capture_environment_provenance(env_keys=(), include_user=False)` captures standard-library Python/platform facts, selected allow-listed environment keys only, user only when requested, and redacts selected env values for secret-like key names containing `token`, `secret`, `password`, `api_key`, `credential`, or `private_key`.
- `capture_dependency_provenance(packages=("loom",), strict=False)` captures explicitly named package versions through `importlib.metadata.version`, records missing names in `missing_packages`, and does not run `pip freeze`, scan imports, inspect lockfiles, or import packages.
- `capture_command_provenance(argv=None, cwd=None, launcher=None)` uses explicit values when supplied, otherwise `sys.argv` and `Path.cwd()`, and writes no files.
- `capture_artifact_lineage(ref: ArtifactRef, *, metadata=None)` copies only ref fields into `ArtifactLineage`; it must not check existence or read artifact content.
- `capture_run_provenance(run_id, run_dir=None, options=None, command=None, config=None, metadata=None)` aggregates selected capture helpers, fills `created_at` with `utc_timestamp()`, writes nothing, and does not import config, pipeline, stores, or I/O. A supplied `command` is used as-is; otherwise command capture runs only when `options.capture_command` is true.

## Design Impact

This phase creates the public vocabulary shared by the rest of v0. The main design impact is that later subsystems can exchange resource refs, artifact refs, records, provenance summaries, and fingerprints as immutable plain-data-compatible values instead of inventing subsystem-specific document shapes.

The phase also establishes serialization as the deterministic plain-data boundary. That keeps fingerprints, run documents, provenance, records, and artifact indexes consistent while preserving a clean separation from I/O and store policy.

Import-direction impact:

- `refs`, `records`, `artifacts`, `protocols`, `ids`, `errors`, and `timestamps` remain standard-library-only or depend only on lower-level `loom` helpers.
- `serialization` may depend on primitive public types only through explicit conversion hooks and must not import `loom.io`.
- `fingerprints` depends on `serialization` for canonical structured-data hashing.
- `provenance` may depend on primitives, timestamps, serialization, and fingerprints, but not config, pipeline, stores, I/O, or project packages.

## Future Compatibility

- Frozen dataclasses with explicit conversion helpers give later store, pipeline, and CLI code stable serialized shapes while allowing internal implementation files to move behind package exports.
- Open string type labels for resources/artifacts allow downstream packages to define domain semantics without subclassing `loom` internals.
- Plain metadata fields allow project-specific context while keeping persisted indexes JSON/YAML-safe.
- Digest strings include algorithm prefixes so future hash algorithms can be introduced without silently comparing incompatible values.
- Schema-version validation helpers create a clear place for future migration support without implementing migration behavior prematurely.
- Manifest protocols and views leave room for filesystem-backed or database-backed manifests after v0 without forcing them into Phase 2.
- Package-wide protocols remain tiny, so subsystem-specific contracts can be added later next to their owning modules without import coupling.
- Provenance capture models are generic enough for future subprocess, SLURM, container, and remote-store phases to reuse without adding those executor concerns now.

## Alternatives Rejected

- Loading behavior on `ResourceRef` or `ArtifactRef`: rejected because loading belongs to I/O sources, codecs, artifact stores, or project code.
- Closed enums for resource/artifact types: rejected because `loom` must stay domain-neutral and downstream packages own concrete artifact/resource semantics.
- Strong identifier wrapper classes or `NewType`: rejected because the approved v0 plan starts with simple aliases and validates at object boundaries.
- Hashing with Python `hash()`, `repr()`, object IDs, current time, path normalization, git state, or environment state: rejected because persisted identities must be deterministic and explicit.
- Combining checksum and fingerprint fields: rejected because checksums describe stored bytes while fingerprints describe semantic production inputs.
- File writes, atomic writes, run-store JSON helpers, or artifact persistence in serialization: rejected because stores and I/O own filesystem policy.
- Automatic arbitrary-object deserialization: rejected because public persisted types should reconstruct through explicit code paths.
- Full schema migration framework: rejected because v0 only needs validation and clear version errors.
- Automatic full dependency/environment capture: rejected because it is slow, noisy, leak-prone, and outside lightweight provenance scope.
- Contract tests for future extension points: rejected for this phase because Phase 2 adds generic protocols but not concrete codec/source/stage/store/executor implementations.
- Integration/e2e tests for pipeline workflows: rejected because Phase 2 does not implement config, pipeline, stores, or execution.

## Debt Introduced

- Schema-version helpers are validation-only. Revisit when a persisted document shape needs a migration path or compatibility shim.
- `InMemoryManifest` is the only manifest implementation. Revisit if later local execution or downstream examples need filesystem-backed, streaming, or database-backed manifests.
- Provenance capture remains lightweight and selected. Revisit if later run-store/resume work requires lockfile digests, project-supplied provenance providers, event timelines, or redacted/full provenance views.
- Fingerprint helpers do not include stage fingerprint policy or fingerprint diff explanations. Revisit in the planning/resume phase where semantic input selection is owned.
- No file/stream checksum helper is planned for Phase 2. Revisit in the local artifact store phase, where file access and URI policy are concrete.
- YAML helper behavior remains deferred to config or a later serialization need because Phase 2 keeps runtime dependencies empty.

Each debt item has a concrete owning future phase or trigger. No debt should be introduced merely to avoid Phase 2 unit coverage.

## Reviewability

The implementation PR should be reviewable as low-level API behavior plus focused tests. Reviewers should be able to inspect:

- public dataclass fields, immutability, validation, and serialized shapes;
- absence of loading/opening/saving methods on refs and artifacts;
- manifest duplicate handling, deterministic iteration, and lazy filter behavior;
- stable JSON and deterministic hash behavior across mapping insertion order;
- path-aware serialization errors for invalid nested values;
- provenance capture degradation when git or packages are unavailable;
- import-boundary tests proving serialization does not import I/O and `import loom` stays cheap;
- absence of runtime dependencies and future-phase behavior.

Avoid mixing this work with config, I/O, store, pipeline, or CLI implementation. If implementing the phase requires changing public API shape beyond this plan, the executor should stop and report the blocker rather than widening scope.

## Files And Areas To Inspect

- `docs/roadmap/stage-0/implementation-plan.md`, especially Phase 2 and the plan quality gate.
- `docs/structure.md` sections "Target Source Tree", "Import and Dependency Shape", "Public API Policy", "Core Model", "Serialization", "Provenance and Resume", and "Test Layout".
- `docs/loom.md` sections 6.1, 6.2, 6.3, 10, 11, and 12.
- `docs/features/core-model.md` for refs, records, manifests, filters, identifiers, and checksum/fingerprint terminology.
- `docs/features/serialization.md` for plain-data rules, dataclass conversion, JSON helpers, schema-version checks, and serialization/I/O boundaries.
- `docs/features/artifacts.md` for `ArtifactRef` fields, checksum/fingerprint semantics, and no-loading behavior.
- `docs/features/fingerprints.md` for digest formats, hash helpers, and deterministic structured-data hashing.
- `docs/features/provenance.md` for provenance models and lightweight capture policy.
- `docs/features/protocols.md` for package-wide protocol limits.
- `docs/features/timestamps.md` for UTC metadata conventions.
- `docs/features/errors.md` for shared error-root guidance.
- `docs/features/testing.md` and `tests/README.md` for suite layout and obligations.
- Existing Phase 1 modules:
  - `src/loom/__init__.py`
  - `src/loom/ids.py`
  - `src/loom/errors.py`
  - `src/loom/timestamps.py`
  - `src/loom/records/__init__.py`
  - `src/loom/provenance/__init__.py`
  - `src/loom/serialization/__init__.py`
- New or changed implementation areas expected for Phase 2:
  - `src/loom/refs.py`
  - `src/loom/artifacts.py`
  - `src/loom/fingerprints.py`
  - `src/loom/protocols.py`
  - `src/loom/records/base.py`
  - `src/loom/records/manifest.py`
  - `src/loom/records/views.py`
  - `src/loom/records/filters.py`
  - `src/loom/records/errors.py`
  - `src/loom/provenance/models.py`
  - `src/loom/provenance/capture.py`
  - `src/loom/provenance/git.py`
  - `src/loom/provenance/environment.py`
  - `src/loom/provenance/packages.py`
  - `src/loom/provenance/errors.py`
  - `src/loom/serialization/plain.py`
  - `src/loom/serialization/dataclasses.py`
  - `src/loom/serialization/json.py`
  - `src/loom/serialization/schema.py`
  - `src/loom/serialization/errors.py`
- Existing package tests that must be updated for Phase 2 public exports:
  - `tests/package/test_import.py`
  - `tests/package/test_public_api.py`
  - `tests/package/test_import_boundaries.py`
- Expected new or updated unit tests:
  - `tests/unit/loom/test_refs.py`
  - `tests/unit/loom/test_artifacts.py`
  - `tests/unit/loom/test_records.py`
  - `tests/unit/loom/test_fingerprints.py`
  - `tests/unit/loom/test_protocols.py`
  - `tests/unit/loom/test_provenance.py`
  - `tests/unit/loom/test_ids.py`
  - `tests/unit/loom/test_errors.py`
  - `tests/unit/loom/serialization/test_plain.py`
  - `tests/unit/loom/serialization/test_dataclasses.py`
  - `tests/unit/loom/serialization/test_json.py`
  - `tests/unit/loom/serialization/test_schema.py`

## Implementation Steps

1. Establish serialization errors and plain-data helpers.
   - Add `src/loom/serialization/errors.py` with `SerializationError`, `DeserializationError`, `SchemaVersionError`, and `PlainDataError`, rooted in the shared hierarchy.
   - Add `PlainData` and path-aware helper functions in `plain.py`.
   - Implement finite-float checks, string-key mapping validation, tuple-to-list normalization, `to_dict` conversion, dataclass conversion delegation, and explicit rejection of unsupported values.
   - Add focused tests for valid data, invalid nested paths, non-mutation, finite floats, rejected non-string keys, rejected sets/bytes/paths/datetimes/callables, and object `to_dict` conversion.

2. Add dataclass and JSON helpers.
   - Implement `dataclass_to_dict`, `dataclass_from_dict`, required-field checks, unknown-field checks, and frozen/slots compatibility.
   - Implement `stable_json_dumps` using sorted keys, compact separators, UTF-8 text, and `allow_nan=False`.
   - Implement `stable_json_bytes` because fingerprints must consume canonical UTF-8 bytes from serialization.
   - Implement `json_dumps_pretty` with two-space indentation, sorted keys by default, and trailing newline.
   - Implement `json_loads` with invalid-JSON wrapping and plain-data validation.
   - Do not implement `write_json`; avoid file writes in Phase 2.

3. Add schema-version helpers.
   - Implement `get_schema_version`, `require_schema_version`, and `check_supported_schema`.
   - Use explicit field names such as `schema_version` by default, with optional parameter support if implementation needs `document_schema_version`.
   - Reject missing, non-integer, unsupported, and future versions with `SchemaVersionError` including path context.

4. Add primitive refs and artifacts.
   - Implement `ResourceRef` in `refs.py`.
   - Implement `ArtifactRef` in `artifacts.py`.
   - Validate required string fields and positive integer schema versions.
   - Validate `metadata`, `checksum`, and `fingerprint` shape without opening URIs or verifying bytes.
   - Use fingerprint digest validation for checksum/fingerprint fields if present, but keep semantic naming distinct in fields and docs.
   - Add `to_dict`/`from_dict` round-trip tests, required `codec_key` tests for set/absent/explicit `None`, immutability tests, no-loading-method tests, and plain-data conversion tests.

5. Add digest and fingerprint helpers.
   - Implement `Digest`, `Checksum`, `Fingerprint`, `HashAlgorithm`, `ParsedDigest`, formatting, parsing, validation, comparison, and hashing helpers.
   - Keep the v0 algorithm allow-list to `sha256`.
   - Ensure `hash_mapping` rejects non-mapping top-level values.
   - Add tests proving deterministic mapping-order behavior, UTF-8 text hashing, bytes hashing, digest parse/validate failures, constant-shape comparison behavior, and rejection of non-plain structured values.

6. Add records, manifest, views, and filters.
   - Implement `Record` and its explicit conversion helpers.
   - Implement manifest lookup and iteration behavior that preserves constructor/serialized record order. Do not sort by `record_id`; tests must lock down input-order preservation.
   - Reject duplicate record IDs at `InMemoryManifest` construction.
   - Implement lazy `ManifestView` that applies composed `RecordFilter` predicates during iteration.
   - Implement only `HasResource`, `MetadataEquals`, and `MetadataIn`. Do not add `AnnotationHasKey`, `RecordIDIn`, regex filters, or serializable filter specs in Phase 2.
   - Add tests for duplicate rejection, deterministic iteration, lookup, length if supported, lazy filtering, filter composition, generic metadata matching, and no domain-specific assumptions.

7. Add generic package-wide protocols.
   - Implement only `Validatable` and `Fingerprintable`.
   - Do not decorate them with `@runtime_checkable` unless the implementation adds an explicit public runtime-check use, which is not expected for this phase.
   - Add tests for structural satisfaction and import cheapness.
   - Do not add subsystem protocols.

8. Add provenance models and capture helpers.
   - Implement frozen models for `GitProvenance`, `CodeProvenance`, `EnvironmentProvenance`, `DependencyProvenance`, `CommandProvenance`, `ArtifactLineage`, `StageProvenance`, `RunProvenance`, and `ProvenanceCaptureOptions`.
   - Keep each model plain-data-convertible and schema-versioned.
   - Implement `capture_git_provenance`, `capture_code_provenance`, `capture_environment_provenance`, `capture_dependency_provenance`, `capture_command_provenance`, `capture_artifact_lineage`, and `capture_run_provenance` exactly as bounded in the Provenance Contract.
   - Keep package capture based on `importlib.metadata.version` for explicitly selected package names.
   - Keep environment capture based on standard-library facts and allow-listed environment keys only; redact obvious secret-like env keys if selected.
   - Add tests with monkeypatch/fakes for git success/failure, missing package capture, selected env capture/redaction, command capture, artifact lineage from `ArtifactRef`, and plain-data conversion.

9. Update package exports and import-boundary tests.
   - Export implemented names from `loom.records`, `loom.provenance`, `loom.serialization`, and `loom.__init__` as described above.
   - Keep Phase 1 config stubs import-safe.
   - Add subprocess-based package tests proving `import loom` does not import config, pipeline, CLI, I/O, stores, or plugins.
   - Add subprocess-based tests proving `import loom.serialization` does not import `loom.io`.
   - Add package tests for `py.typed` and all stable Phase 2 public imports.

10. Run targeted checks during implementation.
   - Use focused direct pytest commands while developing individual modules.
   - Run `make test-package` and `make test-unit` before handing to refinement or PR preparation.

11. Leave final validation to PR preparation.
   - `loom_pr_preparer` must run `make validate-pr` and `make test-summary` before opening/preparing the PR.
   - Record any unavailable checks in completion notes and the PR body.

## Test Plan

### Package Suite

- Required for this phase.
- Expected paths:
  - `tests/package/test_import.py`
  - `tests/package/test_public_api.py`
  - `tests/package/test_import_boundaries.py`
- Required coverage:
  - `import loom` succeeds and remains cheap.
  - `loom.__all__` is exactly `["__version__", "ResourceRef", "InMemoryManifest", "ManifestView", "Record", "ArtifactRef", "Fingerprint", "hash_mapping"]`.
  - `from loom.refs import ResourceRef`, `from loom.artifacts import ArtifactRef`, `from loom.records import Record, InMemoryManifest, ManifestView`, `from loom.fingerprints import Fingerprint, hash_mapping`, `from loom.serialization import ...`, `from loom.provenance import ...`, and `from loom.protocols import ...` work.
  - `py.typed` remains included.
  - Top-level `import loom` does not eagerly import `loom.config`, `loom.pipeline`, `loom.cli`, `loom.io`, `loom.pipeline.stores`, plugin discovery, or downstream project packages.
  - `import loom.serialization` does not import `loom.io`.
  - Existing Phase 1 config stubs still import cleanly and raise `ConfigError` when called.
- Targeted command:

```sh
make test-package
```

### Unit Suite

- Required for this phase.
- Expected paths:
  - `tests/unit/loom/test_refs.py`
  - `tests/unit/loom/test_artifacts.py`
  - `tests/unit/loom/test_records.py`
  - `tests/unit/loom/test_fingerprints.py`
  - `tests/unit/loom/test_protocols.py`
  - `tests/unit/loom/test_provenance.py`
  - `tests/unit/loom/serialization/test_plain.py`
  - `tests/unit/loom/serialization/test_dataclasses.py`
  - `tests/unit/loom/serialization/test_json.py`
  - `tests/unit/loom/serialization/test_schema.py`
- Required coverage:
  - `ResourceRef` and `ArtifactRef` are frozen, typed, equality-stable dataclasses with explicit `to_dict`/`from_dict` round trips.
  - `ResourceRef.codec_key` round-trips for set, absent, and explicit `None` cases.
  - `ResourceRef.to_dict()` has no `fingerprint` key; `ArtifactRef.to_dict()` keeps `checksum` and `fingerprint` as separate keys.
  - Metadata and annotations must be plain-data compatible; invalid nested values raise path-aware errors.
  - Refs and artifacts expose no loading/opening/saving/filesystem methods.
  - Checksums and fingerprints remain separate fields and use digest-format validation where supplied.
  - `Record` conversion preserves resources, metadata, annotations, and provenance without adding domain fields.
  - `InMemoryManifest` rejects duplicate record IDs and iterates deterministically.
  - `ManifestView` applies lazy generic filters and supports composition without copying unless materialized by the caller.
  - `HasResource`, `MetadataEquals`, and `MetadataIn` work only on generic record shape.
  - Fingerprint helpers produce deterministic `sha256:<hex>` values across mapping insertion order and reject unsupported algorithms or invalid digest strings.
  - `stable_json_dumps` uses sorted keys, compact separators, UTF-8 strings, and no trailing newline; pretty JSON uses stable indentation and a trailing newline.
  - JSON loading wraps invalid JSON and validates the plain-data numeric policy.
  - Dataclass helpers work with frozen/slots dataclasses and reject missing or unknown fields as configured.
  - Schema helpers reject missing, non-integer, unsupported, and future versions.
  - Provenance models convert to/from plain data where implemented, include schema versions, preserve metadata, and stay generic.
  - Provenance capture helpers degrade gracefully for missing git or missing packages and do not require network access or heavy imports.
  - Package-wide protocols remain tiny and structural.
  - `ids.__all__` includes `ResourceType`, `Checksum`, and `Fingerprint`; all ID aliases remain plain `str`.
  - `errors.__all__` includes the Phase 2 root errors listed in the Error Hierarchy section while retaining `IOErrorBase`.
- Targeted command:

```sh
make test-unit
```

### Contract Suite

- Intentionally deferred for this phase.
- Reason: Phase 2 defines package-wide generic protocols, but it does not implement concrete extension-point contracts such as codecs, data sources, stages, artifact stores, run stores, or executors. Behavioral contract suites would force future-phase implementation or fake contracts too early.
- Expected path status: `tests/contracts` may remain empty or absent of test files.
- Expected command behavior until a future phase adds contracts:

```sh
make test-contract
```

may report `not present` through the repository harness.

### Integration Suite

- Intentionally deferred for this phase.
- Reason: Phase 2 is low-level and should be fully covered by package and unit tests. It does not combine config, I/O, stores, pipeline planning, execution, or resume behavior.
- No integration tests should be required unless implementation unexpectedly crosses module boundaries. If that happens, the executor should treat the crossing as a design smell and resolve it locally before adding integration coverage.
- Expected command behavior until a future phase adds integration tests:

```sh
make test-integration
```

may report `not present`.

### E2E Suite

- Intentionally deferred for this phase.
- Reason: There is still no functional CLI, config composition, pipeline runner, store, artifact save/load path, or synthetic workflow to exercise end to end.
- Expected command behavior until future workflow phases add e2e tests:

```sh
make test-e2e
```

may report `not present`.

### Opt-In Suites

- Intentionally deferred for this phase.
- Markers affected: `slow`, `slurm`, `network`, and `optional_dependency`.
- Reason: Phase 2 must remain local, standard-library-only, deterministic, and low-level. It should not require network access, SLURM, optional dependencies, remote services, large data, or slow acceptance tests.
- Provenance git tests must use local fake repos, monkeypatched subprocess calls, or unavailable-git assertions, not network.
- If an opt-in test is accidentally needed, the implementation agent must document the exact reason in the completion notes and the PR body, and it must remain outside the default PR gate unless the manager changes validation policy.

## Risks

- Serialization and I/O boundaries could blur if JSON helpers start reading/writing files or if refs grow URI/file behavior. Mitigation: keep Phase 2 helpers string/object-only and add import-boundary tests.
- Public API could become too broad by exporting future subsystem contracts. Mitigation: export only implemented Phase 2 names and keep subsystem protocols local to future phases.
- Digest validation may incorrectly conflate checksum and fingerprint. Mitigation: keep field names and tests separate, while sharing only generic digest format helpers.
- Generic dataclass reconstruction could become too magical. Mitigation: use explicit `from_dict` methods for public types and keep generic reconstruction target-explicit.
- Manifest iteration could become flaky if implementation sorts or materializes unexpectedly. Mitigation: preserve constructor/serialized order and test that policy directly.
- Provenance capture could be fragile or leak sensitive data. Mitigation: return explicit unavailable/error fields, keep remote URL capture opt-in, capture only selected packages/env vars, and redact obvious secret-like env keys.
- Top-level imports could become expensive as modules start doing real work. Mitigation: keep capture helpers side-effect-free at import time and add subprocess import-boundary tests.
- Feature docs describe post-v0 behavior. Mitigation: use the canonical implementation plan as controlling scope and record deferrals.
- Remote GitHub push/fetch is unavailable. Mitigation: base and branch are recorded from local `develop`; PR preparation must handle remote authentication limitations separately.

## Validation Commands

Implementation-time targeted commands:

```sh
make test-package
make test-unit
uv run pytest tests/unit/loom/test_refs.py
uv run pytest tests/unit/loom/test_artifacts.py
uv run pytest tests/unit/loom/test_records.py
uv run pytest tests/unit/loom/test_fingerprints.py
uv run pytest tests/unit/loom/test_provenance.py
uv run pytest tests/unit/loom/serialization
```

Optional suite visibility commands for documenting intentional deferrals:

```sh
make test-contract
make test-integration
make test-e2e
```

Required before PR preparation:

```sh
make validate-pr
make test-summary
```

`make validate-pr` is expected to run Ruff, Pyright, the default Pytest suite, and build. `make test-summary` is expected to write suite-level evidence for the PR body. If either command cannot be run, the PR preparation agent must record the exact reason in this phase plan's completion notes and in the PR body.

## Refinement And Review Budget Status

- Phase implementation refinement: used by the single allowed `loom_phase_refiner` pass on 2026-05-03.
- PR review: unused.

The implementation refinement budget is consumed. The PR review budget remains available for the next workflow stage.

## Handoff Notes For `loom_phase_executor`

- Branch and worktree:
  - Branch: `codex/add-primitives-serialization`.
  - Worktree: `/home/samcantrill/work/loom-worktrees/add-primitives-serialization`.
  - Base: local `develop` at `af9bb3ebe64943343425735d2b84c0ba6a0c0cc7`.
- Do not revisit these plan decisions:
  - `ResourceRef` has no `fingerprint` field.
  - `ResourceRef.codec_key` omission is accepted on input but canonical output always emits `"codec_key": None`.
  - `InMemoryManifest` and `ManifestView` preserve constructor/source order; they do not sort by `record_id`.
  - `MetadataIn.values` normalizes to a tuple, not a set.
  - `PlainSerializable`, file/stream hashing, JSON file read/write helpers, YAML helpers, serializable filters, lockfile capture, subsystem protocols, and future pipeline/I/O/store behavior are out of scope.
  - Digest validation is strict lowercase `sha256:<64 hex>` for persisted input; `format_digest` authors canonical lowercase output.
  - `IOErrorBase` remains the shared I/O root name in Phase 2.
- Safe implementation slices:
  1. Serialization and shared error roots.
     - Owns `src/loom/errors.py` and `src/loom/serialization/*`.
     - Add/update `tests/unit/loom/test_errors.py` and `tests/unit/loom/serialization/*`.
     - Run targeted `uv run pytest tests/unit/loom/test_errors.py tests/unit/loom/serialization`.
  2. Fingerprints and ID aliases.
     - Owns `src/loom/ids.py` and `src/loom/fingerprints.py`.
     - Add/update `tests/unit/loom/test_ids.py` and `tests/unit/loom/test_fingerprints.py`.
     - Run targeted `uv run pytest tests/unit/loom/test_ids.py tests/unit/loom/test_fingerprints.py`.
  3. Refs, artifacts, and records.
     - Owns `src/loom/refs.py`, `src/loom/artifacts.py`, and `src/loom/records/*`.
     - Add `tests/unit/loom/test_refs.py`, `tests/unit/loom/test_artifacts.py`, and `tests/unit/loom/test_records.py`.
     - Run targeted `uv run pytest tests/unit/loom/test_refs.py tests/unit/loom/test_artifacts.py tests/unit/loom/test_records.py`.
  4. Protocols and provenance.
     - Owns `src/loom/protocols.py` and `src/loom/provenance/*`.
     - Add `tests/unit/loom/test_protocols.py` and `tests/unit/loom/test_provenance.py`.
     - Run targeted `uv run pytest tests/unit/loom/test_protocols.py tests/unit/loom/test_provenance.py`.
  5. Public exports and import boundaries.
     - Owns `src/loom/__init__.py`, package `__init__.py` exports, and `tests/package/*`.
     - Run targeted `make test-package` and `make test-unit`.
- Implementation refinement budget is now used; keep PR review budget status marked `unused` for the later PR review stage.
- Do not update Phase 2 status in the canonical implementation plan during execution unless the manager explicitly asks for status metadata work.
- Do not rely on the original checkout's unrelated uncommitted documentation edits.
- If implementation exposes a blocking conflict in the public contract above, stop and report the blocker instead of widening scope.

## Completion Notes

- Draft expanded phase plan created by `loom_phase_planner`.
- Plan expansion: completed in this commit; the plan is decision-complete for `loom_phase_executor`.
- Implementation summary:
  - Completed Phase 2 foundations in worktree `/home/samcantrill/work/loom-worktrees/add-primitives-serialization` with concrete implementations for `refs`, `artifacts`, `fingerprints`, `protocols`, `records`, `provenance`, and `serialization` modules.
  - Added/updated package exports and unit/package tests for all Phase 2 required surfaces.
  - Added strict contract-aligned behavior for record/manifest ordering, lazy manifest views, generic dataclass/plain/JSON helpers, schema helpers, digest validation, and provenance capture degradation paths.
  - Kept I/O boundaries intact: no filesystem write helpers, no URI parsing/loading logic, and no artifact store or codec behavior.
- Refinement summary:
  - Wrapped `ResourceRef` invalid checksum validation as `ResourceRefError` and `ArtifactRef` invalid digest/timestamp validation as `ArtifactValidationError`.
  - Switched digest comparison to the standard-library constant-shape comparison helper and preserved the contract distinction between raw text hashing and stable JSON plain-data hashing.
  - Cleaned Phase 2 lint/type blockers in protocol stubs, provenance/plain-data mapping narrowing, in-memory manifest stored-record narrowing, and unused test imports.
- Test evidence:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/test_artifacts.py::test_artifact_ref_rejects_invalid tests/unit/loom/test_fingerprints.py::test_hash_text_and_mapping_inputs tests/unit/loom/test_fingerprints.py::test_compare_digests tests/unit/loom/test_refs.py::test_resource_ref_rejects_invalid_inputs`: passed, 4 passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/test_artifacts.py tests/unit/loom/test_fingerprints.py tests/unit/loom/test_refs.py`: passed, 16 passed.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-package`: passed, 8 passed.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-unit`: passed, 68 passed.
- Validation evidence:
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr`: passed; Ruff passed, Pyright reported 0 errors, default pytest passed with 76 tests, and `uv build` produced source and wheel distributions.
- PR-prep validation evidence:
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr`: re-run on 2026-05-03 from this worktree and passed; Ruff passed, Pyright reported 0 errors, default pytest passed with 76 tests, and `uv build` produced source and wheel distributions.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary`: passed on 2026-05-03 and wrote `build/test-summary.md`.
- Test-summary evidence:
  - package: passed, 8 tests.
  - unit: passed, 68 tests.
  - contract: not present.
  - integration: not present.
  - e2e: not present.
- Accepted risks:
  - No refinement-scoped residual risks identified.
  - Schema-version helpers remain validation-only until a persisted document shape needs migration support.
  - Filesystem-backed or streaming manifests, stage fingerprint policy, file/stream checksum helpers, fuller provenance capture, and YAML helpers remain deferred to their owning future phases.
- PR status:
  - Canonical Phase 2 status updated to `pr_open`.
  - PR body prepared at `docs/roadmap/stage-0/phases/add-primitives-serialization-pr-body.md`.
  - Remote PR creation was attempted on 2026-05-03.
  - `gh pr list --base develop --head codex/add-primitives-serialization --json number,title,url,state` succeeded through the GitHub API and returned no existing PRs.
  - `git push -u origin codex/add-primitives-serialization` failed with `ssh_askpass: exec(/usr/bin/ssh-askpass): No such file or directory`, `git@github.com: Permission denied (publickey).`, and `fatal: Could not read from remote repository.`
  - PR opening is blocked until SSH credentials or an alternate approved push path are available. No remote or repository-scope workaround was attempted.
- Budget status:
  - Phase implementation refinement: used.
  - PR review: unused.
- Remaining blockers:
  - No implementation blockers identified.
  - PR creation is blocked by unavailable SSH authentication for pushing `codex/add-primitives-serialization` to `origin`.
