"""End-to-end smoke tests for ``loom authority`` lifecycle commands."""

from __future__ import annotations

import io
import json
import socket
from pathlib import Path

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from loom.cli.main import main
from loom.pipeline.stores import (
    WorkspaceIdentity,
    create_authority_client,
    path_to_run_uri,
)


pytestmark = [pytest.mark.e2e, pytest.mark.optional_dependency]


def test_authority_supervisor_cli_lifecycle_smoke(tmp_path: Path) -> None:
    port = _free_port()
    restart_port = _free_port()
    workspace = tmp_path / "workspace"

    try:
        start_stdout = io.StringIO()
        assert (
            main(
                [
                    "authority",
                    "start",
                    "--use-workspace-default",
                    "--workspace-root",
                    str(workspace),
                    "--workspace-id",
                    "workspace-a",
                    "--port",
                    str(port),
                    "--format",
                    "json",
                ],
                stdout=start_stdout,
            )
            == 0
        )
        start_payload = json.loads(start_stdout.getvalue())
        assert start_payload["ok"] is True
        assert start_payload["result"]["readiness"] == "ready"

        status_stdout = io.StringIO()
        assert (
            main(
                [
                    "authority",
                    "status",
                    "--workspace-root",
                    str(workspace),
                    "--format",
                    "json",
                ],
                stdout=status_stdout,
            )
            == 0
        )
        status_payload = json.loads(status_stdout.getvalue())
        assert status_payload["result"]["process_state"] == "running"
        assert status_payload["result"]["registry_status"] == "valid"

        restart_stdout = io.StringIO()
        assert (
            main(
                [
                    "authority",
                    "restart",
                    "--use-workspace-default",
                    "--workspace-root",
                    str(workspace),
                    "--workspace-id",
                    "workspace-a",
                    "--port",
                    str(restart_port),
                    "--format",
                    "json",
                ],
                stdout=restart_stdout,
            )
            == 0
        )
        restart_payload = json.loads(restart_stdout.getvalue())
        assert restart_payload["result"]["readiness"] == "ready"
        assert restart_payload["result"]["command"] == "restart"
        assert restart_payload["result"]["process_state"] == "running"
        assert (
            restart_payload["result"]["service_generation"]
            != start_payload["result"]["service_generation"]
        )
        assert restart_payload["result"]["process_state"] == "running"
        assert restart_payload["result"]["pid"] != start_payload["result"]["pid"]

        doctor_stdout = io.StringIO()
        assert (
            main(
                [
                    "authority",
                    "doctor",
                    "--workspace-root",
                    str(workspace),
                    "--format",
                    "json",
                ],
                stdout=doctor_stdout,
            )
            == 0
        )
        assert json.loads(doctor_stdout.getvalue())["ok"] is True
        active_endpoint = restart_payload["result"]["endpoint"]
        authority_client = create_authority_client(
            {
                "backend_kind": "managed_service",
                "deployment_profile": "managed_service",
                "endpoint": active_endpoint,
                "workspace_id": "workspace-a",
            }
        )
        workspace_response = authority_client.create_workspace(
            WorkspaceIdentity(
                workspace_id="workspace-a",
                root_uri=workspace.resolve().as_uri(),
            ),
            request_id="e2e-workspace-create",
            service_generation=restart_payload["result"]["service_generation"],
        )
        assert workspace_response.result is not None
        assert workspace_response.result.workspace is not None

        from loom.pipeline.execution import create_authority_backed_serial_run_store
        from loom.pipeline.stores import (
            AuthorityConfig,
            AuthorityBackendKind,
            AuthorityDeploymentProfile,
        )
        from tests.support.historical_offline_evidence import complete_manifest

        selected_authority = AuthorityConfig(
            backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
            endpoint=active_endpoint,
            workspace_id="workspace-a",
        )
        run_uri = path_to_run_uri(tmp_path / "runs" / "online-authority")
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs", authority_config=selected_authority
        )
        from loom.pipeline.status import RunStatus

        store.create_run(run_uri)
        store.authority_store.transition_run(
            run_uri, from_status=RunStatus.CREATED, to_status=RunStatus.RUNNING
        )
        store.authority_store.transition_run(
            run_uri, from_status=RunStatus.RUNNING, to_status=RunStatus.SUCCEEDED
        )
        assert store.authority_store.snapshot(run_uri).status.value == "SUCCEEDED"

        manifest = complete_manifest(tmp_path)
        offline_run_uri = manifest.run_uri
        manifest_file = tmp_path / "historical-evidence.json"
        manifest_file.write_text(json.dumps(manifest.to_dict()))
        manifest_path = str(manifest_file)
        import_stdout = io.StringIO()
        assert (
            main(
                [
                    "authority",
                    "import-offline",
                    manifest_path,
                    "--authority-backend",
                    "managed_service",
                    "--authority-profile",
                    "managed_service",
                    "--authority-endpoint",
                    active_endpoint,
                    "--authority-workspace",
                    "workspace-a",
                    "--format",
                    "json",
                ],
                stdout=import_stdout,
            )
            == 0
        )
        import_payload = json.loads(import_stdout.getvalue())
        assert import_payload["ok"] is True
        assert import_payload["result"]["run_uri"] == offline_run_uri
        assert import_payload["result"]["status"] == "SUCCEEDED"
        assert import_payload["result"]["imported_stage_count"] == 2

    finally:
        stop_stdout = io.StringIO()
        main(
            [
                "authority",
                "stop",
                "--use-workspace-default",
                "--workspace-root",
                str(workspace),
                "--format",
                "json",
            ],
            stdout=stop_stdout,
        )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
