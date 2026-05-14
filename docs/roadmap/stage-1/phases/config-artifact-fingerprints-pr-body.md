## Summary

@samcantrill

This PR implements Phase 14's artifact-safe default config fingerprint contract. The public composed-config fingerprint, inspection fingerprint, manifest fingerprint record, and fingerprint stage payload now derive from one `artifact_safe_config` record built from authored-composition facts rather than resolved runtime values.

It also adds a narrow config-layer comparison helper for persisted fingerprint records or manifest-shaped plain data. The helper reports authored-composition match, mismatch, incompatible policy/schema, or insufficient data without claiming exact runtime resolver replay.

The comparison surface treats valid wrong-label records or record-shaped mappings as `incompatible_policy`, while malformed plain mappings report `insufficient_data` without escaping validation errors.

## Acceptance Criteria

- [x] Default config fingerprints change for meaningful authored composition changes.
- [x] Default config fingerprints avoid machine-local absolute path prefixes when source content and authored composition are otherwise equivalent.
- [x] Resolver outputs, raw source bytes, runtime objects, and resolved environment values are excluded from default fingerprint inputs.
- [x] Authored-composition comparison distinguishes match/mismatch/incompatible/insufficient-data outcomes and records that runtime values were not replayed.
- [x] Phase 15 raw snapshot/source hardening and Phase 16 docs/e2e hardening remain out of scope.

## Implementation Notes

`src/loom/config/fingerprints.py` defines the artifact-safe fingerprint policy, default record builder, canonical payload builder, and `compare_config_artifact_fingerprints`. The payload uses Phase 13 source artifact records, include facts, redacted/unresolved config, resolver expressions as authored text, recipe manifest facts, redacted override facts, and policy/schema metadata.

`src/loom/config/compose.py` now wires that default record through `ComposedConfig.fingerprint`, `ConfigCompositionInspection.fingerprint`, `fingerprint_records`, `CompositionManifest.fingerprint_records`, and the `fingerprint` composition stage. The legacy resolved fingerprint remains compatibility provenance metadata only; it is not the public default fingerprint.

New tests implemented:

- Package/import-boundary coverage for the new config exports and optional dependency safety.
- Unit coverage for portable payload construction, redacted overrides, resolver facts, default record shape, and comparison outcomes.
- Contract coverage for `artifact_safe_config` fingerprint records and inspection/manifest agreement.
- Integration coverage for overlay changes, temp-root portability, resolver-output exclusion, authored resolver expression changes, and redacted secret override behavior.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff, Pyright, default isolated pytest, config-extra isolated pytest, and build passed after refinement. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | Wrote `build/test-summary.md`; suite table summarized below. |
| Focused comparison-helper unit check | Passed | `uv run --extra config pytest tests/unit/loom/config/test_config_fingerprints.py`: 5 passed. |
| Targeted default contract check | Passed | `uv run --isolated --locked --group dev pytest tests/contracts/test_config_artifact_contract.py`: 7 passed. |
| Targeted config-extra contract check | Passed | `uv run --extra config pytest tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_composition_inspection_contract.py`: 8 passed. |
| GitHub checks | Pending at submission | PR verification is recorded in the phase notes; CI had not completed when this body was prepared. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 36 | 0 | 0 | 1 | 0 |
| unit | passed | 354 | 0 | 0 | 1 | 0 |
| contract | passed | 29 | 0 | 0 | 2 | 0 |
| integration | passed | 9 | 0 | 0 | 5 | 0 |
| e2e | passed | 5 | 0 | 0 | 0 | 0 |
| config-extra | passed | 288 | 0 | 0 | 0 | 433 |

## Risks / Follow-Ups

- Authored-composition matches do not prove exact runtime resolver equality; runtime-value replay remains unavailable by default.
- Raw source snapshot opt-in, source artifact hardening, and rebuild-from-missing-source policy remain Phase 15 scope.
- Documentation/e2e hardening for full v1 behavior remains Phase 16 scope.
