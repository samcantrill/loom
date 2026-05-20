## Summary

@samcantrill

Hard-switches Loom's config-facing adapter paths to the standalone `weave` package and removes the old `src/loom/config` implementation with no compatibility shim. Loom now consumes trusted authored config through explicit adapter edges while runtime internals remain independent of `weave`.

This phase keeps broad test/example relocation and docs hardening out of scope; those remain Phase 5 and Phase 6 work.

## Acceptance Criteria

- [x] Loom CLI config workflows, queue config loading, diagnostics preflight, and recipe-loading plugin diagnostics call `weave`.
- [x] `src/loom/config` is deleted and `import loom.config` fails by default.
- [x] Core runtime imports remain free of `weave`; `weave` imports no `loom`.
- [x] Metadata-only plugin listing remains import-light, while recipe loading delegates to `weave.recipes.load`.
- [x] Root package metadata and lock data resolve the local `packages/weave` project.
- [x] Final validation and suite evidence passed.

## Implementation Notes

- Rewired CLI validate/plan/run/sweep, diagnostics preflight, and queue config adapters to lazy `weave` imports.
- Added Loom-owned sweep override path validation so runtime sweep specs no longer import config helpers or `weave`.
- Updated plugin diagnostics so recipe loading uses `weave.recipes.load` and metadata-only listing does not import recipe targets.
- Added root dependency metadata for the local `weave` package and refreshed `uv.lock`.
- Updated focused tests and import-boundary assertions for the no-shim hard switch.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-weave` | Passed | Ruff, Pyright, 27 package tests, and `weave-0.1.0` source/wheel build passed |
| Installed wheel smoke | Passed | Built `weave` and `loom` wheels import, `loom.config` is absent, and `loom validate` succeeds on a minimal config |
| `rg "loom\\.config" src tests packages pyproject.toml` | Passed | Only intentional absence assertions remain |
| `make test-package` | Passed | 112 passed, 4 deselected |
| `make test-contract` | Passed | 274 passed, 11 deselected |
| `make test-integration` | Passed | 170 passed, 89 deselected |
| `make test-e2e` | Passed | 46 passed, 6 deselected |
| `make test-config-extra` | Passed | 461 passed, 3 skipped, 2005 deselected |
| `make validate-pr` | Passed | Ruff, Pyright, default suite, config-extra suite, and root build passed |
| `make test-summary` | Passed | `build/test-summary.md` generated with overall status `passed` |
| GitHub checks | Pending | Will be verified by the merge gate after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 112 | 0 | 0 | 0 | 4 | 112 | 16.86s | 19% |
| unit | passed | 1400 | 0 | 0 | 0 | 2 | 1400 | 69.14s | 82% |
| contract | passed | 274 | 0 | 0 | 0 | 11 | 274 | 13.55s | 59% |
| integration | passed | 170 | 0 | 0 | 0 | 89 | 170 | 61.41s | 66% |
| e2e | passed | 46 | 0 | 0 | 0 | 6 | 46 | 41.52s | 59% |
| config-extra | passed | 461 | 0 | 0 | 3 | 2005 | 464 | 117.23s | 58% |
| Overall | passed | 2463 | 0 | 0 | 3 | 2117 | 2466 | 319.71s | - |

## Assumptions

- The Stage 23 recipe entry-point group remains `loom.recipes`; only the loader ownership moved to `weave`.
- Root config-owned tests may remain under root paths until Phase 5 relocates and de-duplicates them.
- Some suite commands need local process/socket permissions outside the sandbox because they exercise the local authority service.

## Risks / Follow-Ups

- Phase 5 still needs to relocate package-owned tests and examples into the `weave` package.
- Phase 6 still needs to harden user-facing docs around the final import path and package boundary.
