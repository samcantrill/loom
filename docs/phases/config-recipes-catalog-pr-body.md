## Summary

@samcantrill

This PR implements Phase 9 recipe catalog and expansion behavior for v1 configuration composition. Recipe expansion now runs after file/user composition includes and before ordinary value overrides, so ordinary overrides target concrete recipe-expanded paths rather than pre-expansion recipe arguments.

Recipe arguments preserve authored resolver-style expressions for artifact-safe recipe records and hashes, while expanded recipe output shape fails closed if it depends on resolver-shaped mapping keys. Explicit `RecipeCatalog` composition remains the deterministic path, with existing compatibility APIs left intact.

## Acceptance Criteria

- [x] Recipes expand before ordinary value overrides.
- [x] Ordinary overrides target expanded concrete paths.
- [x] Recipe records preserve unresolved resolver expressions as authored text.
- [x] Recipes that require resolver outputs for output shape fail.

## Implementation Notes

- Reordered `compose_config` so includes and user composition overrides run first, recipe argument interpolation and recipe expansion run next, then ordinary overrides apply to the expanded config before resolver scanning/runtime interpolation.
- Changed recipe argument interpolation to preserve whole-string and embedded resolver-style tokens such as `${oc.env:KEY}` instead of treating them as ordinary config lookups during recipe artifact handling.
- Added recipe output shape validation that rejects resolver-shaped mapping keys before manifest generation, preventing misleading artifact-safe recipe records.
- Kept recipe work inside `loom.config`; no CLI, pipeline, run-store, public inspection API, source artifact, or fingerprint population behavior is added in this phase.

New tests implemented:

- Integration coverage for recipe-before-ordinary-override ordering and rejection of ordinary overrides aimed at pre-expansion recipe arguments.
- Unit and integration coverage proving resolver-style recipe arguments are preserved in recipe manifest records and may still resolve at runtime in final config values.
- Unit, contract, and integration coverage for resolver-shaped recipe output key failure.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff, Pyright, default tests, config-extra tests, and build passed after implementation refinement. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | `build/test-summary.md` generated 2026-05-05T12:19:16+00:00; overall 677 passed, 0 failed, 0 errors, 8 skipped, 431 deselected. |
| Targeted Phase 9 suite | Passed | 97 focused package/unit/contract/integration tests passed after refinement. |
| GitHub checks | Pending | PR will be opened against `develop`; GitHub checks are expected to run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 36 | 0 | 0 | 1 | 0 |
| unit | passed | 354 | 0 | 0 | 1 | 0 |
| contract | passed | 27 | 0 | 0 | 1 | 0 |
| integration | passed | 9 | 0 | 0 | 5 | 0 |
| e2e | passed | 5 | 0 | 0 | 0 | 0 |
| config-extra | passed | 246 | 0 | 0 | 0 | 431 |
| Overall | passed | 677 | 0 | 0 | 8 | 431 |

## Risks / Follow-Ups

- Resolver-dependent recipe shape detection is intentionally conservative because recipes are trusted Python and opaque to static analysis.
- Full composition manifests, public inspection APIs, source artifacts, and artifact-safe fingerprint population remain deferred to later v1 phases.
