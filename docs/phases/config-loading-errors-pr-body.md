## Summary

@samcantrill

This PR implements v1 Phase 2 for Configuration: strict single-source YAML loading and structured config loading errors. Loader failures now carry machine-readable context for source kind/order/path, config path, stable code, expected/actual shape, directive, remediation, and plain-data details.

It also rejects `_copy_` anywhere in authored config as an explicit unsupported directive while preserving `_include_` and `_replace_` as ordinary data until later phases implement their semantics.

## Acceptance Criteria

- [x] Enforce single-document UTF-8 YAML with non-empty mapping roots and plain-data parsed values.
- [x] Reject `_copy_` anywhere in authored mappings with structured unsupported-directive context.
- [x] Preserve `ConfigError` / `ConfigLoadError` catch compatibility and expose serializable context without parsing message text.

## Implementation Notes

- Added `ConfigErrorContext`, context-bearing config exceptions, and an `UnsupportedConfigDirectiveError` that remains catchable as `ConfigLoadError`.
- Updated `load_config()` failure paths for path validation, read failures, UTF-8 decode, YAML parse, multi-document streams, empty roots, non-mapping roots, non-plain data, and unsupported directives.
- Kept scope limited to loader/error foundations; no includes, overlays, override application, schema validation, resolver execution, run-store writes, CLI behavior, or public compose orchestration changes were added.

New tests implemented:

- Unit coverage for structured context serialization, direct construction validation, strict loader failures, and `_copy_` paths at root, nested mappings, and list-contained mappings.
- Contract coverage for plain-data structured error payloads and round-trip reconstruction.
- Narrow compose coverage confirming `_copy_` now fails through existing loading while `_include_` and `_replace_` remain ordinary data in this phase.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and `uv build` passed. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Wrote `build/test-summary.md`; overall suite status `passed`. |
| GitHub checks | Pending | To run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 | 3.96s |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 | 3.97s |
| contract | passed | 24 | 0 | 0 | 1 | 0 | 25 | 1.66s |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 2.03s |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 | 3.93s |
| config-extra | passed | 125 | 0 | 0 | 0 | 428 | 125 | 8.12s |
| Overall | passed | 553 | 0 | 0 | 8 | 428 | 561 | 23.67s |

## Risks / Follow-Ups

- Structured context codes and fields are intentionally additive foundations for later include, override, resolver, validation, and artifact phases.
- `_copy_` is deliberately unsupported for v1; copy semantics remain out of scope.
- Error context avoids raw source bytes and runtime/resolver values; the full redaction policy is deferred to later artifact/provenance phases.
