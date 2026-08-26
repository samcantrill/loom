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
  retirement. It names nine reference kinds, but
  `agent_coordinator_references` records only `delivery` rows and
  `retire_clean()` therefore proves only that narrow index empty. The same
  coordinator root also owns session state/tombstones, current offers and held
  polls, delivery rows, remote assignment/transfer state, ordinary controls,
  and assignment-control containment receipts.
- `src/loom/queue/agent_session_transport.py` owns the agent journal, retained
  mutations, HTTP adapter, and reference-digested retirement proof. Its
  `agent_session_references` rows also cover only deliveries. Its reachable
  old-session facts additionally include registration and mutation intents,
  held offer/poll state, ordinary and assignment controls, the execution
  journal's assignment/claim/result/event rows, and supervisor receipts.
- `src/loom/queue/local_daemon.py` and
  `src/loom/queue/local_daemon_execution.py` own guarded-recovery intent,
  authority arbitration, joined status, and recovery/physical-ownership facts.
  The execution store already makes `coordinator_assignments.session_id` the
  authoritative managed-assignment join; its atom/event/offer children follow
  that identity. The local or remote execution journal owns exact claim
  commands, provider-release state, process identity, result, events, and final
  availability. Status already projects agent controls, scheduling reloads,
  guarded recovery, and labelled owner revisions, but not a complete session
  inventory or replacement readiness.
- `src/loom/queue/local_daemon_transport.py`,
  `src/loom/queue/agent_session_transport.py`, `src/loom/queue/__init__.py`, and
  `src/loom/cli/queue.py` provide direct/socket/authenticated-HTTP/public/CLI
  seams. Reuse one typed operation and `ScopedAuthorizer`; adapters own no
  policy. The current operator action set has no replacement action and the CLI
  has no final recovery/replacement command, so those are deliberate Phase 9F
  additions rather than assumed harness.
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

The public operation is one operator-scoped request containing only a unique
replacement operation ID, stable `agent_id`, and bounded reason. It derives the
current old session under authorization; the caller supplies neither old/new
session ID nor containment/evidence. Its durable result reports the derived old
session, decision/readiness code, and a coordinator-minted new session only
after ordinary same-policy registration consumes the decision. A same-ID exact
request returns that result; a changed agent or reason conflicts. A different
credential may register the successor only when current protected policy still
maps it to the same stable agent and the one open replacement decision.

Keep two meanings separate:

- Replacement-decision eligibility requires a complete old-session projection
  and, for every member, either terminal plus physical release or exact
  target-owned containment followed by the accepted Phase 9E authority close.
  The latter may authorize only a fenced, zero-capacity successor.
- Replacement readiness additionally requires exact old physical release or a
  fresh successor-owned full provider observation that reflects/withholds every
  retained old claim, followed by a post-fence complete-reference recheck. Only
  then may one fresh availability revision be published and polling begin.

An unavailable old journal/supervisor is an explicit unavailable owner, never
an empty set. It can be covered only per already-enumerated assignment by exact
Phase 9E containment and closure; it cannot hide a coordinator assignment or
make an unscoped control/reference disappear. Conversely, one contained
assignment does not cover another assignment or an owner-wide completeness
failure.

Private row layout, helper names, query composition, intermediate states, and
diagnostic wording are discretionary. Add only one coordinator-owned durable
replacement decision/readiness record: enough to bind operation digest,
agent/derived-old/new identity, fence decision, owner projection digest/revision
tokens, and the readiness barrier/result. Owner rows remain authoritative; do
not duplicate their payloads into a generic reference ledger. Add no plugin
protocol, second recovery machine, adapter policy, compatibility reader, or
migration. Advance fresh schema/protocol identities as needed.

### Complete owner inventory and classification

Completeness is a closed owner inventory, not merely all rows currently present
in `agent_*_references`. The projection must produce a deterministic bounded
item for every applicable class below, or `complete = False` with the unavailable
owner/class named. Child rows are enumerated through their authoritative parent
assignment; absence is never a terminal fact.

| Reference class | Complete enumeration owner/path | Terminal, release, or containment fact |
| --- | --- | --- |
| Session protocol activity | Coordinator control root: session, offer, poll, delivery, and coordinator-reference rows keyed by derived old session | Fence invalidates offer/poll and forbids new delivery; every delivery joins an exact assignment and is resolved only at exact assignment release |
| Managed reservation and claim | Execution store: every `coordinator_assignments` row for old `session_id`, with atom, decision, offer, and coordinator-event children | Coordinator `released` plus agent/provider release is clean; `terminal` or `logical_released` still holds capacity; otherwise exact assignment containment plus Phase 9E close is decision-only eligibility |
| Coordinator remote execution | Coordinator control root: `remote_assignments` for the session, then deliveries, transfers, transfer authorizations, report/output fields, and assignment controls by assignment ID | Remote `RELEASED` and resolved delivery is clean; exact contained-and-closed assignment is decision-only eligibility; pending bytes/authorizations never imply release |
| Operator/control state | Coordinator and available agent control journals: every ordinary control by session and assignment control by joined assignment | Applied/failed plus acknowledged is terminal; exact contained assignment may settle only its assignment control; a pending unscoped control must be fenced and retained as superseded audit state |
| Agent request/provider/process state | Available agent execution journal and provider/supervisor owner: assignments whose immutable identity names the old session, claim commands, process/fence/launch identity, result, and provider state | Agent `RELEASED` or `DECLINED` with no prepared claim is clean; `PROVIDERS_RELEASED` still awaits publication; target-owned supervisor containment must match all immutable identities and the closed recovery receipt |
| Transfer/result/event/outbox state | Coordinator remote-transfer/report/event children and, when available, agent assignment result plus full sequenced event rows including acknowledgement | Committed terminal result and complete acknowledgement/release is clean; contained-and-closed parent covers late facts only because every old mutation boundary is tombstoned; unsent/unknown facts stay explicitly unavailable |
| Authority and recovery | Per-run authority snapshot and `recovery_operations`, joined from every old assignment's run/stage/attempt/fence/process identity | Ordinary exact terminal truth prevails; otherwise only a closed Phase 9E receipt with qualifying evidence and matching authority close qualifies; pending/failed/unknown recovery does not |
| Physical release/readiness | Exact agent journal/provider release, supervisor containment, coordinator release, and successor provider observations | Every old claim is released, or exact containment plus a fresh full successor observation reflects or withholds it; all provider kinds/configuration must be observed before readiness |

The projection owns no lifecycle truth. It validates joins and reports the
authoritative owners' facts. Unknown reference kind, malformed identity, missing
parent, duplicate conflicting parent, unavailable completeness-critical
coordinator store, revision regression, or an unavailable old owner that cannot
be bounded by the complete coordinator assignment inventory makes completeness
false and causes no replacement decision.

### Atomic fence and causal recheck

The cross-owner read is deliberately not called atomic. Use the existing daemon
mutation exclusion plus an old-session fence at the coordinator session owner:

1. Derive the sole open old session from authorized `agent_id`; reject before
   mutation if there is no unique current session or the owner inventory cannot
   enumerate every applicable class.
2. Read and classify a deterministic projection with each authoritative owner
   revision/digest. Reconcile any verified current-fence terminal fact through
   its existing ordinary path before considering Phase 9E closure.
3. Under the same exclusion used by assignment/delivery/control creation,
   re-read the session-facing revisions and complete assignment ID set. Only if
   they still match and all members satisfy decision eligibility, atomically
   persist the replay result, fence/tombstone the old identity, and invalidate
   its offers/polls. Every later reference-producing boundary must reject that
   old session before mutation; exact cleanup is restricted to its old IDs.
4. Permit only ordinary same-agent registration to mint and bind a new session.
   Its readiness remains durable false, capacity is zero, offers are rejected,
   and no work poll can start.
5. After fresh protected configuration reconstruction and a full observation
   from every configured provider, enumerate the complete old-session set again.
   Compare the original identity set and owner revision/digest lineage, admit
   only monotonic terminal/release/audit additions, and fail closed on a new
   assignment, conflicting identity, unavailable owner, or regression.
6. In the readiness transition, bind the fresh observation and post-fence
   projection digest durably before publishing exactly one fresh full
   availability revision. A crash at either side replays or remains at zero;
   it never publishes from the registration revision or old offer.

Do not hold a SQLite transaction across external authority, supervisor, or
provider calls. The durable fence prevents new old-session effects; revisioned
post-fence recheck and the zero-capacity gate provide the cross-store safety.

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
| Replacement sees every old-session reference | Coordinator joined projection over the closed inventory above | Omitted owner/table, missing parent, unavailable owner mistaken for empty, or partial read | Hidden live work overlaps new capacity | One seeded member per class plus unavailable/malformed owner negatives |
| Eligibility uses authoritative release or exact containment | Existing authority, provider/supervisor, and recovery owners | Weak caller evidence or lifecycle-only close | Duplicate physical effects | Weak-evidence negatives and close-before-release cases |
| New session inherits nothing | Session owner plus agent/provider journal | Copied old identity/revision/token/state | Cross-session mutation or double allocation | Fresh-identity and stale-fact matrix |
| Fence and readiness close the non-atomic cross-owner gap | Session mutation fence plus durable replacement/readiness owner | Assignment/reference appears between projection and decision or late fact appears before availability | Incomplete decision or early capacity | Before-fence and before-readiness race tests with revision/digest change |
| Capacity follows a fresh physical observation | Agent provider/availability owner | Registration revision, partial provider observation, or early offer/poll after replacement | Unsafe capacity advertisement | Zero-capacity barriers through every provider observation and post-fence recheck |
| Every public path invokes one authorized operation | Queue application plus `ScopedAuthorizer` | Route- or CLI-specific policy | Divergent auth/lifecycle semantics | Python/direct/socket/HTTP/CLI parity |

## Implementation Slices

1. Extend the existing session/recovery application owner with the closed,
   deterministic projection and classification above. Add only semantic owner
   queries needed to enumerate direct session rows and assignment children;
   do not expose generic CRUD or copy owner payloads.
2. Add the replay-safe replacement decision/readiness record, atomic old-session
   fence/tombstone, invalidation of offers/polls, and the one-registration
   successor gate. Advance fresh root/protocol identities with no reader or
   migration for current version-6 state.
3. Enforce stale-old-session rejection at assignment creation, delivery,
   control, transfer authorization/chunk, start/event/result/output/commit, and
   offer/poll boundaries. Preserve only exact idempotent cleanup against old
   assignment/process/fence/operation IDs, unable to touch successor state.
4. Reconstruct successor configuration, obtain one full observation across all
   configured providers, re-enumerate old references, and durably cross the
   readiness barrier before one fresh availability publication. Extend joined
   status with bounded owner/class counts, completeness, decision, physical
   release, observation/recheck, readiness, and withholding reason.
5. Wire the typed request/result through public Python/direct, Unix socket,
   authenticated HTTP, and CLI using the same application operation and
   authorizer. Add only the `replace_session` operator action/agent target scope;
   update existing recovery/reliability guidance rather than adding a second
   workflow.
6. Add the causal tests below, run the full repository gate, and generate the
   final Stage 29 summary from the final tree.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Typed public surface stays intentional and cheap | Imports succeed without queue side effects or new heavyweight dependency |
| Unit | Required | Complete projection, eligibility, replay, hard cut | Seed one item per inventory class; unavailable/malformed/missing-parent/unknown-kind makes `complete = False`; weak evidence and close-without-physical-readiness stay withheld; exact replay is stable and conflicting operation reuse fails |
| Contract | Required | Authorization and transport parity | Request has operation ID/agent/reason only; unauthorized action/agent rejects before reads or mutation; direct/socket/HTTP/CLI return identical safe result/failure shape and redact secrets/paths/evidence payloads |
| Integration | Required | Atomic fence/recheck and zero-capacity readiness | Inject a new assignment/reference before decision recheck and a changed owner revision before readiness; neither publishes capacity; crash before/after decision, successor bind, observation bind, and availability publication replays one decision/session/publication |
| Integration | Required | Complete cross-owner classification | Multi-assignment case includes coordinator reservation/atoms/events, delivery/transfers/auth, controls, agent claim/result/outbox, supervisor, authority/recovery, and release; containment for one assignment never covers its sibling or an unscoped pending control |
| Integration | Required | Successor isolation and stale facts | Ordinary same-policy registration mints a different session with no inherited claim/request/revision/transfer/token/process/event/outbox; every delayed old mutation rejects with unchanged successor snapshot; exact old cleanup advances only old release/readiness evidence |
| E2E | Required | Final managed/SLURM restart-recovery-replacement story | Fresh coordinator/agent processes, one managed launch and one SLURM submit, authoritative terminal-versus-contained close, lost old root represented unavailable, different successor session, no offer/poll before fresh full observation and recheck |

Keep the causal matrix narrow:

- In `tests/unit/loom/queue/test_agent_sessions.py`, cover the typed request,
  derived-session authorization/replay, closed class inventory, and deterministic
  digest/classification. Do not multiply every class by every adapter.
- In `tests/unit/loom/queue/test_local_daemon.py`, cover application/status
  semantics, pre-mutation rejection, redaction, and the zero-readiness gate.
- In `tests/integration/queue/test_agent_session_transport.py`, exercise remote
  control/execution journals, supervisor evidence, authenticated HTTP parity,
  lost-root/unavailable-owner behavior, stale-message rejection, and the two
  revision-change races.
- In `tests/integration/queue/test_local_daemon_production.py`, exercise the
  coordinator assignment/agent journal/provider join, crash boundaries,
  embedded successor isolation, and one fresh availability publication.
- In `tests/integration/queue/test_slurm_ready_stage.py`, retain a focused
  regression that replacement neither treats SLURM state as agent-session state
  nor releases a closed-but-physically-held SLURM slot.
- In `tests/integration/queue/test_cli_operations.py` and
  `tests/e2e/test_queue_cli.py`, prove CLI/direct/socket operation parity and one
  fresh-process operational story; reuse the existing recovery harness rather
  than building a second daemon fixture.

Targeted commands:

    pytest -q tests/unit/loom/queue/test_agent_sessions.py tests/unit/loom/queue/test_local_daemon.py
    pytest -q tests/integration/queue/test_agent_session_transport.py tests/integration/queue/test_local_daemon_production.py tests/integration/queue/test_slurm_ready_stage.py tests/integration/queue/test_cli_operations.py
    pytest -q tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks are an omitted owner class, an unavailable owner presented as
  empty, a cross-store assignment race, stale facts reaching successor state,
  registration/partial observation enabling early capacity, adapter policy,
  secret leakage, or stale validation.
- Independent implementation review must start from the inventory table and
  trace every old-session-producing mutation to the durable fence, then trace
  every availability/poll entry to the durable readiness gate. A table or row
  count alone is not evidence of causal completeness.
- Stop if any listed owner lacks a bounded query for its old-session or
  assignment-linked facts, if an existing mutation can create a new old-session
  assignment/reference without passing the common durable fence, if a provider
  cannot report a fresh full observation that reflects/withholds retained
  claims, if eligibility requires inference from absence, or if safe
  replacement needs a new product/public/trust decision not fixed above.
- Do not stop merely because the old journal/supervisor is unavailable at
  runtime: preserve that unavailability in the projection and require exact
  per-assignment containment/close plus successor observation. Stop if the
  coordinator's durable assignment inventory is itself incomplete, because
  containment then cannot be scoped completely.
- Accepted risk: effects may repeat after explicit containment and capacity
  remains withheld while evidence is unknown.

## Executor Handoff

- Read this complete plan, the completion records in Phase 9C2, Phase 9D2, and
  Phase 9E, and only the `Session replacement` contract in blocked Phase 9.
- Implement the six slices while preserving existing owner boundaries. Begin by
  writing the complete inventory query/classifier and its one-member-per-class
  causal test; do not begin transport wiring until decision and readiness tests
  prove the fence/recheck sequence.
- Do not reopen compatibility, caller-selected identity, weak containment,
  automatic replacement, or the already accepted Phase 9E arbitration/retry
  design. Keep replacement authorization distinct from recovery outcome and
  ordinary agent registration. Do not edit roadmap metadata, perform GitHub
  operations, or delegate.
- Before handoff, audit all writers of the inventory classes and all offer/poll
  entry points against the fence/readiness gates; record only causal tests, not
  a broad Cartesian matrix.
- Stop under the exact conditions in `Risks, Review, And Stops`; especially do
  not fabricate completeness from an unavailable coordinator owner or solve a
  gap with a generic ledger/second state machine.

## Workflow State

- Manager preparation: complete at base `2412862`; source/harness facts refreshed
- Expanded planning: complete; refined complete-owner enumeration, authoritative
  incomplete-owner handling, atomic fence/post-fence recheck, minimum durable
  replacement/readiness state, public operation shape, causal tests, and stops
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
