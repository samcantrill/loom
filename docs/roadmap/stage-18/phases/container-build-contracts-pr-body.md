## Summary

Phase 1 adds the shared `container_build` contract for Stage 18. It defines import-light build records for named Docker/Apptainer build targets, build sources, output refs, policies, deterministic build keys, requests/results, redacted command projections, evidence, and failures without running Docker or Apptainer commands.

It also updates import-light executor descriptors so Docker, Apptainer, Singularity, and SLURM modes claim the Stage 18 adapter namespaces they will consume in later phases, while preserving existing profile namespace replacement semantics.

## Acceptance Criteria

- [x] Shared build records validate, serialize, redact, and reject invalid source, policy, output, and runtime/output combinations.
- [x] `container_build` is separate from Stage 17 `container` execution options and follows whole-namespace replacement semantics.
- [x] Descriptor namespace claims cover Docker, Apptainer, Singularity, and SLURM composition without importing runtime command modules.
- [x] Default validation remains fake/local/offline and does not require Docker, Apptainer, Singularity, SLURM, registries, images, fakeroot, or network.

## Implementation Notes

New shared records live in `loom.pipeline.executors.containers` beside the landed Stage 17 container execution records. The build-key helper hashes the plain authored target description only; it does not fetch source content, inspect registries, or treat image identity as a semantic stage fingerprint.

New tests implemented:

- Unit and contract coverage for build record round trips, invalid shapes, redaction, output refs, deterministic build keys, requests/results, and import boundaries.
- Runtime profile coverage for `container_build` shorthand and whole-namespace replacement.
- Descriptor coverage for Docker, Apptainer, Singularity, and SLURM namespace claims.

Automated manager review after PR creation fixed ordered command/log vector serialization and redacted metadata projections so redacted records expose metadata keys rather than raw metadata values.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted Phase 1 suite | Passed | 172 passed, 1 skipped |
| Post-review focused suite | Passed | 16 passed |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `make test-summary` | Passed | Overall 2293 passed, 18 skipped, 1871 deselected |
| GitHub checks | Pending | To be recorded after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 102 | 0 | 0 | 1 | 0 |
| unit | passed | 1282 | 0 | 0 | 7 | 1 |
| contract | passed | 260 | 0 | 0 | 2 | 0 |
| integration | passed | 159 | 0 | 0 | 8 | 13 |
| e2e | passed | 43 | 0 | 0 | 0 | 2 |
| config-extra | passed | 447 | 0 | 0 | 0 | 1855 |

## Risks / Follow-Ups

- Later phases still need to implement local builders, Apptainer execution, SLURM composition, preflight, and docs.
- `container_build` intentionally replaces the whole namespace during profile merge; per-target overlay remains deferred.
- Real Docker, Apptainer/SIF, and SLURM smoke remains optional and out of default validation.
