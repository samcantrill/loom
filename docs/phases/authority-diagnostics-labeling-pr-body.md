## Summary

- Add shared plain-data source labels for authoritative service truth, local materialized state, deferred/offline evidence vocabulary, unavailable authority, registry hints, and unknown sources.
- Label backend diagnostics, status/stage/submitted-operation summaries, artifact/log summaries, preflight details, run catalog summaries, and catalog warnings with source/policy facts.
- Surface concise source labels in backend/status/preflight/runs CLI text without changing command structure or mutation behavior.

## Tests

| Command | Result |
| --- | --- |
| `make validate-pr` | Passed: Ruff, Pyright, default harness, config-extra harness, and package build all succeeded |
| `make test-summary` | Passed: overall 1757 passed, 12 skipped, 1350 deselected |

Suite evidence from `make test-summary`:

| Suite | Result |
| --- | --- |
| package | 69 passed, 1 skipped |
| unit | 954 passed, 1 skipped |
| contract | 146 passed, 2 skipped |
| integration | 127 passed, 8 skipped, 10 deselected |
| e2e | 39 passed, 2 deselected |
| config-extra | 422 passed, 1338 deselected |

## Assumptions And Risks

- Source fields are additive JSON payload fields; existing schema versions are unchanged.
- Offline evidence labels are vocabulary-only in this phase. Phase 17 and Phase 18 will attach them to real offline evidence/import data.
- Backend and status read paths remain read-only. Unavailable authority is reported explicitly instead of downgrading lifecycle truth to local files.
