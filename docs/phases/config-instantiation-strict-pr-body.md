## Summary

@samcantrill

This PR tightens the explicit `loom.config.instantiate(...)` runtime construction boundary for Phase 11. It preserves `_target_` as inert composition data while locking strict runtime import semantics, bottom-up nested construction, `_partial_` behavior, and explicit `_inject_` failure handling.

The production change is intentionally small: runtime injection validation now rejects invalid `_inject_` shapes and falsey non-mapping runtime values without normalizing them away. The rest of the phase hardens the accepted contract through focused tests for target import syntax, recursive construction ordering, partial construction, and runtime injection failures.

## Acceptance Criteria

- [x] Accepted dotted and colon `_target_` forms work through the explicit instantiation path.
- [x] Invalid target forms fail clearly as instantiation errors, including nested lookup attempts and fallback/progressive dotted import cases.
- [x] Nested target configs construct bottom-up across kwargs, `_args_`, lists, and tuples.
- [x] `_partial_: true` returns an uncalled `functools.partial` with recursively constructed args/kwargs and injected runtime values.
- [x] `_inject_` duplicate kwargs, missing runtime values, invalid injection shapes, and non-mapping runtime inputs fail as `RuntimeInjectionError`.
- [x] Public composition remains out of scope for runtime construction; no compose-time target importing or future artifact/fingerprint behavior was added.

## Implementation Notes

- `src/loom/config/instantiate/injection.py` now defaults only `runtime is None` to an empty mapping, so falsey non-mapping runtime values still fail validation.
- `_inject_` shape validation moved into the runtime injection path and reports `RuntimeInjectionError` for invalid injection mappings, keys, and runtime-key references.
- `src/loom/config/instantiate/recursive.py` now passes the original runtime value through to injection validation instead of normalizing with `runtime or {}`.
- Target parsing behavior remains strict: dotted targets import exactly the module before the final segment, colon targets accept exactly one top-level object name, and nested attribute traversal is not introduced.
- The phase does not add registries, allow-lists, plugin lookup, CLI behavior, compose-time instantiation, pipeline imports, artifact persistence, or runtime object fingerprinting.

New tests implemented:

- Target import contract tests for accepted forms, invalid syntax, colon nested lookup rejection, and dotted fallback/nested lookup rejection.
- Recursive instantiation tests for bottom-up construction order in kwargs, `_args_`, lists, tuples, and `_partial_` payloads.
- Runtime injection tests for duplicate keys, missing runtime keys, invalid `_inject_` shape, invalid injected key/value shapes, non-mapping runtime inputs, and falsey non-mapping runtime values.
- Synthetic probe helpers in `tests/support/config_samples.py` to make instantiation order and partial-call assertions deterministic.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff, Pyright, default suite, config-extra suite, and build passed at implementation HEAD. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | `build/test-summary.md` generated with overall suite status `passed`. |
| GitHub checks | Not run | PR not opened in this expanded-path draft pass. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 | 3.59s | 22% |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 | 3.74s | 59% |
| contract | passed | 28 | 0 | 0 | 1 | 0 | 29 | 1.43s | 29% |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 1.93s | 43% |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 | 3.47s | 62% |
| config-extra | passed | 266 | 0 | 0 | 0 | 432 | 266 | 8.06s | 76% |
| Overall | passed | 698 | 0 | 0 | 8 | 432 | 706 | 22.23s | - |

Targeted phase checks also passed:

| Check | Result |
| --- | --- |
| `uv run --extra config pytest tests/unit/loom/config/instantiate/test_targets.py` | 6 passed |
| `uv run --extra config pytest tests/unit/loom/config/instantiate/test_recursive.py` | 12 passed |
| `uv run --extra config pytest tests/unit/loom/config/instantiate/test_injection.py` | 9 passed |
| `uv run --extra config pytest tests/package/test_config_api.py tests/package/test_import_boundaries.py` | 17 passed |
| `uv run --extra config pytest tests/integration/config/test_compose_config.py -k target` | 2 passed |

## Risks / Follow-Ups

- The target import contract intentionally remains narrow; future registry, allow-list, or plugin target discovery work needs a separate public design.
- Runtime object fingerprinting and artifact policy for injected objects remain deferred to later pipeline/runtime phases.
- The expanded-path pre-submit blocker gate is still pending and should review this PR body, the final diff, suite evidence, and scope boundary before PR submission.
