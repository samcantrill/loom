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


@pytest.mark.parametrize("kind", ["work", "control"])
@pytest.mark.parametrize("boundary", ["before_read", "after_read"])
def test_stalled_session_allows_other_renewals_and_controls(
    waiting_owner, monkeypatch, kind, boundary
):
    from datetime import timedelta
    from loom.queue.agent_sessions import AgentOfferRenewal
    from loom.timestamps import parse_timestamp, utc_timestamp

    daemon, session, request, target, poll = waiting_owner
    policy = daemon._agent_policy
    peers = [
        replace(
            policy.agents[0],
            agent_id=f"agent-{name}",
            principal_id=f"principal-{name}",
            credential_id=f"agent-{name}",
        )
        for name in ("b", "c")
    ]
    daemon.replace_agent_policy(
        replace(
            policy,
            agents=(*policy.agents, *peers),
            principals=(
                replace(policy.principals[0], agent_ids=("agent-a", "agent-c")),
            ),
        )
    )
    registered = []
    for peer in peers:
        view = daemon.agent_view(
            LocalDaemonPrincipal(
                peer.principal_id, LocalDaemonRole.AGENT, peer.agent_id
            )
        )
        other = view.register(
            AgentRegistration(
                f"register-{peer.agent_id}",
                session.coordinator_id,
                session.coordinator_epoch,
                f"root-{peer.agent_id}",
                "config-1",
                "inventory-1",
                "availability-1",
                ("default",),
                peer.capabilities,
                retirement_verifier=_TEST_RETIREMENT_VERIFIER,
            )
        )
        offer = view.publish_offer(
            _offer(other.session_id, other.coordinator_epoch), idempotency_key="offer"
        )
        registered.append((view, other, offer))
    (view_b, b, offer_b), (view_c, c, _) = registered
    operator = daemon.operator_view(
        LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
    )

    def control(s):
        return AgentControl(
            f"drain-{s.agent_id}",
            AgentControlKind.DRAIN,
            s.agent_id,
            s.session_id,
            s.config_revision,
            "default",
            False,
            "inspection interleaving",
        )

    if kind == "control":
        operator.control_agent(control(session))
    elif boundary == "after_read":
        target()
    operator.control_agent(control(c))
    inspect = "_inspect_work_candidate" if kind == "work" else "_inspect_controls"
    original = getattr(AgentSessionService, inspect)
    paused, release = Event(), Event()

    def pause():
        paused.set()
        assert release.wait(5)

    def stalled(self, session_id, *args, **kwargs):
        if session_id == session.session_id and boundary == "before_read":
            pause()
        result = original(self, session_id, *args, **kwargs)
        if session_id == session.session_id and boundary == "after_read":
            assert result is not None
            pause()
        return result

    monkeypatch.setattr(AgentSessionService, inspect, stalled)
    with ThreadPoolExecutor() as pool:
        pending = (
            pool.submit(poll)
            if kind == "work"
            else pool.submit(
                _view(daemon).wait_for_controls,
                session.session_id,
                received_operation_ids=(),
                wait_timeout_ms=0,
            )
        )
        try:
            assert paused.wait(2)
            renewal = AgentOfferRenewal(
                b.session_id, offer_b["offer_id"], b.availability_revision, 1
            )
            assert (
                pool.submit(view_b.renew_offer, renewal).result(timeout=2)["state"]
                == "renewed"
            )
            reply = pool.submit(
                view_c.wait_for_controls,
                c.session_id,
                received_operation_ids=(),
                wait_timeout_ms=0,
            )
            assert reply.result(timeout=2)["control"] == control(c).value()
            if kind == "work" and boundary == "after_read":
                # The targeted delivery is live. A drain revokes this offer and fences the poll.
                operator.control_agent(control(session))
            else:
                with daemon._connection() as conn:
                    expiry = conn.execute(
                        "SELECT expires_at FROM agent_offers WHERE session_id=? AND current=1",
                        (session.session_id,),
                    ).fetchone()
                if expiry is not None:
                    now = utc_timestamp(
                        parse_timestamp(expiry[0]) + timedelta(seconds=1)
                    )
                    monkeypatch.setattr(daemon, "_clock", lambda: now)
                operator.replace_agent_session(
                    SessionReplacementRequest(
                        "replace-a", session.agent_id, "lost agent"
                    )
                )
        finally:
            release.set()
        with pytest.raises((QueueConflictError, QueueServiceError)):
            pending.result(timeout=2)
    with daemon._connection() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM agent_deliveries WHERE session_id=? AND state='DELIVERED'",
                (session.session_id,),
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("transaction", ["BEGIN IMMEDIATE", "BEGIN"])
def test_sqlite_busy_retries_release_the_state_guard(
    waiting_owner, monkeypatch, transaction
):
    from loom.queue import _coordinator_transactions

    daemon, session, _, _, poll = waiting_owner
    busy, retry = Event(), Event()

    def wait_to_retry(seconds):
        busy.set()
        assert retry.wait(3)

    monkeypatch.setattr(_coordinator_transactions, "sleep", wait_to_retry)
    with ThreadPoolExecutor() as pool, daemon._connection() as blocker:
        blocker.execute(transaction)
        # A read transaction in rollback-journal mode blocks COMMIT. An
        # immediate transaction blocks the polling writer at BEGIN instead.
        blocker.execute("SELECT * FROM agent_sessions").fetchall()
        pending = pool.submit(poll, 1)
        try:
            assert busy.wait(2)
            empty = pool.submit(
                _view(daemon).wait_for_controls,
                session.session_id,
                received_operation_ids=(),
                wait_timeout_ms=0,
            )
            assert empty.result(timeout=1) == {
                "control": None,
                "assignment_control": None,
            }
        finally:
            blocker.rollback()
            retry.set()
        assert pending.result(timeout=2)["result"] == "wait"


@pytest.mark.parametrize("blocker_transaction", ["BEGIN IMMEDIATE", "BEGIN"])
def test_registration_releases_state_guard_while_writer_is_busy(tmp_path, monkeypatch, blocker_transaction):
    from loom.queue import _coordinator_transactions
    from tests.unit.loom.queue.test_agent_sessions import _register

    monkeypatch.setattr(LocalDaemon, "_serve", lambda self: self._stop.wait())
    policy = _policy()
    first = policy.agents[0]
    second = replace(first, credential_id="agent-b", principal_id="principal-b", agent_id="agent-b")
    config = _config(tmp_path, replace(policy, agents=(first, second)))
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    waiting, retry = Event(), Event()

    def wait_to_retry(_seconds):
        waiting.set()
        assert retry.wait(5)

    try:
        current = _register(daemon)
        view = daemon.agent_view(LocalDaemonPrincipal("principal-b", LocalDaemonRole.AGENT, "agent-b"))
        request = AgentRegistration(
            "register-b", current.coordinator_id, current.coordinator_epoch, "root-b", "cfg",
            "inv", "avail", ("default",), ("python",), retirement_verifier=_TEST_RETIREMENT_VERIFIER,
        )
        monkeypatch.setattr(_coordinator_transactions, "sleep", wait_to_retry)
        with ThreadPoolExecutor() as workers, daemon._connection() as blocker:
            blocker.execute(blocker_transaction)
            blocker.execute("SELECT * FROM agent_sessions").fetchall()
            pending = workers.submit(view.register, request)
            try:
                assert waiting.wait(3)
                read = workers.submit(_view(daemon).wait_for_controls, current.session_id,
                                      received_operation_ids=(), wait_timeout_ms=0)
                assert read.result(2) == {"control": None, "assignment_control": None}
            finally:
                blocker.rollback()
                retry.set()
            assert pending.result(3) == view.register(request)
        with daemon._connection() as conn:
            assert conn.execute("SELECT count(*) FROM agent_sessions WHERE agent_id='agent-b'").fetchone()[0] == 1
            assert conn.execute(
                "SELECT count(*) FROM agent_receipts WHERE principal_id='principal-b' AND operation='register'"
            ).fetchone()[0] == 1
    finally:
        retry.set()
        daemon.stop()


@pytest.mark.parametrize("transition", ["gate", "delivery", "replacement", "recovery"])
@pytest.mark.parametrize(("blocker_sql", "change_authority"), [
    ("BEGIN IMMEDIATE", False), ("BEGIN", False), ("BEGIN IMMEDIATE", True),
])
def test_other_agent_reads_while_transition_waits(waiting_owner, monkeypatch, transition, blocker_sql, change_authority):
    from functools import partial
    from loom.queue import _coordinator_transactions
    from loom.queue.local_daemon import TimeRecoveryRequest

    daemon, session, _, target, _ = waiting_owner
    policy = daemon._agent_policy
    peer = replace(policy.agents[0], credential_id="agent-b", principal_id="principal-b", agent_id="agent-b")
    principal = policy.principals[0]
    daemon.replace_agent_policy(replace(
        policy, agents=(*policy.agents, peer),
        principals=(replace(principal, agent_ids=(*principal.agent_ids, peer.agent_id),
                            actions=(*principal.actions, "maintenance", "recover_time")),),
    ))
    peer_view = daemon.agent_view(LocalDaemonPrincipal("principal-b", LocalDaemonRole.AGENT, "agent-b"))
    other = peer_view.register(AgentRegistration(
        "register-b", session.coordinator_id, session.coordinator_epoch, "root-b", "cfg",
        "inv", "avail", ("default",), peer.capabilities, retirement_verifier=_TEST_RETIREMENT_VERIFIER,
    ))
    reader, reader_id = peer_view, other.session_id
    operator = daemon.operator_view(LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR))
    if transition == "gate":
        call = partial(operator.maintenance, {
            "operation_id": "close-test", "maintenance_id": "test", "maintenance_intent_digest": "a" * 64,
            "action": "close", "expected_revision": 0, "check": None,
        }, expected_coordinator_id=session.coordinator_id)
        count = "SELECT count(*) FROM daemon_metadata WHERE key='maintenance-control:close-test'"
    elif transition == "delivery":
        call = target
        count = "SELECT count(*) FROM agent_deliveries"
    elif transition == "replacement":
        reader, reader_id = _view(daemon), session.session_id
        call = partial(operator.replace_agent_session, SessionReplacementRequest("replace-test", other.agent_id, "root lost"))
        count = "SELECT count(*) FROM session_replacements"
    else:
        with monkeypatch.context() as back:
            back.setattr(daemon, "_clock", lambda: "2000-01-01T00:00:00Z")
            with pytest.raises(QueueServiceError, match="regressed|degraded"):
                daemon._accepted_snapshot()
        call = partial(operator.recover_time, TimeRecoveryRequest(
            "recover-test", daemon.status().accepted_time_revision, session.coordinator_epoch, "verified clock",
        ))
        count = "SELECT count(*) FROM time_recoveries"

    waiting, retry = Event(), Event()

    def pause(_seconds):
        waiting.set()
        assert retry.wait(5)

    monkeypatch.setattr(_coordinator_transactions, "sleep", pause)
    with ThreadPoolExecutor() as workers, daemon._connection() as blocker:
        blocker.execute(blocker_sql)
        blocker.execute("SELECT * FROM agent_sessions").fetchall()
        pending = workers.submit(call)
        try:
            assert waiting.wait(3)
            read = workers.submit(reader.wait_for_controls, reader_id,
                                  received_operation_ids=(), wait_timeout_ms=0)
            assert read.result(2) == {"control": None, "assignment_control": None}
            blocker.rollback()
            if change_authority:
                if transition == "delivery":
                    with daemon._connection() as conn:
                        conn.execute("UPDATE agent_offers SET current=0 WHERE session_id=?", (session.session_id,))
                        conn.commit()
                elif transition == "replacement":
                    peer_view.publish_offer(
                        replace(_offer(other.session_id, other.coordinator_epoch, availability=other.availability_revision),
                                config_revision=other.config_revision, inventory_revision=other.inventory_revision),
                        idempotency_key="returned",
                    )
                elif transition == "recovery":
                    monkeypatch.setattr(daemon, "_clock", lambda: "2000-01-01T00:00:00Z")
                else:
                    operator.maintenance({
                        "operation_id": "other-close", "maintenance_id": "other",
                        "maintenance_intent_digest": "b" * 64, "action": "close",
                        "expected_revision": 0, "check": None,
                    }, expected_coordinator_id=session.coordinator_id)
        finally:
            blocker.rollback()
            retry.set()
        if change_authority:
            with pytest.raises(QueueConflictError):
                pending.result(3)
        else:
            assert pending.result(3) == call()
    with daemon._connection() as conn:
        assert conn.execute(count).fetchone()[0] == (0 if change_authority else 1)


@pytest.mark.parametrize(("store", "transaction"), [
    ("control", "BEGIN IMMEDIATE"), ("control", "BEGIN"),
    ("execution", "BEGIN IMMEDIATE"), ("execution", "BEGIN"),
    ("replacement", None), ("lost_commit_reply", None),
])
def test_native_reservation_leaves_no_claim_on_busy_or_store_substitution(
    waiting_owner, tmp_path, monkeypatch, store, transaction,
):
    import os
    import shutil
    import sqlite3

    from loom.queue.local_daemon_execution import _RemoteCandidateTarget, _ReservationBusy
    from tests.unit.loom.queue import test_managed_local as managed

    daemon, session, _, _, _ = waiting_owner
    execution = daemon._execution
    with daemon._connection() as conn:
        offer_id = conn.execute("SELECT offer_id FROM agent_offers WHERE current=1").fetchone()[0]
    _, command = managed._provider()
    assignment = replace(command.assignment, session_id=session.session_id, agent_id=session.agent_id, offer_id=offer_id)
    atom = replace(command.claim.atoms[0], local_capacity_key=f"{session.agent_id}:cpu")
    claim = replace(command.claim, atoms=(atom,))
    path = daemon.config.execution_database
    managed._seed_stage_work(path, assignment)
    execution.coordinator.publish_offer(managed._offer(assignment, (atom,)))
    receipt = managed._decision_receipt(assignment, claim)
    work = execution.stage_work_store.find_stage_work(assignment.stage_work_id)
    target = _RemoteCandidateTarget(
        agent_id=session.agent_id, session_id=session.session_id, offer_id=offer_id,
        availability_revision=session.availability_revision, scheduling_availability_revision=session.availability_revision,
        inventory_revision=session.inventory_revision, offer=_offer(session.session_id, session.coordinator_epoch),
        profile=_profile(tmp_path).descriptor, availability_atoms=(atom,), reflected_claim_ids=(),
    )
    epochs = (daemon._epoch, daemon._scheduling_epoch)

    def reserve():
        return execution.coordinator.reserve(
            assignment, (claim,), max_parallel_stages=1, decision_receipt=receipt,
            _reservation_transaction=lambda: execution._reservation_transaction(work, epochs, target),
        )

    if store == "replacement":
        execution.open_owner_stores()
        donor = tmp_path / "substituted.sqlite"
        shutil.copyfile(path, donor)
        with sqlite3.connect(donor) as conn:
            conn.execute("UPDATE local_daemon_owner_identity SET stable_id='different-coordinator'")
        os.replace(donor, path)
        with pytest.raises(sqlite3.DatabaseError, match="owner identity"):
            reserve()
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM coordinator_assignments").fetchone() == (0,)
        return

    revision = daemon._scheduling_reference_revision
    if store == "lost_commit_reply":
        from loom.queue import local_daemon_execution

        class LostReply(sqlite3.Connection):
            def commit(self):
                super().commit()
                raise sqlite3.OperationalError("lost reply after execution commit")

        with monkeypatch.context() as patch:
            patch.setattr(local_daemon_execution, "_connect_existing_sqlite",
                          lambda path, **kwargs: sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, factory=LostReply))
            with pytest.raises(sqlite3.OperationalError, match="lost reply"):
                reserve()
        assert daemon._scheduling_reference_revision > revision
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT assignment_id FROM coordinator_assignments").fetchall() == [(assignment.assignment_id,)]
    else:
        blocking_path = daemon.config.control_database if store == "control" else path
        with sqlite3.connect(blocking_path) as blocker, ThreadPoolExecutor() as pool:
            blocker.execute(transaction)
            blocker.execute("SELECT COUNT(*) FROM sqlite_schema").fetchone()
            try:
                with pytest.raises(_ReservationBusy):
                    pool.submit(reserve).result(timeout=2)
                assert pool.submit(_view(daemon).wait_for_controls, session.session_id,
                                   received_operation_ids=(), wait_timeout_ms=0).result(timeout=2) == {
                                       "control": None, "assignment_control": None,
                                   }
                with sqlite3.connect(path) as conn:
                    assert conn.execute("SELECT COUNT(*) FROM coordinator_assignments").fetchone() == (0,)
                    assert conn.execute("SELECT COUNT(*) FROM coordinator_atoms").fetchone() == (0,)
                assert daemon._scheduling_reference_revision == revision
            finally:
                blocker.rollback()
    assert reserve() == reserve() == "reserved"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT assignment_id FROM coordinator_assignments").fetchall() == [(assignment.assignment_id,)]
        assert conn.execute("SELECT capacity_key FROM coordinator_atoms").fetchall() == [(atom.local_capacity_key,)]


def test_reconciliation_clock_check_yields_while_sqlite_writer_is_busy(waiting_owner, monkeypatch):
    daemon, session, _, _, _ = waiting_owner
    sample = daemon._sample_clock_health
    outcomes = []
    sampled = Event()

    def record(**kwargs):
        result = sample(**kwargs)
        outcomes.append(result)
        sampled.set()
        return result

    monkeypatch.setattr(daemon, "_sample_clock_health", record)
    with ThreadPoolExecutor() as workers, daemon._connection() as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        turn = workers.submit(daemon.reconcile_once)
        try:
            assert sampled.wait(2)
            assert outcomes == [False]
            assert _view(daemon).wait_for_controls(
                session.session_id, received_operation_ids=(), wait_timeout_ms=0,
            ) == {"control": None, "assignment_control": None}
            assert turn.result(2) == ()
        finally:
            blocker.rollback()
    daemon.reconcile_once()
    assert outcomes == [False, True]


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


@pytest.mark.parametrize("reader", ["agent", "coordinator", "observation"])
def test_lifetime_owner_scan_allows_renewal_and_refuses_new_work(waiting_owner, monkeypatch, reader):
    from loom.queue import local_daemon_execution
    from loom.queue.agent_sessions import AgentOfferRenewal

    daemon, session, _, target, _ = waiting_owner
    view = _view(daemon)
    entered, resume = Event(), Event()
    inspect = local_daemon_execution.local_daemon_owner_work_is_retained

    def paused(*args, **kw):
        retained = inspect(*args, **kw)
        assert not retained
        entered.set()
        assert resume.wait(5)
        return retained

    monkeypatch.setattr(local_daemon_execution, "local_daemon_owner_work_is_retained", paused)
    with daemon._connection() as conn:
        offer_id = conn.execute("SELECT offer_id FROM agent_offers WHERE current=1").fetchone()[0]
    with ThreadPoolExecutor() as pool:
        if reader == "agent":
            decision = pool.submit(view.service_lifetime, session.session_id, session.coordinator_epoch,
                                   "generation", "observe")
        elif reader == "coordinator":
            decision = pool.submit(daemon._lifetime.retire_if_idle)
        else:
            decision = pool.submit(daemon._lifetime.observe, session.agent_root_id)
        try:
            assert entered.wait(3)
            renewal = AgentOfferRenewal(session.session_id, offer_id, session.availability_revision, 1)
            assert pool.submit(view.renew_offer, renewal).result(2)["state"] == "renewed"
            pool.submit(target).result(2)
        finally:
            resume.set()
        outcome = decision.result(3)
    if reader == "agent":
        assert outcome["state"] == "retained"
    elif reader == "coordinator":
        assert outcome is False
    else:
        assert outcome["retained"] and not outcome["retiring"]
    assert not daemon._lifetime.retiring
    with daemon._connection() as conn:
        assert conn.execute("SELECT state FROM agent_sessions").fetchone()[0] == "ACTIVE"


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
