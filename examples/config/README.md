# Config Examples

Config examples cover trusted YAML composition, recipe expansion, interpolation,
and recursive `_target_` construction.

## Catalog

| Example | Demonstrates |
| --- | --- |
| `config.basic-composition` | Base YAML plus overlay YAML, ordinary update/add overrides, and the `resolved`, `unresolved`, and `redacted` config views. |
| `config.includes` | Local `_include_` files, nested includes relative to the including file, user include replacement, brand-new include addition, and include source artifacts. |
| `config.recipes` | Trusted recipe registration, recipe expansion, overlays, ordinary overrides, interpolation, recipe manifest output, redaction, and fingerprints. |
| `config.replacement-overlays` | Multi-overlay order and intentional mapping replacement with `_replace_: true`. |
| `config.artifact-safety` | Metadata-only source artifacts, provenance, redaction, resolver facts, artifact-safe fingerprint comparison, raw snapshot defaults, and raw snapshot opt-in. |
| `config.target-instantiation` | Explicit construction of trusted `_target_` object graphs with nested targets, `_args_`, `_partial_`, and `_inject_`. |
| `config.errors` | Structured config errors for missing includes, invalid include overrides, unsupported resolvers, and unsupported `_copy_`. |

## Run

Run from the repository root:

```sh
uv run python examples/config/basic-composition/compose_basic.py
uv run python examples/config/includes/compose_includes.py
uv run python examples/config/recipes/compose_config.py
uv run python examples/config/replacement-overlays/replacement_overlays.py
uv run python examples/config/artifact-safety/artifact_safety.py
uv run python examples/config/target-instantiation/instantiate_targets.py
uv run python examples/config/errors/show_errors.py
```
