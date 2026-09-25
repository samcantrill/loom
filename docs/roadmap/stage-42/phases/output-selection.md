# Phase 4 Execution Plan: Output Selection

## Metadata

- Status: pr_open; stage 42 / P4.
- PR: [#353](https://github.com/samcantrill/loom/pull/353), verified canonical title
  and `develop` target; implementation head `f05ce49a09751142dc3efd0cfb98a4732dcdc90e`.
- Manifest: [implementation-plan.md](../implementation-plan.md).
- Branch: `agent/stage-42-p4-output-selection`; PR target: `develop`.
- PR title: Stage 42 Run Discovery, Annotations, Lineage, And Result Access - Phase 4: Output Selection
- Worktree/coordination: manifest context; base after P3 is
  `a729b71749350c84b45257bf2430589b51724a45`.
- Dependencies: P3 run selection and P1 native identities.
- Named refinement uncertainty: none. Blockers: none. P3 #352 remotely merged,
  completion metadata published, synchronization passed and exact phase branch
  retired before this branch started.

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

Workflow preparation passed; reuse approved manifest readiness and exact
selection/history contracts. One executor is justified for the coordinated
authority-history, reuse-resolution and native adapter changes. Write scope is
P4 source/tests/user documentation and this card, excluding P5/P6 behavior.
No planning refinement is needed. Preserve every required selection above,
splitting config and MCP fixtures into their locked optional environments;
expand authority protocol/repository coverage for shared serialization changes.
Record final scope and affected static checks before independent actual-head
review. Implementation and targeted validation complete; manager PR/review pending. Blocker corrections 1/3;
improvement entries none.

## Completion Record

Validation selection follows `loom-targeted-validation`: exact/current/history
authority facts, failed-run results, original-producer authorization, retained
reuse associations, bounded nested pages, metadata-only access, and native
Python/CLI/MCP consumers. History already exists in both stores and the versioned
authority result; P4 adds the missing scoped coordinator-authority read route,
without changing storage or record schemas. This expands coverage to repository,
protocol and coordinator-authority contracts. QUERY output requests/responses use
the existing native JSON decoder because the worker decoder's depth/scalar bounds
cannot represent nested output histories and floating-point metadata. Existing
QUERY-role/transport tests and discovery integration therefore remain selected.

Final commands use `uv run --python 3.12 --isolated --locked --group dev`:

- Baseline: `pytest tests/contracts/test_output_selection_contract.py
  tests/contracts/test_authority_store_contract.py
  tests/contracts/test_immutable_artifact_semantics_contract.py
  tests/integration/authority/test_action_result_binding.py
  tests/contracts/test_authority_repository_contract.py
  tests/contracts/test_authority_protocol_contract.py
  tests/integration/authority/test_coordinator_authority_api.py
  tests/unit/loom/pipeline/stores/test_authority_protocol.py
  tests/contracts/test_cli_runs_contract.py tests/unit/loom/cli/test_runs.py
  tests/package/test_runs_api.py tests/unit/loom/queue/test_local_daemon.py
  tests/integration/queue/test_agent_session_transport.py -m 'not optional_dependency and not slow and not network and not slurm'`.
- Config lane (`--extra config`): `pytest
  tests/integration/queue/test_output_selection.py
  tests/integration/queue/test_run_queries.py`.
- MCP lane (`--extra config --extra mcp`): `pytest
  tests/contracts/test_mcp_tools.py tests/integration/mcp/test_stdio.py`.
- Changed Python files: Ruff and Pyright (config/MCP extras for typing), plus
  staged and unstaged diff checks. Expand only for failed checks, newly affected
  consumers, or changes invalidating this evidence. No physical backend is claimed.

| Item | Result |
| --- | --- |
| Implementation | Inert `OutputLocator`, `SelectedOutput` and `OutputSelection` in `loom.runs`; authorized current/all/exact metadata selection, retained commit history, original producer/reuse associations, literal typed metadata filters, bounded nested live pages and explicit missing/unavailable outcomes. No payload reads, new durable identity/index, or P5/P6 behavior. |
| Owning paths | `runs/outputs.py`, `queue/_output_selection.py`; existing coordinator client/control, HTTPS QUERY, CLI and MCP adapters; scoped coordinator-authority history route reuses existing result serialization. Feature documentation: `docs/features/output-selection.md` linked from artifacts. |
| Validation | Baseline selection above: **260 passed, 2 deselected** in 493.23s. The two deselections are unchanged config-only authority publication/reconciliation cases, outside output selection. Config lane: **9 passed** in 96.46s. MCP lane: **42 passed** in 109.66s. No skipped required cases; no physical runtime claim. |
| Final-tree follow-up | Added explicit rejection of nonobject cursors and boolean schema versions during the final pass. Final output contract rerun: **15 passed** in 3.09s. Changed-file Ruff passed; changed-file Pyright: **0 errors, 0 warnings**; staged and unstaged diff checks passed. Earlier transport/authority evidence remains applicable; final changes only tighten invalid selector decoding. |
| Validated tree | `4e5a7c786991d1a990d58c2626ca12c0486e23d4` from `git write-tree`, based on the recorded assignment base. Only this completion receipt changed afterward. Commands/selectors above and committed contract/integration tests are the retained evidence; no sidecars. |
| Review, PR, merge | Pending manager actual-head independent review and delivery. Executor made no PR, merge or branch transition. |
| Residual limits | Live paging is not a snapshot; no retention pin or byte availability guarantee. Whole authority histories use existing readers; oversized metadata produces a bounded explicit outcome. Producer restrictions/unavailability remain visible without hidden provenance. |

### Review Correction R1

Correction 1/3 accounts for each prospective per-selector warning in the output
page byte budget before accepting its outcome. This preserves every requested
selector and its warning while keeping the continuation available when many
unavailable selectors share a long run URI. The affected contract is bounded
native output selection/history paging with truthful incomplete coverage; storage,
authority reads, identities and adapter schemas are unchanged.

The regression exercises 200 explicitly requested stages under an unavailable
authority and a deep collection URI over both Unix and HTTPS. For both
`select_outputs` and `list_output_commits`, every encoded response is below the
1 MiB transport limit, continuations advance, warnings and incomplete coverage
remain visible, and all 200 stage outcomes arrive exactly once.

Validation on source/test tree `06ecdd1ac58510a4f7b1482a2c3ac47788faa2de`
(based on `31e3c39a9ec2a0d270812b11eb47f90f84eba3a5`):
`uv run --python 3.12 --isolated --locked --group dev --extra config pytest
tests/integration/queue/test_output_selection.py
tests/contracts/test_output_selection_contract.py` — **19 passed** in 39.46s,
no skips. Changed-file Ruff passed and Pyright reported **0 errors, 0 warnings**
for `src/loom/queue/_output_selection.py` and
`tests/integration/queue/test_output_selection.py`; diff checks passed. Only this
completion receipt changed afterward. Existing unaffected phase evidence remains
applicable; expand checks only for failures or newly affected behavior. R1 is
corrected and awaits the existing reviewer's confirmation; no PR or merge action
was taken by the refiner.
