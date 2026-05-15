## Summary

- Add `loom runs export`, `loom runs inspect`, and `loom runs import` under the
  existing `loom runs` command group with text and JSON output.
- Keep the CLI thin over public `loom.runs` APIs: export opens the local
  SQLite authority store by run URI, inspect reads through bundle APIs without
  extraction, and import delegates target writes to the public importer.
- Document metadata-only defaults, payload/log/workspace flags, target-local
  identity, source provenance, offline-evidence alignment, unsupported
  providers, and live-resume deferral.

## Tests

| Command / suite | Result |
| --- | --- |
| `make validate-pr` | Passed: Ruff, Pyright, default pytest, config-extra pytest, and build |
| `make test-summary` package | Passed: 77 passed, 1 skipped |
| `make test-summary` unit | Passed: 1055 passed, 7 skipped, 1 deselected |
| `make test-summary` contract | Passed: 180 passed, 2 skipped |
| `make test-summary` integration | Passed: 149 passed, 8 skipped, 13 deselected |
| `make test-summary` e2e | Passed: 42 passed, 2 deselected |
| `make test-summary` config-extra | Passed: 438 passed, 1512 deselected |

## Assumptions And Risks

- `loom runs export` supports local SQLite authority-backed run URIs in v12;
  provider dispatch and plugin-loaded exporters remain deferred.
- Imported bundle runs remain historical-only and target-local; live migrated
  resume, merge, overwrite, fork, and remote materialization remain out of
  scope.
- The CLI returns public result dictionaries in JSON envelopes and does not
  parse archive members or mutate target run stores directly.
