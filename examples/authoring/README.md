# Authoring Examples

Authoring examples cover how users describe work before it runs: trusted YAML
composition, recipe expansion, interpolation, artifact-safe source records,
structured errors, and recursive `_target_` construction.

## Public Python API Workflows

| Example | Demonstrates |
| --- | --- |
| `authoring.config-composition.basic` | Base YAML plus overlay YAML, ordinary update/add overrides, and the `resolved`, `unresolved`, and `redacted` config views. |
| `authoring.config-composition.includes` | Local `_include_` files, nested includes relative to the including file, user include replacement, brand-new include addition, and include source artifacts. |
| `authoring.config-composition.replacement-overlays` | Multi-overlay order and intentional mapping replacement with `_replace_: true`. |
| `authoring.config-composition.errors` | Structured config errors for missing includes, invalid include overrides, unsupported resolvers, and unsupported `_copy_`. |
| `authoring.recipes` | Trusted recipe registration, recipe expansion, overlays, ordinary overrides, interpolation, recipe manifest output, redaction, and fingerprints. |
| `authoring.artifact-safety` | Metadata-only source artifacts, provenance, redaction, resolver facts, artifact-safe fingerprint comparison, raw snapshot defaults, and raw snapshot opt-in. |
| `authoring.target-instantiation` | Explicit construction of trusted `_target_` object graphs with nested targets, `_args_`, `_partial_`, and `_inject_`. |

## Run

Run from the repository root:

```sh
uv run python examples/authoring/config-composition/basic/compose_basic.py
uv run python examples/authoring/config-composition/includes/compose_includes.py
uv run python examples/authoring/config-composition/replacement-overlays/replacement_overlays.py
uv run python examples/authoring/config-composition/errors/show_errors.py
uv run python examples/authoring/recipes/compose_config.py
uv run python examples/authoring/artifact-safety/artifact_safety.py
uv run python examples/authoring/target-instantiation/instantiate_targets.py
```
