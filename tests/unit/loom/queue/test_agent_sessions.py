"""Focused no-launch tests for authenticated agent-session state."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from loom.queue import LocalDaemon, LocalDaemonConfig, LocalDaemonPrincipal, LocalDaemonRole
from loom.queue.agent_sessions import (
    AgentOffer,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    AgentSessionState,
)
from loom.queue.errors import QueueConflictError, QueueServiceError


def _policy(*, revision: str = "policy-1", credential: str = "agent-a") -> AgentPolicyConfig:
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


def _config(tmp_path: Path, policy: AgentPolicyConfig | None = None) -> LocalDaemonConfig:
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
            config_revision="config-1",
            inventory_revision="inventory-1",
            availability_revision="availability-1",
            declared_capabilities=("python", "untrusted"),
        )
    )


def _offer(session_id: str, epoch: str, *, availability: str = "availability-1") -> AgentOffer:
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


def test_registration_replay_is_coordinator_issued_and_digest_bound(tmp_path: Path) -> None:
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
        with pytest.raises(QueueConflictError, match="different content"):
            _view(daemon).register(
                AgentRegistration(
                    idempotency_key="register-1",
                    coordinator_id=registered.coordinator_id,
                    coordinator_epoch=registered.coordinator_epoch,
                    config_revision="changed",
                    inventory_revision="inventory-1",
                    availability_revision="availability-1",
                )
            )
        with pytest.raises(QueueConflictError, match="cannot select"):
            _view(daemon).register(
                AgentRegistration(
                    idempotency_key="register-2",
                    coordinator_id=registered.coordinator_id,
                    coordinator_epoch=registered.coordinator_epoch,
                    config_revision="config-1",
                    inventory_revision="inventory-1",
                    availability_revision="availability-1",
                    session_id="caller-session",
                )
            )
    finally:
        daemon.stop()


def test_policy_removal_fences_existing_session_and_overlap_reconciles(tmp_path: Path) -> None:
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
                AgentPrincipalPolicy("agent-b", "principal-a", "agent-a", ("default",), ("python",)),
            ),
        )
        daemon.replace_agent_policy(overlap)
        resumed = _view(daemon, "agent-b").reconcile(
            registered.session_id, registered.coordinator_epoch
        )
        assert resumed.session_id == registered.session_id
        assert resumed.policy_revision == "policy-3"
    finally:
        daemon.stop()


def test_restart_requires_reconcile_fresh_offer_and_only_returns_wait(tmp_path: Path) -> None:
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
        with pytest.raises(QueueConflictError, match="epoch"):
            _view(second).publish_offer(
                _offer(registered.session_id, registered.coordinator_epoch),
                idempotency_key="offer-stale",
            )
        resumed = _view(second).reconcile(registered.session_id, epoch)
        offer = _view(second).publish_offer(
            _offer(resumed.session_id, epoch), idempotency_key="offer-1"
        )
        assert offer["state"] == "retained"
        wait = _view(second).wait_for_work(
            resumed.session_id, "availability-1", poll_id="poll-1"
        )
        assert wait == {"result": "wait", "poll_id": "poll-1", "coordinator_epoch": epoch}

        # The restricted view cannot touch the Phase 3 execution owners.
        with sqlite3.connect(config.execution_database) as conn:
            assert conn.execute("SELECT COUNT(*) FROM coordinator_assignments").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM coordinator_offers").fetchone()[0] == 0
    finally:
        second.stop()


def test_retirement_fences_then_requires_empty_coordinator_references_and_tombstones(tmp_path: Path) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        with daemon._connection() as conn:  # coordinator-owned known reference
            conn.execute(
                "INSERT INTO agent_coordinator_references(session_id, reference_kind, reference_id, resolved) VALUES (?, ?, ?, 0)",
                (registered.session_id, "outbox", "event-1"),
            )
            conn.commit()
        with pytest.raises(QueueConflictError, match="unresolved"):
            _view(daemon).retire_clean(registered.session_id, idempotency_key="retire-1", agent_proof="proof-1")
        with daemon._connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM agent_offers WHERE current = 1").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM agent_polls WHERE active = 1").fetchone()[0] == 0
            conn.execute("UPDATE agent_coordinator_references SET resolved = 1")
            conn.commit()
        retired = _view(daemon).retire_clean(registered.session_id, idempotency_key="retire-1", agent_proof="proof-1")
        assert retired["state"] == AgentSessionState.RETIRED_CLEAN.value
        with daemon._connection() as conn:
            assert conn.execute("SELECT state FROM agent_session_tombstones").fetchone()[0] == "RETIRED_CLEAN"
    finally:
        daemon.stop()


def test_offer_expiry_and_stale_poll_fail_without_touching_execution_owners(tmp_path: Path) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    now = ["2026-01-01T00:00:00Z"]
    daemon = LocalDaemon(config, clock=lambda: now[0])
    daemon.start()
    try:
        registered = _register(daemon)
        _view(daemon).publish_offer(
            AgentOffer(
                registered.session_id, registered.coordinator_epoch, "config-1",
                "inventory-1", "availability-1", 1, 1, 1,
            ),
            idempotency_key="offer-1",
        )
        now[0] = "2026-01-01T00:00:02Z"
        with pytest.raises(QueueConflictError, match="current offer"):
            _view(daemon).wait_for_work(
                registered.session_id, "availability-1", poll_id="expired-poll"
            )
        with pytest.raises(QueueConflictError, match="availability revision"):
            _view(daemon).wait_for_work(
                registered.session_id, "availability-2", poll_id="stale-poll"
            )
        with sqlite3.connect(config.execution_database) as conn:
            assert conn.execute("SELECT COUNT(*) FROM coordinator_assignments").fetchone()[0] == 0
    finally:
        daemon.stop()


def test_wait_poll_is_digest_replayed_and_current_policy_is_rechecked(tmp_path: Path) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        _view(daemon).publish_offer(_offer(registered.session_id, registered.coordinator_epoch), idempotency_key="offer-1")
        first = _view(daemon).wait_for_work(registered.session_id, "availability-1", poll_id="poll-1")
        assert _view(daemon).wait_for_work(registered.session_id, "availability-1", poll_id="poll-1") == first
        daemon.replace_agent_policy(AgentPolicyConfig(revision="policy-2"))
        with pytest.raises(QueueServiceError, match="not authorized"):
            _view(daemon).wait_for_work(registered.session_id, "availability-1", poll_id="poll-1")
    finally:
        daemon.stop()


def test_reconciliation_and_offer_preserve_the_durable_effective_scope(tmp_path: Path) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        registered = _register(daemon)
        with pytest.raises(QueueConflictError, match="reconciliation facts"):
            _view(daemon).reconcile(
                registered.session_id,
                registered.coordinator_epoch,
                expected=replace(registered, inventory_revision="different"),
            )
        with pytest.raises(QueueConflictError, match="effective scope"):
            _view(daemon).publish_offer(
                replace(_offer(registered.session_id, registered.coordinator_epoch), pools=("other",)),
                idempotency_key="offer-1",
            )
    finally:
        daemon.stop()


def test_current_v1_roots_migrate_additively_without_losing_admission_tables(tmp_path: Path) -> None:
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
            assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'managed_admissions'").fetchone()
            assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'agent_sessions'").fetchone()
    finally:
        daemon.stop()
