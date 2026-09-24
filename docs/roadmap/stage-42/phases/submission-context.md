# Phase 1 Execution Plan: Submission Context

## Metadata

- Status: in_progress; stage 42 / P1.
- Manifest: [implementation-plan.md](../implementation-plan.md).
- Branch: `agent/stage-42-p1-submission-context`; PR target: `develop`.
- PR title: Stage 42 Run Discovery, Annotations, Lineage, And Result Access - Phase 1: Submission Context
- Worktree/coordination: manifest execution context; base `305ffa4416e53d3bb189e6251642641025993e98`.
- Dependencies: existing v40/v41 native lifecycle; no earlier stage-42 phase.
- Named refinement uncertainty: none. Approval, landing, source drift and isolation gates passed.

## Objective And Context

Usable outcome: submit generic context and recover the original reason, current
initial annotations, native operation association and eventual `run_uri` through
Python, CLI and MCP. Context remains useful if no later phase ships. P2 receives
authority-owned annotations; P3 receives retained submission records. Mutable
annotation commands, advanced queries, lineage and transfer are out of scope.

## Current Source And Harness

- `src/loom/coordinator.py`: `PrepareRunRequest`, `RunRequest`, response objects.
- `src/loom/queue/_preparation_operations.py`, `preparation.py`,
  `managed_local_preparation.py`, `repository.py`: durable native preparation,
  request journal and binding/reconciliation.
- `src/loom/queue/_coordinator_client.py`, `_coordinator_control.py`,
  `agent_session_transport.py`: native envelopes, capabilities, roles and replay.
- `src/loom/pipeline/stores/authority.py`, `read_models.py`,
  `sqlite_authority.py`, `authority_protocol.py`, `authority_client.py`,
  `service_authority.py`; `src/loom/authority/_repository.py` and owned routes:
  both authority implementations and authenticated consumers.
- `src/loom/diagnostics/run_inspection.py`, `src/loom/runs`, `src/loom/cli/run.py`,
  `runs.py`, `src/loom/mcp/_server.py`: public presentation owners.
- Existing `tests/integration/queue/test_run_operations.py`,
  `tests/unit/loom/test_coordinator.py`, authority contract fixtures,
  `tests/support/native_run_fixture.py` and MCP stdio fixture.

## Scope And Contracts

Own `FR-42-C01/C02/C03/C07`, `EX-42-C01/C03`, `VAL-42-C01/C02/C05`,
`DQ-42-C01/C04`, the initial storage portion of `DQ-42-C02`, and submission
replay in `FR-42-C06`/`VAL-42-C04`.
The [run-context contract](../planning/run-context.md#detailed-implementation-contract)
owns all public/durable semantics. Use inert value objects; no execution/config
imports for context reads. Existing native facts remain authoritative.

Concrete storage: retain context in the existing coordinator operation request,
its native accepted timestamp/principal and eventual binding. Add authority
annotation initialization with its own revision and initializer operation link.
Keep initialization idempotent and complete it before exposing successful binding
or starting work. Multiple reconciled submissions keep separate original records;
they do not replace current annotations on an already initialized run.

Private discretion: table names, small context/query DTO module layout, read-model
assembly helpers. Do not freeze the next migration version against a moving
branch. No tracking database, hook registry, or config-field inference is needed.

## Invariant Ownership

| Invariant | Owner | Reachable boundary and consequence | Coverage |
| --- | --- | --- | --- |
| Same native request replays; changed context conflicts | Coordinator request serialization/digest | Retry after lost response could duplicate/change accepted intent | Old omitted/empty serialization golden; changed nonempty context replay |
| Initial annotation owner is established once | Authority initialization transaction; preparation awaits it | Crash/reconcile could bind a run with missing context or silently retag existing work | Restart at journal/authority/bind boundaries; second submission retained separately |
| Native versus caller facts are distinct | Public context parser/read model | Caller metadata named status/commit could impersonate execution evidence | Typed round-trip with duplicate-looking native names |
| Context is inert and bounded | Public ingress and serialized transport boundary | Agent passes non-JSON payload/oversize body or untrusted import target | Finite JSON values, UTF-8 budgets, no import/download on reads |

## Implementation Slices

1. Add `SubmissionContext` and initial annotation/context read shapes. Normalize
   empty context to omission in existing request serialization. Add capability
   negotiation and strict parsers without changing old digests. Reject conflicting
   explicit tag sources; apply specified effective-tag precedence.
2. Add additive coordinator/authority migrations using existing migration owners.
   Preserve historical operations and annotate legacy absence honestly. Initialize
   a run once using native binding identity; expose receipt replay, not a new
   execution lifecycle state. Rollback/retry must not overwrite another initializer.
3. Wire preparation journal → authority initialization → run binding, preserving
   operation identity before a run exists. Test a failed preparation and several
   submissions reconciling to one run. Authenticated principal comes from the
   connection, never caller context. Existing authorization remains in force.
4. Add `get_run_context` joining original submissions, current annotations and
   existing run inspection. Return bounded submission links rather than an
   unbounded history embedded in every overview; native operation lookup remains
   available before P3 adds search. Missing authority/coordinator context is a
   reported partial view, not invented original intent.
5. Add Python exports, submission CLI/MCP context input and context inspection.
   Update relevant `docs/features` and command/tool docs. Existing invocation
   without context behaves unchanged. The same fixture drives both transports
   and adapters, including QUERY read access and rejection of submission writes.

## Test And Validation Plan

| Lane | Required evidence |
| --- | --- |
| Unit | JSON/type/size validation, empty-context serialization/digest compatibility, explicit tag conflicts |
| Contract | Both authority backends serialize/init/read equivalent context; migration fixtures preserve legacy tags/notes and unknown origin |
| Integration | Lost-response replay, restart before/after init acknowledgement, many submissions/one run, failed-before-binding identity, read-only role enforcement |
| CLI/MCP | Actual native fixture round-trip, bounded machine output, no implicit execution on inspection |
| Physical | No GPU, real scheduler or container fleet needed: context changes no backend algorithm |

Existing checks to extend: `tests/unit/loom/test_coordinator.py`,
`tests/integration/queue/test_run_operations.py`,
`tests/contracts/test_authority_repository_contract.py`,
`tests/contracts/test_authority_store_contract.py`,
`tests/contracts/test_mcp_tools.py`, `tests/integration/mcp/test_stdio.py`.
New proposed focused files: `tests/contracts/test_run_context_contract.py` and
`tests/integration/queue/test_run_context.py`.

During implementation, use `$loom-targeted-validation`. A focused development
selection is:

```sh
uv run --python 3.12 --isolated --locked --group dev pytest tests/unit/loom/test_coordinator.py tests/integration/queue/test_run_operations.py tests/contracts/test_run_context_contract.py tests/integration/queue/test_run_context.py
```

Final gate: `make validate-pr`, because request digests, additive durable schemas,
both native transports and authority adapters are cross-cutting. Do not rerun
included tests/static checks separately after a current passing final gate.
Expand physical validation only if implementation unexpectedly changes placement,
launch or backend execution rather than attaching context.

## Risks, Review, And Stops

Review crash ordering and legacy replay most closely. Stop for manager review if
the current binding protocol cannot safely wait for idempotent authority context
initialization, or context would enter action/artifact identity. Do not work around
it with an independent journal or lifecycle status. Old servers must explicitly
reject unsupported context; no silent dropping. Old records remain useful with
unknown original context, which is accepted compatibility debt.

## Executor Handoff And Workflow State

Read this entire card, manifest shared constraints, and the run-context detailed
contract. Implement the five slices; do not revisit generic vocabulary, identity,
or many-to-one submission semantics. Manager preparation, implementation,
preparation passed. One phase executor is selected for the cross-cutting store,
replay and adapter implementation scope; it owns implementation and validation,
not PR delivery. Pre-submit validation, independent phase review and PR/merge:
pending implementation.
Refiner: not needed yet. Blocker corrections: 0/3. Improvement entries: none.

## Completion Record

| Item | Result |
| --- | --- |
| Changed paths, tests, validated tree, review/PR/merge, cleanup | Pending implementation |
