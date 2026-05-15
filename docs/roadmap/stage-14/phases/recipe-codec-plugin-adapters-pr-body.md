## Summary

@samcantrill

This PR adds Stage 14 Phase 2 recipe and codec plugin adapter APIs. The adapters load explicitly selected trusted entry points into caller-supplied `RecipeCatalog` and `CodecRegistry` instances while keeping generic plugin discovery metadata-first and registry-neutral.

Recipe plugins register under their entry point names, codec plugins register under runtime `codec.key`, and duplicate or invalid plugin targets are reported through the existing `PluginLoadResult` failure model. Future plugin groups remain listing/check-only.

## Acceptance Criteria

- [x] Recipe and codec adapters populate supplied registries only through explicit loading.
- [x] Duplicate entry point names, duplicate recipe names, duplicate codec keys, invalid objects, and constructor/factory failures report plugin-context failures.
- [x] Generic discovery stays independent from recipe and codec registry imports.
- [x] No global registry mutation, future-group loader, codec replacement API, or artifact-store backend loading is introduced.

## Implementation Notes

- Added lazy public exports for `load_recipe_entry_points` and `load_codec_entry_points` so `import loom.plugins` remains import-light.
- Added a recipe adapter that filters to `loom.recipes`, uses entry point names as catalog names, and defaults `replace=False`.
- Added a codec adapter that filters to `loom.codecs`, accepts codec instances, no-argument codec classes, and no-argument factories, then registers through `CodecRegistry`.
- Kept registration and normalization failures inside the existing plugin load result and strict-mode error paths.

New tests implemented:

- Package API/import-boundary coverage for lazy adapter exports.
- Unit coverage for selected loading, recipe replacement defaults, invalid recipes, codec instance/class/factory shapes, constructor/factory failures, duplicate entry point names, duplicate recipe names, and duplicate runtime codec keys.
- Contract coverage showing fake recipe and codec entry points populate supplied registries and remain usable through existing registry contracts.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Partial rerun; prior pass recorded | Fresh PR-prep rerun passed Ruff and Pyright, then timed out after 900s in `test-no-extra` with no failure output. The phase execution plan records an earlier complete pass. |
| `make test-summary` | Passed | `build/test-summary.md`, generated 2026-05-15T03:36:25+00:00. |
| GitHub checks | Pending | To run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 86 | 0 | 0 | 1 | 0 | 87 |
| unit | passed | 1106 | 0 | 0 | 7 | 1 | 1113 |
| contract | passed | 206 | 0 | 0 | 2 | 0 | 208 |
| integration | passed | 155 | 0 | 0 | 8 | 13 | 163 |
| e2e | passed | 43 | 0 | 0 | 0 | 2 | 43 |
| config-extra | passed | 440 | 0 | 0 | 0 | 1605 | 440 |
| Overall | passed | 2036 | 0 | 0 | 18 | 1621 | 2054 |

## Risks / Follow-Ups

- Codec class/factory normalization is intentionally narrow and accepts only no-argument construction.
- Codec replacement remains unsupported; duplicate runtime keys fail closed.
- CLI, preflight, readiness labels, provenance summaries, and future-group loaders remain assigned to later Stage 14 phases.
