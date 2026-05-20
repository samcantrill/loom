# weave

`weave` contains configuration-related utility foundations that are intentionally lightweight and package-local for Stage 23.

The package currently provides:
- Plain-data normalization helpers
- Stable JSON serialization helpers
- Deterministic digest and fingerprint helpers
- Config-oriented error types and structured context payload helpers

It is scaffolded for future expansion and avoids importing `loom` internals.
