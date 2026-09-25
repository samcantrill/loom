# Phase 2 Execution Plan: Run Annotations

## Metadata

- Status: pr_open; stage 42 / P2.
- PR: [#351](https://github.com/samcantrill/loom/pull/351), target `develop`; independent actual-head review pending.
- Manifest: [implementation-plan.md](../implementation-plan.md).
- Branch: `agent/stage-42-p2-run-annotations`; PR target: `develop`.
- PR title: Stage 42 Run Discovery, Annotations, Lineage, And Result Access - Phase 2: Run Annotations
- Worktree/coordination: manifest execution context; base `27d32d86040ccd7379361715656ba46b8133dde2`.
- Dependencies: P1. Named refinement uncertainty: none.
- Blockers: none; maintainer chose run-scoped mutation IDs. P1 PR #349 remotely merged, completion metadata published and synchronization passed.

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
   paths. Use `(run_uri, authenticated principal, mutation ID)` receipt identity;
   validate same-run replay/conflict and independent cross-run ID reuse;
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
Implementation and expanded local validation complete; actual-PR review found R1 below.
Blocker corrections 1/3 (one scoped refiner correction assigned);
improvement entries none. Required selected tests need baseline, config-extra
and MCP-extra environments as their markers require; do not claim deselection
as adapter coverage. Expand for changed shared migration/protocol consumers.

## Completion Record

### Independent Review R1: Legacy Note Limits

Review of PR #351 head `7496fc31f57d0a103f0d5b1b3c032184f7af8d24` found one
product blocker: supported `RunOptions.notes` can contain 16,385-byte text, but
`RunNote` applies the 16-KiB native append limit to `legacy_runtime` too.
Shared mutation code converts all legacy notes on every write, so such a note
breaks listing, unrelated tag patches and valid short native appends. This
violates preserved legacy evidence and unrelated annotation-write contracts;
the maintainer's initial-tag decision does not authorize rejecting legacy notes.

Smallest correction: separate native append limits from retained legacy evidence,
preserve full legacy text/unknown attribution without truncation or rewriting,
retain bounded listing with an explicit limitation when text cannot fit, and
prevent legacy projection size from invalidating otherwise valid mutations.
Extend supported-producer coverage across both durable authority owners. No new
execution/lifecycle owner or arbitrary scope expansion. Review otherwise found
the transactions, replay, native attribution and validation evidence consistent.
Merge remains blocked until correction and the same reviewer's confirmation.

| Item | Result |
| --- | --- |
| Changed paths | Inert run values/limits; shared annotation SQL owner and additive embedded/repository migrations; coordinator-scoped authority adapters and service fixture; native control/Unix/HTTPS/query, Python, CLI and MCP; corresponding contracts, integration/package/schema tests and feature docs |
| Implementation | `e125ab95b6e05b873c1748373a381a4953ef1dec`: atomic run-scoped receipts before annotation CAS, current-field patches, attributed append-only notes, bounded live pages, legacy first-write preservation, classified uncertain acknowledgements and adapter parity |
| Validation selection | Expanded to `make validate-pr` because both authority schemas and shared native decoding changed. Required context/annotation, mutation API, config-backed native/CLI and MCP selectors are included in their separate locked dependency lanes; no selected adapter coverage is inferred from deselection. |
| Broad baseline / config evidence | `make validate-pr`: default **3206 passed, 2 skipped, 372 deselected**; config-extra **322 passed, 15 skipped, 3261 deselected**, including all 14 run-context integration cases. Baseline skips are the two existing queue CLI manifest checks needing `dotenv`; config skips are the 15 opt-in container acceptance cases. None is a P2 obligation. |
| MCP and remaining full-gate components | The broad command stopped on two stale MCP discovery assertions, after 47 MCP passes. Updated only their expected tool names/mutation hints in `500fb4e09ec2b82049332620e980c7e570805d7c`; `make lint typecheck test-mcp-extra build` then passed: **49 MCP tests**, project-wide Ruff, Pyright (0 errors/warnings), source distribution and wheel. Reused successful baseline/config components rather than rerunning unchanged suites. |
| Final bounded reconciliation | While broad validation was running, annotation acknowledgement classification and typed result decoding were tightened: known owner validation is `not_applied`, uncertain authority/invalid native replies retain `unknown` and the original mutation ID. Final isolated no-extra selection (context contract, annotation authority, mutation API, runs package API) passed **50 tests**; the final config selection covering both authority owners × Unix/HTTPS passed **4 tests** with restart/replay, current-revision conflicts, resulting-size rejection, QUERY denial/read access and CLI parity. Completed/failed identity checks (**2**) and native legacy first-write (**1**) passed; full config and final MCP additionally cover the affected consumers. |
| Validated tree / delivery | Reconciled source/test revision: `500fb4e09ec2b82049332620e980c7e570805d7c` (product source is `e125ab95b6e05b873c1748373a381a4953ef1dec`; later commit changes only the four MCP expectation lines). Subsequent changes are this completion record only. `git diff --check` passes. No independent phase review, PR or merge has occurred. |
| Evidence logs | `/tmp/loom-stage42-p2-validate.log`; `/tmp/loom-stage42-p2-final-gate-repair.log`; `/tmp/loom-stage42-p2-baseline-final.log`; `/tmp/loom-stage42-p2-reply-classification.log`; `/tmp/loom-stage42-p2-completed-identities.log`; `/tmp/loom-stage42-p2-legacy-native.log` |
| Scope decision | Resolved 2026-09-25: maintainer approved uniform run-scoped IDs. Run-context Safe Patches And Notes owns the key, digest and cross-run reuse semantics. |
| Manager base reconciliation | Merged concurrent `develop` PR #350 (`76793120`) into the phase at `db610fcd96b5f4414a0b7dc73feffd8ac67625a9`, without conflicts. Retirement changes touch daemon startup and transport ownership but do not change annotation storage/replay contracts. |
| Combined-tree checks | On `db610fcd`: isolated locked Python 3.12 no-extra pytest for `tests/integration/queue/test_role_retirement.py tests/unit/loom/queue/test_local_daemon.py` with standard non-optional markers: **64 passed, 5 deselected**. Separate config-extra pytest for entire `tests/integration/queue/test_run_context.py`: **14 passed**. Prior unaffected broad/static/MCP/build evidence remains applicable; subsequent edits only workflow metadata. Diff check passed. |
| Residual / cleanup | No unresolved implementation or local-validation blocker. Await manager-owned independent review/delivery. No physical dataset/fleet qualification is required. Stage worktree retained; no branch transition or PR work performed by the executor. |
