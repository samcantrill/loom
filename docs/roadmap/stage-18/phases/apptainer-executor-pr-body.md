## Summary

Phase 3 adds direct Apptainer/Singularity execution for prepared stage attempts. It introduces deterministic `apptainer exec`/`singularity exec` command records, fake/subprocess exec runners, and `ApptainerExecutor`/`SingularityExecutor` implementations that preserve Loom's normal stage-worker result handoff.

The implementation keeps Apptainer behavior adapter-local, keeps shared container records runtime-neutral, records selected command identity, injects required run/artifact path-parity binds, and redacts configured environment values from persisted metadata and failures. SLURM wrapping, diagnostics/docs, and real runtime smoke remain later Stage 18 phases.

## Acceptance Criteria

- [x] Apptainer exec command construction supports binds, workdir, `--cleanenv` default, explicit env projection, GPU flags, and image/SIF refs.
- [x] `singularity` can be selected as a compatibility executor and records the selected command identity.
- [x] Direct execution uses the prepared-worker contract and handles launch, process, worker-result, and conflict failures as structured execution results.
- [x] Package imports remain optional-runtime-light and do not require Apptainer/Singularity binaries.
- [x] Default validation remains fake/local/offline and does not require Docker, Apptainer, Singularity, SLURM, images, registries, fakeroot, or network.

## Implementation Notes

New Apptainer behavior:

- `loom.pipeline.executors.apptainer.commands` owns `ApptainerExecOptions`, `ApptainerExecCommand`, fake/subprocess exec runners, version-command construction, and deterministic `exec` argv construction.
- `loom.pipeline.executors.apptainer.executor` owns `ApptainerExecutor` and `SingularityExecutor`, mirroring Docker/subprocess prepared-worker result handling.
- Required host environment variables are resolved into Apptainer-compatible `--env NAME=value` entries and are redacted in persisted argv/metadata.
- `loom run --executor apptainer` and `loom run --executor singularity` now select the new direct executors.

New tests implemented:

- Unit tests for exec argv construction, option validation, redaction, alias command selection, fake runner behavior, timeout/exception mapping, path binds, worker result failures, process conflicts, and signal metadata.
- Contract/package tests for executor protocol membership and optional-runtime import boundaries.
- Integration tests using an in-process fake runner to prove parent-owned finalization and provenance with both Apptainer and Singularity executor names.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Focused Apptainer unit suite | Passed | 28 passed |
| Targeted package/unit/contract suite | Passed | 159 passed, 1 skipped |
| Integration slice | Passed | 2 passed outside sandbox; sandbox blocks local authority socket creation |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `make test-summary` | Passed | Overall 2334 passed, 18 skipped, 1912 deselected |
| Post-review focused validation | Passed | Apptainer unit suite: 28 passed; targeted Ruff/Pyright passed |
| GitHub checks | Pending | To be recorded after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 103 | 0 | 0 | 1 | 0 |
| unit | passed | 1318 | 0 | 0 | 7 | 1 |
| contract | passed | 261 | 0 | 0 | 2 | 0 |
| integration | passed | 162 | 0 | 0 | 8 | 13 |
| e2e | passed | 43 | 0 | 0 | 0 | 2 |
| config-extra | passed | 447 | 0 | 0 | 0 | 1896 |

## Risks / Follow-Ups

- Direct Apptainer execution records CPU/memory requests as metadata but does not enforce local resource allocation.
- Path parity remains fail-closed; explicit path translation is deferred.
- SLURM composition, selected-executor preflight/docs, examples, and optional real Apptainer/Singularity smoke remain Phase 4 and Phase 5 work.
