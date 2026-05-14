## Summary

This PR makes direct Python runner execution authority-backed by rejecting bare
`LocalRunStore` instances in `PipelineRunner` and `run_pipeline`, then updates
public Python examples and tests to use `create_authority_backed_serial_run_store`.

It keeps local files available through materialization/artifact surfaces while
preventing `LocalRunStore` from acting as mutating lifecycle authority through
the Python facade.

## Changes

- Added a `PipelineRunner` diagnostic for local-only runtime stores.
- Exposed `create_authority_backed_serial_run_store` from
  `loom.pipeline.execution`.
- Updated README, feature docs, and direct Python examples to use the
  authority-backed serial factory.
- Migrated runner, docs-example, import-boundary, integration, and e2e tests to
  authority-backed stores for mutating execution.
- Kept direct `LocalRunStore` coverage focused on local file-lock behavior.

## Tests

| Suite | Result |
| --- | --- |
| `make validate-pr` | Passed Ruff, Pyright, default tests, config-extra tests, and build |
| package | 57 passed, 1 skipped |
| unit | 837 passed, 1 skipped |
| contract | 108 passed, 2 skipped |
| integration | 90 passed, 8 skipped, 10 deselected |
| e2e | 39 passed, 1 deselected |
| config-extra | 420 passed, 1134 deselected |

## Assumptions And Risks

- The transitional SQLite-backed serial adapter still provides the Python API
  bridge until later service/backend phases.
- Changed-config same-run re-execution remains failure-closed after an existing
  authoritative stage output commit; this avoids silent commit replacement
  until explicit rerun/supersede semantics are designed.
