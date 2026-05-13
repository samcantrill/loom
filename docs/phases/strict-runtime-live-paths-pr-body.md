## Summary

Phase 2 hardens the v10-post runtime live paths that later queue phases will depend on. HTTP client-backed authority stores now require a fresh live endpoint readiness check before live SLURM submit, status persistence, or cancellation can proceed, so stale construction-time authority facts are not enough for scheduler mutation.

The bounded parallel runner also treats authority-store failures as trust-boundary failures. Even when ordinary user-code failures use `continue_independent`, authority loss stops new stage launches and leaves unresolved work blocked.

## Acceptance Criteria

- [x] No user stage code starts with stale or missing authority lease or fencing facts.
- [x] Live SLURM fails closed when HTTP service-backed authority reachability is unavailable at the operation boundary.
- [x] Runtime scheduling stops additional stage launches after authority loss.
- [x] Deferred finalization remains outside normal live controller, worker, and SLURM paths.

## Implementation Notes

- Added an internal `requires_live_endpoint_readiness` marker on HTTP client-backed authority stores.
- Centralized strict SLURM authority readiness in `slurm_live_authority_facts(...)`, preserving deterministic in-process authority fixtures while requiring fresh endpoint readiness for HTTP-backed live stores.
- Updated bounded parallel scheduling so authority failures stop further submissions even under `continue_independent`.

New tests implemented:

- SLURM submit/status/cancel rejection coverage for unreachable HTTP authority facts.
- Parallel execution coverage proving `continue_independent` does not launch later work after authority allocation loss.
- Focused regression coverage over existing stage worker and stage-job authority fencing.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default harness passed with 1364 passed, 19 skipped, 14 deselected; config-extra passed with 434 passed, 1394 deselected; `uv build` produced sdist and wheel. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; overall 1825 passed, 12 skipped, 1406 deselected. |
| GitHub checks | Pending | To be populated after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 70 | 0 | 0 | 1 | 0 |
| unit | passed | 992 | 0 | 0 | 1 | 0 |
| contract | passed | 157 | 0 | 0 | 2 | 0 |
| integration | passed | 132 | 0 | 0 | 8 | 10 |
| e2e | passed | 40 | 0 | 0 | 0 | 2 |
| config-extra | passed | 434 | 0 | 0 | 0 | 1394 |
| Overall | passed | 1825 | 0 | 0 | 12 | 1406 |

## Risks / Follow-Ups

- In-process authority fixtures remain deterministic and do not probe fake HTTP endpoints; real HTTP client-backed stores are the strict-readiness path.
- Later queue phases should treat missing authority readiness as a dispatch, status, or cancellation blocker rather than adding queue-specific fallback mutation.
