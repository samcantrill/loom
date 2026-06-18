## Summary

This PR evolves Loom runtime events to the Stage 20 schema-version 2 grammar while keeping existing schema-version 1 local logs, authority audit events, and offline evidence readable through explicit compatibility projection. New durable event records now carry stable event identity, `occurred_at`, generic primary and related resource references, optional causal predecessors, and a durable event reference helper without introducing a second event family.

The change also updates local and authority-compatible event persistence so new audit events retain the full canonical record shape, while legacy records continue to project without eager rewrite. Sink registry, sink dispatch, callback failure facts, observer links, plugin loading, and CLI presentation remain out of scope for later phases.

## Acceptance Criteria

- [x] Schema-version 2 `PipelineEventRecord` records round trip with the planned public fields and omit legacy persisted `timestamp`, `scope`, and `event_name` fields.
- [x] Schema-version 1 records read through `PipelineEventRecord.from_dict()` and `from_schema_v1_dict()` with deterministic compatibility event ids and no source-log rewrite.
- [x] Generic `EventResourceRef`, `EventReference`, causal predecessor, and durable `to_event_reference()` helpers validate strict plain-data shapes.
- [x] Local and authority-compatible append/read paths preserve deterministic per-run ordering and retain canonical v2 fields for new events.
- [x] Offline evidence/import paths validate and replay v2 event records while preserving schema-v1 compatibility.
- [x] Future phases were not implemented: no sink registry, runtime sink dispatch, callback failure records, observer links, plugin loader, CLI event surface, cleanup, or service-specific behavior.

## Implementation Notes

`loom.pipeline.events` now exposes the Stage 20 event grammar with `EVENT_SCHEMA_VERSION = 2`, `LEGACY_EVENT_SCHEMA_VERSION`, `EventResourceRef`, `EventReference`, `compatibility_event_id()`, schema-v1 projection helpers, and durable event-reference creation. Compatibility aliases for `timestamp` and `scope` remain available for run and stage resources so existing adapter boundaries can continue to operate while new persistence writes the canonical v2 shape.

Authority paths now store canonical event JSON alongside legacy query columns. The private authority repository migrates legacy `audit_events` tables to a `(run_uri, sequence)` primary key before appending per-run sequences, and SQLite/service authority paths retain the full v2 event record on append. Offline import tests were updated to assert v2 resource and timestamp fields instead of relying on schema-v1-only `scope` and `timestamp` payloads.

New tests implemented:

- Event model unit coverage for resource refs, durable and non-durable reference shapes, schema-v2 round trip, schema-v1 projection, causal predecessors, strict malformed-input rejection, deterministic compatibility ids, and constructor validation regressions.
- Authority integration coverage for legacy audit tables accepting per-run event sequences after migration.
- Offline import unit coverage updated for schema-v2 event payload readback and replay comparisons.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed after refinement. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; overall status passed. |
| GitHub checks | Pending | Expected to run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 103 | 0 | 0 | 1 | 0 |
| unit | passed | 1343 | 0 | 0 | 7 | 1 |
| contract | passed | 263 | 0 | 0 | 2 | 0 |
| integration | passed | 165 | 0 | 0 | 8 | 13 |
| e2e | passed | 44 | 0 | 0 | 0 | 2 |
| config-extra | passed | 447 | 0 | 0 | 3 | 1927 |
| Overall | passed | 2365 | 0 | 0 | 21 | 1943 |

## Risks / Follow-Ups

- Schema-v1 projection remains compatibility debt until a later documented removal or archival window.
- Scope compatibility aliases are intentionally retained for adapter boundaries until later runtime dispatch work no longer needs them.
- Event sink registry, sink dispatch, callback failure facts, observer links, plugin loading, diagnostics, and broader user-facing event docs remain later Stage 20 phase work.
