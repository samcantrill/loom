# `loom.config` Specification

## 1. Purpose

`loom.config` is the configuration composition and object construction layer for `loom`.

It exists to keep experiment and workflow configuration readable while preserving full access to ordinary Python code. It should compose YAML, validate stable boundaries, construct object graphs, record provenance, and return the resolved result to the Python caller. Recipe expansion is introduced after the initial composition API is in place.

The initial design should be intentionally narrow. The full v0 implementation should support two authoring modes:

1. Full dynamic import instantiation using `_target_`.
2. Named recipes that expand into explicit `_target_` object graphs.

It should avoid intermediate mechanisms at first, especially registry aliases, arbitrary include graphs, complex list merge operators, and large global component registries. Those can be added later if concrete use makes them necessary.

After v0, `loom.config` should add explicit recursive composition through
`_include_` and whole-section replacement through `_replace_`. V1 deliberately
defers `_copy_` and defaults to metadata/hash source records rather than raw
source snapshots. This is not intended to mimic Hydra or depend on Hydra. The
goal is a smaller,
deterministic composition feature that lets users split large configs into
nested component files, swap components for experiments, and preserve clear
provenance, fingerprints, and path-aware errors.

### 1.1 Alignment With `loom.md`

This document refines the configuration responsibilities listed in
[loom.md](../loom.md): configuration composition, recursive importlib construction,
named recipe expansion, validation, provenance capture, and redaction. Recipe
expansion arrives after base composition: Phase 4 rejects `_recipe_` blocks with
a clear unsupported-recipe error, and Phase 5 enables deterministic expansion
and recipe manifests. It keeps
the same non-goal boundary: authored configs are trusted project code in v0, but
`loom.config` must not execute stages, define domain recipes, or become a Hydra
replacement.

---

## 2. Core Position

The configuration system should not try to predict every possible dataset, stage, executor, model, report, or analysis object. Research code varies too much.

Use this architecture:

```text
Low-level flexibility:
  explicit `_target_` importlib object graphs

High-level usability:
  named recipes that expand into low-level object graphs

Validation:
  typed schemas at experiment, recipe, and stable-component boundaries

Execution:
  handled by loom.pipeline, not by loom.config
```

This means `loom.config` is not a workflow engine. It does not run stages or interpret application-specific data. It composes configs, validates structure, constructs Python objects, records provenance, and provides the resulting config/object graph to the caller. After Phase 5 it also expands recipes.

Typed configuration models should be used as internal correctness contracts at
stable `loom` boundaries. They should not become a new YAML authoring language.
Project-specific YAML remains ordinary trusted project config unless it crosses
a `loom` contract such as a pipeline spec, stage spec, artifact reference, or
recipe input. Authored config files, recipes, and `_target_` import paths are
trusted project code. `loom.config` does not provide an untrusted-config
sandbox, import allow-list mode, or safe execution boundary for configs supplied
by an untrusted party.

---

## 3. Package Boundary

### 3.1 `loom`

Owns shared primitives.

Responsibilities:

```text
resource references
artifact references
records and manifests
shared exceptions
serialization helpers
small utility types
```

### 3.2 `loom.config`

Owns configuration and object construction.

Responsibilities:

```text
load YAML/OmegaConf configs
apply overlays
apply Python API override strings
resolve interpolation
expand named recipes
validate configs
resolve import targets
instantiate object graphs
inject runtime dependencies when requested
record config provenance
return artifact-safe manifest/provenance/source/fingerprint records to callers
redact secrets
resolve explicit config includes after v0
resolve explicit config replacements after v0
leave resolved-config persistence and run-store writes to callers
```

### 3.3 `loom.pipeline`

Owns execution.

Responsibilities:

```text
pipeline DAGs
stage execution
artifact passing
stage status
resume/cache logic
executor integration
run directory management
sweeps
```

`loom.pipeline` must remain usable without `loom.config` or composition
manifests. Config composition is an optional Python API path that can produce
plain data for callers; `loom.config` must not call pipeline, stores, CLI
modules, plugin discovery, or project code during composition.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
YAML config loading
OmegaConf interpolation and dot-path overrides
base experiment config
overlay files
override strings
named recipe expansion
full `_target_` recursive instantiation
runtime dependency injection
partial construction or builder construction
basic top-level validation
recipe-level validation
in-memory resolved config generation
recipe provenance data returned to callers
secret redaction
clear error messages
```

### 4.2 Should Not Support in v0

```text
registry aliases for every component
complex `_include_` composition graphs
implicit fallback search by bare filename
advanced list patching
Hydra-style defaults list
Hydra-style launchers/sweepers
arbitrary expression language in YAML
automatic schema inference for arbitrary targets
automatic object lifecycle hooks everywhere
full plugin marketplace behavior
```

The most important constraint: v0 should have only two ways to express reusable behavior.

```text
1. Write the full `_target_` object graph.
2. Use a named recipe that expands into a full `_target_` object graph.
```

### 4.3 Should Support Soon After v0

```text
explicit `_include_` composition inside mappings
explicit `_replace_` mapping replacement for component swaps
strict update overrides plus explicit `+` add overrides
relative include resolution based on the including config file and key path
local path and `file://` include resolution
recursive include expansion with cycle detection
composition provenance, source hashes, and resolved include stacks
deterministic merge of included content with sibling overrides
composition manifests, source metadata/hashes, and opt-in raw source snapshots
clear path-aware errors for missing, invalid, or cyclic composition directives
```

This should remain narrower than Hydra. It should not add defaults lists,
launchers, sweepers, arbitrary YAML expressions, automatic component registries,
advanced list patching, custom interpolation resolvers, or plugin-discovered
composition extensions. It also should not add a YAML `_schema_` directive,
Hydra-style structured-config registry, or automatic imports of project schema
classes from config files. Typed validation belongs behind existing `loom`
boundaries and recipe contracts.

---

## 5. Terminology

### 5.1 Raw Config

The config file as authored before composition, interpolation, recipe expansion,
or override strings.

### 5.2 Composed Config

The config after loading base files, overlays, file/user composition, recipe
expansion, and ordinary Python API override strings.

### 5.3 Expanded Config

The config after recipe expansion. At this point, high-level recipe references should have been converted into explicit lower-level config.

### 5.4 Resolved Config

The final in-memory config after interpolation and validation. V1 exposes this
to Python callers but does not persist it by default; default artifacts use the
artifact-safe unresolved/redacted view plus manifest, provenance, source, and
fingerprint records.

### 5.5 Object Graph

The set of instantiated Python objects created from `_target_` blocks.

### 5.6 Recipe

A named typed object or function that expands a small user-facing config into a detailed explicit config.

Example:

```yaml
data:
  _recipe_: local_jsonl_manifest
  root: /data/project
  pattern: "*.jsonl"
```

Expands to:

```yaml
data:
  source:
    _target_: project.sources.ProjectLocalSource
    root: /data/project
  discovery:
    _target_: project.discovery.GlobDiscovery
    pattern: "*.jsonl"
  manifest:
    _target_: project.manifests.ManifestBuilder
    source: ${data.source}
    discovery: ${data.discovery}
```

The targets above are project-provided examples. V0 `loom` does not provide a
generic `GlobDiscovery` or `ManifestBuilder`; recipe examples should avoid
implying those APIs exist in core.

### 5.7 Target

A Python import path used to construct an object.

Supported forms:

```text
package.module.Class
package.module:function
package.module:Class
```

The syntax is intentionally strict. Dotted targets import the final name from a
module path; colon targets import the name after the colon from the module path
before it. Nested object lookup after the final dotted segment or after the
colon target is not supported, so nested classes or attributes should be exposed
through a top-level module object or factory function.

### 5.8 Include

A config mapping that loads another config document before local sibling keys
are applied.

Example:

```yaml
model:
  _include_: resnet50
  dropout: 0.2
```

If this appears in `configs/experiment.yaml`, the default post-v0 resolution is:

```text
configs/model/resnet50.yaml
```

The included mapping is loaded first, then sibling keys such as `dropout` merge
over the included content. The final resolved config should not require users to
know whether a value came from the base file, an include, an overlay, or an
override string; provenance records that source information explicitly.

If an `_include_` is applied at a config path that already has lower-precedence
mapping content, the same mapping must also contain `_replace_: true`. This
turns component swaps into explicit replacements and prevents stale keys from a
previous component from leaking into the new included component. An include at a
new path does not need `_replace_` because there is no prior mapping to discard.

### 5.9 Replace

A merge directive that replaces the destination mapping at the same config path
instead of recursively merging with it.

Example overlay:

```yaml
model:
  _replace_: true
  _include_: vit_b16
  dropout: 0.1
```

If the base config already has a `model` mapping, that mapping is discarded
before the overlay's expanded `model` mapping is applied. This prevents stale
keys from a previous component from leaking into a replacement component during
experiments or sweeps.

`_replace_` is allowed only in mappings. It is a composition marker and should
not appear in the resolved config. In v1, `_replace_: true` is valid only when
there is lower-precedence mapping content to discard; unnecessary replacement
markers fail as author-intent mismatches.

When `_include_` appears while replacing an existing mapping, `_replace_: true`
is required in the same mapping. A missing marker is a config error rather than
an implicit recursive merge.

### 5.10 Copy

Future-only, not supported in v1: a config mapping that copies an existing
subtree from the composed config before local sibling keys are applied.

Example:

```yaml
stage_configs:
  train_base:
    batch_size: 64
    epochs: 20
    optimizer:
      _include_: adam

pipeline:
  stages:
    train_small:
      config:
        _copy_: stage_configs.train_base
        optimizer:
          lr: 0.0003
```

The copied subtree is deep-copied as plain config data, then local sibling keys
merge over it. The copied result is not a live alias: later local changes at the
copy site do not mutate the source subtree.

If `_copy_` appears in v1 authored config, composition fails with an explicit
unsupported-directive `ConfigError`. Future `_copy_` work should use explicit
config paths, not implicit global names, and should define cycle detection and
provenance before implementation.

### 5.11 Composition Manifest

A versioned artifact-safe record of authoring-level composition operations used
to build the composed config.

The v1 manifest records includes, replacements, overlays, parsed Python API
override strings, source hashes, fingerprint references, recipe records, and
raw snapshot availability. It does not include `_copy_`, resolved resolver
outputs, raw source bytes by default, or resolved-config persistence. Raw source
snapshots are available only through explicit Python API opt-in.

When stable `loom` schemas validate part of the config, the manifest or
provenance should identify the schema boundary, schema version, and config path.
If schema defaults or type coercions affect the resolved config, those effects
should be visible in the resolved config and traceable in provenance.

### 5.12 Dependency and Validation Boundary

Configuration composition remains feature-complete in `loom.config`, but its
external dependencies are optional:

- `omegaconf`
- `pydantic`
- `pyyaml`

These remain published under `[project.optional-dependencies].config` so core
runtime imports and import-boundary tests can run without optional installation.
Runtime entry paths that require configuration loading, interpolation, or recipe
resolution require `loom[config]`.

The import boundary contract is:

- `import loom` and core primitive/records/artifacts/pipeline imports succeed
  without config extras.
- `import loom.config` stays import-safe.
- Config-only APIs that need optional dependencies fail with a clear
  `loom[config]` guidance error when the extra is missing.

Suite evidence is split between:

- no-extra validation targets for default behavior
- `test-config-extra` targets for config composition/interpolation/recipe behavior.

---

## 6. Guiding Design Principles

### 6.1 Keep Authored Config Shallow

Users should not usually hand-edit extremely deep config graphs. They should select recipes or write full object graphs only when necessary.

Recommended authored nesting depth:

```text
experiment config:
  3 to 4 semantic levels

component/recipe config:
  4 to 5 semantic levels if necessary

resolved config:
  no hard nesting limit
```

If a user regularly edits deeper than this, introduce a recipe.

### 6.2 Make Resolved Config Explicit

The in-memory resolved config should be complete enough for the Python caller to
run the workflow without guessing which recipe, overlay, or override string was
used. `loom.config` returns that resolved view to the caller, but it remains
persistence-free and does not choose run-store paths.

For a v1 composed config passed through `PipelineRunner`, the current default
run-store config artifacts are:

```text
config/recipe_manifest.json
config/composition_manifest.json
run.json metadata.config_provenance
```

Those artifacts are plain, artifact-safe data. They preserve authored resolver
expressions, source metadata/hashes, recipe records, and fingerprint/provenance
facts without writing resolver outputs, raw source bytes, or default
`config/resolved.yaml` / `config/resolved.redacted.yaml` snapshots for composed
configs. Explicit raw source snapshot payloads remain a Python API opt-in owned
by the caller.

Future runner/run-store policies may add opt-in raw, overlay, CLI override, or
resolved snapshot files, but those are not v1 composed-config defaults.

### 6.3 Prefer Recipes Over Intermediate Aliases in v0

An alias like `default_runner` can be convenient, but aliases, registries, includes, and scoped config references add another layer of ambiguity. The first version should avoid these unless needed.

For now:

```yaml
serialization:
  codec:
    _target_: project.codecs.CustomJSONCodec
    indent: 2
```

or:

```yaml
pipeline:
  _recipe_: local_pipeline
  run_dir: runs/example
```

Avoid:

```yaml
runner: local
runner:
  _include_: "@project/runner/local"
```

### 6.4 Add Explicit Composition Before Broader Config Language

Recursive file composition and section replacement are useful enough to add
after the v0 kernel, but they should remain explicit and deterministic:

```yaml
model:
  _include_: resnet50

optimizer:
  _include_: file:///configs/optimizer/adam.yaml
```

Design constraints:

```text
_include_ is allowed only in mappings
included content loads before sibling keys
sibling keys override included content with normal merge semantics
include swaps over an existing mapping require _replace_: true
relative includes are resolved from the including file and mapping key path
URI includes are limited to built-in local and file:// resolution in v1
include expansion records provenance and source hashes
include expansion detects cycles and fails clearly
_replace_ is allowed only in mappings and replaces the destination mapping
_copy_ is unsupported in v1 and fails explicitly when authored
composition manifests record artifact-safe source metadata/hashes by default
raw source snapshots are explicit Python API opt-in, not default persistence
```

Relative resolution should be path-based and predictable:

```text
configs/experiment.yaml:
  model:
    _include_: resnet50

resolves to:
  configs/model/resnet50.yaml

configs/experiment.yaml:
  model:
    encoder:
      _include_: small

resolves to:
  configs/model/encoder/small.yaml
```

If the include value is an explicit relative path such as
`../shared/model.yaml`, resolve it relative to the including file directory. If
the include value has a URI scheme such as `file://`, route it through the
matching built-in file resolver. Other URI schemes, plugin-discovered
composition extensions, and custom interpolation resolvers are deferred until
there is a concrete provenance and error model.

Whole-section replacement should be explicit:

```yaml
model:
  _replace_: true
  _include_: vit_b16
```

This means the previous `model` mapping is discarded before the replacement
mapping is applied. Without `_replace_`, mappings recursively merge and sibling
keys continue to override included content.

Subtree reuse through `_copy_` remains future roadmap work. V1 rejects `_copy_`
instead of partially documenting or implementing copy semantics.

This is not a Hydra defaults-list implementation. There is no implicit global
search path, no launcher or sweeper behavior, no arbitrary expression language,
and no automatic registry aliasing for every component.

---

## 7. Composition Order

Historical v0 flow after recipes are implemented:

```text
1. Load raw base config.
2. Load overlay configs in order.
3. Merge overlays into base config.
4. Apply override strings.
5. Resolve enough interpolation for recipe arguments from the composed config.
6. Expand recipes.
7. Resolve interpolation again after expansion.
8. Validate missing values and stable schemas.
9. Redact secrets for persisted config views.
10. Produce raw, overlay, override, recipe, and resolved provenance data for
   the caller.
11. Instantiate object graph when requested.
```

Recipe argument pre-resolution should resolve currently resolvable interpolation
from the composed base/overlay/override config so recipe arguments can reference
those values. Expanded blocks then participate in final interpolation after
expansion. Phase 5 tests should cover both recipe args referencing composed
values and expanded blocks referencing values resolved by the final pass.

Phase 4 bridge behavior:

```text
load base config
load overlays
recursive merge
apply dot-path overrides
resolve interpolation
detect `_recipe_` keys and fail with unsupported-recipe ConfigError
validate
redact
produce empty recipe_manifest
compute config provenance and fingerprint
```

Phase 4 composition writes nothing by itself. Persistence belongs to the runner
and run store. Phase 5 replaces the unsupported-recipe bridge with deterministic
recipe expansion and manifest records.

V1 composition with includes and replacement preserves the core merge rules
while treating base files, overlays, and Python API override strings as
authoring-level inputs:

```text
load base config
load overlays
parse override strings
recursive merge overlays and override mapping into base config, honoring _replace_
recursively expand includes
resolve enough interpolation for recipe args
expand recipes
scan resolver expressions without executing runtime resolvers
redact
compute artifact-safe manifest, provenance, source records, and fingerprint
resolve interpolation again for the in-memory result
validate
```

For ordinary values, override strings remain the highest-precedence authoring
input. User-defined include swaps run after file-defined composition and before
recipes; ordinary value overrides then target the expanded concrete config.

Implementation should preserve source-location metadata through the merge so an
include authored in an overlay still resolves relative to that overlay file. A
brand-new user include sites require explicit relative paths, absolute paths, or
`file://` URIs. Bare user include targets are allowed only at existing
file-defined include sites with known source context.

Directive validation happens during composition. Stable typed validation happens
after directives, recipes, and interpolation have produced the resolved config
shape. This keeps `_include_` and `_replace_` as composition directives rather
than schema declarations. `_copy_` is a reserved unsupported directive in v1.

---

## 8. Merge Semantics

Default merge behavior should be simple:

```text
mapping + mapping:
  recursive merge

mapping with _replace_: true:
  replace destination mapping before applying the marker mapping

scalar + scalar:
  override

list + list:
  replace whole list

null:
  explicit null value
```

Do not add list splice operators until there is a clear recurring need.
`_replace_` should be the only v1 escape hatch for whole-mapping replacement;
it must be recorded in composition provenance and omitted from the resolved
config.

An `_include_` that changes or introduces an included component at a path with
existing lower-precedence mapping content must be paired with `_replace_: true`.
Without the marker, composition should fail with a path-aware error instead of
recursively merging the new included component with stale keys.

---

## 9. Override Strings

V1 exposes dot-path override strings through the Python API with explicit add
syntax:

```text
compose_config(
  "experiment.yaml",
  overrides=(
    "run.seed=123",
    "serialization.codec.indent=2",
    "data.root=/data/project",
    "+vars.learning_rate=0.0003",
  ),
)
```

Override forms:

```text
path=value:
  update an existing path; fail if the path does not exist

+path=value:
  add a new path; fail if the path already exists
```

The `+` form is how users intentionally introduce a new variable, new
structured branch, or composition marker from override strings. This catches
typos in ordinary overrides without preventing rapid experimentation.

Examples:

```text
+vars.learning_rate=0.0003
+evaluation.metrics='["accuracy", "loss"]'
model._include_=vit_b16
```

The final example switches an existing included component. `model._include_`
updates a recorded file-defined include site and reuses its source context. A
brand-new user include site must use `+` and an explicit relative path,
absolute path, or `file://` URI; brand-new bare include targets are not
supported in v1.

Recommended parsing rules:

```text
true/false -> bool
null -> None
integers -> int
floats -> float
JSON arrays/objects -> parsed values
everything else -> string
```

Overrides should be recorded exactly as provided and after parsing.
The add marker belongs to override syntax and should not appear in the resolved
config path.

Override paths split on literal dots. V1 does not define an escape syntax for a
literal dot inside a mapping key, so a key such as `model.v1` is not addressable
through an override path segment. Use authored YAML structure, includes, or
recipe outputs when literal-dot keys are required.

---

## 10. Interpolation

Use OmegaConf-style interpolation. OmegaConf, Pydantic v2, and YAML support are
available through the `loom[config]` optional extra so core primitives, stores,
serialization, and inspection paths remain importable without config-only
dependencies.

Examples:

```yaml
run:
  id: ${now:%Y%m%d-%H%M%S}
  seed: 123

paths:
  root: /runs/${run.id}
  artifacts: ${paths.root}/artifacts
```

Environment interpolation should be explicit:

```yaml
storage:
  endpoint: ${oc.env:LOOM_STORAGE_ENDPOINT}
  token: ${oc.env:LOOM_STORAGE_TOKEN}
```

Secrets resolved from environment variables should be redacted from artifact-safe
public views and should not be persisted as resolved values by default.

---

## 11. Recipes

### 11.1 Recipe Interface

A recipe should be importable, typed, and deterministic.

```python
from dataclasses import dataclass
from typing import Any


@dataclass
class LocalJsonlManifestRecipe:
    root: str
    pattern: str = "*.jsonl"

    def expand(self) -> dict[str, Any]:
        return {
            "source": {
                "_target_": "project.sources.ProjectLocalSource",
                "root": self.root,
            },
            "discovery": {
                "_target_": "project.discovery.GlobDiscovery",
                "pattern": self.pattern,
            },
            "manifest": {
                "_target_": "project.manifests.ManifestBuilder",
                "source": "${data.source}",
                "discovery": "${data.discovery}",
            },
        }
```

The recipe may validate its own arguments before returning expanded config. The
targets above are project-provided examples, not built-in `loom` APIs.

### 11.2 Recipe Catalog

Recipes should be registered by name.

```python
from loom.config import RecipeCatalog, compose_config, compose_config_with_catalog, register_recipe

# Reproducible composition path
catalog = RecipeCatalog()
catalog.register("local_jsonl_manifest", LocalJsonlManifestRecipe)
cfg = compose_config_with_catalog("experiment.yaml", recipe_catalog=catalog)

# Script / notebook / interactive path
register_recipe("local_jsonl_manifest", LocalJsonlManifestRecipe)
cfg = compose_config("experiment.yaml")
```

Optional entry point discovery can be added later:

```toml
[project.entry-points."loom.recipes"]
local_jsonl_manifest = "project.recipes:LocalJsonlManifestRecipe"
```

### 11.3 Recipe Provenance

Each recipe expansion should record:

```text
recipe name
recipe target
input arguments
expanded config hash
expanded config path
loom version
```

Example:

```json
{
  "recipes": [
    {
      "path": "data",
      "name": "local_jsonl_manifest",
      "target": "project.recipes:LocalJsonlManifestRecipe",
      "arguments": {
        "root": "/data/project",
        "pattern": "*.jsonl"
      }
    }
  ]
}
```

### 11.4 Static Fan-Out Recipes

Recipes may later help generate repeated static stage patterns.

Example use cases:

```text
one evaluation stage per dataset
one report stage per cohort
one validation branch per configured model checkpoint
```

The expansion should happen during config composition or recipe expansion, before
pipeline validation and planning. This keeps the pipeline graph static for
resume, provenance, and SLURM dependency generation.

---

## 12. Object Instantiation

Any mapping with `_target_` should be constructible.

```yaml
serialization:
  codec:
    _target_: project.codecs.CustomJSONCodec
    indent: 2
```

Pipeline stage specs are not generic object graphs in v0; do not use runner or
executor examples here as if config composition constructs them.

Rules:

```text
_target_:
  required strict dotted or colon import path

_partial_:
  if true, return functools.partial instead of constructing immediately

_inject_:
  optional map of constructor argument names to runtime dependency keys

other keys:
  recursively instantiated and passed as keyword arguments
```

Example with runtime injection:

```yaml
stage:
  _target_: project.stages.SummarizeStage
  formatter:
    _target_: project.formatters.JsonFormatter
  _inject_:
    logger: logger
```

Python API:

```python
from loom.config import instantiate

stage = instantiate(cfg["stage"], runtime={"logger": logger})
```

Instantiation should fail loudly when a target cannot be imported or constructor arguments do not match.
Targets must use one of the supported strict forms:

```text
package.module.Class
package.module:function
package.module:Class
```

Nested lookup forms such as `package.module.Outer.Inner` and
`package.module:Outer.Inner` are rejected. Put the intended class or factory at
module scope and reference that object directly.

---

## 13. Validation

Validation should happen at stable boundaries:

```text
top-level experiment config
recipe inputs
pipeline spec
stage spec
executor spec
artifact references
composition manifest records
provenance records
```

Typed models are valuable here because these are `loom` contracts. They should
check required fields, supported schema versions, known directive placement,
value types, and unknown keys where `loom` owns the structure.

Avoid automatic schema inference for arbitrary `_target_` classes. That creates
surprising behavior and unclear ownership. Also avoid a YAML schema-binding
directive such as `_schema_` in the initial design. Recipes are the project-code
boundary for typed, project-specific config inputs; arbitrary project-owned
mappings should otherwise pass through unchanged until a recipe, target
constructor, or `loom` schema owns them.

Recommended top-level fields:

```yaml
name: example_run
run:
  seed: 123
  output_dir: runs/example
data: {}
pipeline: {}
```

Required fields can be kept minimal in v0:

```text
name
pipeline
```

Config files may include `schema_version` at stable document boundaries. V0 only
needs to accept the supported version and fail clearly on unsupported versions;
migrations can wait until there are real historical formats to preserve.
Persisted document version parsing belongs to `loom.serialization`, while
`loom.config` decides which config document versions it supports.

Validation should be source-aware. A validation error should be able to report:

```text
config path
source file, overlay, include, replacement mapping, or override string
include stack when relevant
schema boundary when relevant
expected value shape
actual value shape
```

Strictness should be scoped. Unknown keys in `loom`-owned sections should fail
or warn according to that section's schema. Unknown keys in project-owned
subtrees should not be rejected globally, because research configs often carry
domain-specific data that `loom` should not interpret.

---

## 14. Secret Redaction

Support redaction by path and by key pattern.

Default redacted key patterns:

```text
token
secret
password
api_key
credential
```

Expose both:

```text
resolved:
  in-memory full resolved config returned to Python callers

redacted:
  artifact-safe view returned for logs and bug reports
```

Do not print unredacted secrets in error messages.

Composition accepts plaintext secret-like overrides to preserve legacy behavior,
but they are easy to leak through shells, process listings, and history. Avoid
passing secrets directly in override strings such as
`+auth.token=plaintext-secret` or `storage.api_key=plaintext-secret`.

- `plaintext_secret_override_warnings`: a warning list keyed by override path and operation when override keys match secret patterns.

Prefer environment-backed values in authored config, for example
`${oc.env:AUTH_TOKEN}` or `${oc.env:LOOM_STORAGE_TOKEN}`. Keep plaintext
secret overrides for transition only and use the warning data to guide
follow-up.

---

## 15. Public API

Recommended API:

```python
from loom.config import (
    RecipeCatalog,
    compose_config,
    compose_config_with_catalog,
    inspect_config_composition,
    instantiate,
    register_recipe,
    Recipe,
    ConfigError,
)
```

`compose_config`:

```python
cfg = compose_config(
    config_path="experiment.yaml",
    overlays=["overlays/local.yaml"],
    overrides=["run.seed=123"],
)
```

`inspect_config_composition`:

```python
inspection = inspect_config_composition(
    config_path="experiment.yaml",
    overlays=["overlays/local.yaml"],
    overrides=["run.seed=123"],
)
```

`inspect_config_composition` is for inspection, debugging, review tooling, and
tests. It exposes stable plain-data stage records for composition decisions; it
is not a pipeline construction API and callers should not build
`PipelineSpec`/`StageSpec` objects from inspection internals. Use
`compose_config` for normal composition, `instantiate` for trusted object
graphs, and direct `PipelineSpec` inputs when running a pipeline without
`loom.config`.

`compose_config_with_catalog`:

```python
from loom.config import RecipeCatalog, compose_config_with_catalog

catalog = RecipeCatalog()
catalog.register("local_jsonl_manifest", LocalJsonlManifestRecipe)

cfg = compose_config_with_catalog(
    config_path="experiment.yaml",
    recipe_catalog=catalog,
    overlays=["overlays/local.yaml"],
    overrides=["run.seed=123"],
)
```

`compose_config` returns a `ComposedConfig` with:

```text
resolved
redacted
provenance
recipe_manifest
unresolved
manifest
source_artifacts
fingerprint_records
raw_source_snapshots
fingerprint
```

The `resolved` field is an in-memory caller result, not a default persistence
artifact. Raw source snapshots are disabled by default and require
`include_raw_source_snapshots=True`.

`recipe_manifest` is empty when no recipes are expanded. When `_recipe_` blocks
are present, composition expands them through the selected `RecipeCatalog` and
records recipe provenance in the manifest.

`instantiate`:

```python
codec = instantiate(cfg["serialization"]["codec"])
```

Do not use generic `instantiate()` on `pipeline` stage mappings in v0.
`PipelineRunner` parses `pipeline.stages` into `PipelineSpec`/`StageSpec`
objects, where authored `factory._target_` is stored as
`StageSpec.factory.target_path` and authored `config` is stored as
`StageSpec.stage_config`. Stage targets are not
constructed during config composition or generic pipeline parsing.

`register_recipe`:

```python
register_recipe("local_jsonl_manifest", LocalJsonlManifestRecipe)
```

---

## 16. Error Messages

Config errors should identify the failing path and the exact problem.
When composition provenance is available, errors should also identify the
authored source that produced the failing value. That source may be the base
config, an overlay, an included local/file source, a replacement mapping, or an
override string. `_copy_` is unsupported in v1 and should be reported as such.

Composition should fail clearly when:

```text
an _include_ swaps an existing mapping without _replace_: true
a normal override targets a missing path
a + override targets an existing path
```

Example:

```text
Could not instantiate target project.codecs.CustomJSONCodec.

Config path:
  serialization.codec

Reason:
  __init__() got an unexpected keyword argument 'formatterr'

Did you mean:
  formatter
```

Recipe errors should include the recipe name and location:

```text
Recipe expansion failed.

Config path:
  data

Recipe:
  local_jsonl_manifest

Reason:
  root does not exist: /data/project
```

---

## 17. Future CLI Integration

V1 ships Python API composition only. Future CLI commands should wrap the same
public API without adding separate config semantics.

Future CLI commands may call the Python API:

```text
loom validate experiment.yaml
loom plan experiment.yaml
loom run experiment.yaml --set run.seed=123
```

`validate` should compose, expand, resolve, and validate without instantiating or running stages unless explicitly requested.

`plan` should show the resolved pipeline graph and recipe expansions.

When functional CLI behavior is added, `run` should compose config, create a run
directory, and hand execution to `PipelineRunner`. The runner/run store, not
`loom.config`, owns persistence.

---

## 18. Test Strategy

Config tests should be broad enough to prove correctness, but organized by
behavior and source ownership rather than collected into one monolithic config
test directory.

Recommended unit layout:

```text
tests/unit/loom/config/
  test_load.py
  test_merge.py
  test_overrides.py
  test_interpolation.py
  test_validation.py
  test_redaction.py
  test_provenance.py
  test_compose.py
  test_include_resolution.py
  test_includes.py
  test_source_snapshots.py
  recipes/
    test_catalog.py
    test_expansion.py
  instantiate/
    test_targets.py
    test_recursive.py
    test_injection.py
```

Recommended integration layout:

```text
tests/integration/config/
  test_compose_includes.py
  test_compose_overrides.py
  test_compose_recipes.py
  test_compose_provenance.py
  test_compose_validation.py
```

Reusable helpers belong under `tests/support`, not beside production code:

```text
tests/support/configs.py
tests/support/config_assertions.py
tests/support/config_trees/
```

Use a hybrid fixture strategy:

```text
generated temporary YAML:
  default for most tests

checked-in golden config trees:
  only when file layout is the behavior under test
```

Generated fixtures should cover common composition shapes without creating
large fixture directories. Golden config trees should be small and
domain-neutral, and should be reserved for behavior where the authored file
tree matters: bare include resolution, relative includes, `file://` includes,
source metadata/raw snapshot opt-in, and provenance stacks.

The unit suite should cover:

```text
load and parse errors
recursive merge
_replace_ marker behavior
strict update overrides
explicit + add overrides
override value parsing
OmegaConf-style interpolation
redaction
path-aware ConfigError data
include path resolution
recursive include expansion
include cycle errors
required _replace_ for include swaps
unsupported _copy_ errors
scoped validation of loom-owned sections
project-owned pass-through mappings
composition provenance records
source metadata/hash records and raw snapshot opt-in behavior
recipe catalog and expansion
_target_ import and recursive instantiation
runtime dependency injection
```

The integration suite should cover complete `compose_config` flows:

```text
base config plus overlays
strict and + override strings
base and overlay includes
user replacement of included components
interpolation after include expansion
recipe expansion after composition
redaction after composition
stable schema validation after composition
in-memory resolved config without composition markers
fingerprint changes from authored source changes
composition manifest, source metadata/hashes, and raw snapshot opt-in
```

End-to-end config tests should stay small and public-API focused. They should
compose synthetic domain-neutral configs through `compose_config` and assert the
in-memory resolved config, redacted artifact view, provenance, manifests, source
records, and fingerprints. Full pipeline execution belongs to `loom.pipeline`
and runner tests.

---

## 19. Implementation Plan Sketch

Build in this order:

1. Config file loading and recursive merge.
2. Dot-path override string parsing and application.
3. Interpolation and missing-value checks.
4. Redaction, provenance data, empty recipe manifest, and clear rejection of
   `_recipe_` until recipe support lands.
5. Recipe registry and deterministic expansion.
6. Resolved config snapshot data and recipe provenance data.
7. Recursive `_target_` instantiation.
8. Runtime dependency injection.
9. Top-level validation and clear error formatting.
10. V1 `_include_`, `_replace_`, composition manifests, source metadata/hashes,
    raw snapshot opt-in, and explicit `_copy_` rejection.
11. Functional CLI wrappers in a later roadmap version.

Each step should include tests before the next step depends on it.

---

## 20. Summary

`loom.config` should be the narrow configuration layer inside `loom`.

It should support:

```text
explicit `_target_` object graphs
named recipe expansion
simple overlay and override composition
explicit recursive `_include_` composition after v0
explicit `_replace_` component replacement after v0
explicit `_copy_` rejection in v1; subtree reuse remains future work
interpolation
stable validation boundaries
in-memory resolved config for Python callers
recipe provenance
artifact-safe composition provenance, source metadata/hashes, and opt-in raw snapshots
secret redaction
clear instantiation errors
```

It should avoid:

```text
large global registries
implicit include systems and Hydra defaults lists
Hydra-compatible feature breadth
task-specific assumptions
execution behavior
automatic schemas for arbitrary code
YAML `_schema_` bindings or structured-config registries in the initial design
custom interpolation resolvers until their provenance model is clear
plugin-discovered composition extensions until plugin discovery exists
```

This keeps configuration flexible enough for research code while leaving pipeline execution to `loom.pipeline`.
