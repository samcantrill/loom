## Summary

@samcantrill

This Phase 1 PR establishes the configuration artifact contract skeletons and
import-boundary tests needed before later v1 composition phases add behavior.
It adds plain, versioned records for composition manifests, source artifacts,
and config fingerprint fragments under `loom.config.artifacts`.

This is intentionally contract-only work: it does not add compose/include
behavior, resolver execution, run-store writes, CLI commands, `ComposedConfig`
fields, or pipeline construction from manifests. `loom.pipeline` remains
independent from `loom.config` and continues to build from plain data.

## Acceptance Criteria

- [x] `loom.pipeline` remains importable and constructible without `loom.config`.
- [x] Minimal artifact records serialize as plain data with `schema_version`
      fields.
- [x] Manifest records are documented and tested as configuration artifact
      contracts, not pipeline APIs.

## Implementation Notes

- Added `CompositionManifest`, `SourceArtifactRecord`, and
  `ConfigFingerprintRecord` as frozen dataclass contracts in
  `src/loom/config/artifacts.py`, with explicit leaf-module exports.
- Kept records persistence-free and plain-data only, with strict
  `schema_version` validation, unknown-field rejection, and `to_dict()` /
  `from_dict()` round trips.
- Preserved existing `ConfigProvenance` behavior; this phase only adds contract
  coverage around it.
- Added import-boundary checks for `loom.config.artifacts` and plain-data
  pipeline construction so optional config dependencies and config modules do
  not leak into pipeline imports.

New tests implemented:

- Unit coverage for source artifact, fingerprint record, and manifest round
  trips, default metadata, invalid metadata, unknown fields, and accepted future
  source roles.
- Contract coverage for stable artifact/provenance serialization shapes.
- Package import-boundary coverage for `loom.config.artifacts` and
  `loom.pipeline`.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra, and build all passed. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Wrote `build/test-summary.md`; overall suite status passed. |
| GitHub checks | Not run | Expanded-path draft pass only; PR has not been opened yet. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 |
| contract | passed | 20 | 0 | 0 | 1 | 0 | 21 |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 |
| config-extra | passed | 116 | 0 | 0 | 0 | 424 | 116 |
| Overall | passed | 540 | 0 | 0 | 8 | 424 | 548 |

## Risks / Follow-Ups

- Later phases still need to populate these artifact skeletons with real
  include, recipe, provenance, source, and fingerprint data.
- Root or package-level convenience exports remain deferred until the public
  compose and inspection API phase proves the final surface.
- Integration, e2e, raw source snapshot, resolver, run-store, and CLI behavior
  remain out of scope for this phase.
