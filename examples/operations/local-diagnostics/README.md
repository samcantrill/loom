# Local Diagnostics Workflow

## Workflow

The run entrypoints use public `loom.run` with a protected installed agent
profile. Preparation, execution, fenced results and owned-service cleanup follow
the [configured lifecycle](../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). The native admission supplies run status;
typed materialized worker results supply output and diagnostic details after
owned services stop. The short deployment root printed by the script is retained
for inspection; artifacts default to this example's `runs/` directory. Set
`LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to relocate artifacts.

This example runs preflight, executes a two-stage native pipeline, and reports
terminal status, cleanup and materialized artifact count. Successful results
retain the numerical summary and registered text note.

```sh
uv run python examples/operations/local-diagnostics/run_diagnostics.py
```

## Variants

Deployment selection owns ordinary-run backend and lifetime policy. Existing
status/log commands can inspect a matching retained run. For a run created with
co-located service authority, those diagnostic commands accept
`--authority-backend co_located_service --authority-profile co_located`; these
flags do not override the ordinary managed run's installed profile.
