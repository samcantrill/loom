## Summary

- Adds public authority `RunStore` and scoped `StageStore` protocols, plus
  `create_run_store(...)` as the single public factory path for Phase 2.
- Adds authority configuration/reference records, deployment profile and
  backend-kind vocabulary, redaction helpers, and capability-admission
  diagnostics.
- Renames the old path-shaped runtime aggregate to `LegacyRunStore` and keeps
  existing runtime callers on that explicit transitional surface.
- Adds reusable public authority conformance coverage over in-memory and
  transitional SQLite adapters.

## Tests

| Command | Result |
| --- | --- |
| `make validate-pr` | Passed Ruff, Pyright, default tests, config-extra tests, and build. |
| `make test-summary` | Passed; wrote `build/test-summary.md`. |

Suite evidence from `make test-summary`:

| Suite | Result |
| --- | --- |
| package | 57 passed, 1 skipped |
| unit | 834 passed, 1 skipped |
| contract | 107 passed, 2 skipped |
| integration | 89 passed, 8 skipped, 10 deselected |
| e2e | 39 passed, 1 deselected |
| config-extra | 420 passed, 1129 deselected |

## Assumptions And Risks

- Managed service, allocation-scoped service, direct-database, and
  deferred-finalization backends are represented in config/admission records but
  remain unimplemented until later phases.
- `LegacyRunStore` is intentionally transitional; runtime call-site migration
  is deferred to Phases 4-6.
- Transitional SQLite authority remains available for contract coverage until
  service-backed parity and Phase 10 removal.
