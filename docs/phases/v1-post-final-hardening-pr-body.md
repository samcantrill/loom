## Summary

@samcantrill

This PR completes the v1-post final hardening sweep by aligning the public docs and implementation-plan metadata with the accepted Python-API-only configuration contract. The audit covers `docs/features/config.md`, `docs/features/provenance.md`, `docs/features/fingerprints.md`, `docs/features/pipeline.md`, and `docs/loom.md`, keeping future CLI, remote-store, sweep, and `_copy_` material explicitly future-scoped.

It also tightens representative e2e evidence for the composed-config runner path. Composed configs still return in-memory resolved data plus artifact-safe records, while pipeline persistence remains plain run-store data and does not write default resolved or resolved-redacted snapshots for composed configs.

## Acceptance Criteria

- [x] Audit current-behavior docs for stale resolved-persistence, CLI, `_copy_`, manifest, provenance, fingerprint, and security wording.
- [x] Preserve v1-post boundaries: no functional CLI, console script, `_copy_`, plugin/remote resolver, sweep, remote store, config persistence helper, or pipeline import of config classes.
- [x] Keep default composed-config artifacts security-first: no resolver outputs, raw source bytes, or default full resolved composed-config snapshots.
- [x] Update implementation-plan metadata, accepted debt, and v2 handoff notes after final validation evidence.
- [x] Rerun `make validate-pr` and `make test-summary` after the refinement commit.

## Implementation Notes

The docs now distinguish current v1-post composed-config persistence from future runner/CLI policy: `loom.config` is persistence-free, `loom.pipeline` persists plain `config/composition_manifest.json` and `config/recipe_manifest.json`, and current composed-config runs avoid default `config/resolved.yaml` and `config/resolved.redacted.yaml` snapshots. Future roadmap sections remain where useful, but they are labeled as future/non-v1 guidance.

`docs/implementation-plans/implementation-plan-v1-post.md` records Phase 7 completion evidence, accepted debt, and v2 handoff notes. The phase branch adds no product-code changes and no new product semantics.

New or changed tests:

- `tests/e2e/test_local_pipeline_run.py::test_local_pipeline_run_with_composed_config_persists_manifest_not_resolved_snapshots` now verifies the public composed-config object path persists a plain wrapped composition manifest, writes the recipe manifest, preserves authored resolver expressions, omits resolved resolver outputs and raw source snapshots from the persisted wrapper, and avoids default resolved snapshots.
- `tests/e2e/test_config_composition_public_api.py::test_public_python_config_composition_e2e` remains the public config-composition half of the representative e2e path for artifact-safe manifests, provenance, fingerprints, secret filtering, stable artifact fingerprints, and explicit raw-source opt-in.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default harness passed with 448 passed and 11 skipped; config-extra harness passed with 363 passed and 455 deselected; `uv build` succeeded. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; overall 818 passed, 0 failed, 0 errors, 9 skipped, 455 deselected in 28.67s. |
| GitHub checks | Pending | `gh pr checks 57` reports GitHub Actions `checks` pending after the latest push; no failing GitHub checks were reported. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 39 | 0 | 0 | 1 | 0 | 4.71s | 20% |
| unit | passed | 364 | 0 | 0 | 1 | 0 | 4.25s | 53% |
| contract | passed | 36 | 0 | 0 | 2 | 0 | 1.63s | 28% |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 1.87s | 39% |
| e2e | passed | 7 | 0 | 0 | 0 | 0 | 4.58s | 68% |
| config-extra | passed | 363 | 0 | 0 | 0 | 455 | 11.64s | 78% |
| Overall | passed | 818 | 0 | 0 | 9 | 455 | 28.67s | - |

## Risks / Follow-Ups

- Accepted debt: v1-post remains Python-API-only. Functional CLI commands, console scripts, remote stores, sweeps, plugin/remote resolvers, and `_copy_` remain future roadmap work.
- Accepted debt: plain mapping configs may still use legacy resolved snapshot names because they are caller-provided runtime data, not composed-config artifact persistence.
- Accepted debt: exact runtime resolver replay and arbitrary trusted-Python recipe-branching certification remain deferred to explicit future design work.
