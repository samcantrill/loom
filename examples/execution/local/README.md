# Local Pipeline Example

This example demonstrates the main v0 runtime loop:

1. Compose `pipeline.yaml` with `compose_config`.
2. Run two independent in-process branches with `PipelineRunner` against an explicit
   local authority supervisor.
3. Save and load artifacts through `StageContext` and the local artifact store.
4. Reopen the same run directory with `open_existing=True` so unchanged stages
   are reused.
5. Corrupt the saved left-branch input artifact to demonstrate checksum-driven
   repair: that producer and its consumer rerun while the independent right
   branch remains `REUSE`.

## Public Python Surface

This example teaches `loom.pipeline.PipelineRunner`, `loom.pipeline.RunRequest`,
and `weave.compose_config`.

Run from the repository root:

```sh
uv run python examples/execution/local/run_pipeline.py
```

The script writes run state under `examples/execution/local/runs/` by default.
Set `LOOM_EXAMPLE_OUTPUT_ROOT=/tmp/loom-examples` or
`LOOM_EXAMPLE_RUN_ROOT=/tmp/loom-example-runs` to write somewhere else.

The output reads the persisted composition manifest and execution plan to show a
non-empty config fingerprint and stage-fingerprint count. It asserts all stages
are `REUSE` when fingerprints and artifacts are unchanged, then asserts the
checksum-invalid branch repair split. This is distinct from an ordinary authored
config change after an authority output commit: that change remains fail closed
and is intentionally not a same-run overwrite path.
