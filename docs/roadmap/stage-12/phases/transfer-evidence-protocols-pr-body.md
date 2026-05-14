## Summary

- Add public transfer-evidence helpers under `loom.runs` for converting
  `TransferVerificationRecord` values into queue-consumable delegated
  verification mappings.
- Preserve `proven`, `unproven`, and `unsupported` transfer evidence in SLURM
  delegated verification reports without importing run bundle internals into
  queue code.
- Add fake importer/exporter protocol conformance coverage plus structured
  unsupported transfer/provider diagnostics.

## Tests

| Command / suite | Result |
| --- | --- |
| `make validate-pr` | Passed: Ruff, Pyright, default pytest, config-extra pytest, and build |
| `make test-summary` package | Passed: 77 passed, 1 skipped |
| `make test-summary` unit | Passed: 1052 passed, 7 skipped, 1 deselected |
| `make test-summary` contract | Passed: 179 passed, 2 skipped |
| `make test-summary` integration | Passed: 148 passed, 8 skipped, 13 deselected |
| `make test-summary` e2e | Passed: 41 passed, 2 deselected |
| `make test-summary` config-extra | Passed: 438 passed, 1506 deselected |

## Assumptions And Risks

- Transfer handlers and concrete provider adapters remain unsupported in v12;
  this phase only publishes evidence/result contracts and structured
  unsupported diagnostics.
- Queue adapters continue to consume plain delegated verification mappings and
  do not parse bundle archives or provider-specific data.
- Future providers may need to widen protocol options, but this phase does not
  change the Phase 1 `RunExporter` or `RunImporter` method shapes.
