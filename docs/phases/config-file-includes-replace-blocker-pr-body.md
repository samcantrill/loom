## Summary

@samcantrill

This follow-up lands the scoped Phase 6 review-blocker fix that missed the PR
#31 merge window. It keeps file-authored include expansion strict by rejecting
unconsumed `_replace_` markers authored inside included files, so replacement
markers cannot leak into the final composed config.

No user include swaps, public inspection API, new public `ComposedConfig`
fields, manifests, artifacts, fingerprints, persistence, CLI, pipeline imports,
plugin/remote/global resolvers, recipes, runtime interpolation behavior, raw
source snapshots, or `_copy_` support are added.

## Acceptance Criteria

- [x] Root `_replace_` markers authored inside included files fail closed.
- [x] Nested `_replace_` markers authored inside included files fail closed.
- [x] Valid overlay same-site `_replace_: true` include swaps still work.
- [x] Successful include expansion does not retain `_replace_` markers.

## Implementation Notes

`src/loom/config/includes.py` now rejects unconsumed `_replace_` markers during
recursive include expansion before included mappings become merge bases. The
error uses structured `ConfigIncludeExpansionError` context with the include
site, resolved target, and marker path.

New tests implemented:

- Unit coverage for root and nested `_replace_` markers inside included files.
- Integration coverage that public `compose_config()` rejects included
  `_replace_` markers.
- Regression coverage that valid overlay same-site `_replace_` include swaps
  remain enabled and successful expansions omit `_replace_`.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default harness passed with 425 passed/9 skipped; config-extra passed with 212 passed/430 deselected; build succeeded. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | Wrote `build/test-summary.md`; overall suite evidence passed with 642 passed, 0 failed, 0 errors, 8 skipped, and 430 deselected. |
| Targeted blocker validation | Passed | Include unit tests passed with 43 tests; compose include integration passed with 6 tests; changed-file Ruff/Pyright passed. |
| GitHub checks | Pending | CI starts after PR creation; verify status on the opened PR. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 | 3.74s |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 | 3.99s |
| contract | passed | 26 | 0 | 0 | 1 | 0 | 27 | 1.49s |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 1.97s |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 | 3.45s |
| config-extra | passed | 212 | 0 | 0 | 0 | 430 | 212 | 7.71s |
| Overall | passed | 642 | 0 | 0 | 8 | 430 | 650 | 22.36s |

## Risks / Follow-Ups

- This only closes the Phase 6 replacement-marker blocker. User include swaps,
  public inspection, and artifact/fingerprint population remain later-phase
  work.
