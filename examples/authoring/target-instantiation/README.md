# Target Instantiation

This example demonstrates recursive construction of trusted `_target_` config
blocks after config composition:

- nested target construction
- positional args with `_args_`
- deferred construction with `_partial_`
- runtime object injection with `_inject_`

## Public Python Surface

This example teaches `loom.config.instantiate`.

Run from the repository root:

```sh
uv run python examples/authoring/target-instantiation/instantiate_targets.py
```
