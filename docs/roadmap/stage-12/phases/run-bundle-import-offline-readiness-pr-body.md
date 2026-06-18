## Summary

- Add local bundle import APIs under `loom.runs`, including import record
  construction, `LocalRunBundleImporter`, strict checksum/member validation,
  target-local identity, collision rejection, provenance, copied payload
  rebasing, and historical-only resume readiness.
- Add an offline-evidence importer adapter that preserves v10 authority-owned
  validation/mutation and maps accepted or rejected imports into shared
  `RunBundleImportResult` semantics without converting offline evidence into a
  bundle.
- Admit historical portable imports into run-catalog scans based on their
  runtime provenance so successful imports are visible without claiming live
  resume support.

## Tests

| Command / suite | Result |
| --- | --- |
| `make validate-pr` | Passed: Ruff, Pyright, default pytest, config-extra pytest, and build |
| `make test-summary` package | Passed: 77 passed, 1 skipped |
| `make test-summary` unit | Passed: 1048 passed, 7 skipped, 1 deselected |
| `make test-summary` contract | Passed: 176 passed, 2 skipped |
| `make test-summary` integration | Passed: 148 passed, 8 skipped, 13 deselected |
| `make test-summary` e2e | Passed: 41 passed, 2 deselected |
| `make test-summary` config-extra | Passed: 438 passed, 1499 deselected |

## Assumptions And Risks

- Imported bundle runs remain historical-only in v12; live migrated resume,
  overwrite, merge, fork, remote materialization, and queue/CLI behavior remain
  out of scope.
- Target-local naming is deterministic from the source run URI basename and
  intentionally rejects collisions.
- Offline evidence continues to mutate authority state only through existing
  `loom.authority.offline_import` paths.
