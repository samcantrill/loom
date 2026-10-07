"""Opt-in installed two-host maintenance and actual controller interruption."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from typing import Any, cast

import pytest

from loom.coordinator import CoordinatorOperatorClient
from loom.fleet._host import atomic
from loom.fleet.configuration import load_inventory, protected_directory
from loom.fleet.upgrades import preview
from loom.fleet.ssh_operations import operation_status, ssh
from loom.queue.deployment import _load_protected_config

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def selected_case(name):
    if os.environ.get("LOOM_RUN_FLEET_ACCEPTANCE") != "1":
        pytest.skip(
            "installed evidence unavailable: explicit fleet acceptance opt-in required"
        )
    path = os.environ.get("LOOM_FLEET_ACCEPTANCE_CONFIG")
    if not path:
        pytest.fail(
            "protected disposable acceptance selection required; no fleet discovery"
        )
    source, _, raw, _ = _load_protected_config(path)
    if (
        raw.get("schema_version") != 1
        or raw.get("disposable") is not True
        or raw.get("kind") != "runtime-upgrade"
    ):
        pytest.fail(
            "selection must explicitly authorize disposable runtime-upgrade cases"
        )
    value = cast(dict[str, Any], raw.get("cases", {})).get(name)
    if value is None:
        pytest.skip("installed case unavailable: " + name)
    value = dict(value)
    required = {
        "fleet",
        "runtime_release",
        "deployment",
        "operator_connection",
        "config",
        "operation_id",
        "roots",
        "source_releases",
        "report",
        "timeout_seconds",
    }
    if set(value) - (required | {"env_file"}) or required - set(value):
        pytest.fail("incomplete or unknown installed upgrade selection fields")
    for key in (
        "fleet",
        "runtime_release",
        "deployment",
        "operator_connection",
        "report",
        "env_file",
    ):
        if key in value:
            value[key] = (source.parent / value[key]).resolve()
    if not 1 <= value["timeout_seconds"] <= 900:
        pytest.fail("timeout_seconds must be 1..900")
    if value["report"].exists():
        pytest.fail("report must be a new protected destination")
    return value


def _invoke(args, log):
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from loom.cli.main import main; raise SystemExit(main())",
            "fleet",
            *args,
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


@pytest.mark.parametrize("case", ["upgrade", "interruption"])
def test_installed_runtime_upgrade(case):
    selected = selected_case(case)
    inventory = load_inventory(selected["fleet"])
    assert (
        len(inventory.hosts) == 2
        and len({entry.host for entry in inventory.hosts}) == 2
    )
    options = {
        key: selected[key] for key in ("runtime_release", "deployment", "config")
    }
    options.update(
        connection=selected["operator_connection"], env_file=selected.get("env_file")
    )
    before = preview(inventory, **options)
    assert {
        name: row["expected_root_id"] for name, row in before["hosts"].items()
    } == selected["roots"]
    assert {
        name: row["source_release"]["descriptor_sha256"]
        for name, row in before["hosts"].items()
    } == selected["source_releases"]
    assert before["gate"]["state"] == "open"
    report = selected["report"]
    protected_directory(report.parent)
    atomic(
        report,
        {
            "case": case,
            "before": before,
            "operation_id": selected["operation_id"],
            "outcome": "incomplete",
            "controller_python": sys.version,
        },
    )
    common = ["--fleet", str(selected["fleet"]), "--format", "json"]
    initial = [
        "upgrade",
        *common,
        "--runtime-release",
        str(selected["runtime_release"]),
        "--apply",
        "--operation-id",
        selected["operation_id"],
        "--deployment",
        str(selected["deployment"]),
        "--connection",
        str(selected["operator_connection"]),
        "--config",
        selected["config"],
        "--timeout",
        "30",
    ]
    if selected.get("env_file"):
        initial += ["--env-file", str(selected["env_file"])]
    deadline = time.monotonic() + selected["timeout_seconds"]
    interrupted, gate_evidence, controller_exits = False, None, []
    with report.with_suffix(".log").open("xb") as log:
        os.chmod(log.name, 0o600)
        process = _invoke(initial, log)
        try:
            with CoordinatorOperatorClient.from_connection_file(
                selected["operator_connection"]
            ) as operator:
                while time.monotonic() < deadline:
                    if case == "interruption" and not interrupted:
                        gate = dict(operator.observe_maintenance())
                        if (
                            gate["state"] == "closed"
                            and gate["maintenance_id"] == selected["operation_id"]
                        ):
                            gate_evidence = gate
                            os.killpg(process.pid, signal.SIGTERM)
                            process.wait(timeout=30)
                            interrupted = True
                    if process.poll() is not None:
                        controller_exits.append(process.returncode)
                        result = operation_status(inventory, selected["operation_id"])
                        atomic(
                            report,
                            {
                                "case": case,
                                "before": before,
                                "gate_at_interruption": gate_evidence,
                                "result": result,
                                "controller_exits": controller_exits,
                                "outcome": "incomplete",
                            },
                        )
                        if result["outcome"] == "complete":
                            break
                        assert result["outcome"] in {"waiting", "running", "pending"}, (
                            result
                        )
                        process = _invoke(
                            ["operation", "resume", selected["operation_id"], *common],
                            log,
                        )
                    time.sleep(0.2)
                else:
                    pytest.fail(
                        "installed upgrade deadline; preserve exact operation/native owners"
                    )
                assert case != "interruption" or interrupted
                gate = dict(operator.observe_maintenance())
                assert (
                    gate["state"] == "open" and gate["checks"] == {} and gate["settled"]
                )
                after = preview(inventory, **options)
                assert {
                    name: row["expected_root_id"]
                    for name, row in after["hosts"].items()
                } == selected["roots"]
                assert all(
                    row["source_release"]["descriptor_sha256"]
                    == before["release"]["descriptor_sha256"]
                    for row in after["hosts"].values()
                )
                settlement = {}
                for name, row in after["hosts"].items():
                    fact = ssh(
                        row["host"],
                        {
                            **row,
                            "release": after["release"],
                            "action": "upgrade-settlement",
                            "include_pending_poll": False,
                        },
                    )
                    assert (
                        fact["availability"] == "available" and fact["value"]["settled"]
                    ), fact
                    settlement[name] = fact
                check_evidence = {}
                for rows in result["checks"].values():
                    attempt = rows[-1]
                    check = json.loads(
                        (
                            inventory.path.parent
                            / "checks"
                            / attempt["operation_id"]
                            / "result.json"
                        ).read_text()
                    )
                    assert check["outcome"] == "passed"
                    check_evidence[attempt["operation_id"]] = check
                    for fact in check["checks"].values():
                        if fact["outcome"] != "not_requested":
                            assert (
                                fact["assignment"]["value"]["released"]
                                and fact["assignment"]["value"]["terminal_acknowledged"]
                            )
                atomic(
                    report,
                    {
                        "case": case,
                        "before": before,
                        "after": after,
                        "gate_at_interruption": gate_evidence,
                        "final_gate": gate,
                        "result": result,
                        "controller_exits": controller_exits,
                        "outcome": "passed",
                        "owned_controller_cleanup": True,
                        "native_settlement": settlement,
                        "check_evidence": check_evidence,
                        "candidate_evidence": {
                            name: json.loads(
                                (
                                    inventory.path.parent
                                    / "operations"
                                    / selected["operation_id"]
                                    / (name + "-candidate.json")
                                ).read_text()
                            )
                            for name in after["hosts"]
                        },
                    },
                )
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=30)
