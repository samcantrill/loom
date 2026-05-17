## Summary

Phase 2 adds local foreground build/reuse support for Stage 18 `container_build` targets. It introduces a runtime-neutral policy decision and dispatch service, deterministic fake builders, Docker image build helpers over the existing Docker command runner, and a build-only Apptainer package for SIF construction.

The implementation keeps shared records import-light and keeps runtime command behavior in Docker/Apptainer-owned modules. It records redacted command projections and bounded evidence/failure metadata without adding SDKs, registry/auth helpers, global cache, image locks, daemon queues, direct Apptainer execution, or SLURM composition.

## Acceptance Criteria

- [x] Local/fake builders deterministically build, reuse, and fail Docker image and Apptainer SIF targets.
- [x] `always`, `if_stale`, and `never` policy decisions are covered by shared tests.
- [x] Docker build commands are CLI/buildx-compatible and redact build-arg values.
- [x] Apptainer build commands support definition/local/URI sources and SIF outputs without adding `apptainer exec`.
- [x] Default validation remains fake/local/offline and does not require Docker, Apptainer, Singularity, SLURM, registries, images, fakeroot, or network.

## Implementation Notes

New shared behavior in `loom.pipeline.executors.containers`:

- `ContainerBuildPolicyDecision` and `evaluate_container_build_policy`.
- `LocalContainerBuildService` and `ContainerBuilder` protocol.
- `FakeContainerBuilder` for deterministic local build service tests.
- Redacted persisted build-key fields while preserving raw authored inputs for the digest.

New runtime-specific behavior:

- `loom.pipeline.executors.docker.build` constructs `docker build` and `docker buildx build` argv, checks local image presence with the existing fakeable Docker runner, and returns shared `ContainerBuildResult` records.
- `loom.pipeline.executors.apptainer.build` constructs `apptainer build`/`singularity build` SIF commands, uses local output/source mtimes for cheap reuse decisions, and exposes fake/subprocess build runners.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Focused Phase 2 suite | Passed | 133 passed, 1 skipped |
| Phase-level targeted suite | Passed | 519 passed, 7 skipped |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `make test-summary` | Passed | Overall 2308 passed, 18 skipped, 1886 deselected |
| GitHub checks | Pending | To be recorded after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 102 | 0 | 0 | 1 | 0 |
| unit | passed | 1295 | 0 | 0 | 7 | 1 |
| contract | passed | 261 | 0 | 0 | 2 | 0 |
| integration | passed | 160 | 0 | 0 | 8 | 13 |
| e2e | passed | 43 | 0 | 0 | 0 | 2 |
| config-extra | passed | 447 | 0 | 0 | 0 | 1870 |

## Risks / Follow-Ups

- Docker `if_stale` intentionally reuses a locally inspectable image without registry freshness checks or image locks.
- Apptainer URI source freshness remains unprobed to keep default behavior offline.
- Direct Apptainer execution, SLURM composition, preflight, docs, examples, and optional real runtime smoke remain later phases.
