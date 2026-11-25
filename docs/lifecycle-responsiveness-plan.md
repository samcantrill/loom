# Loom lifecycle responsiveness implementation plan

The design uses Loom `91a2e86e98b1` as its baseline. Each numbered section describes the blocking path on that revision, its proposed replacement, and a test that would distinguish the two. The implementation evidence and outstanding work at the end refer to the local candidate branch. Source references are relative to the Loom repository. Python snippets show proposed control flow. Identifiers newly introduced in a snippet describe the change to implement. The SQL snippets identify the intended production query shapes.

## What an acknowledgement means

A client may be waiting for different events. For a cancellation, Loom can return an operation ID when the coordinator commits the request. An agent can later acknowledge receipt, the supervisor can request a stop, the execution owner can establish containment, and the resource owner can release the claim. Terminal cancellation requires the relevant owners to settle. For an artifact, the analogous distinctions are result committed, declaration visible, bytes received, integrity checked, and verification receipt committed. Attach each reply and status field to the event it actually establishes.

The investigation recorded a renewal with 1.264 s of coordinator lock wait, a start permit with 789 ms of lock hold across two acquisitions, and an image-retention task with 28.355 s of worker wait for 10.5 ms of execution. They are individual observations. They identify three different places to measure and fix. A job can increase traffic and expose the coupling even when that job is healthy. The existing five-agent fixture passed on the reference revision with p99 renewals of 0.211 s across 360 normal samples and 0.124 s across 752 samples during its 31.5 s injected delay. This fixture exercises one slow-I/O path. Each additional source of coupling below needs its own reproduction. [Existing qualification scope](coordinator-responsiveness.md) · [Five-agent fixture](../tests/integration/queue/test_coordinator_responsiveness.py)

| Order | Deliver together | User-visible result |
|---|---|---|
| 1 | Coordinator writes, offer lookups, observer dispatch | A busy writer, historical offers, or another run’s sink stop delaying independent control reads and run mutations. |
| 2 | Agent release, transport capacity, TLS accept, reconciler turns, cancellation fan-out | An independent agent or assignment can connect, start, receive a stop and report progress during transfers or containment. |
| 3 | Event acknowledgement, SLURM task pages, keyed watches and fleet reads | New feedback costs scale with the new events, requested page and affected owners. |
| 4 | Artifact verification, fleet check observation, sweep submission window | Verified checks become visible as they finish and independent trials can be admitted together. |

Start each wave with a test that holds the identified dependency at a barrier. Assert the other owner completes before releasing the barrier. Use timeouts as test deadlock guards. Then exercise replay or a concurrent change at the new boundary. Keep each numbered change separately reviewable, with its relevant tests and documentation.

### Which acknowledgement a caller can act on

| Caller is waiting for | First durable acknowledgement | What establishes completion |
|---|---|---|
| Assignment start | Coordinator accepts the exact assignment and fence | The start permit survives the final cancellation check, and the execution owner records the matching started evidence. |
| Drain or cancellation | The coordinator records the requested control or cancellation epoch | The agent records receipt, each affected owner proves containment, and each required claim is released. Drain may stop new work while existing releases are pending. |
| Agent event | The event owner persists the contiguous sequence and confirms the exact request | The sender advances the proven workspace range. The terminal handoff includes the last event the producer supplied. |
| Fleet check | The check operation retains the admission identity | The result is committed and the check owner retains the required verification receipt. A caller's observation deadline can expire in between. |
| Waiting sweep | The manifest retains the trial identity and the coordinator accepts its operation | The trial's terminal observation frees a submission slot. An uncertain send continues to own its slot. |

Use these boundaries when timing the feedback. For example, measure cancellation request-to-receipt separately from receipt-to-containment for each assignment. A slow stop on A belongs in A's containment time. If B's first stop is also delayed, inspect the dispatch queue before tuning containment.

### Implementation dependencies

| Deliverable | What must be in place first | Reason |
|---|---|---|
| Short writes and indexed offers (1–2) | Correlated timings and the pinned baseline | A registry write can incur both lock wait and history-dependent SQL cost. Measure the two separately. |
| Observer delivery and TLS acceptance (3, 5) | A run-scoped mutation owner for callbacks, or a socket owner through authentication for TLS | These can ship independently. In both cases shutdown must account for the worker until it actually exits. |
| Agent release and transport capacity (4) | Exact recoverable release evidence before relaxing the gate, plus compatible sender and receiver classification | Freeing one end of an exchange leaves a queue at the other. A timed-out release may already have succeeded. |
| Reconciliation and cancellation (6–7) | Durable cancellation epoch and bounded external workers | The coordinator can rotate only after a turn returns. Stop delivery needs a worker even when all containment waits are slow. |
| Events, task pages and watches (8–10) | Page/sequence boundaries, revalidation of actionable evidence, and post-commit notification | Local SQL and fleet-read changes can ship independently. Enable wire extensions only after negotiation and old-peer tests. |
| Artifact verification and sweeps (11–12) | Check/trial receipts stable across detachment | A lost reply must resume the original admission. Both changes can proceed independently once their own receipt contracts are tested. |

Use the component's existing authority as the recovery point. For example, a cancelled start is decided by the final coordinator transaction, an uncertain physical release is resolved from the agent's provider proof, and a completed artifact check is established by its verification receipt. These choices determine where to place barriers in the tests and which evidence survives a restart.

## 1. Release broad guards before SQLite contention waits

**Current path.** `_poll_write` already sets an immediate SQLite busy response and releases the daemon state guard between attempts. Registration acquires a serialization decorator outside the transaction. Preparation acceptance and other transitions enter `BEGIN IMMEDIATE` inside the guard. The connection’s busy handler can therefore park a thread that still owns the process lock. Even a control read on a different session can queue behind it. Start permission has an additional cost. Both guarded checks load JSON and reconstruct the same delivery bundle. [Polling, registration, transfers and start permission](../src/loom/queue/agent_sessions.py) · [Preparation acceptance](../src/loom/queue/_preparation_operations.py) · [Admission transitions](../src/loom/queue/_coordinator_admission.py)

**Change.** Extract the transaction mechanics from `_poll_write` into a coordinator helper. Inventory registration/reconciliation, admission and retry, offer publication, start permission, and assignment/transfer write boundaries. Classify each guarded block by SQL, immutable preparation, external effect and post-commit action. Open the connection and set its busy timeout before entering the guards. Preserve the established ordering for operations that also require the scheduling-reload guard. On every attempt repeat operation-specific authorization, lifetime and fence checks. Roll back on failure, including a busy commit. Retry only SQLite's recognized busy condition up to the original deadline. Wake listeners after commit. Keep process-local generation changes synchronized with a successful commit when their semantics require it.

```python
delivery = load_exact_delivery(request)
prepared = decode_delivery(delivery.payload)       # outside the state guard
authority_ok = observe_start_authority_once(request, prepared)

def apply(conn):
    current = read_current_start_facts(conn, request)
    require_same_delivery_and_fence(current, delivery)
    require_current_session_policy_and_staging(conn, current, prepared)
    if current.cancelled or not authority_ok:
        return False
    return record_start_permission(conn, current)

return retry_short_write(apply, required_guards, deadline)
```

The critical detail is the scope of the retry. A decorator acquiring the same lock outside this helper would reintroduce the original wait. The connection is configured for an immediate busy response for the entire loop.

```python
def retry_short_write(apply, required_guards, deadline):
    with connection_with_zero_busy_timeout() as conn:
        while True:
            try:
                with acquire_in_existing_order(required_guards):
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        receipt = apply(conn)
                        conn.commit()
                    except BaseException:
                        conn.rollback()
                        raise
                return receipt
            except sqlite3.OperationalError as exc:
                if not sqlite_busy(exc) or monotonic() >= deadline:
                    raise
            sleep_until_next_attempt(deadline)
```

Authorize the initial read before accessing a protected delivery. Stale identity or a superseded grant follows the existing conflict path. Keep provider actions, authority calls and filesystem I/O outside retryable callbacks. For input chunks, authorize before and after reading the exact bytes. Expiry checks can advance the accepted-time high-water mark, so place those writes through the same short transition. A real competing SQLite writer will still delay another writer. It should leave independent reads and unrelated daemon state accessible.

One remaining caller needs a different replay boundary. `LocalDaemonExecution._reservation_guard` holds the scheduling guard and the control database transaction across `coordinator.reserve(...)` on the execution store. The SLURM reservation also receives this guard. Retrying the entire block after a busy control-database commit could execute a reservation that already committed in the other store. Bind the work to the existing immutable assignment and attempt first. Use nonblocking acquisition at the guarded entry, validate the current target and cancellation epoch, and recover an uncertain execution-store write by looking up that exact reservation. Revalidate eligibility before issuing a physical start. Test both database boundaries independently, including cancellation or reload between reservation and launch. [Reservation guard and callers](../src/loom/queue/local_daemon_execution.py)

At the cross-store boundary, give the scheduling turn three possible outcomes. A busy store yields a pending assignment. A matching committed reservation resumes the existing operation. A mismatched reservation enters the existing conflict/recovery path. Keep the immutable identity across every retry, and account for a reservation committed in the execution store even if a subsequent control-store write fails. Consumers that sample a scheduling generation must observe this change. A final eligibility check has to serialize with cancellation when granting permission to start.

```python
identity = existing_assignment_and_attempt(work)
outcome = attempt_reservation_without_waiting(identity, expected_offer, epochs)
if outcome.uncertain:
    return reconcile_exact_reservation(identity)
if outcome.busy:
    return pending(identity)
return advance_after_current_authority_check(identity)
```

In the embedded path, narrow the scope of the actual `reservation_guard()` passed to `run_managed_local_assignment()`. Its body currently spans the execution-store reserve, authority bind, bound-state advance and local journal write. After a matching logical reserve, the capacity already has a durable owner. Schedule the bind and journal work under that assignment, recheck the exact attempt and cancellation before the grant, and let subsequent turns rediscover the retained reservation. Pause each of these effects in a native integration test, commit another run's control, then restart after each durable handoff and check for a single grant and launch. [Embedded reservation body](../src/loom/queue/_managed_local.py)

Review the reservation change in two pieces. First prepare the immutable native decision receipt, claim atoms and assignment identity outside the guards. For SLURM retain the exact delivery, request digest and input paths. Keep the mutable offer, capacity, run/profile limits, cancellation and scheduling epoch checks at their current authorities. Open existing stores outside the process guards, preserve the scheduling → daemon → control writer → execution writer order on paths that acquire all four, and use immediate busy responses at both writer boundaries. On contention before an effect, release every enclosing guard and return the same work for a later turn. A control commit can fail after the execution commit succeeded. Use the execution owner's existing identity and receipt comparison to recover that outcome. Invalidate outstanding ownership observations even in this partial-commit case. [Native reservation replay](../src/loom/queue/_managed_local.py) · [SLURM reservation replay](../src/loom/queue/slurm_ready_stage.py)

Second, transfer the remaining bind, bound-state advance and request journal write to the exact assignment owner. The local worker's presence protects that handoff while it is alive. A restart loses the worker. The missing request in the local journal then says nothing about whether the run authority already committed a bind. For a cancelled reservation, require the authority to settle the exact binding against the cancellation epoch. A proven absent binding or an exact unbind receipt can settle a pre-grant reservation. A retained grant requires its original fence and execution recovery. Unavailable or contradictory evidence keeps the claim pending. Use the same authority contract for remote and embedded callers that can reach this gap. [Cancellation join](../src/loom/queue/local_daemon_execution.py) · [Binding, unbind receipts and grant replay](../src/loom/pipeline/stores/sqlite_authority.py)

Audit the embedded wrapper as well as its body. Its precondition calls `_install_cancellation_if_requested()` under `_cycle_lock`. On an existing request this can detach the action graph and install the cancellation epoch at the run authority. Its exit calls `_activate_admission()` through a fresh control writer while the same lock is held. Split those effects out. Under the guarded reservation check, an applicable durable cancellation request must withhold the reservation immediately while the cancellation owner installs its epoch. After a successful reserve, use the existing conditional activation update, which already checks `cancellation_operation_id IS NULL`, then wake the scheduler. A late activation must preserve an intervening cancellation. [Embedded wrapper and cancellation effects](../src/loom/queue/local_daemon_execution.py) · [Conditional activation](../src/loom/queue/local_daemon.py)

| Inject failure or pause | Required observation |
|---|---|
| Competing control writer or execution writer before reserve | Another agent reads its controls during the hold. After release the exact decision acquires capacity once. |
| Execution commits its reserve and the outer control commit fails | The same reservation and atoms are found on retry. An intervening cancellation prevents launch, and a pending ownership scan cannot release the reserved capacity. |
| Authority commits the bind, then the process loses the reply before the local journal exists | Restart and cancel the original attempt. Recover the binding outcome and settle it under the same assignment. Account for every retained grant or binding before the cancellation can finish. |
| Scheduling reload or cancellation occurs between reserve and grant | The current authority rechecks eligibility before any physical start. The superseded proof cannot authorize a new launch. |

On the candidate, the production resident, outbound and SLURM reservation paths now use one transaction owner. It prepares each store's inputs first, sets immediate busy responses, takes the scheduling and daemon guards in their existing order, checks the control facts and begins the execution write. The execution connection rechecks its stable owner and schema. The control clock commits first, then the execution commit acquires the claim. A known busy result at either boundary rolls back the staged claim and yields to a later turn. Losing the execution commit reply invalidates pending absence observations. The exact assignment, decision receipt and atoms remain the replay identity. The embedded bind, bound-state advance, journal persistence and admission activation now run outside those guards. A cancelled never-bound reservation and a committed bind with a lost reply settle through the authority's exact unbind receipt. A live action producer or a competing owner retains its protection.

Run-cancellation acceptance previously held the daemon guard while waiting for a control writer. Both run cancellation and preparation acceptance also called `operation_projection()` to check for a collision, which could decode a retained SLURM job and collect evidence about it. The candidate performs a keyed existence query and preparation policy selection off the guard. The final transaction rechecks the execution owner, daemon configuration, epochs and the generation advanced by SLURM reservations. A retained matching receipt wins on replay. If a preparation commits first, a competing SLURM reservation checks the same protected key and refuses the collision. [Preparation and run controls](../src/loom/queue/_preparation_operations.py) · [SLURM reservation](../src/loom/queue/local_daemon_execution.py)

**Proof.** Extend the polling contention fixture to registration and the other converted entry points. Hold a real SQLite write transaction, start registration B, and complete C’s empty zero-wait control read while B is waiting. Release the writer and assert one registration receipt under replay. Pause start-permit decoding or external observation, commit cancellation, resume and assert permission is refused. Also exercise busy-at-commit, shutdown during retry, and an authorization change during a chunk read. [Existing busy-at-BEGIN and busy-at-COMMIT cases](../tests/unit/loom/queue/test_agent_waiting.py) · [Session tests](../tests/unit/loom/queue/test_agent_sessions.py) · [Responsiveness tests](../tests/unit/loom/queue/test_coordinator_responsiveness.py)

## 2. Separate current offer mutation from historical lookup

**Current path.** The database snapshot in the investigation had 18,184 offer rows and 12 current rows. Several session-level invalidations match every retained offer for a session, including those already retired. At the same time, replacement must search retired availability revisions to reject reuse. Operator status also needs the latest retained offer and control for an offline agent. A current-only index cannot answer all three queries. [Offer replacement, decline and release](../src/loom/queue/agent_sessions.py) · [Operator reads and drain](../src/loom/queue/local_daemon.py)

**Change.** Use a single session-scoped invalidation helper for every session mutation. Keep epoch-wide invalidation explicitly global. Keep the historical check and replacement write in the same transaction. For the pinned base this includes the separate drain mutation in the daemon as well as the session-service callers. Install lookup indexes during both fresh initialization and exclusively owned startup of an existing database.

```sql
UPDATE agent_offers SET current = 0
WHERE session_id = ? AND current = 1;

CREATE INDEX IF NOT EXISTS agent_offers_session_revision
    ON agent_offers(session_id, availability_revision);
CREATE INDEX IF NOT EXISTS agent_offers_session ON agent_offers(session_id);
CREATE INDEX IF NOT EXISTS agent_controls_session ON agent_controls(session_id);
```

Use the existing partial current-session index for the update. Verify the session-leading indexes serve the actual latest-row queries including their ordering. Keep the historical index nonunique, since making it unique would impose a new constraint on retained data.

**Proof.** Open a retained-root fixture with many obsolete rows across several sessions. Compare query plans and matched rows as history grows. With one current row, invalidation must change one row. Verify retired-revision reuse still fails and an offline agent still reports its latest historical offer and control. Measure index construction during owned startup separately from steady-state latency. [Existing retained-root index test](../tests/unit/loom/queue/test_agent_sessions.py)

## 3. Separate run mutations, audit appends and callback delivery

**Current path.** The authority wrapper acquires the observer lock around mutation and before/after snapshots. The observer acquires that same lock around event lookup, audit append, local projection and sink dispatch. A slow sink for A therefore delays a state transition for B. The 100 ms flush budget is checked after an item returns. [Authority wrapper and event emission](../src/loom/queue/_lifecycle_observers.py)

**Change.** Use a run-scoped mutation guard for the cases requiring a coherent before/after pair. Prefer existing mutation receipts that already contain the committed revision and occurrence time. Enqueue those facts in order under short bookkeeping ownership. Append each stable event ID at an existing revision-safe point between readiness windows. Audit appends can advance the run revision. Deliver local projection and sink callbacks outside both the mutation guard and the coordinator thread.

```python
with guard_for_run(run_uri):
    result, facts = mutate_and_capture(authority, request)
    pending_facts.extend(run_uri, facts)

# Called at the run's existing revision-safe flush point.
if deliveries.try_reserve():
    fact = pending_facts.claim_next(run_uri)
    append_and_enqueue_if_new(fact, deliveries)
```

Reserve dispatch capacity before consuming a fact, release unused capacity on empty, duplicate or failed work, and keep the original owner’s pending fact when the queue is full. Preserve same-run ordering and any sink-wide serialization contract. Send sink failures to the existing evidence owner. Track oldest pending age, queue depth and actual worker exit. Preserve event-ID deduplication and the current best-effort delivery contract across a crash.

**Proof.** Pause A inside a real sink, commit B to RUNNING, then release A. Verify ordered delivery for A, duplicate event suppression, sink failure evidence and restart behavior. Exercise a readiness decision across an audit-generated revision change. [Observer integration tests](../tests/integration/queue/test_lifecycle_observers.py)

## 4. Free the agent mutation gate during release and reserve lifecycle transport capacity

**Current path.** `_release_completed_assignment` holds the delivery and mutation gates. It calls `release_assignment`, which itself holds the mutation gate across the RPC. The inner transport can retry an uncertain response. An asynchronous network call still leaves those logical gates owned. Separately, the sender classifies accept, start permit, started and release with artifact traffic. The sender’s bulk lane has two workers and the receiver admits four agent bulk requests. A free coordinator thread cannot help a start permit still queued at the sender. GPU occupancy sampling also yields to an external worker while its enclosing resource preparation owns the mutation gate. [Release caller](../src/loom/queue/_agent_assignment.py) · [RPC and request classification](../src/loom/queue/agent_session_transport.py) · [Sender allocation](../src/loom/queue/_agent_progress.py) · [Resource preparation](../src/loom/queue/_agent_session_protocol.py)

**Change.** Split the outer release caller and its decorated callee. Use the per-assignment owner for physical release and its existing execution journal. Under the brief agent gate, bind the exact session/root, assignment, fence, prior and released availability revisions, and provider proof to the pending delivery. A locally released resource must stay unavailable for conflicting advertisement until its coordinator transition settles. Exchange the same request with a cumulative attempt deadline, including internal retries. Re-enter the gate only to apply the response to its original journal owner.

```python
pending = yield from prepare_journaled_release(assignment)
reply = yield from exchange_once("release", pending.request, deadline)
with mutation_gate():
    journal.resolve_exact_delivery(pending, reply)
    if journal.offer_still_matches(pending.session, pending.prior_revision):
        journal.apply_released_capacity(pending, reply)
```

Perform the local journal checks and updates atomically. If the session has moved, settle only the matching predecessor proof under the existing replacement rules. Keep newer offers and unresolved claims intact. Reconstruct pending work on restart from the execution proof and delivery reference. A timeout leaves the outcome uncertain. For GPU refresh, capture provider identity and claim revision, sample outside the gate, then recheck both and sample freshness before publishing.

One availability revision represents the whole resource offer. Order competing release transitions that would both advance it, using a dedicated release owner if necessary. Keep local stop delivery, unrelated result journaling and control receipts independent of that ordering. A physically released GPU can remain ineligible for advertisement until the coordinator has accepted the exact revision change. [Existing overlapping-release and local-stop tests](../tests/integration/queue/test_concurrent_outbound_agent.py)

Use one cost classification at both sender and receiver. Reserve bounded capacity for short lifecycle transitions while preserving the existing poll, control-wait and SLURM lanes. Split expensive proof or external-authority preparation from its short final commit before giving a request reserved capacity. Share bounded bulk capacity fairly and measure its throughput. [Release completion and provider proof](../src/loom/queue/_agent_session_journal.py)

For the negotiated transport, submit a short, exact-identity request that can immediately return pending. A reserved sender and receiver slot must both be available for this request. On the coordinator, give start-authority observations bounded worker capacity independent of artifact transfers. A completely saturated transfer pool otherwise recreates the original start-permit wait one step earlier. File reads, sealing and byte transfer remain subject to their storage budget. A release waiting on its own seal can yield its lifecycle slot. Keep an outstanding proof keyed by session, assignment, fence and operation so a duplicate poll attaches to the same work. Reuse existing durable receipts for crash recovery. Leave queued and running work accounted for until withdrawn or actually finished.

```python
# Each pass through the reserved receiver is short. A poll may arrive again.
prepared = proofs.completed(exact_request)
if prepared is None:
    proofs.offer_once(exact_request, workers=workers_for_preparation(operation))
    return pending(exact_request)

def commit(conn):
    require_current_authority(conn, exact_request, prepared)
    return record_or_replay_transition(conn, exact_request, prepared)

return short_write(daemon, commit)
```

If a coordinator epoch changes while a release reply is uncertain, reauthenticate and look up the retained proof. A byte-identical previously authorized proof can settle its matching delivery after validating the session, secret and fence. Rebinding an unaccepted proof to a new epoch requires a definite response from the authorized coordinator and a fresh validation of the original physical evidence. A timeout supplies no such evidence. Test both sides of the commit and an overlapping drain. Older peers retain their existing exchange through explicit capability negotiation.

**Proof.** Occupy both ends’ bulk capacity with normal transfers. A second assignment must obtain a start permit before the transfers finish. Lose a release reply after coordinator commit, restart, replay, and assert one provider release and one coordinator transition. Deliver a late old reply after session replacement and verify the newer offer survives. Pause GPU sampling and receive an independent control.

## 5. Move TLS negotiation off the accept loop

**Current path.** The HTTP server is threaded, but `get_request()` calls `wrap_socket(..., server_side=True)` before returning the connection. Request threading starts after this point. A slow negotiation can therefore delay otherwise independent agents before their request types are known. [TLS listener and worker handoff](../src/loom/queue/agent_session_transport.py)

**Change.** Accept raw sockets promptly. Admit each to a bounded handshake worker with a deadline measured from acceptance, including queue time. After mutual TLS succeeds, hand socket ownership to the existing request worker and immediately free the handshake slot. Keep the application’s current credential-to-role check at dispatch. Capture a coherent TLS context on reload, close refused or expired sockets, and close tracked queued/in-flight negotiations on shutdown. Bound outstanding accepted sockets as well as worker count.

```python
accepted = AcceptedSocket(sock, address, expires=monotonic() + budget)
if not handshakes.try_submit(accepted):
    accepted.close()

# Handshake worker owns the socket until dispatch accepts ownership.
with accepted.close_unless_transferred():
    tls = authenticate(accepted, deadline=accepted.expires)
    accepted.transfer_to(request_workers, tls)
```

**Proof.** Use a controlled isolated handshake fixture that pauses one worker. A second authenticated connection must reach its ordinary handler while the first is paused and capacity remains. Verify invalid credentials, credential rotation, a full queue and shutdown return the expected outcomes and release sockets. Measure acceptance-to-authentication separately from request latency. [Transport integration tests](../tests/integration/queue/test_agent_session_transport.py)

## 6. Make coordinator turns resumable and keep storage waits from occupying all workers

**Current path.** `_reconcile_once` runs preparation, GPU refresh, observer flush, recovery and admission processing in sequence. Some subpaths already have budgets and cursors. One slow call inside a phase can still delay later phases. The two shared bulk workers also admit FIFO work. Target publication takes a blocking file lock and can wait on a renderer subprocess. An unrelated short image-retention operation can spend most of its lifetime waiting for a worker. [Coordinator pass](../src/loom/queue/local_daemon.py) · [Bulk ownership](../src/loom/queue/_bulk_operations.py) · [Target lock and rendering](../src/loom/queue/managed_local_preparation.py)

**Change.** Keep one owner for scheduling decisions and reuse the admission cursor, priority rules, existing work owners and completion wakeups. Rotate bounded turns for cancellation/recovery, applying completions, discovery, preparation and scheduling. Page large inventories. Make a slow provider or authority observation a keyed pending operation whose completion wakes that owner. Apply only after checking the configuration/epoch, current admission and cancellation. A wall-time check between items cannot interrupt a blocking system call.

```python
for owner in rotate_ready_owners():
    outcome = owner.advance(item_limit=limit, deadline=turn_deadline())
    if outcome.more_ready_now:
        wake_scheduler()
    # An outstanding future wakes its owner when it actually completes.
```

Two parts of the current pass rely on seeing the entire active set. The bulk-work owner retires tickets absent from an authoritative inventory, and scheduling chooses across runnable admissions in priority order. When paging discovery, retain tickets through partially visited pages. Retire a ticket on an observed terminal transition or after a complete inventory pass confirms absence. Keep a priority-ordered selection across eligible work even as the starting point for *inspection* rotates. Yielding after a fixed number of dispatches still permits a slow GPU query or owner-store call to occupy the entire turn. Give those calls their own completion wakeup. [Pass, priority and ticket retirement](../src/loom/queue/local_daemon.py) · [Bulk owner](../src/loom/queue/_bulk_operations.py)

Acquire the per-target publication lock without blocking a general worker. On contention, keep the prepared candidate and its identity, release the execution slot, and retry fairly with bounded backoff. Give long renders/publications a bounded budget that leaves capacity for short preparation. Count any running renderer through actual exit, including after timeout. Recheck the candidate and destination under the acquired target lock before atomic install. Hold that lock through the installation and replay check.

At candidate commit `ed710f40` the scheduler calls `open_owner_stores()` at entry to `_reconcile_once()` and again through `_admission_context()`. The call reopens the embedded journal and validates coordinator structures and owner bindings. Retain synchronous validation during exclusive startup. During operation, let a bounded worker check the same owner stores for the current daemon and scheduling generation. Deduplicate concurrent requests for that check. Allow independent control receipts, reads and completed work to advance while it runs. Gate new scheduling mutations on a valid result, discard it on owner replacement or reload, and preserve exact identity and cancellation checks at reservation. A successful probe cannot permanently certify a mutable database. Verify that loss or replacement of a store between probe and reserve fails closed at the write boundary. [Scheduler entry](../src/loom/queue/local_daemon.py) · [Owner validation and admission context](../src/loom/queue/local_daemon_execution.py)

Implement this in the background scheduling pass and the per-run admission path together. The latter calls `bind_coordinator_admission()` even with a prepared intent. Schedule that exchange under the existing admission operation ID and let the completion wake the scheduler. Check the admission revision and epochs before applying the returned receipt. Startup and explicit health/reconciliation requests must still surface a missing or substituted owner. Preserve the current rule that an owner check for one operation cannot authorize a later operation indefinitely. On the connection doing a reservation, verify the expected stable store identity in the transaction before writing, including on replay. Open a required retained store in existing-only mode so removing it cannot create an empty replacement. [Admission reconciliation](../src/loom/queue/_coordinator_run_progress.py) · [Owner substitution and loss tests](../tests/unit/loom/queue/test_local_daemon.py)

For bounded admission discovery, keep the current priority ordering by run priority, enqueue sequence and admission ID. Advance a bounded cursor over the population being inspected. Obtain the globally eligible head when allocating scarce capacity, and retain tickets for owners still awaiting inspection. Test with a later high-priority runnable admission competing for the last slot and a low-priority admission whose context is slow. Also delete an admission behind the cursor and add one during the pass. Verify that retained tickets are reclaimed only after terminal evidence or a complete scan and that repeated arrivals cannot indefinitely postpone the original population. [Priority integration](../tests/integration/queue/test_local_daemon_production.py) · [Scan behavior](../tests/unit/loom/queue/test_admission_scan.py)

**Proof.** Hold A’s publication lock and pause a renderer. Before releasing either, complete an unrelated image-retention task, advance a fresh admission and record a cancellation. Then verify A publishes exactly once and global runnable priority is preserved. Compare queue age and execution duration by action, plus maximum running workers and child processes. [Preparation integration tests](../tests/integration/queue/test_preparation_operations.py) · [Coordinator responsiveness](../tests/unit/loom/queue/test_coordinator_responsiveness.py)

### Preserve the selection order through the embedded reservation

There are two decisions in the candidate that can produce different orders. The scheduler ranks a bounded page of READY projections and chooses a stage for a particular agent. Its embedded path can then return `False` for either an outstanding request preparation or an assignment worker already staging the workspace. The window excludes that stage for this pass and considers the next candidate. Each submitted assignment worker later attempts its own database reserve. The transaction prevents capacity from being spent twice. It has no knowledge of the priority comparison that took place before both workers started. In addition, contexts validated on different turns can make only a subset of the READY page eligible for consideration. [Selection and bypass](../src/loom/queue/_coordinator_run_progress.py) · [Worker submission](../src/loom/queue/local_daemon_execution.py) · [Workspace staging before reserve](../src/loom/queue/_managed_local.py)

Moving owner checks and authority binding onto workers exposed the existing one-slot priority test. The retained execution database showed one running low-priority assignment while the higher-priority stage was READY. A separate instrumented run passed. In that run the scheduler offered high and then low, both calls returned pending, and two separate assignment workers entered the reservation path. High committed first in that run. The failing database records the outcome but contains no per-worker timing from which to reconstruct its exact ordering. The two observations establish a need to cover the competing decisions directly. [One-slot and off-page priority cases](../tests/integration/queue/test_local_daemon_production.py)

Split the embedded operation at its existing boundary between preparing the exact workspace and calling `reserve`. Bounded workers can prepare inputs for multiple stages and return their assignment identity, staged input evidence, requested capacity atoms, policy/configuration epoch and offer revision. Keep those results across turns while their identities and authority remain current. Give one scheduling owner the choice among fully prepared eligible candidates. Have it commit or authorize one reservation per conflicting set of atoms before offering the same capacity again. Do slow binding and launch under the exact committed assignment. On an uncertain commit, reconcile that identity before reassigning its capacity. The public synchronous path and restart path can compose the same preparation and reserve operations. They need no second authority for claims.

```python
# A scheduler turn consumes completed preparations without joining their workers.
for evidence in workspaces.completed():
    prepared.retain_if_current(evidence)
for choice in policy.rank(prepared.eligible(current_ready_page, available_atoms)):
    decision = reserve_exact_if_current(choice, epochs, cancellation, available_atoms)
    if decision.committed:
        available_atoms.consume(choice.claims)
        launches.offer_once(decision.assignment_id)
    elif decision.uncertain:
        reconcile_original_reservation(choice.assignment_id)
        available_atoms.withhold(choice.claims)
```

The eligibility distinction matters. If both workspaces are prepared for the same remaining CPU, priority determines the winner. If the high-priority workspace is still reading input, another prepared stage can use available capacity. Existing leases, run limits, admission cancellation and offer revisions remain authoritative at commit. The same calculation must permit two nonconflicting claims to advance when capacity allows. A fixed sleep would make all three outcomes depend on machine speed.

Use two explicit barriers in the test. In the first case, release two completed preparations to the scheduler together and assert the high-priority stage owns the single claim through the durable assignment row. In the second, pause one workspace before completion and assert a prepared peer launches before releasing it. Repeat selection with a reload or cancellation between preparation and commit, and with a committed claim whose reply is lost. Retain the off-page priority test, which separately checks that a freed context slot goes to a READY high-priority run during a saturated discovery pass. [Input barrier and cancellation](../tests/integration/queue/test_local_daemon_production.py) · [Reservation replay](../tests/unit/loom/queue/test_agent_waiting.py)

### Resume a run after an authority read

A scheduler time budget is only checked when control returns from a function. On the reference path a run can spend that entire time inside `open_run()`. Reconciliation reads before computing eligible stages, reads again after advancing SLURM, and reads after orchestration before deciding terminal status. Cancellation reads on either side of the epoch and stop fan-out. Moving the first read alone leaves the later reads on the same shared thread.

Use the existing reconciliation owner to perform mutations. Suspend that run at each read boundary, submit the scoped read, and let the scheduler visit another run. Resume at the exact point that needed the observation. Pin the suspended work to its admission revision and both daemon epochs. A committed cancellation or reload can supersede an outstanding read. Count that physical read against the pool until it returns, and prevent a newer revision of the same admission from taking the second slot while the obsolete read is still running. An administrative caller driving one run synchronously can consume the same sequence of steps.

```python
snapshot = yield                     # worker reads this run's authority
reconcile_ready_stages(snapshot)     # scheduler owns the decision
snapshot = yield                     # effects may have advanced the revision
return determine_outcome(snapshot)
```

At READY selection there is a separate read before managed or SLURM dispatch. Give each selected admission a bounded observation there as well. Pin the observation to the current admission, scheduling configuration, stage attempt and projection. Apply failure policy to the observed run, discard superseded evidence, and recheck cancellation and reservation at the actual commit. When both prepared workspaces compete for one CPU, a delayed or lost commit reply still belongs to the winning assignment. Exercise four barriers separately: ordinary reconciliation, cancellation, managed dispatch and SLURM dispatch. Also hold an authority read from an old daemon epoch across reload. The acceptance condition is that a healthy run finishes before the held read returns and stale evidence cannot launch a process. [Run reconciliation and READY selection](../src/loom/queue/_coordinator_run_progress.py) · [Scoped authority](../src/loom/queue/_coordinator_run_authority.py)

The READY query must still reread database membership, priority and the cursor every time it makes a placement decision. Its scheduling reader can reuse the decoded record for byte-identical row payloads. Keep that cache private to scheduling and bounded to the current and next 256-row windows. An operator or other public store consumer receives its own decoded objects. Changed bytes get decoded again. A page containing only disabled SLURM routes may withdraw its dispatch tickets immediately. Preserve the concrete waiting reason when a freshly reconciled admission is due for a status update.

```python
for payload in read_current_ready_page(cursor, priority_boundary):
    record = scheduling_decoder(payload)   # bounded cache keyed by exact bytes
    if route_can_dispatch(record):
        offer_for_authority_observation(record)
```

In the 257-stage regression a peer sits after 257 independent stages assigned to an unavailable SLURM profile. A trace of the candidate before decoded-row reuse measured 124 READY-window reads taking a total of 8.59 seconds on the scheduling thread. Separate context workers spent a total of 15.30 seconds binding or loading admission contexts. These timings can overlap. Changing the dispatch read alone left 66 stages absent at the fixture deadline. The test requires the managed stage to produce its output and all 257 SLURM stages to remain pending under the original deadline. [Large mixed-route regression](../tests/integration/queue/test_slurm_ready_stage.py)

A second trace of the 257-stage run identified an interaction with audit ordering. A later trace measured 21.86 seconds in 167 scheduler calls to `flush_prepared`. Appending an audit record can change the revision while a background authority read is suspended. A readiness transaction then presents a stale expected revision and the ordinary failure path backs off. Isolate the audit append itself. Use one bounded audit writer to preserve existing delivery ordering. Select a run with pending facts or completed callback evidence. Before reading that run for a readiness slice, let any previously offered audit for it finish on the read worker. While that slice owns its snapshot, allow audit work for other runs. After the slice, offer the same run another short batch. Shutdown drains submitted callbacks and audit facts. Sink delivery retains its own limit. A real paused audit write for A allowed B to finish on the only CPU. The 257-stage case then completed within its original 45-second stage deadline, with 258 prepared attempts and zero SLURM submissions.

```python
audit = offer_bounded_audit_batch(run_uri)
def read_for_next_slice():
    if audit is not None:
        audit.result()                    # this run's read worker
    return authority.open_run(run_uri)
submit_read(run_uri, read_for_next_slice)
# The scheduling owner can consume a completed slice for another run.
```

Trace the remaining mutation paths separately. `_reconcile_slurm_terminal_assignment` reads authority, confirms the exact prepared attempt and compares its fence before marking a SLURM record terminal. `_reconcile_terminal_without_report` reads an attempt revision when constructing a guarded recovery. `_apply_controller_action` reads current truth for SKIP or REUSE. There is a similar read per producer claim in `ActionResultResolution._observe_result`. Give each blocking observation its own resumable turn. Read a producer run once for a bounded group of eligible claims, then recheck each claim revision before retaining or adopting outputs. Embedded SLURM already offloads the provider submission. The replay path is different. `_reconcile_slurm_run` calls `replay_pending`, which holds the agent job lock while acknowledging a page. Its callback calls `acknowledge_slurm_agent` with synchronous retention defaults. A replayed provider-release record carrying a shared recovery tree can reach file retention on the scheduling thread. Route that receipt through the existing pending-storage owner where the execution schema supports it, keep its outbox sequence pending until the exact proof is durable, and preserve legacy receipt semantics. Hold the actual recovery copy during replay and require a managed peer to finish before releasing it. A lost `sbatch` response continues to use the existing uncertain-submission reconciliation. Keep SKIP's compare-and-set, the terminal assignment's exact grant and the guarded recovery's expected attempt revision at their existing mutation owners. Inject a competing report, cancellation and revision change before each commit, and require the peer-run barrier for these paths. [Scheduler](../src/loom/queue/_coordinator_run_progress.py) · [SLURM and controller actions](../src/loom/queue/local_daemon_execution.py) · [Audit owner](../src/loom/queue/_lifecycle_observers.py)

## 7. Fan out stop delivery and collect containment per assignment

**Current path.** After installing a cancellation epoch the coordinator visits SLURM, local and remote owners sequentially. On the agent, the active-assignment loop waits for stop and containment of each launch before proceeding to the next. Preparation cancellation can collect child admission and ownership evidence under the state guard. An accepted cancellation of a multi-assignment run can thus appear inert while the first process settles. [Coordinator cancellation](../src/loom/queue/local_daemon_execution.py) · [Agent containment](../src/loom/queue/agent_session_transport.py) · [Child settlement](../src/loom/queue/_preparation_operations.py)

**Change.** Commit the request and install the existing cancellation epoch before fan-out. Build a bounded set of stop operations keyed by cancellation, assignment and execution fence. Give delivery and containment separate concurrency budgets. Persist each owner’s progress on completion. On restart reconcile uncertain stop effects using the retained supervisor or scheduler identity. Collect child and ownership evidence outside the daemon guard. Recheck the current child set and its ownership at finalization under the existing authority.

```python
for owner in cancellation.eligible_owners():
    stop_delivery.offer_once(cancellation.id, owner.id, owner.fence)
for receipt in containment.completed():
    cancellation.record_if_current(receipt)
if authority.all_required_owners_settled(cancellation):
    authority.finalize_cancellation(cancellation)
```

Expose request recorded, control received, stop requested, containment confirmed and resources released from their respective receipts. Keep an unknown SLURM submission, uncontained process or unresolved release visibly pending. Retain the existing single-process root ownership rule during drain and shutdown. Recheck late naturally terminal runs against the authority before finalization.

Trace both ends of a machine-wide control. The agent's `poll_control()` holds the mutation gate, while reload preparation and `_apply_agent_control()` can hold the control lock across `_cancel_active_assignments()`. Starting multiple containment tasks inside that scope would still delay independent agent updates. Capture the exact control ID, expected session, active launches and fences under a short gate. Immediately install the existing admission/drain restriction where required. Drive per-launch work outside both gates. On return, persist each exact physical result with its launch owner even if a newer control arrived. Revalidate the control and session before applying an effect or acknowledging the original command. A newer control cannot reverse an already delivered physical stop. [Control receipt and application](../src/loom/queue/agent_session_transport.py)

The service also has an early receipt path. After `_receive_service_controls()` retains a machine-wide cancel command, it loops over unresolved launches and calls the supervisor's one-attempt `request_stop()`. A healthy native B can therefore receive its signal before A is contained today. Each IPC attempt still precedes the next one, and `_cancel_active_assignments()` subsequently joins stop and containment in order. Fix both loops. Give each launch a bounded attempt, preserve its existing stop intent, and advance an available peer even when the first result says pending. In the restart case, reconstruct the set from unresolved journal references and exact supervisor launch records. Record physical evidence against the launch before deciding whether the machine-wide control can still be acknowledged. Test the time of B's signal *and* the time its positive containment reaches its workspace while A is paused. [Early control receipt and later application](../src/loom/queue/agent_session_transport.py)

A combined control-wait response can carry both a machine command and an assignment command. Retain both promptly. If the first handler waits for its stop IPC, the machine command can still be waiting in the response body when its second assignment needs a stop. The execution view, early receiver and machine control can also request the same physical exchange. Coalesce an in-flight attempt by operation and immutable launch identity. Direct each execution view to its retained assignment control using the indexed assignment ID. A released assignment's late receipt can skip a live owner's pending command. These are separate queues from the supervisor's own backend workers.

```python
command, prior_effect = prepare_or_replay_under_mutation_gate(session)
if prior_effect is None:
    # A stop is deliverable as soon as this launch has capacity.
    # Each owner records a positive result before the aggregate join returns.
    results = await gather_per_launch(command, unresolved_deliveries())
    effect = recheck_command_and_record_effect(command, results)
else:
    effect = prior_effect
acknowledge_exact_effect(command.operation_id, effect)
```

The supervisor already sends some native stops immediately. For a Docker-backed or starting launch, stop or containment may need a worker. `_SupervisorDispatch` currently charges those slow effects against one limit. Preserve the immediate native path and reserve actual stop-delivery capacity for the slower path. Coalesce retries by exact launch identity and keep a running effect charged until it exits. Exercise a slow-path stop while all general containment capacity is occupied, as well as a fast native stop. [Supervisor dispatch](../src/loom/queue/_agent_process_supervisor.py)

Service retirement needs the same ownership check. In the baseline, `service_lifetime()` wraps `CoordinatorLifetime.retained()` inside the shared cycle lock. The latter inspects coordinator records, expires startup attachments, and inspects physical owner stores. Capture the generation and candidate owners, gather physical evidence outside the guard, and recheck generation, attachments, references and admission eligibility before authorizing closure. Expire attachments in a short coordinator transaction. Calling the existing `retained()` from inside a new write transaction would introduce a second connection that can wait for the first writer. Pause an owner read, verify another agent's renewal, then create a retained reference and require retirement to stay pending. [Service request](../src/loom/queue/agent_sessions.py) · [Lifetime owner](../src/loom/queue/_service_lifetime.py)

**Proof.** Hold A’s containment proof, observe B receive its stop and record containment, then restart before A’s proof is recorded. The same operation must resume, keep A named as pending, and become terminal only after all required ownership is settled. Include mixed local/remote/SLURM owners and a late valid terminal result.

### Coordinator cancellation after a local claim has been accepted

The mixed local/remote fixture exposed a gap between two durable receipts. With a local provider abort paused, the remote stop and release succeeded. When the local abort returned, the embedded journal recorded a definitive decline and release with no grant fence or process. The coordinator still recorded `accepted`. An ordinary decline replay called `release_unaccepted()`, which expects `bound`. Ordinary replay could also move the journal past `DECLINED` before the cancellation reconciler saw it. The original fixture timed out at 90 s. On `21d7f763` it reaches terminal cancellation, including after a daemon restart between the two releases. A separate lost-grant-reply case recovered the authority's original fence and cancelled before any process launched. [Mixed-owner integration](../tests/integration/queue/test_agent_session_transport.py) · [Resident journal](../src/loom/queue/_managed_local.py) · [Replay and cancellation](../src/loom/queue/local_daemon_execution.py)

Give retained pre-grant cancellation one owner across scheduler turns and restart. Let an already-running local prepare or grant settle under its existing owner. When the cancellation epoch covers that exact attempt and the grant is refused, hand the retained assignment to cancellation recovery. Publish the exact remote controls as soon as the epoch is installed. Reserve capacity for local aborts and SLURM stop commands independently of regular observations. Keep the ordinary recovery path for a grant that actually succeeded, including a grant with a lost response. Before accepting no-start evidence, require an exact authority unbind or its replay receipt. A journal state alone cannot resolve an authority grant.

```python
if local_prepare_or_grant_in_flight(assignment):
    return pending(assignment)
if not unbind_or_recover_exact_ungranted_attempt(assignment, cancel_epoch):
    return reconcile_granted_or_unknown_owner(assignment)
if not journal.proves_pregrant_decline(assignment):
    return offer_exact_claim_cleanup_or_wait(assignment)
coordinator.cancellation_release_pregrant(assignment.id)
return settled(assignment)
```

The proof reader needs to recognize both a durable decline and a released, definitively declined assignment with matching identity and no grant or launch. Use the existing journal evidence and idempotent unbind/release operations. Never infer the state of a remote assignment from a missing embedded journal row. A crash during provider preparation can leave the request and claim commands durable before the journal records the prepare outcome. Reconcile the exact provider commands on that path before treating the claim as free. Failure or uncertainty retains the owner for retry. Exercise restart after the provider abort, after authority unbind, and after the journal release with the coordinator still `accepted`. Require exactly one logical release, no second launch, and an eventual terminal receipt. In a separate SLURM adapter test, hold both ordinary observation workers inside scheduler calls, then require a third, exactly identified job to reach the physical stop adapter before either observation returns.

### Preparation cancellation with one or more child admissions

Before the child-proof change, `_advance_owned()` counted a child's live assignments under the daemon state guard. `_reconcile_cancellations()` could repeat that check for every child and publish the control outcome through a second connection. The counter acquired a write transaction on the execution store. A capacity count could also exclude a terminal assignment that still owed physical release. An unrelated execution writer could therefore delay daemon readers. A child created after an off-guard count could otherwise be omitted at finalization. [Both child paths](../src/loom/queue/_preparation_operations.py) · [Execution-store count](../src/loom/queue/_managed_local.py)

```python
scope = capture_target_and_children(control_id)
if any_child_nonterminal(scope):
    return pending(control_id)
proof = child_owner_checks.completed_or_schedule(scope)
if proof is None or not proof.all_released:
    return pending(control_id)
return short_write(lambda conn: finalize_if_scope_matches(conn, scope, proof))
```

Capture the cancellation operation, target and principal, exact child IDs, run URIs, admission revisions and the generation protecting new scheduling references. Query native and SLURM ownership off the scheduling thread with a read transaction on the initialized store. The final short transaction compares the scope again. Every applicable child creation and reservation must invalidate the scope before a stale proof can finalize, including a partial cross-store reservation. Reuse an existing child cancellation intent and avoid updating an identical pending result on every pass. If any owner is unavailable, leave the operation pending. Pause the ownership read, demonstrate an unrelated control read or renewal, then add a child or change its ownership before applying the result. Require the stale proof to be discarded and the original operation to finish after the current children release.

## 8. Acknowledge only new events and relay bounded pages

**Current path.** The outbound workspace reads all pending events, sends one RPC per event, counts the entire prefix to check for a gap, and marks the whole prefix acknowledged again. For 1,024 sequential acknowledgements that matches 524,800 rows on the updates alone. The managed-local journal has the same prefix-count/update shape with an assignment-scoped nullable `acknowledged_sequence` column. Terminal result and release can sit behind the relay. [Workspace journal](../src/loom/queue/_remote_stage_execution.py) · [Relay](../src/loom/queue/agent_session_transport.py) · [Managed journal](../src/loom/queue/_managed_local.py) · [Upgrade consumer of acknowledgement state](../src/loom/queue/service_upgrade.py)

**Change.** Page pending events in sequence order. In one transaction verify that the acknowledgement refers to the exact range sent, starts at the first outstanding event, and covers contiguous retained identities. A duplicate exact acknowledgement is a successful replay. If the exchange ends before a valid receipt, retain the entire sent batch locally. Replay its original bytes so the receiver can recognize the already committed prefix. Index outstanding work and update only newly acknowledged rows. The per-workspace store already scopes events to its assignment. The shared managed store requires an assignment predicate and an assignment-leading index. Preserve every supported reader’s interpretation of its nullable watermark, including upgrade checks.

```sql
CREATE INDEX IF NOT EXISTS events_pending_sequence
    ON events(sequence) WHERE acknowledged = 0;

SELECT sequence, event_id, payload_json FROM events
WHERE acknowledged = 0 ORDER BY sequence LIMIT ?;

UPDATE events SET acknowledged = 1
WHERE acknowledged = 0 AND sequence BETWEEN ? AND ?;
```

Use each journal’s existing state as the authority. For the managed store, confirm which consumers require the latest acknowledged sequence, expose the equivalent answer from indexed retained rows, and test old-format reads before changing per-row values. Avoid a full prefix count by validating the bounded newly acknowledged range against the last contiguous acknowledged boundary, including the first-ever range. Yield after each page. At completion seal or capture the final required sequence under the assignment owner, after the last producer has handed off its events. Confirm the terminal boundary before release.

Ship the local journal improvement first. Add an explicitly negotiated batch RPC with count and encoded-byte limits. The receiver validates the assignment, ordered sequence, stable IDs and payload equality through the existing event owner, then reports the highest contiguous durable sequence for that request. Bind the receipt to the assignment, canonical request digest and exact final sequence. An older peer uses paged single-event delivery.

**Proof.** At 1,024 events, count approximately 1,024 newly updated acknowledgement rows per journal and check that the full-prefix counts also disappear. Test exact replay, changed payload for the same ID, gaps, reply loss after a partial batch, restart and an event arriving during final flush. Keep old-agent/old-workspace interoperability and upgrade detection of unacknowledged events. [Workspace tests](../tests/unit/loom/queue/test_remote_stage_execution.py) · [Managed journal tests](../tests/unit/loom/queue/test_managed_local.py)

## 9. Batch recovery facts for SLURM task pages

**Current path.** The session service calls the task-page builder under its cycle lock. Pages have a 32-record cap, yet each task scans and parses recovery requests, then page construction separately asks whether recovery withholds that assignment. The work grows with both task count and historical recovery population. Repeated envelope encoding adds work under the same guard. [Session dispatch](../src/loom/queue/agent_sessions.py) · [Task construction and cursor semantics](../src/loom/queue/local_daemon_execution.py)

**Change.** Authorize the session, capture its execution owner and epochs, select one bounded candidate page with its existing lookahead, and retrieve recovery facts for the candidate assignment IDs in one indexed lookup. Use the same facts for recovery proof and withholding. Match the index expression to the actual query on the retained JSON assignment ID and check its plan on retained data. Preserve all relevant records for an assignment, including pending, evidence-confirmed and closed recovery. Continue using the real encoded response envelope for the byte ceiling.

```python
session = capture_authorized_session(request)
rows = assignments.agent_page(session.agent_id, session.root, after=cursor)
facts = recoveries.for_assignment_ids([row.assignment_id for row in rows])
page = pack_page(rows, facts, response_byte_limit)
return return_if_still_current(session, rows, facts, page)
```

Build and encode outside the coordinator lock. Before returning actionable evidence, revalidate the session, policy/epoch, relevant assignment facts and recovery state, including creation of a previously absent recovery. Use exact versions or bounded comparisons at the existing authorities. On a change rebuild under the original cursor and deadline. Preserve the last safe cursor if a task would exceed the response budget and advance correctly across withheld records. Evidence acknowledgements remain separate mutations.

On the baseline the expected agent sequence has another hidden cost. `_slurm_task()` calls `agent_evidence()` for each row, which enters the assignment store's `BEGIN IMMEDIATE` transaction just to read a sequence. The assignment page already selected that column. Carry it in the returned record. For final page validation compare only that page's assignment identities, sequence, execution fence, cancellation, and recovery/projection facts together with session and scheduling authority. Use the same cursor when the comparison fails. Routine offer renewals for an unrelated session should allow a stable page to be delivered. Add that case alongside recovery creation during packing. [Assignment-store query and evidence transaction](../src/loom/queue/slurm_ready_stage.py)

**Proof.** Compare 1- and 32-task pages with a large unrelated recovery history. Assert bounded recovery queries per page, stable encoding and correct cursors. Pause construction while another agent renews, change a formerly absent recovery to pending, then demand the newer withholding/proof result. Include closed recovery and an overlarge single task. [SLURM page tests](../tests/unit/loom/queue/test_slurm_task_pages.py)

## 10. Wake affected watchers and observe fleet members independently

**Current path.** Waiters already snapshot a generation before reading durable state, which closes a lost-wakeup race. The control database’s commit callback wakes a shared signal. Routine changes for B can cause all of A’s operation/admission watchers to reread. In the operator view, one client reads agents in inventory order, so a delayed response postpones all later observations. [Commit notifications](../src/loom/queue/_service_signals.py) · [Durable waits](../src/loom/queue/local_daemon.py) · [Fleet view](../src/loom/fleet/administration.py)

**Change.** Reuse the existing session subscription pattern for operation and admission keys. During a transaction accumulate affected keys at the code that knows which receipts/revisions it changed. Publish once after successful commit. Discard pending keys on rollback. Release subscriptions when the last waiter exits. For derived projections include each affected owner, and retain the bounded fallback read for other owner stores and other processes. Broadcast shutdown to every subscription.

```python
with changes.subscribe(("admission", admission_id)) as signal:
    while True:
        generation = signal.snapshot()
        admission = read_durable_admission(admission_id)
        if should_return(admission, expected_revision, deadline):
            return admission
        signal.wait_for_change(generation, min(fallback, remaining(deadline)))
```

Put notification bookkeeping at the write site. For example, one status update can touch both an admission ID and a queue-item ID. Capture all changed keys from the SQL result. Keeping those keys in the same SQLite transaction makes savepoint rollback remove its hints along with its rows. After the outer commit the connection passes distinct surviving keys to the daemon. Independent owner databases need an explicit post-commit hint where available and the normal fallback reread. [Status mutation and commit](../src/loom/queue/_service_signals.py)

For fleet reads use a bounded set of independent clients pinned to the selected coordinator, one per worker unless concurrent use is supported. Record per-host observation time, owner and failure as each result arrives. Assemble the final report in inventory order. A caller requesting a complete report waits for the slowest outstanding host or its deadline. Faster hosts can finish and report progress independently.

**Proof.** Watch A while B commits repeated offer changes. Count A’s reads against the fallback interval. Commit between the snapshot and the wait, roll back a write, commit from another process, and stop the daemon. For the fleet view hold host A, observe B complete, then verify the final order and individual errors. [Generation and shutdown tests](../tests/unit/loom/queue/test_service_signals.py) · [Session subscription implementation](../src/loom/queue/_agent_poll_waiters.py)

## 11. Make artifact verification resumable and give fleet checks fair observation time

**Current path.** A 65 MiB artifact takes 260 sequential 256 KiB range requests at the current public limit. Each range calls the native client, whose default path performs a separate protocol handshake before the request. A fetch failure cleans ordinary staging, so resuming a fleet check can repeat completed bytes. The upgrader already dispatches checks before observing them and already has three workers. It uses a shared deadline and consumes observation futures in submission order. A slow early check can delay publishing a later finished result, while queued steps can start with almost no allowance. [Range fetching](../src/loom/_artifact_fetch.py) · [Native negotiation](../src/loom/queue/_coordinator_client.py) · [Self-test verification](../src/loom/fleet/self_tests.py) · [Upgrade check orchestration](../src/loom/fleet/upgrades.py)

**Change the transfer.** Bind a private reader to coordinator identity, principal, scope, exact locator, declaration and member. Negotiate once per eligible connection and renegotiate after reconnect, credential rotation or coordinator replacement. Preserve producer and consumer authorization on each read. Use a small bounded window of independent offsets and a bounded aggregate memory budget across checks. Validate offset, declaration and length before writing into a private staging file. Mark a range complete only after its bytes are safely reusable under the selected crash model. Verify the final digest in file order and publish atomically with the existing no-overwrite rule.

```python
for chunk in reader.completed_ranges(member, window=window, deadline=step_end):
    staging.write_validated_range(chunk)
if staging.complete(member):
    verify_declared_length_and_digest(staging, member)
if staging.all_members_verified():
    publish_and_recover_existing_exact_result(staging, destination)
    checks.record_verification(check_id, declaration, verification_level)
```

Select resumable staging for fleet verification only. Bind private progress to the check ID, declaration and member identities. On resume reauthorize and revalidate the declaration. Missing scratch can restart a transfer under the same check. Keep the verified receipt with the check so scratch cleanup does not invalidate completed work. If publication completed just before a crash, reconcile the exact existing output and verify it before recording success. Ordinary fetch retains its existing cleanup behavior. Legacy declarations keep their weaker verification status and producer-declared shared artifacts retain their access contract.

**Change check orchestration.** Give each selected check a bounded dispatch opportunity and record its exact ID/outcome. Preserve the dispatch-first barrier. Next, fairly schedule small observation, fetch or verification steps with separate attempt, execution-policy and caller-observation deadlines. Write results in completion order under the existing receipt owner. Bounded step means the actual wait or transfer checkpoints by its budget. Ensure pool shutdown or a joining context manager cannot hold the caller past detachment. Retain any outstanding worker slot until the worker actually stops.

```python
dispatch_or_recover_each_check_once(checks)
while watcher.has_time() and checks.pending():
    workers.offer_fair_steps(checks, watcher.deadline)
    for check_id, progress in workers.completed_until(watcher.deadline):
        checks.record_progress(check_id, progress)
return checks.snapshot()
```

Implement the check watcher in three reviewable steps.

1. **Identify exactly what was sent.** The baseline dispatch marker is written before native submission. It proves the intended operation ID. Record a definite rejection, an uncertain exchange, or a confirmed native receipt independently. The baseline dispatch-only path can report `checks_dispatched` after its loop hits a deadline. Return per-check dispositions including those still awaiting a send. Recover a lost response by reading the retained operation on the bound coordinator. Replay the immutable request only when that exact operation lookup proves absence. A missing admission or output further down the observation path supplies no evidence about whether the start operation exists.
2. **Start the observation budget at entry.** On the baseline the per-check `flock(LOCK_EX)` precedes deadline creation. `start_run`, several operator reads, and output selection can also spend a fresh transport budget. Establish one monotonic caller deadline before authorization, lock acquisition, or pool submission. Pass the remaining allowance through each nested read and exchange. A busy receipt owner should return its last durable progress or a pending outcome. Preserve the check's allowed execution lifetime when its observer leaves. On continuation, give checks still awaiting their first dispatch a turn before retrying earlier slow checks. Start downloads after every selected check has had a bounded dispatch opportunity.
3. **Commit each result when it arrives.** On the baseline, `_run_checks` calls `future.result()` in input order. Collect whichever bounded step completes first and immediately publish that check's progress. Retain a verified artifact receipt separately from transient observations in the same check directory. A later observation can then say that release evidence is pending without erasing the earlier integrity proof. Re-read current assignment, session and capacity evidence before declaring the check passed. Charge each physical worker until it exits so repeated observer detachment cannot accumulate hidden downloads. [Check intent, owner lock, submission and verification](../src/loom/fleet/self_tests.py) · [Maintenance check ordering](../src/loom/fleet/upgrades.py)

The isolated eight-service upgrade exposed a second delay after implementing fair first dispatch. Multiple storage downloads were advancing under their original IDs while their receipts showed `publication_failed`. The fetcher caught an elapsed observation deadline as a generic I/O error. The controller also allowed one ten-second step per check per invocation. Continuing a growing download therefore repeated the outer host inspections. A representative invocation took 52.85 seconds, including about ten seconds of host preflight. Record observer expiry explicitly, keep each range under its existing binding, and grant a growing transfer a fair share of the remaining absolute watcher budget. When all transfers stall, return the retained outcomes. A fast terminal check must still reach disk immediately. Compare verified throughput and request counts with the baseline before rollout. [Fetch outcome](../src/loom/_artifact_fetch.py) · [Bounded check steps](../src/loom/fleet/_check_workers.py)

Both baseline control transports close the connection after each exchange. Implement bounded reads over the existing authenticated request path first. Enable connection-specific negotiation reuse only on a transport that keeps that exact authenticated connection alive. Count connections and ranges separately in the 65 MiB comparison, so an improvement in request overlap cannot be mistaken for a reduction in handshakes. [Control transports](../src/loom/queue/_coordinator_transport.py) · [Native request negotiation](../src/loom/queue/_coordinator_client.py)

The caller also traverses an administrative path inside `_run_checks`. Enumerate exact check IDs at entry, then read the owned gate once. Reuse a grant only when its request, principal, resources and predecessor still match. Serialize new grants by the gate revision. If a reply is uncertain, recover that mutation before advancing the revision again. Offer each host a share of the remaining preparation time. Schedule nonexclusive GPU capability SSH after native dispatch, and pass the deadline through both a retained host receipt lookup and the physical call. Record which verified checks have passed in this observation round so a short continuation can work on the remaining checks. Before reopening, recheck live gate settlement and host policy/session identity. Local input and release verification still perform filesystem I/O. A transport deadline alone cannot interrupt a blocked filesystem call. [Maintenance owner](../src/loom/fleet/upgrades.py) · [SSH receipt replay](../src/loom/fleet/ssh_operations.py)

**Proof.** Use the reviewed 24-check shape and 65 MiB fixture. Pause an early transfer, finish a later check and persist its result. Detach mid-download, resume the same check IDs and verify no duplicate admissions, reuse of completed verification and bounded memory. Exercise changed declaration, revoked access, bad bytes and a crash between publication and receipt. Reopen fleet admission only after every required check passes. [Artifact-access contract](../tests/contracts/test_artifact_access_contract.py) · [Dispatch-first regression](../tests/unit/loom/fleet/test_upgrade_efficiency.py)

## 12. Separate sweep submission from terminal waiting

**Current path.** A waiting sweep iterates trials and calls `run(..., wait=True)` for each trial. The next independent trial may be absent from the coordinator while the first occupies only one execution slot. Detaching a waiting sweep currently leaves later trials unsent. That is observable behavior users rely on. [Sweep dispatcher](../src/loom/pipeline/sweep/dispatch.py) · [Waiting-detachment test](../tests/unit/loom/pipeline/sweep/test_native_dispatch.py)

**Change.** Add an opt-in positive submission window, for example `--max-in-flight N`, for waiting sweeps. Default to one and preserve `--no-wait` semantics. Build on the existing manifest update/lock, per-trial operation ID, queue-item ID, deployment attachment and cleanup records. Under a short atomic manifest update, retain the exact intent and reserve a window slot before the network send. Count accepted nonterminal and uncertain submissions. Recover existing intents before selecting new ones, including after restart or concurrent invocation for the same sweep. Perform the RPC outside the manifest lock.

```python
while watcher.has_time() and sweep.has_work():
    for intent in sweep.reserve_up_to(window):
        submit_or_recover_original_operation(intent)
    for observation in observe_ready(sweep.in_flight(), watcher.deadline):
        sweep.record_observation(observation)
    sweep.wait_for_progress_if_needed(watcher.deadline)
```

Refill as a slot really becomes available. A lost reply occupies its slot until the original operation is reconciled. Keep deployment lifetime ownership correct when trials share a service. On detachment record accepted, unresolved and unsent work. Status and collection stay passive. Explicit resumption via the execution entry point can continue the remaining selected trials.

Recovery has two ordering requirements. A second sender can receive a local refusal after the first sender's reply was lost. That refusal establishes only what happened on the second attempt. Keep the slot reserved until the original operation is reconciled. A run-owned service can also retire after its last job releases, before the sweep has recorded the terminal observation. Reopen the bound coordinator and read the retained operation to finish cleanup. A later observation from another caller must respect the admission revision already saved in the manifest.

The wider window uses independent bounded status reads with one pending read per trial. Each trial owns its client through the physical exchange, including after its caller detaches. Available status readers remain independent of terminal cleanup. A slow status RPC for A can therefore remain outstanding when the manifest records B’s terminal admission and C takes the freed slot. Reconnecting a retired service uses the exact bound coordinator. A failed reconnect retains the uncertain trial's slot for a later observation. [Waiting-window loop](../src/loom/pipeline/sweep/_window.py)

**Proof.** With window two, hold A in RUNNING and observe B admitted before A reaches terminal. With the default window detach and verify B remains unsent. Interrupt immediately before send and immediately after durable acceptance, then resume under the same operation and queue-item IDs. Check cleanup with a shared deployment and verify status/collection cause no new admissions. [Sweep dispatch integration](../tests/integration/pipeline/sweep/test_native_dispatch_integration.py)

## Qualification and rollout

1. **Take comparable measurements.** Use full qualification sampling on the isolated deployment with the same agents, manifests, admission mix and injected delays before and after. Correlate existing operation/assignment/session IDs and renewal sequence. Measure sender queue, transport exchange, coordinator lock wait and hold, SQLite busy wait, durable request receipt, worker queue age and execution, physical effect, result commit, release and caller observation. Use monotonic durations within a process. Relate machines by identity. Record percentiles and sample counts per operation and lane, queue maxima, errors/retries, bulk throughput and actual worker/resource occupancy. Keep production telemetry sampled. [Timing implementation](../src/loom/queue/_phase_timing.py)
2. **Prove independence at each change.** Run the item’s barrier, stale-state and restart cases on the affected entry points. For capacity bounds, hold the actual dependency after the caller times out and assert that its occupied slot is still accounted for. Reuse tests for exact ownership, replay, containment and cursor/receipt durability. Record the precise revision and selectors. A passing fixture covers only the exercised path.
3. **Qualify retained state and mixed versions.** Exercise owned upgrade of existing coordinator, workspace and agent SQLite roots, including old receipts and offline hosts. Run an old agent against the new coordinator and the new agent against an older coordinator using negotiated fallback. Check old-client artifact/event behavior, lost replies around committed effects, stale responses across replacement, and actual reopening of a qualified retained root by the proposed rollback version.
4. **Run the canary in isolation.** Combine concurrent registrations, renewals, cancellations, event backlog, publication and artifact verification. Require existing renewal p99 below 1 s normally and below 5 s under injected delay with the 30 s offer lifetime. Compare bulk throughput to the same baseline. Require the per-issue independence and ownership checks even if renewal p99 already passes. Record request, start, containment, verified completion and release separately.
5. **Use the existing whole-fleet maintenance upgrade.** After the canary passes, confirm admitted work has settled or that the authorized cancellations have durable settlement. Drain through the supported upgrader, preserve coordinator roots, agent journals, inventory and submission IDs, and use one retained upgrade operation. Verify every required check and fresh per-host evidence before reopening normal admission. If verification stalls or a check fails, keep the maintenance state, expose the exact pending check and resume the same operation or use the supported forward repair for its recorded phase. The previous-release reopen is an isolated compatibility gate. Production recovery after service replacement follows the [whole-fleet upgrade contract](fleet.md#whole-fleet-service-runtime-upgrades).

For the matched workload in steps 1 and 4, use equivalent clean starting state and the same physical resource and check policy for both releases. Start normal renewals and collect a normal-load interval. During a second interval, hold a real storage range for 31.5 s while independent clients register, relay a known event sequence, cancel a known running assignment and observe the remaining checks. Verify the overlap in the traces. Collect renewals per agent and in aggregate, with sample counts, deadline failures and missed renewals. Record verified bytes per elapsed transfer interval, retries, check IDs and each owner's stop and release proofs. Track the observation deadline separately from the check's allowed execution time. This eight-agent, 24-check comparison supplements the existing five-agent control fixture. [Control fixture](../tests/integration/queue/test_coordinator_responsiveness.py) · [Maintenance checks](../tests/integration/fleet/test_runtime_upgrade.py)

### What has evidence on the implementation branch

The numbered current paths above describe the pinned baseline. The following changes have separate, local evidence on `fix/lifecycle-progress`.

| Change | Implementation | What the evidence establishes |
|---|---|---|
| Timings | `04b48049` | The isolated deployment can record all requests and separate sender queue time from the exchange. |
| Short coordinator writes and start permission | `7a7d9be6` | A waiting registration releases the state guard during contention. Cancellation during delivery decoding or the external authority check prevents the subsequent start permit. [SQLite contention tests](../tests/unit/loom/queue/test_agent_waiting.py) · [Start-permit race test](../tests/unit/loom/queue/test_coordinator_responsiveness.py) |
| Preparation and cancellation acceptance in item 1 | `37b10bd2` | A peer read finished with a real writer still open and again with the cancellation's execution lookup paused. Replay returned the original receipt without a new execution lookup. Two native store orderings gave one identity owner: an intervening SLURM reservation invalidated the negative lookup, and an earlier public receipt prevented the SLURM reservation. The parallel SLURM admission-limit cases also passed. [Preparation interleavings](../tests/integration/queue/test_preparation_operations.py) · [SLURM limits](../tests/integration/queue/test_slurm_ready_stage.py) |
| Embedded binding and cancellation in items 1 and 7 | `e77149b4` | A remote assignment reached release while the local bind was paused. On restart after a committed bind and lost reply, the coordinator settled the same assignment with no local launch. Embedded and authenticated authorities also refused a competing binding or an exempt live producer. [Native mixed run](../tests/integration/queue/test_agent_session_transport.py) · [Authority contracts](../tests/integration/authority/test_action_producer_cancellation.py) |
| Compound reservation in item 1 | `ed710f40` | Real control and execution writers blocked begin, and readers blocked commit. In all four orderings a peer control read completed, no partial claim survived, and exact retry acquired one claim. Substitution after owner validation refused reserve. A lost execution commit reply invalidated the sampled generation and replayed the single committed reservation. Native local/remote scheduling, SLURM admission limits and competing operation IDs have separate tests. [Contention and substitution](../tests/unit/loom/queue/test_agent_waiting.py) |
| Reconciliation clock write in item 1 | `fc39b47c` | While another connection held a real SQLite write transaction, a full empty reconciliation turn returned, a registered agent read its controls and the scheduler skipped dispatch. After release the next turn established clock health. The sample/high-water serialization and durable clock-degradation tests passed. [Contention test](../tests/unit/loom/queue/test_agent_waiting.py) |
| Current and historical offers | `e8603761` | Session invalidation updates the current row while retained revision and latest-row lookups retain their indexes. [Agent session tests](../tests/unit/loom/queue/test_agent_sessions.py) |
| Run observers | `be32999e` | B reaches RUNNING with A's callback still blocked. The callback queue is bounded and audit evidence is applied at a revision-safe point. [Observer regression](../tests/unit/loom/queue/test_lifecycle_observers.py) |
| Observer backlog and replay in item 3 | `23b5f925` | Operator status reports the oldest pending fact in milliseconds through callback evidence application. With a blocked sink this age advanced while another run committed. The backlog returned to zero, all 24 events for the first run stayed ordered, and duplicate delivery was suppressed. The native two-stage run recorded its sink failure and both output commits. Restart selected only future callbacks. [Observer tests](../tests/unit/loom/queue/test_lifecycle_observers.py) · [Native execution and restart](../tests/integration/queue/test_lifecycle_observers.py) |
| TLS accept | `7ea2918f` | A second authenticated client reaches dispatch with a negotiation paused, and shutdown closes sockets still owned by the handshake workers. [TLS transport tests](../tests/integration/queue/test_agent_session_transport.py) |
| Local event journals and single-event relay portion of item 8 | `edb2327b` | A 1,024-event workspace changes 1,024 acknowledgement rows in total, including replay of the last acknowledgement. The final flush includes a fact handed off during the last exchange. The selected remote restart and managed release/decline integration cases passed. [Outbox regressions](../tests/unit/loom/queue/test_remote_stage_execution.py) |
| Negotiated relay portion of item 8 | `4362651e` | The sender uses at most 32 events and 65,536 encoded bytes. An interrupted append or lost reply replays the same events. A wrong digest leaves the local outbox pending. An old-peer handshake selects singles. [Protocol and journal tests](../tests/unit/loom/queue/test_managed_local.py) |
| Release, sampling and sender deadlines in item 4 | `64967ad0` | A drain completed while sampling was paused and while an independent release reply was delayed. Applying the delayed reply preserved the newer session. Queue expiry prevented dispatch of a waiting request. [Overlapping agent operations](../tests/integration/queue/test_concurrent_outbound_agent.py) · [Retry and queue budget](../tests/unit/loom/queue/test_agent_transport_policy.py) |
| Release replay across coordinator restart in item 4 | `53a0765d` | After a committed release and lost reply, the reconciled agent replayed its exact original proof. When the coordinator had received nothing, only its explicit epoch refusal permitted rebinding the proof to the reconciled session. Both loopback mutual-TLS cases reached RELEASED without a second physical launch. [Release restart tests](../tests/integration/queue/test_concurrent_outbound_agent.py) |
| Lifecycle request capacity in item 4 | `bcab8c22` | A fresh run received start permission with both sender transfer slots and all four receiver transfer handlers occupied by authenticated output traffic. SQLite contention reused the prepared proof, and cancellation during the pending permit prevented authorization. Immediate local idle polls yielded for control receipt. [Concurrent agent tests](../tests/integration/queue/test_concurrent_outbound_agent.py) |
| Embedded GPU observation in item 6 | `22efc40e` | A CPU job reached SUCCEEDED while the original GPU observation was paused. A scheduling reload replaced the provider during an outstanding sample. Its cache remained unknown until the new provider supplied its own observation. [CPU admission](../tests/integration/queue/test_local_daemon_production.py) · [Provider reload](../tests/unit/loom/queue/test_local_daemon.py) |
| Supervisor stop delivery in item 7 | `b9fe275f` | A Docker assignment received exactly one kill through its backend adapter while two other Docker operations remained paused. With the stop worker occupied, duplicate requests coalesced against the same pending launch and shutdown stayed fenced. Native stop and lost-launch-reply cases also passed. [Supervisor IPC tests](../tests/unit/loom/queue/test_agent_process_supervisor.py) |
| Outbound cancellation and restart in item 7 | `3aa76242` | With an empty work-poll reply held, B received its native stop while A's first stop IPC was paused. After the poll settled, the machine command recorded B's cancelled worker result while B's ordinary execution and assignment-control views were paused and A's proof was unavailable. B then reached RELEASED while the machine command remained unacknowledged. Stopping and reopening the agent preserved that command and produced two released assignments from the original two launches. A stale reload requested zero stops. Separate release-loss cases preserved ordered availability in both coordinator-epoch scenarios, measuring from the post-commit reply after any HTTP 202 preparation responses. [Native two-worker fixture](../tests/integration/queue/test_concurrent_outbound_agent.py) · [Ownership and stale-reload cases](../tests/unit/loom/queue/test_agent_control_waiting.py) |
| SLURM stop delivery in item 7 | `33d8bf3d` | With two observation workers blocked inside the scheduler adapter, a third known job received an exact `scancel` before either observer returned. A later stale batch result could not overwrite its stop decision. These tests exercised the adapter with a controlled scheduler runner. [Command progress](../tests/unit/loom/queue/test_agent_slurm.py) · [Batch interleavings](../tests/unit/loom/queue/test_slurm_batching.py) |
| Mixed local and remote cancellation in item 7 | `21d7f763` | The remote control and release advanced with the local claim abort held. Cancellation reached terminal after the provider returned, after restart following a committed journal release, and after recovery of a committed authority grant with a lost reply. [Mixed-owner integration](../tests/integration/queue/test_agent_session_transport.py) |
| Preparation child release in items 6–7 | `e377f4c8` | An execution writer could stay open during the read. Independent reconciliation completed with the read paused. A new reference invalidated the sampled proof. A new child joined the same target before finalization and the control stayed pending through a second scan. Repeating the public cancellation on a settling mixed-owner run preserved its diagnostic and revision. Exclusive retained-root startup rebuilt all three native, SLURM and preparation lookup indexes, and query plans selected them. [Preparation control](../tests/integration/queue/test_preparation_operations.py) · [Changing child membership](../tests/integration/queue/test_reconciled_runs.py) |
| Service lifetime and retirement in item 7 | `1bc061b6` | The agent decision, coordinator decision and client lifetime observation each allowed an offer renewal during a paused physical-owner scan. A remote assignment appeared before the scan returned. All three paths retained the service. The explicit receipt and fence replayed on both SQLite storage configurations. New work, abandoned attachments and acknowledgement of an earlier retirement have separate integration coverage. [Interleavings](../tests/unit/loom/queue/test_agent_waiting.py) · [Removal](../tests/integration/queue/test_role_retirement.py) · [Run-owned lifetime](../tests/integration/queue/test_service_lifetime.py) |
| Recovery lookup and sequence read in item 9 | `526c5c16` | One- and 32-assignment lookups each issued one indexed recovery query against 4,096 unrelated records. Closed SLURM recovery retained its special withholding rule. The page-cursor tests and guarded-recovery integration passed. [Page tests](../tests/unit/loom/queue/test_slurm_task_pages.py) · [Guarded recovery](../tests/integration/queue/test_slurm_ready_stage.py) |
| Page construction and evidence revalidation in item 9 | `18cc8202` | Another agent renewed during paused page packing. Recovery creation and an advanced evidence sequence each forced reconstruction under the original cursor. An unrelated renewal returned the original page. The active-owner lookup index reopened on an existing root. [Page interleavings](../tests/unit/loom/queue/test_slurm_task_pages.py) |
| Fleet observation portion of item 10 | `c95270b7` | A second observation completes while the first is paused. The report preserves inventory order, per-host time and per-host failure. [Fleet observation test](../tests/integration/fleet/test_configuration.py) |
| Watch notifications in item 10 | `de6bd901` | Unrelated commits leave a subscribed operation asleep. Operation, admission and queue-item changes are signalled after commit, with rollback, savepoint, independent SLURM-owner, fallback and shutdown coverage. [Keyed waiter tests](../tests/unit/loom/queue/test_service_signals.py) |
| Storage workers in item 6 | `dae45f5b` | With an external target lock held and a renderer paused, the coordinator retained an independent image and admitted and cancelled another run. The locked target later published once from one report read. [Combined storage test](../tests/integration/queue/test_preparation_operations.py) |
| Scheduler ownership in item 6 | Background owner validation, keyed admission binding and prepared embedded reservations | Two independent workspaces reached a barrier before either claimed the single CPU. The scheduling thread committed the higher-priority assignment first. Its reply was lost, and both original assignments eventually released after exactly two supervisor launches. Separately, a lower-priority peer used the sole CPU while the higher-priority workspace was blocked, and a peer run finished while another admission's authority bind was paused. [Priority and peer progress](../tests/integration/queue/test_local_daemon_production.py) · [Owner checks](../tests/unit/loom/queue/test_local_daemon.py) |
| Admission metadata and READY lookup in item 6 | Priority cursor, indexed owner checks and bounded dispatch turns | With 12,000 retained admissions, continuation after a deleted cursor sought past the preceding 7,970 rows and read the last members of the original population before a later urgent arrival. A saturated discovery pass preserved an off-page ticket. READY pages resolved admissions by ID and the global one-slot and off-page priority cases passed. [Database cursor](../tests/unit/loom/queue/test_admission_scan.py) · [Saturated sweep](../tests/unit/loom/queue/test_coordinator_responsiveness.py) |
| Embedded provider observation in item 6 | One capacity worker and a shared placement/offer observation | A real remote assignment reached RUNNING while the local provider was still paused. The same native run then finished on both agents. A paused observation from before scheduling reload was discarded, and no local candidate became usable until the replacement sample completed. The prepared-workspace arbitration, exact lost-commit replay, held-input bypass and independent-run cases passed with asynchronous sampling. [Mixed placement](../tests/integration/queue/test_agent_session_transport.py) · [Reload ordering](../tests/unit/loom/queue/test_local_daemon.py) |
| Background recovery and admission retry in item 6 | Bounded, individually owned recovery attempts and indexed pending admission retries | B's durable recovery settled while A remained inside its authority observation. Restart after an actual committed authority retry and a lost reply returned a complete manual reconciliation turn while replay was held. Releasing the barrier let existing retry clients converge on the same admission. The synchronous startup recovery and closed-operation replay tests also passed. [Independent recoveries](../tests/unit/loom/queue/test_local_daemon.py) · [Retained admission retry](../tests/integration/queue/test_preparation_operations.py) |
| Run and cancellation reads in item 6 | Resumable per-run reconciliation with two bounded authority reads | With one run's scoped snapshot paused, a peer acquired the sole CPU and completed. Cancellation before and after peer submission fenced the held run. Exactly one process launched in each case. A separate scheduling reload withheld READY preparation until a replacement observation completed. Targeted tests also covered a late cancellation, mixed containment owners, and release before terminal cancellation. The separate READY dispatch read and lower-level SLURM reconciliation require their own isolation checks. [Peer and cancellation tests](../tests/integration/queue/test_local_daemon_production.py) |
| Restart repair of legacy cancellations in items 6–7 | Indexed cursor and bounded recovery workers | On restart a retained admission reported CANCELLED while the underlying run still reported RUNNING with a cancelled stage. While its authority read was held, a new run completed using the only CPU. The legacy run then settled under its coordinator cancellation operation. Repair rechecks the original admission revision before recording intent. [Legacy restart regression](../tests/integration/queue/test_local_daemon_production.py) |
| READY selection, audit scheduling and fair run slices in items 3 and 6 | `477ab80f` | Paused managed and SLURM selection reads allowed the sole-CPU peer to finish and stale reads could not start cancelled work. With a physical SQLite audit append paused, B finished before A resumed. The 257-stage unavailable-route case reached its managed output under the original deadline. Both priority orderings, lost-commit staging, callback restart, mixed local/remote progress, and one ordinary SLURM submission passed their targeted cases. [Native scheduler barriers](../tests/integration/queue/test_local_daemon_production.py) · [SLURM](../tests/integration/queue/test_slurm_ready_stage.py) · [Observer integration](../tests/integration/queue/test_lifecycle_observers.py) |
| Transfer contention and useful watcher time in item 11 | `02001e2f` | Three concurrent check owners shared four active range readers and verified three independent destinations. A 65 MiB native transfer resumed under the same ID after observation expiry. A growing transfer used the rest of the caller's budget, an unchanged receipt returned waiting, and nonterminal peer results survived detachment. Separate cases distinguished transport-attempt expiry, refused capacity and whole-observer expiry, including exact offset retry. Physical-fleet throughput requires remeasurement. [Range contracts](../tests/contracts/test_artifact_access_contract.py) · [Check watcher](../tests/unit/loom/fleet/test_upgrade_efficiency.py) · [Native transfer](../tests/integration/fleet/test_self_tests.py) |
| Fleet check result publication and exact replay in item 11 | `7a3a63ee` | In a 24-check orchestration fixture, all checks reached dispatch before observation, and the first CPU check stayed paused until the later storage receipt reached disk. The other checks still published after one observation raised an error. In separate native integrations a lost start reply recovered the same CPU and storage admissions, the ordinary 65 MiB download verified, and an interrupted send recovered a durable native refusal. [Completion ordering](../tests/unit/loom/fleet/test_upgrade_efficiency.py) · [Native recovery](../tests/integration/fleet/test_self_tests.py) |
| Resumable storage verification in item 11 | `535a7b5b` | A native 65 MiB download resumed from verified scratch ranges, recovered a crash after atomic publication, and retained its verification after the transient result was removed. A separate HTTPS test read twelve ranges with at most four connections and one negotiation per reused socket. Changed declaration, revoked access, invalid bytes and old-peer fallback have targeted coverage. [Recovery](../tests/integration/fleet/test_self_tests.py) · [TLS](../tests/integration/queue/test_artifact_access.py) · [Access contract](../tests/contracts/test_artifact_access_contract.py) |
| Check worker ownership in item 11 | `8414c60d` | Two 0.8 s watchers detached while the original storage worker was still occupied. A later CPU result had already reached disk. The continuation retained the original dispatch IDs and only one storage worker. An occupied standalone receipt lock returned retained progress. [Watcher](../tests/unit/loom/fleet/test_upgrade_efficiency.py) · [Receipt owner](../tests/integration/fleet/test_self_tests.py) |
| Outer maintenance watcher in item 11 | `8c4e9ddb` | A 24-slot orchestration test resumed one real native 65 MiB check. Its 23 simulated peers reached durable success while the transfer was paused. A second interruption occurred after publication. The check recovered the same native admission and verified the published bytes. Separate tests exercised a slow first preparation, a lost authorization reply, a changed grant, and the isolated runtime upgrade through abort, retry, native checks and restoration. [Combined transfer](../tests/integration/fleet/test_self_tests.py) · [Grant ordering](../tests/unit/loom/fleet/test_upgrade_efficiency.py) · [Runtime upgrade](../tests/integration/fleet/test_runtime_upgrade.py) |
| Waiting sweep window in item 12 | `ea7b3619` | In an isolated three-trial run, B and C reached SUCCEEDED while A's worker remained paused. With a window of two, C was submitted after B reached terminal. Two interruption cases resumed the original operations with one durable preparation and one admission per trial. A refused resend after a lost reply left the default window occupied. [Sweep integration](../tests/integration/pipeline/sweep/test_native_dispatch_integration.py) · [Manifest and uncertainty tests](../tests/unit/loom/pipeline/sweep/test_native_dispatch.py) |
| Independent waiting-sweep observations in item 12 | `cca46b32` | Trial A's real native status response was withheld. B and C both reached SUCCEEDED before A's reply was released. A deadline test detached with a read physically occupied, then verified client release, unchanged retained receipts, and resumption with three distinct sends. Concurrent window accounting and interrupted-send regressions passed. [Native RPC barrier](../tests/integration/pipeline/sweep/test_native_dispatch_integration.py) · [Detachment](../tests/unit/loom/pipeline/sweep/test_native_dispatch.py) |

### Isolated baseline measurements

The eight-agent maintenance deployment used one coordinator, eight separate resident agent services and eight distinct A100 device UUIDs on one host. On reference `91a2e86e98b1`, setup took 833.09 s and the existing maintenance operation took 563.33 s including its continuations. The retained receipts showed eight released CPU checks, eight released storage checks at 65 MiB each, eight contained nonexclusive CUDA checks, and the applied maintenance-open receipt. Across the storage range interval the rate was 520 MiB / 172.543 s, or 3.014 MiB/s. The injected 31.5 s delay was included. All eight agents renewed during the hold. The p99 renewal was 0.224 s across 510 requests outside it and 0.091 s across 51 overlapping requests using nearest rank. The initial measurement reader expected observations inside the dispatch history. Reading the public check results, per-step GPU receipts and open receipt verified all 24 outcomes from the completed operation.

A separate matched-load fixture on that revision used eight authenticated resident identities on one coordinator. During a 31.544 s hold in a real 65 MiB storage read, two agents registered, a running job was cancelled, two assignments released and 128 distinct workload events reached the coordinator event store. Six active renewal senders completed 950 exchanges wholly inside the hold. Renewal p99 was 0.150 s across 99 samples before the hold and 0.093 s during it. Durable cancellation acceptance took 0.0094 s. End-to-end verified transfer throughput including the hold was 1.131 MiB/s. Compare each workload to its own run on the rollout revision.

The same eight-identity load on isolated candidate `33b8c416` verified 65 MiB at 1.467 MiB/s including the 31.563 s hold. Renewal p99 was 0.122 s for 111 normal requests and 0.277 s for 738 held requests. Two new registrations, two releases, two results and 128 distinct workload events overlapped the hold. Cancellation acceptance took 0.0282 s. Both latency targets passed. Held renewal latency and cancellation acceptance were slower than the reference sample. These figures apply to this candidate and fixture.

The eight-service maintenance fixture at `33b8c416` stopped during initial setup, before the upgrade. All eight agents recorded CPU and storage verification, and all eight GPU checks passed. One CPU result still reported `fresh_offer_unavailable` after recording its SHA-256. The fixture asserted completion on the first setup observation and tore down its isolated services. Resume the supported setup operation under the same ID when it returns `waiting`, then independently require 24 passing upgrade results and open admission. This run provides no upgrade timing or deployment qualification.

On isolated candidate `347e8025`, setup completed under the same operation ID after 879.07 s. Maintenance completed in 1,473.27 s, compared with 563.33 s on the reference. Both the published and native receipts verified all 24 checks, 520 MiB, released assignments on all eight workers, eight distinct GPU identities and open admission. Renewal p99 was 0.296 s for 1,959 outside-delay and 0.239 s for 41 overlapping requests. The storage range interval was 1,147.215 s, or **0.453 MiB/s compared with 3.014 MiB/s**. The test's original observer had a 1,200 s cutoff. At an inter-observation boundary a second observer continued the same operation with the same pinned native upgrader. The nine services ran continuously, and the original observer resumed and independently verified completion. The elapsed time includes this handoff. These results qualify the stated checks on that candidate and demonstrate a throughput regression requiring a new measurement.

The candidate served 2,418 full-size ranges in the eight-host run, versus 2,081 on the reference. Gaps longer than one second between successive full-range starts totaled about 684 seconds, versus 32 seconds on the reference. These are aggregate timestamps at the server and include periods spent doing other work. The source exposed two amplification mechanisms. Each short observation restarted administrative and artifact-selection work, and three check workers could independently request four ranges each although the server permits six concurrent long client requests. A third boundary is the ten-second HTTPS exchange deadline. When that attempt expires while the caller still has time, retry the same authorized offset once. Give an exhausted attempt, a refused slot and an elapsed observer separate pending codes. The check watcher now gives growing transfers a fair share of remaining time. Simultaneous fleet transfers to one coordinator share physical range workers while keeping requests, credentials, deadlines and destination checks private. Measure range starts, completed bytes, capacity refusals, deadlines and phase durations on the next physical canary to determine their respective contributions. [Check workers](../src/loom/fleet/_check_workers.py) · [Range reads](../src/loom/_artifact_ranges.py) · [HTTP admission](../src/loom/queue/agent_session_transport.py)

The matched eight-identity workload on `02001e2f` verified 65 MiB at 1.592 MiB/s including the 31.508 s hold. Renewal p99 was 0.133 s for 119 normal requests and 0.233 s for 729 overlapping requests. Two registrations, two results, two releases and 128 distinct events were recorded. Cancellation acceptance took 0.0438 s. On this workload the reference had 1.131 MiB/s throughput, 0.150/0.093 s renewal p99 and 0.0094 s cancellation acceptance. The separate eight-service maintenance comparison measures the controller and its 24 checks.

### Mixed-peer and retained-root exercise

Isolated coordinator and agent interpreters used baseline `91a2e86e98b1` and candidate `bcab8c22` over mutual TLS. Each scenario interrupted local completion after the coordinator had accepted the release, replayed it with a restarted agent, shut down cleanly, reopened the same roots, and ran a second admission. The retained supervisor showed exactly two launches for the two successful admissions.

| Initial coordinator / agent | Agent replaying the release | Coordinator / agent after clean shutdown | Initial event calls | Second admission event calls |
|---|---|---|---:|---:|
| Candidate / baseline | Candidate | Baseline / baseline | 45 singles | 45 singles |
| Baseline / candidate | Baseline | Candidate / candidate | 45 singles | 1 single and 3 batches |
| Candidate / candidate | Candidate | Baseline / baseline | 1 single and 3 batches | 45 singles |

The native supervisor requires the normal clean-shutdown evidence before a stopped process owner can rotate on the same boot. A forced test-only shutdown correctly refused reopen. The successful runs used the supported clean-shutdown route. This exercise covers native execution, event negotiation and release. Repeat it on the final candidate, including any additional durable formats introduced by the artifact and sweep changes.

### Remaining implementation and qualification work

| Items | Next piece to deliver or qualify | Evidence needed to close it |
|---|---|---|
| 1–3 | Repeat the distinct writer, binding-recovery, retained-root and audit/readiness cases on the rollout revision. | Exercise a competitor at each distinct lock/transaction shape and a blocked sink across readiness changes. |
| 4–5 | Repeat the isolated listener overload and certificate-rotation cases alongside the lifecycle reservation and restart cases on the final candidate. | A start-permit request finishes with both bulk sides occupied. Lost releases before and after commit recover correctly across restart. Four isolated listener tests passed on the local candidate for independent negotiation, overload/shutdown, certificate replacement and live credential policy. |
| 6–7 | Finish isolating blocking observations and the remaining reconciliation phases. Local native priority, lost-commit recovery, and isolation of owner validation and authority binding have targeted integration or unit evidence. Qualify local, remote and SLURM control together on the final revision. | Hold the owner-store probe while an independent control progresses. Replace a store between probe and reservation and require the physical launch to be withheld. Combine the child-membership, pre-grant release, blocked scheduler observation and agent-restart cases with the isolated canary. |
| 8–10 | Exercise the journal, task pages and targeted watches together on retained state under load. Repeat the real mixed-peer checks on the final candidate. | Exact final event, stable safe cursor and current recovery decision, bounded unrelated rereads, and old-version reopen. |
| 11 | Qualify the complete maintenance workflow on final candidates, including an eight-agent canary with real checks. Exercise slow administrative inputs as well as native RPC and download deadlines. | With 24 checks, a fast later result is durable while the first transfer is paused. A detached 65 MiB transfer resumes under its check ID and retains verification through a later pending observation. |
| 12 | Include retained manifests and shared service retirement in final candidate and rollback qualification. | An old reader can reopen retained state, the new reader recovers the same IDs, and the combined run preserves the configured submission window. |

After component coverage, run the mixed-version, rollback, combined-canary and maintenance steps above. The reference five-agent measurement supplies a comparison for its original workload. Compare the final candidate with the two eight-agent baselines above, preserving each workload and its measurement interval. Record any additional baseline separately if its workload changes.
