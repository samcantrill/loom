## Summary

@samcantrill

This PR completes Phase 3 of the v1-post configuration plan by making strict config composition and instantiation diagnostics source-aware, path-aware, and serializable without changing the public error names callers already catch.

It adds metadata-only final-value authorship facts for base/overlay values, includes, local include customizations, recipe outputs, and ordinary overrides; uses those facts for resolver/interpolation diagnostics; and tightens redaction so secret-like override paths and values do not leak through errors, provenance, manifests, or fingerprint metadata.

## Acceptance Criteria

- [x] Ordinary overrides and composed final values carry safe authorship metadata.
- [x] Interpolation and unsupported resolver failures attribute to final authored value sources when known.
- [x] Merge, override, include, recipe, and target failures expose structured context through existing public error classes.
- [x] Include diagnostics include actionable remediation and active include-stack facts for nested failures.
- [x] Provenance, manifest, fingerprint, and serialized error surfaces avoid raw secret-like override strings and values.
- [x] Phase 4/5 work remains out of scope: no provenance schema-version-2, artifact-ordering, pipeline/store persistence, CLI, `_copy_`, resolver allow-list, or public hierarchy expansion.

## Implementation Notes

Final-value authorship is recorded under `source_fact_records.final_value_authorship` as path/fact records. Records include source kind, source path/order, composition stage, digest/size when available, and safe origin details such as include site, recipe path, or override operation/order. They do not store authored values.

Structured diagnostics now flow through existing error names by letting config error subclasses carry `ConfigErrorContext`. Merge and override failures include path, operation, directive, expected/actual facts, remediation, and redacted override details. Include resolution/expansion errors keep existing cycle behavior and now add remediation plus active include-stack details for nested non-cycle failures.

Resolver rejection uses final-value authorship for overlay- and override-authored values, with a structured `authorship_missing` fallback. Recipe expansion, target import, and target instantiation failures now preserve exception chaining while adding stage/path/directive context.

New tests implemented:

- Authorship metadata for overlay, include, ordinary override, and redacted secret override paths.
- Source-aware resolver errors for overlay- and override-authored values.
- Include-stack/remediation coverage for nested include resolution failures.
- Structured context contract coverage for existing public error names.
- Unit coverage for merge, override, recipe, target import, target instantiation, and fingerprint redaction paths.
- Public redaction matrix coverage for parent secret-like override paths, include local customizations, recipe arguments, provenance, manifests, fingerprints, and serialized errors.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default suite passed with 436 passed/11 skipped; config-extra passed with 346 passed/442 deselected; `uv build` produced sdist and wheel. |
| `make test-summary` | Passed | Wrote `build/test-summary.md` on 2026-05-06T02:43:20+00:00; overall 788 passed, 9 skipped, 442 deselected. |
| GitHub checks | Not run | PR was not opened in this expanded-path draft pass; checks are expected after the refine/open pass. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 38 | 0 | 0 | 1 | 0 | 39 | 4.89s | 20% |
| unit | passed | 357 | 0 | 0 | 1 | 0 | 358 | 4.23s | 53% |
| contract | passed | 32 | 0 | 0 | 2 | 0 | 34 | 1.57s | 28% |
| integration | passed | 9 | 0 | 0 | 5 | 0 | 14 | 1.85s | 39% |
| e2e | passed | 6 | 0 | 0 | 0 | 0 | 6 | 4.19s | 68% |
| config-extra | passed | 346 | 0 | 0 | 0 | 442 | 346 | 10.82s | 77% |
| Overall | passed | 788 | 0 | 0 | 9 | 442 | 797 | 27.56s | - |

## Risks / Follow-Ups

- Recipe authorship intentionally points to recipe block/manifest facts rather than trusted Python internals.
- Phase 4 still owns artifact-before-resolver ordering and provenance schema-version-2 writes.
- Phase 5 still owns run-store composition manifest persistence and default resolved-config persistence removal.
