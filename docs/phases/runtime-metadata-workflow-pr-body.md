## Summary

Adds the Phase 7 run workflow wiring for v4 runtime options. `RunRequest`
now carries normalized `RunOptions` as the canonical invocation-policy field,
the runner resolves typed per-stage runtime handoffs for executors, and local
runs persist a safe schema-versioned `runtime.json` observability document.

This keeps execution behavior local-only. Runtime metadata is safe to inspect
but is not the executor handoff, does not include environment variable names or
values, does not persist raw adapter payloads, and does not participate in
semantic stage fingerprints.

## Acceptance Criteria

- [x] `RunRequest.options` normalizes `RunOptions` or mapping inputs.
- [x] Legacy `run_uri`, `selectors`, and `resume` inputs normalize into
  `options` with clear conflict errors.
- [x] `RunRequest.open_existing` remains run-store lifecycle policy; runtime
  resume remains planning reuse policy.
- [x] `StageExecutionRequest.resolved_runtime` carries typed per-stage runtime
  data.
- [x] Local runs write and read safe `runtime.json` through run-store APIs.
- [x] CLI validate/plan/run use composed config, profiles, and CLI flags to
  build normalized `RunOptions`.
- [x] Plan and dry-run remain read-only for explicit fresh run URIs.
- [x] Python runner rejects concrete `dry_run=True` requests before store
  mutation.

## Implementation Notes

- Added `src/loom/pipeline/runtime/metadata.py` with
  `ResolvedStageRuntimeOptions`, `RuntimeMetadata`,
  `resolve_run_runtime()`, and `build_runtime_metadata()`.
- Extended execution models so `RunRequest.options` is canonical while
  compatibility fields mirror normalized values for existing callers.
- Added runner wiring to resolve runtime once, write safe runtime metadata
  after config/spec resolution, and pass the per-stage typed handoff to
  executors.
- Added `RunRuntimeMetadataStore` plus `LocalRunStore` `runtime.json`
  read/write methods.
- Updated CLI plan/run/validate to compose config before runtime option merge
  and final run URI handling, allowing config-authored runtime options to
  participate in normalization.
- Updated public docs and package/API contracts for the new runtime metadata
  and store surfaces.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default suite, config-extra suite, and build passed on 2026-05-07. |
| `make test-summary` | Passed | Wrote `build/test-summary.md` on 2026-05-07 with overall status `passed`. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 50 | 0 | 0 | 1 | 0 | 5.64s |
| unit | passed | 559 | 0 | 0 | 1 | 0 | 5.90s |
| contract | passed | 53 | 0 | 0 | 2 | 0 | 1.94s |
| integration | passed | 15 | 0 | 0 | 7 | 7 | 2.09s |
| e2e | passed | 16 | 0 | 0 | 0 | 0 | 6.23s |
| config-extra | passed | 397 | 0 | 0 | 0 | 693 | 19.27s |
| Overall | passed | 1090 | 0 | 0 | 11 | 700 | 41.07s |

## Risks / Follow-Ups

- Non-local executor behavior, subprocess/stage-worker handoff, plugin
  discovery, adapter schemas, retries/timeouts, and environment application
  remain future roadmap work.
- Safe adapter metadata is namespace/count only until a later descriptor or
  plugin phase defines approved adapter summaries.
- Run and stage environment requests remain separate in the resolved handoff
  until a later phase defines sparse environment merge semantics.
