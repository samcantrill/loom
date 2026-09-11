"""The CLI uses native preparation through either coordinator connection."""

from dataclasses import replace
import json
from pathlib import Path
import sqlite3

import pytest

from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonSocketServer
from loom.queue.agent_session_transport import (
    AgentTlsServerConfig,
    LocalDaemonAgentHttpServer,
)
from loom.queue.deployment import load_coordinator_service_config
from tests.integration.queue.test_preparation_operations import (
    _cli_result,
    _request,
    _service,
)
from tests.support.mutual_tls import certificate_fingerprint, mutual_tls_credentials


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("transport", ("unix", "https"))
def test_cli_prepare_observe_guard_submit_and_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transport: str,
) -> None:
    service = _service(tmp_path)
    credentials = None
    if transport == "https":
        credentials = mutual_tls_credentials(tmp_path / "tls")
        config_path = tmp_path / "coordinator.json"
        authored = json.loads(config_path.read_text())
        authored["agent_policy"]["principals"] = [
            {
                "credential_id": "client-credential",
                "principal_id": "client",
                "role": "client",
                "actions": [],
                "agent_ids": [],
                "pools": [],
            }
        ]
        config_path.write_text(json.dumps(authored))
        service = load_coordinator_service_config(config_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    if credentials is None:
        server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
        server.start()
        connection = ("--endpoint", str(service.daemon.endpoint))
    else:
        server = LocalDaemonAgentHttpServer(
            daemon,
            AgentTlsServerConfig(
                "localhost",
                0,
                credentials["server"].with_suffix(".crt"),
                credentials["server"].with_suffix(".key"),
                credentials["ca"].with_suffix(".crt"),
                {
                    certificate_fingerprint(
                        credentials["other"].with_suffix(".crt")
                    ): "client-credential"
                },
            ),
        )
        server.start()
        path = tmp_path / "client.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "loom.coordinator-client",
                    "transport": {
                        "kind": "https",
                        "url": f"https://localhost:{server.port}",
                        "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
                        "certificate_path": str(
                            credentials["other"].with_suffix(".crt")
                        ),
                        "private_key_path": str(
                            credentials["other"].with_suffix(".key")
                        ),
                    },
                }
            )
        )
        path.chmod(0o600)
        connection = ("--connection", str(path))
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request().to_dict()))
    try:
        accepted = _cli_result(
            "daemon-prepare", *connection, "--request", str(request_path)
        )["result"]
        assert accepted["operation_id"] == "prepare-1"
        assert accepted["state"] == "pending"
        observed = _cli_result(
            "daemon-operation-wait", *connection, "prepare-1", "--timeout", "25"
        )["result"]
        prepared = observed["operation"]
        assert prepared["state"] == "applied"
        assert prepared["result"]["preflight_status"] == "PASS"
        coordinator_id = prepared["result"]["coordinator_id"]
        guarded = (*connection, "--expected-coordinator-id", coordinator_id)
        assert (
            _cli_result("daemon-operation", *guarded, "prepare-1")["result"] == prepared
        )
        reads = []
        original = daemon.operation

        def counted_read(operation_id):
            reads.append(operation_id)
            return original(operation_id)

        monkeypatch.setattr(daemon, "operation", counted_read)
        rejected = _cli_result(
            "daemon-operation",
            *connection,
            "--expected-coordinator-id",
            "different-coordinator",
            "prepare-1",
            expected_exit=6,
        )
        assert rejected["ok"] is False
        assert reads == []
        monkeypatch.setattr(daemon, "operation", original)
        receipt = prepared["result"]["prepared_run"]
        assert (
            len(_cli_result("daemon-admissions", *connection)["result"]["admissions"])
            == 1
        )
        admitted = _cli_result(
            "daemon-submit", *guarded, "cli-target", receipt["run_uri"]
        )["result"]
        assert admitted["run_uri"] == receipt["run_uri"]
        terminal = _cli_result(
            "daemon-wait", *guarded, "cli-target", "--timeout", "25"
        )["result"]
        assert terminal["state"] == "SUCCEEDED"

        request_path.write_text(
            json.dumps(
                replace(
                    _request(),
                    operation_id="cancel-prepare",
                    run_name="cancel-target",
                ).to_dict()
            )
        )
        assert daemon._preparations._reconcile_lock.acquire(timeout=25)
        try:
            _cli_result("daemon-prepare", *guarded, "--request", str(request_path))
            cancelled = _cli_result(
                "daemon-cancel-preparation", *guarded, "cancel-prepare"
            )["result"]
            assert cancelled["state"] == "pending"
        finally:
            daemon._preparations._reconcile_lock.release()
        cancelled = _cli_result(
            "daemon-operation-wait", *guarded, "cancel-prepare", "--timeout", "25"
        )["result"]["operation"]
        assert cancelled["state"] == "cancelled"
        assert cancelled["result"]["preparation_admission_id"] is None
        assert not (service.daemon.run_store_root / "cancel-target").exists()
        staged = replace(
            _request(),
            source=replace(_request().source, mode="staged"),
            operation_id="staged-prepare",
            run_name="staged-target",
        )
        request_path.write_text(json.dumps(staged.to_dict()))
        rejected = _cli_result(
            "daemon-prepare", *guarded, "--request", str(request_path), expected_exit=6
        )
        assert rejected["ok"] is False
        with sqlite3.connect(service.daemon.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM preparation_operations").fetchone()[
                    0
                ]
                == 2
            )
        assert not (service.daemon.run_store_root / "staged-target").exists()
    finally:
        server.stop()
        daemon.stop()
