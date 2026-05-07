## Summary

@samcantrill

This PR adds the Phase 3 runtime invocation model layer for v4. Python callers can now construct, validate, serialize, and safely summarize `RunOptions`, `ExecutionOptions`, `StageRuntimeOptions`, `RunEnvironmentRequest`, and `StageEnvironmentRequest` before later phases add profile merge, executor capability checks, CLI/config mapping, run workflow wiring, or persisted runtime metadata.

The implementation keeps planning and execution ownership intact: selector and resume inputs adapt to existing planning models, entry-based resources flow through the Phase 2 `ResourceRequest` schema, environment requests remain in-memory only, and safe metadata omits environment keys/values and raw adapter payloads.

## Acceptance Criteria

- [x] Public runtime imports expose run options, stage options, execution options, and run/stage environment requests.
- [x] Runtime models support strict plain-data serialization and round trips.
- [x] `RunOptions` adapts selector and resume data to planning-owned `PlanSelectors` and `ResumeOptions`.
- [x] Stage runtime options carry entry-based resources, execution settings, environment requests, and adapter options keyed by exact stage ID.
- [x] Safe metadata omits environment keys/values and raw adapter payloads.
- [x] Runner, CLI/config, preflight, executor descriptor, profile merge, plugin discovery, local environment application, and `runtime.json` wiring remain out of scope.

## Implementation Notes

| Area | Notes |
| --- | --- |
| Runtime models | Added frozen, strict runtime option dataclasses with deterministic `to_dict` / `from_dict` behavior and public facade exports from `loom.pipeline.runtime` and `loom.pipeline`. |
| Planning boundary | Added adapters from `RunOptions` to `PlanSelectors` and `ResumeOptions` without moving graph-aware selector or resume semantics into runtime. |
| Stage options | Added exact-stage validation helpers and entry-based `ResourceRequest` integration; old resource aliases remain rejected by the resource layer. |
| Privacy | Added safe metadata summaries that preserve counts and namespace names while excluding environment keys, environment values, and raw adapter payloads. |
| Deferred wiring | Contract tests pin that `RunRequest.options`, `StageExecutionRequest.runtime_options`, and stage environment consumption are still deferred to later phases. |

New tests implemented:

- Runtime unit coverage for defaults, populated round trips, immutable inputs, schema errors, environment privacy, entry-based stage resources, and known-stage validation.
- Contract coverage for plain-data serialization, planning adapter ownership, and the unwired execution-envelope boundary.
- Integration coverage for Python API construction with synthetic exact stage IDs and resource entries.
- Package/API coverage for public exports and import-light runtime boundaries.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Recorded during Phase 3 implementation refinement: Ruff, Pyright, default tests with 617 passed / 13 skipped / 12 deselected, config-extra with 396 passed / 632 deselected, and `uv build` passed. |
| `make test-summary` | Passed | `UV_CACHE_DIR=/tmp/loom-uv-cache make test-summary` wrote `build/test-summary.md`; overall 1028 passed, 10 skipped, 644 deselected. |
| GitHub checks | Pending | PR opening triggers GitHub CI; this preparation pass does not claim GitHub-side check evidence. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 50 | 0 | 0 | 1 | 0 | 5.94s |
| unit | passed | 513 | 0 | 0 | 1 | 0 | 5.63s |
| contract | passed | 44 | 0 | 0 | 2 | 0 | 1.67s |
| integration | passed | 10 | 0 | 0 | 6 | 12 | 1.94s |
| e2e | passed | 15 | 0 | 0 | 0 | 0 | 6.33s |
| config-extra | passed | 396 | 0 | 0 | 0 | 632 | 16.18s |
| Overall | passed | 1028 | 0 | 0 | 10 | 644 | 37.70s |

## Risks / Follow-Ups

- Runtime profiles and merge precedence are Phase 4 scope.
- Executor descriptors, capability validation, and adapter namespace diagnostics are Phase 5 scope.
- CLI/config mapping and preflight wiring are Phase 6 scope.
- Run workflow wiring, `RunRequest.options`, resolved stage runtime handoff, and persisted `runtime.json` are Phase 7 scope.
- Environment requests are intentionally not applied to local in-process execution or persisted.
