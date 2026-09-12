# Failing Run Diagnostics

The run entrypoints use public `loom.run` with a protected installed agent
profile. Preparation, execution, fenced results and owned-service cleanup follow
the [configured lifecycle](../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). The native admission supplies run status;
typed materialized worker results supply output and diagnostic details after
owned services stop. The short deployment root printed by the script is retained
for inspection; artifacts default to this example's `runs/` directory. Set
`LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to relocate artifacts.

This example runs preflight and a native pipeline whose first stage fails.
It reports the native failed admission, failed stage names and artifact count;
structured failure and logs remain in the materialized worker result.

```sh
uv run python examples/operations/failing-run/run_failure_diagnostics.py
```
