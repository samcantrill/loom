# Captured Logs Diagnostics

This example uses the Python runner with
`LocalExecutor(capture_stdout_stderr=True)` under an explicit local authority
supervisor to persist stage stdout and stderr, then inspects those logs through
the v3 `loom logs` CLI.

## Public Python Surface

This example teaches `loom.pipeline.PipelineRunner`, `loom.pipeline.RunRequest`,
and `loom.pipeline.executors.LocalExecutor`.

Run from the repository root:

```sh
uv run python examples/operations/captured-logs/run_captured_logs.py
```
