# Basic Config Composition

This example demonstrates the public `compose_config` API without recipes,
includes, target instantiation, or pipeline execution:

- base YAML plus overlay YAML
- ordinary update and add overrides
- `resolved`, `unresolved`, and `redacted` views

Run from the repository root:

```sh
uv run python examples/authoring/config-composition/basic/compose_basic.py
```
