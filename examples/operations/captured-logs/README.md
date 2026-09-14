# Captured Logs Diagnostics

This example uses a run-owned native coordinator and installed agent worker, then reads captured stdout/stderr through `loom logs`. The stage also writes one file through
`local_output_path()` and explicitly registers it as `report`, while its
workspace note remains a project-owned intermediate file rather than an output.

The example does not make project files discoverable by `loom logs`; it only
captures the stage's Python stdout and stderr. See
[`docs/downstream-operations.md`](../../../docs/downstream-operations.md) for
the complete artifact and log-ownership distinctions.

## Public Python Surface

This example teaches native run-owned coordinator sessions, retained worker log references,
and bounded local content/path inspection.

Run from the repository root:

```sh
uv run python examples/operations/captured-logs/run_captured_logs.py
```
