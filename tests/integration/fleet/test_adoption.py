"""Installation handover over actual disposable SSH, native roots and tmux."""

from __future__ import annotations

import hashlib
import json
import time
from typing import cast

import pytest

from loom.coordinator import CoordinatorOperatorClient
from loom.fleet import adoption, ssh_operations
from loom.fleet.configuration import load_inventory
from loom.queue.agent_sessions import AgentControl, AgentControlKind
from loom.queue.errors import QueueConfigError, QueueConflictError
from loom.queue.operations import inspect_native_service
from loom.queue.service_upgrade import inspect_service_settlement
from tests.integration.fleet.test_ssh_operations import bundle, endpoint, site, write  # noqa: F401
from tests.integration.fleet.test_runtime_upgrade import target_bundle

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def retained_installation(inventory, base, tmp_path):
    """Retain real native services, withdrawing only fixture installer bindings.

    This covers transfer from an unmanaged current runtime. Actual schema-18
    predecessor migration and physical two-host evidence are separate coverage.
    """
    bindings = {}
    owners = {}
    for host in inventory.hosts:
        root = base / ("c" if host.name == "coordinator" else host.name)
        native = root / "coordinator" if host.name == "coordinator" else root
        observed = inspect_native_service(native)
        assert observed.value["ownership"] == "live"
        admin = root.parent / (
            ".loom-fleet-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
        )
        previous = json.loads((admin / "active.json").read_text())
        python = (
            admin
            / "releases"
            / previous["descriptor_sha256"]
            / "environment/bin/python"
        )
        bindings[host.name] = {
            "expected_root_id": observed.owner,
            "python": str(python),
        }
        owners[host.name] = observed
        for name in ("active.json", "service.json"):
            (admin / name).rename(admin / ("retained-legacy-" + name))
    path = write(
        tmp_path / "adoption.json",
        {"schema_version": 1, "kind": "loom.fleet-adoption", "hosts": bindings},
    )
    target = target_bundle(inventory, tmp_path)
    value = json.loads(inventory.path.read_text())
    value["runtime_release"] = str(target)
    write(inventory.path, value)
    return load_inventory(inventory.path), path, owners


@pytest.mark.parametrize(
    "site", [None, 107], indirect=True, ids=["short-path", "linux-max-socket"]
)
def test_quiesced_adoption_preserves_native_history_and_resolves_lost_reply(
    site,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    inventory, base, selection = site
    setup = ssh_operations.apply(
        inventory,
        operation_id="legacy-setup",
        issuer=base / "issuer",
        check_selection=selection,
    )
    assert setup["outcome"] == "complete", setup
    with CoordinatorOperatorClient.from_connection_file(
        setup["operator_connection"]
    ) as operator:
        history = {
            fact["assignment"]["value"]["assignment_id"]: operator.observe_assignment(
                fact["assignment"]["value"]["assignment_id"]
            ).to_dict()["value"]
            for fact in setup["checks"]["worker"]["checks"].values()
            if fact["outcome"] == "passed"
        }
    assert history
    inventory, bindings, owners = retained_installation(inventory, base, tmp_path)
    preview = adoption.preview(inventory, bindings=bindings)
    assert preview["outcome"] == "preview" and preview["ready"] is False
    assert not (inventory.path.parent / "operations/adopt").exists()
    assert all(not row.get("conflict") for row in preview["hosts"].values())
    with pytest.raises(QueueConfigError, match="operator-exclusion"):
        adoption.adopt(inventory, bindings=bindings, operation_id="adopt", apply=True)

    # A supported live producer has an outstanding poll, despite idle CPU.
    deadline = time.monotonic() + 10
    waits = []
    while time.monotonic() < deadline:
        settlement = inspect_service_settlement(
            base / "worker", expected_root_id=owners["worker"].owner
        )
        waits = cast(list[str], settlement.value.get("wait_reasons", []))
        if "unresolved_poll" in waits:
            break
        time.sleep(0.05)
    assert "unresolved_poll" in waits
    result = adoption.adopt(
        inventory,
        bindings=bindings,
        operation_id="adopt",
        apply=True,
        operator_exclusion=True,
    )
    assert result["outcome"] == "waiting", result
    assert "settlement" in result["reason"]
    assert not (inventory.path.parent / "operations/adopt/replacement.json").exists()
    assert (
        inspect_native_service(base / "worker").value["expected_process"]
        == owners["worker"].value["expected_process"]
    )

    original = bindings.read_bytes()
    bindings.write_bytes(original + b"\n")
    with pytest.raises(QueueConflictError, match="input changed"):
        adoption.adopt(inventory, operation_id="adopt")
    bindings.write_bytes(original)
    with CoordinatorOperatorClient.from_connection_file(
        setup["operator_connection"]
    ) as operator:
        current = operator.observe_agent("worker").value
        operator.control_agent(
            AgentControl(
                "adoption-drain",
                AgentControlKind.DRAIN,
                "worker",
                cast(str, current["session_id"]),
                cast(str, current["config_revision"]),
                None,
                False,
                "Disposable installation adoption",
            )
        )
    original_ssh = ssh_operations.ssh
    replaced = []

    def lose_reply(host, request):
        result = original_ssh(host, request)
        if request["action"] == "adopt-replace" and request["name"] == "coordinator":
            replaced.append(request["request_id"])
            if len(replaced) == 1:
                raise ssh_operations.SshUnavailable("lost adopted coordinator reply")
        return result

    monkeypatch.setattr(ssh_operations, "ssh", lose_reply)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = adoption.adopt(inventory, operation_id="adopt")
        if replaced or result["outcome"] != "waiting":
            break
        assert "settlement" in result["reason"], result
        time.sleep(0.1)
    assert result["outcome"] == "waiting" and len(replaced) == 1, result
    with pytest.raises(QueueConflictError, match="no automatic rollback"):
        adoption.adopt(inventory, operation_id="adopt", action="abort")
    result = adoption.adopt(inventory, operation_id="adopt")
    assert result["outcome"] == "complete", result
    assert len(replaced) == 1  # The lost reply was observed, never dispatched again.
    assert result["ready"] is False and result["qualification"] == "required"
    assert result["identities"] == setup["identities"]
    assert (
        inspect_native_service(base / "worker").value["session_id"]
        == owners["worker"].value["session_id"]
    )
    with CoordinatorOperatorClient.from_connection_file(
        setup["operator_connection"]
    ) as operator:
        for identity, retained in history.items():
            assert operator.observe_assignment(identity).to_dict()["value"] == retained
    assert adoption.adopt(inventory, operation_id="adopt") == result
    from loom.cli.main import main

    capsys.readouterr()
    assert (
        main(
            [
                "fleet",
                "operation",
                "status",
                "adopt",
                "--fleet",
                str(inventory.path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["installation"] == "adopted"
