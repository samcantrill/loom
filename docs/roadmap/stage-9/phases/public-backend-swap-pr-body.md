## Summary

This phase makes new public local and subprocess serial `loom run` executions use
the SQLite-backed authoritative serial store by default, with no user setup.
SLURM dry-run and live-submission preparation continue to use explicit local
materialization stores, so the serial backend swap does not broaden scheduler
policy.

Status, artifact, submitted-operation, and catalog current-summary reads for
authoritative runs now use backend snapshots, authority revisions, or
backend-backed read models. Legacy status, output, artifact-index, and submitted
operation files remain materialized evidence for local workflows, but corrupt,
missing, stale, or contradictory files do not override backend facts for new
authoritative runs.

## Acceptance Criteria

- [x] New public local/subprocess serial runs initialize with the SQLite
  authoritative backend by default.
- [x] Serial status, artifact summaries, submitted-operation details, catalog
  extraction, and freshness evidence read backend truth for authoritative runs.
- [x] Planning/resume consumers that read through the run-store facade receive
  backend status, output, artifact, submitted-operation, and revision facts from
  the authority-backed store.
- [x] Missing, corrupt, stale, or contradictory legacy human-readable files do
  not become fallback truth for new authoritative runs.
- [x] Catalog direct scans preserve compact warnings for missing, corrupt,
  unsupported, partial, or changing authoritative runs without querying private
  SQLite tables.
- [x] Missing or unavailable authority databases on authority-marked runs are
  reported as errors or catalog warnings, not interpreted from legacy local
  status or artifact files.
- [x] Old v0-v8 migration, backend CLI commands, parallel execution,
  workspace/sweep coordination, export/snapshot/repair workflows, and public
  SQLite schema/path contracts remain out of scope.

## Implementation Notes

- Updated `loom run` default store construction so public local/subprocess
  serial runs create an `AuthorityBackedSerialRunStore` backed by the run-local
  SQLite authority; SLURM preparation paths use an explicit `LocalRunStore`.
- Let `create_authority_backed_serial_run_store()` construct the SQLite
  authority by default while still accepting injected authority stores for
  tests and future adapters.
- Added authority revision-backed freshness records to the serial authority
  adapter so catalog refresh can validate against backend revisions instead of
  local sidecar freshness alone.
- Updated diagnostics inspection to prefer `read_authoritative_run()` snapshots
  for run status, stage status, submitted-operation summaries, and artifact
  summaries while preserving local logs, provenance, failures, and inputs as
  materialized refs. Authority-marked runs with missing or unreadable authority
  state now raise diagnostics errors rather than falling back to local live
  files.
- Updated `RunCatalog` direct scan to detect authoritative run candidates,
  extract summaries through backend-neutral read models, and convert missing,
  malformed, or unsupported authority schema failures into catalog warnings.

New tests implemented:

- Unit coverage for public CLI default store selection.
- Unit coverage proving authority-backed status, outputs, artifact indexes, and
  submitted-operation reads ignore deleted, corrupt, or conflicting legacy
  documents.
- Diagnostics coverage proving status and artifact summaries use authoritative
  facts when legacy local files are corrupt.
- Diagnostics and catalog coverage proving missing authority databases do not
  fall back to legacy local truth.
- Catalog scan coverage for malformed and unsupported authority DB schemas.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Reran after blocker-resolution pass 1: Ruff, Pyright, default harness (1038 passed, 18 skipped, 14 deselected), config-extra harness (420 passed, 1066 deselected), and `uv build` passed. |
| `make test-summary` | Passed | Refreshed after blocker-resolution pass 1: overall status `passed`: 1483 passed, 12 skipped, 1077 deselected. |
| GitHub checks | Pending | The manager will poll CI after the blocker-resolution update is pushed. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 56 | 0 | 0 | 1 | 0 | 57 |
| unit | passed | 806 | 0 | 0 | 1 | 0 | 807 |
| contract | passed | 92 | 0 | 0 | 2 | 0 | 94 |
| integration | passed | 72 | 0 | 0 | 8 | 10 | 80 |
| e2e | passed | 37 | 0 | 0 | 0 | 1 | 37 |
| config-extra | passed | 420 | 0 | 0 | 0 | 1066 | 420 |
| Overall | passed | 1483 | 0 | 0 | 12 | 1077 | 1495 |

## Risks / Follow-Ups

- Old v0-v8 local run directories remain intentionally unsupported by new
  live-state readers; future import/export or migration work owns that path.
- Local materialized documents are still needed for inputs, fingerprints, logs,
  provenance, payloads, and worker handoff even though lifecycle and committed
  facts are backend-owned.
- Multi-host, remote authority, backend diagnostics CLI, export/snapshot/repair,
  bounded parallelism, and workspace/sweep coordination remain later-phase work.
