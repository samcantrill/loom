# Runtime Profile Run

The run entrypoints use public `loom.run` with a protected installed agent
profile. Preparation, execution, fenced results and owned-service cleanup follow
the [configured lifecycle](../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). The native admission supplies run status;
typed materialized worker results supply output and diagnostic details after
owned services stop. The short deployment root printed by the script is retained
for inspection; artifacts default to this example's `runs/` directory. Set
`LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to relocate artifacts.

This example preserves authored runtime tags, notes and per-stage resources,
adds invocation tags/notes, and reads the persisted safe `runtime.json` summary.
The installed agent profile selects the worker environment.

```sh
uv run python examples/execution/runtime-profile/run_runtime_profile.py
```
