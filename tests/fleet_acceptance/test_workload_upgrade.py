"""Protected opt-in: two real SIFs, unchanged services and exact old run evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any, cast

import pytest

from loom.coordinator import (
    CoordinatorClient,
    CoordinatorClientError,
    CoordinatorOperatorClient,
    RunRequest,
)
from loom.deployment import load_deployment
from loom.fleet._host import atomic
from loom.fleet.configuration import load_inventory, protected_directory
from loom.fleet.ssh_operations import _file_hash, ssh
from loom.fleet.upgrades import preview, upgrade
from loom.queue.deployment import _load_protected_config
from loom.queue.preparation import PrepareRunRequest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def selected_case():
    if os.environ.get("LOOM_RUN_FLEET_ACCEPTANCE") != "1":
        pytest.skip(
            "installed evidence unavailable: explicit fleet acceptance opt-in required"
        )
    selection = os.environ.get("LOOM_FLEET_ACCEPTANCE_CONFIG")
    if not selection:
        pytest.fail("protected disposable selection required; no fleet discovery")
    source, _, raw, _ = _load_protected_config(selection)
    if (
        raw.get("schema_version") != 1
        or raw.get("disposable") is not True
        or raw.get("kind") != "workload-upgrade"
    ):
        pytest.fail("selection must explicitly authorize a disposable workload-upgrade")
    value = cast(dict[str, Any], dict(raw))
    required = {
        "schema_version",
        "disposable",
        "kind",
        "fleet",
        "workload_profile",
        "image",
        "image_sha256",
        "deployment",
        "operator_connection",
        "config",
        "operation_id",
        "roots",
        "service_descriptor",
        "old_run",
        "old_run_uri",
        "old_profile",
        "history",
        "report",
        "timeout_seconds",
    }
    if set(value) - (required | {"env_file"}) or required - set(value):
        pytest.fail("incomplete or unknown installed workload selection fields")
    for key in (
        "fleet",
        "image",
        "deployment",
        "operator_connection",
        "report",
        "env_file",
    ):
        if key in value:
            value[key] = (source.parent / value[key]).resolve()
    if not 1 <= value["timeout_seconds"] <= 1800 or value["report"].exists():
        pytest.fail("timeout must be 1..1800 and report a new protected destination")
    if set(value["history"]) != {"source", "profile", "result"}:
        pytest.fail("history must pin old native source, profile and result files")
    for item in value["history"].values():
        if set(item) != {"path", "sha256"}:
            pytest.fail("each history item requires path and sha256")
        item["path"] = str((source.parent / item["path"]).resolve())
        assert _file_hash(Path(item["path"])) == item["sha256"]
    assert (
        value["old_profile"]["revision"]
        in Path(value["history"]["profile"]["path"]).read_text()
    )
    assert _file_hash(value["image"]) == value["image_sha256"]
    return value


def test_installed_workload_upgrade():
    selected = selected_case()
    inventory = load_inventory(selected["fleet"])
    assert (
        len(inventory.hosts) == 2 and len({host.host for host in inventory.hosts}) == 2
    )
    old = load_deployment(selected["deployment"])
    assert old.connection is not None
    old_selection_bytes = selected["deployment"].read_bytes()
    options = {
        key: selected[key]
        for key in ("workload_profile", "image", "deployment", "config")
    }
    options.update(
        connection=selected["operator_connection"], env_file=selected.get("env_file")
    )
    before = preview(inventory, **options)
    assert {
        name: row["expected_root_id"] for name, row in before["hosts"].items()
    } == selected["roots"]
    assert before["gate"]["state"] == "open"
    assert all(
        row["source_release"]["descriptor_sha256"] == selected["service_descriptor"]
        for row in before["hosts"].values()
    )
    assert all(
        candidate["source"]["profile"] == selected["old_profile"]
        for candidate in before["candidates"].values()
    )
    assert all(
        candidate["target"]["profile"] != selected["old_profile"]
        for candidate in before["candidates"].values()
    )
    report = selected["report"]
    protected_directory(report.parent)
    with CoordinatorClient.from_connection_file(old.connection) as client:
        previous = client.observe_run(selected["old_run"], wait=False)
        assert (
            previous.admission is not None
            and previous.admission.state.value == "SUCCEEDED"
        )
        assert previous.admission.run_uri == selected["old_run_uri"]
        assert previous.operation is not None
        original_operation = previous.operation.to_dict()
        atomic(
            report,
            {
                "outcome": "incomplete",
                "before": before,
                "old_operation": original_operation,
                "history": selected["history"],
            },
        )
        deadline = time.monotonic() + selected["timeout_seconds"]
        result = upgrade(
            inventory, operation_id=selected["operation_id"], apply=True, **options
        )
        service_observations = []
        while True:
            observed = {}
            for name, row in before["hosts"].items():
                fact = ssh(
                    row["host"],
                    {**row, "release": before["release"], "action": "inspect"},
                )
                assert (
                    fact["installed"]["descriptor_sha256"]
                    == selected["service_descriptor"]
                )
                assert fact["native_owner"]["owner"] == selected["roots"][name]
                observed[name] = fact
            service_observations.append(observed)
            if result["outcome"] != "waiting" or time.monotonic() >= deadline:
                break
            time.sleep(1)
            result = upgrade(inventory, operation_id=selected["operation_id"])
        assert result["outcome"] == "complete", result
        assert result["release"]["descriptor_sha256"] == selected["service_descriptor"]
        assert result["image_sha256"] == selected["image_sha256"]
        newer = load_deployment(result["deployment"])
        assert newer.source == old.source and newer.connection == old.connection
        assert newer.preparation_profile != old.preparation_profile
        assert selected["deployment"].read_bytes() == old_selection_bytes
        historical = client.observe_run(selected["old_run"], wait=False)
        assert historical.admission == previous.admission
        assert (
            historical.operation is not None
            and historical.operation.to_dict() == original_operation
        )
        for item in selected["history"].values():
            assert _file_hash(Path(item["path"])) == item["sha256"]
        refused_id = selected["operation_id"] + "-old-selection-refused"
        request = RunRequest(
            PrepareRunRequest(
                refused_id,
                refused_id,
                old.source,
                selected["config"],
                old.preparation_profile,
            ),
            refused_id,
        )
        with pytest.raises(CoordinatorClientError) as refusal:
            client.start_run(request)
        assert refusal.value.code not in {"unavailable", "deadline_exceeded"}
        checks = {}
        for attempts in result["checks"].values():
            identity = attempts[-1]["operation_id"]
            check = json.loads(
                (
                    inventory.path.parent / "checks" / identity / "result.json"
                ).read_text()
            )
            assert check["outcome"] == "passed"
            for fact in check["checks"].values():
                if fact["outcome"] != "not_requested":
                    assert (
                        fact["assignment"]["value"]["released"]
                        and fact["assignment"]["value"]["terminal_acknowledged"]
                    )
            checks[identity] = check
        repeated = upgrade(inventory, operation_id=selected["operation_id"])
        assert (
            repeated["checks"] == result["checks"]
            and repeated["deployment"] == result["deployment"]
        )
        with CoordinatorOperatorClient.from_connection_file(
            selected["operator_connection"]
        ) as operator:
            gate = dict(operator.observe_maintenance())
            assert gate["state"] == "open" and gate["checks"] == {} and gate["settled"]
        atomic(
            report,
            {
                "outcome": "passed",
                "before": before,
                "result": result,
                "repeated": repeated,
                "old_operation": original_operation,
                "old_admission": previous.admission.to_dict(),
                "history": selected["history"],
                "old_selection_refusal": refusal.value.to_dict(),
                "services": service_observations,
                "checks": checks,
                "final_gate": gate,
                "controller_processes_started": 0,
                "owned_controller_cleanup": True,
            },
        )
