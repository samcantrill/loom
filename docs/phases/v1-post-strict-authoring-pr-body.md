## Summary

@samcantrill

This PR implements Phase 2 of the v1-post configuration remediation plan: strict config authoring and override semantics. It rejects duplicate YAML mapping keys before composition can silently collapse them, and it makes JSON double-quoted override scalars decode as literal strings rather than being reinterpreted as booleans, `null`, or numbers.

It also adds public compose regression coverage for intentionally unsupported v1 behavior: literal-dot override keys remain unaddressable through dot-path override strings, backslash is not a literal-dot escape, and `_copy_` remains rejected when authored in overlays or included files.

## Acceptance Criteria

- [x] JSON double-quoted scalar overrides decode to literal strings without a second type-guessing pass.
- [x] Existing unquoted booleans, `null`, finite numbers, arrays, objects, and invalid JSON rejection behavior is preserved.
- [x] Duplicate YAML mapping keys are rejected during base, overlay, and included config loading with existing structured `ConfigLoadError` context.
- [x] Public compose coverage confirms no literal-dot escape syntax and no v1 override addressing for literal-dot mapping keys.
- [x] Public compose coverage confirms `_copy_` is rejected in overlays and included files.
- [x] Future-phase work such as `_copy_` implementation, literal-dot path grammar, schema registries, provenance, persistence, and broader structured-error expansion is not included.

## Implementation Notes

- `src/loom/config/overrides.py` now treats valid JSON double-quoted values as literal strings, including boolean-like, null-like, numeric-looking, empty, escaped, and ordinary strings. Malformed JSON strings raise `OverrideParseError`; existing array/object JSON parsing and unquoted scalar parsing remain separate.
- `src/loom/config/load.py` now uses a loader-local `yaml.SafeLoader` subclass to reject duplicate mapping keys before root validation, recursive-alias checks, unsupported directive checks, merge/include composition, or plain-data conversion. The implementation does not mutate global PyYAML loader behavior.
- Duplicate-key failures continue through existing `ConfigLoadError` and `ConfigErrorContext` fields with `code="duplicate_key"`, source kind/order/path, best-effort config path, expected/actual values, remediation, and duplicated-key details.
- Override path parsing remains the existing dot-split behavior with explicit `+` add semantics. No escaping, bracket notation, list patching, deletion, or splice semantics were added.

New tests implemented:

- Unit override parser coverage for JSON-quoted scalar strings, malformed JSON strings, and preservation of existing typed override parsing.
- Unit loader coverage for duplicate keys at root, nested mappings, sequence-contained mappings, base/overlay source context, and loader-local PyYAML behavior.
- Public compose integration coverage for duplicate keys in base, overlay, and included config files.
- Public compose integration coverage for literal-dot/no-escape override behavior and `_copy_` rejection in overlays and included files.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default harness passed with 435 passed and 11 skipped; config-extra passed with 338 passed and 441 deselected; `uv build` produced sdist and wheel artifacts. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; overall summary passed with 779 passed, 9 skipped, and 441 deselected. |
| GitHub checks | Pending at PR creation | CI will run after the PR is submitted; local PR validation passed before opening. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 38 | 0 | 0 | 1 | 0 | 39 | 4.25s | 21% |
| unit | passed | 357 | 0 | 0 | 1 | 0 | 358 | 3.92s | 55% |
| contract | passed | 31 | 0 | 0 | 2 | 0 | 33 | 1.55s | 29% |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 1.92s | 40% |
| e2e | passed | 6 | 0 | 0 | 0 | 0 | 6 | 4.52s | 68% |
| config-extra | passed | 338 | 0 | 0 | 0 | 441 | 338 | 10.02s | 77% |
| Overall | passed | 779 | 0 | 0 | 9 | 441 | 788 | 26.17s | - |

## Risks / Follow-Ups

- Duplicate-key config paths are best effort from YAML nodes, but source kind/order/path and duplicated-key details are recorded through the existing structured context.
- Mapping keys containing literal dots remain intentionally unaddressable by v1 override strings until a future explicit path grammar is designed.
- Later phases still own source-authorship completion, broader structured-error expansion, artifact-safe provenance/fingerprint changes, pipeline persistence, recipe hardening, and final documentation/evidence cleanup.
