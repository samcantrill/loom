## Summary

- Adds `RunArtifactStore` and `StageArtifactStore` as artifact/materialization
  only protocols.
- Adds `LocalRunArtifactStore` and `LocalStageArtifactStore` wrappers over the
  existing local layout without exposing lifecycle methods.
- Keeps payload `ArtifactStore` behavior unchanged and documents that
  materialization stores are non-authoritative.
- Adds package, unit, contract, and integration coverage for the new boundary.

## Tests

| Command | Result |
| --- | --- |
| `make validate-pr` | Passed Ruff, Pyright, default tests, config-extra tests, and build. |
| `make test-summary` | Passed; wrote `build/test-summary.md`. |

Suite evidence from `make test-summary`:

| Suite | Result |
| --- | --- |
| package | 57 passed, 1 skipped |
| unit | 836 passed, 1 skipped |
| contract | 108 passed, 2 skipped |
| integration | 90 passed, 8 skipped, 10 deselected |
| e2e | 39 passed, 1 deselected |
| config-extra | 420 passed, 1133 deselected |

## Assumptions And Risks

- Runtime callers still use `LegacyRunStore`; migration is deferred to Phases
  4-6.
- The local wrappers delegate to `LocalRunStore` internally to avoid duplicating
  layout code, but the public wrapper protocols do not expose lifecycle state.
- Remote artifact materialization is intentionally not introduced in this
  phase.
