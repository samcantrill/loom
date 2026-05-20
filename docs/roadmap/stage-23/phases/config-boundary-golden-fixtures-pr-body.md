## Summary

This PR pins the current `loom.config` artifact contract before Stage 23 starts moving config ownership into `weave`. It adds a small domain-neutral config fixture project, checked-in golden JSON outputs for the required artifact families, and a contract test that regenerates those outputs through public config APIs.

It also extends package import-boundary coverage with current-state assertions for `loom.config`, documenting the pre-extraction boundary while keeping future `weave` enforcement for later phases.

## Acceptance Criteria

- [x] Golden artifacts cover resolved config, redacted config, composition manifest, recipe manifest, source artifact records, raw source snapshots, artifact-safe fingerprint records, and structured config errors.
- [x] Golden outputs are generated through public config APIs and normalize only host-specific fixture paths.
- [x] Import-boundary tests document the Phase 1 current state without creating or requiring `weave`.
- [x] Final validation evidence is recorded for `make validate-pr`, `make test-summary`, targeted contract checks, and package boundary checks.

## Implementation Notes

- Added `tests/fixtures/config/golden_project/` with compact YAML fixtures for overlays, includes, recipe expansion, redaction, provenance, fingerprints, raw source snapshots, and a deterministic include-resolution error.
- Added `tests/golden/config/extraction-v23/` expected JSON files, using `<golden_project>` placeholders for portable path-bearing public artifact fields while preserving digests and schema data.
- Added `tests/contracts/test_config_extraction_golden_artifacts_contract.py`, which uses `inspect_config_composition`, `RecipeCatalog`, public `to_dict()` methods, and `ConfigErrorContext.from_dict()` round-tripping.
- Extended `tests/package/test_import_boundaries.py` so `import loom.config` remains the explicit Phase 1 baseline and does not pull in pipeline execution, executor, store, CLI, or future `weave` modules.

New tests implemented:

- Golden config extraction artifact contract for the eight Stage 23 Phase 1 artifact families.
- Current-state package import-boundary assertions for the pre-extraction `loom.config` boundary.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Passed outside the sandbox after dependency/network setup and sandbox no-output handling. |
| `make test-summary` | Passed | Passed outside the sandbox and wrote `build/test-summary.md`. |
| Targeted golden contract | Passed | `UV_CACHE_DIR=/tmp/uv-cache uv run --active pytest tests/contracts/test_config_extraction_golden_artifacts_contract.py` |
| Targeted package boundary | Passed | `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py` |
| Contract suite | Passed | `UV_CACHE_DIR=/tmp/uv-cache uv run make test-contract` |
| GitHub checks | Not run | PR opening is intentionally deferred for this preparation pass. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 109 | 0 | 0 | 1 | 0 | 110 | 15.98s |
| unit | passed | 1394 | 0 | 0 | 7 | 1 | 1401 | 69.50s |
| contract | passed | 274 | 0 | 0 | 3 | 0 | 277 | 13.36s |
| integration | passed | 170 | 0 | 0 | 8 | 18 | 178 | 62.54s |
| e2e | passed | 46 | 0 | 0 | 0 | 6 | 46 | 41.97s |
| config-extra | passed | 461 | 0 | 0 | 3 | 2002 | 464 | 119.70s |
| Overall | passed | 2454 | 0 | 0 | 22 | 2027 | 2476 | 323.05s |

## Risks / Follow-Ups

- Later Stage 23 phases must preserve these golden artifact shapes or explicitly record any accepted break with rationale and migration notes.
- The root-owned config fixtures are temporary; Phase 5 should move or mirror them under package-local `weave` tests.
- The import-boundary tests intentionally document Phase 1 current state and should be flipped to final `weave` boundary enforcement during the hard switch phase.
