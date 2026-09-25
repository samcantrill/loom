# Phase 3 Execution Plan: Run Discovery

## Metadata

- Status: merged; stage 42 / P3; vocabulary semantics approved.
- PR: [#352](https://github.com/samcantrill/loom/pull/352), targeting `develop`;
  implementation head `93ab7af9fc414ac2359e9acb724f023effce861a`.
- Manifest: [implementation-plan.md](../implementation-plan.md).
- Branch: `agent/stage-42-p3-run-discovery`; PR target: `develop`.
- PR title: Stage 42 Run Discovery, Annotations, Lineage, And Result Access - Phase 3: Run Discovery
- Worktree/coordination: manifest context; base
  `1723c85128abc52e07649d6261c2faa255a5186f` after P2 publication/synchronization.
- Dependencies: P1/P2. Named refinement uncertainty: none.
- Blockers: none; maintainer selected per-page vocabulary uniqueness with a
  deduplicating collector. P1 #349 and P2 #351 remotely merged; predecessor metadata
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
no physical-runtime qualification is claimed. Final evidence follows below.
Blocker corrections 1/3; improvement entries none.

Execution clarification: the maintainer approved local metadata enumeration
outside the 500 detailed-candidate budget; the discovery owner records that
decision. Managed initializing-submission ordering uses journal candidates,
checks authority initializer identity within the budget, and continues past
noninitializing reconciled submissions without treating them as new runs.
Job rows preserve existing admission identity and structured owner associations;
historical assignment arrays have no implicit scalar predicate. The manager
accepted that projection interpretation for independent review against FR-Q02.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation state | Implementation and required validation complete; ready for independent actual-head review. No PR/merge or branch transition performed by the executor. |
| Changed paths | New query/evaluator, page, acquisition and local-collection modules under `src/loom/runs`; native query acquisition under `src/loom/queue`; public catalog/client, Unix/HTTPS control and QUERY, CLI and MCP adapters; query unit/contract/native integration tests, API/MCP regression expectations; `docs/features/run-discovery.md` and catalog routing. |
| Public choices | Resolved by the maintainer in the discovery owner: metadata enumeration may exceed the detailed-acquisition budget; vocabulary uniqueness is per page and its collector unions observations while preserving coverage. No retained global vocabulary index/state. |
| Vocabulary implementation | Bounded 500-detail reads, including empty continuing pages; per-run continuation re-reads current annotations; keys/values remain generic. Collector retains page observations and warnings. Unicode-expanded annotations and escaped-value response budgets have discriminating tests. |
| Baseline expansion | `make validate-pr` ran the full no-extra suite: **3238 passed, 2 skipped, 392 deselected**, with two stale exact capability expectations failing. Updated only those expectations for `run-query-v1`; the exact Unix handshake and HTTPS configured-role regression nodes then passed (**2 passed**, isolated locked Python 3.12/dev). Baseline skips are the existing queue CLI manifest checks requiring dotenv, not P3 obligations. Successful unaffected broad evidence is retained. |
| Final bounded reconciliation | The final isolated locked Python 3.12/dev selection of query unit/contract, existing catalog contract/direct-scan/SQLite/current-list, and runs package API tests passed **46 tests**. This reconciles the vocabulary byte-budget/Unicode projection changes made while the broad baseline ran, including the subsequently added Unicode case. The command uses the six no-extra paths from this card's final targeted selection plus `tests/package/test_runs_api.py`, with `-m 'not optional_dependency' -q`. |
| Config/native/CLI coverage | `make lint typecheck test-config-extra test-mcp-extra build` completed config-extra: **336 passed, 15 skipped, 3302 deselected**, including all **5** `tests/integration/queue/test_run_queries.py` cases. These exercise Unix and HTTPS CLIENT, HTTPS QUERY vocabulary/search, CLI search translation, actual admission/assignment links, annotation mutation, unavailable authority under NOT, disconnected scope and reconciled original submissions. Skips are opt-in physical container acceptance, not P3 obligations. |
| MCP and remaining gate components | The preceding command stopped at one stale MCP SDK tool-name inventory after 54 MCP passes. Updated that expectation for the six new tools; `make lint typecheck test-mcp-extra build` then passed: **55 MCP tests**, project-wide Ruff, Pyright **0 errors/warnings**, source distribution and wheel. It includes the required tool contracts and real stdio selection. `uv lock --check` and staged diff checks pass. No selected P3 obligation is skipped. |
| Evidence tree | Reconciled validation applies to staged content tree `93adc4c02eb164eca209e4593e7e155ec48f389f`, based on `e1fb5162f17cdefdfef7b2ca32b7f390f9dfa361`; source subtree `8de098c1683a93ae2901b12473e0a6128c97e151`, tests subtree `a6772f9df1e481b5041964eb81adf6a18243b457`. Only this completion receipt changed afterward. No background validation jobs remain. |
| Remaining work | PR #352 opened with verified canonical title, target and implementation head; independent actual-head review and delivery pending. Manager checked diff scope and reconciled source/test subtree evidence; only roadmap status changed afterward. No public contract choice remains unresolved; no summary rerun is required by this card. |
| Residual limits | Live pages are not snapshots. Uncaptured run start/finish facts remain unknown; revision/preparation times are not substituted. Job assignment arrays are preserved but not scalar-searchable. No physical runtime qualification is claimed. |
| Independent review and delivery | Required actual-head review found R1; the same reviewer confirmed its correction at `47383ec44371d313f877052d847e3c2f593a797b`, with no remaining qualified findings. PR #352 remotely squash-merged as `c18130472e0f05b83c6cecc479e29f673c6c505f` on 2026-09-25. Delivery verified the merge and retired the exact remote phase branch; transition to coordination passed. |
| Completion | Required validation and independent review passed. Completion metadata published through coordination and synchronization; retain the stage worktree for P4. Earlier pending-review wording records pre-delivery evidence, not an outstanding gate. |
| R1 correction (1/3) | FR-42-Q06/Q07: normal owner-reader returns with unavailable association storage now contribute admission/axis-scoped `job_associations_unavailable` warnings, including the existing bounded diagnostic. Owner projections are preserved. The existing page warning cap and collector propagate incomplete coverage. Corrected; awaiting the existing reviewer's confirmation. |
| R1 focused evidence | On base `e86db60294772d627363ba64e4d7b2bbe5a031a1`, source blob `aeec20e8983b42aa3cb27f54947cb3ccbc841f44` and test blob `0e4cface42748eaa83abc5eb005e94d6de8e7eb4`: isolated locked Python 3.12/dev/config `pytest tests/integration/queue/test_run_queries.py::test_job_query_retains_unavailable_owner_coverage -q` passed **2** cases (corrupt execution database and agent journal with healthy run authority, preserved projections, page/collection warnings and incomplete coverage). The preceding full `test_run_queries.py` plus `test_local_daemon_production.py::test_status_degrades_per_run_for_corrupt_or_missing_owner_data` selection passed the **6 unchanged** cases on the final source; its two new regression cases needed fixture corrections and are superseded by the final two-case pass. |
| R1 boundaries and static checks | Isolated locked Python 3.12/dev `pytest tests/unit/loom/runs/test_query.py tests/contracts/test_run_query_contract.py -q` passed **31** tests, covering existing page/collector semantics and limits. Final `make lint typecheck` passed (project-wide Ruff, Pyright **0 errors/warnings**); `git diff --check` passed. No selected cases skipped. Earlier broad evidence remains applicable outside this bounded acquisition change. Expand only for newly affected owner contracts, page/codec changes, or a concrete regression. Only this receipt changed after validation; no background jobs remain. |
