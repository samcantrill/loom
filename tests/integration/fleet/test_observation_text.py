"""Fleet text and JSON present the same host selection and native evidence."""

from contextlib import nullcontext
from copy import deepcopy
import io
import json
from types import SimpleNamespace

import pytest

from loom.cli.main import main
from loom.fleet import administration
from loom.fleet import ssh_operations
from loom.queue.operations import OperatorObservation
from tests.integration.fleet.test_configuration import inventory
from tests.integration.fleet.test_releases import bundle

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def invoke(command, path, *args):
    output, error = io.StringIO(), io.StringIO()
    code = main(
        ["fleet", command, "--fleet", str(path), *args], stdout=output, stderr=error
    )
    assert not error.getvalue(), error.getvalue()
    return code, output.getvalue()


def capture_acquisition(monkeypatch, module, name):
    acquire = getattr(module, name)
    reports = []

    def capture(*args, **kwargs):
        report = acquire(*args, **kwargs)
        reports.append(deepcopy(report))
        return report

    monkeypatch.setattr(module, name, capture)
    return reports


def test_fleet_status_displays_native_freshness_and_independent_declaration_failures(
    tmp_path, monkeypatch
):
    path = inventory(tmp_path)
    config = json.loads(path.read_text())
    config["agents"]["gpu02"] = dict(config["agents"]["gpu01"], host="second-ssh")
    path.write_text(json.dumps(config))
    when = "2026-06-05T12:00:00Z"

    def observation(name, value, freshness="current", reason=None):
        return OperatorObservation(
            name, when, "revision-3", freshness, "available", value, reason
        )

    def agent(name):
        if name == "gpu02":
            return observation(
                name, {"state": "ACTIVE"}, "retained", "observation_stale"
            )
        return observation(name, {"state": "ACTIVE"})

    operator = SimpleNamespace(
        observe_status=lambda: observation("coord-id", {"service_health": "healthy"}),
        observe_agent=agent,
    )
    monkeypatch.setattr(
        administration,
        "load_coordinator_connection_file",
        lambda _: SimpleNamespace(expected_coordinator_id="coord-id"),
    )
    monkeypatch.setattr(
        administration.CoordinatorOperatorClient,
        "from_connection_file",
        lambda *a, **kw: nullcontext(operator),
    )
    reports = capture_acquisition(monkeypatch, administration, "observe")
    monkeypatch.setenv("COLUMNS", "150")
    args = ("--connection", "selected", "--profile", "missing")
    code, output = invoke("status", path, *args)
    assert code == 0
    assert "Qualification: failed" in output
    for name, state, freshness in (
        ("coordinator", "healthy", "current"),
        ("gpu01", "ACTIVE", "current"),
        ("gpu02", "ACTIVE", "retained"),
    ):
        line = next(line for line in output.splitlines() if line.startswith(name))
        assert state in line and freshness in line
    assert "observation_stale" in output
    assert output.index("gpu02") < output.index(
        "Declaration: invalid_or_unavailable_native_declaration"
    )
    assert "Profile missing: unavailable_or_ambiguous_identity" in output
    assert "revision-3" not in output
    code, explained = invoke("status", path, *args, "--explain")
    assert code == 0
    for value in (
        when,
        "owner=coord-id",
        "revision=revision-3",
        "host_installation_unavailable",
        "host_storage_unavailable",
    ):
        assert value in explained

    code, original = invoke("status", path, *args, "--format", "json")
    assert code == 0 and json.loads(original) == reports[-1]
    monkeypatch.setenv("COLUMNS", "32")
    code, narrow = invoke("status", path)
    assert code == 0
    assert "HEALTH / SESSION: unknown" in narrow
    assert "operator_connection_not_selected" in narrow.replace("\n", "").replace(
        " ", ""
    )
    assert len(reports) == 4


@pytest.mark.parametrize("valid_release, expected_exit", [(True, 3), (False, 2)])
def test_preflight_distinguishes_failed_unavailable_and_verified_checks(
    tmp_path, monkeypatch, valid_release, expected_exit
):
    path = inventory(tmp_path)
    if valid_release:
        bundle(tmp_path)
    monkeypatch.setenv("COLUMNS", "180")
    reports = capture_acquisition(monkeypatch, administration, "observe")
    code, output = invoke("preflight", path)
    assert code == expected_exit
    rows = [line.split() for line in output.splitlines()]
    unavailable = next(
        i
        for i, row in enumerate(rows)
        if row[:3] == ["gpu01", "storage", "unavailable"]
    )
    passed = next(
        i
        for i, row in enumerate(rows)
        if row[:4] == ["coordinator", "credential", "files", "verified"]
    )
    assert unavailable < passed
    assert "host_storage_unavailable" in output
    assert "Local credential file permissions validated" in output
    if valid_release:
        assert (
            "Preflight: incomplete" in output
            and "Local bundle hashes validated for service-1" in output
        )
    else:
        failed = next(
            i
            for i, row in enumerate(rows)
            if row[:4] == ["fleet", "runtime", "release", "failed"]
        )
        assert failed < unavailable and "invalid_or_unavailable_release" in output
    code, explained = invoke("preflight", path, "--explain")
    assert code == expected_exit and "owner=local-files" in explained
    if valid_release:
        assert "descriptor sha256" in explained
    code, original = invoke("preflight", path, "--format", "json")
    assert code == expected_exit and json.loads(original) == reports[-1]
    assert len(reports) == 3


@pytest.mark.parametrize("reachable", [True, False])
def test_fleet_plan_preserves_host_actions_and_refusals(
    tmp_path, monkeypatch, reachable
):
    path = inventory(tmp_path)
    bundle(tmp_path)
    coordinator = tmp_path / "coordinator.yaml"
    declaration = json.loads(coordinator.read_text())
    declaration["agent_server"] = {
        "host": "localhost",
        "port": 8443,
        "certificate_path": "server.crt",
        "private_key_path": "server.key",
        "client_ca_path": "ca.crt",
        "credential_fingerprints": {},
    }
    coordinator.write_text(json.dumps(declaration))
    blank = {
        "service_manager": None,
        "bound_root": None,
        "root_exists": False,
        "installed": None,
        "local_storage": True,
        "credentials_complete": False,
    }

    def inspect(requests):
        assert list(requests) == ["coordinator", "gpu01"]
        assert all(request["action"] == "inspect" for _, request in requests.values())
        agent = (
            dict(blank, root_exists=True)
            if reachable
            else ssh_operations.SshUnavailable("SSH timed out")
        )
        return {"coordinator": blank, "gpu01": agent}

    monkeypatch.setattr(ssh_operations, "_ssh_many", inspect)
    reports = capture_acquisition(monkeypatch, ssh_operations, "plan")
    args = ("--hosts", "gpu01")
    code, output = invoke("plan", path, *args)
    assert code == 0 and "Reservation: no" in output
    coord, worker = output.split("\ngpu01\n")
    assert "coordinator (dependency)" in coord
    coord_actions = reports[-1]["hosts"]["coordinator"]["actions"]
    assert [line.strip() for line in coord.splitlines() if line.startswith("  ")] == [
        f"{i}. {action}" for i, action in enumerate(coord_actions, start=1)
    ]
    if reachable:
        assert "Conflict: existing root lacks retained installation" in worker
        assert "1. verify immutable candidate" in worker
    else:
        assert "Unavailable: SSH timed out" in worker and "1." not in worker
    code, explained = invoke("plan", path, *args, "--explain")
    assert code == 0 and "root exists: no" in explained and "host: gpu-ssh" in explained
    code, original = invoke("plan", path, *args, "--format", "json")
    assert code == 0 and json.loads(original) == reports[-1]
    assert len(reports) == 3
