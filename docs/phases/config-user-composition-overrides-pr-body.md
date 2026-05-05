## Summary

@samcantrill

This PR implements Phase 7 user composition overrides for configuration includes. It adds the private composition stage that applies user-authored `path._include_=...` overrides after file-defined include expansion and before ordinary value overrides.

The phase supports exact recorded include-site replacement, explicit brand-new include additions, local sibling customization replay over replacement includes, and ordinary overrides against recomposed values. It intentionally keeps the work private to `loom.config` with no public root exports, new `ComposedConfig` fields, manifests, artifacts, fingerprints, provenance population, CLI behavior, pipeline imports, resolver execution, recipe ordering changes, or `_copy_`.

## Acceptance Criteria

- [x] `path._include_=...` replaces an existing file-defined include site using the recorded include-site source context.
- [x] `+path._include_=...` adds a brand-new include site only when the target is explicit relative, absolute, or `file://`.
- [x] Brand-new bare include targets fail with structured source/context details.
- [x] Local sibling customizations replay over replacement includes without keeping stale replaced-file values.
- [x] Ordinary overrides apply after user include composition and preserve their relative order.
- [x] Phase boundaries remain intact: no public config artifact fields, CLI, pipeline imports, resolver execution, recipe ordering changes, or `_copy_`.

## Implementation Notes

The implementation splits parsed overrides into include-composition overrides and ordinary value overrides in `src/loom/config/overrides.py`, then wires the include-composition stage into `compose_config` before the existing ordinary override pass.

`src/loom/config/includes.py` now carries private recomposition context for include sites: source-local include paths, source metadata, and local customization payloads. `src/loom/config/compose.py` uses that context to replace existing include sites, load and recursively expand replacement targets, replay local overlays, reject `+` against existing recorded include sites, and add only explicit brand-new include sites rooted in the base config source context.

Composition errors for user include overrides are wrapped as `ConfigIncludeExpansionError` with override raw text, order, operation, include-site path, and source details where available. Replacement targets that do not resolve to mappings are reported with user override context rather than leaking lower-level load errors.

New tests implemented:

- Unit coverage for override partitioning while preserving ordinary override order.
- Integration coverage for existing include replacement, strict `+` semantics for existing include sites, nested bare replacement using source-local context, local customization replay, brand-new explicit include additions, brand-new bare target rejection, existing concrete container rejection, structured non-mapping replacement errors, and ordinary overrides after recomposition.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff, Pyright, default test harness, config-extra harness, and build passed on 2026-05-05. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Wrote `build/test-summary.md`; overall 651 passed, 0 failed, 8 skipped, 430 deselected. |
| Focused override/composition suite | Passed | `tests/unit/loom/config/test_overrides.py` and `tests/integration/config/test_compose_overrides.py`: 22 passed after refinement. |
| Broader phase-targeted config suite | Passed | Include, compose, error-contract, and import-boundary targeted suite: 73 passed after refinement. |
| GitHub checks | Pending | Not available before PR creation; review the opened PR checks for remote CI status. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 | 3.64s | 23% |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 | 3.73s | 60% |
| contract | passed | 26 | 0 | 0 | 1 | 0 | 27 | 1.55s | 29% |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 1.79s | 44% |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 | 3.65s | 63% |
| config-extra | passed | 221 | 0 | 0 | 0 | 430 | 221 | 7.94s | 76% |
| Overall | passed | 651 | 0 | 0 | 8 | 430 | 659 | 22.30s | - |

## Risks / Follow-Ups

- User composition records remain private and may be reshaped additively when later inspection, manifest, source artifact, and fingerprint phases expose composition stages.
- Brand-new explicit relative user includes are anchored to the base config source because Python API override strings do not carry their own source file context.
- Resolver security, recipe ordering, public inspection APIs, persisted artifacts, fingerprints, CLI behavior, and `_copy_` remain deferred to later phases.
