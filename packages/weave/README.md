# weave

`weave` is the trusted config authoring package used by Loom. It owns YAML
composition, overlays, includes, recipes, interpolation, target instantiation,
config provenance, redaction, config fingerprints, and config-specific errors.

Loom depends on `weave` through explicit adapter paths for CLI and runtime
workflows. `weave` remains independent from Loom runtime modules.

Package-local examples live in [`examples/`](examples/README.md). Package-local
tests live in [`tests/`](tests/).

The package currently provides:
- Plain-data normalization helpers
- Stable JSON serialization helpers
- Deterministic digest and fingerprint helpers
- Config-oriented error types and structured context payload helpers

It is scaffolded for future expansion and avoids importing `loom` internals.
