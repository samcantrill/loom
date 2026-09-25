# Phase 2 Execution Plan: Run Annotations

## Metadata

- Status: in_progress; stage 42 / P2.
- Manifest: [implementation-plan.md](../implementation-plan.md).
- Branch: `agent/stage-42-p2-run-annotations`; PR target: `develop`.
- PR title: Stage 42 Run Discovery, Annotations, Lineage, And Result Access - Phase 2: Run Annotations
- Worktree/coordination: manifest execution context; base `27d32d86040ccd7379361715656ba46b8133dde2`.
- Dependencies: P1. Named refinement uncertainty: none.
- Blockers: none; P1 PR #349 remotely merged, completion metadata published and synchronization passed.

## Objective, Scope, And Reuse

Usable outcome: callers safely edit current descriptions/tags/metadata and append
attributed notes. This is independently valuable before search ships. P3 consumes
the same authority-owned view. Own `FR-42-C04/C05/C06`, `EX-42-C02`,
`VAL-42-C03/C04`, `DQ-42-C02/C03`; P1 already owns submission replay.

Reuse P1 models, authority owners and native context route. Organizational
authority methods now live in `queue/coordinator_authority.py`,
`pipeline/stores/coordinator_authority.py` and `_run_annotations.py`; extend that
scoped owner rather than adding worker-facing lifecycle methods. Extend
`src/loom/pipeline/stores/{authority.py,read_models.py,sqlite_authority.py,authority_protocol.py,authority_client.py,service_authority.py}`,
`src/loom/authority/_repository.py` and routes, native coordinator client/control,
`src/loom/cli/runs.py`, and `src/loom/mcp/_server.py`. Do not write legacy runtime
files directly or route an annotation through a worker lease. Notes and mutation
receipts are small authority records justified by current note/replay consumers.

Out of scope: query language, deep patch grammar, note editing/deletion, event
audit platform, or modifying authored execution configuration.

## Fixed Contracts And Private Discretion

The [safe patch contract](../planning/run-context.md#safe-patches-and-notes)
owns CAS, idempotency, patch meaning, notes, author and legacy behavior. Annotation
revision is separate from lifecycle revision. One authority transaction commits
effect plus receipt; identical uncertain-reply replay is checked before CAS.
Only a deliberate new request after re-read can rebase a conflict. Notes append
without full annotation CAS so concurrent independent notes need not conflict.

Native CLIENT writes and QUERY reads use existing access policy; reject QUERY
writes before effects. Caller-provided author text is not authenticated identity.
Recorded original context and fingerprints are immutable under these operations.
Private SQL/helper names and DTO grouping remain implementation discretion.

## Invariant Ownership

| Invariant | Owner | Reachable boundary and consequence | Coverage |
| --- | --- | --- | --- |
| No lost update | Authority annotation CAS transaction | Two agents patch same revision and one could erase the other's edit | One succeeds, one conflicts; explicit rebase preserves both unrelated keys |
| Exactly one effect for an idempotent mutation | Authority receipt transaction | Lost response causes retry | Same ID/digest returns original result even after later revision; changed request conflicts |
| Independent note history and native attribution | Authority note append | Concurrent/replayed notes or supplied author claims | Both independent appends, one replayed append, native time/author, stable bounded listing |
| Annotation does not change execution truth | Existing identity owners; mutation writes only annotations | Tag edit on completed/reused work could invalidate a fingerprint/cache hit | Compare captured config/action/artifact identities before/after edit and note |

## Implementation Slices

1. Add strict patch/note request/result objects and authority schema migrations
   for notes and mutation receipts. Validate JSON values and text/transport limits
   at ingress. Set/remove overlap rejects; absent versus null remains distinct.
2. Implement the same CAS/receipt transaction in embedded and service authority
   paths. Use authenticated principal plus mutation ID/digest and run target;
   test restart persistence. First write on a legacy run explicitly establishes
   the writable annotation record from its legacy view once.
3. Add native `patch_run_annotations`, `append_run_note`, `list_run_notes` routes;
   include writes in the mutation-operation set and preserve uncertain-reply
   evidence, coordinator identity and role checks. Do not auto-retry with a new ID.
4. Add Python/CLI/MCP patch and note methods with explicit conflict output and
   mutation IDs. CLI may allocate an ID per invocation and print it for replay;
   programmatic APIs require the caller's stable ID. Add updated examples and
   document original versus edited values and append-only correction practice.

## Test And Validation Plan

Required unit/contract checks: patch semantics, sizes, null/removal, legacy first
write, authority parity, receipt retention/replay, annotation versus lifecycle
revision, invariant identities. Required integration: concurrent clients, lost
reply then restart/retry, read-only principal rejection, Unix/HTTPS and CLI/MCP
equivalence. No dataset or physical backend qualification is needed.

Extend P1's proposed `tests/contracts/test_run_context_contract.py`,
`tests/integration/queue/test_run_context.py`; existing
`tests/integration/authority/test_mutation_api.py`,
`tests/contracts/test_mcp_tools.py`, `tests/integration/mcp/test_stdio.py`;
add focused `tests/integration/authority/test_run_annotations.py`.

Final targeted selection (new paths exist by this phase):

```sh
uv run --python 3.12 --isolated --locked --group dev pytest tests/contracts/test_run_context_contract.py tests/integration/queue/test_run_context.py tests/integration/authority/test_run_annotations.py tests/integration/authority/test_mutation_api.py tests/contracts/test_mcp_tools.py tests/integration/mcp/test_stdio.py
```

Use `$loom-targeted-validation` and the repository's changed-file Ruff/Pyright
checks plus `git diff --check`. If shared mutation protocol/migration changes
affect unrelated operations, expand to authority/native affected suites or the
full `make validate-pr` once, rather than claiming these focused checks cover
unbounded impact. The native fixture must test both authority storage modes.

## Risks, Stops, And Handoff

Read the entire card and owning run-context sections. Critical review: transaction
ordering and credentials, particularly author spoofing and stale replay. Stop if
annotations require changing lifecycle fencing or artifact identity; resolve at
the owner instead. Durable generic audit history beyond notes/current annotations
is deferred until there is a consumer. Supported merge state includes all four
client operations even if P3 never ships.

Workflow preparation passed; no refinement uncertainty. One phase executor is
selected for the cross-store CAS/receipt and adapter implementation scope, with
manager-owned validation acceptance and independent actual-PR review/delivery.
Implementation/validation/review/PR pending. Blocker corrections 0/3;
improvement entries none. Required selected tests need baseline, config-extra
and MCP-extra environments as their markers require; do not claim deselection
as adapter coverage. Expand for changed shared migration/protocol consumers.

## Completion Record

| Item | Result |
| --- | --- |
| Changed paths, tests, validated tree, review/PR/merge, residual risk and cleanup | Pending implementation |
