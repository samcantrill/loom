## Summary

@samcantrill

Moves config-owned tests and examples beside the standalone `weave` package,
while leaving Loom adapter/runtime tests in the root suite. The repository test
summary now reports package-local `weave` and `weave-examples` evidence
separately for PR review and final docs hardening.

This phase keeps broad feature-doc and README hardening out of scope; Phase 6
owns final documentation cleanup against the new package-local evidence.

## Acceptance Criteria

- [x] Config-owned unit, contract, and pure composition integration tests live
      under `packages/weave/tests`.
- [x] Root suites retain Loom CLI/runtime adapter tests and import-boundary
      checks.
- [x] Config authoring examples live under `packages/weave/examples`.
- [x] `make test-weave-examples` validates package-local examples and example
      manifests.
- [x] `make validate-weave` includes package lint, typecheck, tests, examples,
      and build.
- [x] `make test-summary` reports `weave` and `weave-examples` suite rows.
- [x] Final validation and suite evidence passed.

## Implementation Notes

- Moved root config implementation tests into package-local unit, contract, and
  integration tiers, with a package-local support fixture copy.
- Added package pytest configuration so `packages/weave` tests collect from the
  package root without depending on Loom's root test package.
- Moved authoring examples into `packages/weave/examples`, updated imports,
  paths, manifest validation pointers, and added a root authoring handoff README.
- Added `test-weave-examples`, expanded `validate-weave`, and taught the test
  harness to run package-local `weave` suites from `packages/weave`.
- Added harness regressions for package-local Weave grouping and file-based
  suite discovery.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make test-weave` | Passed | 375 package-local tests passed |
| `make test-weave-examples` | Passed | 8 package-local example and manifest checks passed |
| `make validate-weave` | Passed | Ruff, Pyright, 375 package tests, 8 example checks, and package build passed |
| Root config adapter focus | Passed | `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/config -m optional_dependency`: 26 passed outside the sandbox |
| `rg "loom\\.config" src tests packages examples pyproject.toml` | Passed | Only intentional absence assertions remain |
| Package-local Loom import sweep | Passed | Only the no-Loom-import assertion and preserved `loom.recipes` entry-point group string remain |
| `make validate-pr` | Passed | Ruff, Pyright, default suite, config-extra suite, and root build passed outside the sandbox |
| `make test-summary` | Passed | `build/test-summary.md` generated with overall status `passed` |
| GitHub checks | Pending | Will be verified by the merge gate after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 112 | 0 | 0 | 0 | 4 | 112 | 16.74s | 19% |
| unit | passed | 1402 | 0 | 0 | 0 | 2 | 1402 | 69.30s | 82% |
| contract | passed | 252 | 0 | 0 | 0 | 8 | 252 | 13.97s | 59% |
| integration | passed | 170 | 0 | 0 | 0 | 82 | 170 | 61.46s | 66% |
| e2e | passed | 46 | 0 | 0 | 0 | 6 | 46 | 41.57s | 59% |
| config-extra | passed | 128 | 0 | 0 | 3 | 1985 | 131 | 112.29s | 58% |
| weave | passed | 375 | 0 | 0 | 0 | 0 | 375 | 4.28s | 88% |
| weave-examples | passed | 8 | 0 | 0 | 0 | 0 | 8 | 2.68s | N/A |
| Overall | passed | 2493 | 0 | 0 | 3 | 2087 | 2496 | 322.30s | - |

## Assumptions

- Root Loom adapter tests remain root-owned when they exercise CLI, pipeline,
  store, authority, or runtime behavior through `weave`.
- The Stage 23 recipe entry-point group remains `loom.recipes`; loader ownership
  is already in `weave`.
- Some validation commands need local process/socket permissions outside the
  sandbox because they exercise the local authority service.

## Risks / Follow-Ups

- Phase 6 still needs to update user-facing docs and historical example
  coverage docs to describe `weave` as the config authoring package.
