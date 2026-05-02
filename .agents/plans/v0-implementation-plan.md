# Expanded V0 Implementation Plan For `loom`

## Summary

Implement v0 as a source-tree-first, fully typed Python package aligned with the boundaries in `docs/structure.md`, `docs/config.md`, `docs/loom.md`, and `docs/future.md`.

Current implementation is metadata-only:

- `src/loom/__init__.py` exposes only `__version__`.
- `src/loom/py.typed` exists.
- `tests/test_package.py` asserts the package imports.
- `pyproject.toml` has no runtime dependencies and has dev gates for `pytest`, `ruff`, and `pyright`.

The v0 acceptance target is:

```text
compose trusted YAML config
expand recipes
instantiate user stage targets
validate a local artifact DAG
run it in-process
persist an inspectable run directory
resume unchanged stages from the same run directory using strict fingerprints
```

`loom` must stay generic. It describes, configures, constructs, runs, resumes, and tracks artifact-based workflows. Domain packages supply concrete stages, recipes, codecs, schemas, datasets, models, reports, and analysis semantics.

Important doc anchors:

- `docs/structure.md`: public vocabulary stays near the top level; serialization is not I/O; subsystems use protocols and registries where names must resolve to behavior.
- `docs/config.md`: config v0 supports only explicit `_target_` object graphs and named `_recipe_` expansion; no Hydra-style defaults, include graphs, arbitrary expression language, or registry aliases for every component.
- `docs/loom.md`: `loom` owns generic pipeline/config/artifact/provenance/execution mechanics; project code owns concrete task behavior.
- `docs/future.md`: resume-safe local execution, status files, artifact indexes, fingerprints, and dummy-stage test infrastructure are the highest-value missing pieces.

Key decisions locked in:

- Use the full selected target package tree with import-safe stubs for deferred features.
- Add hard config runtime dependencies when config implementation begins: OmegaConf, Pydantic v2, and YAML support.
- No functional CLI in v0; CLI modules may exist only as import-safe unsupported-feature stubs.
- Use `loom.records` and `loom.provenance` as packages, not top-level files.
- Require `uv run pytest`, `uv run ruff check .`, `uv run pyright`, and `uv build` to pass where relevant.

## Public Interfaces And Types

### Top-Level Package API

`loom.__init__` should remain cheap and safe. It may import only stable primitive exports and package metadata:

```python
from loom.refs import ResourceRef
from loom.records import Record, InMemoryManifest, ManifestView
from loom.artifacts import ArtifactRef
from loom.fingerprints import Fingerprint, hash_mapping

__all__ = [
    "__version__",
    "ResourceRef",
    "Record",
    "InMemoryManifest",
    "ManifestView",
    "ArtifactRef",
    "Fingerprint",
    "hash_mapping",
]
```

It must not import config composition, pipeline runners, CLI modules, plugin discovery, domain packages, SLURM/subprocess executors, or any optional/heavy dependency path.

### Primitive API

Implement the public vocabulary near the top level, as required by `docs/structure.md`:

```text
loom.ids
loom.refs
loom.records
loom.artifacts
loom.provenance
loom.fingerprints
loom.protocols
loom.errors
loom.timestamps
```

Core objects are frozen, typed dataclasses unless a protocol is explicitly required.

### Config API

Expose from `loom.config`:

```python
compose_config
instantiate
register_recipe
Recipe
ConfigError
```

`compose_config(config_path, overlays=(), overrides=(), recipe_catalog=None)` returns:

```python
ComposedConfig(
    resolved: Mapping[str, Any],
    redacted: Mapping[str, Any],
    provenance: ConfigProvenance,
    fingerprint: str,
)
```

Composition order:

```text
load base config
load overlays
recursive merge
apply dot-path overrides
resolve enough interpolation for recipe args
expand recipes
resolve interpolation again
validate
redact
compute config provenance and fingerprint
```

### Pipeline API

Expose from `loom.pipeline` and `loom.pipeline.execution`:

```python
PipelineSpec
StageSpec
OutputSpec
Stage
StageContext
PipelineRunner
```

Stages are structural protocol implementations, not subclasses:

```python
def run(
    self,
    context: StageContext,
    inputs: Mapping[str, ArtifactRef],
) -> Mapping[str, ArtifactRef]: ...
```

### Store And I/O API

Expose:

```python
from loom.io.sources import DataSource, LocalFileSystemSource
from loom.io.codecs import Codec, CodecRegistry, JSONCodec, TextCodec, BytesCodec
from loom.pipeline.stores import ArtifactStore, RunStore, LocalArtifactStore, LocalRunStore
```

I/O owns bytes, files, URIs, sources, and codecs. Serialization owns Python object to plain structured data conversion. These boundaries must be tested.

### Stage Config Shape

Standardize on inline stage config:

```yaml
pipeline:
  stages:
    - name: build
      _target_: project.stages.BuildStage
      config:
        limit: 100
      outputs:
        index:
          artifact_type: json
          codec_key: json.v1

    - name: report
      _target_: project.stages.ReportStage
      depends_on: [build]
      inputs:
        index: build.index
      outputs:
        report:
          artifact_type: text
          codec_key: text.v1
```

Rules:

- Parse only orchestration fields into `StageSpec`: `name`, `_target_`, `config`, `depends_on`, `inputs`, `outputs`, and `resources`.
- Pass only the stage `config` mapping as constructor kwargs to the stage target.
- Require every output name to declare `artifact_type` and `codec_key`.
- Use only `stage.output` for input bindings.
- Input refs create data dependencies; `depends_on` adds control dependencies.
- The runner, not the stage, owns lifecycle, planning, output validation, status writes, fingerprints, `outputs.json`, and resume decisions.
- Stage implementations save artifacts through `context.artifact_store.save(...)`.

## Phase 1: Foundation

### Goal

Create the package skeleton, public import surface, shared errors, timestamp/id helpers, and import-boundary guardrails. This phase turns the current metadata-only package into a stable typed foundation without implementing runtime behavior yet.

### References

- `docs/structure.md` sections 1.1, 1.2, 1.6, 1.7, 3.1, 3.2, 3.3, 3.10, 3.11, 20.1, 20.2.
- `docs/loom.md` sections 1, 2, 3, 4, 12, 14.

### Implementation Details

Add or update:

```text
src/loom/__init__.py
src/loom/ids.py
src/loom/errors.py
src/loom/timestamps.py
src/loom/records/__init__.py
src/loom/provenance/__init__.py
src/loom/serialization/__init__.py
src/loom/io/__init__.py
src/loom/config/__init__.py
src/loom/pipeline/__init__.py
src/loom/pipeline/graph/__init__.py
src/loom/pipeline/planning/__init__.py
src/loom/pipeline/execution/__init__.py
src/loom/pipeline/executors/__init__.py
src/loom/pipeline/stores/__init__.py
src/loom/cli/__init__.py
```

Concrete specs:

- `loom.ids` defines simple aliases only: `RecordID`, `ResourceKey`, `CodecKey`, `ArtifactID`, `ArtifactType`, `RunID`, `StageID`. Do not use `NewType` or wrapper classes in v0.
- `loom.errors` defines broad catchable classes:
  - `LoomError`
  - `ValidationError`
  - `ContractError`
  - `ArtifactError`
  - `ConfigError`
  - `PipelineError`
  - `ExecutionError`
  - `IOErrorBase`
- `loom.timestamps` defines UTC-only helpers:
  - `utc_now`
  - `utc_timestamp`
  - `safe_timestamp_for_path`
  - `parse_timestamp`
- Deferred modules must import cleanly. Any deferred callable should raise `UnsupportedFeatureError` or an equivalent `LoomError` subclass with a clear message.
- `pyproject.toml` keeps Python `>=3.12`, pyright standard mode, ruff target `py312`, and dev dependencies.
- Add hard config dependencies only when Phase 4 starts, so Phase 1 remains minimal if implemented as a separate PR.

### Testing

Add tests:

```text
tests/test_public_imports.py
tests/test_import_boundaries.py
tests/test_deferred_stubs.py
tests/test_errors.py
tests/test_timestamps.py
```

Test cases:

- `import loom` is cheap and exposes the expected public names.
- `from loom.errors import LoomError, ConfigError, PipelineError` works.
- Timestamp helpers emit UTC timestamps and path-safe strings.
- Deferred package imports succeed.
- Deferred feature functions fail only when called, not at import time.
- Public import boundary checks:
  - top-level primitives do not import `loom.pipeline`
  - `loom.serialization` does not import `loom.io`
  - `loom.pipeline` does not import `loom.cli`
  - `loom` does not import config, pipeline runners, CLI, or domain packages.

Run:

```bash
uv run pytest
uv run ruff check .
uv run pyright
uv build
```

### PR Summary

Establishes the typed package foundation, stable public imports, shared error hierarchy, timestamp/id helpers, and import-safe package skeleton for the v0 implementation.

## Phase 2: Primitives And Serialization

### Goal

Implement the generic value objects and serialization helpers used by every later subsystem. This is the public vocabulary layer: refs, artifacts, records, manifests, provenance, fingerprints, protocols, and deterministic plain-data conversion.

### References

- `docs/structure.md` sections 3.4 through 4.7, 20.5, 20.6, 21.1, 22 Phase 1, 23.1.
- `docs/loom.md` sections 6.1, 6.2, 6.3, 10, 11, 12.
- `docs/future.md` sections 5.1 through 5.5, 9.1.

### Implementation Details

Add or update:

```text
src/loom/refs.py
src/loom/artifacts.py
src/loom/records/base.py
src/loom/records/manifest.py
src/loom/records/views.py
src/loom/records/filters.py
src/loom/records/errors.py
src/loom/provenance/models.py
src/loom/provenance/capture.py
src/loom/fingerprints.py
src/loom/protocols.py
src/loom/serialization/plain.py
src/loom/serialization/dataclasses.py
src/loom/serialization/json.py
src/loom/serialization/schema.py
src/loom/serialization/errors.py
```

Concrete specs:

- `ResourceRef`:
  - frozen dataclass with slots
  - fields: `uri`, `resource_type`, `codec_key`, `schema_version=1`, `checksum=None`, `metadata={}`
  - no loading or decoding methods
  - no domain-specific helpers such as video/signal/image refs.
- `ArtifactRef`:
  - frozen dataclass with slots
  - fields: `uri`, `artifact_type`, `codec_key`, `schema_version=1`, `checksum=None`, `fingerprint=None`, `producer_stage=None`, `created_at=None`, `metadata={}`
  - no artifact loading logic; loading belongs to `ArtifactStore`.
- `Record`:
  - frozen dataclass with slots
  - fields: `record_id`, `resources`, `metadata`, `annotations`, `provenance`
  - helper methods: `has_resource`, `get_resource`, `require_resource`
  - no domain fields such as subject/session/trial.
- `Manifest` protocol:
  - iteration, length, `get`, `require`, and simple selection surface.
- `InMemoryManifest`:
  - stores records by `record_id`
  - rejects duplicate record IDs
  - preserves deterministic iteration order.
- `ManifestView`:
  - lazy filtered view over a manifest
  - supports simple generic filters.
- Filters:
  - `HasResource`
  - `MetadataEquals`
  - `MetadataIn`
- `provenance`:
  - `CodeProvenance`
  - `EnvironmentProvenance`
  - `RunProvenance`
  - `StageProvenance`
  - avoid heavy dependency/version inspection; use standard library where possible.
- `fingerprints`:
  - `Fingerprint`
  - `stable_json_dumps`
  - `hash_bytes`
  - `hash_text`
  - `hash_mapping`
  - never use Python built-in `hash()` for persisted identities.
- `protocols`:
  - only package-wide generic protocols such as `Validatable` and `Fingerprintable`
  - do not put `Stage`, `Codec`, `DataSource`, `ArtifactStore`, or `RunStore` here.
- `serialization.plain`:
  - `to_plain_data`
  - `is_plain_data`
  - `normalize_mapping`
  - `normalize_sequence`
  - output only `None`, `bool`, `int`, `float`, `str`, `list`, and `dict[str, plain]`.
- `serialization.dataclasses`:
  - `dataclass_to_dict`
  - `dataclass_from_dict` only for explicit known public dataclasses
  - `is_dataclass_instance`.
- `serialization.json`:
  - `stable_json_dumps`
  - `json_dumps_pretty`
  - `read_json`
  - `write_json`
  - do not implement filesystem atomic writes here.
- `serialization.schema`:
  - `require_schema_version`
  - `get_schema_version`
  - `check_supported_schema`
  - fail clearly on unsupported versions; no migrations in v0.

### Testing

Add tests:

```text
tests/test_refs.py
tests/test_artifacts.py
tests/test_records.py
tests/test_manifests.py
tests/test_provenance.py
tests/test_fingerprints.py
tests/test_serialization_plain.py
tests/test_serialization_dataclasses.py
tests/test_serialization_json.py
tests/test_serialization_schema.py
```

Test cases:

- `ResourceRef` and `ArtifactRef` default values, immutability, equality, and plain-data conversion.
- `Record.require_resource` returns a resource or raises a path/context-rich record error.
- `InMemoryManifest` rejects duplicates and supports deterministic iteration.
- `ManifestView` filters records without materializing domain semantics.
- Provenance models serialize to deterministic plain data.
- `hash_mapping` is stable across mapping insertion order.
- Checksum/fingerprint distinction is explicit:
  - byte content affects checksum
  - semantic production mapping affects fingerprint
  - noisy values such as timestamps are included only when explicitly passed.
- Schema-version helpers pass supported versions and fail unsupported versions.
- Serialization does not import I/O.

Run:

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

### PR Summary

Adds the generic primitive and serialization layer: refs, artifacts, records/manifests, provenance models, stable fingerprints, schema checks, and deterministic plain-data/JSON conversion.

## Phase 3: I/O Basics

### Goal

Implement local filesystem access, URI helpers, generic codecs, and codec registration. This phase creates the bridge between plain serialized data and stored bytes without introducing domain codecs or remote stores.

### References

- `docs/structure.md` sections 1.3, 5, 6, 7, 20.15, 21.5, 22 Phase 2, 23.2.
- `docs/loom.md` sections 4, 6.1, 6.3.
- `docs/future.md` section 16.

### Implementation Details

Add or update:

```text
src/loom/io/uris.py
src/loom/io/errors.py
src/loom/io/sources/base.py
src/loom/io/sources/local.py
src/loom/io/sources/errors.py
src/loom/io/codecs/base.py
src/loom/io/codecs/json_codec.py
src/loom/io/codecs/text_codec.py
src/loom/io/codecs/bytes_codec.py
src/loom/io/codecs/registry.py
src/loom/io/codecs/errors.py
```

Concrete specs:

- `io.uris`:
  - `parse_uri`
  - `is_file_uri`
  - `uri_to_path`
  - `path_to_file_uri`
  - `normalize_uri`
  - `get_uri_scheme`
  - no resource loading or codec selection.
- `DataSource` protocol:
  - `glob(pattern: str) -> Iterable[str]`
  - `open(uri: str, mode: str = "rb")`
  - `exists(uri: str) -> bool`
  - `stat(uri: str) -> Mapping[str, Any]`
  - `resolve(path: str) -> str`
- `LocalFileSystemSource`:
  - supports local paths and `file://` URIs
  - normalizes paths
  - exposes safe `open`, `exists`, `stat`, and `glob`
  - does not know artifact-store layout.
- `Codec` protocol:
  - `key: str`
  - `save(obj, uri, *, metadata=None) -> ResourceRef | ArtifactRef` where the concrete store decides reference type later
  - `load(ref) -> Any`
  - v0 concrete codecs can expose lower-level encode/decode helpers if this is cleaner for store integration.
- `JSONCodec`:
  - saves only plain-data-compatible objects
  - loads JSON into plain data.
- `TextCodec`:
  - UTF-8 default
  - explicit encoding option.
- `BytesCodec`:
  - raw bytes only.
- `CodecRegistry`:
  - explicit instance-based registry
  - `register`
  - `get`
  - optional convenience `load`/`save`
  - duplicate registration fails
  - unknown codec key fails.

### Testing

Add tests:

```text
tests/test_io_uris.py
tests/test_local_source.py
tests/test_codecs_json.py
tests/test_codecs_text.py
tests/test_codecs_bytes.py
tests/test_codecs_registry.py
```

Test cases:

- Path to file URI and file URI to path conversion for absolute paths, relative paths, paths with spaces, and normalized paths.
- Non-file URI handling fails with `UnsupportedURIError` where appropriate.
- `LocalFileSystemSource.open`, `exists`, `stat`, and `glob`.
- JSON/text/bytes codec round trips.
- JSON codec rejects non-plain unsupported objects.
- Text codec handles encoding explicitly.
- Codec registry duplicate keys and unknown keys fail with codec-specific errors.
- No generic package domain codecs are introduced.

Run:

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

### PR Summary

Adds local filesystem I/O, URI helpers, generic codecs, and codec registration so resources and artifacts can be read and written without domain-specific logic.

## Phase 4: Config Composition

### Goal

Implement trusted YAML config composition and provenance without object construction side effects. This turns authored base configs, overlays, and overrides into resolved/redacted configs.

### References

- `docs/config.md` sections 1 through 10, 13 through 16, 18.
- `docs/structure.md` sections 8.1 through 8.11, 20.3, 20.12, 21.2, 22 Phase 3, 23.3.
- `docs/loom.md` sections 7, 11, 12, 14.

### Implementation Details

Add hard dependencies in `pyproject.toml` when this phase begins:

```toml
dependencies = [
    "omegaconf>=2.3",
    "pydantic>=2",
    "pyyaml>=6",
]
```

Add or update:

```text
src/loom/config/api.py
src/loom/config/load.py
src/loom/config/compose.py
src/loom/config/merge.py
src/loom/config/overrides.py
src/loom/config/interpolation.py
src/loom/config/validation.py
src/loom/config/redaction.py
src/loom/config/provenance.py
src/loom/config/errors.py
```

Concrete specs:

- `load.py`:
  - `load_yaml`
  - `load_json`
  - `load_config_file`
  - loading only; no overlays, no interpolation, no recipes.
- `merge.py`:
  - `merge_mapping`
  - `merge_sequence`
  - `merge_config`
  - mapping plus mapping recursively merges
  - scalar replaces scalar
  - list replaces list
  - `null` is explicit
  - no list append/delete/patch operators.
- `overrides.py`:
  - `parse_override`
  - `parse_overrides`
  - `apply_override`
  - `parse_scalar_value`
  - `set_by_dot_path`
  - parse `true`, `false`, `null`, integers, floats, JSON arrays/objects, and strings
  - record overrides exactly as provided and after parsing.
- `interpolation.py`:
  - `resolve_interpolation`
  - `check_unresolved`
  - optional resolver registration for `env` and `now`
  - wrap OmegaConf so other modules do not become OmegaConf-specific.
- `validation.py`:
  - `validate_schema_version`
  - `validate_reserved_keys`
  - `validate_pipeline_section`
  - `validate_no_missing_values`
  - `validate_config_shape`
  - v0 required top-level fields: `name` and `pipeline`.
- `redaction.py`:
  - `redact_config`
  - `is_secret_key`
  - `redact_mapping`
  - `redact_value`
  - recursively redact keys containing `token`, `secret`, `password`, `api_key`, `credential`, and `private_key`
  - do not print unredacted secrets in errors.
- `provenance.py`:
  - `ConfigProvenance`
  - source config path
  - overlay paths
  - raw override strings
  - parsed overrides
  - recipe expansion records placeholder
  - resolved config hash
  - created timestamp.
- `compose.py`:
  - `ComposedConfig`
  - `compose_config`
  - writes nothing by itself unless the API explicitly receives a persistence target later; persistence belongs to runner/run store.

### Testing

Add tests:

```text
tests/test_config_load.py
tests/test_config_merge.py
tests/test_config_overrides.py
tests/test_config_interpolation.py
tests/test_config_validation.py
tests/test_config_redaction.py
tests/test_config_compose.py
tests/test_config_provenance.py
```

Test cases:

- Base config loading and invalid YAML/JSON errors.
- Multiple overlays applied in order.
- Nested mapping merge, scalar replacement, list replacement, explicit `null`.
- Override parsing for all supported value types.
- Dot-path set into nested mappings and clear errors for invalid paths.
- OmegaConf interpolation, explicit environment interpolation, unresolved values, and missing values.
- Required top-level field validation.
- Redaction for nested secret keys and environment-derived secrets.
- Config provenance hash changes when source, overlay, overrides, or resolved data changes.
- `compose_config` returns `resolved`, `redacted`, `provenance`, and `fingerprint`.

Run:

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

### PR Summary

Implements the trusted config composition pipeline with YAML loading, overlays, dot-path overrides, OmegaConf interpolation, validation, redaction, provenance, and the public `compose_config` API.

## Phase 5: Recipes And Instantiation

### Goal

Implement the two reusable config mechanisms allowed in v0: named `_recipe_` expansion and recursive `_target_` object construction. This phase makes authored configs ergonomic while keeping resolved configs explicit.

### References

- `docs/config.md` sections 5.6, 5.7, 6.3, 7, 11, 12, 16, 18.
- `docs/structure.md` sections 9, 10, 20.3, 20.7, 20.15, 21.2, 22 Phase 4, 23.3.
- `docs/future.md` sections 4.1, 4.2, 20 Phase 3.

### Implementation Details

Add or update:

```text
src/loom/config/recipes/base.py
src/loom/config/recipes/catalog.py
src/loom/config/recipes/expansion.py
src/loom/config/recipes/errors.py
src/loom/config/instantiate/targets.py
src/loom/config/instantiate/recursive.py
src/loom/config/instantiate/injection.py
src/loom/config/instantiate/errors.py
src/loom/config/api.py
```

Concrete specs:

- `ConfigRecipe` protocol:
  - `expand(self) -> dict[str, Any]`.
- `RecipeModel`:
  - Pydantic v2 `BaseModel`
  - `extra="forbid"`
  - useful for typed recipe inputs.
- `RecipeCatalog`:
  - explicit instance-based catalog
  - `register(name, recipe_type)`
  - `get(name)`
  - `list()`
  - duplicate registration fails
  - unknown recipe fails
  - no entry-point discovery in v0.
- Public `register_recipe`:
  - uses a small default catalog
  - tests isolate global/default registry state.
- Recipe expansion:
  - recursively find mappings with `_recipe_`
  - instantiate recipe from remaining mapping keys
  - call `expand`
  - recursively expand nested recipes
  - record path, recipe name, recipe target, input arguments, expanded config hash, expanded config path, and loom version.
- Target import:
  - support `package.module.Class`
  - support `package.module:function`
  - support `package.module:Class`
  - validate target path syntax before import
  - failures include config path and target path.
- Recursive instantiation:
  - any mapping with `_target_` is constructible
  - recursively instantiate nested mappings and sequences
  - `_args_` provides positional args
  - `_partial_=true` returns `functools.partial`
  - `_inject_` maps constructor kwarg names to runtime dependency keys
  - reserved keys: `_target_`, `_args_`, `_partial_`, `_context_`, `_recipe_`
  - unknown or misused reserved keys fail loudly.
- Runtime injection:
  - explicit runtime mapping only
  - missing runtime keys fail
  - injected values are not serialized into resolved config.
- Security:
  - document configs as trusted code
  - no allow-list, sandbox, or disabled-import mode in v0.

### Testing

Add tests:

```text
tests/test_config_recipes.py
tests/test_config_recipe_catalog.py
tests/test_config_recipe_expansion.py
tests/test_config_instantiate_targets.py
tests/test_config_instantiate_recursive.py
tests/test_config_injection.py
```

Test cases:

- Recipe registration, duplicate names, lookup, list, and unknown recipe errors.
- Recipe input validation with Pydantic and dataclass-like recipes.
- Nested recipe expansion and deterministic expansion hashes.
- Recipe provenance captures path, name, target, arguments, and expanded hash.
- Recipe expansion failures include config path and recipe name.
- Target imports for dotted and colon paths.
- Missing module, missing object, non-callable target, and constructor errors.
- Recursive nested object construction through dicts and lists.
- `_args_`, `_partial_`, and `_inject_` success cases.
- Missing injection keys and reserved-key validation.
- Trusted config warning appears in docs or README snippet.

Run:

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

### PR Summary

Adds deterministic recipe expansion and recursive importlib instantiation, including Pydantic-backed recipe validation, recipe provenance, target import support, partials, runtime injection, and path-aware errors.

## Phase 6: Pipeline Specs And Graph

### Goal

Implement the static pipeline model, stage contract, status types, and pure graph validation before persistent stores and execution. This phase makes a resolved config inspectable and validatable as a DAG.

### References

- `docs/structure.md` sections 11, 12, 20.1, 20.16, 21.3, 22 Phase 5, 23.4.
- `docs/loom.md` sections 6.4, 6.5, 8, 12, 14.
- `docs/future.md` sections 6, 7.1, 7.2, 7.4, 18.2.

### Implementation Details

Add or update:

```text
src/loom/pipeline/specs.py
src/loom/pipeline/stage.py
src/loom/pipeline/context.py
src/loom/pipeline/status.py
src/loom/pipeline/validation.py
src/loom/pipeline/errors.py
src/loom/pipeline/graph/dag.py
src/loom/pipeline/graph/topology.py
src/loom/pipeline/graph/bindings.py
```

Concrete specs:

- `OutputSpec`:
  - frozen dataclass
  - fields: `name`, `artifact_type`, `codec_key`, `schema_version=1`, `metadata={}`.
- `StageSpec`:
  - frozen dataclass
  - fields:
    - `name`
    - `target_path`
    - `constructor_config`
    - `depends_on`
    - `inputs`
    - `outputs`
    - `resources`
  - parsed from inline stage config.
- `PipelineSpec`:
  - frozen dataclass
  - fields: `name`, `stages`, `metadata`.
  - preserves stage order from authored config but validates execution order separately.
- Parsing:
  - `parse_stage_spec`
  - `parse_pipeline_spec`
  - accept only documented orchestration fields at stage level
  - put target constructor kwargs only under `config`.
- `Stage` protocol:
  - structural `run(context, inputs) -> Mapping[str, ArtifactRef]`.
- `StageContext`:
  - `run_id`
  - `stage_name`
  - `run_dir`
  - `stage_dir`
  - `resolved_config`
  - `stage_config`
  - `artifact_store`
  - `run_store`
  - `provenance`
  - `metadata`
  - stage-bound artifact writer helper.
- Status types:
  - `StageStatus`: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED`, `STALE`, `CANCELLED`
  - `RunStatus`
  - `StatusRecord`.
- Graph:
  - `build_stage_graph`
  - `upstream_of`
  - `downstream_of`
  - `transitive_upstream`
  - `transitive_downstream`
  - `topological_sort`
  - `detect_cycles`.
- Bindings:
  - `parse_artifact_reference`
  - `resolve_input_bindings`
  - `bind_stage_inputs`
  - input ref format is strictly `stage.output`.
- Validation:
  - unique stage names
  - valid target path strings
  - declared outputs
  - valid input refs
  - input refs point to existing upstream outputs
  - no cycles
  - topological order
  - `depends_on` references existing stages
  - control-only dependencies do not require input artifacts.

### Testing

Add tests:

```text
tests/test_pipeline_specs.py
tests/test_pipeline_stage_contract.py
tests/test_pipeline_context.py
tests/test_pipeline_status.py
tests/test_pipeline_validation.py
tests/test_pipeline_graph.py
tests/test_pipeline_bindings.py
```

Test cases:

- Parse the documented inline stage YAML shape.
- Reject unknown stage-level orchestration keys.
- Pass only `config` as constructor config.
- Reject duplicate stage names.
- Reject missing outputs, bad output spec shape, bad `stage.output` refs, unknown stages, unknown outputs, cycles, and self-dependencies.
- Topological sort for linear, branching, and diamond DAGs.
- Distinguish input data dependencies from `depends_on` control dependencies.
- Dummy stages satisfy the `Stage` protocol without inheritance.
- `StageContext` contains only generic runtime fields.

Run:

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

### PR Summary

Defines the static pipeline model and DAG validation layer: typed stage/output specs, structural stage protocol, stage context, status records, graph construction, binding resolution, and validation.

## Phase 7: Stores And Planning

### Goal

Implement durable local run/artifact state and resume planning without executing stages. This phase makes local run directories inspectable, atomic, and conservative about reuse.

### References

- `docs/structure.md` sections 13, 16, 20.4 through 20.10, 21.4, 22 Phase 5, 23.5.
- `docs/loom.md` sections 9, 10, 11.
- `docs/future.md` sections 8, 9, 16.

### Implementation Details

Add or update:

```text
src/loom/pipeline/stores/artifact_store.py
src/loom/pipeline/stores/run_store.py
src/loom/pipeline/stores/indexes.py
src/loom/pipeline/stores/local_artifacts.py
src/loom/pipeline/stores/local_runs.py
src/loom/pipeline/stores/atomic.py
src/loom/pipeline/stores/errors.py
src/loom/pipeline/planning/plan.py
src/loom/pipeline/planning/planner.py
src/loom/pipeline/planning/resume.py
src/loom/pipeline/planning/invalidation.py
```

Concrete specs:

- `ArtifactStore` protocol:
  - `save(obj, *, name, artifact_type, codec_key, metadata=None) -> ArtifactRef`
  - `load(ref, *, expected_type=None) -> Any`
  - `exists(ref) -> bool`
  - `validate(ref) -> None`.
- `LocalArtifactStore`:
  - filesystem-backed
  - uses `CodecRegistry`
  - allocates artifact paths under the current run/stage artifact directory
  - writes through temp paths and atomic moves where possible
  - computes checksum from stored bytes
  - returns `ArtifactRef` with producer stage and created timestamp
  - does not implement remote backends.
- `RunStore` protocol:
  - `create_run`
  - `get_run_dir`
  - `get_stage_dir`
  - `read_status`
  - `write_status`
  - `read_inputs`
  - `write_inputs`
  - `read_outputs`
  - `write_outputs`
  - `read_fingerprint`
  - `write_fingerprint`.
- `LocalRunStore`:
  - creates stable, human-inspectable run directory
  - manages stage dirs, logs dirs, and config/provenance dirs.
- Run layout:
  - `config/raw.yaml`
  - `config/overlays.yaml`
  - `config/cli_overrides.yaml`
  - `config/resolved.yaml`
  - `config/resolved.redacted.yaml`
  - `config/recipe_manifest.json`
  - `stages/<stage>/status.json`
  - `stages/<stage>/inputs.json`
  - `stages/<stage>/outputs.json`
  - `stages/<stage>/fingerprint.json`
  - `stages/<stage>/provenance.json`
  - `stages/<stage>/logs/`
  - `artifacts/<stage>/`
  - `artifacts.json`
  - `run.json`
  - `provenance/environment.json`
  - `provenance/git.json`
  - `provenance/dependencies.json`.
- `stores.atomic`:
  - `atomic_write_json`
  - `atomic_write_text`
  - `atomic_write_bytes`
  - `replace_file`
  - `ensure_dir`
  - unique temp filenames.
- Indexes:
  - `ArtifactIndex`
  - `StageIndex`
  - `RunIndex`
  - logical artifact key format: `stage.output`.
- Fingerprint calculation includes:
  - stage name
  - target path
  - constructor config
  - declared output specs
  - bound input `ArtifactRef`s
  - Python version
  - `loom` version
  - relevant git state
  - configured dependency versions
  - configured extra fingerprint fields.
- Fingerprint calculation excludes noisy values unless explicitly configured:
  - wall-clock timestamps
  - log paths
  - temp paths
  - random run IDs.
- `ExecutionPlan` and `StagePlan`:
  - topological order
  - bound inputs
  - current fingerprint
  - run/skip decision
  - skip reason
  - invalidated downstream state.
- Resume rule:
  - skip only when previous status is `SUCCEEDED`
  - fingerprint matches
  - `outputs.json` exists
  - all declared artifacts exist
  - checksums validate when present.
- Interrupted or corrupt state is never reusable.

### Testing

Add tests:

```text
tests/test_artifact_store.py
tests/test_run_store.py
tests/test_store_atomic.py
tests/test_store_indexes.py
tests/test_pipeline_planner.py
tests/test_pipeline_resume.py
tests/test_pipeline_invalidation.py
```

Test cases:

- Artifact save/load through JSON/text/bytes codecs.
- Artifact type validation prevents miswired downstream loading.
- Checksums are written and validated.
- Missing artifact files refuse resume.
- Run directory layout contains expected files.
- Atomic writes do not leave corrupt final files after simulated exceptions.
- Status transitions are persisted.
- Artifact indexes map `stage.output` to `ArtifactRef`.
- Planner computes bound inputs and topological stage plans.
- Resume skips valid succeeded stages.
- Config change reruns changed stage and downstream dependents.
- Output spec change reruns changed stage and downstream dependents.
- Target path change reruns changed stage and downstream dependents.
- Missing `outputs.json`, corrupt JSON, stale `RUNNING`, failed status, and partial artifact dirs are not reusable.
- Branch and diamond invalidation propagate correctly.

Run:

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

### PR Summary

Adds local artifact/run stores and the planning layer, including atomic run-state files, artifact indexes, stage fingerprints, conservative resume checks, and downstream invalidation.

## Phase 8: Local Execution

### Goal

Implement the end-to-end local runner using the already-tested config, graph, store, and planning layers. This is the first fully runnable v0 path.

### References

- `docs/structure.md` sections 14, 15.1 through 15.3, 20.4, 20.8, 20.9, 23.4, 23.6, 23.7.
- `docs/loom.md` sections 8 through 12.
- `docs/future.md` sections 7, 8, 9, 10.1, 18.

### Implementation Details

Add or update:

```text
src/loom/pipeline/executors/base.py
src/loom/pipeline/executors/local.py
src/loom/pipeline/executors/errors.py
src/loom/pipeline/execution/runner.py
src/loom/pipeline/execution/lifecycle.py
src/loom/pipeline/execution/atomic.py
src/loom/pipeline/execution/logs.py
```

Concrete specs:

- `Executor` protocol:
  - executes one stage plan
  - returns `ExecutionResult`.
- `ExecutionResult`:
  - stage name
  - status
  - returned outputs
  - started/finished timestamps
  - error details if failed.
- `LocalExecutor`:
  - invokes `stage.run(context, inputs)` in the current Python process
  - catches exceptions and returns failure result or raises executor-specific error according to runner contract
  - does not implement subprocess or SLURM.
- Lifecycle helpers:
  - `prepare_stage`
  - `mark_stage_running`
  - `mark_stage_succeeded`
  - `mark_stage_failed`
  - `mark_stage_skipped`
  - `finalize_stage`.
- `PipelineRunner`:
  - receives a composed config or resolved mapping plus run options
  - creates or reuses a run directory
  - writes raw/resolved/redacted config and config provenance
  - parses and validates `PipelineSpec`
  - instantiates stage targets through `loom.config.instantiate`
  - constructs `StageContext`
  - asks `PipelinePlanner` for a plan
  - binds inputs from prior outputs
  - executes runnable stages through `LocalExecutor`
  - validates returned outputs
  - writes stage status, inputs, outputs, fingerprint, provenance
  - updates artifact index
  - finalizes `run.json`.
- Output validation:
  - returned keys must match declared outputs exactly
  - each returned value must be an `ArtifactRef`
  - artifact type must match `OutputSpec.artifact_type`
  - codec key must match `OutputSpec.codec_key`
  - referenced files must exist
  - checksums validate when present.
- Failure behavior:
  - failed stage writes `FAILED` status and error context
  - downstream stages are not executed in the same run
  - run status becomes failed
  - persisted state remains inspectable.
- Resume behavior:
  - same run directory only
  - valid unchanged stages are marked `SKIPPED` or represented as skip decisions according to the status model
  - changed stages and downstream dependents run.

### Testing

Add tests:

```text
tests/test_local_executor.py
tests/test_pipeline_runner.py
tests/test_stage_lifecycle.py
tests/test_pipeline_e2e.py
tests/helpers/stages.py
```

Dummy stages:

- `WriteNumberStage`
- `AddNumberStage`
- `MultiplyNumberStage`
- `ReportStage`
- `FailingStage`
- `MissingOutputStage`
- `WrongTypeOutputStage`

End-to-end pipeline:

```text
write -> add -> multiply -> report
```

Test cases:

- Run synthetic local pipeline from YAML.
- Verify run directory contains config files, recipe manifest where applicable, run status, stage statuses, fingerprints, inputs, outputs, provenance, artifacts, and indexes.
- Rerun same run directory and verify unchanged stages skip.
- Change stage config and verify that stage plus downstream dependents rerun.
- Change an upstream artifact-producing stage and verify downstream invalidation.
- Simulate missing artifact files and verify reuse is refused.
- Return undeclared output and verify path-aware failure.
- Return missing declared output and verify path-aware failure.
- Return wrong artifact type or codec and verify path-aware failure.
- Return artifact ref pointing to missing file and verify path-aware failure.
- Simulate stage exception and verify status/provenance are written and run fails cleanly.

Run:

```bash
uv run pytest
uv run ruff check .
uv run pyright
uv build
```

### PR Summary

Delivers the first runnable local pipeline path with in-process execution, stage lifecycle handling, output validation, run directory persistence, same-run-dir resume, and synthetic E2E coverage.

## Phase 9: Hardening And Documentation

### Goal

Tighten errors, recovery, contracts, and docs once the local execution path works. This phase does not add major deferred features; it makes v0 safer and easier to diagnose.

### References

- `docs/structure.md` sections 20.1 through 20.16, 21, 23, 24, 25.
- `docs/config.md` sections 14, 16, 19.
- `docs/loom.md` sections 9 through 16.
- `docs/future.md` sections 8, 9, 18, 19, 21, 22.

### Implementation Details

Add or update:

```text
README.md
docs/loom.md
docs/config.md
docs/structure.md
tests/test_error_messages.py
tests/test_interrupted_runs.py
tests/test_extension_contracts.py
tests/test_import_boundaries.py
```

Concrete specs:

- Improve path-aware errors across:
  - config loading and merging
  - overrides
  - interpolation
  - redaction
  - recipe expansion
  - target import and instantiation
  - pipeline parsing and validation
  - graph bindings
  - artifact store
  - run store
  - resume planner
  - local runner.
- Error messages include relevant context:
  - config path such as `pipeline.stages[2]._target_`
  - stage name
  - artifact key such as `train.best_checkpoint`
  - target path
  - file path.
- Interrupted run hardening:
  - stale `RUNNING` stage is not reusable
  - missing `outputs.json` is not reusable
  - partial artifact directories are not reusable
  - corrupt JSON is not reusable
  - checksum mismatch is not reusable
  - failed prior stage can be rerun but not skipped.
- Extension contract tests:
  - dummy stages
  - dummy codecs
  - dummy recipes
  - dummy stores
  - all satisfy protocols structurally without inheritance.
- Docs and README snippets:
  - trusted configs
  - `_target_`
  - `_recipe_`
  - stage contract
  - artifact saving
  - output specs
  - run directory layout
  - checksums vs fingerprints
  - same-run-dir resume.
- Import-boundary tests become permanent guardrails.

### Testing

Add tests:

```text
tests/test_error_messages.py
tests/test_interrupted_runs.py
tests/test_extension_contracts.py
tests/test_docs_examples.py
```

Test cases:

- Golden-message checks for representative path-aware errors.
- Stale `RUNNING`, missing/corrupt files, partial artifacts, and invalid checksums refuse reuse.
- Contract tests prove downstream-style classes work without base classes.
- README/docs snippets execute where feasible.
- Full import-boundary tests still pass after all subsystems exist.

Run:

```bash
uv run pytest
uv run ruff check .
uv run pyright
uv build
```

### PR Summary

Hardens the v0 local pipeline kernel with path-aware errors, interrupted-run recovery coverage, extension-point contract tests, import-boundary guardrails, and user-facing documentation for trusted configs, stages, artifacts, and resume.

## Deferred Features

Do not implement in v0:

- Functional CLI commands.
- Subprocess executor.
- SLURM executor.
- Sweeps.
- Plugins or entry-point discovery.
- Remote artifact stores.
- Source registry beyond local source needs.
- Executor registry unless needed for local-only ergonomics.
- Global run discovery.
- Cross-run cache index.
- Path templates for outputs.
- Output path interpolation.
- Domain codecs, stages, recipes, schemas, datasets, models, metrics, reports, or analysis logic.
- Sandbox/allow-list mode for config imports.
- Hydra defaults, include graphs, complex list patching, arbitrary expression language, automatic schema inference, or registry aliases for every configurable object.
- Database-backed orchestration or dashboards.

Deferred features may have import-safe stubs only when preserving public import paths is useful.

## Overall Test Plan

### Unit Tests

- Primitive construction, immutability, public imports, and plain-data serialization.
- Stable fingerprint determinism and checksum/fingerprint separation.
- Dataclass conversion, schema-version checks, and stable JSON output.
- URI helpers, local source behavior, codec round trips, and codec registry errors.
- Config load, merge, overrides, interpolation, validation, redaction, and provenance.
- Recipe registration, expansion, validation, provenance, and unknown recipe errors.
- Target import, recursive instantiation, `_args_`, `_partial_`, `_inject_`, and bad constructor errors.
- Pipeline spec parsing, DAG validation, graph order, input binding, output spec validation, and stage output validation.
- Artifact/run store atomic writes, artifact indexes, status transitions, resume decisions, and corrupt state handling.

### E2E Tests

- Run synthetic local pipeline from YAML.
- Verify run directory contains raw/resolved/redacted config where applicable, recipe manifest, provenance, status files, fingerprints, inputs, outputs, and artifact refs.
- Rerun same run directory and verify unchanged stages skip.
- Change stage config and verify that stage plus downstream dependents rerun.
- Change an upstream artifact-producing stage and verify downstream invalidation.
- Simulate missing artifact files and verify reuse is refused.
- Return undeclared, missing, wrong-type, wrong-codec, or non-existent output and verify runner fails with a path-aware error.
- Simulate a stage failure and verify status/provenance are written and the run fails cleanly.

### Acceptance Gates

```bash
uv run pytest
uv run ruff check .
uv run pyright
uv build
```

## Assumptions And Defaults

- Python remains `>=3.12`.
- Pyright must pass, but strict mode is deferred.
- Config dependencies are hard runtime dependencies once Phase 4 starts, even though docs discuss optional config extras.
- CLI modules may exist only as import-safe stubs.
- No local lock manager is required in v0 unless tests prove it necessary; atomic writes are required.
- Same-run-dir resume is required; cross-run cache reuse is not.
- Physical artifact paths are owned by `LocalArtifactStore`.
- Stages declare logical output names and specs, not path templates.
- Public imports should remain stable even if internals are later refactored.
- Deferred features fail explicitly, not silently.
- Configs are trusted code; no sandbox or allow-list mode in v0.
- Every `loom` extension point remains domain-agnostic and structurally typed.
