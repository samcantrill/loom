## Summary

This PR defines the Phase 1 authority resolution contract for v10 online and offline behavior. It adds stable, side-effect-free resolver records for online mutation mode, explicit offline-first mode, supplied registry and health facts, typed outcomes, failure categories, and actionable diagnostics without starting services, reading registry files, opening SQLite, or changing runtime factory adoption.

It also exports the new resolver vocabulary through `loom.pipeline.stores` and adds opt-in shared CLI parsing helpers so later commands can carry explicit authority mode intent. Existing authority defaults and service APIs remain compatible for this phase; strict factory/runtime adoption stays in later phases.

## Acceptance Criteria

- [x] Resolver contract types are importable from stable non-transport store modules.
- [x] Missing authority references fail closed for online mutation mode.
- [x] `direct_database` selections produce unsupported/reserved diagnostics rather than online mutation access.
- [x] Explicit offline-first resolution succeeds as non-authoritative.
- [x] Diagnostics include next steps without starting a service or probing external state.
- [x] Existing authority store/service behavior remains covered without runtime factory adoption.

## Implementation Notes

Added `src/loom/pipeline/stores/authority_resolution.py` with the public resolver API: authority modes, reference sources, service health facts, registry hints, diagnostic records, outcome/failure enums, resolver inputs/results, env/mapping helpers, and `resolve_authority()`.

The resolver accepts only supplied facts and classifies explicit endpoints, valid registry hints, stale or wrong-workspace registry hints, incompatible generation or protocol facts, unavailable or unhealthy service facts, missing authority, reserved direct database selections, and explicit offline-first mode. `loom.pipeline.stores` deliberately exports the new public vocabulary, and `src/loom/cli/authority.py` can opt into hidden `--authority-mode` / `--offline-first` parsing without changing existing command defaults.

New tests implemented:

- Package export and import-boundary coverage for resolver contracts.
- Unit coverage for resolver classification, diagnostics, mode env/mapping helpers, and shared CLI parsing.
- Contract coverage proving clients can distinguish online, offline, stale registry, incompatible, unavailable/unhealthy, and reserved direct-database outcomes from typed data.
- Integration regression evidence through the final PR validation gate for existing service authority behavior.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default isolated harness passed with 1173 passed, 18 skipped, and 14 deselected; config-extra passed with 420 passed and 1202 deselected; `uv build` produced sdist and wheel artifacts. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Wrote `build/test-summary.md`; overall summary passed with 1619 passed, 12 skipped, and 1213 deselected. |
| GitHub checks | Pending | Not available before PR creation; GitHub CI will run after submission. |

### Test Suite Summary

| Suite | Status | Passed | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: |
| package | passed | 61 | 1 | 0 | 13.87s |
| unit | passed | 878 | 1 | 0 | 43.79s |
| contract | passed | 120 | 2 | 0 | 11.89s |
| integration | passed | 101 | 8 | 10 | 61.10s |
| e2e | passed | 39 | 0 | 1 | 37.40s |
| config-extra | passed | 420 | 0 | 1202 | 63.49s |

## Risks / Follow-Ups

- The resolver names become long-lived v10 vocabulary, so future failure classes should be additive and contract-tested.
- Current factories still auto-bootstrap co-located service outside this resolver until the Phase 10 strict resolver adoption work.
- Offline-first is represented as resolver intent and outcome only; offline evidence writing and import remain later-phase work.
