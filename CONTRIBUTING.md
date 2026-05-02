# Contributing

This project is in repository setup before v0 implementation.

## Development Setup

```sh
uv sync --all-groups
```

## Checks

Run the local quality gate before committing:

```sh
make check
```

`make check` runs Ruff, Pyright, and Pytest. Use `make build` to verify the
package can be built.

## Scope

Keep contributions focused on the generic `loom` infrastructure. Domain-specific
stages, recipes, codecs, datasets, and analysis logic belong in downstream
packages.
