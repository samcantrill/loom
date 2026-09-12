# Subprocess Pipeline Example

The run entrypoints use public `loom.run` with a protected installed agent
profile. Preparation, execution, fenced results and owned-service cleanup follow
the [configured lifecycle](../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). The native admission supplies run status;
typed materialized worker results supply output and diagnostic details after
owned services stop. The short deployment root printed by the script is retained
for inspection; artifacts default to this example's `runs/` directory. Set
`LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to relocate artifacts.

The success script runs two stages in supervised native workers and reports
materialized outputs. The failure script retains the failed stage's stderr and
structured failure. The separate direct-worker example retains its prepared-stage
primitive; it does not demonstrate the ordinary managed run entrypoint.

```sh
uv run python examples/execution/subprocess/run_subprocess_pipeline.py
uv run python examples/execution/subprocess/run_failure_diagnostics.py
uv run python examples/execution/subprocess/run_direct_worker.py
```
