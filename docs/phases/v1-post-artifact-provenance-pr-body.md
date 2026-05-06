## Summary

@samcantrill

This PR makes config composition artifacts artifact-safe by construction: source artifacts, unresolved/redacted config, provenance metadata, manifests, and fingerprint records are now built before runtime interpolation executes. Runtime-resolved values remain available through the in-memory `resolved` result, but they no longer influence default config artifacts, provenance-emitted digests, or `ComposedConfig.fingerprint`.

It also moves new `ConfigProvenance` writes to schema version 2 with a top-level `artifact_fingerprint` and no top-level `resolved_fingerprint`, while preserving legacy schema-version-1 reads by normalizing old resolved fingerprints into `metadata.legacy_resolved_fingerprint`.

## Acceptance Criteria

- [x] Artifact-safe records are constructed before runtime interpolation and preserve resolver expressions/paths.
- [x] New provenance writes use schema version 2 with `artifact_fingerprint` and omit top-level `resolved_fingerprint`.
- [x] Legacy schema-version-1 provenance reads remain supported without re-emitting `resolved_fingerprint`.
- [x] Environment resolver value changes do not affect default fingerprints, provenance metadata, manifests, or fingerprint records.
- [x] Config docs warn against plaintext secret overrides such as `+auth.token=plaintext-secret` and recommend `oc.env`.

## Implementation Notes

- `src/loom/config/compose.py` now builds redacted/unresolved artifact records, provenance, manifest metadata, artifact placeholders, and default fingerprint records before the runtime interpolation and validation stages.
- `src/loom/config/provenance.py` now treats schema version 2 as the write format, requires non-empty `artifact_fingerprint` for new writes, rejects unexpected schema-version-2 top-level fields, and keeps schema-version-1 compatibility for old `resolved_fingerprint` payloads.
- Provenance and manifest metadata now include artifact-safe fingerprint facts and explicitly record that resolved runtime fingerprints are not included.
- The diff stays inside config composition/provenance, config docs, phase docs, and config-focused tests. It does not add Phase 5 pipeline/run-store APIs, `PipelineRunner` persistence changes, or default resolved-config persistence changes.

New tests implemented:

- Unit and contract coverage for schema-version-2 provenance serialization, legacy schema-version-1 reads, and rejection of top-level `resolved_fingerprint` on schema-version-2 payloads.
- Integration coverage proving artifact/provenance/fingerprint construction occurs before runtime interpolation and remains stable when environment resolver values change.
- Recipe integration coverage proving env-backed recipe arguments keep recipe manifests and default artifacts runtime-value-free.
- Docs/example coverage for the plaintext secret override warning.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright passed; default harness passed with 439 passed, 11 skipped; config-extra harness passed with 360 passed, 445 deselected; `uv build` succeeded. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; overall 805 passed, 9 skipped, 445 deselected. |
| GitHub checks | Pending | PR opened for CI after local validation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 38 | 0 | 0 | 1 | 0 | 39 | 3.80s | 20% |
| unit | passed | 357 | 0 | 0 | 1 | 0 | 358 | 3.54s | 53% |
| contract | passed | 35 | 0 | 0 | 2 | 0 | 37 | 1.44s | 28% |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 1.75s | 38% |
| e2e | passed | 6 | 0 | 0 | 0 | 0 | 6 | 3.40s | 67% |
| config-extra | passed | 360 | 0 | 0 | 0 | 445 | 360 | 9.85s | 77% |
| Overall | passed | 805 | 0 | 0 | 9 | 445 | 814 | 23.77s | - |

## Risks / Follow-Ups

- Runtime-resolved fingerprint policy remains intentionally absent; a future policy should be explicit, opt-in, and separately labeled.
- Phase 5 still owns pipeline/run-store composition manifest persistence and default resolved-config persistence changes.
