## Summary

@samcantrill

This PR implements Stage 12 Phase 2 by adding the first concrete local run bundle exporter and read-only inspector over the Phase 1 portable exchange contracts.

The default export path remains metadata-only. Payload bytes are included only when explicitly selected, and bundle inspection validates archive members and checksums without extracting files.

## Acceptance Criteria

- [x] Completed-run metadata can be converted into portable export records and local bundle manifests.
- [x] Metadata-only export writes only the manifest by default.
- [x] Explicit payload selection writes selected local file refs as regular archive members with size and checksum facts.
- [x] Inspection reads manifest and payload counts without extraction.
- [x] Unsafe archive members, duplicate members, missing payloads, and checksum mismatches produce structured diagnostics.
- [x] Import, offline evidence alignment, queue behavior, transfer handlers, and CLI commands remain out of scope.

## Implementation Notes

The new local bundle implementation lives in `src/loom/runs/bundles.py` and is exported through `loom.runs`.

Key behavior:

- `build_portable_run_export_record` builds metadata-backed export records from `CompletedRunBundleMetadata`.
- `LocalRunBundleExporter` conforms to the Phase 1 `RunExporter` protocol.
- `export_run_bundle` lazily reads completed-run metadata from authority stores and writes local tar bundles.
- `inspect_run_bundle` validates archive member names, duplicate/link members, manifest shape, and optional checksum evidence without extracting.
- `normalize_bundle_member_path` centralizes traversal-safe POSIX archive paths for Phase 3 reuse.
- Payload writes use explicit regular-file tar members so source symlinks do not become link members in exported bundles.

New tests cover package exports/import boundaries, metadata-only defaults, explicit payload selection, missing payload diagnostics, exporter protocol conformance, unsafe archive fixtures, and SQLite-backed completed-run export/inspect.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted pytest | Passed | 51 passed across package, import-boundary, unit, contract, and integration Phase 2 tests. |
| Targeted Ruff | Passed | `uv run --isolated --locked --group dev ruff check ...` |
| Targeted Pyright | Passed | `uv run --isolated --locked --group dev --extra config pyright ...` |
| `make validate-pr` | Passed | Ruff, Pyright, default suite, config-extra suite, and build passed outside the sandbox. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; all suites passed. |
| GitHub checks | Pending | To be populated after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 77 | 0 | 0 | 1 | 0 | 78 | 14.14s |
| unit | passed | 1041 | 0 | 0 | 7 | 1 | 1048 | 52.00s |
| contract | passed | 174 | 0 | 0 | 2 | 0 | 176 | 11.03s |
| integration | passed | 147 | 0 | 0 | 8 | 13 | 155 | 52.23s |
| e2e | passed | 41 | 0 | 0 | 0 | 2 | 41 | 36.67s |
| config-extra | passed | 438 | 0 | 0 | 0 | 1489 | 438 | 81.25s |
| Overall | passed | 1918 | 0 | 0 | 18 | 1505 | 1936 | 247.32s |

## Risks / Follow-Ups

- Phase 3 should reuse the archive safety helpers and manifest reader instead of reimplementing path validation.
- Import, offline-evidence alignment, CLI exposure, remote materialization, signing, encryption, dedupe, and transfer handlers remain deferred to later phases or stages.
