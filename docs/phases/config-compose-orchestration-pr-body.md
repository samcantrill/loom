## Summary

@samcantrill

This PR wires the public v1 composition path over one staged orchestration flow. `compose_config(...)` now returns a compatibility-preserving `ComposedConfig` with additive artifact fields, while `inspect_config_composition(...)` exposes the same run as stable stage records for reviewers and future artifact population work.

The change keeps configuration domain-neutral and persistence-free: it does not write run directories, instantiate `_target_` values during composition, add CLI behavior, or make pipeline code depend on config artifacts.

## Acceptance Criteria

- [x] Full order runs through source loading, overlays, file includes, user composition overrides, recipe argument interpolation, recipe expansion, ordinary overrides, resolver scan, runtime interpolation, validation, redaction, provenance, fingerprinting, artifact placeholders, and final composition.
- [x] `inspect_config_composition(...)` exposes stable additive stage records with plain-data payloads and no private helper objects.
- [x] `ComposedConfig` keeps existing fields and adds `unresolved`, `manifest`, `source_artifacts`, and `fingerprint_records`.
- [x] `_target_` mappings remain inert during composition and inspection; explicit `instantiate(...)` still works after composition.
- [x] `loom.pipeline` remains independent from config artifact imports.

## Implementation Notes

- Added public `ConfigCompositionInspection`, `ConfigCompositionStageRecord`, and `inspect_config_composition(...)` through `loom.config`.
- Refactored `src/loom/config/compose.py` so public compose and inspection share the same staged flow instead of maintaining divergent paths.
- Preserved existing `ComposedConfig` fields and added v1 placeholders: `manifest` carries the current recipe manifest with empty source/fingerprint records, while `source_artifacts` and `fingerprint_records` remain empty for Phase 13/14 population.
- Captured `unresolved` after includes, user composition overrides, recipes, ordinary overrides, and resolver-expression scanning, before runtime resolver execution.
- Kept resolver outputs out of placeholder artifact fields and kept constructed runtime objects out of compose/inspection artifacts.

New tests implemented:

- Package API coverage for the new exports and signatures.
- Unit coverage for staged compose/inspection consistency, additive `ComposedConfig` fields, placeholder manifest schema semantics, and the internal compose helper return type.
- Contract coverage for stable inspection stage names, completed statuses, plain payload shape, and placeholder artifact limits.
- Integration coverage comparing `compose_config(...)` with `inspect_config_composition(...).to_composed_config()`, locking stage order, distinguishing unresolved from resolved values, and proving explicit post-compose `instantiate(...)` behavior.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ran after refinement; includes Ruff, Pyright, default pytest, build, and config-extra coverage. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | Wrote `build/test-summary.md` with overall suite status `passed`. |
| GitHub checks | Not run | PR was not opened in the expanded-path draft pass. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 | 3.65s | 22% |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 | 3.95s | 58% |
| contract | passed | 28 | 0 | 0 | 2 | 0 | 30 | 1.46s | 28% |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 1.78s | 43% |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 | 3.71s | 63% |
| config-extra | passed | 270 | 0 | 0 | 0 | 433 | 270 | 8.08s | 76% |
| Overall | passed | 702 | 0 | 0 | 9 | 433 | 711 | 22.63s | - |

## Risks / Follow-Ups

- Phase 12 intentionally provides placeholder artifact records only; Phase 13 and Phase 14 still own final provenance, source artifact, manifest, redaction, and artifact-safe fingerprint population.
- Stage names and payload shapes become reviewer-visible public inspection contracts, so compatibility expectations should be checked closely before merge.
- Broader docs and representative config-specific e2e hardening remain in Phase 16.
