## Summary

- Adds strict v10 offline evidence import into the authority service through one repository-owned transaction.
- Introduces manifest validation and rejection diagnostics for schema/source completeness, terminal state, stage/output consistency, event ordering, and collision handling.
- Wires the import flow through FastAPI mutation routes, the authority client, and `loom authority import-offline`, and surfaces imported provenance in authoritative read/status output.

## Implementation Notes

- `src/loom/authority/offline_import.py` owns the import-specific validation and result/rejection models so CLI and transport adapters stay repository-free.
- `AuthorityRepository.import_offline_evidence_manifest(...)` rejects existing run URIs before mutation, writes authoritative run/stage/attempt/output/artifact facts inside one SQLite transaction, records `authority_import` provenance on the run snapshot, and preserves replay-level offline history as `offline_import.*` audit events.
- Replay validation now parses full `PipelineEventRecord` payloads and preserves original run/stage scope when storing replay audit records.
- The client/CLI path stays on the public authority protocol boundary. The CLI sends an explicit `imported_by` marker and renders compact JSON/text result payloads from `AuthorityProtocolResult.body`.
- Imported runs remain terminal authority facts with provenance metadata; Phase 18 does not copy payload bytes, repair incomplete evidence, import legacy directories, or replace/fork collisions.

New tests implemented:

- Unit coverage for accepted import, validation rejections, collision rejection, replay event validation, and rollback on mid-transaction failure.
- Contract coverage for `offline_import` protocol vocabulary, request/response/result shapes, and new public export expectations.
- Integration and e2e coverage for import through the authority API and `loom authority import-offline`, plus authoritative snapshot/provenance readback.

## Tests And Validation

| Command | Result | Evidence |
| --- | --- | --- |
| Focused Ruff/Pyright/Pytest | Passed | Changed implementation/tests passed targeted Ruff, Pyright, and focused import/package/integration coverage during development. |
| `make validate-pr` | Passed | Ruff, Pyright, default `1348 passed, 19 skipped, 14 deselected`, config-extra `424 passed, 1378 deselected`, and build succeeded. |
| `make test-summary` | Passed | Suite table below. |
| GitHub checks | Pending | To be updated after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 70 | 0 | 0 | 1 | 0 |
| unit | passed | 978 | 0 | 0 | 1 | 0 |
| contract | passed | 157 | 0 | 0 | 2 | 0 |
| integration | passed | 130 | 0 | 0 | 8 | 10 |
| e2e | passed | 40 | 0 | 0 | 0 | 2 |
| config-extra | passed | 424 | 0 | 0 | 0 | 1378 |

## Risks / Follow-Ups

- Collision policy is reject-only in v10; replacement or fork workflows remain future work.
- Imported payload evidence is reference metadata only. Phase 18 does not move payload bytes into authority-owned storage.
- Imported audit history is replay-labeled rather than represented as live online mutation events, which preserves provenance but is intentionally not a lossless transport-level replay API.
