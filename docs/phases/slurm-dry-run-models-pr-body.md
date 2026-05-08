## Summary

This PR adds the Phase 3 SLURM dry-run model layer for implementation plan v6. It introduces a scheduler-dependency-free `loom.pipeline.executors.slurm` package with typed SLURM modes, options, validated `extra_sbatch`, launcher and generated command argv records, resource-to-SBATCH mapping, logical dependency records, planned job records, manifest schema models, and generated-artifact path helpers.

The phase is intentionally model-only. It does not render shell scripts, wire CLI dry-run behavior, invoke scheduler commands, parse scheduler job IDs, record submitted status, or change the generic continuation commands.

## Acceptance Criteria

- [x] Structured option parsing rejects unknown fields and modeled/generated directive conflicts.
- [x] `extra_sbatch` normalizes flag names, accepts only string or `true` values, and cannot override modeled or generated directives.
- [x] Generic CPU, memory, and GPU resources map to deterministic SBATCH directive summaries, with path-aware errors for conflicts or unsupported values.
- [x] Planned manifests round trip as schema-versioned plain data with logical job keys, `afterok` dependencies, and scheduler job IDs absent or null only.
- [x] SLURM path helpers request safe run-scoped artifact paths through the store-owned generated-artifact helper.

## Implementation Notes

- Added import-light public exports under `loom.pipeline.executors.slurm`.
- Kept SLURM-specific planning errors, options, resource mapping, manifest records, and path helpers inside the executor adapter package.
- Reused generic `ResourceRequest` and run-store path contracts rather than widening generic runtime models or walking local run directories.
- Preserved the v6 boundary that Phase 4 owns script rendering, Phase 5 owns CLI integration, and v7 owns live scheduler submission.

New tests implemented:

- Package import-boundary coverage for the SLURM package and lower-layer imports.
- Unit coverage for options, launcher argv, `extra_sbatch`, resource mapping, manifest records, logical job keys, dependencies, and path helpers.
- Contract coverage for deterministic planned-submission manifest serialization.
- Integration coverage for generated-artifact path helper interaction with a real local run store.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Refinement pass: Ruff, Pyright, default tests `809 passed, 14 skipped, 8 deselected`, config-extra `405 passed, 828 deselected`, build succeeded. |
| Targeted Phase 3 suite | Passed | `82 passed` across package, unit, contract, and integration paths for SLURM models. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | `build/test-summary.md`: overall `1233 passed, 11 skipped, 836 deselected`. |
| GitHub checks | Pending | Expected to run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 51 | 0 | 0 | 1 | 0 | 5.75s |
| unit | passed | 671 | 0 | 0 | 1 | 0 | 8.71s |
| contract | passed | 58 | 0 | 0 | 2 | 0 | 2.40s |
| integration | passed | 29 | 0 | 0 | 7 | 8 | 3.95s |
| e2e | passed | 19 | 0 | 0 | 0 | 0 | 7.97s |
| config-extra | passed | 405 | 0 | 0 | 0 | 828 | 21.51s |
| Overall | passed | 1233 | 0 | 0 | 11 | 836 | 50.30s |

## Risks / Follow-Ups

- Site-specific SBATCH options remain in validated `extra_sbatch` until later phases justify typed fields.
- Resource mapping is conservative and cluster-free; Phase 5 preflight and v7 live submission own richer site diagnostics.
- Script rendering, CLI behavior, dry-run artifact writing, and live scheduler state are deliberately deferred to later phases.
