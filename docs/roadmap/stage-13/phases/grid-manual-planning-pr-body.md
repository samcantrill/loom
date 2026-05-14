## Summary

Implements Phase 2 of deterministic sweeps: plan-only grid and manual sweep
expansion over the Phase 1 provider and manifest contracts. The new planning
surface normalizes trusted specs, expands deterministic finite providers, emits
stable Loom-owned trial IDs, maps trial run URIs, writes generated manifests,
and reports incompatible existing plans without executing or enqueuing runs.

## Acceptance Criteria

- [x] Grid specs produce deterministic cartesian trial order, IDs, overrides,
  provider records, run URI mappings, and manifests.
- [x] Manual specs preserve authored order, names, provider/external IDs,
  metadata, and override facts without importing optimizer packages.
- [x] Plans above the default `100` generated-trial guard fail unless the spec
  explicitly opts into a higher limit.
- [x] Existing generated manifests can be read back when compatible and return
  structured diagnostics when incompatible.

## Implementation Notes

- Added `GridSweepSpec`, `ManualSweepSpec`, `ManualTrialSpec`, and first-party
  `GridSweepProposalProvider` / `ManualSweepProposalProvider` implementations.
- Added plan-only helpers for provider selection, in-memory planning,
  JSON-spec planning, manifest/spec writes, compatible readback, trial ID
  generation, run URI mapping, and override-expression rendering.
- Kept sweep planning below execution, queue, CLI, coordination, plugin, and
  optimizer layers. Planning validates override facts through the existing
  config override parser and does not apply or merge configs.

New tests cover spec normalization, deterministic expansion, manual external
trial lists, guard behavior, provider contracts, manifest compatibility,
package exports/import boundaries, and narrow plan-file integration.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted Phase 2 tests | Passed | 70 passed across sweep unit, provider/manifest/planning contracts, package boundaries, and plan-file integration |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `make test-summary` | Passed | Wrote `build/test-summary.md` |
| GitHub checks | Pending | Available after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 79 | 0 | 0 | 1 | 0 |
| unit | passed | 1068 | 0 | 0 | 7 | 1 |
| contract | passed | 194 | 0 | 0 | 2 | 0 |
| integration | passed | 151 | 0 | 0 | 8 | 13 |
| e2e | passed | 42 | 0 | 0 | 0 | 2 |
| config-extra | passed | 438 | 0 | 0 | 0 | 1543 |

## Risks / Follow-Ups

- Phase 3 owns direct dispatch, run request construction, early-stop lifecycle
  handling, and compatible execution resume.
- Phase 4 owns coordination, queue dispatch, and status aggregation.
- Phase 5 owns the public `loom sweep` CLI, collection, docs, and final
  hardening.
