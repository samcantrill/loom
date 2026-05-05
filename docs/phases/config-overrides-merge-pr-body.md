## Summary

@samcantrill

This PR implements the v1 Configuration Phase 3 merge primitive for strict whole-section replacement. `merge_configs()` now treats `_replace_: true` as a Loom-owned directive when a higher-precedence mapping replaces an existing lower-precedence mapping, consumes the marker, validates invalid or unnecessary marker use, and keeps recursive merge behavior when the marker is absent.

The phase also hardens focused override and merge coverage for typed override values, strict update versus explicit add behavior, non-mutating helper behavior, literal numeric mapping keys, root-level replacement, and scalar/list/null replacement semantics.

## Acceptance Criteria

- [x] Update overrides fail on missing paths, and explicit `+` add overrides fail on existing paths.
- [x] Mapping-over-mapping merges recurse unless `_replace_: true` requests whole-section replacement.
- [x] `_replace_: true` is consumed, omitted from returned config, and rejected when invalid, marker-only, or unnecessary.
- [x] Scalar, list, mapping-over-non-mapping, non-mapping-over-mapping, and explicit `null` replacements remain direct replacements.

## Implementation Notes

`src/loom/config/merge.py` now normalizes base and overlay values without mutating caller inputs, delegates child merge decisions through `_merge_values()`, and centralizes `_replace_` validation in `_merge_replace_mapping()`. Root-level `_replace_: true` is supported when replacing the whole root mapping because the top-level merge is still a mapping-over-existing-mapping operation.

This phase intentionally does not add include loading, source-authored overlays, recursive include expansion, recipe ordering changes, public inspection APIs, persistence artifacts, CLI behavior, provenance population, fingerprints, `_copy_`, escaped-dot override paths, list indexing, or list patching.

New or changed tests cover:

- Override parser typed values, invalid dot paths, ordered add/update behavior, parent creation only for explicit adds, non-mapping traversal failures, numeric-looking mapping keys, and non-mutation.
- Merge recursive behavior, scalar/list/null replacement, mapping/non-mapping type replacement, `_replace_` success and failure cases, root replacement, marker omission, and non-mutation.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default suite passed 423 tests with 9 skipped; config-extra passed 145 tests with 428 deselected; build succeeded. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | `build/test-summary.md` generated 2026-05-05T07:01:43Z with overall 573 passed, 8 skipped, 428 deselected. |
| GitHub checks | Pending | PR created from `codex/config-overrides-merge` to `develop`; remote checks had not completed at creation time. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 |
| contract | passed | 24 | 0 | 0 | 1 | 0 | 25 |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 |
| config-extra | passed | 145 | 0 | 0 | 0 | 428 | 145 |
| Overall | passed | 573 | 0 | 0 | 8 | 428 | 581 |

## Risks / Follow-Ups

- Override and merge errors remain stable message-only subclasses in this phase; structured override/merge diagnostic payloads remain later Phase 7 or Phase 12 work.
- Add overrides may create missing parent mappings only for explicit `+` operations; schema validation and public orchestration remain later-phase responsibilities.
- This PR does not change final v1 `compose_config` ordering for includes, recipes, user composition overrides, or ordinary value overrides.
