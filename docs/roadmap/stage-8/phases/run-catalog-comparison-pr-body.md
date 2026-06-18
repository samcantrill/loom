## Summary

- Implemented `RunCatalog.compare(left, right)` as the public Phase 5 metadata comparison API.
- Added private comparison helpers that produce deterministic `RunComparison` sections for run facts, fingerprints, keyed stages, keyed artifacts, execution/submitted-operation metadata, and selected provenance.
- Preserved current catalog warning behavior and added missing-side warnings for absent comparison inputs.

## Scope Notes

- Comparison reads persisted run metadata through current catalog/list behavior.
- Artifact payloads are not read, project code is not imported, and no CLI, plugin, or public SQL behavior is added in this phase.
- Inputs are treated as canonical `run_uri` strings; broader selector ergonomics remain out of scope for v8 Phase 5.

## Tests

| Suite / Command | Result |
| --- | --- |
| `uv run ruff check src/loom/runs tests/unit/loom/runs tests/contracts/test_run_catalog_comparison_contract.py tests/integration/pipeline/test_run_catalog_compare.py` | Passed |
| `uv run pyright src/loom/runs tests/unit/loom/runs tests/contracts/test_run_catalog_comparison_contract.py tests/integration/pipeline/test_run_catalog_compare.py` | Passed: 0 errors, 0 warnings |
| `uv run pytest tests/package/test_runs_api.py tests/package/test_import_boundaries.py tests/unit/loom/runs tests/contracts/test_run_catalog_comparison_contract.py tests/integration/pipeline/test_run_catalog_compare.py tests/integration/pipeline/test_run_catalog_current_list.py` | Passed: 58 passed |
| `make validate-pr` | Passed: Ruff, Pyright, default harness, config-extra harness, and build |
| `make test-summary` | Passed; wrote `build/test-summary.md` |

`make test-summary` suite evidence:

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 55 | 0 | 0 | 1 | 0 | 7.41s |
| unit | passed | 755 | 0 | 0 | 1 | 0 | 16.58s |
| contract | passed | 75 | 0 | 0 | 2 | 0 | 3.25s |
| integration | passed | 61 | 0 | 0 | 7 | 10 | 53.17s |
| e2e | passed | 36 | 0 | 0 | 0 | 1 | 15.63s |
| config-extra | passed | 413 | 0 | 0 | 0 | 985 | 32.36s |
| Overall | passed | 1395 | 0 | 0 | 11 | 996 | 128.39s |

## Assumptions And Risks

- Missing optional scalar metadata is reported as `unknown`; one-sided keyed children such as stages and artifacts are reported as `left_only` or `right_only`.
- Comparison warning output may include current-list warnings from the collection scan, matching the Phase 4 current-read behavior this API delegates to.
- CLI presentation and user-friendly selector parsing are deferred to Phase 6.
