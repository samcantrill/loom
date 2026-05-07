## Summary

This PR establishes the Phase 1 runtime package boundary for v4 runtime options by converting `loom.pipeline.runtime` from a single module into an import-light package facade. Existing public imports remain stable through both `loom.pipeline.runtime` and `loom.pipeline`, including `RuntimeKind`, `RuntimeRequest`, `parse_runtime_request`, and `RUNTIME_SCHEMA_VERSION`.

The implementation preserves current runtime/resource behavior and serialization while documenting the package ownership and future executor descriptor import direction in `docs/structure.md`. It does not introduce `RunOptions`, typed resource entries, profiles, environment models, descriptor behavior, registries, preflight wiring, CLI/config runtime mapping, `runtime.json`, or runner request rewiring.

## Acceptance Criteria

- [x] Public runtime imports remain stable and cheap after the package split.
- [x] Existing runtime/resource behavior and tests remain unchanged.
- [x] `docs/structure.md` describes the runtime package boundary and import direction.
- [x] Runtime package imports do not load CLI, diagnostics, executor implementations, plugins, project packages, or optional backends.

## Implementation Notes

`src/loom/pipeline/runtime/__init__.py` is now the public facade with explicit `__all__` exports. The existing runtime request implementation moved to the private leaf `src/loom/pipeline/runtime/_models.py`, with imports adjusted to keep the package facade compatible and lightweight.

`docs/structure.md` now shows `pipeline/runtime/` as the runtime model package boundary and records that future executor descriptor records belong on the import-light metadata side of the boundary. The documentation uses future-boundary language only; descriptor records and behavior remain out of scope for this phase.

New tests implemented:

- Package import-boundary coverage for `loom.pipeline.runtime` public exports, package-level re-exports, and forbidden layer imports in a fresh interpreter.
- Unit import-path compatibility coverage for `RuntimeKind`, `RuntimeRequest`, and `parse_runtime_request`.
- Existing runtime resource behavior, serialization, integration, e2e, and config-extra suites were rerun through the final validation gates.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `git diff --check develop...HEAD` | Passed | Reran during PR-body draft; no whitespace errors. |
| `make validate-pr` | Passed | Recorded phase evidence: Ruff, Pyright, default harness, config-extra harness, and `uv build` passed. |
| `make test-summary` | Passed | Generated `build/test-summary.md` on 2026-05-07 with all suites passing. |
| GitHub checks | Pending | PR creation is deferred to the expanded-path PR-body refine pass. |

### Test Suite Summary

| Suite | Status | Evidence |
| --- | --- | --- |
| package | Passed | 49 passed, 1 skipped in 4.98s. |
| unit | Passed | 453 passed, 1 skipped in 5.14s. |
| contract | Passed | 41 passed, 2 skipped in 1.56s. |
| integration | Passed | 9 passed, 6 skipped, 12 deselected in 1.90s. |
| e2e | Passed | 15 passed in 6.12s. |
| config-extra | Passed | 396 passed, 567 deselected in 15.26s. |
| Overall | Passed | 963 passed, 10 skipped, 579 deselected in 34.96s. |

## Risks / Follow-Ups

- The runtime package is intentionally minimal until later phases add real runtime options, profiles, environment, validation, registry, descriptor, and serialization behavior.
- The executor descriptor boundary is documentation-only in this phase; concrete descriptor records and capability checks remain later-phase work.
- Callers that reached into private implementation files should use the stable `loom.pipeline.runtime` facade instead.
