## Summary

This PR establishes the Phase 1 persistence and concurrency contract surface for v9. It adds backend-neutral per-run authority, capability, schema-policy, read-model, and workspace coordination contracts under `loom.pipeline.stores`, while keeping the existing local-file `RunStore` and `LocalRunStore` as the current legacy store surface.

The phase is contract-only: it adds deterministic in-memory conformance fakes, package/unit/contract coverage, and docs for the new authority boundaries. It does not implement a SQLite backend, runner write-path swap, backend CLI, parallel scheduler, sweep runner, migration path, or legacy local-file fallback.

## Acceptance Criteria

- [x] Per-run contracts express create/open, guarded transitions, attempt allocation, leases, submitted operations, output commits, artifact facts, revisions, schema checks, snapshots, and recovery scans.
- [x] Read-model records include coarse run/stage statuses plus attempts, leases, submitted operations, commits, artifact facts, materialized refs, revision evidence, schema version, static outcomes, cleanup candidates, recovery facts, and warnings.
- [x] Workspace coordination contracts are limited to cross-run identity, trial references, trial/resource leases, counters, `run_uri` references, and recovery scans.
- [x] Capability and schema failures are machine-readable and suitable for loud API/CLI diagnostics.
- [x] `RunStatus` and `StageStatus` remain coarse; transient lifecycle detail stays in structured records and snapshots.
- [x] Store imports stay independent of CLI, `loom.runs`, project code, optional backends, and SQLite.

## Implementation Notes

- Added `PerRunAuthorityStore` plus transition, attempt-allocation, and output-commit result records in `src/loom/pipeline/stores/authority.py`.
- Added backend capability declarations, unsupported-capability diagnostics, and loud schema-version checks in `capabilities.py` and `schema_policy.py`.
- Added authoritative read-model value records for revisions, attempts, leases, commits, artifact facts, materialized refs, cleanup, recovery, static outcomes, lifecycle reasons, warnings, and snapshots in `read_models.py`, with round-trip `from_dict` coverage for exported contract records.
- Added `WorkspaceCoordinationStore` and cross-run workspace/sweep records in `coordination.py`, including first-class trial lease and coordination recovery records that carry workspace/sweep/trial/resource identity while deliberately excluding per-stage lifecycle mutation.
- Kept the public store facade import-light with explicit exports, and updated store/state/sweep/source-tree docs to describe the v9 authority boundary without exposing SQLite details.

New tests implemented:

- Package tests for public store exports, contract method presence, and forbidden import boundaries.
- Unit tests for capability results, schema loud-fail policy, read-model and coordination record round trips, static outcome validation, and store error exports.
- Contract tests for in-memory per-run authority behavior and workspace coordination behavior, including lease fencing, revisioned snapshots, submitted operations, output commits, recovery scans, cross-run lease identity, and cross-run-only coordination.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and `uv build` passed during blocker-resolution pass 1/3. |
| `make test-summary` | Passed | Regenerated `build/test-summary.md` during blocker-resolution pass 1/3 with overall status `passed`. |
| GitHub checks | Pending | PR is opened after local validation; CI polling is owned by the managing agent. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 56 | 0 | 0 | 1 | 0 | 7.66s |
| unit | passed | 766 | 0 | 0 | 1 | 0 | 16.33s |
| contract | passed | 83 | 0 | 0 | 2 | 0 | 4.06s |
| integration | passed | 64 | 0 | 0 | 7 | 10 | 52.93s |
| e2e | passed | 37 | 0 | 0 | 0 | 1 | 15.68s |
| config-extra | passed | 416 | 0 | 0 | 0 | 1009 | 32.46s |
| Overall | passed | 1422 | 0 | 0 | 11 | 1020 | 129.12s |

## Risks / Follow-Ups

- The contract surface is intentionally broader than the current runner uses; Phase 2 must prove the SQLite backend can implement the semantics without changing public contract names or leaking schema details.
- In-memory conformance fakes validate protocol behavior but cannot prove real SQLite transaction, locking, or clock semantics.
- Read models are internal compatibility surfaces for later status, catalog, diagnostics, and bundle/export work; they are not a user-facing snapshot/export workflow in this phase.
