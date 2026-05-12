# Local Pipeline Example

This example demonstrates the main v0 runtime loop:

1. Compose `pipeline.yaml` with `compose_config`.
2. Run a two-stage in-process pipeline with `PipelineRunner` against an explicit
   local authority supervisor.
3. Save and load artifacts through `StageContext` and the local artifact store.
4. Reopen the same run directory with `open_existing=True` so unchanged stages
   are reused.

## Public Python Surface

This example teaches `loom.pipeline.PipelineRunner`, `loom.pipeline.RunRequest`,
and `loom.config.compose_config`.

Run from the repository root:

```sh
uv run python examples/execution/local/run_pipeline.py
```

The script writes run state under `examples/execution/local/runs/` by default.
Set `LOOM_EXAMPLE_OUTPUT_ROOT=/tmp/loom-examples` or
`LOOM_EXAMPLE_RUN_ROOT=/tmp/loom-example-runs` to write somewhere else.
