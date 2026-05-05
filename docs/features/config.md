# `loom.config` Specification

## 1. Purpose

`loom.config` is the configuration composition and object construction layer for `loom`.

It exists to keep experiment and pipeline configuration readable while preserving full access to ordinary Python code. It should compose YAML, validate stable boundaries, construct object graphs, record provenance, and hand the resolved result to `loom.pipeline`. Recipe expansion is introduced after the initial composition API is in place.

The initial design should be intentionally narrow. The full v0 implementation should support two authoring modes:

1. Full dynamic import instantiation using `_target_`.
2. Named recipes that expand into explicit `_target_` object graphs.

It should avoid intermediate mechanisms at first, especially registry aliases, arbitrary include graphs, complex list merge operators, and large global component registries. Those can be added later if concrete use makes them necessary.

After v0, `loom.config` should add explicit recursive composition through
`_include_`, whole-section replacement through `_replace_`, in-document subtree
reuse through `_copy_`, and rebuildable config source snapshots. This is not
intended to mimic Hydra or depend on Hydra. The goal is a smaller,
deterministic composition feature that lets users split large configs into
nested component files, swap components for experiments, reuse stage config
templates, and preserve clear provenance, fingerprints, and path-aware errors.

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
recipe input.

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
apply CLI overrides
resolve interpolation
expand named recipes
validate configs
resolve import targets
instantiate object graphs
inject runtime dependencies when requested
record config provenance
produce serializable resolved config snapshots for the runner/run store
redact secrets
resolve explicit config includes after v0
resolve explicit config replacements after v0
resolve explicit config copies after v0
produce rebuildable config composition manifests after v0
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

`loom.pipeline` should call `loom.config`; `loom.config` should not call `loom.pipeline` except through optional protocol types.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
YAML config loading
OmegaConf interpolation and dot-path overrides
base experiment config
overlay files
CLI overrides
named recipe expansion
full `_target_` recursive instantiation
runtime dependency injection
partial construction or builder construction
basic top-level validation
recipe-level validation
resolved config snapshot generation
recipe provenance data for the runner/run store to persist
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
explicit `_copy_` subtree reuse for stage/component config templates
strict update overrides plus explicit `+` add overrides
relative include resolution based on the including config file and key path
local path and `file://` include resolution
recursive include expansion with cycle detection
copy expansion with cycle detection
composition provenance, source hashes, and resolved include/copy stacks
deterministic merge of included content with sibling overrides
composition manifests and source snapshots for rebuildable runs
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

The config file as authored before composition, interpolation, recipe expansion, or CLI overrides.

### 5.2 Composed Config

The config after loading base files, overlays, and CLI overrides.

### 5.3 Expanded Config

The config after recipe expansion. At this point, high-level recipe references should have been converted into explicit lower-level config.

### 5.4 Resolved Config

The final config after interpolation, missing-value checks, redaction handling, and validation. This is what the runner/run store should save for reproducibility.

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
know whether a value came from the base file, an include, an overlay, or a CLI
override; provenance records that source information explicitly.

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
not appear in the resolved config. When a mapping with `_replace_: true` has no
destination value to replace, the marker is stripped and the mapping is used as
written.

When `_include_` appears while replacing an existing mapping, `_replace_: true`
is required in the same mapping. A missing marker is a config error rather than
an implicit recursive merge.

### 5.10 Copy

A config mapping that copies an existing subtree from the composed config before
local sibling keys are applied.

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

`_copy_` should use explicit config paths, not implicit global names. Copy
expansion must detect cycles and record both the source path and the destination
path in provenance.

### 5.11 Composition Manifest

A persisted record of authoring-level composition operations used to build the
resolved config.

The manifest should record includes, copies, replacements, overlays, parsed CLI
overrides, source hashes, and source snapshots needed to reconstruct the
composition process. This complements `resolved.yaml`: the resolved config shows
what was used, while the manifest and snapshots explain how to rebuild it even
if project files later move or change.

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

The resolved config should be complete enough to reproduce the run without guessing which recipe, overlay, or CLI argument was used.

A run should save:

```text
config/raw.yaml
config/overlays.yaml
config/cli_overrides.yaml
config/recipe_manifest.json
config/composition_manifest.json
config/resolved.yaml
config/resolved.redacted.yaml
config/source_snapshots/
```

`resolved.yaml` is sufficient to inspect the exact final values used by a run.
To rebuild the composition process from scratch, the run also needs the
composition manifest and source snapshots for base configs, overlays, included
files, including files that define copied source subtrees. Source snapshots
should be content-addressed or otherwise tied to recorded hashes so the manifest
can prove which authored inputs produced the resolved config.

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

Recursive file composition, section replacement, and subtree copying are useful
enough to add after the v0 kernel, but they should remain explicit and
deterministic:

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
_copy_ is allowed only in mappings and deep-copies a composed config subtree
copy expansion records source/destination paths and detects cycles
composition manifests and source snapshots make authored composition rebuildable
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

Subtree reuse should also be explicit:

```yaml
pipeline:
  stages:
    train_alt:
      config:
        _copy_: stage_configs.train_base
        optimizer:
          lr: 0.0001
```

`_copy_` copies the source subtree as plain config data and then applies local
siblings as normal overrides. This is useful for repeated stage configurations
that differ by a small number of values.

This is not a Hydra defaults-list implementation. There is no implicit global
search path, no launcher or sweeper behavior, no arbitrary expression language,
and no automatic registry aliasing for every component.

---

## 7. Composition Order

Full v0 flow after recipes are implemented:

```text
1. Load raw base config.
2. Load overlay configs in order.
3. Merge overlays into base config.
4. Apply CLI dot-path overrides.
5. Resolve enough interpolation for recipe arguments from the composed config.
6. Expand recipes.
7. Resolve interpolation again after expansion.
8. Validate missing values and stable schemas.
9. Redact secrets for persisted config views.
10. Produce raw, overlay, override, recipe, and resolved provenance data for
   the runner/run store to persist.
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

Post-v0 composition with includes, replacement, and copies should preserve the
core merge rules while treating base files, overlays, and CLI dot-path
overrides as authoring-level inputs:

```text
load base config
load overlays
parse CLI dot-path overrides into a highest-precedence override mapping
recursive merge overlays and override mapping into base config, honoring _replace_
recursively expand includes
recursively expand copies
resolve enough interpolation for recipe args
expand recipes
resolve interpolation again
validate
redact
compute config provenance and fingerprint
```

For ordinary values, CLI overrides remain the highest-precedence authoring
input. Representing them as an override mapping before directive expansion lets
experiments and sweeps replace component selections with values such as
`model._include_=vit_b16` or by applying `_replace_: true` to an entire section.

Implementation should preserve source-location metadata through the merge so an
include authored in an overlay still resolves relative to that overlay file. A
bare include authored by CLI override should resolve relative to the root config
file directory and the overridden config path unless it is an explicit path or
URI.

Copy expansion happens after include expansion so copied stage or component
templates contain the same included defaults they would have had at their
source location.

Directive validation happens during composition. Stable typed validation happens
after directives, recipes, and interpolation have produced the resolved config
shape. This keeps `_include_`, `_replace_`, and `_copy_` as composition
directives rather than schema declarations.

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

## 9. CLI Overrides

Support dot-path overrides with explicit add syntax:

```text
loom run experiment.yaml \
  --set run.seed=123 \
  --set serialization.codec.indent=2 \
  --set data.root=/data/project \
  --set +vars.learning_rate=0.0003
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
--set +vars.learning_rate=0.0003
--set +evaluation.metrics='["accuracy", "loss"]'
--set +model._replace_=true --set model._include_=vit_b16
```

The final example switches an existing included component. `model._include_`
updates an existing include target, while `+model._replace_=true` explicitly
adds the required replacement marker. If the config path does not already have
a `model` mapping, a new included component can be introduced with
`+model._include_=vit_b16`.

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
  endpoint: ${env:LOOM_STORAGE_ENDPOINT}
  token: ${env:LOOM_STORAGE_TOKEN}
```

Secrets resolved from environment variables should be redacted from persisted public views.

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
  required import path

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
source file, overlay, include, copy, or CLI override
include/copy stack when relevant
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

Persist both:

```text
resolved.yaml:
  full resolved config, private and local-only

resolved.redacted.yaml:
  safe for logs and bug reports
```

Do not print unredacted secrets in error messages.

---

## 15. Public API

Recommended API:

```python
from loom.config import (
    RecipeCatalog,
    compose_config,
    compose_config_with_catalog,
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
composition_manifest after v1
source_snapshots after v1
fingerprint
```

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
config, an overlay, an included file or URI, a copied subtree, a replacement
mapping, or a CLI override.

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

## 17. CLI Integration

`loom.config` should support the `loom` CLI without becoming CLI-specific.

CLI commands can call the Python API:

```text
loom validate experiment.yaml
loom plan experiment.yaml
loom run experiment.yaml --set run.seed=123
```

`validate` should compose, expand, resolve, and validate without instantiating or running stages unless explicitly requested.

`plan` should show the resolved pipeline graph and recipe expansions.

When functional CLI behavior is added, `run` should compose config, create a run
directory, and hand execution to `PipelineRunner`. The runner, not
`loom.config.instantiate`, parses `pipeline.stages` and imports stage targets
with no constructor kwargs in v0.

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
  test_copies.py
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
  test_compose_copies.py
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
source snapshots, and provenance stacks.

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
_copy_ deep-copy behavior
copy cycle errors
scoped validation of loom-owned sections
project-owned pass-through mappings
composition provenance records
source snapshot hashing
recipe catalog and expansion
_target_ import and recursive instantiation
runtime dependency injection
```

The integration suite should cover complete `compose_config` flows:

```text
base config plus overlays
strict and + CLI overrides
base and overlay includes
CLI replacement of included components
copying included defaults
interpolation after include/copy expansion
recipe expansion after composition
redaction after composition
stable schema validation after composition
resolved config without composition markers
fingerprint changes from authored source changes
composition manifest and source snapshots
```

End-to-end config tests should stay small and public-API focused. They should
compose synthetic domain-neutral configs through `compose_config` and assert the
resolved config, redacted view, provenance, manifests, and fingerprints. Full
pipeline execution belongs to `loom.pipeline` and runner tests.

---

## 19. Implementation Plan Sketch

Build in this order:

1. Config file loading and recursive merge.
2. Dot-path CLI override parsing and application.
3. Interpolation and missing-value checks.
4. Redaction, provenance data, empty recipe manifest, and clear rejection of
   `_recipe_` until recipe support lands.
5. Recipe registry and deterministic expansion.
6. Resolved config snapshot data and recipe provenance data.
7. Recursive `_target_` instantiation.
8. Runtime dependency injection.
9. Top-level validation and clear error formatting.
10. Post-v0 `_include_`, `_replace_`, `_copy_`, composition manifests, and
    source snapshots.
11. Functional CLI wrappers after v0.

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
explicit `_copy_` subtree reuse after v0
interpolation
stable validation boundaries
resolved config export
recipe provenance
composition provenance and rebuildable source snapshots after v0
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
