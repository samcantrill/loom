## Summary

@samcantrill

This follow-up lands the scoped Phase 5 review-blocker fix that missed the PR
#29 merge window. It keeps the include resolver fail-closed for decoded
`file://` paths that cannot be represented as local filesystem paths, including
embedded NUL bytes.

No Phase 6 recursive include behavior, public API, persistence, artifacts,
pipeline imports, CLI, or remote resolver behavior is added.

## Acceptance Criteria

- [x] `file://` paths with decoded embedded NUL bytes fail before candidate
      path validation.
- [x] The failure is a structured `ConfigIncludeResolutionError`, not a raw
      filesystem `ValueError`.
- [x] The fix is limited to the Phase 5 include-resolution blocker and its
      evidence.

## Implementation Notes

`src/loom/config/includes.py` validates the decoded file URI string before
constructing or resolving a `Path`. Embedded NUL bytes now raise
`invalid_file_uri` with `reason` set to `embedded_nul_byte`.

New tests implemented:

- `tests/unit/loom/config/test_includes.py` covers
  `file:///tmp/a%00.yaml` and asserts structured error context.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default harness passed with 424 passed/9 skipped; config-extra passed with 192 passed/429 deselected; build succeeded. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | Wrote `build/test-summary.md`; overall suite evidence passed with 621 passed, 0 failed, 0 errors, 8 skipped, and 429 deselected. |
| Targeted phase validation | Passed | Include unit tests passed with 32 tests; changed-file Ruff passed; changed-file Pyright reported 0 errors. |
| GitHub checks | Pending | CI starts after PR creation; verify status on the opened PR. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 | 3.79s |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 | 3.93s |
| contract | passed | 25 | 0 | 0 | 1 | 0 | 26 | 1.53s |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 1.97s |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 | 3.52s |
| config-extra | passed | 192 | 0 | 0 | 0 | 429 | 192 | 7.59s |
| Overall | passed | 621 | 0 | 0 | 8 | 429 | 629 | 22.34s |

## Risks / Follow-Ups

- This only closes the Phase 5 file URI representability blocker. Recursive
  include traversal, include stacks/cycles, sibling merge behavior, and public
  composition artifacts remain later-phase work.
