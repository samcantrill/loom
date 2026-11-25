"""Agent registration, mutual TLS identity, and lost registration reply replay."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
from collections.abc import Mapping
from threading import Event
from time import monotonic, sleep
from typing import Any, cast

import pytest

import loom.queue.deployment as queue_deployment
from loom.queue import (
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)
from loom.queue._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
    ResidentExecutionProfile,
    ResidentProfileDescriptor,
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
)
from loom.queue.deployment import (
    OutboundAgentRegistrationConfig,
    OutboundAgentServiceConfig,
    run_outbound_agent_service,
)
from loom.queue.agent_sessions import (
    AgentOffer,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentSessionState,
)
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.serialization import PlainData
from tests.support.mutual_tls import (
    certificate_fingerprint as _fingerprint,
    mutual_tls_credentials as _credentials,
)
from tests.support.agent_sessions import (
    _shutdown_detached_remote_supervisors as _shutdown_detached_remote_supervisors,
    _fresh_remote_agent_root,
    _local_launch_profile,
    _policy,
    _provider_descriptors,
    _remote_agent_root,
    _request,
    _slurm_bootstrap_profile,
    _sqlite_dump,
)


@pytest.mark.parametrize("old_version", ["5", "6"])
def test_agent_client_rejects_an_old_protocol_without_compatibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_version: str
) -> None:
    client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            "https://localhost:1",
            tmp_path / "ca.crt",
            tmp_path / "agent.crt",
            tmp_path / "agent.key",
        )
    )

    def old_handshake(
        operation: str,
        value: Mapping[str, PlainData],
        *,
        role: str = "agent",
    ) -> Mapping[str, PlainData]:
        _ = operation, value, role
        return {
            "protocol_version": old_version,
            "capabilities": [f"agent-sessions-v{old_version}"],
            "coordinator_id": "coordinator-1",
            "coordinator_epoch": "epoch-1",
            "role": "agent",
        }

    monkeypatch.setattr(client, "_call", old_handshake)
    with pytest.raises(QueueServiceError, match="hard cut-over"):
        client.handshake()


@pytest.mark.parametrize("ceiling", [1, 2])
@pytest.mark.parametrize("missing", ["concurrent-resident-assignments-v1", "agent-control-wait-v1", "remote-stage-execution-v4"])
def test_outbound_service_rejects_missing_current_capability_before_offering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ceiling: int, missing: str
) -> None:
    profile = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "resident", "1", "project", "environment", "executor"
        ),
        tmp_path,
        Path(sys.executable),
    )
    config = AgentTlsClientConfig(
        "https://localhost:1",
        tmp_path / "ca.crt",
        tmp_path / "agent.crt",
        tmp_path / "agent.key",
        _fresh_remote_agent_root(tmp_path),
        resident_profiles=(profile,),
        max_concurrent_assignments=ceiling,
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(config)
    client = LocalDaemonAgentHttpClient(config)
    stop = Event()
    calls = []

    def old_coordinator(operation, value, *, role="agent"):
        calls.append(operation)
        stop.set()
        return {
            "protocol_version": "13",
            "capabilities": [capability for capability in (
                "agent-sessions-v12",
                REMOTE_EXECUTION_CAPABILITY,
                REGULAR_FILE_RELAY_CAPABILITY,
                "concurrent-resident-assignments-v1",
                "agent-control-wait-v1",
            ) if capability != missing] + (["remote-stage-execution-v3"] if missing == REMOTE_EXECUTION_CAPABILITY else []),
            "coordinator_id": "coordinator-1",
            "coordinator_epoch": "epoch-1",
            "role": role,
        }

    monkeypatch.setattr(client, "_call", old_coordinator)
    refusal = (
        "protocol is unsupported"
        if missing == REMOTE_EXECUTION_CAPABILITY
        else f"upgrade required.*{missing}"
    )
    with pytest.raises(QueueServiceError, match=refusal):
        client.handshake()
    stop.clear()
    calls.clear()
    monkeypatch.setattr(
        queue_deployment, "_open_outbound_agent", lambda *args, **kwargs: client
    )
    run_outbound_agent_service(
        OutboundAgentServiceConfig(
            config,
            OutboundAgentRegistrationConfig(
                "config-1", "inventory-1", "availability-1", ("default",), ("python",)
            ),
            0.01,
            tmp_path / "agent.yaml",
            "immutable",
            "active",
        ),
        stop=stop,
    )
    assert calls == ["handshake"]
    with sqlite3.connect(cast(Path, config.agent_root) / "control.sqlite") as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM agent_sessions_local").fetchone()[0] == 0
        )


@pytest.mark.parametrize("value", [None, True, 0, -1, 1.5, "2", 1025])
def test_programmatic_agent_rejects_invalid_assignment_ceiling(
    tmp_path: Path, value: Any
) -> None:
    with pytest.raises(QueueServiceError, match="max_concurrent_assignments"):
        AgentTlsClientConfig(
            "https://localhost",
            tmp_path / "ca",
            tmp_path / "cert",
            tmp_path / "key",
            max_concurrent_assignments=value,
        )


def test_programmatic_agent_ceiling_fingerprint_and_slurm_boundary(
    tmp_path: Path,
) -> None:
    from loom.queue.agent_session_transport import _agent_active_fingerprint

    base = AgentTlsClientConfig(
        "https://localhost", tmp_path / "ca", tmp_path / "cert", tmp_path / "key"
    )
    assert _agent_active_fingerprint(base) == _agent_active_fingerprint(
        replace(base, max_concurrent_assignments=1)
    )
    assert _agent_active_fingerprint(base) != _agent_active_fingerprint(
        replace(base, max_concurrent_assignments=2)
    )
    assert (
        replace(base, max_concurrent_assignments=1024).max_concurrent_assignments
        == 1024
    )
    slurm = replace(
        base,
        agent_root=tmp_path / "agent",
        slurm_profiles=(_slurm_bootstrap_profile(tmp_path),),
    )
    assert slurm.max_concurrent_assignments == 1
    with pytest.raises(QueueServiceError, match="unsupported with slurm_profiles"):
        replace(slurm, max_concurrent_assignments=2)


@pytest.mark.parametrize("old_version", [5, 6])
def test_agent_open_rejects_an_old_root_without_migration(
    tmp_path: Path, old_version: int
) -> None:
    root = tmp_path / f"version-{old_version}-agent"
    LocalDaemon.initialize_agent_root(root)
    with sqlite3.connect(root / "control.sqlite") as conn:
        conn.execute(f"PRAGMA user_version = {old_version}")

    with pytest.raises(QueueServiceError, match="schema is unsupported"):
        LocalDaemonAgentHttpClient(
            AgentTlsClientConfig(
                "https://localhost:1",
                tmp_path / "ca.crt",
                tmp_path / "agent.crt",
                tmp_path / "agent.key",
                agent_root=root,
            )
        )


def test_loopback_mtls_derives_credential_and_rechecks_live_policy(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent-root",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=_local_launch_profile(),
        agent_policy=_policy(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost",
            0,
            credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"),
            credentials["ca"].with_suffix(".crt"),
            {
                _fingerprint(
                    credentials["agent"].with_suffix(".crt")
                ): "agent-credential",
                _fingerprint(
                    credentials["other"].with_suffix(".crt")
                ): "agent-credential-2",
            },
        ),
    )
    server.start()
    remote_agent_root = _remote_agent_root(tmp_path)
    client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
            remote_agent_root,
        )
    )
    try:
        handshake = dict(client.handshake())
        assert set(handshake) == {
            "protocol_version",
            "capabilities",
            "coordinator_id",
            "coordinator_epoch",
            "role",
        }
        request = _request(handshake, client.agent_root_id)
        registered = client.register(request)
        with daemon._connection() as conn:
            verifier = conn.execute(
                "SELECT retirement_verifier FROM agent_sessions WHERE session_id = ?",
                (registered.session_id,),
            ).fetchone()[0]
        direct_replay = (
            daemon.agent_view(  # direct and HTTP share transition/idempotency state
                LocalDaemonPrincipal(
                    "agent-principal", LocalDaemonRole.AGENT, "agent-credential"
                )
            ).register(replace(request, retirement_verifier=str(verifier)))
        )
        assert direct_replay.session_id == registered.session_id
        changed = replace(
            request, config_revision="changed", retirement_verifier=str(verifier)
        )
        with pytest.raises(QueueConflictError, match="protocol conflict"):
            client._call("register", changed.value())
        with pytest.raises(QueueConflictError, match="different content"):
            daemon.agent_view(
                LocalDaemonPrincipal(
                    "agent-principal", LocalDaemonRole.AGENT, "agent-credential"
                )
            ).register(changed)
        with pytest.raises(QueueConflictError, match="protocol conflict"):
            client._call(
                "reconcile",
                {
                    "expected": replace(
                        registered, agent_id="body-selected-agent"
                    ).value(),
                    "coordinator_epoch": registered.coordinator_epoch,
                    "idempotency_key": "reconcile-forged-agent",
                },
            )
        client.publish_offer(
            AgentOffer(
                registered.session_id,
                registered.coordinator_epoch,
                "config-1",
                "inventory-1",
                "availability-1",
                1,
                1,
                10,
                _provider_descriptors("cpu", "memory"),
            ),
            idempotency_key="offer-1",
        )
        connection = client._connection
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(
                client.wait_for_work,
                registered.session_id,
                registered.availability_revision,
                sequence=1,
                wait_timeout_ms=1_000,
            )
            deadline = monotonic() + 2
            while monotonic() < deadline:
                with daemon._connection() as conn:
                    active = conn.execute(
                        "SELECT active FROM agent_poll_state "
                        "WHERE session_id = ? AND sequence = 1",
                        (registered.session_id,),
                    ).fetchone()
                if active is not None and bool(active[0]):
                    break
                sleep(0.01)
            else:
                pytest.fail("loopback work poll did not become active")
            daemon.replace_agent_policy(AgentPolicyConfig(revision="policy-2"))
            with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
                pending.result(timeout=2)
        assert connection is not None  # policy was rechecked on the held TLS request
        assert client._connection is None  # rejected requests fence connection framing
        client.close()

        daemon.replace_agent_policy(
            AgentPolicyConfig(
                revision="policy-3",
                agents=(
                    AgentPrincipalPolicy(
                        "agent-credential-2",
                        "agent-principal",
                        "agent-a",
                        ("default",),
                        ("python",),
                    ),
                ),
            )
        )
        rotated = LocalDaemonAgentHttpClient(
            AgentTlsClientConfig(
                f"https://localhost:{server.port}",
                credentials["ca"].with_suffix(".crt"),
                credentials["other"].with_suffix(".crt"),
                credentials["other"].with_suffix(".key"),
                remote_agent_root,
            )
        )
        try:
            current = rotated.handshake()
            resumed = rotated.reconcile(
                registered.session_id,
                str(current["coordinator_epoch"]),
                idempotency_key="reconcile-rotated-credential",
            )
            assert resumed.policy_revision == "policy-3"
            # Reauthorization does not settle a poll rejected by the old policy.
            # Resolve its exact retained identity before advertising fresh work.
            rotated._resume_pending_poll(wait_timeout_ms=1_000)
            assert rotated._require_journal().pending_poll() is None
            assert rotated.resume_retained_work() == ()
            rotated.publish_offer(
                AgentOffer(
                    resumed.session_id,
                    resumed.coordinator_epoch,
                    resumed.config_revision,
                    resumed.inventory_revision,
                    resumed.availability_revision,
                    1,
                    1,
                    10,
                    _provider_descriptors("cpu", "memory"),
                ),
                idempotency_key="offer-rotated-credential",
            )
            assert (
                rotated.wait_for_work(
                    resumed.session_id,
                    resumed.availability_revision,
                    sequence=2,
                    wait_timeout_ms=10,
                )["result"]
                == "wait"
            )
        finally:
            rotated.close()
    finally:
        client.close()
        server.stop()
        daemon.stop()


def test_lost_registration_response_replays_into_remote_agent_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials = _credentials(tmp_path / "tls")
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "coordinator-agent",
        tmp_path / "runs",
        _local_launch_profile(),
        agent_policy=_policy(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, clock=lambda: "2020-01-01T00:00:00Z")
    daemon.start()
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost",
            0,
            credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"),
            credentials["ca"].with_suffix(".crt"),
            {
                _fingerprint(
                    credentials["agent"].with_suffix(".crt")
                ): "agent-credential"
            },
        ),
    )
    server.start()
    remote_agent_root = _remote_agent_root(tmp_path)
    journal = remote_agent_root / "control.sqlite"
    client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
            remote_agent_root,
        )
    )
    try:
        request = _request(client.handshake(), client.agent_root_id)
        original = client._call
        lose_once = {"register", "reconcile"}

        def lose_response(
            operation: str, value: Mapping[str, PlainData], *, role: str = "agent"
        ):
            result = original(operation, value, role=role)
            if operation in lose_once:
                lose_once.remove(operation)
                raise QueueServiceError("agent protocol outcome is indeterminate")
            return result

        monkeypatch.setattr(client, "_call", lose_response)
        with pytest.raises(QueueServiceError, match="indeterminate"):
            client.register(request)
        repaired = client.register(request)
        with sqlite3.connect(journal) as conn:
            persisted_request, first_secret = conn.execute(
                "SELECT request_json, retirement_secret FROM agent_registration_intents WHERE operation_id = ?",
                (request.idempotency_key,),
            ).fetchone()
            assert conn.execute(
                "SELECT result_json FROM agent_registration_intents WHERE operation_id = ?",
                (request.idempotency_key,),
            ).fetchone()[0]
            assert (
                conn.execute("SELECT session_id FROM agent_sessions_local").fetchone()[
                    0
                ]
                == repaired.session_id
            )
        assert first_secret is not None and len(str(first_secret)) == 64
        assert "retirement_verifier" in str(persisted_request)
        with sqlite3.connect(config.control_database) as conn:
            verifier = conn.execute(
                "SELECT retirement_verifier FROM agent_sessions WHERE session_id = ?",
                (repaired.session_id,),
            ).fetchone()[0]
        assert str(first_secret) not in str(verifier)
        assert config.agent_root is not None
        with sqlite3.connect(config.agent_root / "control.sqlite") as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM agent_sessions_local").fetchone()[0]
                == 0
            )

        daemon.stop()
        daemon.start()
        current = client.handshake()
        current_epoch = str(current["coordinator_epoch"])
        assert current_epoch != repaired.coordinator_epoch
        with pytest.raises(QueueServiceError, match="indeterminate"):
            client.reconcile(
                repaired.session_id,
                current_epoch,
                idempotency_key="reconcile-1",
            )
        resumed = client.reconcile(
            repaired.session_id,
            current_epoch,
            idempotency_key="reconcile-1",
        )
        assert resumed.coordinator_epoch == current_epoch
        with sqlite3.connect(journal) as conn:
            stored = conn.execute(
                "SELECT value_json FROM agent_sessions_local WHERE session_id = ?",
                (resumed.session_id,),
            ).fetchone()[0]
        assert current_epoch in str(stored)

        # Legacy authorization replay could persist a backward reconciliation.
        # A definitive rejection plus a fresh epoch observation retires it;
        # transport uncertainty must retain the exact intent for another replay.
        with pytest.raises(QueueConflictError):
            client.reconcile(
                resumed.session_id, repaired.coordinator_epoch,
                idempotency_key="legacy-backward-reconcile",
            )
        retained = client._require_journal().pending_reconciliations()
        assert len(retained) == 1

        def unavailable(operation, value, *, role="agent"):
            raise QueueServiceError("agent protocol outcome is indeterminate")

        monkeypatch.setattr(client, "_call", unavailable)
        with pytest.raises(QueueServiceError, match="indeterminate"):
            client._replay_pending_reconciliation()
        assert client._require_journal().pending_reconciliations() == retained
        monkeypatch.setattr(client, "_call", original)
        client._replay_pending_reconciliation()
        assert client._require_journal().pending_reconciliations() == ()
        assert client.active_session() == resumed
        monkeypatch.setattr(client, "_call", lose_response)

        replacement_root = _remote_agent_root(tmp_path, "replacement-owner")
        replacement = LocalDaemonAgentHttpClient(
            AgentTlsClientConfig(
                f"https://localhost:{server.port}",
                credentials["ca"].with_suffix(".crt"),
                credentials["agent"].with_suffix(".crt"),
                credentials["agent"].with_suffix(".key"),
                replacement_root,
            )
        )
        try:
            with pytest.raises(QueueServiceError, match="evidence is unavailable"):
                replacement.retire_clean(
                    repaired.session_id, idempotency_key="retire-lost-root"
                )
        finally:
            replacement.close()

        lose_once.add("retire")
        with pytest.raises(QueueServiceError, match="indeterminate"):
            client.retire_clean(resumed.session_id, idempotency_key="retire-first")
        with sqlite3.connect(journal) as conn:
            assert (
                conn.execute(
                    "SELECT retirement_secret FROM agent_sessions_local WHERE session_id = ?",
                    (resumed.session_id,),
                ).fetchone()[0]
                == first_secret
            )
            assert (
                conn.execute(
                    "SELECT result_json FROM agent_mutation_intents "
                    "WHERE operation = 'retire' AND operation_id = 'retire-first'"
                ).fetchone()[0]
                is None
            )
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute(
                    "SELECT state FROM agent_sessions WHERE session_id = ?",
                    (resumed.session_id,),
                ).fetchone()[0]
                == AgentSessionState.RETIRED_CLEAN.value
            )

        client.retire_clean(resumed.session_id, idempotency_key="retire-first")
        with sqlite3.connect(journal) as conn:
            assert (
                conn.execute(
                    "SELECT retirement_secret FROM agent_registration_intents WHERE operation_id = ?",
                    (request.idempotency_key,),
                ).fetchone()[0]
                is None
            )
            assert (
                conn.execute(
                    "SELECT retirement_secret FROM agent_sessions_local WHERE session_id = ?",
                    (resumed.session_id,),
                ).fetchone()[0]
                is None
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_retirement_proofs_local"
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM agent_mutation_intents WHERE operation = 'retire'"
                ).fetchone()[0]
                == 0
            )
        with sqlite3.connect(config.control_database) as conn:
            coordinator_dump = "\n".join(conn.iterdump())
        assert str(first_secret) not in coordinator_dump

        second = client.register(
            replace(
                _request(current, client.agent_root_id), idempotency_key="register-2"
            )
        )
        with sqlite3.connect(journal) as conn:
            second_secret = conn.execute(
                "SELECT retirement_secret FROM agent_registration_intents WHERE operation_id = 'register-2'"
            ).fetchone()[0]
        assert second_secret is not None and second_secret != first_secret
        proof = client._journal.fence_and_prove_empty(second.session_id)  # type: ignore[union-attr]
        before = _sqlite_dump(config.control_database)
        missing_secret = proof.value()
        del missing_secret["retirement_secret"]
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            client._call(
                "retire",
                {"proof": missing_secret, "idempotency_key": "retire-missing-secret"},
            )
        assert _sqlite_dump(config.control_database) == before
        with pytest.raises(QueueServiceError, match="proof is invalid"):
            daemon.agent_view(
                LocalDaemonPrincipal(
                    "agent-principal", LocalDaemonRole.AGENT, "agent-credential"
                )
            ).retire_clean(
                replace(proof, retirement_secret=str(first_secret)),
                idempotency_key="retire-old-secret",
            )
        assert _sqlite_dump(config.control_database) == before
        client.retire_clean(second.session_id, idempotency_key="retire-second")

        missing_root = tmp_path / "missing-agent-root"
        with pytest.raises(QueueServiceError, match="root is missing"):
            LocalDaemonAgentHttpClient(
                AgentTlsClientConfig(
                    f"https://localhost:{server.port}",
                    credentials["ca"].with_suffix(".crt"),
                    credentials["agent"].with_suffix(".crt"),
                    credentials["agent"].with_suffix(".key"),
                    missing_root,
                )
            )
        assert not missing_root.exists()
    finally:
        client.close()
        server.stop()
        daemon.stop()
