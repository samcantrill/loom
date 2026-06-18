## Phase

- Phase: Phase 2 — Primitives And Serialization
- Branch: `codex/add-primitives-serialization`
- Target: `develop`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-primitives-serialization`
- Plan: `docs/roadmap/stage-0/implementation-plan.md`
- Expanded phase plan: `docs/roadmap/stage-0/phases/add-primitives-serialization.md`

## Summary

Implements the Phase 2 domain-neutral primitive layer for refs, artifacts,
records/manifests, provenance, serialization, protocols, and deterministic
fingerprints.

## Acceptance Criteria

- [x] Frozen typed primitives have deterministic equality and plain-data conversion.
- [x] `ResourceRef.codec_key` round-trips when set, omitted, or explicitly `None`.
- [x] Manifests reject duplicate record IDs and preserve deterministic iteration.
- [x] Manifest views support generic filtering without domain semantics.
- [x] Fingerprints are deterministic across mapping insertion order.
- [x] Serialization outputs only plain structured data.
- [x] Serialization does not import the I/O subsystem.

## Implementation Notes

- Added frozen `ResourceRef`, `ArtifactRef`, and `Record` value objects with
  explicit `to_dict` / `from_dict` conversion and validation at object
  boundaries.
- Added `InMemoryManifest`, `ManifestView`, and generic filters
  (`HasResource`, `MetadataEquals`, `MetadataIn`) with source-order preserving
  iteration.
- Added standard-library-only serialization helpers for plain data, dataclass
  conversion, stable JSON, and schema-version checks.
- Added strict `sha256:<hex>` digest validation and deterministic fingerprint
  helpers built on stable JSON bytes.
- Added generic provenance models and lightweight capture helpers that degrade
  through explicit unavailable/error fields instead of requiring git, network,
  package imports, or heavy dependency inspection.
- Kept Phase 2 boundaries intact: no config composition, I/O sources/codecs,
  filesystem writes, artifact stores, run stores, pipeline specs, execution, or
  CLI behavior were added.

## Tests And Validation

Final validation commands and results:

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright reported 0 errors, default pytest passed with 76 tests, and uv build produced source and wheel distributions.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; wrote build/test-summary.md with suite-level evidence.
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 0.46s | `uv run pytest tests/package -m "not slow and not slurm and not network and not optional_dependency"` |
| unit | passed | 0.36s | `uv run pytest tests/unit -m "not slow and not slurm and not network and not optional_dependency"` |
| contract | not present | 0.00s | `uv run pytest tests/contracts -m "not slow and not slurm and not network and not optional_dependency"` |
| integration | not present | 0.00s | `uv run pytest tests/integration -m "not slow and not slurm and not network and not optional_dependency"` |
| e2e | not present | 0.00s | `uv run pytest tests/e2e -m "not slow and not slurm and not network and not optional_dependency"` |

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

## Risks / Follow-Ups

- Schema-version helpers remain validation-only until a persisted document shape
  needs migration support.
- Filesystem-backed/streaming manifests, stage fingerprint policy, file/stream
  checksum helpers, fuller provenance capture, and YAML helpers remain deferred
  to their owning future phases.
- Phase implementation refinement budget is used; PR review budget remains
  unused for the next workflow stage.
