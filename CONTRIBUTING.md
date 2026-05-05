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

`make check` runs Ruff, Pyright, and the default Pytest suite. Use
`make validate-pr` before opening a PR to run Ruff, Pyright, the default test
suite, and the package build.

Use `make help` to list target groups, then `make setup-help`, `make dev-help`,
or `make test-help` for grouped target details.

Focused test targets are available for phase work:

```sh
make test-help
make test-package
make test-unit
make test-contract
make test-integration
make test-e2e
make test-summary
```

`make test-summary` writes a Markdown suite summary under `build/` for PR
review.

## Scope

Keep contributions focused on the generic `loom` infrastructure. Domain-specific
stages, recipes, codecs, datasets, and analysis logic belong in downstream
packages.
