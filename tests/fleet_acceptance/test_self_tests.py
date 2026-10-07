"""Explicitly selected disposable installed SIF/GPU acceptance; never discovery."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sys
import subprocess
from pathlib import Path
import time
from typing import Any, cast

import pytest

from loom.queue.deployment import (
    _load_protected_config,
    load_coordinator_connection_file,
)
from loom.fleet.configuration import (
    load_inventory,
    protected_directory,
    exclude_captures,
)
from loom.fleet.self_tests import self_test

pytestmark = [pytest.mark.slow, pytest.mark.optional_dependency, pytest.mark.gpu]


def acceptance_selection():
    if os.environ.get("LOOM_RUN_FLEET_ACCEPTANCE") != "1":
        pytest.skip(
            "installed evidence unavailable: LOOM_RUN_FLEET_ACCEPTANCE=1 is not selected"
        )
    path = os.environ.get("LOOM_FLEET_ACCEPTANCE_CONFIG")
    if not path:
        pytest.fail(
            "explicit protected LOOM_FLEET_ACCEPTANCE_CONFIG is required; no fleet discovery"
        )
    source, _, raw, _ = _load_protected_config(path)
    selection = cast(dict[str, Any], dict(raw))
    required = {
        "schema_version",
        "disposable",
        "fleet",
        "deployment",
        "operator_connection",
        "agent_id",
        "config",
        "coordinator_id",
        "agent_root_id",
        "profile",
        "gpu_uuids",
        "image",
        "image_sha256",
        "report",
    }
    if (
        set(selection) != required
        or selection["schema_version"] != 1
        or selection["disposable"] is not True
    ):
        pytest.fail("acceptance requires the complete explicit disposable selection")
    for key in ("fleet", "deployment", "operator_connection", "image", "report"):
        selection[key] = source.parent / selection[key]
    inventory = load_inventory(selection["fleet"])
    hosts = inventory.select([selection["agent_id"]])
    if len(hosts) != 1 or hosts[0].name == "coordinator":
        pytest.fail("acceptance must select exactly one declared agent")
    connection = load_coordinator_connection_file(selection["operator_connection"])
    assert connection.expected_coordinator_id == selection["coordinator_id"]
    _, _, raw_role, _ = _load_protected_config(hosts[0].config)
    role = cast(dict[str, Any], dict(raw_role))
    profiles = [
        p
        for p in role["resident_profiles"]
        if p["descriptor"]["profile_id"] == selection["profile"]["profile_id"]
    ]
    assert len(profiles) == 1
    assert selection["gpu_uuids"] and set(selection["gpu_uuids"]) == {
        device["binding_value"] for device in profiles[0]["gpu_devices"]
    }, "explicit GPU selection must match the disposable profile"
    container = profiles[0].get("container")
    assert container and container["kind"] == "apptainer", (
        "installed SIF execution is required"
    )
    image = Path(container["container"]["image"]["reference"])
    assert image.resolve() == selection["image"].resolve()
    with image.open("rb") as stream:
        assert (
            hashlib.file_digest(stream, "sha256").hexdigest()
            == selection["image_sha256"]
        )
    assert all(value.startswith("GPU-") for value in selection["gpu_uuids"])
    runtime_version = subprocess.run(
        [container["options"]["command"], "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    selection["versions"] = {
        "loom": importlib.metadata.version("loom"),
        "python": sys.version,
        "container_runtime": runtime_version.stdout.strip(),
    }
    # Allocate the evidence destination before any native request. Never replace
    # an earlier run or silently mutate services as part of test cleanup.
    protected_directory(selection["report"].parent)
    _, _, coordinator, _ = _load_protected_config(inventory.hosts[0].config)
    for declared in cast(Any, coordinator)["preparation"]["source_roots"].values():
        exclude_captures(
            selection["report"].parent,
            [inventory.hosts[0].config.parent / declared["path"]],
        )
    descriptor = os.open(
        selection["report"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    return inventory, selection, descriptor


def test_installed_sif_gpu_self_tests():
    inventory, selection, descriptor = acceptance_selection()
    from loom.coordinator import CoordinatorOperatorClient

    with os.fdopen(descriptor, "w") as evidence:
        with CoordinatorOperatorClient.from_connection_file(
            selection["operator_connection"]
        ) as client:
            before = client.observe_agent(selection["agent_id"])
        assert before.value["agent_root_id"] == selection["agent_root_id"]
        assert (
            selection["profile"]
            in cast(Any, before.value)["offer"]["profile_identities"]
        )
        evidence.write(
            json.dumps(
                {
                    "selection": {
                        k: str(v) if isinstance(v, Path) else v
                        for k, v in selection.items()
                    },
                    "before": before.to_dict(),
                }
            )
            + "\n"
        )
        evidence.flush()
        result = self_test(
            inventory,
            deployment=selection["deployment"],
            operator_connection=selection["operator_connection"],
            agent_id=selection["agent_id"],
            config=selection["config"],
            checks=("cpu", "storage", "gpu"),
            timeout_seconds=180,
        )
        evidence.write(json.dumps(result) + "\n")
        evidence.flush()
        deadline = time.monotonic() + 180
        while result["outcome"] == "waiting" and time.monotonic() < deadline:
            time.sleep(1)
            result = self_test(
                inventory,
                operation_id=result["operation_id"],
                timeout_seconds=min(30, deadline - time.monotonic()),
            )
            evidence.write(json.dumps(result) + "\n")
            evidence.flush()
        assert result["outcome"] == "passed", (
            "installed check incomplete; retain and continue exact operation IDs"
        )
        assert (
            result["checks"]["gpu"]["report"]["device_uuid"] in selection["gpu_uuids"]
        )
        for row in result["checks"].values():
            assignment = row["assignment"]["value"]
            assert assignment["profile"] == selection["profile"]
            assert assignment["released"] and assignment["terminal_acknowledged"]
            assert (
                assignment["release_proof"]["agent_root_id"]
                == selection["agent_root_id"]
            )
        assert result["checks"]["gpu"]["report"]["torch_version"]
        # Native containment, terminal acknowledgement, provider release and a
        # fresh offer prove owned workload cleanup. Borrowed services remain up.
        evidence.write(
            json.dumps(
                {
                    "cleanup": "owned_work_settled; existing_services_borrowed",
                    "operation_id": result["operation_id"],
                }
            )
            + "\n"
        )
