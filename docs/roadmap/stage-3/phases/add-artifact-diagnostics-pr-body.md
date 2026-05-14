## Summary

Completes the v3 local diagnostics surface with metadata-only artifact
inspection. `loom artifacts list RUN_URI` now summarizes recorded artifact
references, and `loom artifacts show RUN_URI ARTIFACT_ID` shows one artifact's
metadata plus generic stage provenance when available.

The implementation reads through public run-store APIs and keeps artifact
payload loading, checksum verification, catalog behavior, and private
run-layout traversal out of scope.

## Acceptance Criteria

- [x] Users can list recorded artifacts without loading payloads.
- [x] Users can inspect one artifact's metadata and generic provenance without
  loading payloads.
- [x] Missing artifact IDs fail clearly.
- [x] Successful and failed local runs can be diagnosed end to end through CLI
  text/JSON flows.
- [x] JSON output uses stable v3 envelopes and plain diagnostics payloads.
- [x] Diagnostics and CLI use public store APIs rather than private local layout
  traversal.

## Implementation Notes

- Added artifact diagnostics summaries over `read_artifact_index()`,
  `parse_artifact_key()`, and `read_stage_provenance()`.
- Added `loom artifacts list` and `loom artifacts show` with text and JSON
  output, command-owned schema versions, clear missing/ambiguous artifact
  errors, and compact text formatting.
- `show` resolves the public `ARTIFACT_ID` argument against
  `ArtifactRef.artifact_id`, while list output exposes both the logical
  run-store key and artifact ID.
- Artifact inspection remains metadata/provenance-only: it does not invoke
  codecs, read payload bytes, verify checksums, or inspect artifact-store paths.

New tests implemented:

- Diagnostics unit tests for sorted summaries, metadata/provenance payloads,
  missing IDs, and duplicate artifact IDs.
- CLI unit tests for artifacts list/show JSON and text behavior plus nested
  command usage errors.
- Contract coverage proving diagnostics consume public run-store artifact and
  stage-provenance readers.
- Integration and e2e coverage for successful and failed local diagnostics
  workflows using preflight, run, status, logs, and artifacts commands.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff clean; Pyright 0 errors; default isolated suite 550 passed/13 skipped/12 deselected; config-extra 396 passed/565 deselected; build succeeded. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Wrote `build/test-summary.md`; all suites passed. |
| GitHub checks | Passed | PR #69 CI `checks` workflow passed. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 48 | 0 | 0 | 1 | 0 | 4.96s |
| unit | passed | 452 | 0 | 0 | 1 | 0 | 5.11s |
| contract | passed | 41 | 0 | 0 | 2 | 0 | 2.15s |
| integration | passed | 9 | 0 | 0 | 6 | 12 | 1.90s |
| e2e | passed | 15 | 0 | 0 | 0 | 0 | 5.92s |
| config-extra | passed | 396 | 0 | 0 | 0 | 565 | 15.67s |

## Risks / Follow-Ups

- Artifact commands intentionally do not verify artifact existence, checksums,
  or payload readability.
- If future workflows produce duplicate `ArtifactRef.artifact_id` values, a
  separate key-based selector may be worth adding.
