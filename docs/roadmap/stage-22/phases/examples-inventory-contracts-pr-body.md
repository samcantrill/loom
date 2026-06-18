## Summary

This PR defines the Stage 22 Phase 1 example inventory contract for the existing examples. It adds docs-owned metadata to every current `example.yaml` manifest so examples advertise their public surfaces, owning docs, owning roadmap stages, validation evidence, and manual prerequisites where needed.

It also documents the manifest vocabulary in `examples/README.md` and tightens the docs integration checks so manifest ownership, README catalog placement, feature coverage references, validation paths, and manual rationale stay aligned. There are no runtime behavior changes and no new examples.

## Acceptance Criteria

- [x] Existing example manifests expose stable ownership, public-surface, roadmap-stage, and validation metadata.
- [x] Manual or illustrative examples record prerequisites and rationale for why default validation cannot run them.
- [x] Docs integration checks validate manifest shape, owner docs, feature coverage references, README catalog sections, and smoke validation commands.
- [x] Scope remains docs/examples/tests only, with no runtime imports or new runtime behavior.

## Implementation Notes

- Added `public_surfaces`, `owner_docs`, `owner_stages`, `validation_path`, and where applicable `validation_command`, `prerequisites`, and `manual_rationale` to all 26 existing example manifests.
- Kept metadata as plain YAML owned by docs/tests rather than introducing a runtime schema or package API.
- Extended `tests/integration/docs/test_v0_python_examples.py` to validate the inventory contract and README/catalog consistency while preserving existing smoke example execution.

New tests implemented:

- Manifest contract checks for ownership fields, stage vocabulary, owner-doc existence, validation references, and manual rationale.
- README catalog checks ensuring examples appear under the correct group sections and `internal_demo` examples stay out of primary catalogs.
- Feature coverage consistency checks for manifests that point at focused example coverage docs.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted docs integration | Passed | `UV_CACHE_DIR=.uv-cache uv run --active pytest tests/integration/docs/test_v0_python_examples.py`: 35 passed in 54.11s |
| `make validate-pr` | Passed | Initial sandbox run hung during default pytest because of sandbox execution restrictions and was terminated; rerun outside sandbox passed Ruff, Pyright (`0 errors`), default pytest (`1963 passed, 26 skipped, 21 deselected`), config-extra pytest (`451 passed, 3 skipped, 2001 deselected`), and `uv build` |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; overall 2443 passed, 21 skipped, 2017 deselected |
| GitHub checks | Pending | PR creation will start CI after push |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 108 | 0 | 0 | 1 | 0 | 18% |
| unit | passed | 1394 | 0 | 0 | 7 | 1 | 77% |
| contract | passed | 274 | 0 | 0 | 2 | 0 | 56% |
| integration | passed | 170 | 0 | 0 | 8 | 13 | 62% |
| e2e | passed | 46 | 0 | 0 | 0 | 2 | 59% |
| config-extra | passed | 451 | 0 | 0 | 3 | 2001 | 60% |
| Overall | passed | 2443 | 0 | 0 | 21 | 2017 | - |

## Risks / Follow-Ups

- Validation paths intentionally stay docs/test-owned; if later phases need reusable docs tooling, that should be revisited outside runtime modules.
- Some full/manual examples point to coverage docs rather than per-example executable assertions; Phases 2 and 3 own stronger runnable integration and e2e evidence.
