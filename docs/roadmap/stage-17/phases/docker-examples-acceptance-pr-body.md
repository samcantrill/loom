## Summary

This PR completes Stage 17 by adding user-facing Docker executor examples and
acceptance documentation. The new example runs `loom run --executor docker`
through the public CLI path with a daemon-free fake `docker` command, inspects
selected-Docker preflight diagnostics, and shows Docker failure inspection
through existing status and log surfaces.

The docs now cover the implemented Stage 17 Docker behavior: per-stage
execution, `adapter_options.container` plus `adapter_options.docker`, path
parity, stable preflight IDs, redacted metadata, optional live Docker guidance,
and the explicit non-goals around whole-controller containers and security
sandbox claims.

## Acceptance Criteria

- [x] Docker examples cover normal pipeline execution through
  `loom run --executor docker`.
- [x] Docker examples cover selected-Docker preflight pass/fail diagnostics.
- [x] Docker examples cover inspectable Docker failures through status and
  logs.
- [x] Runtime/profile examples use `container` and `docker` adapter
  namespaces.
- [x] Default validation remains Docker-daemon-free, network-free,
  registry-free, image-pull-free, and SDK-free.

## Implementation Notes

New example content lives under
`examples/execution/containers/docker/`. The smoke scripts install a small fake
`docker` command on `PATH`; that helper parses `docker run`, applies explicit
`--env` handoff, records redacted call facts, and executes the prepared worker
command locally. This preserves the product path through the CLI,
`DockerExecutor`, Docker command builder, run store, worker result handling,
status, logs, and provenance without requiring a daemon.

Feature docs and catalog coverage were updated in
`docs/features/container-executors.md`, `docs/features/preflight.md`,
`docs/features/runtime-resources.md`, `docs/features/provenance.md`,
`docs/features/reliability.md`, `docs/features/testing.md`, and
`docs/features/container-example-coverage.md`.

New tests implemented:

- `tests/integration/docs/test_v0_python_examples.py` now asserts the v17
  Docker example catalog entry, coverage doc links, Docker command/preflight
  README content, and safety language.
- The existing smoke example harness executes the new Docker pipeline,
  preflight, and failure scripts under the config-extra suite.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py` | Passed | `33 passed` |
| Targeted Phase 5 suite | Passed | `261 passed` across docs examples, diagnostics, Docker executor integration, executor/diagnostics units, and Docker/container/preflight contracts |
| `uv run ruff check examples/execution/containers/docker tests/integration/docs/test_v0_python_examples.py` | Passed | `All checks passed` |
| `make validate-pr` | Passed | Ruff passed; Pyright `0 errors`; default harness `1751 passed, 26 skipped, 18 deselected`; config-extra harness `446 passed, 1788 deselected`; build passed |
| `make test-summary` | Passed | Overall `2225 passed, 18 skipped, 1804 deselected` |
| GitHub checks | Pending | To be filled after PR CI runs |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 100 | 0 | 0 | 1 | 0 | 16.17s |
| unit | passed | 1228 | 0 | 0 | 7 | 1 | 55.78s |
| contract | passed | 251 | 0 | 0 | 2 | 0 | 14.92s |
| integration | passed | 157 | 0 | 0 | 8 | 13 | 75.30s |
| e2e | passed | 43 | 0 | 0 | 0 | 2 | 50.93s |
| config-extra | passed | 446 | 0 | 0 | 0 | 1788 | 112.30s |
| Overall | passed | 2225 | 0 | 0 | 18 | 1804 | 325.39s |

## Risks / Follow-Ups

- Default validation uses a fake Docker command by design; live Docker smoke
  remains manual unless a future roadmap stage introduces deterministic live
  Docker acceptance.
- The examples require path parity for real Docker runs. Images must be able to
  import `loom` and the example stage module at the mounted paths.
- Image builds, registry authentication, Compose, Kubernetes,
  Apptainer/Singularity, SLURM-container composition, GPU mapping, and
  whole-controller container mode remain deferred roadmap work.
