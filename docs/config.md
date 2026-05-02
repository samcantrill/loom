# `loom.config` Specification

## 1. Purpose

`loom.config` is the configuration composition and object construction layer for `loom`.

It exists to keep experiment and pipeline configuration readable while preserving full access to ordinary Python code. It should compose YAML, expand named recipes, validate stable boundaries, construct object graphs, record provenance, and hand the resolved result to `loom.pipeline`.

The initial design should be intentionally narrow. The first implementation should support two authoring modes:

1. Full dynamic import instantiation using `_target_`.
2. Named recipes that expand into explicit `_target_` object graphs.

It should avoid intermediate mechanisms at first, especially registry aliases, arbitrary include graphs, complex list merge operators, and large global component registries. Those can be added later if concrete use makes them necessary.

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

This means `loom.config` is not a workflow engine. It does not run stages or interpret application-specific data. It composes configs, expands recipes, validates structure, constructs Python objects, records provenance, and provides the resulting config/object graph to the caller.

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
write resolved configs
redact secrets
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
resolved config export
include/recipe provenance
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

---

## 5. Terminology

### 5.1 Raw Config

The config file as authored before composition, interpolation, recipe expansion, or CLI overrides.

### 5.2 Composed Config

The config after loading base files, overlays, and CLI overrides.

### 5.3 Expanded Config

The config after recipe expansion. At this point, high-level recipe references should have been converted into explicit lower-level config.

### 5.4 Resolved Config

The final config after interpolation, missing-value checks, redaction handling, and validation. This is what should be saved for reproducibility.

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
    _target_: loom.io.sources.LocalFileSystemSource
    root: /data/project
  discovery:
    _target_: loom.io.sources.GlobDiscovery
    pattern: "*.jsonl"
  manifest:
    _target_: loom.records.ManifestBuilder
    source: ${data.source}
    discovery: ${data.discovery}
```

### 5.7 Target

A Python import path used to construct an object.

Supported forms:

```text
package.module.Class
package.module:function
package.module:Class
```

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
config/resolved.yaml
```

### 6.3 Prefer Recipes Over Intermediate Aliases in v0

An alias like `default_runner` can be convenient, but aliases, registries, includes, and scoped config references add another layer of ambiguity. The first version should avoid these unless needed.

For now:

```yaml
runner:
  _target_: loom.pipeline.runner.PipelineRunner
  executor:
    _target_: loom.pipeline.executors.LocalExecutor
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

---

## 7. Composition Order

Recommended flow:

```text
1. Load raw base config.
2. Load overlay configs in order.
3. Merge overlays into base config.
4. Apply CLI dot-path overrides.
5. Expand recipes.
6. Resolve interpolation.
7. Validate missing values and stable schemas.
8. Redact secrets for persisted config views.
9. Save raw, overlay, override, recipe, and resolved provenance.
10. Instantiate object graph when requested.
```

Recipe expansion should happen before final interpolation so expanded blocks can reference values elsewhere in the config.

---

## 8. Merge Semantics

Default merge behavior should be simple:

```text
mapping + mapping:
  recursive merge

scalar + scalar:
  override

list + list:
  replace whole list

null:
  explicit null value
```

Do not add list splice operators until there is a clear recurring need.

---

## 9. CLI Overrides

Support dot-path overrides:

```text
loom run experiment.yaml \
  --set run.seed=123 \
  --set pipeline.executor.max_workers=8 \
  --set data.root=/data/project
```

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

---

## 10. Interpolation

Use OmegaConf-style interpolation if OmegaConf is installed with the config extra.

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
                "_target_": "loom.io.sources.LocalFileSystemSource",
                "root": self.root,
            },
            "discovery": {
                "_target_": "loom.io.sources.GlobDiscovery",
                "pattern": self.pattern,
            },
            "manifest": {
                "_target_": "loom.records.ManifestBuilder",
                "source": "${data.source}",
                "discovery": "${data.discovery}",
            },
        }
```

The recipe may validate its own arguments before returning expanded config.

### 11.2 Recipe Catalog

Recipes should be registered by name.

```python
from loom.config import register_recipe

register_recipe("local_jsonl_manifest", LocalJsonlManifestRecipe)
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

---

## 12. Object Instantiation

Any mapping with `_target_` should be constructible.

```yaml
executor:
  _target_: loom.pipeline.executors.LocalExecutor
  max_workers: 4
```

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
```

Avoid automatic schema inference for arbitrary `_target_` classes. That creates surprising behavior and unclear ownership.

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
resolved.full.yaml:
  private, local-only, optional

resolved.redacted.yaml:
  safe for logs and bug reports
```

Do not print unredacted secrets in error messages.

---

## 15. Public API

Recommended API:

```python
from loom.config import (
    compose_config,
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

`instantiate`:

```python
pipeline = instantiate(cfg["pipeline"])
```

`register_recipe`:

```python
register_recipe("local_jsonl_manifest", LocalJsonlManifestRecipe)
```

---

## 16. Error Messages

Config errors should identify the failing path and the exact problem.

Example:

```text
Could not instantiate target project.stages.SummarizeStage.

Config path:
  pipeline.stages[1]

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

`run` should compose config, instantiate the pipeline, create a run directory, and hand execution to `loom.pipeline`.

---

## 18. Initial Implementation Plan

Build in this order:

1. Config file loading and recursive merge.
2. Dot-path CLI override parsing and application.
3. Interpolation and missing-value checks.
4. Recipe registry and deterministic expansion.
5. Resolved config export and recipe provenance.
6. Recursive `_target_` instantiation.
7. Runtime dependency injection.
8. Redaction.
9. Top-level validation and clear error formatting.
10. CLI wrappers.

Each step should include tests before the next step depends on it.

---

## 19. Summary

`loom.config` should be the narrow configuration layer inside `loom`.

It should support:

```text
explicit `_target_` object graphs
named recipe expansion
simple overlay and override composition
interpolation
stable validation boundaries
resolved config export
recipe provenance
secret redaction
clear instantiation errors
```

It should avoid:

```text
large global registries
implicit include systems
Hydra-compatible feature breadth
task-specific assumptions
execution behavior
automatic schemas for arbitrary code
```

This keeps configuration flexible enough for research code while leaving pipeline execution to `loom.pipeline`.
