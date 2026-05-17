## Summary

Phase 5 completes Stage 18 by adding selected-executor preflight diagnostics for shared container build targets, direct Apptainer/Singularity execution, and SLURM plus Apptainer composition. The checks stay cheap by default: they inspect authored runtime options, local path metadata, command presence through `PATH`, and redacted option summaries without running Docker, Apptainer, Singularity, SLURM, registries, fakeroot, or network operations.

The phase also updates user-facing docs for container execution, SLURM composition, preflight, provenance, and testing, and adds opt-in real-runtime acceptance hooks that skip unless explicitly enabled.

## Acceptance Criteria

- [x] Stable preflight IDs cover selected container build targets, Apptainer/Singularity command/options/image/environment checks, SLURM/container compatibility, Apptainer resource mapping, and relevant filesystem checks.
- [x] Preflight consumes the existing `container`, `container_build`, `apptainer`, `singularity`, and `slurm` adapter namespaces without changing build or execution semantics.
- [x] Diagnostics remain JSON-safe and redacted; environment values and command/build secrets are not persisted.
- [x] Default validation does not run real containers, submit SLURM jobs, contact registries, or require Docker/Apptainer/Singularity/SLURM to be installed.
- [x] Feature docs describe Stage 18 build target reuse, direct Apptainer/Singularity execution, SLURM wrapping, cheap preflight, provenance boundaries, and opt-in smoke hooks.
- [x] Real Docker/Apptainer/SIF-build acceptance hooks exist and skip unless explicitly enabled by environment variables.

## Implementation Notes

- Added stable diagnostics under the existing `runtime`, `executor`, `resources`, and `filesystem` preflight groups instead of introducing a container-specific group.
- Added container build target validation for selected runtimes, including missing targets, runtime/output compatibility, local source checks, and non-mutating output checks.
- Added direct Apptainer/Singularity checks for command availability, parsed container options, image/SIF references, bind source/target parity, writable run paths, artifact-root visibility, required host env names, and GPU flag compatibility.
- Added SLURM plus Apptainer compatibility checks so selected scheduler/container profiles expose missing runtime flags or incompatible resource mappings before dry-run or live submission.
- Added skipped-by-default acceptance hooks in `tests/container_acceptance/test_real_container_runtimes.py` for real Docker preflight, real Apptainer preflight, and real Apptainer SIF build checks.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Optional container acceptance hooks | Passed | 3 skipped by default |
| Targeted diagnostics/package/e2e suite | Passed | 217 passed |
| Ruff | Passed | `uv run ruff check .` |
| Pyright | Passed | `uv run --extra config pyright` |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed outside the sandbox |
| `make test-summary` | Passed | Overall 2350 passed, 21 skipped, 1928 deselected |
| GitHub checks | Pending | To be verified after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 103 | 0 | 0 | 1 | 0 |
| unit | passed | 1329 | 0 | 0 | 7 | 1 |
| contract | passed | 263 | 0 | 0 | 2 | 0 |
| integration | passed | 164 | 0 | 0 | 8 | 13 |
| e2e | passed | 44 | 0 | 0 | 0 | 2 |
| config-extra | passed | 447 | 0 | 0 | 3 | 1912 |

## Risks / Follow-Ups

- Direct Apptainer/Singularity preflight intentionally does not resolve `container.target`; users should pass the built SIF path through `container.image.reference` until a future explicit target-resolution contract is approved.
- Container build output checks remain local/reference metadata checks only; expensive builder, registry, or remote filesystem probes are deferred.
- SLURM remains responsible for CPU, memory, and GPU allocation; Apptainer diagnostics only verify selected runtime flags and metadata compatibility.
