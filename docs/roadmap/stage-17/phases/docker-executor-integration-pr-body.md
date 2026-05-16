## Summary

Implements the Phase 3 Docker executor integration. `DockerExecutor` now runs
prepared stage-worker attempts through the Phase 2 Docker command runner,
reads the standard worker result, and returns parent-finalized
`StageExecutionResult` values without taking over run-store or artifact-store
authority.

The PR also exposes lazy Docker executor imports and wires
`loom run --executor docker` through the existing CLI executor selection path.
Default validation remains Docker-daemon-free through fake command runners.

## Acceptance Criteria

- [x] `DockerExecutor` uses the prepared-worker lifecycle with parent-owned
  finalization.
- [x] Docker command metadata is redacted and excludes raw adapter payloads and
  raw environment values.
- [x] Success, missing/invalid/mismatched worker result, failed worker result,
  process/worker conflict, signal, and launch-error mappings are covered.
- [x] `loom run --executor docker` selects the Docker executor without
  changing local, subprocess, or SLURM routing.

## Implementation Notes

- Added `loom.pipeline.executors.docker.executor.DockerExecutor` with
  `requires_prepared_worker_request = True`.
- The executor parses `adapter_options.container` and `adapter_options.docker`,
  derives Docker resource intent from resolved runtime resources, adds
  path-parity mounts for the local run directory and artifact root, and builds
  a shell-free Docker argv.
- Worker result handling mirrors the prepared subprocess path while using
  Docker-specific failure messages and executor metadata.
- Docker package and root executor exports stay lazy so importing command
  contracts does not import runtime layers.

New tests implemented:

- Unit coverage for Docker executor success, setup errors, result validation,
  failure wrapping, process conflicts, resource flags, signal facts, path
  mounts, and redaction.
- Integration coverage for a fake Docker runner that invokes the real durable
  stage worker and lets the parent runner finalize outputs.
- CLI/package coverage for `_build_executor("docker")`, explicit
  `--executor docker`, and public lazy exports.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted Docker executor pytest | Passed | `14 passed` |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `make test-summary` | Passed | `2211 passed, 18 skipped, 1796 deselected` |
| GitHub checks | Passed | PR #173 `checks` succeeded before merge |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 99 | 0 | 0 | 1 | 0 |
| unit | passed | 1222 | 0 | 0 | 7 | 1 |
| contract | passed | 250 | 0 | 0 | 2 | 0 |
| integration | passed | 157 | 0 | 0 | 8 | 13 |
| e2e | passed | 43 | 0 | 0 | 0 | 2 |
| config-extra | passed | 440 | 0 | 0 | 0 | 1780 |

## Risks / Follow-Ups

- Docker preflight diagnostics and stable check IDs remain Phase 4.
- Published examples and optional live Docker smoke guidance remain Phase 5.
- Timeout/retry policy remains future Stage 19 work; Phase 3 records process
  facts only.
