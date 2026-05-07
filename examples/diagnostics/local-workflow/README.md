# Local Diagnostics Workflow

This example runs a small local pipeline and inspects the resulting run through
the v3 diagnostics CLI:

1. `loom preflight`
2. `loom run`
3. `loom status`
4. `loom artifacts list`
5. `loom artifacts show`

Run from the repository root:

```sh
uv run python examples/diagnostics/local-workflow/run_diagnostics.py
```
