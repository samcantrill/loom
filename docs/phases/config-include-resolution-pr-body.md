## Summary

@samcantrill

This PR implements Configuration Phase 5 include resolution primitives. It adds
an internal resolver that turns one authored `_include_` target plus source
context into a deterministic local file path, or raises a structured config
error with source and include-site context.

The scope is intentionally limited to target classification, path/URI safety,
exact-file validation, and error shape. It does not load included YAML, traverse
config trees, expand recursive includes, change `compose_config()` behavior, or
add public manifest/provenance/fingerprint fields.

## Acceptance Criteria

- [x] Bare names resolve from the including file plus mapping-key path and
      append exactly `.yaml`.
- [x] Explicit relative paths, absolute paths, and local-only `file://` URIs
      resolve only to exact existing regular files.
- [x] Unsupported schemes, ambiguous `file:` forms, unsafe implicit paths,
      missing targets, directories, invalid include-site paths, and
      resolver-dependent targets fail with structured config errors.
- [x] Include primitives remain internal, with no root `loom.config` export or
      recursive include expansion.

## Implementation Notes

`src/loom/config/includes.py` adds `resolve_include_target()` and the internal
`IncludeResolutionResult` shape. The resolver accepts a `ConfigSource` and
`ConfigPath`, validates that the site points at `_include_`, classifies accepted
target forms, normalizes candidate paths, and records whether the author made an
explicit escape from the implicit bare-name layout.

Bare-name targets are restricted to `[A-Za-z0-9_-]+`, use exact mapping-key path
segments without splitting literal dots, reject list-index and unsafe path
segments, append exactly `.yaml`, and reject symlink escapes from the derived
config directory. Explicit relative, absolute, and `file://` targets are allowed
to escape only because the target form is explicit, but still require one exact
existing regular file and do not probe suffix variants.

`src/loom/config/errors.py` adds internal `ConfigIncludeResolutionError`.
Structured error context carries the source path/order/kind, formatted include
site, authored target, target kind, candidate/resolved path details where
applicable, and safety/scheme reasons without resolving interpolation or
including raw source bytes.

New tests implemented:

- Unit coverage for accepted bare-name, nested bare-name, explicit relative,
  absolute, and local `file://` targets.
- Unit coverage for invalid include sites, unsupported target forms, missing
  exact files, directory targets, unsafe bare-name containment, malformed or
  ambiguous file URIs, unsupported schemes, and resolver-dependent targets.
- Unit and contract coverage for the include error subclass and serialized
  `ConfigErrorContext` payload.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default harness passed with 424 passed/9 skipped; config-extra passed with 191 passed/429 deselected; build succeeded. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | Wrote `build/test-summary.md`; overall suite evidence passed with 620 passed, 0 failed, 0 errors, 8 skipped, and 429 deselected. |
| Targeted phase validation | Passed | Include unit tests passed with 31 tests; include error unit/contract tests passed; package API/import-boundary checks passed during final gates. |
| GitHub checks | Pending | CI starts after PR creation; this expanded-path draft does not open the PR. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 | 3.83s |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 | 3.75s |
| contract | passed | 25 | 0 | 0 | 1 | 0 | 26 | 1.56s |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 1.95s |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 | 3.42s |
| config-extra | passed | 191 | 0 | 0 | 0 | 429 | 191 | 7.73s |
| Overall | passed | 620 | 0 | 0 | 8 | 429 | 628 | 22.23s |

## Risks / Follow-Ups

- Recursive include traversal, include stacks/cycles, sibling merge behavior,
  and public composition artifacts remain Phase 6+ work.
- The result and include-error shapes are internal and may need additive fields
  once recursive expansion and inspection records consume them.
- Path behavior is POSIX-local for this phase; remote/plugin resolvers and
  Windows-specific positive forms remain out of scope.
