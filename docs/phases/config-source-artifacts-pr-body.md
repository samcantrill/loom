## Summary

@samcantrill

This PR adds the Phase 15 raw source snapshot opt-in for configuration composition. The default path remains metadata/hash-only and artifact-safe, while callers can explicitly request a caller-owned raw snapshot bundle from the Python API for supported local/file base, overlay, and include sources.

It also hardens source artifact, manifest, provenance, and inspection metadata so reviewers and future callers can tell when raw snapshots are disabled, available, or unavailable without embedding raw content in persisted artifact contracts.

## Acceptance Criteria

- [x] Default source metadata/hash records remain backward-compatible and do not include raw source content.
- [x] Opt-in raw snapshots can reconstruct supported local/file authored sources from returned caller-owned payloads.
- [x] Duplicate raw payloads are deduped by digest plus size while preserving one reference per source.
- [x] Recipe source artifacts stay metadata-only with an explicit unsupported-source reason.
- [x] No Phase 16 documentation/e2e broadening, storage/run-store persistence, CLI behavior, pipeline integration, remote/plugin sources, or default raw-byte persistence is included.

## Implementation Notes

- Added keyword-only `include_raw_source_snapshots: bool = False` to `compose_config(...)`, `inspect_config_composition(...)`, and `compose_config_with_catalog(...)`, with explicit bool validation that preserves existing positional calls.
- Added plain-data `RawSourceSnapshotBundle`, `RawSourceSnapshotPayload`, and `RawSourceSnapshotReference` contracts and public config exports for caller-owned opt-in data.
- Threaded raw source capture through config load/include composition only when opted in, reusing UTF-8 source text from supported local/file reads and keeping `loom.config` persistence-free.
- Added deduped payload construction keyed by content digest and size, plus per-source availability references using `disabled`, `available`, and `unavailable` states.
- Added metadata-only raw snapshot limitation facts to source artifacts, manifest/provenance metadata, and inspection stages without adding raw content to manifests, source records, provenance records, or default fingerprints.

New tests implemented:

- Package/API tests cover keyword-only signatures, non-bool validation, config exports, and import-boundary expectations.
- Unit and contract tests cover raw snapshot helper serialization, disabled/default references, deduped opt-in payloads, recipe unavailability, source artifact limitation metadata, and inspection contract shape.
- Integration tests cover default metadata-only behavior, opt-in reconstructability for local/file sources, recipe metadata-only behavior, and default fingerprint exclusion of raw payloads.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted Phase 15 suite | Passed | 77 tests passed across package/import-boundary, unit artifact/compose/fingerprint, contract artifact/inspection, and integration provenance/fingerprint/source-snapshot coverage. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff, Pyright, default pytest `429 passed, 10 skipped`, config-extra `300 passed, 434 deselected`, and build succeeded. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | Wrote `build/test-summary.md` with all suites passing. |
| GitHub checks | Pending | PR opening and GitHub check collection are intentionally deferred to the expanded-path PR-body refine pass. |

### Test Suite Summary

| Suite | Status | Passed | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: |
| package | passed | 36 | 1 | 0 |
| unit | passed | 354 | 1 | 0 |
| contract | passed | 30 | 2 | 0 |
| integration | passed | 9 | 5 | 0 |
| e2e | passed | 5 | 0 | 0 |
| config-extra | passed | 300 | 0 | 434 |
| Overall | passed | 734 | 9 | 434 |

## Risks / Follow-Ups

- Raw snapshot payloads remain caller-owned return data only; future run-store work must define persistence, protection, and restore policy.
- Snapshot reconstruction is intentionally limited to supported local/file UTF-8 authored config sources.
- Recipe source artifacts remain metadata-only until a future recipe provenance phase defines safe raw source ownership.
