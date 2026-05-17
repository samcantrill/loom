## Summary

Phase 4 composes the existing SLURM dry-run and live submission paths with Apptainer/Singularity execution. It wraps generated `loom prepared-run continue` and `loom stage-job run` commands with deterministic `apptainer exec` argv, resolves selected Apptainer SIF build targets before rendering or submission, and records redacted container command/build metadata without introducing a new scheduler executor.

SLURM remains the scheduler authority for resources, dependencies, `sbatch`, status, and cancellation. Batch scripts contain only executable container launch commands; they do not hide Docker or Apptainer build commands.

## Acceptance Criteria

- [x] Existing `slurm-single-job` and `slurm-afterok` modes can render Apptainer-wrapped continuation and stage-job commands.
- [x] Run-level and stage-level `adapter_options.container.target` values resolve through `adapter_options.container_build` before dry-run rendering or live `sbatch`.
- [x] Successful Apptainer SIF outputs become `container.image.reference` values used by generated SLURM commands.
- [x] Build target failures, missing targets, and non-Apptainer outputs fail before rendering/submission.
- [x] Generated command metadata remains plain-data-compatible and redacts environment values.
- [x] Default validation stays fake/local/offline and does not require real Docker, Apptainer, Singularity, SLURM, images, registries, fakeroot, or network.

## Implementation Notes

New SLURM composition behavior:

- `loom.pipeline.executors.slurm.container` owns Apptainer command wrapping, target resolution, required run/artifact path-parity mount injection, and redacted build-result summaries.
- `SlurmCommandArgv` now supports optional plain-data metadata while preserving the previous manifest shape when metadata is absent.
- Single-job and afterok planners accept optional container and Apptainer options and wrap generated worker commands before script rendering.
- CLI dry-run/live paths resolve selected build targets first, then pass resolved container options into the existing planning and submission code.
- `singularity` adapter options select the compatible command name without changing the scheduler executor.

New tests implemented:

- Unit tests for SLURM/Apptainer wrapping, target resolution, failure mapping, planner command metadata, and CLI runtime-option rewriting.
- Contract tests for SLURM manifest metadata round trips.
- Integration tests for dry-run script rendering and fake live `sbatch` reuse of wrapped plans.
- E2E dry-run coverage for public CLI generation of direct Apptainer image commands.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted SLURM and CLI unit suite | Passed | 103 passed |
| Targeted contract/integration/e2e suite | Passed | 21 passed, 3 skipped |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed outside the sandbox |
| `make test-summary` | Passed | Overall 2344 passed, 18 skipped, 1922 deselected |
| GitHub checks | Pending | To be recorded after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 103 | 0 | 0 | 1 | 0 |
| unit | passed | 1324 | 0 | 0 | 7 | 1 |
| contract | passed | 262 | 0 | 0 | 2 | 0 |
| integration | passed | 164 | 0 | 0 | 8 | 13 |
| e2e | passed | 44 | 0 | 0 | 0 | 2 |
| config-extra | passed | 447 | 0 | 0 | 0 | 1906 |

## Risks / Follow-Ups

- Path parity remains fail-closed; explicit path translation is deferred.
- SLURM owns CPU/memory/GPU allocation while Apptainer metadata records runtime/device flags only.
- Selected-executor preflight, user docs/examples, and optional real runtime/cluster smoke remain Phase 5 work.
