# Loom

`loom` is a lightweight runtime for composing, running, and tracing reproducible research pipelines.

The package focuses on generic infrastructure:

- configuration composition and object construction
- recipe expansion for reusable configuration patterns
- artifact and resource references
- pipeline stages, run directories, and resumable execution
- provenance, fingerprints, and clear error reporting

Detailed design notes live in:

- [docs/loom.md](docs/loom.md)
- [docs/config.md](docs/config.md)
- [docs/structure.md](docs/structure.md)
- [docs/future.md](docs/future.md)

## Development

```sh
uv sync --all-groups
make check
make build
```
