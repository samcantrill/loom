## Summary

Implements Stage 15 Phase 2 artifact-store backend contracts. The phase adds
store-owned descriptor/factory/handler protocols, operation capability records,
structured backend diagnostics/results, backend-kind normalization, and a
programmatic registry keyed by backend kind.

It also adds an explicit lazy
`load_artifact_store_backend_entry_points(...)` plugin adapter that uses Stage
14 generic entry-point loading into a caller-supplied registry. Generic plugin
readiness remains listing-only for artifact-store backend groups and does not
claim backend availability or run-readiness.

## Acceptance Criteria

- [x] Programmatic backend registration works without plugins and reports
  deterministic duplicate, missing, and incompatible-version diagnostics.
- [x] Artifact-store capability records support `supported`, `unsupported`, and
  `unknown` states for read/write/list/delete/checksum/commit/consistency/
  lookup/publish/materialize operations.
- [x] Fake tracking-style and object-store-style descriptors/handlers exercise
  the public contract without real SDKs, network probes, credentials, or
  payload movement.
- [x] The specialized plugin adapter is supplied-registry-based and does not
  change Stage 14 generic readiness semantics.

## Implementation Notes

- New public store contracts live in
  `loom.pipeline.stores.artifact_backends` and are re-exported from
  `loom.pipeline.stores`.
- The registry accepts factories and descriptors that carry a factory object;
  descriptor serialization omits the factory.
- Capability admission fails closed through structured unsupported/unknown
  operation results.
- `loom.plugins.artifact_backends` is lazy-exported from `loom.plugins`; store
  modules do not import plugin discovery.

New tests cover registry behavior, capability serialization/admission, plugin
adapter registration, package exports/import boundaries, and tracking/object
store contract fixtures.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted Phase 2 pytest | Passed | 76 passed |
| Broad Phase 2 pytest | Passed | 522 passed, 3 skipped |
| `make validate-pr` | Passed | Ruff passed; Pyright 0 errors; default harness 1634 passed / 26 skipped / 18 deselected; config-extra 440 passed / 1671 deselected; build succeeded |
| `make test-summary` | Passed | Overall 2102 passed / 18 skipped / 1687 deselected |
| GitHub checks | Passed | CI `checks` job passed in 2m54s on PR #161 |

### Test Suite Summary

| Suite | Status | Passed | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: |
| package | passed | 90 | 1 | 0 |
| unit | passed | 1151 | 7 | 1 |
| contract | passed | 222 | 2 | 0 |
| integration | passed | 156 | 8 | 13 |
| e2e | passed | 43 | 0 | 2 |
| config-extra | passed | 440 | 0 | 1671 |

## Risks / Follow-Ups

- Descriptor-load success remains separate from configured backend readiness;
  later diagnostics phases must preserve that wording.
- Payload publish/materialize behavior is intentionally shaped as structured
  unsupported/unknown results for future Stage 16 work, not implemented here.
