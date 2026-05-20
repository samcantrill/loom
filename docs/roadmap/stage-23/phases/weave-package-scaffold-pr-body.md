## Summary

Adds the initial standalone `weave` package scaffold for Stage 23 Phase 2. The package now has local metadata with config runtime dependencies, a `src/weave` import package, `py.typed`, version metadata, package-local README, and config-owned helper foundations for plain data, stable JSON, digests, and structured config errors.

This keeps Loom runtime behavior unchanged: `src/loom/config` is not ported or removed, Loom adapters are not rewired to `weave`, and boundary tests assert that `weave` does not import `loom` while core Loom imports still avoid `weave`.

## Acceptance Criteria

- [x] `weave` is independently importable from `packages/weave`.
- [x] Package-local helper APIs exist for plain data, stable JSON, digest formatting/hashing, and structured config errors.
- [x] Package-local tests cover the new helper contracts and import surface.
- [x] Repository tooling includes `make test-weave`, `make build-weave`, and `make validate-weave`.
- [x] Root import-boundary coverage includes the new `weave` package boundary.

## Implementation Notes

- Added `packages/weave/pyproject.toml` using the local package layout, normal config runtime dependencies, and lightweight build tooling already used in the repository.
- Added `weave.plain`, `weave.json`, `weave.digests`, and `weave.errors` as package-owned foundations for later config implementation porting.
- Kept helper behavior intentionally package-local rather than shared with Loom runtime modules, preserving the Stage 23 ownership split.
- Added isolated import-boundary assertions so package checks do not rely on prior in-process imports hiding eager dependencies.

New tests implemented:

- Package-local tests for `weave` import behavior, package metadata including runtime dependencies, plain-data validation and normalization, stable JSON output, digest helpers, and structured error context.
- Root package boundary tests proving `weave` imports no `loom` and selected Loom imports do not import `weave`.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default Pytest, config-extra Pytest, and root build passed; recorded in the phase plan. |
| `make test-summary` | Passed | `build/test-summary.md` generated with overall status `passed`; 2456 passed, 22 skipped, 2029 deselected, 0 failed/errors. |
| `make test-weave` | Passed | 23 package-local tests passed. |
| `make build-weave` | Passed | Built `weave-0.1.0` source and wheel artifacts. |
| `make validate-weave` | Passed | Package-local Ruff, Pyright, 23 tests, and package build passed. |
| `uv run pytest tests/package/test_import_boundaries.py` | Passed | 60 boundary tests passed during implementation; final summary reports 67 import-boundary tests passed in the package suite. |
| GitHub checks | Pending | To run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 111 | 0 | 0 | 1 | 0 | 112 |
| unit | passed | 1394 | 0 | 0 | 7 | 1 | 1401 |
| contract | passed | 274 | 0 | 0 | 3 | 0 | 277 |
| integration | passed | 170 | 0 | 0 | 8 | 18 | 178 |
| e2e | passed | 46 | 0 | 0 | 0 | 6 | 46 |
| config-extra | passed | 461 | 0 | 0 | 3 | 2004 | 464 |
| Overall | passed | 2456 | 0 | 0 | 22 | 2029 | 2478 |

## Assumptions

- Phase 2 helper duplication is intentional and accepted by the Stage 23 plan so `weave` can own config-package helper behavior without depending on Loom runtime helpers.
- The package-local scaffold is sufficient for local build and validation; publication and separate repository extraction remain future work.
- Loom continues to own current config implementation and adapter paths until later Stage 23 phases.

## Risks / Follow-Ups

- Helper behavior can drift from Loom-owned equivalents if future phases do not keep golden artifact compatibility checks authoritative.
- The package metadata is local-workspace oriented and not publication-proven.
- Later phases still need to port config implementation into `weave`, hard-switch Loom adapters, remove `src/loom/config`, and move config-owned tests/examples.
