## Summary

@samcantrill

This PR closes the v1 configuration-composition hardening phase. It aligns the
config, provenance, fingerprint, resume, and testing feature docs with the
accepted v1 contract: Python API composition, artifact-safe records by default,
explicit raw-source snapshot opt-in, `_copy_` rejection, and no config-owned
pipeline, CLI, run-store, plugin, remote, sweep, or persistence behavior.

It also adds one representative public-Python e2e flow for strict composition
and fixes a focused `CompositionManifest.to_dict()` serialization bug so nested
recipe-manifest mappings remain round-trippable plain data.

## Acceptance Criteria

- [x] Feature docs describe supported v1 behavior without promising `_copy_`,
  default raw source bytes, default resolved-config persistence, CLI behavior,
  or pipeline dependence on config artifacts.
- [x] Public-Python e2e coverage exercises base/overlay composition, nested
  includes, user include replacement, strict/update and `+` add overrides,
  recipes, resolver expressions, redaction, source metadata, fingerprints, and
  raw-source snapshot default/opt-in behavior.
- [x] Product changes are limited to the accepted v1 artifact contract bug fix
  for nested recipe-manifest serialization.
- [x] No future CLI, plugin, remote, sweep, `_copy_`, run-store persistence, or
  pipeline dependency scope is introduced.

## Implementation Notes

- Updated `docs/features/config.md`, `docs/features/provenance.md`,
  `docs/features/fingerprints.md`, `docs/features/resume.md`, and
  `docs/features/testing.md` to distinguish current v1 behavior from future
  roadmap material.
- Kept `loom.config` persistence-free and Python-API-only in the docs: it
  returns composed config artifacts to callers, while future runners/run stores
  own any file persistence.
- Fixed `to_plain_mapping()` in `src/loom/config/artifacts.py` to thaw nested
  plain-data values instead of rejecting frozen nested recipe-manifest mappings.

New tests implemented:

- Added `tests/e2e/test_config_composition_public_api.py` for a domain-neutral
  end-to-end config composition flow through `inspect_config_composition()` and
  `compose_config()`.
- Extended `tests/contracts/test_config_artifact_contract.py` to cover nested
  recipe-manifest plain-data round trips and renamed fixture paths from
  `pipeline` to `workflow`.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted e2e/contract regression | Passed | `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/contracts/test_config_artifact_contract.py tests/e2e/test_config_composition_public_api.py`: 10 passed |
| `make validate-pr` | Passed | Ruff passed, Pyright passed, default suite 430 passed/11 skipped, config-extra 301 passed/436 deselected, build succeeded |
| `make test-summary` | Passed | Wrote `build/test-summary.md` with all suites passing |
| Focused confirmation after final docs-only blocker fix | Passed | `git diff --check`; focused text scans confirmed the `Persist both:` wording was removed and the `Expose both:`, `resolved:`, and `redacted:` wording remains |
| GitHub checks | Pending | CI will run after PR creation |

### Test Suite Summary

| Suite | Result | Evidence |
| --- | --- | --- |
| package | Passed | 36 passed/1 skipped |
| unit | Passed | 354 passed/1 skipped |
| contract | Passed | 31 passed/2 skipped |
| integration | Passed | 9 passed/5 skipped |
| e2e | Passed | 6 passed |
| config-extra | Passed | 301 passed/436 deselected |

## Risks / Follow-Ups

- Future CLI, plugin/remote resolver, sweep, `_copy_`, and run-store persistence
  work remains deferred to later roadmap phases.
- The final blocker-resolution commit is docs-only and was confirmed with
  focused text checks rather than a full validation rerun; the full validation
  evidence above is from the same branch immediately before that wording fix.
