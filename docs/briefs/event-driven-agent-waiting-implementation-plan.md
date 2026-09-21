# Event-driven agent waiting: implementation plan

Implementation proposal approved for publication on 2026-09-22. Runtime
implementation has not started. This is an ordinary feature plan, not a numbered
roadmap stage.

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

An agent currently opens a work request with a maximum five-second wait. The
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

The real interval is `LocalDaemonConfig.poll_interval_seconds`; 0.05 seconds is
the default. Each iteration opens database connections, checks state, and uses
`BEGIN IMMEDIATE` for the delivery lookup even when no assignment exists. Offer
validation also executes the accepted-time metadata update. In the ordinary
inner-loop validation connection that update is not committed before close.

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

The handler's normal owner-state check handles closure after waking. The helper
does not invent a new wire response for shutdown. Python documents this
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
on stop; a later daemon start gets a fresh collection.

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
Several session operations already use this guard, but `wait_for_work` is not
decorated and `replace_agent_policy` currently assigns the policy directly.
Do not decorate the entire blocking poll. Audit the direct and HTTP callers and
ensure policy installation participates in the same ordering. Preserve the
existing lock order with scheduling reload and SQLite.

The cycle lock also protects broader reconciliation. Measure lock waiting in the
integration evidence; do not claim the request is a hard real-time deadline or
introduce a new global lock solely to optimize a hypothetical large fleet.

**7. Wake for invalidation as well as assignments**

The 50 ms loop currently discovers more than new work. Wire notifications at the
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

Shutdown must release waiters without holding the cycle lock while joining them.
Allow them to finish their existing receipt/fence cleanup while the root is still
owned. Coordinate server-stop and daemon-stop ordering at their current owners;
do not release the root and leave old handlers mutating it during a new start.

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
| Shutdown during an empty wait or delivery race | Handlers stop/settle under the existing owner before root ownership is released; retained jobs/claims remain intact. |
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
