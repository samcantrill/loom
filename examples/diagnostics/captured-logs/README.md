# Captured Logs Diagnostics

This example uses the Python runner with `LocalExecutor(capture_stdout_stderr=True)`
to persist stage stdout and stderr, then inspects those logs through the v3
`loom logs` CLI.

Run from the repository root:

```sh
uv run python examples/diagnostics/captured-logs/run_captured_logs.py
```
