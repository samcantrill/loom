# Summary

- Adds metadata-first sweep collection records and helpers for trial facts,
  lifecycle/status summaries, artifact refs, and unsupported extraction
  diagnostics.
- Adds `loom sweep plan`, `loom sweep run`, `loom sweep status`, and
  `loom sweep collect` as CLI wrappers over public sweep planning, dispatch,
  status, and collection APIs.
- Updates sweep docs and package/import-boundary coverage for the final v13
  workflow without introducing metric parsing, payload extraction, or queue
  controller behavior.

# Validation

| Command or suite | Result |
| --- | --- |
| Targeted Phase 5 pytest/Ruff | Passed (`49 passed`) |
| `make validate-pr` | Passed: Ruff, Pyright, default harness, config-extra harness, package build |
| `make test-summary` package | Passed (`80 passed, 1 skipped`) |
| `make test-summary` unit | Passed (`1088 passed, 7 skipped, 1 deselected`) |
| `make test-summary` contract | Passed (`199 passed, 2 skipped`) |
| `make test-summary` integration | Passed (`155 passed, 8 skipped, 13 deselected`) |
| `make test-summary` e2e | Passed (`43 passed, 2 deselected`) |
| `make test-summary` config-extra | Passed (`438 passed, 1574 deselected`) |

# Notes

- Collection remains metadata-only and does not load artifact payloads or parse
  project metrics.
- Extraction requests return explicit unsupported diagnostics for later
  materialization work.
- Queue-backed CLI behavior submits planned trial intents and reports status;
  it does not start a controller loop or drain queues.
