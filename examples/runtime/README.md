# Runtime Examples

Runtime examples cover the v4 invocation policy surface: typed resource entries,
runtime profiles, CLI/config/Python `RunOptions` mapping, capability
diagnostics, and safe `runtime.json` metadata.

## Catalog

| Example | Demonstrates |
| --- | --- |
| `runtime.runtime-profile-run` | Configured runtime profile, CLI tags/notes, resource diagnostics, local run, and safe `runtime.json`. |
| `runtime.resource-preflight` | Local executor resource warnings and strict preflight escalation. |
| `runtime.python-run-options` | Public Python construction, merge, stage validation, and capability diagnostics for `RunOptions`. |

## Run

Run from the repository root:

```sh
uv run python examples/runtime/runtime-profile-run/run_runtime_profile.py
uv run python examples/runtime/resource-preflight/run_resource_preflight.py
uv run python examples/runtime/python-run-options/run_options_api.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to redirect generated
run directories.
