## Summary

This phase adds the public runtime profile and merge API for v4 runtime
options. Python callers can now define named `RuntimeProfile` defaults, group
them in a `RuntimeProfileCollection`, select a profile, and normalize
base/profile/explicit invocation data into a canonical `RunOptions`.

The merge contract is deterministic and profile-focused: sparse mapping inputs
preserve absent fields, typed `RunOptions` inputs are fully supplied sources,
scalars and sequences replace, mappings merge shallowly, stage options merge by
exact stage ID, and stage resources merge by `ResourceRequest.entries` kind.

## Acceptance Criteria

- [x] Python callers can construct, serialize, select, and merge runtime
  profiles into normalized `RunOptions`.
- [x] Core profile sections validate strictly while non-core adapter namespaces
  are preserved as opaque plain data.
- [x] Base/profile/explicit precedence is stable:
  `config base < selected runtime profile < explicit invocation options`.
- [x] Stage options merge by exact stage ID, resource entries merge by kind, and
  known-stage validation can run after merge.
- [x] Phase scope excludes config/CLI mapping, executor descriptors, preflight,
  runner handoff, persisted `runtime.json`, and adapter schema validation.

## Implementation Notes

- Added `src/loom/pipeline/runtime/profiles.py` with `RuntimeProfile`,
  `RuntimeProfileCollection`, profile parsing/selection helpers, and
  `merge_run_options`.
- Exported the new profile and merge APIs from `loom.pipeline.runtime` and
  `loom.pipeline` while preserving the runtime package import boundary.
- Reused existing Phase 3 models for strict core section parsing:
  `RunOptions`, `ExecutionOptions`, `StageRuntimeOptions`, environment
  requests, selector/resume adapters, and entry-based resources.
- Folded non-core top-level profile sections into `RunOptions.adapter_options`
  as plain data, with duplicate in-profile adapter namespaces rejected.
- Updated runtime resource/profile docs and structure notes to document the
  implemented profile merge contract without claiming later config, CLI,
  preflight, execution, or persistence behavior.

New tests implemented:

- Package tests for public exports and import-boundary preservation.
- Unit tests for profile construction, serialization, strict schema failures,
  profile selection failures, sparse mapping behavior, typed source behavior,
  scalar/list replacement, shallow mapping merge, environment merge, exact-stage
  merge, resource-entry merge, adapter namespace preservation, and no-deletion
  semantics.
- Contract tests for deterministic plain-data serialization, normalized
  `RunOptions` merge output, typed-source behavior, and absence of outer runtime
  layer imports.
- Integration tests for config-shaped base/profile/explicit dictionaries,
  selected-profile resolution, explicit profile clearing, and known-stage
  validation.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default harness tests, config-extra harness tests, and `uv build` passed during implementation. |
| `make test-summary` | Passed | `build/test-summary.md` generated on 2026-05-07 with overall status `passed`. |
| GitHub checks | Passed | PR #73 `checks` workflow completed with `SUCCESS` on 2026-05-07. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 50 | 0 | 0 | 1 | 0 |
| unit | passed | 526 | 0 | 0 | 1 | 0 |
| contract | passed | 48 | 0 | 0 | 2 | 0 |
| integration | passed | 12 | 0 | 0 | 6 | 12 |
| e2e | passed | 15 | 0 | 0 | 0 | 0 |
| config-extra | passed | 396 | 0 | 0 | 0 | 651 |
| Overall | passed | 1047 | 0 | 0 | 10 | 663 |

## Risks / Follow-Ups

- Mapping fields still have no deletion syntax; empty sparse mappings do not
  clear inherited tags, settings, resource entries, or adapter namespaces.
- Stage runtime options match only exact stage IDs; glob, tag, group, and graph
  matching remain later-phase work.
- Adapter payloads are preserved but not schema-validated until descriptor,
  adapter, or plugin phases claim those namespaces.
