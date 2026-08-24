"""Focused no-launch tests for authenticated agent-session state."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

import pytest

from loom.queue import (
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)
from loom.queue.agent_sessions import (
    AgentOffer,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    AgentRetirementProof,
    AgentSessionState,
)
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


def _policy(
    *, revision: str = "policy-1", credential: str = "agent-a"
) -> AgentPolicyConfig:
    return AgentPolicyConfig(
        revision=revision,
        agents=(
            AgentPrincipalPolicy(
                credential_id=credential,
                principal_id="principal-a",
                agent_id="agent-a",
                pools=("default",),
                capabilities=("python",),
            ),
        ),
    )


def _config(
    tmp_path: Path, policy: AgentPolicyConfig | None = None
) -> LocalDaemonConfig:
    return LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        agent_policy=_policy() if policy is None else policy,
    )


def _view(daemon: LocalDaemon, credential: str = "agent-a"):
    return daemon.agent_view(
        LocalDaemonPrincipal("principal-a", LocalDaemonRole.AGENT, credential)
    )


def _register(daemon: LocalDaemon, *, key: str = "register-1"):
    handshake = _view(daemon).handshake()
    return _view(daemon).register(
        AgentRegistration(
            idempotency_key=key,
            coordinator_id=str(handshake["coordinator_id"]),
            coordinator_epoch=str(handshake["coordinator_epoch"]),
            agent_root_id="agent-root-a",
            config_revision="config-1",
            inventory_revision="inventory-1",
            availability_revision="availability-1",
            declared_pools=("default", "untrusted-pool"),
            declared_capabilities=("python", "untrusted"),
        )
    )


def _offer(
    session_id: str, epoch: str, *, availability: str = "availability-1"
) -> AgentOffer:
    return AgentOffer(
        session_id=session_id,
        coordinator_epoch=epoch,
        config_revision="config-1",
        inventory_revision="inventory-1",
        availability_revision=availability,
        cpu=2,
        memory_bytes=1024,
        ttl_seconds=30,
    )


def _proof(session) -> AgentRetirementProof:
    return AgentRetirementProof(
        session_id=session.session_id,
        coordinator_id=session.coordinator_id,
        coordinator_epoch=session.coordinator_epoch,
        agent_id=session.agent_id,
        agent_root_id=session.agent_root_id,
        policy_revision=session.policy_revision,
        config_revision=session.config_revision,
        inventory_revision=session.inventory_revision,
        availability_revision=session.availability_revision,
        reference_revision=0,
        reference_digest="a" * 64,
    )


def _sqlite_snapshot(path: Path) -> tuple[str, ...]:
    with sqlite3.connect(path) as conn:
        return tuple(conn.iterdump())


def _file_snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (str(path.relative_to(root)), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def test_registration_replay_is_coordinator_issued_and_digest_bound(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        replay = _register(daemon)
        assert replay.session_id == registered.session_id
        assert registered.session_id.startswith("session-")
        assert registered.capabilities == ("python",)
        assert registered.pools == ("default",)
        with pytest.raises(QueueConflictError, match="different content"):
            _view(daemon).register(
                AgentRegistration(
                    idempotency_key="register-1",
                    coordinator_id=registered.coordinator_id,
                    coordinator_epoch=registered.coordinator_epoch,
                    agent_root_id=registered.agent_root_id,
                    config_revision="changed",
                    inventory_revision="inventory-1",
                    availability_revision="availability-1",
                    declared_pools=("default",),
                )
            )
        with pytest.raises(QueueConflictError, match="cannot select"):
            _view(daemon).register(
                AgentRegistration(
                    idempotency_key="register-2",
                    coordinator_id=registered.coordinator_id,
                    coordinator_epoch=registered.coordinator_epoch,
                    agent_root_id=registered.agent_root_id,
                    config_revision="config-1",
                    inventory_revision="inventory-1",
                    availability_revision="availability-1",
                    declared_pools=("default",),
                    session_id="caller-session",
                )
            )
    finally:
        daemon.stop()


def test_policy_removal_fences_existing_session_and_overlap_reconciles(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        daemon.replace_agent_policy(AgentPolicyConfig(revision="policy-2"))
        with pytest.raises(QueueServiceError, match="not authorized"):
            _view(daemon).publish_offer(
                _offer(registered.session_id, registered.coordinator_epoch),
                idempotency_key="offer-1",
            )
        overlap = AgentPolicyConfig(
            revision="policy-3",
            agents=(
                AgentPrincipalPolicy(
                    "agent-b", "principal-a", "agent-a", ("default",), ("python",)
                ),
            ),
        )
        daemon.replace_agent_policy(overlap)
        resumed = _view(daemon, "agent-b").reconcile(
            registered,
            registered.coordinator_epoch,
            idempotency_key="reconcile-1",
        )
        assert resumed.session_id == registered.session_id
        assert resumed.policy_revision == "policy-3"
    finally:
        daemon.stop()


def test_restart_requires_reconcile_fresh_offer_and_only_returns_wait(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    first = LocalDaemon(config)
    first.start()
    registered = _register(first)
    first.stop()

    second = LocalDaemon(config)
    second.start()
    try:
        handshake = _view(second).handshake()
        epoch = str(handshake["coordinator_epoch"])
        assert epoch != registered.coordinator_epoch
        replayed = _view(second).register(
            AgentRegistration(
                idempotency_key="register-1",
                coordinator_id=registered.coordinator_id,
                coordinator_epoch=registered.coordinator_epoch,
                agent_root_id=registered.agent_root_id,
                config_revision=registered.config_revision,
                inventory_revision=registered.inventory_revision,
                availability_revision=registered.availability_revision,
                declared_pools=("default", "untrusted-pool"),
                declared_capabilities=("python", "untrusted"),
            )
        )
        assert replayed == registered
        with pytest.raises(QueueConflictError, match="epoch"):
            _view(second).publish_offer(
                _offer(registered.session_id, registered.coordinator_epoch),
                idempotency_key="offer-stale",
            )
        resumed = _view(second).reconcile(
            registered, epoch, idempotency_key="reconcile-1"
        )
        offer = _view(second).publish_offer(
            _offer(resumed.session_id, epoch), idempotency_key="offer-1"
        )
        assert offer["state"] == "retained"
        wait = _view(second).wait_for_work(
            resumed.session_id,
            "availability-1",
            poll_id="poll-1",
            wait_timeout_ms=5,
        )
        assert wait == {
            "result": "wait",
            "poll_id": "poll-1",
            "coordinator_epoch": epoch,
        }

        # The restricted view cannot touch the Phase 3 execution owners.
        with sqlite3.connect(config.execution_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM coordinator_assignments").fetchone()[
                    0
                ]
                == 0
            )
            assert (
                conn.execute("SELECT COUNT(*) FROM coordinator_offers").fetchone()[0]
                == 0
            )
    finally:
        second.stop()


def test_retirement_fences_then_requires_empty_coordinator_references_and_tombstones(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        reconciled = _view(daemon).reconcile(
            registered,
            registered.coordinator_epoch,
            idempotency_key="reconcile-before-retire",
        )
        proof = _proof(reconciled)
        _view(daemon).publish_offer(
            _offer(registered.session_id, registered.coordinator_epoch),
            idempotency_key="offer-1",
        )
        with pytest.raises(QueueConflictError, match="proof is stale"):
            _view(daemon).retire_clean(
                replace(proof, agent_root_id="replacement-root"),
                idempotency_key="retire-wrong-root",
            )
        with daemon._connection() as conn:  # coordinator-owned known reference
            conn.execute(
                "INSERT INTO agent_polls(poll_id, principal_id, session_id, "
                "availability_revision, coordinator_epoch, wait_timeout_ms, "
                "digest, active, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL)",
                (
                    "poll-active",
                    "principal-a",
                    registered.session_id,
                    registered.availability_revision,
                    registered.coordinator_epoch,
                    100,
                    "digest",
                ),
            )
            conn.execute(
                "INSERT INTO agent_coordinator_references(session_id, reference_kind, reference_id, resolved) VALUES (?, ?, ?, 0)",
                (registered.session_id, "outbox", "event-1"),
            )
            conn.commit()
        with pytest.raises(QueueConflictError, match="unresolved"):
            _view(daemon).retire_clean(proof, idempotency_key="retire-1")
        with daemon._connection() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_offers WHERE current = 1"
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_polls WHERE active = 1"
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute("SELECT state FROM agent_sessions").fetchone()[0]
                == "RETIRING"
            )
            conn.execute("UPDATE agent_coordinator_references SET resolved = 1")
            conn.commit()
        daemon.stop()
        daemon.replace_agent_policy(
            AgentPolicyConfig(
                revision="policy-2",
                agents=(
                    AgentPrincipalPolicy(
                        "agent-b",
                        "principal-a",
                        "agent-a",
                        ("default",),
                        ("python",),
                    ),
                ),
            )
        )
        daemon.start()
        retired = _view(daemon, "agent-b").retire_clean(
            proof, idempotency_key="retire-1"
        )
        assert retired["state"] == AgentSessionState.RETIRED_CLEAN.value
        with daemon._connection() as conn:
            assert (
                conn.execute("SELECT state FROM agent_session_tombstones").fetchone()[0]
                == "RETIRED_CLEAN"
            )
        original_registration = AgentRegistration(
            idempotency_key="register-1",
            coordinator_id=registered.coordinator_id,
            coordinator_epoch=registered.coordinator_epoch,
            agent_root_id=registered.agent_root_id,
            config_revision=registered.config_revision,
            inventory_revision=registered.inventory_revision,
            availability_revision=registered.availability_revision,
            declared_pools=("default", "untrusted-pool"),
            declared_capabilities=("python", "untrusted"),
        )
        with pytest.raises(QueueConflictError, match="no longer actionable"):
            _view(daemon, "agent-b").register(original_registration)
        with pytest.raises(QueueConflictError, match="no longer actionable"):
            _view(daemon, "agent-b").reconcile(
                registered,
                registered.coordinator_epoch,
                idempotency_key="reconcile-before-retire",
            )
    finally:
        daemon.stop()


def test_offer_expiry_and_stale_poll_fail_without_touching_execution_owners(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    now = ["2026-01-01T00:00:00Z"]
    daemon = LocalDaemon(config, clock=lambda: now[0])
    daemon.start()
    try:
        registered = _register(daemon)
        _view(daemon).publish_offer(
            AgentOffer(
                registered.session_id,
                registered.coordinator_epoch,
                "config-1",
                "inventory-1",
                "availability-1",
                1,
                1,
                1,
            ),
            idempotency_key="offer-1",
        )
        now[0] = "2026-01-01T00:00:02Z"
        with pytest.raises(QueueConflictError, match="current offer"):
            _view(daemon).wait_for_work(
                registered.session_id,
                "availability-1",
                poll_id="expired-poll",
                wait_timeout_ms=5,
            )
        with pytest.raises(QueueConflictError, match="availability revision"):
            _view(daemon).wait_for_work(
                registered.session_id,
                "availability-2",
                poll_id="stale-poll",
                wait_timeout_ms=5,
            )
        with sqlite3.connect(config.execution_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM coordinator_assignments").fetchone()[
                    0
                ]
                == 0
            )
    finally:
        daemon.stop()


def test_offer_wire_shape_uses_bounded_exact_capacity_atoms() -> None:
    value = _offer("session-1", "epoch-1").value()
    assert "cpu" not in value and "memory_bytes" not in value
    atoms = value["capacity_atoms"]
    assert isinstance(atoms, list)
    assert atoms == [
        {
            "owner_resource_kind": "cpu",
            "local_capacity_key": "cpu",
            "amount": {"numerator": 2, "denominator": 1},
            "unit": "count",
            "granularity": {"numerator": 1, "denominator": 1},
        },
        {
            "owner_resource_kind": "memory",
            "local_capacity_key": "memory",
            "amount": {"numerator": 1024, "denominator": 1},
            "unit": "byte",
            "granularity": {"numerator": 1, "denominator": 1},
        },
    ]


def test_wait_poll_is_digest_replayed_and_current_policy_is_rechecked(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        _view(daemon).publish_offer(
            _offer(registered.session_id, registered.coordinator_epoch),
            idempotency_key="offer-1",
        )
        first = _view(daemon).wait_for_work(
            registered.session_id,
            "availability-1",
            poll_id="poll-1",
            wait_timeout_ms=10,
        )
        assert (
            _view(daemon).wait_for_work(
                registered.session_id,
                "availability-1",
                poll_id="poll-1",
                wait_timeout_ms=10,
            )
            == first
        )
        with pytest.raises(QueueConflictError, match="different content"):
            _view(daemon).wait_for_work(
                registered.session_id,
                "availability-1",
                poll_id="poll-1",
                wait_timeout_ms=11,
            )

        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(
                _view(daemon).wait_for_work,
                registered.session_id,
                "availability-1",
                poll_id="poll-live",
                wait_timeout_ms=1_000,
            )
            deadline = monotonic() + 2
            while monotonic() < deadline:
                with daemon._connection() as conn:
                    active = conn.execute(
                        "SELECT active FROM agent_polls WHERE poll_id = 'poll-live'"
                    ).fetchone()
                if active is not None and bool(active[0]):
                    break
                sleep(0.01)
            else:
                pytest.fail("live work poll did not become active")
            with pytest.raises(QueueConflictError, match="already active"):
                _view(daemon).wait_for_work(
                    registered.session_id,
                    "availability-1",
                    poll_id="poll-live",
                    wait_timeout_ms=1_000,
                )
            with pytest.raises(QueueConflictError, match="active work poll"):
                _view(daemon).wait_for_work(
                    registered.session_id,
                    "availability-1",
                    poll_id="poll-concurrent",
                    wait_timeout_ms=10,
                )
            with pytest.raises(QueueConflictError, match="active poll"):
                _view(daemon).publish_offer(
                    _offer(registered.session_id, registered.coordinator_epoch),
                    idempotency_key="offer-during-poll",
                )
            daemon.replace_agent_policy(AgentPolicyConfig(revision="policy-2"))
            with pytest.raises(QueueServiceError, match="not authorized"):
                pending.result(timeout=2)
    finally:
        daemon.stop()


def test_reconciliation_and_offer_preserve_the_durable_effective_scope(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        with pytest.raises(QueueConflictError, match="reconciliation facts"):
            _view(daemon).reconcile(
                replace(registered, inventory_revision="different"),
                registered.coordinator_epoch,
                idempotency_key="reconcile-stale",
            )
        with pytest.raises(QueueConflictError, match="effective scope"):
            _view(daemon).publish_offer(
                replace(
                    _offer(registered.session_id, registered.coordinator_epoch),
                    pools=("other",),
                ),
                idempotency_key="offer-1",
            )
    finally:
        daemon.stop()


def test_current_v1_roots_migrate_additively_without_losing_admission_tables(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    for path in (config.control_database, config.agent_root / "control.sqlite"):
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        with sqlite3.connect(config.control_database) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'managed_admissions'"
            ).fetchone()
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'agent_sessions'"
            ).fetchone()
    finally:
        daemon.stop()


def test_current_version_incomplete_session_schema_is_rejected_not_repaired(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    with sqlite3.connect(config.control_database) as conn:
        conn.execute("DROP TABLE agent_retirement_proofs")
        conn.commit()

    daemon = LocalDaemon(config)
    with pytest.raises(QueueServiceError, match="schema is incomplete"):
        daemon.start()
    with sqlite3.connect(config.control_database) as conn:
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'agent_retirement_proofs'"
            ).fetchone()
            is None
        )

    trigger_config = _config(tmp_path / "missing-trigger")
    LocalDaemon.initialize(trigger_config)
    with sqlite3.connect(trigger_config.agent_root / "control.sqlite") as conn:
        conn.execute("DROP TRIGGER agent_reference_revision_update")
        conn.commit()
    with pytest.raises(QueueServiceError, match="schema is incomplete"):
        LocalDaemon(trigger_config).start()


def test_every_agent_operation_is_causally_outside_execution_owners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        execution = daemon._execution
        assert execution is not None

        def unexpected_launch(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("agent operation reached the execution launcher")

        monkeypatch.setattr(type(execution), "_execute", unexpected_launch)
        monkeypatch.setattr(SQLitePerRunAuthorityStore, "__init__", unexpected_launch)
        execution_before = _sqlite_snapshot(config.execution_database)
        provider_before = _sqlite_snapshot(config.agent_journal)
        artifacts_before = _file_snapshot(config.run_store_root)

        _view(daemon).handshake()
        registered = _register(daemon)
        reconciled = _view(daemon).reconcile(
            registered,
            registered.coordinator_epoch,
            idempotency_key="reconcile-no-launch",
        )
        _view(daemon).publish_offer(
            _offer(reconciled.session_id, reconciled.coordinator_epoch),
            idempotency_key="offer-no-launch",
        )
        _view(daemon).wait_for_work(
            reconciled.session_id,
            reconciled.availability_revision,
            poll_id="poll-no-launch",
            wait_timeout_ms=5,
        )
        _view(daemon).retire_clean(
            _proof(reconciled), idempotency_key="retire-no-launch"
        )

        assert _sqlite_snapshot(config.execution_database) == execution_before
        assert _sqlite_snapshot(config.agent_journal) == provider_before
        assert _file_snapshot(config.run_store_root) == artifacts_before
    finally:
        daemon.stop()
