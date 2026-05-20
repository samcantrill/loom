# Config Error Handling

This example demonstrates structured config errors from the public
`compose_config` API:

- missing local include target
- invalid include override value
- unsupported resolver expression
- unsupported `_copy_` directive

## Public Python Surface

This example teaches `weave.compose_config` and the structured config
errors it raises.

The entrypoint catches each exception and prints selected context fields rather
than relying on full error message text.

Run from the repository root:

```sh
uv run python examples/authoring/config-composition/errors/show_errors.py
```
