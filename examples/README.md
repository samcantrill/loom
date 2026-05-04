# Loom Examples

These examples show supported `loom` behavior through small, domain-neutral
projects. Project code owns concrete stages and recipes; `loom` owns
configuration, artifact records, local execution, provenance snapshots, and
same-run resume decisions.

Examples are organized by user-facing capability. Each example has its own
`README.md`, copyable project code, and an `example.yaml` manifest used by tests.

## Catalog

| Example | Capability | Validation | Summary |
| --- | --- | --- | --- |
| `config.recipes` | config | smoke | Compose YAML with overlays, overrides, interpolation, and trusted recipe expansion. |
| `config.target-instantiation` | config | smoke | Recursively construct trusted `_target_` object graphs. |
| `pipelines.local-run` | pipelines | smoke | Run a local two-stage pipeline and reuse unchanged stages from the same run directory. |

Run each smoke example from the repository root:

```sh
uv run python examples/config/recipes/compose_config.py
uv run python examples/config/target-instantiation/instantiate_targets.py
uv run python examples/pipelines/local-run/run_pipeline.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT=/tmp/loom-examples` to redirect generated example
outputs. Pipeline examples also accept `LOOM_EXAMPLE_RUN_ROOT` for run
directories.

## Validation Tiers

- `smoke`: fast runnable examples covered by default integration tests.
- `full`: runnable examples that are useful but too slow or broad for the
  default test path; tests should mark these `slow`.
- `manual`: illustrative examples that cannot run in the default environment and
  must document why in their manifest.

The v0 runtime is local-only. It does not provide a functional CLI, remote
stores, distributed execution, scheduler integration, or cross-run cache reuse.
