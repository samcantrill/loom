# Phase 1 Execution Plan: Submission Context

## Metadata

- Status: merged; stage 42 / P1.
- PR: [#349](https://github.com/samcantrill/loom/pull/349), target `develop`.
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
   without context behaves unchanged except for the explicitly approved limits
   on all initial tags (run-context Transport And Limits). The same fixture drives both transports
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
or many-to-one submission semantics. Manager preparation passed.
One phase executor was selected for the cross-cutting store,
replay and adapter implementation scope; it owns implementation and validation,
not PR delivery. Pre-submit validation, independent phase review and PR/merge:
passed. Independent review found no required corrections; delivery verified remote merge.
Refiner: not needed. Blocker corrections: 1/3. Improvement entries: none.

Execution resumed after the maintainer explicitly selected universal initial-tag
limits on 2026-09-25. No grandfathering is permitted. One directly related executor
repair completed the validation failures and added the clarified limit coverage.

## Completion Record

Implementation coverage: bounded immutable context and request digests; original
principal/time in the preparation journal; coordinator schema 18 and additive
embedded/service authority annotation schemas; initialization before published
binding/admission; separate reconciled reasons; context inspection; native Unix,
HTTPS QUERY/client, Python, CLI and MCP adapters. Annotation mutations remain P2.
The scoped coordinator authority protocol owns these organizational operations;
the worker-facing per-run lifecycle protocol does not gain annotation writes.

The manager explicitly authorized the narrow pre-existing
typing repair at `tests/unit/loom/queue/test_gpu_probe.py:93`: assert that retained
evidence is a mapping before inspecting `claim_retained`, preserving the original
assertion and production behavior. This is the only non-context repair.

Repair coverage: initial effective tags now fail terminally with `invalid_context`
when limits are exceeded, rather than remaining in retryable reconciliation.
Native integration checks authored-only overflow, merged overflow, serialized
payload overflow, valid UTF-8/key/count boundaries, no successful binding or target
admission on rejection, and nonmutating partial inspection of oversized legacy
evidence. The schema-17 migration now preserves its existing action-result tables;
it previously attempted to create them again. Regression coverage preserves the
original intent columns, unknown accepted time, backups, retained worker journals,
and schema-15/16 migration paths. Lost-publication replay tests allow only the new
annotation initialization while retaining all lifecycle/provenance rows and exact
non-authority file bytes. Capability/export/MCP expectations match the new surface.

Validation completed on 2026-09-25 using `loom-targeted-validation`, with fresh
passing evidence reused rather than repeating unaffected lanes:

- Focused affected regressions: 54 tests passed before a new limit-test assertion
  was corrected; the complete context integration file then passed **10 tests**.
- Required `make validate-pr` passed Ruff, Pyright and the full default lane:
  **3185 passed, 2 skipped, 365 deselected**. Config-extra ran completely with
  **311 passed, 7 failed, 15 skipped, 3237 deselected**. Its seven failures were
  obsolete schema/fixture and whole-authority-file expectations, not production
  failures. Evidence: `build/stage-42-p1-repair-validate-pr.log`.
- Only those two optional test files changed afterward. All seven failing node
  cases passed together (**7 passed in 55.73s**) via isolated config-extra pytest:
  `test_preparation_operations.py::test_upgrade_reopens_real_nonterminal_admission_and_retained_worker_journal`,
  `test_preparation_operations.py::test_restart_reuses_capture_and_replays_a_claimed_complete_target`
  (five parameters), and
  `test_reconciled_runs.py::test_schema_upgrade_preserves_accepted_exact_intent_and_cancel_receipt`.
  The other 311 config-extra passes and all default-lane evidence remain valid.
- `make -o test-no-extra -o test-config-extra validate-pr` completed the remaining
  gate successfully: Ruff, Pyright (**zero errors**), MCP (**46 passed**) and
  source/wheel builds. Evidence: `build/stage-42-p1-repair-remaining-gate.log`.
  This is a completed gate with targeted repair/reuse, not a claim of one entirely
  passing unmodified umbrella invocation. No summary rerun was required.
- Validated final source/test tree: `d70684ec02a306330d1f72f7727cf4e4a111b16f`.
  Only this completion record changed afterward; staged diff whitespace passed.

Logs are local ignored build evidence. The 15 config-extra skips are opt-in
physical container acceptance; the two baseline skips are existing queue CLI
cases. No physical GPU, scheduler or container-fleet qualification is claimed or
required by this context-only phase. No remaining implementation blocker is known;
the independent actual-head review passed at `0812f83fd8abdae48e5100a52c20fb0ad8f01310`
with no required findings. PR #349 squash-merged into `develop` as
`ea4dba287c3d620c7be59356def76bd8d2bc53ad` on 2026-09-25.

Resolved contract decision: on 2026-09-25 the maintainer explicitly accepted
the 128-key/48-KiB limits for all initial tags, including authored-only tags.
The run-context contract owns this intentional compatibility exception.
Assertions cover rejection before binding/target execution and unchanged
persisted legacy evidence on partial inspection; no truncation or grandfathering.

| Item | Result |
| --- | --- |
| Implementation paths | `src/loom/{runs,queue,authority,pipeline/stores,cli,mcp}`, coordinator facade; new context/annotation helpers and additive schema migrations |
| Documentation | `docs/features/{coordinator-client,agent-preparation,cli,mcp}.md` |
| Tests | New context contract/integration files and existing native, authority, Python, MCP/QUERY adapters; narrow authorized GPU-probe typing repair |
| Completion | Implementation and gate coverage complete with explicit focused repair/reuse above; ready for manager delivery |
| Review/PR/merge/cleanup | PR #349 independently approved and remotely merged; delivery deleted the exact remote phase branch; transition to coordination passed; persistent worktree retained for P2 |
