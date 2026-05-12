# Replacement Overlays

This example uses the public `loom.config.compose_config` API to compose a
base YAML file with two overlays.

It demonstrates:

- overlay order, where later overlays override earlier overlays;
- `_replace_: true` on an existing mapping;
- replacement marker consumption in the resolved config;
- source order in composition provenance.

## Public Python Surface

This example teaches `loom.config.compose_config`.

Run from the repository root:

```sh
uv run python examples/authoring/config-composition/replacement-overlays/replacement_overlays.py
```
