## Summary

@samcantrill

This PR populates Phase 13's artifact-safe configuration records: source metadata/hash records, composition manifest references, provenance metadata, redaction/security facts, and the default unresolved/redacted artifact views. The config API remains persistence-free and keeps runtime-resolved interpolation values in memory only.

The refinement and user-authorized pre-submit blocker pass narrowed default `fingerprint_records` to a single unresolved artifact-safe record, keeps user include source artifact references aligned after include replacements/additions, and redacts raw plaintext secret override strings plus nested secret-like JSON values in artifact metadata and warning facts while continuing to accept those overrides.

## Acceptance Criteria

- [x] Manifest records artifact-safe source, include, override, recipe, resolver, redaction, and security facts needed by later resume and CLI inspection work.
- [x] Manifest references populated default source metadata/hash records for base, overlay, include, and safe recipe sources.
- [x] User include replacements and brand-new include additions produce source artifact records and manifest references for the effective include files.
- [x] Default artifact records exclude raw source bytes and resolved runtime values; resolver expressions remain authored strings in unresolved/redacted artifacts.
- [x] Redaction runs before artifact serialization for sensitive authored paths, including raw override strings, nested secret-like override values, and warning facts.

## Implementation Notes

`src/loom/config/compose.py` now builds source artifacts from existing base/overlay source metadata, include-site records, and safe recipe manifest expansion facts, then threads those records into `ComposedConfig`, `ConfigCompositionInspection`, `CompositionManifest`, and provenance metadata. Inspection stages keep the established ordering and receive additive artifact count/reference payloads.

Redaction now targets the unresolved artifact-safe config before interpolation output is serialized. `src/loom/config/redaction.py` exposes the shared marker, key matcher, and policy metadata so compose/provenance records use the same default key-pattern policy as the redacted artifact view.

Include records now carry included-file digest/size and replacement-marker facts so include source artifacts and provenance can describe both the authored include site and the included source without persisting raw bytes. User include recomposition now contributes effective include records for replacement and brand-new include overrides so source artifact references do not retain the replaced include file or omit the added include file. Plaintext secret override guidance was added to `docs/features/config.md`; these overrides remain accepted, but artifact metadata records redacted warning facts.

New tests implemented:

- Contract coverage for populated inspection manifest/source/fingerprint records.
- Unit coverage for staged compose output staying in sync with inspection artifacts.
- Integration coverage for base/overlay/include source artifacts, safe recipe source records, resolver-expression preservation, redacted secret-like overrides, provenance security facts, and absence of runtime/secret values from serialized artifact payloads.
- Integration coverage for user include replacement source artifact references, brand-new user include addition references, and nested JSON secret override redaction across serialized provenance, manifest metadata, provenance metadata, warning facts, and redacted artifacts.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted Phase 13 suite | Passed | 100 passed across package/import-boundary, unit config artifact/provenance/redaction/compose, contract artifact/inspection, and config integration provenance suites |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff passed; Pyright 0 errors; default pytest 427 passed/10 skipped; config-extra 279 passed/432 deselected; build succeeded |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | Wrote `build/test-summary.md` with overall status passed |
| GitHub checks | Not run | PR not opened in this expanded-path draft pass |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 36 | 0 | 0 | 1 | 0 | 37 | 3.62s | 22% |
| unit | passed | 354 | 0 | 0 | 1 | 0 | 355 | 3.69s | 58% |
| contract | passed | 28 | 0 | 0 | 2 | 0 | 30 | 1.44s | 28% |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 1.87s | 42% |
| e2e | passed | 5 | 0 | 0 | 0 | 0 | 5 | 3.40s | 64% |
| config-extra | passed | 279 | 0 | 0 | 0 | 432 | 279 | 8.13s | 76% |
| Overall | passed | 711 | 0 | 0 | 9 | 432 | 720 | 22.15s | - |

## Risks / Follow-Ups

- Phase 14 still owns final artifact-safe fingerprint comparison and resume behavior; this PR only supplies the default unresolved fingerprint record and source facts.
- Phase 15 still owns raw source snapshot opt-in and dedupe policy; default source artifacts remain metadata/hash-only.
- Recipe source artifact records are limited to safe manifest expansion facts and avoid project-code source introspection.
- E2E artifact persistence remains deferred per plan; the existing harness e2e suite passed through `make test-summary`.
