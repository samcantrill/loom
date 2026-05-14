## Summary

This PR establishes the Phase 1 deterministic sweep foundation. It adds the
import-light `loom.pipeline.sweep` contract package with public provider,
proposal, dispatch, feedback, extraction, trial, and manifest records that
later phases can implement against.

The implementation is contract-only: it does not add grid/manual expansion,
trial execution, queue dispatch, coordination writes, status aggregation,
collection, CLI commands, plugin discovery, or optimizer integrations.

## Acceptance Criteria

- [x] Public sweep contracts are exported from `loom.pipeline.sweep` without
      optional optimizer, queue, CLI, or project-code imports.
- [x] Provider/proposal contracts support fake finite and unsized providers
      without requiring `len()` on every provider.
- [x] Dispatch, feedback, extraction, trial, and manifest records round-trip as
      plain data.
- [x] Versioned sweep/trials manifests reject unsupported schemas and report
      malformed payloads through compatibility diagnostics.
- [x] Default extraction behavior is explicit unsupported diagnostics, with no
      artifact payload parsing.

## Implementation Notes

- Added `src/loom/pipeline/sweep/` with value records for provider identity and
  context, trial proposals, canonical trial/run bindings, dispatch requests and
  results, feedback observations, unsupported extraction diagnostics, and
  sweep/trials manifests.
- Kept dispatch records adapter-neutral so direct and queue-backed adapters in
  later phases consume the same intent/result shapes.
- Kept provider-supplied IDs in metadata/fields separate from Loom-owned
  `trial_id`, `trial_index`, and `run_uri` bindings.
- Added manifest compatibility checks that distinguish malformed payloads,
  missing schema versions, unsupported schema versions, and sweep ID mismatch.

New tests implemented:

- Package import-boundary and public export tests for `loom.pipeline.sweep`.
- Unit tests for record validation, plain-data normalization, manifest
  round-trips, feedback, dispatch, and unsupported extraction.
- Contract tests for provider capability, dispatch records, manifest
  compatibility, and extraction diagnostics.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted package tests | Passed | `45 passed` |
| Targeted sweep unit/contract tests | Passed | `16 passed` |
| Targeted Ruff | Passed | `All checks passed` |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build all completed |
| `make test-summary` | Passed | Wrote `build/test-summary.md` |
| GitHub checks | Pending | To be populated by GitHub after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 79 | 0 | 0 | 1 | 0 | 12.90s |
| unit | passed | 1061 | 0 | 0 | 7 | 1 | 51.49s |
| contract | passed | 190 | 0 | 0 | 2 | 0 | 12.08s |
| integration | passed | 149 | 0 | 0 | 8 | 13 | 52.08s |
| e2e | passed | 42 | 0 | 0 | 0 | 2 | 36.97s |
| config-extra | passed | 438 | 0 | 0 | 0 | 1530 | 79.02s |

## Risks / Follow-Ups

- Grid/manual expansion, generated-trial guards, stable ID generation policy,
  and run URI mapping are intentionally deferred to Phase 2.
- Early-stop lifecycle mapping and direct dispatch are deferred to Phase 3.
- Queue dispatch, coordination projection, and status aggregation are deferred
  to Phase 4.
- Collection and CLI behavior are deferred to Phase 5.
