## Summary

@samcantrill

This implements Stage 24 Phase 2 scoped overlay composition for `weave` argv config shorthand. It keeps the public compose and inspection APIs unchanged while adding private composition plumbing that can apply already-resolved argv scoped overlays at non-root config scopes.

Scoped overlays now load as overlay-family sources, apply after file include expansion and before recipe expansion, participate in source maps/provenance/manifests/raw snapshots/fingerprint facts, and support update/add validation plus recursive merge semantics including `_replace_: true`.

## Acceptance Criteria

- [x] Apply argv scoped overlays at the confirmed post-include, pre-recipe insertion point without changing public non-argv compose or inspection behavior.
- [x] Preserve auditability through overlay-family source metadata, final value authorship, provenance/manifest metadata, raw snapshot references, and artifact-safe fingerprint facts.
- [x] Cover scoped overlay merge order, target validation, inspection staging, artifact contracts, and non-argv regression behavior with package-local tests.

## Implementation Notes

- Added private scoped-overlay composition inputs in `weave.compose`; `compose_config(...)` and `inspect_config_composition(...)` signatures remain unchanged.
- Extended source-map merge support so resolved argv overlays can update or add nested mapping targets with structured validation and existing recursive merge behavior.
- Added internal argv inspection-stage support for `argv_scoped_overlays`, including the zero-overlay private argv path, while preserving the public non-argv inspection stage tuple.
- Kept scoped overlay audit data as metadata on existing `kind="overlay"` source artifacts; no new artifact kind or manifest schema version was introduced.
- Ensured non-argv golden artifacts do not receive empty scoped-overlay metadata.

New tests implemented:

- Integration coverage for `data/=...`, `model/=...`, nested scoped overlays, `+scope/=...`, `_replace_: true`, value override precedence, raw snapshots, and structured target errors.
- Contract coverage for artifact metadata, manifest/source facts, fingerprint changes, and argv-only inspection stage ordering.
- Regression coverage that direct non-argv inspection output and artifact metadata remain unchanged.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff and Pyright passed for repo and weave package; builds passed; pytest groups passed: default `1982 passed, 108 deselected`, config-extra `128 passed, 3 skipped, 1985 deselected`, weave `404 passed`, weave-examples `8 passed`. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; overall `2522 passed, 0 failed, 0 errors, 3 skipped, 2087 deselected, 2525 total` in `313.90s`. |
| GitHub checks | Pending | PR opened for CI; no GitHub check result was available at PR creation time. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 112 | 0 | 0 | 0 | 4 | 112 |
| unit | passed | 1402 | 0 | 0 | 0 | 2 | 1402 |
| contract | passed | 252 | 0 | 0 | 0 | 8 | 252 |
| integration | passed | 170 | 0 | 0 | 0 | 82 | 170 |
| e2e | passed | 46 | 0 | 0 | 0 | 6 | 46 |
| config-extra | passed | 128 | 0 | 0 | 3 | 1985 | 131 |
| weave | passed | 404 | 0 | 0 | 0 | 0 | 404 |
| weave-examples | passed | 8 | 0 | 0 | 0 | 0 | 8 |
| Overall | passed | 2522 | 0 | 0 | 3 | 2087 | 2525 |

## Risks / Follow-Ups

- Public argv compose/inspection helpers, warning UX, API exports, and feature docs remain Phase 3 scope.
- Scoped overlay facts remain metadata on overlay-family artifacts; revisit only if future consumers need a schema-versioned source kind.
