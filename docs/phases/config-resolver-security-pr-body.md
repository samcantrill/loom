## Summary

@samcantrill

This PR implements Phase 8 resolver security for configuration composition. It adds private no-execution resolver scanning so `loom.config` can preserve authored resolver expressions for future artifact-safe paths, while final runtime interpolation allows only the Phase 8 resolver allow-list: `oc.env`.

Unsupported resolver-style interpolation, including custom resolvers and other available OmegaConf built-ins, now fails before execution with structured `ConfigUnsupportedResolverError` context. Include targets and Phase 7 user-composition include overrides that contain interpolation keep the existing `ConfigIncludeResolutionError` / `resolver_dependent` contract.

## Acceptance Criteria

- [x] Private artifact-safe resolver scanning preserves authored config strings and resolver metadata without executing resolver code.
- [x] Runtime interpolation executes only allow-listed `oc.env` resolver expressions.
- [x] Custom resolver expressions and non-allow-listed OmegaConf built-ins fail before execution with `ConfigUnsupportedResolverError`.
- [x] Resolver-dependent include targets and user-composition include overrides fail closed with `ConfigIncludeResolutionError` code `resolver_dependent`.
- [x] Phase boundaries remain intact: no public root exports, public `ComposedConfig` fields, manifest/source-artifact/fingerprint/provenance population, CLI behavior, pipeline imports, run-store writes, resolver plugins, remote resolvers, recipe behavior changes, or `_copy_`.

## Implementation Notes

`src/loom/config/interpolation.py` now separates resolver scanning from runtime resolution. `scan_resolver_expressions` converts config data to plain data, walks strings without calling OmegaConf resolution, records resolver expression metadata, and preserves authored token text. `resolve_interpolation` rejects unsupported resolver names before calling `OmegaConf.to_container(..., resolve=True)`, so only `oc.env` can execute in the final runtime interpolation stage.

`src/loom/config/errors.py` adds `ConfigUnsupportedResolverError` as both a structured config-domain error and `NotImplementedError`. `src/loom/config/compose.py` wires the private scan before final interpolation while keeping include expansion, user-composition include overrides, ordinary overrides, recipe argument interpolation, recipe expansion, validation, redaction, provenance, and current fingerprint behavior in the existing order.

New tests implemented:

- Unit coverage for scanner metadata, no-execution sentinel behavior, `oc.env` runtime resolution, unsupported resolver failures, structured error shape, and non-allow-listed OmegaConf built-ins.
- Contract coverage for `ConfigUnsupportedResolverError` structured serialization and inheritance.
- Integration coverage for public compose behavior with `oc.env`, custom/non-allow-listed resolver rejection, resolver-expression include targets, and resolver-expression user-composition include overrides.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default suite passed 426 with 9 skipped; config-extra passed 236 with 431 deselected; build succeeded. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | Wrote `build/test-summary.md`; overall 667 passed, 0 failed, 8 skipped, 431 deselected. |
| Targeted resolver/error suite | Passed | `tests/unit/loom/config/test_interpolation.py`, `tests/unit/loom/config/test_config_errors.py`, and `tests/contracts/test_config_error_contract.py`: 24 passed. |
| Targeted include/recipe/compose/import suite | Passed | Include, recipe expansion, resolver compose, override compose, and import-boundary targets: 83 passed. |
| GitHub checks | Pending | Available after PR creation; review the opened PR checks for remote CI status. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 | 6.19s | 23% |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 | 6.47s | 60% |
| contract | passed | 27 | 0 | 0 | 1 | 0 | 28 | 2.36s | 29% |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 2.65s | 44% |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 | 4.54s | 63% |
| config-extra | passed | 236 | 0 | 0 | 0 | 431 | 236 | 10.57s | 76% |
| Overall | passed | 667 | 0 | 0 | 8 | 431 | 675 | 32.77s | - |

## Risks / Follow-Ups

- Resolver metadata remains private until later inspection, manifest, redaction, and fingerprint phases expose artifact-safe records additively.
- The runtime resolver allow-list is intentionally only `oc.env`; other OmegaConf built-ins need explicit future review before becoming part of the contract.
- Runtime resolver outputs are not persisted by default, so exact runtime values are not replayable from Phase 8 artifacts.
- Recipe resolver-dependent shape behavior, public unresolved config output, source artifacts, artifact-safe fingerprints, CLI behavior, and resolver plugin APIs remain deferred to later phases.
