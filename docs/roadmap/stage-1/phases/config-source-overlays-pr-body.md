## Summary

@samcantrill

This PR implements Configuration Phase 4 source-authored overlays. Base and overlay configs now flow through an internal source-aware composition helper that preserves caller overlay order and records which `ConfigSource` authored each retained config node.

The public `ComposedConfig` shape, provenance payload, manifests, fingerprints, CLI surface, and inspection APIs are unchanged. Include-like keys are tracked as ordinary authored data only; this PR does not resolve includes or add later v1 public artifact fields.

## Acceptance Criteria

- [x] Overlay order is preserved exactly for source-aware composition.
- [x] Source maps identify base-authored values versus first and later overlay-authored values.
- [x] Overlay-authored `_include_` values retain overlay source context without include resolution.
- [x] Source-map replacement behavior mirrors Phase 3 `merge_configs()` and consumes `_replace_` markers.

## Implementation Notes

`src/loom/config/source_maps.py` adds internal immutable config path tuples, diagnostic path formatting, base source-map construction, and `compose_config_with_sources()` for base plus ordered overlay composition. The helper records root, mapping, list, scalar, and explicit `null` nodes, preserves surviving lower-precedence descendants during recursive mapping merges, and reauthors replaced subtrees to the winning overlay source.

`src/loom/config/compose.py` now loads overlays in the existing order, passes loaded `(config, ConfigSource)` pairs through the internal source-aware helper, and continues returning the same public `ComposedConfig` fields after overrides, interpolation, recipes, provenance, and fingerprint generation.

This phase intentionally does not implement include resolution, recursive includes, user include replacement, public source-map or inspection fields, manifests/provenance population, fingerprints, raw source persistence, CLI behavior, or pipeline imports.

New tests implemented:

- Unit coverage for immutable tuple path identity, literal-dot diagnostic formatting, base source-map coverage, ordered overlay authorship, recursive merge preservation, container/list/scalar/null replacement, `_replace_` marker discard, nested replacement parity with `merge_configs()`, and overlay-authored `_include_` data.
- Integration coverage that loads a base plus two overlays and verifies final values and source authorship for base, first-overlay, and second-overlay retained values through the internal helper.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default harness passed with 423 passed/9 skipped; config-extra passed with 160 passed/428 deselected; build succeeded. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | Wrote `build/test-summary.md`; overall suite evidence passed with 588 passed, 0 failed, 0 errors, 8 skipped, and 428 deselected. |
| Targeted phase validation | Passed | Source-map unit tests: 11 passed; merge/compose unit tests: 28 passed; config integration tests: 5 passed; targeted Ruff check passed. |
| GitHub checks | Pending | CI starts after PR creation; PR target/head verification is recorded in the phase notes. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 | 3.73s |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 | 4.01s |
| contract | passed | 24 | 0 | 0 | 1 | 0 | 25 | 1.53s |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 1.86s |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 | 3.43s |
| config-extra | passed | 160 | 0 | 0 | 0 | 428 | 160 | 7.55s |
| Overall | passed | 588 | 0 | 0 | 8 | 428 | 596 | 22.10s |

## Risks / Follow-Ups

- Source maps remain internal by design and may be reshaped additively when include expansion, public inspection, and artifact population phases define their final record needs.
- Mapping container nodes can be overlay-authored while surviving descendants remain base-authored after recursive merges; reviewers should inspect both node and descendant source-map behavior.
