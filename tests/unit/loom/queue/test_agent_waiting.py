"""Real poll/publisher interleavings without scheduler or sleep-based races."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event, get_ident

import pytest

from loom.queue import LocalDaemon, LocalDaemonPrincipal, LocalDaemonRole
from loom.queue._agent_poll_waiters import _PollSignal, _PollWaiters
from loom.queue.agent_sessions import (
    AgentControl,
    AgentControlKind,
    AgentPolicyConfig,
    AgentSessionService,
    SessionReplacementRequest,
    AgentRegistration,
    _target_remote_delivery,
    REMOTE_EXECUTION_CAPABILITY,
    REGULAR_FILE_RELAY_CAPABILITY,
)
from loom.queue.errors import QueueConflictError, QueueServiceError
from tests.unit.loom.queue.test_agent_sessions import (
    _config,
    _policy,
    _offer,
    _view,
    _proof,
    _TEST_RETIREMENT_VERIFIER,
)
from tests.unit.loom.queue.test_remote_stage_execution import _profile, _request


@pytest.fixture
def waiting_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Reconciliation has its own periodic SQL; isolate the pending-poll owner.
    monkeypatch.setattr(LocalDaemon, "_serve", lambda self: self._stop.wait())
    capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
    )
    policy = _policy()
    policy = replace(
        policy, agents=(replace(policy.agents[0], capabilities=capabilities),)
    )
    config = replace(
        _config(tmp_path, policy),
        agent_root=None,
        resident_worker_launch_profile=None,
        cpu_capacity=0,
        memory_capacity_bytes=0,
        agent_resource_providers=(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        view = _view(daemon)
        handshake = view.handshake()
        session = view.register(
            AgentRegistration(
                "register",
                str(handshake["coordinator_id"]),
                str(handshake["coordinator_epoch"]),
                "agent-root-a",
                "config-1",
                "inventory-1",
                "availability-1",
                ("default",),
                capabilities,
                retirement_verifier=_TEST_RETIREMENT_VERIFIER,
            )
        )
        profile = _profile(tmp_path)
        view.publish_offer(
            replace(
                _offer(session.session_id, session.coordinator_epoch),
                resident_profiles=(profile.descriptor,),
            ),
            idempotency_key="offer",
        )
        request = _request(profile)
        source = tmp_path / "input.data"
        source.write_bytes(b"input")

        def target():
            _target_remote_delivery(
                daemon,
                session_id=session.session_id,
                availability_revision=session.availability_revision,
                request=request,
                run_uri="file:///waiting-run",
                input_paths={"input-1": source},
            )

        def poll(timeout=5000, sequence=1):
            return view.wait_for_work(
                session.session_id,
                session.availability_revision,
                sequence=sequence,
                wait_timeout_ms=timeout,
            )

        yield daemon, session, request, target, poll
    finally:
        daemon.stop()


def _pause_before_wait(monkeypatch):
    ready, proceed = Event(), Event()
    original = _PollSignal.wait_for_change

    def paused(self, observed, timeout):
        ready.set()
        assert proceed.wait(3), "test did not release pending handler"
        original(self, observed, timeout)

    monkeypatch.setattr(_PollSignal, "wait_for_change", paused)
    return ready, proceed


def _observe_sleep(monkeypatch):
    asleep = Event()
    original = _PollSignal.wait_for_change

    def observed(self, generation, timeout):
        wait = self._condition.wait

        def marked(timeout=None):
            # Condition's lock is held here. A producer can acquire it only
            # after wait releases it, so notification occurs while sleeping.
            asleep.set()
            return wait(timeout)

        with monkeypatch.context() as patch:
            patch.setattr(self._condition, "wait", marked)
            original(self, generation, timeout)

    monkeypatch.setattr(_PollSignal, "wait_for_change", observed)
    return asleep


def test_assignment_before_subscription_and_exact_reply_replay(waiting_owner):
    daemon, session, request, target, poll = waiting_owner
    target()
    first = poll()
    assert first["request"]["assignment_id"] == request.assignment_id
    assert poll() == first
    with daemon._connection() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM remote_assignments").fetchone()[0] == 1
        )
        assert tuple(
            conn.execute("SELECT state, poll_sequence FROM agent_deliveries").fetchone()
        ) == ("DELIVERED", 1)
    assert daemon._poll_waiters._subscribers == {}


@pytest.mark.parametrize("sleeping", [False, True])
def test_target_commit_wakes_same_pending_poll_without_deadline(
    waiting_owner,
    monkeypatch,
    sleeping,
):
    daemon, session, request, target, poll = waiting_owner
    if sleeping:
        ready = _observe_sleep(monkeypatch)
        proceed = None
    else:
        ready, proceed = _pause_before_wait(monkeypatch)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(poll)
        assert ready.wait(2)
        try:
            target()
        finally:
            if proceed is not None:
                proceed.set()
        result = pending.result(timeout=2)
    assert result["request"]["assignment_id"] == request.assignment_id
    assert result["request"]["claim_id"] == request.claim_id
    assert poll() == result


def test_rejected_retry_preserves_original_subscription(waiting_owner, monkeypatch):
    daemon, session, request, target, poll = waiting_owner
    ready = _observe_sleep(monkeypatch)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(poll)
        assert ready.wait(2)
        with pytest.raises(QueueConflictError, match="already active"):
            poll()
        assert daemon._poll_waiters._subscribers[session.session_id][1] == 1
        target()
        assert (
            pending.result(timeout=2)["request"]["assignment_id"]
            == request.assignment_id
        )
    assert daemon._poll_waiters._subscribers == {}


def test_suppressed_notification_is_recovered_at_final_check(
    waiting_owner, monkeypatch
):
    daemon, session, request, target, poll = waiting_owner
    ready, proceed = _pause_before_wait(monkeypatch)
    monkeypatch.setattr(daemon._poll_waiters, "notify", lambda session_id: None)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(poll, 250)
        assert ready.wait(2)
        try:
            target()
        finally:
            proceed.set()
        assert (
            pending.result(timeout=2)["request"]["assignment_id"]
            == request.assignment_id
        )


def test_target_replay_notifies_a_waiter_after_a_missed_signal(
    waiting_owner, monkeypatch
):
    daemon, session, request, target, poll = waiting_owner
    ready = _observe_sleep(monkeypatch)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(poll)
        assert ready.wait(2)
        with monkeypatch.context() as patch:
            patch.setattr(daemon._poll_waiters, "notify", lambda session_id: None)
            target()
        target()
        assert (
            pending.result(timeout=2)["request"]["assignment_id"]
            == request.assignment_id
        )


@pytest.mark.parametrize(
    "change", ["policy", "drain", "replace", "retire", "clock_regression", "clock_jump"]
)
def test_invalidation_wins_before_delivery(waiting_owner, monkeypatch, change):
    daemon, session, request, target, poll = waiting_owner
    ready, proceed = _pause_before_wait(monkeypatch)
    operator = daemon.operator_view(
        LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
    )
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(poll)
        assert ready.wait(2)
        try:
            if change in {"policy", "drain"}:
                # Only the invalidator may wake this handler: keep an already
                # durable assignment from masking a missing invalidation signal.
                with monkeypatch.context() as patch:
                    patch.setattr(daemon._poll_waiters, "notify", lambda _: None)
                    target()
            if change == "policy":
                daemon.replace_agent_policy(AgentPolicyConfig(revision="revoked"))
            elif change == "drain":
                operator.control_agent(
                    AgentControl(
                        "drain",
                        AgentControlKind.DRAIN,
                        session.agent_id,
                        session.session_id,
                        session.config_revision,
                        "default",
                        False,
                        "waiting test",
                    )
                )
            elif change == "retire":
                _view(daemon).retire_clean(_proof(session), idempotency_key="retire")
            elif change == "replace":
                # A lost agent with an expired offer can be replaced.
                from datetime import timedelta
                from loom.timestamps import parse_timestamp, utc_timestamp

                with daemon._connection() as conn:
                    expires = str(
                        conn.execute(
                            "SELECT expires_at FROM agent_offers WHERE current = 1"
                        ).fetchone()[0]
                    )
                stamp = utc_timestamp(parse_timestamp(expires) + timedelta(seconds=1))
                monkeypatch.setattr(daemon, "_clock", lambda: stamp)
                operator.replace_agent_session(
                    SessionReplacementRequest("replace", session.agent_id, "lost agent")
                )
            else:
                stamp = (
                    "2020-01-01T00:00:00Z"
                    if change == "clock_regression"
                    else "2099-01-01T00:00:00Z"
                )
                monkeypatch.setattr(daemon, "_clock", lambda: stamp)
                with daemon._connection() as conn, pytest.raises(QueueServiceError):
                    daemon._accepted_time(conn)
        finally:
            proceed.set()
        with pytest.raises((QueueConflictError, QueueServiceError)):
            pending.result(timeout=2)
    with daemon._connection() as conn:
        assert conn.execute("SELECT active FROM agent_poll_state").fetchone()[0] == 0
        deliveries = conn.execute("SELECT state FROM agent_deliveries").fetchall()
        assert [row[0] for row in deliveries] == (
            ["TARGETED"] if change in {"policy", "drain"} else []
        )


def test_delivery_receipt_survives_later_drain(waiting_owner):
    daemon, session, request, target, poll = waiting_owner
    target()
    result = poll()
    daemon.operator_view(
        LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
    ).control_agent(
        AgentControl(
            "drain",
            AgentControlKind.DRAIN,
            session.agent_id,
            session.session_id,
            session.config_revision,
            "default",
            False,
            "waiting test",
        )
    )
    assert poll() == result


def test_shutdown_waits_for_exact_fence_before_releasing_root(
    waiting_owner, monkeypatch
):
    daemon, session, request, target, poll = waiting_owner
    ready, proceed = _pause_before_wait(monkeypatch)
    closed = Event()
    close = daemon._poll_waiters.close

    def observed_close():
        close()
        closed.set()

    monkeypatch.setattr(daemon._poll_waiters, "close", observed_close)
    checks = []
    check = AgentSessionService._check_work_poll

    def counted(self, **kwargs):
        checks.append(1)
        return check(self, **kwargs)

    monkeypatch.setattr(AgentSessionService, "_check_work_poll", counted)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(poll)
        assert ready.wait(2)
        stopping = workers.submit(daemon.stop)
        assert closed.wait(2)
        try:
            assert daemon._coordinator_lock is not None
            assert not stopping.done()
            with pytest.raises(QueueServiceError, match="stopping"):
                poll(sequence=2)
        finally:
            proceed.set()
        with pytest.raises(QueueServiceError, match="stopping"):
            pending.result(timeout=2)
        stopping.result(timeout=2)
    assert checks == [1]
    assert daemon._coordinator_lock is None
    with daemon._connection() as conn:
        assert conn.execute("SELECT active FROM agent_poll_state").fetchone()[0] == 0
    old_waiters = daemon._poll_waiters
    daemon.start()
    assert daemon._poll_waiters is not old_waiters
    assert not daemon._poll_waiters._closed


def test_idle_sql_is_bounded_independently_of_wait_duration(waiting_owner, monkeypatch):
    daemon, session, request, target, poll = waiting_owner
    original = daemon._connection
    counts = Counter()
    owner = get_ident()

    @contextmanager
    def traced():
        with original() as conn:
            if get_ident() == owner:
                counts["connections"] += 1
                conn.set_trace_callback(
                    lambda sql: counts.update([sql.split()[0].upper()])
                )
            yield conn

    monkeypatch.setattr(daemon, "_connection", traced)
    observed = []
    for sequence, duration in enumerate((150, 300), 1):
        counts.clear()
        assert poll(duration, sequence)["result"] == "wait"
        observed.append(counts.copy())
    # Registration INSERT versus UPDATE differs; waiting work stays fixed.
    for key in ("connections", "SELECT", "BEGIN", "COMMIT", "ROLLBACK"):
        assert observed[0][key] == observed[1][key]
    assert observed[0]["connections"] <= 6


def test_notifications_do_not_extend_deadline_or_grant_work(waiting_owner, monkeypatch):
    daemon, session, request, target, poll = waiting_owner
    waits = []
    original = _PollSignal.wait_for_change

    def noisy(self, observed, timeout):
        waits.append(timeout)
        if len(waits) <= 3:
            self.notify()
        original(self, observed, timeout)

    monkeypatch.setattr(_PollSignal, "wait_for_change", noisy)
    assert poll(150)["result"] == "wait"
    assert len(waits) == 4
    assert waits == sorted(waits, reverse=True)
    with daemon._connection() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM remote_assignments").fetchone()[0] == 0
        )


def test_waiter_registry_targets_and_cleans_subscriber_lifetimes():
    waiters = _PollWaiters()
    with waiters.subscribe("one") as one, waiters.subscribe("two") as two:
        before = two.snapshot()
        with waiters.subscribe("one") as retry:
            assert retry is one
        waiters.notify("one")
        assert one.snapshot() == 1
        assert two.snapshot() == before
        waiters.close()
        with pytest.raises(QueueServiceError, match="stopping"):
            with waiters.subscribe("new"):
                pytest.fail("closed owner admitted a new waiter")
    waiters.drain()
    assert waiters._subscribers == {}


@pytest.mark.parametrize("fractional", [False, True])
def test_offer_equality_waits_for_next_timestamp_then_expires(
    waiting_owner, monkeypatch, fractional
):
    from datetime import timedelta
    from loom.timestamps import parse_timestamp, utc_timestamp

    daemon, session, request, target, poll = waiting_owner
    with daemon._connection() as conn:
        expires = str(
            conn.execute(
                "SELECT expires_at FROM agent_offers WHERE current = 1"
            ).fetchone()[0]
        )
    now = [expires]
    monkeypatch.setattr(daemon, "_clock", lambda: now[0])
    if fractional:
        from loom.queue.agent_sessions import AgentOfferRenewal

        now[0] = utc_timestamp(
            parse_timestamp(expires) + timedelta(microseconds=123456),
            timespec="microseconds",
        )
        with daemon._connection() as conn:
            offer_id = str(
                conn.execute(
                    "SELECT offer_id FROM agent_offers WHERE current = 1"
                ).fetchone()[0]
            )
        renewed = _view(daemon).renew_offer(
            AgentOfferRenewal(
                session.session_id, offer_id, session.availability_revision, 1
            )
        )
        expires = now[0] = str(renewed["expires_at"])
    delays = []

    def expire(self, observed, timeout):
        delays.append(timeout)
        now[0] = utc_timestamp(parse_timestamp(expires) + timedelta(seconds=1))

    monkeypatch.setattr(_PollSignal, "wait_for_change", expire)
    with pytest.raises(QueueConflictError, match="current offer"):
        poll()
    assert delays == [0.000001 if fractional else 1.0]


def test_rolled_back_target_never_notifies_or_delivers(waiting_owner, monkeypatch):
    import sqlite3

    daemon, session, request, target, poll = waiting_owner
    ready, proceed = _pause_before_wait(monkeypatch)
    original = daemon._connection
    notifications = []

    @contextmanager
    def denied():
        with original() as conn:
            conn.set_authorizer(
                lambda action, table, *args: (
                    sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_INSERT and table == "agent_deliveries"
                    else sqlite3.SQLITE_OK
                )
            )
            yield conn

    with ThreadPoolExecutor() as workers:
        pending = workers.submit(poll, 150)
        assert ready.wait(2)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(daemon, "_connection", denied)
                patch.setattr(daemon._poll_waiters, "notify", notifications.append)
                with pytest.raises(sqlite3.DatabaseError, match="authorized"):
                    target()
            assert not notifications
            daemon._poll_waiters.notify(session.session_id)
        finally:
            proceed.set()
        assert pending.result(timeout=2)["result"] == "wait"
    with daemon._connection() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM remote_assignments").fetchone()[0] == 0
        )


def test_restart_retains_target_and_original_issuer_after_lost_notification(
    waiting_owner, monkeypatch
):
    daemon, session, request, target, poll = waiting_owner
    ready = _observe_sleep(monkeypatch)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(poll)
        assert ready.wait(2)
        with monkeypatch.context() as patch:
            patch.setattr(daemon._poll_waiters, "notify", lambda session_id: None)
            target()
        daemon.stop()
        with pytest.raises(QueueServiceError, match="stopping"):
            pending.result(timeout=2)
    daemon.start()
    view = _view(daemon)
    resumed = view.reconcile(session, daemon._epoch, idempotency_key="restart")
    view.publish_offer(
        replace(
            _offer(resumed.session_id, resumed.coordinator_epoch),
            resident_profiles=(request.profile,),
        ),
        idempotency_key="restart-offer",
    )
    reply = poll(sequence=2)
    assert reply["request"]["assignment_id"] == request.assignment_id
    assert reply["request"]["claim_id"] == request.claim_id
    assert (
        reply["coordinator_epoch"]
        == resumed.coordinator_epoch
        != session.coordinator_epoch
    )
    with daemon._connection() as conn:
        assert (
            conn.execute("SELECT issuer_epoch FROM remote_assignments").fetchone()[0]
            == session.coordinator_epoch
        )


def test_targeted_wake_leaves_other_real_poll_asleep(waiting_owner, monkeypatch):
    daemon, session, request, target, poll = waiting_owner
    from loom.queue.agent_sessions import AgentPrincipalPolicy

    policy = daemon._agent_policy
    assert policy is not None
    daemon.replace_agent_policy(
        replace(
            policy,
            agents=(
                *policy.agents,
                AgentPrincipalPolicy(
                    "agent-b",
                    "principal-b",
                    "agent-b",
                    ("default",),
                    ("python",),
                ),
            ),
        )
    )
    view_b = daemon.agent_view(
        LocalDaemonPrincipal("principal-b", LocalDaemonRole.AGENT, "agent-b")
    )
    other = view_b.register(
        AgentRegistration(
            "register-b",
            session.coordinator_id,
            session.coordinator_epoch,
            "root-b",
            "config-1",
            "inventory-1",
            "availability-1",
            ("default",),
            ("python",),
            retirement_verifier=_TEST_RETIREMENT_VERIFIER,
        )
    )
    view_b.publish_offer(
        _offer(other.session_id, other.coordinator_epoch), idempotency_key="offer-b"
    )
    checks = Counter()
    check = AgentSessionService._check_work_poll
    both_ready = Event()
    count_waiting = set()
    wait = _PollSignal.wait_for_change

    def counted(self, **kwargs):
        checks[kwargs["session_id"]] += 1
        return check(self, **kwargs)

    def entered(self, generation, timeout):
        # Both conditions enter their real wait before assertions below.
        original = self._condition.wait

        def marked(timeout=None):
            count_waiting.add(self)
            if len(count_waiting) == 2:
                both_ready.set()
            return original(timeout)

        with monkeypatch.context() as patch:
            patch.setattr(self._condition, "wait", marked)
            wait(self, generation, timeout)

    monkeypatch.setattr(AgentSessionService, "_check_work_poll", counted)
    monkeypatch.setattr(_PollSignal, "wait_for_change", entered)
    with ThreadPoolExecutor() as workers:
        one = workers.submit(poll)
        two = workers.submit(
            view_b.wait_for_work,
            other.session_id,
            other.availability_revision,
            sequence=1,
            wait_timeout_ms=5000,
        )
        try:
            assert both_ready.wait(2)
            target()
            assert (
                one.result(timeout=2)["request"]["assignment_id"]
                == request.assignment_id
            )
            assert checks[other.session_id] == 1
            assert not two.done()
        finally:
            daemon.stop()
        with pytest.raises(QueueServiceError, match="stopping"):
            two.result(timeout=2)


def test_retirement_notifies_at_withdrawal_even_if_later_proof_fails(
    waiting_owner, monkeypatch
):
    daemon, session, request, target, poll = waiting_owner
    with daemon._connection() as conn:
        conn.execute(
            "INSERT INTO agent_coordinator_references(session_id, reference_kind, reference_id, resolved) VALUES (?, 'outbox', 'retained-event', 0)",
            (session.session_id,),
        )
        conn.commit()
    ready = _observe_sleep(monkeypatch)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(poll)
        assert ready.wait(2)
        with pytest.raises(QueueConflictError, match="unresolved"):
            _view(daemon).retire_clean(_proof(session), idempotency_key="retire")
        with pytest.raises(QueueConflictError, match="fenced"):
            pending.result(timeout=2)
    with daemon._connection() as conn:
        assert (
            conn.execute("SELECT state FROM agent_sessions").fetchone()[0] == "RETIRING"
        )


def test_command_lifetime_withdrawal_wakes_poll(waiting_owner, monkeypatch):
    daemon, session, request, target, poll = waiting_owner
    ready = _observe_sleep(monkeypatch)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(poll)
        assert ready.wait(2)
        decision = _view(daemon).service_lifetime(
            session.session_id, session.coordinator_epoch, "generation", "observe"
        )
        assert decision["state"] == "authorized"
        with pytest.raises(QueueConflictError, match="fenced"):
            pending.result(timeout=2)


def test_committed_delivery_wins_before_shutdown(waiting_owner, monkeypatch):
    daemon, session, request, target, poll = waiting_owner
    committed, proceed = Event(), Event()
    take = AgentSessionService._take_targeted_delivery

    def paused(self, **kwargs):
        result = take(self, **kwargs)
        assert result is not None
        committed.set()
        assert proceed.wait(3)
        return result

    monkeypatch.setattr(AgentSessionService, "_take_targeted_delivery", paused)
    target()
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(poll)
        assert committed.wait(2)
        stopping = workers.submit(daemon.stop)
        try:
            assert daemon._coordinator_lock is not None
            assert not stopping.done()
        finally:
            proceed.set()
        assert (
            pending.result(timeout=2)["request"]["assignment_id"]
            == request.assignment_id
        )
        stopping.result(timeout=2)
    with daemon._connection() as conn:
        assert (
            conn.execute("SELECT result_json FROM agent_poll_state").fetchone()[0]
            is not None
        )
        assert (
            conn.execute("SELECT state FROM agent_deliveries").fetchone()[0]
            == "DELIVERED"
        )


def test_applied_control_revision_wakes_existing_poll(waiting_owner, monkeypatch):
    from loom.queue.agent_sessions import AgentControlEffect

    daemon, session, request, target, poll = waiting_owner
    ready = _observe_sleep(monkeypatch)
    view = _view(daemon)
    operator = daemon.operator_view(
        LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
    )
    control = AgentControl(
        "resume",
        AgentControlKind.RESUME,
        session.agent_id,
        session.session_id,
        session.config_revision,
        "default",
        False,
        "refresh availability",
    )
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(poll)
        assert ready.wait(2)
        operator.control_agent(control)
        assert view.next_control(session.session_id) == control
        view.acknowledge_control(
            session.session_id,
            AgentControlEffect(
                control.operation_id,
                "applied",
                session.config_revision,
                session.inventory_revision,
                "availability-resumed",
            ),
        )
        with pytest.raises(QueueConflictError, match="fenced"):
            pending.result(timeout=2)
