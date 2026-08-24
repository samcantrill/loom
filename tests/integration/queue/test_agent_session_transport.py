"""Real loopback mutual-TLS evidence for the restricted agent protocol."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import ssl
import sqlite3
import subprocess
from collections.abc import Mapping
from time import monotonic, sleep

import pytest

from loom.queue import (
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
    _decode,
)
from loom.queue.agent_sessions import (
    AgentOffer,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    AgentSessionState,
    TransportPrincipalPolicy,
)
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.serialization import PlainData


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


def _credentials(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir()
    _run(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "ca.key",
        "-out",
        "ca.crt",
        "-subj",
        "/CN=loom-test-ca",
        "-days",
        "1",
        cwd=tmp_path,
    )
    for name, subject in (
        ("server", "/CN=localhost"),
        ("agent", "/CN=agent"),
        ("other", "/CN=other"),
    ):
        _run(
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            f"{name}.key",
            "-out",
            f"{name}.csr",
            "-subj",
            subject,
            cwd=tmp_path,
        )
        extension = (
            "subjectAltName=DNS:localhost"
            if name == "server"
            else "extendedKeyUsage=clientAuth"
        )
        (tmp_path / f"{name}.ext").write_text(extension, encoding="utf-8")
        _run(
            "x509",
            "-req",
            "-in",
            f"{name}.csr",
            "-CA",
            "ca.crt",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-out",
            f"{name}.crt",
            "-days",
            "1",
            "-sha256",
            "-extfile",
            f"{name}.ext",
            cwd=tmp_path,
        )
    return {name: tmp_path / name for name in ("ca", "server", "agent", "other")}


def _fingerprint(certificate: Path) -> str:
    return hashlib.sha256(
        ssl.PEM_cert_to_DER_cert(certificate.read_text(encoding="utf-8"))
    ).hexdigest()


def _policy() -> AgentPolicyConfig:
    return AgentPolicyConfig(
        agents=(
            AgentPrincipalPolicy(
                "agent-credential",
                "agent-principal",
                "agent-a",
                ("default",),
                ("python",),
            ),
        )
    )


def _request(handshake: Mapping[str, object], agent_root_id: str) -> AgentRegistration:
    return AgentRegistration(
        idempotency_key="register-1",
        coordinator_id=str(handshake["coordinator_id"]),
        coordinator_epoch=str(handshake["coordinator_epoch"]),
        agent_root_id=agent_root_id,
        config_revision="config-1",
        inventory_revision="inventory-1",
        availability_revision="availability-1",
        declared_pools=("default",),
        declared_capabilities=("python",),
    )


def _remote_agent_root(tmp_path: Path, name: str = "remote-owner") -> Path:
    root = tmp_path / name / "agent"
    LocalDaemon.initialize_agent_root(root)
    return root


def _sqlite_dump(path: Path) -> tuple[str, ...]:
    with sqlite3.connect(path) as conn:
        return tuple(conn.iterdump())


def test_protocol_codec_rejects_duplicate_nonfinite_deep_and_oversized_json() -> None:
    with pytest.raises(QueueServiceError, match="JSON is invalid"):
        _decode(b'{"value":1,"value":2}')
    with pytest.raises(QueueServiceError, match="JSON is invalid"):
        _decode(b'{"value":NaN}')
    with pytest.raises(QueueServiceError, match="deeply nested"):
        _decode(b'{"a":{"b":{"c":{"d":{"e":{"f":{"g":{"h":{"i":1}}}}}}}}}')
    with pytest.raises(QueueServiceError, match="too large"):
        _decode(b"{" + b" " * 65_536 + b"}")


def test_loopback_mtls_derives_credential_and_rechecks_live_policy(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent-root",
        run_store_root=tmp_path / "runs",
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
            ),
            idempotency_key="offer-1",
        )
        connection = client._connection
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(
                client.wait_for_work,
                registered.session_id,
                registered.availability_revision,
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
                ),
                idempotency_key="offer-rotated-credential",
            )
            assert (
                rotated.wait_for_work(
                    resumed.session_id,
                    resumed.availability_revision,
                    poll_id="poll-rotated-credential",
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
            client.retire_clean(
                resumed.session_id, idempotency_key="retire-first"
            )
        with sqlite3.connect(journal) as conn:
            assert conn.execute(
                "SELECT retirement_secret FROM agent_sessions_local WHERE session_id = ?",
                (resumed.session_id,),
            ).fetchone()[0] == first_secret
            assert conn.execute(
                "SELECT result_json FROM agent_mutation_intents "
                "WHERE operation = 'retire' AND operation_id = 'retire-first'"
            ).fetchone()[0] is None
        with sqlite3.connect(config.control_database) as conn:
            assert conn.execute(
                "SELECT state FROM agent_sessions WHERE session_id = ?",
                (resumed.session_id,),
            ).fetchone()[0] == AgentSessionState.RETIRED_CLEAN.value

        client.retire_clean(resumed.session_id, idempotency_key="retire-first")
        with sqlite3.connect(journal) as conn:
            assert conn.execute(
                "SELECT retirement_secret FROM agent_registration_intents WHERE operation_id = ?",
                (request.idempotency_key,),
            ).fetchone()[0] is None
            assert conn.execute(
                "SELECT retirement_secret FROM agent_sessions_local WHERE session_id = ?",
                (resumed.session_id,),
            ).fetchone()[0] is None
            assert conn.execute(
                "SELECT COUNT(*) FROM agent_retirement_proofs_local"
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM agent_mutation_intents WHERE operation = 'retire'"
            ).fetchone()[0] == 0
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


def test_loopback_rejects_unmapped_client_certificate_and_wrong_service_ca(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(
            TransportPrincipalPolicy("client-credential", "client-principal", "client"),
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        agent_policy=policy,
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
                ): "agent-credential"
            },
        ),
    )
    server.start()
    rejected = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["other"].with_suffix(".crt"),
            credentials["other"].with_suffix(".key"),
        )
    )
    wrong_ca = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["server"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
        )
    )
    wrong_service = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://127.0.0.1:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
        )
    )
    try:
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            rejected.handshake()
        with pytest.raises(QueueServiceError, match="indeterminate"):
            wrong_ca.handshake()
        with pytest.raises(QueueServiceError, match="indeterminate"):
            wrong_service.handshake()
    finally:
        rejected.close()
        wrong_ca.close()
        wrong_service.close()
        server.stop()
        daemon.stop()


def test_loopback_exposes_client_and_operator_views_only_to_configured_roles(
    tmp_path: Path,
) -> None:
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(
            TransportPrincipalPolicy("client-credential", "client-principal", "client"),
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        agent_policy=policy,
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
                ): "client-credential",
            },
        ),
    )
    server.start()
    client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["other"].with_suffix(".crt"),
            credentials["other"].with_suffix(".key"),
        )
    )
    agent = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
        )
    )
    try:
        handshake = client.handshake(role="client")
        assert handshake["role"] == "client"
        assert handshake["capabilities"] in (
            ("authenticated-application-v1",),
            ["authenticated-application-v1"],
        )
        remote_status = client.call_application("client", "status", {})
        direct_status = (
            daemon.client_view(
                LocalDaemonPrincipal(
                    "client-principal", LocalDaemonRole.CLIENT, "client-credential"
                )
            )
            .status()
            .to_dict()
        )
        assert remote_status["coordinator_id"] == direct_status["coordinator_id"]
        assert remote_status["coordinator_epoch"] == direct_status["coordinator_epoch"]
        assert remote_status["admissions"] in ((), [])
        assert direct_status["admissions"] == []
        daemon.replace_agent_policy(
            AgentPolicyConfig(revision="policy-2", agents=policy.agents)
        )
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            client.handshake(role="client")
        daemon.replace_agent_policy(
            AgentPolicyConfig(
                revision="policy-3",
                agents=policy.agents,
                principals=(
                    TransportPrincipalPolicy(
                        "client-credential", "operator-principal", "operator"
                    ),
                ),
            )
        )
        operator_handshake = client.handshake(role="operator")
        assert operator_handshake["role"] == "operator"
        remote_operator = client.call_application("operator", "status", {})
        direct_operator = (
            daemon.operator_view(
                LocalDaemonPrincipal(
                    "operator-principal",
                    LocalDaemonRole.OPERATOR,
                    "client-credential",
                )
            )
            .status()
            .to_dict()
        )
        assert remote_operator["coordinator_id"] == direct_operator["coordinator_id"]
        assert client.call_application("operator", "reconcile", {})["admissions"] in (
            (),
            [],
        )
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            agent.handshake(role="client")
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            agent.call_application("client", "status", {})
    finally:
        client.close()
        agent.close()
        server.stop()
        daemon.stop()
