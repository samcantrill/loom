## Summary

- Adds `loom cancel RUN_URI --jobs` for the latest active submitted SLURM operation, with schema-versioned JSON and conservative text output.
- Implements SLURM cancellation under the backend package: per-job `scancel`, terminal-target skips, partial/unknown result mapping, durable manifest cancellation attempts, and submitted-operation backend metadata.
- Mutates core Loom statuses only where safe: successfully cancelled non-final stages can become `CANCELLED`, full cancellation can mark the run `CANCELLED`, and final `SUCCEEDED`/`FAILED` stage outcomes are never overwritten.
- Keeps default validation fake-runner and cluster-free; exact submission ID selection, retries, cleanup, and real-cluster cancellation acceptance remain deferred.

## Tests

| Suite | Result |
| --- | --- |
| `make validate-pr` | Passed: default 911 passed / 17 skipped / 10 deselected; config-extra 412 passed / 936 deselected; build succeeded |
| `make test-summary` | Passed: package 52 passed / 1 skipped; unit 731 passed / 1 skipped; contract 72 passed / 2 skipped; integration 45 passed / 7 skipped / 10 deselected; e2e 36 passed; config-extra 412 passed / 936 deselected |
| Targeted Phase 6 slice | Passed: 47 cancellation/import tests |
| Broader SLURM/CLI slice | Passed: 155 SLURM, CLI, cancellation, status-contract, manifest-contract, integration, and e2e tests |

## Notes

- `loom cancel` intentionally requires `--jobs` in this phase.
- Partial and unknown cancellation outcomes remain active in the submitted-operation registry for follow-up inspection or cancellation.
- Real SLURM cancellation acceptance coverage is part of Phase 7.
