## Summary

Add the Stage 15 Phase 1 external artifact record surface in `loom.artifacts`:
location kinds, backend-neutral store refs, location summaries, external
immutable declarations, published immutable records, and explicit immutable
lookup request/result records.

The implementation keeps `ArtifactRef` and `ArtifactAddress` compatibility
unchanged while adding strict plain-data `to_dict`/`from_dict` contracts for the
new adjacent records. No backend registry, plugin loading, preflight,
catalog/bundle exchange behavior, payload movement, or real adapter behavior is
included in this phase.

## Acceptance Criteria

- [x] New artifact records round trip through strict plain dictionaries with
      unknown-field rejection, digest validation, enum/status validation,
      non-negative size checks, and frozen internal plain data.
- [x] Existing `ArtifactRef` dictionaries remain compatible, including
      positive integer schema versions.
- [x] `loom.artifacts` remains import-light and does not import stores,
      plugins, diagnostics, runs, CLI, config extras, or optional backend SDKs.

## Implementation Notes

- Added public exports from `loom.artifacts` for
  `ArtifactLocationKind`, `ArtifactStoreRef`, `ArtifactLocationSummary`,
  `ExternalArtifactDeclaration`, `PublishedArtifactRecord`,
  `ImmutableArtifactLookupRequest`, and `ImmutableArtifactLookupResult`.
- Kept store refs generic: `ArtifactStoreRef.kind` is a backend-neutral string,
  while `ArtifactLocationSummary.kind` is the location-kind enum.
- Preserved the adjacent-record strategy. `ArtifactRef` top-level schema was not
  expanded.

New tests implemented:

- Unit coverage for strict round trips, invalid shapes, digest and size checks,
  immutability of nested plain data, and old `ArtifactRef` compatibility.
- Contract coverage for serialized field sets, location-kind values, lookup
  statuses, authority rules, and display URI separation.
- Package/import-boundary coverage for `loom.artifacts` exports and import
  safety.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Focused Phase 1 pytest paths | passed | 88 passed in 14.72s |
| `make validate-pr` | passed | Ruff passed; Pyright 0 errors; default harness 1622 passed / 26 skipped / 18 deselected; config-extra 440 passed / 1659 deselected; build passed |
| `make test-summary` | passed | Overall 2090 passed / 18 skipped / 1675 deselected |
| GitHub checks | pending | To run after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: |
| package | passed | 90 | 1 | 0 |
| unit | passed | 1142 | 7 | 1 |
| contract | passed | 219 | 2 | 0 |
| integration | passed | 156 | 8 | 13 |
| e2e | passed | 43 | 0 | 2 |
| config-extra | passed | 440 | 0 | 1659 |
| Overall | passed | 2090 | 18 | 1675 |

## Risks / Follow-Ups

- Later phases must keep backend registry, plugin adapter, diagnostics,
  catalog/bundle, and run-exchange behavior layered on top of these plain
  records instead of importing those systems into `loom.artifacts`.
- Redaction mechanics remain handler-owned future work; Phase 1 records only
  preserve separate `uri` and `display_uri` fields.
