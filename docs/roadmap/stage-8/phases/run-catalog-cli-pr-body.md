## Summary

- Added the `loom runs` command group with `index`, `list`, and `diff` subcommands.
- Wired the commands to the public `RunCatalog` API and added text plus JSON formatting for catalog results and comparisons.
- Updated run-catalog and CLI docs for the implemented command surface, filters, JSON schema versions, and boundaries.

## Scope Notes

- CLI handlers delegate to `RunCatalog.rebuild()`, `RunCatalog.list()`, and `RunCatalog.compare()`.
- The CLI parses exact-match filters and formats public API result models; it does not scan run directories directly, query SQLite directly, load artifact payloads, or import project code.
- `loom runs diff` takes an explicit collection path plus two run URI strings.

## Tests

| Suite / Command | Result |
| --- | --- |
| `uv run ruff check src/loom/cli tests/unit/loom/cli tests/contracts/test_cli_runs_contract.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py tests/package/test_import_boundaries.py` | Passed |
| `uv run pyright src/loom/cli tests/unit/loom/cli tests/contracts/test_cli_runs_contract.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py tests/package/test_import_boundaries.py` | Passed: 0 errors, 0 warnings |
| `uv run pytest tests/unit/loom/cli/test_main.py tests/unit/loom/cli/test_runs.py tests/contracts/test_cli_runs_contract.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py tests/package/test_import_boundaries.py` | Passed: 47 passed |
| `make validate-pr` | Passed: Ruff, Pyright, default harness, config-extra harness, and build |
| `make test-summary` | Passed; wrote `build/test-summary.md` |

`make test-summary` suite evidence:

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 55 | 0 | 0 | 1 | 0 | 7.63s |
| unit | passed | 760 | 0 | 0 | 1 | 0 | 22.68s |
| contract | passed | 78 | 0 | 0 | 2 | 0 | 4.68s |
| integration | passed | 64 | 0 | 0 | 7 | 10 | 78.04s |
| e2e | passed | 37 | 0 | 0 | 0 | 1 | 20.66s |
| config-extra | passed | 413 | 0 | 0 | 0 | 997 | 39.88s |
| Overall | passed | 1407 | 0 | 0 | 11 | 1008 | 173.56s |

## Assumptions And Risks

- Text output is intentionally compact; JSON preserves the full public result payload.
- Catalog warnings are shown both in the public result payload and as top-level CLI warnings for consistent command-envelope handling.
- Richer selectors, sorting, pagination, top-level diff aliases, bundles, and sweep commands remain out of scope.
