# Phase 4 Execution Plan: Output Selection

## Metadata

- Status: pending; stage 42 / P4.
- Manifest: [implementation-plan.md](../implementation-plan.md).
- Branch: `agent/stage-42-p4-output-selection`; PR target: `develop`.
- PR title: Stage 42 Run Discovery, Annotations, Lineage, And Result Access - Phase 4: Output Selection
- Worktree/coordination/base: manifest context; base after P3.
- Dependencies: P3 run selection and P1 native identities.
- Named refinement uncertainty: none. Blockers: stage gates/earlier merges.

## Objective, Scope, And Supported Merge State

Turn run/stage/query selection into exact published output identities. Callers can
inspect current results and explicit history, including outputs from failed runs
and cross-run reused results. This is metadata-only and useful before graph or
download support. P5/P6 consume the exact same `OutputLocator`.

Own `FR-42-A04/A05/A08`, `EX-42-A04`, `VAL-42-A03`, `DQ-42-A02`;
P6 owns byte-level enforcement of A05 and access outcomes in A08. Reuse origin
preservation also supplies P5's `FR-42-A03`. Do not fetch files or introduce
version IDs, retention pins, output-head writes or new result authority.

## Existing Source And Harness

- `src/loom/pipeline/stores/read_models.py`: `OutputCommitRecord`, artifact
  facts, current lifecycle snapshot and `ActionResultBinding`.
- `src/loom/pipeline/stores/sqlite_authority.py`,
  `src/loom/authority/_repository.py` and authority protocol/client/service
  adapters: existing durable output history and original producer bindings.
- `src/loom/diagnostics/run_inspection.py`, `src/loom/runs/artifact_metadata.py`,
  P3 query surface, native routes, `src/loom/cli/runs.py`, MCP server.
- Existing `tests/contracts/test_authority_store_contract.py`,
  `tests/contracts/test_immutable_artifact_semantics_contract.py`,
  `tests/integration/authority/test_action_result_binding.py`.

## Fixed Contracts, Ownership, And Discretion

Use the [output-access detailed contract](../planning/output-access.md#detailed-implementation-contract):
`OutputLocator(run_uri, stage_name, commit_id, output_name)` always addresses the
original producer. `SelectedOutput` separately retains the run/stage through
which the caller matched a reused output. The authority verifies locator ↔ fact;
a client-supplied changed `ArtifactRef.uri` never authorizes retrieval.

Current/history selection reports its policy, observed context and every missing
or unavailable requested run/stage. Existing commits/facts remain the authority;
no catalog row creates published success. Default availability is `not_checked`.
Private read batching and DTO module arrangement can remain small and local.

| Invariant | Owner | Reachable boundary and consequence | Coverage |
| --- | --- | --- | --- |
| Exact version survives producer retry | Authority commit/fact lookup | New current commit appears after selection | Exact old locator still resolves old fact; deleted bytes later yield unavailable |
| Reuse is not a new producer | Existing action-result binding reader | Consumer has no local commit/attempt | Return original locator plus matched consumer, no fabricated consumer commit |
| Failure does not erase earlier results | Stage output reader | Later stage/run fails | Useful committed output appears independently of run status |
| Authorized metadata-only view | Native selector | Untrusted exact producer or output metadata | Scope check, bounded inert fields; no target import or file open |

## Implementation Slices

1. Add value objects and authority read methods for exact commit, historical
   commits and named artifact facts where not exposed already. Reuse existing
   tables and read models; do not duplicate commit history in a query database.
2. Implement `select_outputs` and `list_output_commits`. Inputs support explicit
   runs/stages or P3 query, output name/type/metadata, and current/all/exact history.
   Paginate nested run/output expansion, preserving query warnings and selection
   failures. Separate a requested run with no matching output from a scope that
   could not be inspected.
3. Resolve action-result bindings through original facts. Require authorized
   access to the matched run and the original producer under existing scope rules;
   a reference is not an authorization capability. If the producer cannot be
   resolved/authorized, report a restricted/unavailable boundary without leaking
   hidden provenance. No cross-deployment federation or credential following.
4. Add CLIENT/QUERY native routes and `output-query-v1`, Python methods,
   `loom runs outputs`, historical selection, MCP `loom_select_outputs`, and
   feature docs. Exercise exact native wire requests, not only mocked facades.

## Test And Validation Plan

Add `tests/contracts/test_output_selection_contract.py` and
`tests/integration/queue/test_output_selection.py`. Fixture: two commits, a
failed downstream stage, a reused result without a consumer commit, a missing
stage/output, and an unavailable authority. Assert current versus all/exact,
original and matched identity, stable selected ref, authorization, empty versus
incomplete outcomes, paging and no payload reads.

Final targeted selection:

```sh
uv run --python 3.12 --isolated --locked --group dev pytest tests/contracts/test_output_selection_contract.py tests/integration/queue/test_output_selection.py tests/contracts/test_authority_store_contract.py tests/contracts/test_immutable_artifact_semantics_contract.py tests/integration/authority/test_action_result_binding.py tests/contracts/test_mcp_tools.py tests/integration/mcp/test_stdio.py
```

Use `$loom-targeted-validation`, affected CLI tests, changed-file Ruff/Pyright and
diff checks. Add authority repository/protocol suites if exposing history alters
shared serialization. No physical backend needed; source authority and native
transport fixtures are the affected boundaries.

## Risks, Stops, And Handoff

Review binding-versus-local-commit behavior and history paging. Stop if selected
versions require inferring a producer from checksum/filename, or if reuse access
would bypass the original producer's policy. Do not fix missing bytes by changing
the locator. No retention guarantee is offered. Read this card and output
selection/history contract before implementation.

Workflow preparation/refinement/implementation/validation/independent review/PR:
not started. Blocker corrections 0/3; improvement entries none.

## Completion Record

| Item | Result |
| --- | --- |
| Changed paths, tests, validated tree, review/PR/merge, residual risk and cleanup | Pending implementation |
