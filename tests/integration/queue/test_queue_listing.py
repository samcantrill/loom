"""The public CLI and client share one authenticated admission-summary read."""

import io
import json
import os

import pytest

from loom.cli.main import main
from loom.coordinator import CoordinatorClient, RunRequest
from tests.integration.mcp.test_stdio import _coordinator
from tests.integration.queue.test_preparation_operations import _request

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("https", [False, True])
def test_selected_queue_through_native_transport(tmp_path, monkeypatch, https):
    with _coordinator(tmp_path, https=https) as (service, daemon, deployment):
        if https:
            monkeypatch.setenv("LOOM_DEPLOYMENT", deployment[1])
            client = CoordinatorClient.from_connection_file(tmp_path / "client.json")
            flags = []
            principal = "client"
        else:
            monkeypatch.setenv("LOOM_DEPLOYMENT", "/missing/ignored-by-explicit-option")
            client = CoordinatorClient.from_unix_socket(service.daemon.endpoint)
            flags = ["--endpoint", str(service.daemon.endpoint)]
            principal = f"uid:{os.getuid()}"

        with client:
            assert client.list_queue()["admissions"] == []
            request = RunRequest(_request(), "summary-test")
            client.start_run(request)
            result = daemon.wait_operation(request.preparation.operation_id, timeout=90).operation
            assert result.state == "applied", result
            daemon._wait("summary-test", timeout_seconds=60)

            def no_detail(*args, **kwargs):
                pytest.fail("listing attempted detailed owner reads")

            monkeypatch.setattr(daemon, "admission", no_detail)
            monkeypatch.setattr(daemon, "status", no_detail)
            assert client.list_queue(principal="another-principal", include_terminal=True)["admissions"] == []
            stdout, stderr = io.StringIO(), io.StringIO()
            code = main(["queue", "list", *flags, "-u", principal, "--all", "--format", "json"],
                        stdout=stdout, stderr=stderr)
            assert code == 0, (stdout.getvalue(), stderr.getvalue())
            envelope = json.loads(stdout.getvalue())
            assert envelope["schema_version"] == "loom.cli.queue.list.v1"
            rows = envelope["result"]["admissions"]
            assert {r["admitted_by"] for r in rows} == {principal}
            assert "summary-test" in {r["queue_item_id"] for r in rows}
            assert len(rows) >= 2  # target and its preparation child


def test_invalid_shell_selection_names_failing_deployment(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setenv("LOOM_DEPLOYMENT", str(missing))
    output = io.StringIO()
    assert main(["queue", "list", "--format", "json"], stdout=output, stderr=io.StringIO()) != 0
    assert str(missing) in json.loads(output.getvalue())["error"]["message"]


def test_stale_deployment_reports_actual_and_expected_coordinator(tmp_path, monkeypatch):
    with _coordinator(tmp_path, https=True) as (_, daemon, deployment):
        path = tmp_path / "client.json"
        connection = json.loads(path.read_text())
        connection["expected_coordinator_id"] = "previous-coordinator"
        path.write_text(json.dumps(connection))
        monkeypatch.setenv("LOOM_DEPLOYMENT", deployment[1])
        output = io.StringIO()
        assert main(["queue", "list", "--format", "json"], stdout=output, stderr=io.StringIO()) != 0
        error = json.loads(output.getvalue())["error"]
        assert deployment[1] in error["message"]
        assert error["context"]["expected_coordinator_id"] == "previous-coordinator"
        assert error["context"]["observed_coordinator_id"] == daemon._coordinator_id
