# Config Includes

This example demonstrates local YAML includes through the public
`compose_config` API:

- an explicit relative include authored in the base config;
- a nested include resolved relative to the file that contains it;
- user replacement of an existing include while preserving local sibling
  customizations;
- user addition of a brand-new include site with an explicit relative target.

## Public Python Surface

This example teaches `loom.config.compose_config`.

Run from the repository root:

```sh
uv run python examples/authoring/config-composition/includes/compose_includes.py
```

The example uses only trusted local files and public composition overrides. It
does not use plugin, remote, global search path, or custom resolver behavior.
