## Summary

@samcantrill

This PR implements Phase 6 file-defined recursive `_include_` expansion for
configuration composition. Base and overlay YAML can now include mapping
components, expand nested includes relative to the file that authored each
directive, merge local siblings over included content, and reject cycles or
invalid include roots with source-aware structured errors.

The change keeps Phase 6 scoped to file-authored composition. User-defined
include swaps, public inspection fields, manifests, fingerprints, source
artifact population, resolver policy changes, CLI behavior, and run-store writes
remain out of scope for later phases.

## Acceptance Criteria

- [x] Nested file-authored includes expand recursively before local sibling
  keys merge over included content.
- [x] Include cycles fail with active include-stack context and the attempted
  repeated target.
- [x] Sibling customizations are recorded as local add or override facts.
- [x] Include swaps over existing lower-precedence mapping content require
  same-site `_replace_: true`.

## Implementation Notes

`src/loom/config/includes.py` now owns the recursive expansion stage, including
internal include-site records, include-stack frames, local customization records,
cycle detection, source-aware include-root errors, and same-site replacement
enforcement. It reuses the Phase 5 include resolver and strict loader rather
than adding another target parser.

`src/loom/config/source_maps.py` now carries narrow internal mapping-site and
consumed replacement-site facts so include expansion can distinguish valid
overlay component swaps from accidental stale-key merges. `src/loom/config/compose.py`
wires file include expansion after source-aware base/overlay merge and before
user overrides, recipes, interpolation, validation, redaction, provenance, and
fingerprinting. `ConfigIncludeExpansionError` adds a structured error type for
expansion-time failures.

New tests implemented:

- Unit coverage for nested includes, bare-name resolution from included files,
  cycle diagnostics, non-string include values, missing source-map entries,
  non-mapping include roots, sibling customization records, and `_replace_`
  edge cases.
- Integration coverage for public `compose_config` ordering across base,
  overlays, file include expansion, and ordinary user overrides.
- Contract coverage for structured include expansion error serialization.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default suite passed 425/425 with 9 skipped; config-extra suite passed 209/209 selected; build produced sdist and wheel. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | Wrote `build/test-summary.md`; overall summary passed 639 tests with 8 skipped and 430 deselected. |
| GitHub checks | Pending | Available after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 36 | 0 | 0 | 1 | 0 | 3.89s |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 3.92s |
| contract | passed | 26 | 0 | 0 | 1 | 0 | 1.54s |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 1.83s |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 3.40s |
| config-extra | passed | 209 | 0 | 0 | 0 | 430 | 7.61s |
| Overall | passed | 639 | 0 | 0 | 8 | 430 | 22.19s |

## Risks / Follow-Ups

- Include-site and local customization records remain internal handoff data;
  later inspection, manifest, source artifact, and fingerprint phases may expose
  or reshape them additively.
- User-defined include swaps are intentionally not implemented here and remain a
  Phase 7 responsibility.
- Public artifact-safe config fields, resolver handling, raw source snapshots,
  CLI behavior, and run-store persistence remain deferred to later v1 phases.
