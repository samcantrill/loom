# Phase 9F Execution Plan: Session Replacement And Recovery Operations

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 9F
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9f-session-replacement-recovery-operations`
- Worktree root: `/home/can134/work/active/loom-worktrees`
- Worktree path: `/home/can134/work/active/loom-worktrees/stage-29-p9f-session-replacement-recovery-operations`
- Base revision: `241286265f066548374ce44df23ccf4ed4700a7f`, current
  `origin/develop` after the Phase 9E metadata merge
- PR target: `develop`
- PR title: `feat(scheduling): close recovery operations and replacement`
- Dependencies: Phase 9C2 `b0ed116`, Phase 9D2 `82b311f`, and Phase 9E
  `0dab7a9` are merged. Blocked Phase 9 retains the approved replacement
  contract as read-only evidence.
- Workflow path: expanded. The concrete trigger is a complete-reference join
  across coordinator, agent journal, provider/supervisor, authority/recovery,
  and transport owners; an omission can expose capacity beside old live work.
- Blocker corrections: 0/3

## Objective And Context

Complete Stage 29 by replacing a lost session only after every retained
reference is terminal-and-released or covered by qualifying containment and its
close/release saga. A new identity starts at zero capacity and cannot poll until
fresh provider/configuration truth is fully observed. Finish authenticated
operations, guidance, fresh-process E2E proof, and final repository evidence.

This is a hard cut. There is no compatibility reader, migration, import, or
adoption path for old roots, schemas, profiles, descriptors, or copied state.
Missing, incompatible, or incomplete protected evidence fails closed and
requires explicit fresh initialization or guarded recovery.

## Current Source And Harness

- `src/loom/queue/agent_sessions.py` owns protocol-v6 sessions and clean
  retirement. It names nine reference kinds, but its coordinator table records
  only deliveries; `retire_clean()` therefore checks an incomplete set.
- `src/loom/queue/agent_session_transport.py` owns the agent journal, retained
  mutations, HTTP adapter, and reference-digested retirement proof. Its current
  session-reference rows also cover only deliveries.
- `src/loom/queue/local_daemon.py` and
  `src/loom/queue/local_daemon_execution.py` own guarded-recovery intent,
  authority arbitration, joined status, and recovery/physical-ownership facts.
  Status already projects agent controls, scheduling reloads, and guarded
  recovery, but not a complete session inventory or replacement readiness.
- `local_daemon_transport.py`, `agent_session_transport.py`,
  `queue/__init__.py`, and `cli/queue.py` provide direct/socket/HTTP/public/CLI
  seams. Reuse one operation and authorizer; adapters own no policy.
- Primary unit, integration, CLI, and E2E seams are the targeted test files
  below; existing recovery tests already exercise fresh managed processes and
  simulated SLURM.
- Keep `loom.scheduling` import-light. Session/recovery behavior stays in queue
  application infrastructure, while authority terminal truth and provider/
  supervisor physical truth remain with their existing owners.

## Scope

In scope:

- Build one deterministic old-session projection spanning assignments, provider
  preparations/claims, deliveries/work requests, controls, transfers,
  results/outputs, events, outbox, releases, recovery, and supervisor evidence.
- Classify every reference using owner facts. Replacement is eligible only when
  enumeration itself is complete and each item is terminal-and-physically-
  released, or has exact target-owned positive containment followed by the
  accepted lifecycle close and release/reconciliation state.
- Add one replay-safe scoped operator operation that fences/tombstones the old
  identity. The caller cannot choose a session ID or supply containment.
- Admit an ordinary coordinator-minted session for the same policy-bound agent.
  It inherits no claim, request, revision, transfer, token, process, launch,
  event sequence, or outbox state.
- Hold capacity at zero until fresh reconstruction, physical observation,
  old-reference recheck, and a fresh availability publication complete.
- Reject every delayed old-session mutation using immutable session,
  assignment, process, execution-fence, and operation identities.
- Extend redacted joined status with reference classification, evidence,
  arbitration/retry, physical release, readiness, and withholding reason.
- Expose status, guarded close, and session replacement consistently through
  public Python/direct, Unix socket, authenticated HTTP, and CLI paths; update
  reliability/operations guidance and close Stage 29 validation evidence.

Out of scope:

- Automatic replacement/recovery, HA, power fencing, checkpoint migration,
  legacy import, inferred containment, repair tooling, or route fallback.
- Moving authority lifecycle truth, provider physical truth, or authorization
  policy into the reference projection, transport, CLI, or presentation layer.

Assume policy still maps the credential to the same stable agent; otherwise
reject. Only Phase 9E exact containment/close receipts qualify. Absence,
operator prose, `scancel`, credentials, and an empty root do not.

## Fixed Contracts And Private Discretion

Replacement checks the complete set, not a convenient subset:

```python
references = coordinator.list_complete_session_references(old_session_id)
if not references.complete:
    return ReplacementRejected("incomplete_reference_enumeration")
if not all(
    item.terminal_and_released or item.qualifying_containment
    for item in references.items
):
    return ReplacementRejected("incomplete_containment")
```

The availability order is fixed:

```text
old complete reference set resolved
  -> old identity fenced and replacement decision durable
  -> new protected session identity created
  -> zero availability and no work polling
  -> fresh provider/configuration observation recorded
  -> retained ownership rechecked
  -> one fresh full availability observation published
  -> work polling enabled
```

Exact replay returns the durable result; conflicting reuse fails. Old facts are
audit-only, while exact late cleanup may affect only its old claim. Status never
exposes secrets, tokens, private paths, credentials, or unbounded payloads.

Private row layout, helpers, query composition, states, and wording are
discretionary. Add no plugin protocol, second recovery machine, adapter policy,
or compatibility layer. Advance fresh schema/protocol identities as needed.

## Proportionality

- Reuse the session service, authorizer, recovery receipts, containment,
  authority CAS, provider release, joined status, and dispatch seams.
- Add only the durable replacement decision/readiness state and complete joined
  projection required by this current operation. Do not duplicate every owner
  row into a generic ledger when deterministic owner queries can remain
  authoritative.
- Defer automation, external fencing, pruning, and disaster restoration.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Replacement sees every old-session reference | Coordinator joined reference query | Omitted owner/table or partial read | Hidden live work overlaps new capacity | Causal omit/include test for every reference class |
| Eligibility uses authoritative release or exact containment | Existing authority, provider/supervisor, and recovery owners | Weak caller evidence or lifecycle-only close | Duplicate physical effects | Weak-evidence negatives and close-before-release cases |
| New session inherits nothing | Session owner plus agent/provider journal | Copied old identity/revision/token/state | Cross-session mutation or double allocation | Fresh-identity and stale-fact matrix |
| Capacity follows a fresh physical observation | Agent provider/availability owner | Early offer/poll after replacement | Unsafe capacity advertisement | Zero-capacity barriers through full observation |
| Every public path invokes one authorized operation | Queue application plus `ScopedAuthorizer` | Route- or CLI-specific policy | Divergent auth/lifecycle semantics | Python/direct/socket/HTTP/CLI parity |

## Implementation Slices

1. Add the complete deterministic owner projection, eligibility classification,
   durable replay-safe replacement decision, old-session fence/tombstone, and
   new-session zero-availability barrier.
2. Enforce fresh reconstruction and stale-old-fact rejection at every reachable
   mutation boundary; extend joined status with bounded owner-labelled evidence.
3. Wire the one domain operation through public Python/direct, Unix socket,
   authenticated HTTP, and CLI surfaces; update hard-cut operational guidance.
4. Add causal unit/contract/integration/fresh-process E2E coverage, run the full
   repository gate, and generate the final Stage 29 summary from the final tree.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Typed public surface stays intentional and cheap | Imports succeed without queue side effects or new heavyweight dependency |
| Unit | Required | Complete projection, eligibility, replay, hard cut | Every kind included; partial/weak evidence rejects before mutation; conflicting replay fails |
| Contract | Required | Authorization and transport parity | Least privilege and identical result/failure shape across supported adapters |
| Integration | Required | Cross-owner state, zero start, stale facts | Multi-assignment/provider/outbox cases; old facts cannot touch new identity; availability waits for fresh observation |
| E2E | Required | Final managed/SLURM restart-recovery-replacement story | Fresh processes, one launch/submit, correct terminal-versus-close result, different session, no early capacity |

Targeted commands:

    pytest -q tests/unit/loom/queue/test_agent_sessions.py tests/unit/loom/queue/test_local_daemon.py
    pytest -q tests/integration/queue/test_agent_session_transport.py tests/integration/queue/test_local_daemon_production.py tests/integration/queue/test_slurm_ready_stage.py tests/integration/queue/test_cli_operations.py
    pytest -q tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks are an incomplete/non-atomic join, stale facts reaching new state,
  early capacity, adapter policy, secret leakage, or stale validation.
- Expanded plan refinement must focus on the complete owner inventory,
  authoritative completeness marker, atomic/recheck boundary, and the minimum
  durable replacement/readiness state. Independent implementation review must
  repeat the complete-reference and stale-fact audit.
- Stop if any supported owner cannot enumerate its old-session references, if
  eligibility needs inference from absence, or if safe replacement needs a new
  product/public/trust decision not fixed above.
- Accepted risk: effects may repeat after explicit containment and capacity
  remains withheld while evidence is unknown.

## Executor Handoff

- Read this complete plan, the completion records in Phase 9C2, Phase 9D2, and
  Phase 9E, and only the `Session replacement` contract in blocked Phase 9.
- Implement the four slices while preserving existing owner boundaries.
- Do not reopen compatibility, caller-selected identity, weak containment,
  automatic replacement, or the already accepted Phase 9E arbitration/retry
  design. Do not edit roadmap metadata, perform GitHub operations, or delegate.
- Stop if an owner cannot enumerate references, safe recheck is impossible, or
  a new public/trust decision is required.

## Workflow State

- Manager preparation: complete at base `2412862`; source/harness facts refreshed
- Expanded planning: pending one `loom_phase_planner` pass for complete-owner
  enumeration, atomic recheck, and minimum durable replacement/readiness state
- Implementation: pending
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: required after validation for complete-reference and
  stale-fact safety
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none yet |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
