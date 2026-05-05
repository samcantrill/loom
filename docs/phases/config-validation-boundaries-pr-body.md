## Summary

@samcantrill

This PR narrows public config validation so `compose_config(...)` treats trusted
project-owned mappings as domain-neutral pass-through data instead of requiring
top-level `name`, `pipeline`, or Loom schema defaults. Loom-owned validation now
stays at explicit config boundaries while `_target_` remains inert composition
data for the later instantiation phase.

It also rejects authored `_schema_` directives in base, overlay, and included
YAML with structured source context, preserving the v1 decision that project
schema authoring is out of scope for generic composition.

## Acceptance Criteria

- [x] Generic project configs compose without top-level `name`, `pipeline`, or
  `schema_version`.
- [x] Public composition does not inject `schema_version` into project-owned
  payloads or derived redacted/fingerprint data.
- [x] Project-owned unknown keys and `_target_` nodes pass through composition
  without schema inference, import, or constructor inspection.
- [x] Exact authored `_schema_` keys fail as unsupported schema-authoring
  directives with source-aware context.
- [x] Structured validation errors can carry serializable context without
  pulling pipeline validation into `loom.config`.

## Implementation Notes

- `validate_top_level_fields(...)` now validates only that the public composition
  boundary receives a mapping, then returns a shallow copy of the project
  payload. It no longer requires or defaults Loom-specific top-level fields.
- Config loading rejects `_schema_` alongside the existing unsupported `_copy_`
  directive check, with directive, config path, source kind/order/path, expected
  shape, actual value, and remediation in the error context.
- `ConfigValidationError` now uses the shared config error base so validation
  boundary failures can serialize structured context consistently with load,
  include, override, and resolver errors.
- The change stays inside `loom.config` and tests; there are no new runtime
  dependencies, CLI changes, persistence changes, pipeline imports, schema
  registries, or instantiation behavior changes.

New tests implemented:

- Unit coverage for generic top-level pass-through, no schema-version defaulting,
  inert `_target_` data, non-mapping validation failure, and authored `_schema_`
  load rejection.
- Integration coverage for generic `compose_config(...)` payloads without
  `name`/`pipeline`, redaction/provenance/fingerprint behavior on generic data,
  inert project-scoped `_target_`, and `_schema_` rejection in base, overlay, and
  included files.
- Contract coverage for `ConfigValidationError` structured context
  serialization.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted Phase 10 refinement group | Passed | `47 passed` |
| Remaining targeted group | Passed | `38 passed` |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff, Pyright, default tests, config-extra tests, and build completed |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | Suite summary below from `build/test-summary.md` |
| GitHub checks | Pending | PR not opened yet; local validation passed |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 36 | 0 | 0 | 1 | 0 |
| unit | passed | 354 | 0 | 0 | 1 | 0 |
| contract | passed | 28 | 0 | 0 | 1 | 0 |
| integration | passed | 9 | 0 | 0 | 5 | 0 |
| e2e | passed | 5 | 0 | 0 | 0 | 0 |
| config-extra | passed | 253 | 0 | 0 | 0 | 432 |
| Overall | passed | 685 | 0 | 0 | 8 | 432 |

## Risks / Follow-Ups

- Project schema validation remains intentionally external to v1; `_schema_` is
  rejected until a future roadmap designs explicit project schema extension
  points.
- `_target_` validation remains owned by the Phase 11 instantiation boundary,
  so this PR deliberately does not import or inspect target objects during
  composition.
- GitHub checks still need to run after the PR is submitted.
