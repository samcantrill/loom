## Summary

@samcantrill

This PR implements Stage 19 Phase 2 by adding durable reliability fact
persistence and authoritative read-model projections for the Phase 1 reliability
records. It adds store-owned read/write surfaces for selected reliability
policy facts, status details, stage-attempt transactions, retry decisions, and
timeout outcomes without adding execution lifecycle writes, retry automation,
timeout enforcement, diagnostics, CLI presentation, events, or cleanup behavior.

Reliability facts are now materialized as strict, immutable records in local,
in-memory, SQLite, and service authority-compatible paths. Authoritative run
and stage snapshots carry typed reliability projections while older snapshots
without reliability fields continue to deserialize with empty defaults.

## Acceptance Criteria

- [x] Store/read-model facets persist policy facts, status details,
  transactions, retry decisions, and timeout outcomes.
- [x] Local reliability facts live outside `events.jsonl`, status metadata, and
  executor logs.
- [x] Local, in-memory, SQLite, and service authority-compatible paths share
  typed write/read semantics.
- [x] Authoritative snapshots preserve reliability facts and default missing
  reliability fields to empty tuples.
- [x] Package, unit, contract, integration, full PR, and suite-summary checks
  passed.

## Implementation Notes

The new `loom.pipeline.stores.reliability_facts` helper module centralizes
reliability fact identity, payload comparison, run-uri validation, and stage
name projection. `ReliabilityPolicyFact` lives with store read models as the
store envelope around selected `ReliabilityPolicy` values, with run, stage, and
attempt scopes.

`LocalRunStore` writes one JSON document per reliability fact under
run-scoped `reliability/` family directories. Rewriting the same identity with
the same payload is idempotent; rewriting it with a different payload fails.
SQLite authority uses dedicated reliability tables and includes those facts in
snapshots. The service and in-memory authority paths mirror the same record
semantics for contract coverage.

New tests cover:

- Strict serialization and backward-compatible snapshot defaults.
- Local reliability fact round trips, immutable writes, deterministic reads,
  and independence from events, status metadata, and logs.
- SQLite snapshot-backed reliability facts and immutable write behavior.
- Authoritative read-model contracts carrying reliability facts across
  in-memory and service authority paths.
- Store API/package exports and protocol shape for the new reliability store
  surface.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default suite `1788 passed, 26 skipped, 18 deselected`; config-extra `446 passed, 1825 deselected`; build succeeded |
| `make test-summary` | Passed | Overall `2262 passed, 18 skipped, 1841 deselected`; see suite table below |
| GitHub checks | Pending | To be populated by GitHub after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 102 | 0 | 0 | 1 | 0 | 103 | 14.97s | 19% |
| unit | passed | 1256 | 0 | 0 | 7 | 1 | 1263 | 54.69s | 76% |
| contract | passed | 256 | 0 | 0 | 2 | 0 | 258 | 12.75s | 58% |
| integration | passed | 159 | 0 | 0 | 8 | 13 | 167 | 54.64s | 62% |
| e2e | passed | 43 | 0 | 0 | 0 | 2 | 43 | 37.09s | 59% |
| config-extra | passed | 446 | 0 | 0 | 0 | 1825 | 446 | 85.03s | 62% |
| Overall | passed | 2262 | 0 | 0 | 18 | 1841 | 2280 | 259.17s | - |

## Risks / Follow-Ups

Phases 3 through 6 still own execution lifecycle writes, failure
classification, timeout diagnostics, retry automation, and read-only
inspection. Stage 20 event projection and Stage 21 cleanup/deletion remain out
of scope.
