# Failing Run Diagnostics

This example demonstrates v3 diagnostics for a local pipeline whose first stage
fails. It runs preflight, executes the failing run, then inspects status and
artifact metadata.

Run from the repository root:

```sh
uv run python examples/diagnostics/failing-run/run_failure_diagnostics.py
```
