# Durable Many-Run Admission

This project-code example defines its own normalized scientific mapping and
uses `loom.fingerprints.hash_mapping` before streaming requests through
`QueueClient.enqueue_many`.

Run it from the repository root:

```sh
uv run python examples/operations/durable-many-run-admission/run_many.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` to redirect the local queue database.
