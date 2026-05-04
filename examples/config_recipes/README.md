# Config Composition And Recipes

This example demonstrates v0 config composition without running a pipeline:

- base YAML plus overlay YAML
- dot-path overrides
- interpolation before and after recipe expansion
- explicit trusted recipe registration
- recipe manifest and secret redaction output

Run from the repository root:

```sh
uv run python examples/config_recipes/compose_config.py
```

