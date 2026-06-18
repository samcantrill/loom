## Summary

This PR hard-swaps Loom's runtime resource schema from fixed `cpus`, `memory_mb`, `gpus`, and `custom` fields to typed resource entries. The public resource model is now `ResourceRequest(entries={...})` with immutable `ResourceEntry(kind, amount, unit, attributes)` leaves, schema-versioned serialization, canonical authored `resources.entries` syntax, and explicit old-field rejection.

The change keeps resource validation domain-neutral and separate from future executor capability checks. It adds deterministic validator registry composition, built-in `cpu`, `memory`, and `gpu` validators, stage/runtime integration, public exports, migrated docs/examples, and tests while leaving `RunOptions`, profiles, descriptors/capabilities, preflight wiring, CLI/config runtime mapping, `runtime.json`, and runner rewiring out of scope.

## Acceptance Criteria

- [x] Public imports expose `ResourceEntry`, entry-based `ResourceRequest`, and `parse_resource_request`.
- [x] Authored stage resources accept only canonical `resources.entries` syntax and reject old or noncanonical shapes.
- [x] Entry mapping keys must match `ResourceEntry.kind`; resource-kind syntax is lowercase ASCII identifier segments separated by dots.
- [x] Built-in `cpu`, `memory`, and `gpu` validators enforce amount, unit, and empty-attribute semantics.
- [x] Validator registry composition is explicit and deterministic, with duplicate-kind rejection, custom registry isolation, and unregistered-kind failures.
- [x] `StageSpec.resource_request` and `RuntimeRequest.resources` parse and serialize the entry-based schema.
- [x] Resource changes remain excluded from semantic fingerprints.
- [x] Docs, canonical examples, and tests are migrated away from the old resource field schema.

## Implementation Notes

- Replaced `src/loom/pipeline/resources.py` with the entry-based schema, `RESOURCE_SCHEMA_VERSION = 2`, `ResourceValidatorRegistry`, built-in validators, schema-versioned `ResourceRequest.to_dict()` / `from_dict()`, and authored `parse_resource_request()` handling.
- Kept `StageSpec.resources` as frozen plain data while validating through `parse_resource_request()` and returning typed requests through `StageSpec.resource_request`.
- Preserved `RuntimeRequest` as the runtime envelope and updated nested resource serialization/deserialization to require entry-based `ResourceRequest` documents.
- Re-exported `ResourceEntry` from the public pipeline facade and migrated runtime resource docs, related feature docs, and the local-run example to entry syntax.

New tests implemented:

- Resource entry immutability, plain-data attributes, serialization, schema versioning, kind syntax, key/kind matching, built-in validator semantics, old-field rejection, and explicit registry composition behavior.
- Stage and runtime integration for entry-based resources, including authored config shape validation and nested `RuntimeRequest` round trips.
- Public API export coverage and semantic fingerprint coverage confirming resources remain non-semantic.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Reran during PR-body refine/open on 2026-05-07: Ruff, Pyright, default harness, config-extra harness, and build passed. |
| `make test-summary` | Passed | Reran during PR-body refine/open on 2026-05-07; wrote `build/test-summary.md` with overall status `passed`. |
| GitHub checks | Pending | GitHub checks run after the PR is opened. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 49 | 0 | 0 | 1 | 0 | 5.02s |
| unit | passed | 495 | 0 | 0 | 1 | 0 | 5.27s |
| contract | passed | 41 | 0 | 0 | 2 | 0 | 1.49s |
| integration | passed | 9 | 0 | 0 | 6 | 12 | 2.02s |
| e2e | passed | 15 | 0 | 0 | 0 | 0 | 5.72s |
| config-extra | passed | 396 | 0 | 0 | 0 | 609 | 15.47s |
| Overall | passed | 1005 | 0 | 0 | 10 | 621 | 35.00s |

## Risks / Follow-Ups

- This is an intentional breaking v4 resource schema change; downstream configs using old resource fields must migrate to `resources.entries`.
- Plugin or adapter-supplied resource validators are not discovered automatically yet; callers must compose explicit registries until later plugin/runtime phases add discovery.
- Executor capability checks, runtime profiles, CLI/config runtime mapping, and persisted `runtime.json` metadata remain future-phase work.
