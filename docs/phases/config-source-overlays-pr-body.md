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
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Failed | Ruff passed; Pyright failed on `tests/unit/loom/config/test_source_maps.py` because helper parameter `kind: str` is passed to `ConfigSource.kind: Literal["base", "overlay"]`. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Failed | Wrote `build/test-summary.md`; package, unit, contract, integration, and e2e suites passed, but `config-extra` errored during collection due duplicate `test_source_maps.py` module basenames. |
| Targeted phase validation | Passed | Source-map unit tests: 11 passed; merge/compose unit tests: 28 passed; config integration tests: 5 passed; targeted Ruff check passed. |
| GitHub checks | Not run | PR creation is intentionally deferred to the expanded-path `pr-body-refine.md` pass. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 | 3.98s |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 | 4.59s |
| contract | passed | 24 | 0 | 0 | 1 | 0 | 25 | 1.57s |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 2.15s |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 | 3.37s |
| config-extra | failed | 0 | 0 | 1 | 0 | 428 | 1 | 3.35s |
| Overall | failed | 428 | 0 | 1 | 8 | 428 | 437 | 19.01s |

## Risks / Follow-Ups

- Final PR validation is blocked by the Pyright test-helper type error and the `config-extra` duplicate test-module collection error noted above.
- Source maps remain internal by design and may be reshaped additively when include expansion, public inspection, and artifact population phases define their final record needs.
- Mapping container nodes can be overlay-authored while surviving descendants remain base-authored after recursive merges; reviewers should inspect both node and descendant source-map behavior.
