# Phase 3 Execution Plan: Run Discovery

## Metadata

- Status: in_progress; stage 42 / P3.
- Manifest: [implementation-plan.md](../implementation-plan.md).
- Branch: `agent/stage-42-p3-run-discovery`; PR target: `develop`.
- PR title: Stage 42 Run Discovery, Annotations, Lineage, And Result Access - Phase 3: Run Discovery
- Worktree/coordination: manifest context; base
  `1723c85128abc52e07649d6261c2faa255a5186f` after P2 publication/synchronization.
- Dependencies: P1/P2. Named refinement uncertainty: none.
- Blockers: none. P1 #349 and P2 #351 remotely merged; predecessor metadata
  published, exact phase branches retired, and stage/control/remote synchronized.

## Objective And Supported Merge State

Find runs, submissions and native job views by explicit IDs, native timestamps,
recorded provenance, caller labels/metadata and human text. Discover supported
fields and observed tags. Return bounded truthful pages. This phase is useful
without artifact retrieval: a caller can answer “what did we launch yesterday,
and why?” and then inspect or annotate the identified runs.

Own all `FR-42-Q01`–`Q07`, `EX-42-Q01`–`Q04`, `VAL-42-Q01`–`Q06`,
`DQ-42-Q01`–`Q04`. Output selection, graph traversal and payload access remain
later phases. No query service, graph/index database or domain schema is added.

## Current Source And Harness

- `src/loom/runs/catalog.py` and artifact metadata readers: reuse current
  collection discovery and authority-aware state acquisition; keep existing
  exact-filter `list` behavior stable.
- `src/loom/queue/repository.py`, native operations/admissions, P1 context and P2
  annotation readers: managed scope candidates and recorded context.
- `src/loom/pipeline/stores/read_models.py`, authority clients and
  `src/loom/diagnostics/run_inspection.py`: recorded lifecycle/provenance only.
- `src/loom/cli/runs.py`, `src/loom/mcp/_server.py`, both coordinator transports:
  thin adapters over the checked native representation.
- Existing catalog contract, direct-scan/SQLite/current-list tests; native fixture
  and roles/HTTPS transport fixture. New query objects/evaluator may be small
  modules under `src/loom/runs`; importable without optional array/ML stacks.

## Fixed Contracts And Private Discretion

The [discovery detailed contract](../planning/discovery.md#detailed-implementation-contract)
owns field segments, finite predicate tree, three-valued logic, same-stage
quantification, explicit strict SemVer comparisons, timestamp semantics, managed
and configured collection scope, live keyset continuation and coverage.

Search methods return the existing entity's identity, not a new search/run ID.
`search_submissions` includes every original request, including not-yet-bound and
failed requests. `search_runs` original-context predicates refer to the initializer.
Query evaluation does not import recorded `_target_` values or read payload bytes.
Responses and iterators retain incomplete coverage even on an empty page.

Private choices: straightforward in-memory evaluation first, candidate batching,
read-only projections and optional proven-equivalent SQL pushdown. Do not add a
durable cache/snapshot service just to optimize an unmeasured workload.

## Invariant Ownership

| Invariant | Owner | Reachable boundary and consequence | Coverage |
| --- | --- | --- | --- |
| Exact type/presence logic | One parsed query evaluator | Mixed application metadata could turn strings/booleans/missing into false numeric matches | Truth table, nested boolean predicates, missing vs unknown vs null |
| Correct event/entity provenance | Acquisition projection and explicit quantifier | Several submissions/stages could satisfy unrelated conditions incorrectly | Many-to-one submissions; same-stage conjunction; created/submitted/finished times |
| Scope and redaction | Native acquisition/authorization boundary | Remote caller names another deployment/arbitrary path or private field | Reject unsupported scope/field; no implicit services or cross-scope leak |
| Honest bounded progress | Page assembler and cursor verifier | Mutable rows, exhausted scan budget or unavailable authority could appear exhaustive | Empty page with next, stable tie-break, tampered/query-mismatched cursor, retained warnings |

## Implementation Slices

1. Implement inert public query DTOs/serialization and one parser, with field
   capability table, finite tree/operand limits and unsupported-query errors.
   Implement typed evaluator and pure strict SemVer comparator; no `eval`, SQL
   fragments or PEP-440 reinterpretation of SemVer tags.
2. Assemble candidate snapshots from managed operations/admissions/run readers
   and explicitly configured collection scope. Retain per-field known/missing/
   unavailable distinctions and native source descriptions. Never hold write
   transactions while querying another authority or reading the filesystem.
3. Implement `search_runs`, `search_submissions`, `search_jobs`, `query_fields`,
   `tag_keys`, `tag_values`, and local `RunCatalog.search` over shared semantics.
   Native job projection preserves its actual admission/queue/assignment IDs.
   Tag vocabulary methods have independent bounded distinct-value pages and
   coverage; they are observations, not registration APIs.
4. Add validated live keyset cursors and all-page iterator preserving warnings.
   Enforce candidate budget even when matches are sparse; continue from the last
   examined key, not merely the last match. Stop response assembly before byte
   limits; oversized individual projections become an explicit bounded diagnostic.
   Queries without a reliable requested sort fact report incomplete coverage.
5. Expose the same query mapping as CLI JSON and MCP input, plus simple CLI
   conveniences translated to it. Advertise `run-query-v1` for CLIENT and QUERY
   roles on both transports. Add examples using two unrelated tag vocabularies,
   recent original reasons, note text, literal dotted keys and commit equality.

## Test And Validation Plan

Required new files: `tests/unit/loom/runs/test_query.py`,
`tests/contracts/test_run_query_contract.py`,
`tests/integration/queue/test_run_queries.py`. Exercise numeric/string/bool/null/
absence, unavailable under NOT, membership, SemVer prerelease/build/invalid values,
UTC boundary normalization, punctuation keys, and correlated stage predicates.

Integration fixtures must exceed one result page and one candidate budget, mutate
annotations between pages, leave an authority unavailable, and reject cursor
query/scope/coordinator mismatch. Verify no payload opening or target execution.
Test local collection scan parity without treating stale offline lifecycle as
current truth. Existing catalog APIs/return envelopes remain unchanged.

Final targeted selection:

```sh
uv run --python 3.12 --isolated --locked --group dev pytest tests/unit/loom/runs/test_query.py tests/contracts/test_run_query_contract.py tests/integration/queue/test_run_queries.py tests/contracts/test_run_catalog_contract.py tests/integration/pipeline/test_run_catalog_direct_scan.py tests/integration/pipeline/test_run_catalog_sqlite.py tests/integration/pipeline/test_run_catalog_current_list.py tests/contracts/test_mcp_tools.py tests/integration/mcp/test_stdio.py
```

Use `$loom-targeted-validation`, affected CLI tests, changed-file Ruff/Pyright and
diff checks. Expand to the complete catalog/inspection suites if acquisition
refactors change old readers. Full validation is required if changes escape the
new query routes into shared protocol behavior. No physical scheduler or dataset
needed; HTTPS is exercised with the existing local authenticated fixture.

## Risks, Stops, And Handoff

Read this card and full detailed discovery sections. Review unknown/NOT semantics,
scan progression and native versus claimed provenance. Stop if a selected native
field is not captured and cannot be reported unavailable, or a promised scope
would require cross-deployment credential discovery. Legacy absent fields and
non-snapshot pages are accepted, documented limits; repeatable bytes come from
later exact output selection, not an overstated search snapshot.

Workflow preparation: passed; reuse manifest readiness and fixed discovery
contracts. No planning refinement needed. One executor is justified by the
cross-cutting evaluator, acquisition, pagination and transport integration;
its write boundary is P3 source/tests/docs and this card, not later phases.
Independent actual-PR-head review remains a separate required gate.

Validation routing: retain every selection above, splitting baseline tests from
config-dependent fixtures and MCP-extra tests into their locked environments
per `tests/README.md`. Cover CLI query translation and both authenticated native
transports. Apply the stated expansion triggers after inspecting the final diff;
no physical-runtime qualification is claimed. Implementation and final evidence
pending. Blocker corrections 0/3; improvement entries none.

## Completion Record

| Item | Result |
| --- | --- |
| Changed paths, tests, validated tree, review/PR/merge, residual risk and cleanup | Pending implementation |
