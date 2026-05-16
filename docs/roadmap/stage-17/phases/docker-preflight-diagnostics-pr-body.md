## Summary

This PR adds Docker selected-executor preflight diagnostics for command
availability, container/Docker option shape, image references, required host
environment variables, mount sources and targets, run-directory writability,
local artifact-root path visibility, CPU/memory mapping, and unsupported GPU
requests.

The checks reuse the Stage 17 container and Docker option records, emit
structured plain-data details, redact environment values, and stay cheap by
default: no Docker daemon probe, image pull, registry contact, network check,
or Docker SDK dependency is introduced.

## Acceptance Criteria

- [x] Stable Docker preflight check IDs cover command, config, image, env,
  filesystem, artifact-root, CPU/memory, and GPU readiness.
- [x] Docker checks run only for the selected Docker executor and preserve
  local, subprocess, and SLURM preflight behavior.
- [x] JSON/details output is actionable and redaction-safe.
- [x] Default validation remains Docker-free and daemon-free.

## Implementation Notes

- Added Docker check IDs to the existing diagnostics model under executor,
  resources, and filesystem groups.
- Extended `diagnostics.preflight` with selected-Docker checks that parse
  `adapter_options.container` and `adapter_options.docker` through existing
  container and Docker records.
- Kept command readiness to `PATH` lookup only, and kept image checks to
  authored-reference validation only.
- Added filesystem checks for authored mount source existence, Stage 17
  path-parity target summaries, run-directory parent writability, and required
  run/artifact mount conflicts.
- Added resource checks for Docker CPU/memory mapping and unsupported GPU
  requests.

New tests cover Docker pass/fail diagnostics, redaction, stable IDs, CLI JSON,
real preflight integration, selected-executor behavior, and import boundaries.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted Phase 4 suite | Passed | `87 passed, 2 skipped` |
| Broader Phase 4 suite with config extra | Passed | `666 passed` |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `make test-summary` | Passed | Overall `2221 passed, 18 skipped, 1804 deselected` |
| GitHub checks | Passed | GitHub Actions `checks` passed |

### Test Suite Summary

| Suite | Passed | Skipped | Deselected |
| --- | ---: | ---: | ---: |
| package | 100 | 1 | 0 |
| unit | 1228 | 7 | 1 |
| contract | 251 | 2 | 0 |
| integration | 157 | 8 | 13 |
| e2e | 43 | 0 | 2 |
| config-extra | 442 | 0 | 1788 |
| overall | 2221 | 18 | 1804 |

## Risks / Follow-Ups

- Docker command readiness is intentionally PATH-only; live daemon, image
  availability, digest, pull, and registry checks remain future opt-in work.
- GPU mapping remains unsupported for Stage 17.
- Phase 5 will add user-facing Docker examples, preflight examples, failure
  inspection docs, and optional live Docker smoke guidance.
