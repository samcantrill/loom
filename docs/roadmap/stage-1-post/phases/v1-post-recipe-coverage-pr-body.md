## Summary

@samcantrill

This phase hardens the residual recipe and include coverage left after the v1-post artifact-safety work. It records the accepted v1 debt that trusted Python recipes can still branch on unresolved resolver text, while adding public assertions that authored resolver expressions remain artifact-safe in recipe manifests, provenance metadata, composition manifests, and fingerprint records.

The implementation also covers explicit `../shared/foo.yaml` include escapes, exact non-secret sibling local-customization payloads, recipe fingerprint mismatch facts, and the v1-post package policy that no console script entry point is exposed. Product code and recipe semantics are unchanged.

## Acceptance Criteria

- [x] Record opaque recipe branching on unresolved resolver text as accepted debt without adding sandboxing or new recipe semantics.
- [x] Add public recipe artifact-safety and fingerprint coverage for authored resolver arguments and recipe output facts.
- [x] Add public provenance/manifest coverage for explicit relative include escapes and exact sibling local-customization path/kind/value payloads.
- [x] Guard that v1-post remains Python-API-only with no console script entry point.

## Implementation Notes

- `docs/roadmap/stage-1-post/implementation-plan.md` now records the accepted residual recipe-branching debt and revisit trigger.
- Recipe tests assert authored resolver expressions are preserved across public artifact surfaces and stay independent of resolved environment values.
- Fingerprint coverage now checks public recipe manifest metadata and mismatch comparison facts, not only the top-level digest.
- Provenance coverage now exercises an explicit sibling include escape and validates include-site facts, target kind, explicit-escape metadata, and safe local customization payloads in both provenance and manifest records.
- Package metadata coverage asserts `pyproject.toml` does not expose project scripts or GUI scripts.

New tests implemented:

- `tests/integration/config/test_compose_recipes.py`
- `tests/integration/config/test_compose_config.py`
- `tests/integration/config/test_compose_provenance.py`
- `tests/package/test_import.py`

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default harness passed with 448 passed, 11 skipped; config-extra harness passed with 363 passed, 455 deselected; `uv build` succeeded. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; overall 818 passed, 9 skipped, 455 deselected in 24.50s. |
| GitHub checks | Passed | CI workflow `checks` completed successfully on PR #55. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 39 | 0 | 0 | 1 | 0 | 3.85s | 20% |
| unit | passed | 364 | 0 | 0 | 1 | 0 | 3.90s | 53% |
| contract | passed | 36 | 0 | 0 | 2 | 0 | 1.43s | 28% |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 1.72s | 39% |
| e2e | passed | 7 | 0 | 0 | 0 | 0 | 3.55s | 67% |
| config-extra | passed | 363 | 0 | 0 | 0 | 455 | 10.05s | 78% |
| Overall | passed | 818 | 0 | 0 | 9 | 455 | 24.50s | - |

## Risks / Follow-Ups

- Accepted debt: v1-post still does not prove arbitrary trusted Python recipe internals avoided branching on unresolved resolver text. Revisit if users need deterministic recipe shape certification, sandboxed recipe execution, or reproducibility guarantees for unreviewed third-party recipes.
- GitHub CI passed on PR #55.
