# Phase 1 Execution Plan: Submission Context

## Metadata

- Status: blocked; stage 42 / P1; implementation checkpoint, not complete.
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

Execution paused by manager pending resolution of the effective-tag compatibility
conflict described below. No accepted limits or grandfather policy were changed.

## Completion Record

Implementation coverage: bounded immutable context and request digests; original
principal/time in the preparation journal; coordinator schema 18 and additive
embedded/service authority annotation schemas; initialization before published
binding/admission; separate reconciled reasons; context inspection; native Unix,
HTTPS QUERY/client, Python, CLI and MCP adapters. Annotation mutations remain P2.
The scoped coordinator authority protocol owns these organizational operations;
the worker-facing per-run lifecycle protocol does not gain annotation writes.

Development checks: baseline coordinator unit selection passed 24 tests; initial
context contract/integration selection with config extras passed 22 tests. The
expanded final selection is the approved `make validate-pr` across all lanes;
added coverage also exercises late failure with surviving output references,
HTTPS lost-response context replay, authenticated authority initialization,
QUERY read-only access and real MCP stdio context round-trips.

Initial final-gate attempt passed Ruff and stopped at type checking. P1 typing
issues were corrected. The manager explicitly authorized the narrow pre-existing
typing repair at `tests/unit/loom/queue/test_gpu_probe.py:93`: assert that retained
evidence is a mapping before inspecting `claim_retained`, preserving the original
assertion and production behavior. This is the only non-context repair.

Final-gate checkpoint: `make validate-pr` passed Ruff and Pyright (zero errors),
then failed the default lane: **3174 passed, 9 failed, 2 skipped, 360 deselected**
in 1453.94 seconds. Later lanes and build/lock/diff gates were not reached.
Evidence: `build/stage-42-p1-validate-pr.log` (local, ignored). Validated tree:
`056aff7f24fbb1703579187b3f3bd5f3f64cf09b`; only this completion record changed
after that gate. No subsequent runtime corrections or rerun were made because
the manager directed a blocked handoff after the running gate finished.

Remaining baseline failures are in
`tests/integration/queue/test_agent_session_transport.py` (two: exact capability
set and rejection-message expectation), `tests/package/test_runs_api.py`
(exports), `tests/unit/loom/authority/test_repository_run_lifecycle.py` (schema
version), `tests/unit/loom/queue/test_coordinator_upgrade.py` (four: version
expectations/unsupported-version fixture and schema-16 fixture shape), and
`tests/unit/loom/queue/test_local_daemon.py` (exact capability set). The MCP unit
tool-name expectation in `tests/unit/loom/mcp/test_server.py` also still needs
the new read tool; its lane was not reached. Expanded optional integration/MCP
coverage is unvalidated at this checkpoint.

Blocking contract decision: existing authored `RunOptions.tags` accepts arbitrary
string mappings (`src/loom/pipeline/runtime/options.py::_str_mapping`), but the
new effective-annotation initialization passes merged runtime tags through the
128-key/48-KiB submission-context limits. A supported config with 129 authored
tags and no explicit context can therefore fail before binding, conflicting with
this card's unchanged no-context invocation contract. Legacy projection uses the
same bounded annotation object. The manager must resolve whether/how existing
effective tags are grandfathered versus the accepted annotation limits before
implementation continues; no silent truncation or limit change is authorized.

| Item | Result |
| --- | --- |
| Implementation paths | `src/loom/{runs,queue,authority,pipeline/stores,cli,mcp}`, coordinator facade; new context/annotation helpers and additive schema migrations |
| Documentation | `docs/features/{coordinator-client,agent-preparation,cli,mcp}.md` |
| Tests | New context contract/integration files and existing native, authority, Python, MCP/QUERY adapters; narrow authorized GPU-probe typing repair |
| Completion | Blocked checkpoint; full gate failed; accepted behavior and required evidence not yet complete |
| Review/PR/merge/cleanup | Not started; manager-owned after contract resolution and passing validation |
