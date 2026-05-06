# Pipeline Examples

Pipeline examples cover static pipeline configs, local execution, artifact
storage, and same-run resume behavior.

## Catalog

| Example | Demonstrates |
| --- | --- |
| `pipelines.local-run` | Composing a static pipeline config, running a two-stage local pipeline, writing artifacts through the local store, recording provenance/fingerprints, and reusing unchanged stages from the same run directory. |

## Run

Run from the repository root:

```sh
uv run python examples/pipelines/local-run/run_pipeline.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to redirect generated
run directories.
