# Loom Examples

These examples show the implemented v0 Python API. They are intentionally
domain-neutral: project code owns concrete stage behavior, while `loom` owns
configuration, artifact records, local execution, provenance snapshots, and
same-run resume decisions.

## Examples

- `local_pipeline/`: compose a trusted YAML config, run two local stages, save
  JSON and text artifacts, and reopen the same run directory to reuse unchanged
  stages.
- `config_recipes/`: compose base and overlay YAML, apply dot-path overrides,
  expand a trusted `_recipe_` block, inspect the recipe manifest, and see
  redacted secrets.
- `target_instantiation/`: recursively construct trusted `_target_` objects,
  including positional args, partial callables, and runtime injection.

Run each example from the repository root:

```sh
uv run python examples/local_pipeline/run_pipeline.py
uv run python examples/config_recipes/compose_config.py
uv run python examples/target_instantiation/instantiate_targets.py
```

The v0 runtime is local-only. It does not provide a functional CLI, remote
stores, distributed execution, scheduler integration, or cross-run cache reuse.

