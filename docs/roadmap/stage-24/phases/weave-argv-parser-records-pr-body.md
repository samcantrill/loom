## Summary

This PR implements Phase 1 of Weave argv config shorthand by adding a private `weave._argv` parser layer for argv-like config tokens. It parses `<command> <base-config> ...` into internal records for value overrides, scoped overlay requests, and unparsed command args without changing config composition behavior.

The implementation stays parser-only: it adds no public exports, no scoped-overlay YAML loading or merging, no base-file existence validation, no warnings, no provenance or fingerprint changes, no docs/features behavior changes, no first-party CLI integration, and no Loom imports.

## Acceptance Criteria

- [x] Parse command and base config argv tokens with caller-provided command choices and structured diagnostics.
- [x] Lower no-slash shorthand tokens through the existing override parser while preserving path-like RHS values as values.
- [x] Record trailing-slash scoped overlay tokens, including nested slash scopes and `+scope/=`, with deterministic RHS candidates and resolved path where available.
- [x] Reject unsupported root overlays and report malformed argv, missing base token, disallowed unparsed args, invalid values, and missing overlay candidates with structured argv context.
- [x] Keep Phase 1 internal and parser-only with no public API, composition, YAML loading, provenance, fingerprint, warning, CLI, or Loom runtime changes.

## Implementation Notes

`packages/weave/src/weave/_argv.py` defines frozen internal records for parsed argv, value overrides, scoped overlays, scoped overlay candidates, and unparsed args. Value tokens reuse `parse_overrides(...)`, while scoped overlay tokens resolve candidate paths using scope-directory then base-directory order, `.yaml` before `.yml` for suffixless relative RHS values, exact absolute paths, no `~` expansion, and normalized relative escapes.

Structured parser errors use existing config-owned error context with `source_kind="argv"` and include command, token, scope, RHS, and candidate details where relevant. The parser inspects the filesystem only to select scoped overlay RHS candidates; it does not validate the base config file and does not load YAML.

New tests implemented:

- `packages/weave/tests/unit/config/test_argv.py` covers command choices, missing command/base token diagnostics, value override lowering, path-like RHS values, scoped overlay classification, nested scopes, `+scope/=`, absolute and relative RHS lookup, suffix probing, literal `~`, relative escape normalization, unparsed args, root overlay rejection, candidate diagnostics, and base-file non-validation.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright passed; default harness `1982 passed, 108 deselected`; config-extra `128 passed, 3 skipped, 1985 deselected`; weave package `395 passed`; weave examples `8 passed`; loom and weave builds succeeded. |
| `make test-summary` | Passed | Generated `build/test-summary.md`; overall `2513 passed, 0 failed, 0 errors, 3 skipped, 2087 deselected`. |
| GitHub checks | Not run | PR not opened in this expanded-path draft pass; refine/open pass will create the PR and CI evidence. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 112 | 0 | 0 | 0 | 4 | 112 | 23.84s | 19% |
| unit | passed | 1402 | 0 | 0 | 0 | 2 | 1402 | 45.41s | 82% |
| contract | passed | 252 | 0 | 0 | 0 | 8 | 252 | 13.34s | 59% |
| integration | passed | 170 | 0 | 0 | 0 | 82 | 170 | 46.79s | 66% |
| e2e | passed | 46 | 0 | 0 | 0 | 6 | 46 | 44.27s | 59% |
| config-extra | passed | 128 | 0 | 0 | 3 | 1985 | 131 | 124.49s | 58% |
| weave | passed | 395 | 0 | 0 | 0 | 0 | 395 | 5.91s | 88% |
| weave-examples | passed | 8 | 0 | 0 | 0 | 0 | 8 | 3.56s | N/A |
| Overall | passed | 2513 | 0 | 0 | 3 | 2087 | 2516 | 307.60s | - |

## Risks / Follow-Ups

- Phase 2 still owns scoped overlay YAML loading, merge behavior, provenance, fingerprints, and inspection integration.
- Phase 3 still owns public argv compose/inspect helpers, warnings, docs, and end-to-end public behavior.
- Parser records remain private in this phase; future public record shape should be finalized only when the Phase 3 API is exposed.
