## Summary

@samcantrill

This PR adds artifact-safe pipeline persistence for composed configs by storing the full composition manifest as plain run-store data instead of writing default resolved or resolved-redacted config snapshots. Composed-config runs now persist `config/composition_manifest.json`, the existing recipe manifest, and config provenance metadata while continuing to build the runtime `PipelineSpec` from in-memory resolved config.

It also documents and tests the runtime fingerprint boundary: output-affecting runtime objects are represented only through explicit stage fingerprint fields, fingerprint context extras, or caller-converted `Fingerprintable.fingerprint()` values. Config fingerprints remain runtime-free.

## Acceptance Criteria

- [x] Add plain-data run-store APIs for reading and writing composition manifests.
- [x] Persist local composition manifests at `config/composition_manifest.json` with strict schema-versioned wrapper validation.
- [x] Stop default composed-config persistence of `config/resolved.yaml` and `config/resolved.redacted.yaml`.
- [x] Keep pipeline/store code free of `loom.config` imports and config artifact classes.
- [x] Preserve caller-provided plain mapping snapshot behavior without treating it as composed-config replay.
- [x] Cover explicit runtime fingerprint inputs without adding automatic runtime object fingerprinting.

## Implementation Notes

`RunConfigStore` now exposes `read_composition_manifest(...)` and `write_composition_manifest(...)` as plain-data protocol methods. `LocalRunStore` implements those methods with an exact-field wrapper containing `schema_version`, `run_id`, `created_at`, and `composition_manifest`, and rejects malformed wrappers, mismatched run IDs, non-integer schema versions, unknown fields, missing fields, and non-mapping manifest payloads.

`PipelineRunner` now duck-types composed configs through `resolved`, `redacted`, `manifest`, `provenance`, and `recipe_manifest` attributes without importing `loom.config`. For composed configs it writes the composition manifest, recipe manifest, and provenance metadata only; plain mapping configs still use the conservative legacy snapshot path because they are caller-provided runtime data.

New or changed tests cover store protocol/API shape, import boundaries, local-store wrapper read/write validation, composed-config runner persistence, no default resolved snapshot files for composed-config runs, e2e local pipeline behavior, and explicit runtime fingerprint inputs through `StageSpec.fingerprint_fields`, `FingerprintContext.extra`, and caller-supplied `Fingerprintable.fingerprint()` values.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default harness passed with 447 passed and 11 skipped; config-extra harness passed with 362 passed and 454 deselected; `uv build` produced sdist and wheel. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; overall 816 passed, 0 failed, 0 errors, 9 skipped, 454 deselected. |
| GitHub checks | Pending | PR opened from `codex/v1-post-pipeline-persistence` to `develop`; remote checks run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 38 | 0 | 0 | 1 | 0 | 3.80s |
| unit | passed | 364 | 0 | 0 | 1 | 0 | 3.91s |
| contract | passed | 36 | 0 | 0 | 2 | 0 | 1.41s |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 1.76s |
| e2e | passed | 7 | 0 | 0 | 0 | 0 | 3.69s |
| config-extra | passed | 362 | 0 | 0 | 0 | 454 | 10.17s |

## Risks / Follow-Ups

- Plain mapping configs still write legacy `resolved` and `resolved_redacted` snapshots because they are caller-provided runtime mappings; a neutral v2 snapshot policy remains future work.
- Runtime object fingerprinting remains explicit and caller-managed. Automatic object discovery, runtime replay, remote stores, CLI inspection, `_copy_`, and Phase 6 recipe residual-risk coverage are intentionally out of scope.
