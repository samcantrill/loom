"""Real loopback mutual-TLS evidence for the restricted agent protocol."""

from __future__ import annotations

import hashlib
from pathlib import Path
import ssl
import subprocess
from collections.abc import Mapping

import pytest

from loom.queue import LocalDaemon, LocalDaemonConfig, LocalDaemonPrincipal, LocalDaemonRole
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
)
from loom.queue.agent_sessions import (
    AgentOffer,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    TransportPrincipalPolicy,
)
from loom.queue.errors import QueueServiceError


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


def _credentials(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir()
    _run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.crt", "-subj", "/CN=loom-test-ca", "-days", "1", cwd=tmp_path)
    for name, subject in (("server", "/CN=localhost"), ("agent", "/CN=agent"), ("other", "/CN=other")):
        _run("req", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{name}.key", "-out", f"{name}.csr", "-subj", subject, cwd=tmp_path)
        extension = "subjectAltName=DNS:localhost" if name == "server" else "extendedKeyUsage=clientAuth"
        (tmp_path / f"{name}.ext").write_text(extension, encoding="utf-8")
        _run("x509", "-req", "-in", f"{name}.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial", "-out", f"{name}.crt", "-days", "1", "-sha256", "-extfile", f"{name}.ext", cwd=tmp_path)
    return {name: tmp_path / name for name in ("ca", "server", "agent", "other")}


def _fingerprint(certificate: Path) -> str:
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate.read_text(encoding="utf-8"))).hexdigest()


def _policy() -> AgentPolicyConfig:
    return AgentPolicyConfig(
        agents=(AgentPrincipalPolicy("agent-credential", "agent-principal", "agent-a", ("default",), ("python",)),)
    )


def _request(handshake: Mapping[str, object]) -> AgentRegistration:
    return AgentRegistration(
        idempotency_key="register-1",
        coordinator_id=str(handshake["coordinator_id"]),
        coordinator_epoch=str(handshake["coordinator_epoch"]),
        config_revision="config-1",
        inventory_revision="inventory-1",
        availability_revision="availability-1",
        declared_capabilities=("python",),
    )


def test_loopback_mtls_derives_credential_and_rechecks_live_policy(tmp_path: Path) -> None:
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
            "localhost", 0, credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"), credentials["ca"].with_suffix(".crt"),
            {_fingerprint(credentials["agent"].with_suffix(".crt")): "agent-credential"},
        ),
    )
    server.start()
    client = LocalDaemonAgentHttpClient(
        AgentTlsClientConfig(
            f"https://localhost:{server.port}", credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"), credentials["agent"].with_suffix(".key"),
        )
    )
    try:
        handshake = dict(client.handshake())
        assert set(handshake) == {"protocol_version", "capabilities", "coordinator_id", "coordinator_epoch", "role"}
        registered = client.register(_request(handshake))
        direct_replay = daemon.agent_view(  # direct and HTTP share transition/idempotency state
            LocalDaemonPrincipal("agent-principal", LocalDaemonRole.AGENT, "agent-credential")
        ).register(_request(handshake))
        assert direct_replay.session_id == registered.session_id
        connection = client._connection
        daemon.replace_agent_policy(AgentPolicyConfig(revision="policy-2"))
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            client.publish_offer(
                AgentOffer(registered.session_id, registered.coordinator_epoch, "config-1", "inventory-1", "availability-1", 1, 1, 10),
                idempotency_key="offer-1",
            )
        assert client._connection is connection  # policy is rechecked on one TLS connection
    finally:
        client.close()
        server.stop()
        daemon.stop()


def test_loopback_rejects_unmapped_client_certificate_and_wrong_service_ca(tmp_path: Path) -> None:
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(TransportPrincipalPolicy("client-credential", "client-principal", "client"),),
    )
    config = LocalDaemonConfig(tmp_path / "coordinator", tmp_path / "agent-root", tmp_path / "runs", agent_policy=policy)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig("localhost", 0, credentials["server"].with_suffix(".crt"), credentials["server"].with_suffix(".key"), credentials["ca"].with_suffix(".crt"), {_fingerprint(credentials["agent"].with_suffix(".crt")): "agent-credential"}),
    )
    server.start()
    rejected = LocalDaemonAgentHttpClient(AgentTlsClientConfig(f"https://localhost:{server.port}", credentials["ca"].with_suffix(".crt"), credentials["other"].with_suffix(".crt"), credentials["other"].with_suffix(".key")))
    wrong_ca = LocalDaemonAgentHttpClient(AgentTlsClientConfig(f"https://localhost:{server.port}", credentials["server"].with_suffix(".crt"), credentials["agent"].with_suffix(".crt"), credentials["agent"].with_suffix(".key")))
    try:
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            rejected.handshake()
        with pytest.raises(QueueServiceError, match="indeterminate"):
            wrong_ca.handshake()
    finally:
        rejected.close()
        wrong_ca.close()
        server.stop()
        daemon.stop()


def test_loopback_exposes_client_status_only_to_configured_client_role(tmp_path: Path) -> None:
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(TransportPrincipalPolicy("client-credential", "client-principal", "client"),),
    )
    config = LocalDaemonConfig(tmp_path / "coordinator", tmp_path / "agent-root", tmp_path / "runs", agent_policy=policy)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost", 0, credentials["server"].with_suffix(".crt"), credentials["server"].with_suffix(".key"), credentials["ca"].with_suffix(".crt"),
            {
                _fingerprint(credentials["agent"].with_suffix(".crt")): "agent-credential",
                _fingerprint(credentials["other"].with_suffix(".crt")): "client-credential",
            },
        ),
    )
    server.start()
    client = LocalDaemonAgentHttpClient(AgentTlsClientConfig(f"https://localhost:{server.port}", credentials["ca"].with_suffix(".crt"), credentials["other"].with_suffix(".crt"), credentials["other"].with_suffix(".key")))
    agent = LocalDaemonAgentHttpClient(AgentTlsClientConfig(f"https://localhost:{server.port}", credentials["ca"].with_suffix(".crt"), credentials["agent"].with_suffix(".crt"), credentials["agent"].with_suffix(".key")))
    try:
        remote_status = client.call_application("client", "status", {})
        direct_status = daemon.client_view(
            LocalDaemonPrincipal("client-principal", LocalDaemonRole.CLIENT, "client-credential")
        ).status().to_dict()
        assert remote_status["coordinator_id"] == direct_status["coordinator_id"]
        assert remote_status["coordinator_epoch"] == direct_status["coordinator_epoch"]
        assert remote_status["admissions"] in ((), [])
        assert direct_status["admissions"] == []
        with pytest.raises(QueueServiceError, match="agent_protocol_rejected"):
            agent.call_application("client", "status", {})
    finally:
        client.close()
        agent.close()
        server.stop()
        daemon.stop()
