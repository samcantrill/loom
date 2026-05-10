## Summary

This PR closes the Phase 6 read-model paths by making lifecycle status,
catalog, plan resume, diagnostics, and SLURM active-submission preflight read
from authority-backed state instead of local status files.

Local logs, artifact refs, generated files, and provenance materialization
remain readable. Historical local-only runs are now reported as unsupported
lifecycle state rather than indexed as current behavior.

## Changes

- Routed `loom plan --resume` default store construction through the
  authority-backed serial run-store factory.
- Made diagnostics status inspection authority-only for lifecycle facts while
  preserving local artifact and log materialization reads.
- Routed SLURM active-submission preflight through authority-backed submitted
  operation reads.
- Updated run catalog direct scans to summarize lifecycle facts from
  authority snapshots, retain local artifact materialization refs, and warn
  without indexing local-only lifecycle state.
- Updated CLI contracts, examples, and tests so supported lifecycle fixtures use
  authority-backed runs and local-only lifecycle candidates report
  `local_lifecycle_unsupported`.

## Tests

| Suite | Result |
| --- | --- |
| `make validate-pr` | Passed Ruff, Pyright, default tests, config-extra tests, and build |
| package | 57 passed, 1 skipped |
| unit | 838 passed, 1 skipped |
| contract | 108 passed, 2 skipped |
| integration | 90 passed, 8 skipped, 10 deselected |
| e2e | 39 passed, 1 deselected |
| config-extra | 420 passed, 1135 deselected |

## Assumptions And Risks

- Historical local-only runs are still useful for artifacts and logs, but
  lifecycle behavior now requires an authority backend.
- Catalog warning payloads now include `local_lifecycle_unsupported`, which is
  intentionally treated as a public compatibility warning code.
