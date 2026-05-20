## Summary

@samcantrill

Ports the trusted config implementation into the standalone `weave` package while preserving the existing Loom config path as the temporary Phase 3 baseline. Direct config users can now exercise composition, inspection, recipes, artifact records, fingerprints, instantiation, target checks, raw source snapshots, provenance, redaction, and structured config errors through `weave`.

This phase keeps the hard switch out of scope: there is no Loom adapter rewiring and no `src/loom/config` removal in this phase.

## Acceptance Criteria

- [x] `weave` exposes real config-owned public APIs without importing Loom.
- [x] Package-local tests prove config behavior, recipe loading, instantiation, target checks, golden artifact parity, and import boundaries.
- [x] Root Loom behavior remains on the existing config implementation until Phase 4.
- [x] Final validation and suite evidence passed.

## Implementation Notes

- Added package-local config modules under `packages/weave/src/weave` for API records, composition, loading, merging, overrides, includes, interpolation, redaction, provenance, source maps, artifacts, artifact-safe fingerprints, recipes, recipe entry-point loading, target instantiation, target checks, and validation helpers.
- Replaced Loom-owned helper usage with package-owned `weave` helpers for plain data, stable JSON, digests, version metadata, and config errors.
- Kept the Stage 23 `loom.recipes` entry-point group while moving recipe loading ownership into `weave`, avoiding imports from `loom.plugins`.
- Added narrow Make/test target wiring needed to validate the package-local port.

New tests implemented:

- `packages/weave/tests/test_config_port.py` covers Phase 1 golden artifact parity, recipe entry-point loading through `weave`, target instantiation/check behavior, structured errors, and no-Loom import boundaries.
- `tests/package/test_import_boundaries.py` now asserts public `weave` config symbol resolution does not import Loom and core runtime imports still do not depend on `weave` before Phase 4.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make test-weave` | Passed | 27 passed |
| `make validate-weave` | Passed | Ruff, Pyright, 27 package tests, and `weave-0.1.0` source/wheel build passed |
| `PYTHONPATH=packages/weave/src uv run --extra config pytest packages/weave/tests` | Passed | 27 passed |
| `uv run pytest tests/package/test_import_boundaries.py` | Passed | 61 passed |
| `uv run --extra config pytest tests/contracts/test_config_extraction_golden_artifacts_contract.py` | Passed | 1 passed |
| `uv run --extra config pytest tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_error_contract.py tests/contracts/test_config_composition_inspection_contract.py tests/contracts/test_recipe_contract.py` | Passed | 32 passed |
| `make validate-pr` | Passed | Ruff, Pyright, default suite, config-extra suite, and root build passed |
| `make test-summary` | Passed | `build/test-summary.md` generated with overall status `passed` |
| GitHub checks | Not run | PR creation was intentionally skipped for this preparation pass |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 112 | 0 | 0 | 1 | 0 | 113 | 16.40s | 18% |
| unit | passed | 1394 | 0 | 0 | 7 | 1 | 1401 | 69.52s | 77% |
| contract | passed | 274 | 0 | 0 | 3 | 0 | 277 | 13.18s | 56% |
| integration | passed | 170 | 0 | 0 | 8 | 18 | 178 | 62.01s | 62% |
| e2e | passed | 46 | 0 | 0 | 0 | 6 | 46 | 42.01s | 59% |
| config-extra | passed | 461 | 0 | 0 | 3 | 2005 | 464 | 119.26s | 60% |
| Overall | passed | 2457 | 0 | 0 | 22 | 2030 | 2479 | 322.38s | - |

## Assumptions

- Temporary duplicate implementation between `src/loom/config` and `packages/weave/src/weave` is accepted until Phase 4 performs the hard switch.
- Package-local tests may overlap root config tests during the transition; Phase 5 owns final relocation and de-duplication.
- Recipe entry-point compatibility keeps the `loom.recipes` group name for Stage 23.

## Risks / Follow-Ups

- The duplicate config implementation can drift if Phase 4 is delayed.
- Package-local and root config coverage intentionally overlap until Phase 5 relocates and de-duplicates ownership.
- GitHub checks still need to run after the managing agent opens the PR.
