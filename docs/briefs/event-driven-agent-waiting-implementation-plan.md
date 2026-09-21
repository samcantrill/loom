# Event-driven agent waiting: implementation plan

Implemented on 2026-09-22 as an ordinary feature change, not a numbered roadmap
stage. The design and examples below explain the accepted behavior; the
implementation evidence at the end records the concrete owners, measurements,
and validation.

Replace the coordinator's repeated database checks during an agent work request
with an in-memory notification and a bounded wait. Keep the existing HTTPS
request, response, assignment identity, and recovery protocol.

The result should be a quieter idle coordinator: it checks for work when a request
arrives, when something relevant changes, or when a deadline requires a check.
An idle agent should no longer cause database queries every 50 milliseconds.

The implementation evidence tree is the clean Loom control checkout at
`8c647195f49ae571605118640fa39233c09215a2`, the fetched `origin/develop` when this
plan was prepared for publication. Earlier discussion examined rphys's Loom pin
`2f32bc77ed115b75ea04432f23f94e9f641384b2`. The chosen implementation baseline also
contains the newer same-epoch fenced-poll recovery fix; preserve it. Refresh the
source comparison if implementation starts on a later revision.

All snippets below illustrate proposed private wiring. Names and intermediate
types are implementation choices, not new public APIs.

**1. What changes, and why**

Before this change, an agent opened a work request with a maximum five-second wait. The
coordinator registers that poll durably, checks for an assignment, and then runs
a loop resembling this:

```python
while before_request_deadline():
    sleep(0.05)
    check_authorization_session_and_offer()
    assignment = take_targeted_delivery()
    if assignment is not None:
        return assignment
return record_wait_response()
```

The former inner-loop interval was `LocalDaemonConfig.poll_interval_seconds`; 0.05 seconds is
the default. Each iteration opens database connections, checks state, and uses
`BEGIN IMMEDIATE` for the delivery lookup even when no assignment exists. Offer
validation also executes the accepted-time metadata update. In the ordinary
inner-loop validation connection that update is not committed before close.

There are two separate loops here. Across the network, an idle agent renews its
HTTP work request after the five-second wait response. Inside the coordinator,
that one request previously caused repeated 50 ms checks. The approximately 100
checks are local checking cycles, not 100 HTTP requests. This proposal changes
the inner loop; agents continue speaking the same long-polling protocol.

Distinguish SQL statements, write transactions, committed row changes, and
physical disk writes. They are different measurements. This change should reduce
idle queries, connection churn, write attempts, and writer-lock acquisitions.
It does not promise that every removed check corresponds to a removed durable
write or disk flush.

With the default interval, one five-second idle request runs about 100 checking
iterations, excluding processing time. The proposed path is:

```text
agent sends the same HTTP work request
    -> coordinator registers it and checks existing state
    -> handler sleeps without an open database transaction
    -> assignment commit or relevant change wakes the handler
    -> handler validates current state and returns the existing response
```

If nothing changes, the handler wakes for a relevant deadline. Work committed
before the handler begins waiting is found by its initial state check.

| Activity | Effect of this implementation |
| --- | --- |
| Repeated idle delivery/session/offer checks | Removed between relevant events and deadlines. |
| Empty delivery transactions | Substantially fewer. |
| Poll registration and durable response receipts | Retained. |
| Assignment, execution, result, and release records | Retained. |
| Five-second HTTP renewal | Retained, including agent journal operations. |
| Resource-offer refresh, 30-second offer TTL, and 10-second HTTP client timeout | Retained. |
| Scheduler reconciliation and resource observation | Retain their existing timing and owners. |
| Thread-per-connection HTTP server | Retained; sleeping handlers still occupy threads and sockets. |

Do not introduce WebSockets, a message broker, a durable event log, a public event
API, or a second job queue. Longer HTTP waits and a full streaming transport can
be considered separately after measurement. This work belongs in Loom; rphys
would consume a qualified published revision later.

**2. Existing owners and proposed updates**

| Owner | Proposed update |
| --- | --- |
| [`queue/agent_sessions.py`](../../src/loom/queue/agent_sessions.py), `AgentSessionService.wait_for_work` | Replace the sleep/check loop with notification-driven waiting. Preserve sequence validation, replay, fencing, and response schemas. |
| Same file, `_take_targeted_delivery` | Retain the authoritative delivery transition and poll receipt. Keep validation and delivery correctly ordered against session/policy changes. |
| Same file, `_target_remote_delivery` | Notify the selected session after its durable delivery transaction commits, including the successful replay path when a waiter may already exist. |
| Same file, control acknowledgement, retirement, and session replacement | Notify affected waiters after the committed change that invalidates their poll or offer. |
| [`queue/local_daemon.py`](../../src/loom/queue/local_daemon.py), `LocalDaemon` | Own the private waiter collection, policy/lifecycle notifications, and its start/stop lifetime. Keep the existing scheduler `_wake` separate. |
| Same file, policy replacement and scheduling reload | Wake waiting agents after policy installation; preserve ordering with the delivery decision. |
| [`queue/agent_session_transport.py`](../../src/loom/queue/agent_session_transport.py) | Preserve the wire/client behavior. Adjust server shutdown integration only if needed to finish registered waiters before owner teardown. |
| [`queue/deployment.py`](../../src/loom/queue/deployment.py) | Keep poll duration, offer refresh, reconnect, and retained-work recovery unchanged. |
| [Queue documentation](../features/queue.md), [protocol documentation](../features/protocols.md) | Explain that outbound HTTP long polling remains, while the coordinator waits on notifications internally. |

There is one current consumer for the notification mechanism: pending agent work
polls. Keep the helper private and small, either beside its owner or in a private
queue module if separation improves readability. Do not turn it into a general
event framework or reuse the scheduler's shared `Event`: that event has a
different consumer, and clearing it from either path could interfere with the
other path.

**3. The correctness rule**

The database decides what happened. A notification only asks a handler to check.

An in-memory notification must never reserve resources, create an assignment,
grant execution, mark delivery complete, acknowledge a result, or release a
claim. All of those operations retain their existing owners and records.

The following invariants govern the change:

- One delivery is still bound to its exact session, poll identity, and request
  digest. Existing same-sequence replay, stale/gap rejection, and concurrent-poll
  rejection continue to apply.
- An assignment response and its durable poll receipt remain committed through
  the existing atomic delivery operation. Duplicate notifications cannot create
  another logical assignment.
- Authorization, session state, availability, coordinator identity, and accepted
  time remain checked at their authoritative decision boundaries. A notification
  carries no cached permission to execute.
- Invalidation and delivery have an ordered winner. If invalidation wins first,
  delivery fails under the existing rules. If delivery commits first, later
  cancellation/revocation follows the existing lifecycle; it cannot unsend an
  already committed response. Physical execution still requires its normal grant.
- No handler holds a database transaction, the daemon cycle lock, or the waiter
  collection lock while sleeping.
- Losing a notification can delay discovery until a deadline or reconnect, but
  cannot remove a committed assignment or create extra capacity.

Progress assumes that the coordinator, database, and agent can run again after a
failure. The five-second request duration bounds the intended idle wait, not all
OS scheduling, lock contention, or outage duration. This design does not promise
exactly-once network delivery; it preserves replay of one logical operation.

**4. A small notification primitive**

Use a condition variable plus an in-memory change number for each session with
an active handler. The number means only that something changed since a handler
looked. It is not the durable poll sequence, an assignment number, or an epoch.

For example, a handler observes `7`. An assignment notification increments the
number to `8`. The handler only needs to notice that the number differs; it does
not need to reconstruct an event for every increment. Several notifications can
be covered by one fresh database check.

```python
from threading import Condition


class _PollSignal:
    def __init__(self):
        self._condition = Condition()
        self._generation = 0
        self._closed = False

    def snapshot(self):
        with self._condition:
            return self._generation

    def notify(self):
        with self._condition:
            self._generation += 1
            self._condition.notify_all()

    def wait_for_change(self, observed, timeout):
        with self._condition:
            self._condition.wait_for(
                lambda: self._closed or self._generation != observed,
                timeout=timeout,
            )

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()
```

Add an explicit stopping/closure check to the handler's guarded decision before
database work and delivery. The existing `_require_started()` and session checks
do not observe `_stop`; installed identity remains present while handlers drain.
The new check must exit through the existing service-error and exact poll-fence
cleanup path. Otherwise a closed condition would return immediately and make the
handler query repeatedly until its deadline. No new wire response is needed.
Python documents this
lock-and-condition waiting pattern in its
[condition-variable reference](https://docs.python.org/3.12/library/threading.html#condition-objects).

The daemon owns a collection mapping session IDs to currently subscribed signal
objects. A subscription retains the same object for the whole request, including
its initial check. Concurrent retry handlers may temporarily share that object;
the database still rejects an impermissible second active poll. Track subscriber
ownership so one rejected retry cannot remove another handler's signal.

Remove an entry when its last handler leaves. A notification with no subscriber
can be discarded because the next handler reads durable state before sleeping.
Do not retain entries for every historical session. Close and drain the collection
on stop, rejecting new subscriptions once draining starts. A later daemon start
gets a fresh collection.

Keep the collection lock limited to attaching, detaching, and locating signals.
Never acquire the daemon cycle lock or access SQLite while holding a signal or
collection lock. This prevents the notification mechanism from adding a reverse
lock-order dependency.

**5. Avoid the check-then-sleep race**

Reading the change number must happen before reading durable state:

```python
observed = signal.snapshot()
decision = check_current_poll_and_delivery()
if decision.has_reply:
    return decision.reply
signal.wait_for_change(observed, timeout=remaining_wait)
```

This order covers the three useful cases:

| Assignment commit occurs… | Why the handler notices |
| --- | --- |
| Before the state check | The database check finds the assignment. |
| After the state check but before sleeping | The publisher increments the number; the handler's comparison prevents sleeping. |
| After sleeping begins | The notification wakes the condition variable. |

A concrete instance of the middle case is:

```text
handler:      records generation 7, then finds no assignment
coordinator:  commits assignment A, then changes generation to 8 and notifies
handler:      asks to wait only while the generation still equals 7
condition:    sees 8, so returns without sleeping
handler:      checks the database again and finds assignment A
```

The condition lock makes comparing the number and entering the wait one
synchronized operation. While blocked, the condition releases its lock so the
publisher can acquire it and notify. The handler rechecks durable state after
waking because the notification is a hint, not an assignment or execution grant.

Publish only after a successful commit:

```python
with daemon._connection() as connection:
    persist_targeted_delivery(connection, request)
    connection.commit()
daemon._poll_waiters.notify(request.session_id)
```

The actual publisher is `_target_remote_delivery`, not a new assignment creator.
Do not notify from a `finally` block that also runs after rollback. Do not make
notification failure roll back or retry a committed assignment under a new ID.

A process can stop between commit and notify. That is why notifications remain
temporary hints and why the bounded deadline and restart paths remain necessary.

**6. Replace only the waiting section of the poll**

Keep the existing public method and durable registration/replay rules. Subscribe
before the first state read that can lead to waiting. Use a fixed monotonic
request deadline; repeated notifications must not extend it.

```python
with daemon._poll_waiters.subscribe(session_id) as signal:
    replay = begin_or_replay_existing_poll(request)
    if replay is not None:
        return replay

    deadline = monotonic() + request.wait_timeout_ms / 1000
    try:
        while True:
            observed = signal.snapshot()
            # Includes the new stopping check before any database work.
            decision = check_current_poll_and_delivery(request)
            if decision.has_reply:
                return decision.reply

            remaining = deadline - monotonic()
            if remaining <= 0:
                return finish_existing_poll_at_deadline(request)

            signal.wait_for_change(
                observed,
                timeout=min(remaining, decision.offer_recheck_after),
            )
    except Exception:
        fence_existing_poll_using_its_exact_identity(request)
        raise
```

The helper names stand for the existing session, offer, delivery, and receipt
logic. Keep one authoritative implementation of those checks. Preserve existing
exception classes and exact-identity cleanup. In particular, retain the baseline's
same-epoch fenced-poll recovery and assignment issuer-epoch behavior.

The deadline path performs a final current-state and delivery check, then records
the existing `wait` response if no assignment can be delivered. Order that final
check and receipt against targeting/invalidation through the existing ownership
guard. If targeting occurs after the wait receipt, the assignment remains
`TARGETED` for the next poll. Do not reset the deadline after an unrelated wake.

Use the existing `_cycle_lock` for the short validation/delivery section and
matching policy/session mutations where needed to make their ordering explicit.
At the baseline, several session operations already used this guard, while
`wait_for_work` was not decorated and `replace_agent_policy` assigned the policy
directly. The implementation now guards policy installation and short poll
decisions; it does not decorate the blocking poll.
Do not decorate the entire blocking poll. Audit the direct and HTTP callers and
ensure policy installation participates in the same ordering. Preserve the
existing lock order with scheduling reload and SQLite.

The short guarded decision is conceptually:

```python
with daemon._cycle_lock:
    reject_if_owner_is_stopping()
    validate_current_authorization_session_and_offer(request)
    decision = perform_existing_delivery_transition_if_available(request)

# The guard is released before signal.wait_for_change(...).
```

These operations reuse the authoritative checks and atomic receipt transition
described above. If invalidation wins the guard first, the request is rejected.
If delivery commits first, its receipt remains durable and later control follows
the existing lifecycle. The guard cannot retract an already committed response.
The notification itself never establishes which operation won.

The cycle lock also protects broader reconciliation. Measure lock waiting in the
integration evidence; do not claim the request is a hard real-time deadline or
introduce a new global lock solely to optimize a hypothetical large fleet.

**7. Wake for invalidation as well as assignments**

The former 50 ms loop discovered more than new work. Wire notifications at the
owners of supported state changes before removing that loop.

| Trigger | Owner and notification boundary |
| --- | --- |
| Targeted assignment becomes durable | `_target_remote_delivery`: selected session, after commit; cover its successful replay path. |
| Drain/reload withdraws an offer or fences a poll | `LocalDaemon._control_agent`: affected session after the withdrawal commit. |
| Applied control changes session revisions | `AgentSessionService.acknowledge_control`: affected session after commit. |
| Session replacement | `replace_agent_session`: old session after the replacement/fence decision commits. |
| Clean or command-lifetime retirement | `retire_clean` and `service_lifetime`: after the first committed transition that withdraws eligibility, even if later retirement work fails. |
| Credential/policy installation | `replace_agent_policy` and the scheduling reload installation path: waiting sessions after the new policy is installed under the owner guard. A global wake is proportionate for this rare operation. |
| Coordinator shutdown | Close the waiter collection before dropping coordinator identity, locks, or database ownership; finish handler cleanup before releasing that ownership. |
| Accepted-time health becomes degraded | Notify after the existing degradation commit, using the existing clock-health owner. Avoid notifications for ordinary high-water updates. |
| Offer expiry or request timeout | A deadline wakes the handler without requiring another producer. |

Verify all writes to `agent_poll_state.active`, `agent_offers.current`, session
eligibility/revisions, and policy installation against this table. Some are poll
completion or startup recovery and need no extra notification. Classify each by
whether another live handler can be affected; do not broadcast after every write.

Resource updates that are already forbidden during an active poll remain
forbidden. Do not expand their protocol to justify another event type. Signals
from control changes allow the existing control/reconnect loop to proceed; this
feature does not add control messages to the assignment response.

Order the transition to stopping against the short guarded delivery decision.
Reject new subscriptions, close existing signals, and let each awakened handler
detect stopping and exit without another ordinary checking iteration. Shutdown
must release waiters without holding the cycle lock while joining them. Allow
them to finish their existing receipt/fence cleanup while the root is still owned.
Coordinate server-stop and daemon-stop ordering at their current owners; do not
release the root and leave old handlers mutating it during a new start.

```text
mark the owner as stopping, ordered against delivery
    -> reject new waiting subscriptions
    -> close signals and wake existing handlers
    -> handlers detect stopping and finish exact receipt/fence cleanup
    -> release coordinator/root ownership
```

The cleanup may access the database while the root is still owned. The prohibited
behavior is repeatedly returning to the ordinary checking loop after closure.
Do not hold the lifecycle guard while waiting for those handlers to finish.

**8. Deadlines, clocks, and missing notifications**

Keep the current five-second maximum poll duration. Use monotonic time for the
request's elapsed-time budget. Use the existing accepted-time policy for offer
validity; these clocks answer different questions.

Let the existing offer validator expose the timing information it already reads
so the handler can estimate its next necessary expiry check. Convert the remaining
offer lifetime to a monotonic wakeup delay using the observation made during that
validation. This is only a wakeup hint. Revalidate using accepted time after
waking, before delivery, and before recording a timeout response.

Preserve the current strict expiry comparison (`expires_at < accepted_time`) and
timestamp precision. Avoid a zero-timeout busy loop at exact equality: schedule
the next representable expiry check, capped by the request deadline. Test this
boundary with the actual timestamp representation.

Wall-clock movement can make an expiry hint inaccurate. Existing accepted-time
checks remain authoritative, and detected unhealthy time wakes waiting handlers.
The unchanged request deadline remains a fallback. This change promises current
validation at delivery, not a new hard bound on detecting every external clock
adjustment. Do not add a per-agent 50 ms clock monitor or broadcast every ordinary
clock observation; either would recreate the idle load.

If a producer commits but does not notify, the deadline's final check discovers
the assignment or preserves it for the next valid poll. After a coordinator
restart, the waiter collection starts empty and the existing session reconciliation
and durable poll recovery determine what can be replayed or delivered. No durable
notification cursor, migration, or event-replay log is required.

Distinguish a lost internal notification from a lost HTTP response:

| Failure point | Recovery behavior |
| --- | --- |
| Assignment A commits, but its internal notification is missed | A remains durable; a deadline check or a later valid request discovers it. |
| Assignment A and its poll receipt commit, but the HTTP response is lost | The agent retries the exact existing poll identity; the recorded response refers to A again. |
| The coordinator restarts during either case | Existing poll/session reconciliation determines replay or delivery; the temporary notification collection can start empty. |

Neither recovery path creates a new assignment just because the agent did not
observe the original response. Existing grant and launch checks still govern
physical execution. The guarantee concerns one logical operation with safe
replay, rather than exactly one transmission over the network.

Do not use this change to alter the accepted-time helper's persistence policy.
Record actual SQL and transaction changes in validation, including any deliberate
boundary adjustment needed to make delivery and invalidation ordering correct.

**9. Implementation sequence**

Deliver this as one coherent product change, with the following internal work
steps. There is no need for a separate PR containing an unused notification
framework or an inter-step documentation-only PR.

1. **Confirm the baseline and capture an idle trace.** Reuse synthetic session and
   loopback TLS fixtures. Record poll-loop database connections, SELECTs, write
   statements, transaction starts/commits, and elapsed handler time. Separate the
   waiting path from scheduler reconciliation and agent resource maintenance.
2. **Add the private waiter lifetime and change counter.** Cover attach/detach,
   same-session retry ownership, missed-wakeup ordering, targeted notification,
   closure, and cleanup. Keep counters in memory.
3. **Integrate the poll and publishers together.** Replace the inner loop, wire
   the assignment and invalidation owners above, preserve deadline and exception
   semantics, and make the short delivery/invalidation ordering explicit.
4. **Qualify recovery and compatibility.** Exercise direct and TLS adapters,
   retained polls, response loss, coordinator/agent restart, policy changes,
   and bounded shutdown. Check the existing worker-start evidence.
5. **Compare overhead and update documentation.** Explain the two layers of
   polling, unchanged timeout settings, fallback behavior, and measured limits.
   Submit the code, tests, and behavior documentation together.

This is a moderate concurrency refactor. Most work is in the poll owner,
notification sites, and race/recovery tests. It is smaller than replacing the
transport because agents, payloads, durable schemas, and assignment identities
remain compatible. Elapsed effort should be estimated after the publisher and
shutdown audit, rather than inferred from the size of the condition-variable
helper.

**10. Validation and acceptance**

Use supported producers and deterministic synchronization. Arrange race ordering
with `Event`/barrier fixtures or a narrow monkeypatch around an existing boundary.
Use test timeouts to prevent hangs; avoid hoping a short sleep happens to hit the
race. Do not expose new production test-control endpoints.

For the missed-wakeup case, pause the real handler immediately after its empty
database check and before its wait. Commit an assignment through the normal
publisher while the handler is paused, then release it. Assert that this same
pending request returns the assignment before its fallback deadline, and that
the existing assignment/claim identity remains unchanged. This tests the race
directly rather than merely testing that the condition variable can wake.

| Scenario | Material assertion |
| --- | --- |
| Assignment exists before subscription | First state check returns the existing assignment. |
| Commit occurs between empty check and wait | The same pending request notices it without waiting for the deadline. |
| Commit occurs while sleeping | The correct session wakes and receives its assignment; unrelated agents do not recheck. |
| Duplicate or irrelevant notification | No new assignment/claim/launch; the same deadline remains in force. |
| Publisher transaction rolls back | No assignment becomes deliverable; a wake, if injected, grants nothing. |
| Commit succeeds but notification is suppressed | Deadline/reconnect discovers the durable assignment; no extra reservation. |
| Policy revocation/drain/replacement wins the guarded race | Existing rejection/fence behavior; no stale delivery or new launch. |
| Delivery wins before invalidation | Exact receipt remains replayable; later control follows its existing lifecycle. |
| Offer expires during the wait | Existing expiry behavior at the appropriate deadline; exact equality does not spin. |
| Accepted-time regression/jump is detected | Existing degraded-time behavior; no new admission based on the wakeup hint. |
| Assignment response is lost | Exact poll replay returns the same assignment; existing launch-count assertions remain one. |
| Coordinator restarts after targeting but before notifying | Retained delivery/session reconciliation preserves the same assignment and issuer evidence. |
| Agent restarts with a fenced poll in the same coordinator epoch | Baseline recovery still advances safely; no permanently pending local poll. |
| Shutdown during an empty wait or delivery race | New subscriptions are rejected; awakened handlers explicitly exit without repeated checks after closure and settle under the existing owner before root ownership is released; retained jobs/claims remain intact. |
| Retry handler exits while original handler waits | Subscription cleanup does not discard the original handler's notification object. |

Start from these existing test owners and their fixtures:

- [`test_agent_sessions.py`](../../tests/unit/loom/queue/test_agent_sessions.py):
  poll sequencing/replay/current-policy checks, stale/gap rejection, offer expiry,
  principal isolation, replacement, and retirement. Add the waiting races here or
  a focused adjacent file if fixture reuse remains simple.
- [`test_remote_stage_execution.py`](../../tests/unit/loom/queue/test_remote_stage_execution.py):
  targeted assignment and execution boundaries; preserve assignment identity.
- [`test_local_daemon.py`](../../tests/unit/loom/queue/test_local_daemon.py):
  accepted-time health/recovery, controls, scheduling reload, and shutdown.
- [`test_agent_session_transport.py`](../../tests/integration/queue/test_agent_session_transport.py):
  real loopback mTLS, current credentials, retained work, lost replies, and one
  supervised execution across restart.
- [`test_agent_service_lifecycle.py`](../../tests/integration/queue/test_agent_service_lifecycle.py):
  foreground stop, pending-poll recovery, and
  `test_agent_restart_recovers_fenced_poll_without_coordinator_restart`.

Run focused selections first using the repository's
[targeted validation command](../../tests/README.md#targeted-validation):

```sh
uv run --python 3.12 --isolated --locked --group dev pytest \
  tests/unit/loom/queue/test_agent_sessions.py \
  tests/unit/loom/queue/test_remote_stage_execution.py \
  tests/unit/loom/queue/test_local_daemon.py

uv run --python 3.12 --isolated --locked --group dev pytest \
  tests/integration/queue/test_agent_session_transport.py \
  tests/integration/queue/test_agent_service_lifecycle.py
```

Inspect fixture requirements and skips before interpreting results. Add the
existing configuration-extra environment only for any changed configuration
consumer; this proposal introduces no configuration fields. Extend to authority
contracts and local production integration if changes reach scheduling/grants or
shared daemon lifecycle beyond waiting. Use `make validate-pr` if the final impact
cannot be bounded by the selected suites or an applicable workflow requires it;
do not automatically repeat its included checks or run all physical GPU/container/
Slurm acceptance for a waiting-only change.

The performance check must establish behavior, not a fragile machine-speed quota:

- During an empty wait with no event or nearer deadline, there are no repeated
  poll-owner database checks at the old 50 ms interval.
- Doubling an idle request's duration does not double its waiting-path SQL count;
  request-entry and deadline work remain bounded.
- A session-specific assignment wakes that session, rather than causing all idle
  agents to query SQLite.
- Record before/after SQL operations and transaction counts. Report coordinator
  CPU, lock-wait time, and delivery latency as observations on the named machine,
  with fleet size and scheduler activity stated. A reduction in SQL operations is
  not by itself a measured reduction in physical disk writes.

The current request-entry and completion writes are expected to remain. Total
coordinator activity will also include its unchanged scheduler loop. No numerical
speedup or maximum supported fleet size is claimed by this plan.

**11. Replacement, rollback, and completion**

Upgrade the coordinator through its supported service lifecycle after validation.
Existing compatible agents continue sending the same work requests; no agent-first
deployment, new capability negotiation, database migration, or root deletion is
needed for the waiting change. Preserve current journals and reconnect receipts.
Mixed-version compatibility means versions already compatible with the chosen
Loom baseline, not arbitrary historical agent versions.

Rollback restores the old waiting implementation against the same records, within
the existing supported version/schema range. Close active handlers and retain
their durable state through normal shutdown. A build rollback must not delete
pending polls, assignments, or agent journals to force a clean start.

After the Loom change is published and qualified, downstream rphys may update its
pin through its normal dependency validation. That adoption is separate from
authoring this plan and from the coordinator's notification implementation.

The feature is complete when all listed behavioral and recovery obligations pass,
the idle trace demonstrates removal of periodic waiting-path checks, the affected
documentation matches the implementation, and the review can account for every
supported invalidation producer. Future streaming, longer waits, a fully
event-driven scheduler, and accepted-time persistence changes remain separate
decisions with their own measured need.


**Implementation evidence (2026-09-22)**

The implementation starts from `307680bb6a3d60cb2ab316d307c3f0b0fc8cc96b`.
Relative to the source evidence baseline above, this adds only the published
planning documentation; no intervening runtime change required a design update.

The daemon owns private [`_PollWaiters`](../../src/loom/queue/_agent_poll_waiters.py)
and creates a fresh collection on start. `AgentSessionService.wait_for_work`
subscribes before registration, then uses `_begin_work_poll`, `_check_work_poll`,
and `_finish_work_poll` under short cycle-lock sections. The check reads current
policy/session/offer state and reuses `_take_targeted_delivery` for its existing
atomic delivery/receipt commit. The timeout path makes the final delivery check
under the same guard as its wait receipt. `stop()` closes subscriptions under
that guard, drains them outside it, and only then releases owner locks. The HTTP
server already stops accepting requests before daemon teardown; its daemon
handler threads are covered by the poll subscription drain. No transport or
schema change was needed. The initial delivery check now also runs inside the
exact-identity exception cleanup, so a service exception there immediately
fences its poll instead of leaving it active until restart. The integration
assertion records this earlier fence while preserving lost-response recovery
and the one-assignment/one-launch assertions.

Publisher audit:

| Supported mutation | Implemented notification or reason none is needed |
| --- | --- |
| `_target_remote_delivery`, including exact target replay | Notify that session after commit; direct and scheduler callers use the cycle guard. |
| `_control_agent` drain/reload | Notify that session after the withdrawal/fence commit. |
| `acknowledge_control` applied revision | Notify that session after commit. |
| `replace_agent_session` | Notify the old session after the replacement commit. |
| `retire_clean` | Notify immediately after the first withdrawal commit, even if the later empty-reference proof fails. |
| `service_lifetime` authorizes retirement | Notify after committed withdrawal. |
| `decline_assignment` and `release_assignment` | Notify after their committed availability revision and offer withdrawal. These additional existing producers were identified during implementation. |
| Protected policy replacement and scheduling reload | Notify all subscribed sessions after installing policy under the cycle guard. |
| Accepted-time degradation | Notify after the degradation commit; ordinary high-water updates remain silent. |
| Operator time recovery | Notify after the epoch replacement and offer withdrawal commit, under the cycle guard. |
| Registration / startup poll fencing | No previous live handler exists for that new session/process lifetime. |
| Session reconciliation | Policy installation or epoch restart already supplies the relevant invalidation boundary; reconciliation does not withdraw an offer. |
| Offer publication | Existing active-poll rejection prevents concurrent publication. |
| Offer renewal | Extends the same offer; the previous expiry hint may cause one early check but cannot delay expiry detection. |
| Poll completion, exact exception fencing, final retirement | Completion belongs to that handler; retirement's earlier withdrawal already notifies. |

The private signal never holds the cycle lock or accesses SQLite. Subscriber
reference counts keep a rejected concurrent retry from removing the original
handler's signal. Only live subscriptions occupy the collection. No durable
counter, new configuration, dependency, assignment identity, or agent journal
field was introduced.

Measured on `sleipnir`, Python 3.12, one synthetic agent, coordinator-only roots
on NAS, with the scheduler parked to isolate waiting work. Each row is one direct
poll, including registration/completion. SQL tracing covers statements within
the yielded coordinator connections; root-opening identity validation is outside
that callback. INSERT counts include uncommitted accepted-time high-water writes.
Connection close rolls those validation transactions back; SQL count is not a
physical disk-write measurement.

| Idle request | Connections / BEGIN | SELECT | INSERT / UPDATE | COMMIT | Process CPU | Elapsed |
| --- | --- | --- | --- | --- | --- | --- |
| Before, 1 s | 25 / 25 | 64 | 14 / 1 | 14 | 86.9 ms | 1.116 s |
| Before, 2 s | 45 / 45 | 114 | 23 / 2 | 24 | 195.9 ms | 2.102 s |
| After, 1 s | 6 / 6 | 18 | 5 / 1 | 4 | 23.5 ms | 1.104 s |
| After, 2 s | 6 / 6 | 18 | 4 / 2 | 4 | 15.2 ms | 2.087 s |

A separate direct delivery observation with one waiting agent and the scheduler
parked measured 142.9 ms from entering target publication to receiving the reply,
including input retention and database work; 102.1 ms elapsed after target
publication returned. Process CPU was 32.4 ms. Four measured cycle-lock
acquisitions waited 0.0012–0.0037 ms each. These are uncontended observations on
a shared host while other validation ran, not fleet latency bounds or throughput guarantees. Real scheduler,
TLS, execution, and restart behavior are qualified by the integration suites.

[`test_agent_waiting.py`](../../tests/unit/loom/queue/test_agent_waiting.py) adds
barrier-driven commit-before-wait, sleeping delivery, exact replay, lost signal,
target replay, rollback, invalidation ordering, rejected retry, expiry equality,
shutdown/drain, restart/issuer retention, and unrelated-session coverage. It also
asserts that doubling an idle wait does not increase waiting SQL and that repeated
notifications do not extend the deadline. Existing execution integration tests
retain the single-launch and same-epoch fenced-poll recovery obligations.

Validation covers the three unit suites and two integration suites named above,
plus the new waiting suite, local daemon production, service lifetime, and the
local daemon authority contract because the cycle guard and stop lifetime are
shared owners. Ruff, targeted Pyright, local documentation links/snippets, and
diff checks cover the changed surface. No configuration fields changed, so no
configuration-extra lane is selected. Physical GPU/container/Slurm fleet
qualification is outside this waiting change. Test temporary roots use a short
`TMPDIR` because supervisor Unix socket paths derived from a long NAS temporary
path exceed the platform socket-address limit.

Local unit validation passed all 176 selected cases, including 26 waiting cases;
a subsequent strengthening of the invalidation wake test passed all six affected
cases. Ruff and targeted Pyright passed; all 14 local plan links, six illustrative
Python snippets, and whitespace checks passed. All 203 selected integration and
contract cases passed with no skips: 107 before the earlier-fence assertion was
updated, then the corrected case and the remaining 95 cases. The first failed
assertion expected an active poll after a handled initial-check exception; the
accepted design puts that check inside exact fence cleanup. Its replacement
asserts the immediate fence and retains the original restart/single-launch checks.
The implementation PR records the exact selectors and reviewed revision.
