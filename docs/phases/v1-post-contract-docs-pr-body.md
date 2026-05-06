## Summary

@samcantrill

This PR cleans up the v1-post Phase 1 configuration contract surface. It removes the source-level `loom.pipeline` type-only dependency on `loom.config`, adds regression coverage proving a direct `PipelineSpec` runner path works without importing config-only modules, and updates user-facing docs to match accepted v1 decisions around trusted config authoring, inspection APIs, override paths, and strict `_target_` syntax.

It also narrows stale roadmap language so v1 no longer advertises `_copy_` as implemented scope and marks resolved D01, D03, and D23 planning-note items as confirmed.

## Acceptance Criteria

- [x] `loom.pipeline` direct Python execution remains usable without importing `loom.config` or config-only dependencies.
- [x] Public config docs describe authored configs as trusted project code and clarify that untrusted configs are unsupported.
- [x] `inspect_config_composition` is documented as an inspection/debugging/testing API, not a pipeline construction path.
- [x] Dot-path override no-escape behavior and strict dotted/colon `_target_` syntax are documented.
- [x] Stale `_copy_` v1 roadmap scope and resolved planning-note metadata are corrected without implementing future-phase runtime behavior.

## Implementation Notes

- Replaced the `RunRequest.config` concrete `ComposedConfig` type annotation in `src/loom/pipeline/execution/models.py` with a private duck-typed protocol that preserves existing mapping and composed-config validation behavior without importing `loom.config`.
- Added a subprocess package regression that constructs a direct `PipelineSpec`, runs it through `PipelineRunner.run(...)` with `LocalRunStore`, verifies the expected artifact index, and asserts `loom.config`, `loom.cli`, `project`, `yaml`, `omegaconf`, and `pydantic` are not imported.
- Added unit coverage for direct `PipelineSpec`, plain mapping config, and duck-typed composed config acceptance.
- Updated `docs/features/config.md`, `docs/implementation-plans/implementation-roadmap.md`, and `docs/implementation-plans/roadmap-v1-planning-notes.md` for the Phase 1 documentation cleanup.

New tests implemented:

- `tests/package/test_import_boundaries.py`: full direct runner import-boundary regression.
- `tests/unit/loom/pipeline/execution/test_execution_models.py`: `RunRequest` direct pipeline, plain mapping config, and duck-typed composed config coverage.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors, 0 warnings, 0 informations; default suite passed 435 tests with 11 skipped; config-extra suite passed 314 tests with 441 deselected; build succeeded. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; all suites passed with 755 total passing tests and 9 skipped. |
| GitHub checks | Passed | GitHub CI `checks` completed successfully on PR #44. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 38 | 0 | 0 | 1 | 0 | 4.00s |
| unit | passed | 357 | 0 | 0 | 1 | 0 | 3.74s |
| contract | passed | 31 | 0 | 0 | 2 | 0 | 1.53s |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 1.88s |
| e2e | passed | 6 | 0 | 0 | 0 | 0 | 3.50s |
| config-extra | passed | 314 | 0 | 0 | 0 | 441 | 9.35s |
| Overall | passed | 755 | 0 | 0 | 9 | 441 | 24.01s |

## Risks / Follow-Ups

- Phase 1 is merge-eligible after review because PR #44 targets `develop` and GitHub CI has passed.
- Later v1-post phases still own strict YAML duplicate-key rejection, JSON-quoted scalar override parsing, artifact-safe provenance/fingerprint ordering, default resolved snapshot persistence changes, run-store composition manifests, structured-error expansion, and recipe/resolver residual-risk hardening.
