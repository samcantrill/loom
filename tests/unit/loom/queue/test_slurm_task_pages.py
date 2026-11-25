"""Slurm control pages honor encoded bytes and never skip an undelivered task."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
import json
import sqlite3
from threading import Event, RLock
from typing import Any, cast
from types import SimpleNamespace

import pytest

from loom.queue.errors import QueueServiceError
from loom.queue.local_daemon import _ensure_recovery_assignment_index
from loom.queue.local_daemon_execution import LocalDaemonExecution
from loom.queue._slurm_task_page import pack_page
from loom.queue._agent_session_codec import _MAX_BODY_BYTES, _decode
from loom.queue import agent_sessions


def owner_for(sizes, *, withheld=()):
    records = [SimpleNamespace(assignment=SimpleNamespace(assignment_id=f"assignment-{i:03d}")) for i in range(len(sizes))]
    constructed = []

    def page(agent, root, *, after):
        assert (agent, root) == ("agent", "root")
        return tuple(row for row in records if after is None or row.assignment.assignment_id > after)[:33]

    def task(row, facts):
        identity = row.assignment.assignment_id
        constructed.append(identity)
        return {"assignment": {"assignment_id": identity}, "recovery_request": None,
                "payload": "x" * sizes[int(identity.rsplit("-", 1)[1])]}

    return SimpleNamespace(
        slurm_assignments=SimpleNamespace(agent_page=page), _slurm_task=task,
        _slurm_recoveries=lambda ids: {key: [("{}", "pending", True)] for key in ids if key in withheld},
    ), constructed


def page(owner, cursor=None):
    rows = owner.slurm_assignments.agent_page("agent", "root", after=cursor)
    ids = [row.assignment.assignment_id for row in rows]
    facts = owner._slurm_recoveries(ids)

    def task_at(index):
        return owner._slurm_task(rows[index], facts.get(ids[index], ())), ids[index] in facts

    return cast(dict[str, Any], pack_page(ids, cursor, task_at))


def wire(reply):
    return json.dumps({"ok": True, "result": reply}, sort_keys=True, separators=(",", ":")).encode()


def test_page_count_bounds_materialization_and_replays_lost_response():
    owner, constructed = owner_for([10] * 70)
    first = page(owner)
    assert len(first["tasks"]) == 32
    assert len(constructed) == 32
    assert page(owner) == first
    second = page(owner, first["next_cursor"])
    third = page(owner, second["next_cursor"])
    assert [len(reply["tasks"]) for reply in (first, second, third)] == [32, 32, 6]
    assert third["next_cursor"] is None
    assert len({row["assignment"]["assignment_id"] for reply in (first, second, third) for row in reply["tasks"]}) == 70
    assert len(wire(first)) <= _MAX_BODY_BYTES
    _decode(wire(first))


def test_byte_boundary_returns_last_delivered_cursor():
    owner, _ = owner_for([20000] * 5)
    first = page(owner)
    assert len(first["tasks"]) == 3
    assert len(wire(first)) <= _MAX_BODY_BYTES
    second = page(owner, first["next_cursor"])
    assert len(second["tasks"]) == 2
    assert second["tasks"][0]["assignment"]["assignment_id"] == "assignment-003"
    assert second["next_cursor"] is None


def test_oversized_task_is_an_error_not_an_advanced_cursor():
    owner, _ = owner_for([_MAX_BODY_BYTES + 1, 10])
    for _ in range(2):
        with pytest.raises(QueueServiceError, match="response budget"):
            page(owner)


def test_withheld_recovery_page_still_advances_scan_without_losing_later_work():
    owner, _ = owner_for([10] * 34, withheld={f"assignment-{i:03d}" for i in range(32)})
    first = page(owner)
    assert first == {"tasks": [], "next_cursor": "assignment-031"}
    assert len(page(owner, first["next_cursor"])["tasks"]) == 2

@pytest.mark.parametrize("page_size", [1, 32])
def test_recovery_lookup_reads_one_indexed_page(tmp_path, page_size):
    path = tmp_path / "control.sqlite"
    queries = []

    @contextmanager
    def connect(database):
        with sqlite3.connect(database) as conn:
            conn.set_trace_callback(queries.append)
            yield conn

    ids = tuple(f"page-{i}" for i in range(page_size))
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE recovery_operations (request_json TEXT, state TEXT)")
        conn.executemany(
            "INSERT INTO recovery_operations VALUES (?, ?)",
            [(json.dumps({"assignment_id": f"other-{i}"}), "pending") for i in range(4096)]
            + [(json.dumps({"assignment_id": ids[0], "target": {"kind": kind}}), state)
               for kind, state in (("slurm", "closed"), ("managed", "closed"), ("slurm", "pending"),
                                   ("slurm", "evidence_confirmed"), ("slurm", "refused"))],
        )
        _ensure_recovery_assignment_index(conn)
    owner = SimpleNamespace(config=SimpleNamespace(control_database=path, connect_database=connect))
    facts = LocalDaemonExecution._slurm_recoveries(cast(LocalDaemonExecution, owner), ids)
    assert list(facts) == [ids[0]]
    assert [(state, retains) for _, state, retains in facts[ids[0]]] == [
        ("closed", False), ("closed", True), ("pending", True), ("evidence_confirmed", True),
    ]
    assert len(queries) == 1
    with sqlite3.connect(path) as conn:
        plan = conn.execute("EXPLAIN QUERY PLAN " + queries[0]).fetchall()
    assert any("SEARCH recovery_operations USING INDEX recovery_by_assignment" in row[3] for row in plan)


@pytest.mark.parametrize("change", ["recovery", "sequence", "unrelated"])
def test_agent_renews_during_packing_and_reply_uses_current_page(tmp_path, monkeypatch, change):
    from dataclasses import replace

    from loom.queue import LocalDaemon, LocalDaemonPrincipal, LocalDaemonRole
    from loom.queue.local_daemon import RecoverUnknownAssignment, SlurmRecoveryTarget
    from loom.queue import _slurm_task_page
    from loom.queue.agent_sessions import AgentOfferRenewal, AgentRegistration, SLURM_SUBMISSION_CAPABILITY
    from tests.unit.loom.queue.test_agent_sessions import _config, _offer, _policy, _TEST_RETIREMENT_VERIFIER
    from tests.unit.loom.queue.test_slurm_admission import ReservationFixture

    directory = tmp_path / "reservation"
    directory.mkdir()
    fixture = ReservationFixture(directory)
    policy = _policy()
    a = replace(policy.agents[0], capabilities=("python", SLURM_SUBMISSION_CAPABILITY))
    b = replace(a, credential_id="agent-b", agent_id="agent-b", principal_id="principal-b")
    config = replace(_config(tmp_path, replace(policy, agents=(a, b))),
                     agent_root=None, resident_worker_launch_profile=None, agent_resource_providers=(),
                     cpu_capacity=0, memory_capacity_bytes=0, slurm_profiles=(fixture.profile,))
    monkeypatch.setattr(LocalDaemon, "_serve", lambda self: self._stop.wait())
    LocalDaemon.initialize(config)
    if change == "unrelated":
        with config.connect_database(config.execution_database) as conn:
            conn.execute("DROP INDEX slurm_active_agent_page")
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        def register(rule):
            view = daemon.agent_view(LocalDaemonPrincipal(rule.principal_id, LocalDaemonRole.AGENT, rule.credential_id))
            identity = view.handshake()
            session = view.register(AgentRegistration(
                rule.agent_id, str(identity["coordinator_id"]), str(identity["coordinator_epoch"]),
                "root-" + rule.agent_id, "config-1", "inventory-1", "availability-1",
                ("default",), rule.capabilities, retirement_verifier=_TEST_RETIREMENT_VERIFIER,
            ))
            return view, session

        view, session = register(a)
        other, peer = register(b)
        offer = other.publish_offer(_offer(peer.session_id, peer.coordinator_epoch), idempotency_key="offer")
        execution = daemon._execution
        assert execution is not None
        with config.connect_database(config.execution_database) as conn:
            plan = conn.execute("EXPLAIN QUERY PLAN SELECT assignment_id FROM slurm_stage_assignments "
                                "WHERE state != 'released' AND json_extract(identity_json, '$.agent_id') = ? "
                                "AND json_extract(identity_json, '$.agent_root_id') = ? AND assignment_id > ? "
                                "ORDER BY assignment_id LIMIT 33", (session.agent_id, session.agent_root_id, "")).fetchall()
            assert any("USING INDEX slurm_active_agent_page" in row[3] for row in plan)
        fixture.work = execution.stage_work_store
        assignment, args = fixture.candidate("work", 0)
        assignment = replace(assignment, agent_id=session.agent_id, agent_root_id=session.agent_root_id)
        store = execution.slurm_assignments
        store.reserve(assignment, **{**args, "max_reserved_gpus": None})

        def reject_full_record(_row):
            pytest.fail("agent task observation decoded a complete worker record")

        monkeypatch.setattr(store, "_record", reject_full_record)
        paused, resume = Event(), Event()
        attempts = []
        original = _slurm_task_page.pack_page

        def pack(*args):
            page = original(*args)
            attempts.append(page)
            if len(attempts) == 1:
                paused.set()
                assert resume.wait(5)
            return page

        monkeypatch.setattr(_slurm_task_page, "pack_page", pack)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(view.slurm_work, session.session_id, session.coordinator_epoch)
            try:
                assert paused.wait(3)
                renewal = AgentOfferRenewal(peer.session_id, str(offer["offer_id"]), peer.availability_revision, 1)
                assert pool.submit(other.renew_offer, renewal).result(timeout=2)["state"] == "renewed"
                if change == "recovery":
                    # Model the control journal immediately after durable recovery admission.
                    request = RecoverUnknownAssignment(
                        "recovery", assignment.run_uri, assignment.stage_name, assignment.attempt,
                        assignment.stage_work_id, assignment.assignment_id, "process", "fence",
                        SlurmRecoveryTarget(assignment.profile_id, assignment.operation_id, "cluster", "123", None),
                        1, "failed", False, "verify task withholding during recovery",
                    )
                    with daemon._connection() as conn:
                        conn.execute("INSERT INTO recovery_operations VALUES "
                                     "('recovery', 'operator', ?, 'digest', '2026-11-01T00:00:00Z', 'pending', NULL, '{}')",
                                     (json.dumps(request.to_dict()),))
                        conn.commit()
                elif change == "sequence":
                    store.accept_agent_evidence(assignment.assignment_id, 1, {"sequence": 1})
            finally:
                resume.set()
            result = cast(dict[str, Any], pending.result(timeout=5))
        assert len(attempts) == (1 if change == "unrelated" else 2)
        assert attempts[0]["tasks"][0]["expected_sequence"] == 0
        if change == "recovery":
            assert result == {"tasks": [], "next_cursor": None}
        else:
            assert result["tasks"][0]["expected_sequence"] == (1 if change == "sequence" else 0)
    finally:
        daemon.stop()


@pytest.mark.parametrize("reload", [False, True])
def test_slow_task_page_yields_to_evidence_and_discards_stale_observations(monkeypatch, reload):
    entered, finish = Event(), Event()
    lock = RLock()
    page = {"tasks": [{"assignment": "exact-assignment"}], "next_cursor": None}

    def slow_page(agent_id, root_id, *, cursor):
        assert (agent_id, root_id, cursor) == ("agent", "root", None)
        entered.set()
        assert finish.wait(5)
        return page

    def acknowledge(agent_id, root_id, evidence, *, _defer_output):
        assert (agent_id, root_id, evidence) == ("agent", "root", {"sequence": 1})
        assert not _defer_output
        return {"sequence": 1}

    session = SimpleNamespace(
        agent_id="agent", agent_root_id="root", state=agent_sessions.AgentSessionState.ACTIVE,
        policy_revision="policy", capabilities={
            agent_sessions.SLURM_SUBMISSION_CAPABILITY, agent_sessions.SLURM_PENDING_EFFECTS_CAPABILITY,
        },
    )
    connection = SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchone=lambda: None))
    daemon: Any = SimpleNamespace(
        _cycle_lock=lock, _state_guard=lambda: lock, _connection=lambda: nullcontext(connection),
        _epoch="epoch", _scheduling_epoch="before", _require_started=lambda: "owner",
        _execution=SimpleNamespace(slurm_agent_task_page=slow_page, acknowledge_slurm_pending=acknowledge),
    )
    monkeypatch.setattr(agent_sessions, "_session_from_row", lambda *_, **__: session)
    rule = SimpleNamespace(principal_id="principal", agent_id="agent")
    service = agent_sessions.AgentSessionService(daemon, cast(Any, None))
    monkeypatch.setattr(service, "_authorize", lambda _: (rule, "policy"))
    with ThreadPoolExecutor(max_workers=2) as workers:
        observation = workers.submit(service.slurm_work, "session", "epoch")
        try:
            assert entered.wait(3)
            receipt = workers.submit(service.slurm_work, "session", "epoch", {"sequence": 1})
            assert receipt.result(timeout=2) == {"sequence": 1}
            if reload:
                with lock:
                    daemon._scheduling_epoch = "after"
        finally:
            finish.set()
        expected = {"tasks": [], "next_cursor": None} if reload else page
        assert observation.result(timeout=3) == expected
