# Captured Logs Diagnostics

This example uses the Python runner with
`LocalExecutor(capture_stdout_stderr=True)` under an explicit local authority
supervisor to persist stage stdout and stderr, then inspects those logs through
the v3 `loom logs` CLI. The stage also writes one file through
`local_output_path()` and explicitly registers it as `report`, while its
workspace note remains a project-owned intermediate file rather than an output.

The example does not make project files discoverable by `loom logs`; it only
captures the stage's Python stdout and stderr. See
[`docs/downstream-operations.md`](../../../docs/downstream-operations.md) for
the complete artifact and log-ownership distinctions.

## Public Python Surface

This example teaches `loom.pipeline.PipelineRunner`, `loom.pipeline.RunRequest`,
and `loom.pipeline.executors.LocalExecutor`.

Run from the repository root:

```sh
uv run python examples/operations/captured-logs/run_captured_logs.py
```
