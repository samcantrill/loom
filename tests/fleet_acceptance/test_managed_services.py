"""Installed service-manager evidence on explicitly selected disposable hosts.

The operator supplies already initialized roles and bounded synthetic assignments
through ordinary native submission. This owner changes only selected service
lifetimes; it neither discovers fleets nor provisions host policy. Each case
retains a new protected receipt, including exact launch and cleanup evidence.
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any, cast

import pytest

from loom.queue.deployment import _load_protected_config
from loom.fleet.configuration import load_inventory, protected_directory

pytestmark = [pytest.mark.slow, pytest.mark.optional_dependency]

CASES = (
    "ssh_disconnect",
    "logout",
    "resident_agent_restart",
    "sif_agent_restart",
    "idle_reboot",
    "in_job_reboot",
)


def selection(case):
    if os.environ.get("LOOM_RUN_FLEET_ACCEPTANCE") != "1":
        pytest.skip(
            "installed managed-service evidence unavailable: explicit opt-in absent"
        )
    selected = os.environ.get("LOOM_FLEET_ACCEPTANCE_CONFIG")
    if not selected:
        pytest.fail(
            "protected LOOM_FLEET_ACCEPTANCE_CONFIG required; no fleet discovery"
        )
    source, _, raw, _ = _load_protected_config(selected)
    value = cast(dict[str, Any], raw)
    assert value.get("schema_version") == 1 and value.get("disposable") is True
    assert value.get("kind") == "managed-services"
    cases = value["cases"]
    if case not in cases:
        pytest.skip(f"installed {case} evidence unavailable: no explicit selection")
    item = dict(cases[case])
    required = {
        "fleet",
        "agent_id",
        "agent_root_id",
        "coordinator_id",
        "session_id",
        "agent_python",
        "coordinator_python",
        "operator_connection",
        "report",
        "timeout_seconds",
    }
    assert required <= item.keys(), "complete native identity selection required"
    assert 1 <= item["timeout_seconds"] <= 900
    for key in ("fleet", "report", "operator_connection"):
        item[key] = (source.parent / item[key]).resolve()
    inventory = load_inventory(item["fleet"])
    assert inventory.service_manager == "systemd-user"
    agent = inventory.select([item["agent_id"]])
    coordinator = inventory.select(["coordinator"])
    assert len(agent) == len(coordinator) == 1 and agent[0].host != coordinator[0].host
    assert agent[0].name != "coordinator"
    for host in (agent[0].host, coordinator[0].host):
        assert (
            host
            and not host.startswith("-")
            and all(c.isalnum() or c in ".-_@" for c in host)
        )
    if "reboot" in case:
        if os.environ.get("LOOM_ALLOW_FLEET_REBOOT") != "1":
            pytest.skip(
                "actual reboot unavailable: separate reboot authorization absent"
            )
        assert agent[0].host in value.get("reboot_authorized_hosts", ()), (
            "exact reboot host authorization required"
        )
    if case != "idle_reboot":
        assert item.get("assignment_id"), (
            "already submitted bounded native assignment required"
        )
    if case == "sif_agent_restart":
        assert item.get("image") and item.get("image_sha256"), (
            "exact installed SIF required"
        )
    assert not item["report"].exists(), "receipt path must be new"
    protected_directory(item["report"].parent)
    return item, agent[0], coordinator[0]


def remote_program():
    """Fixed SSH program; every path, host and identity arrives as JSON data."""
    import hashlib
    import importlib.metadata
    import json
    import os
    from pathlib import Path
    import select
    import subprocess
    import sys
    import time
    from typing import Any, cast
    from loom.fleet._services import systemctl, unit_name
    from loom.queue.deployment import (
        load_outbound_agent_service_config,
        load_coordinator_service_config,
    )
    from loom.queue.operations import inspect_native_service, inspect_local_assignment
    from loom.queue._agent_process_supervisor import (
        AgentProcessSupervisorClient,
        _service_configuration,
        _launch_from_value,
    )
    from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace

    request = json.loads(sys.stdin.readline())
    role = request["role"]
    selected = request["selected"]
    config = request["config"]
    env_file = request.get("env_file")
    if role == "agent":
        root = load_outbound_agent_service_config(
            config, env_file=env_file
        ).client.agent_root
    else:
        root = load_coordinator_service_config(
            config, env_file=env_file
        ).daemon.coordinator_root
    assert root is not None
    expected = (
        selected["agent_root_id"] if role == "agent" else selected["coordinator_id"]
    )

    def observe(*, live=True):
        fact = cast(dict[str, Any], inspect_native_service(root).to_dict())
        assert fact["availability"] == "available" and fact["owner"] == expected, fact
        if live:
            assert fact["value"]["ownership"] == "live", fact
        return fact

    before = observe()
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    versions = {
        "python": sys.version,
        "loom": importlib.metadata.version("loom"),
        "systemd": subprocess.run(
            ["systemctl", "--version"], capture_output=True, text=True, check=True
        ).stdout,
        "source_sha256": hashlib.sha256(
            Path(
                __import__("loom.fleet._services", fromlist=["x"]).__file__
            ).read_bytes()
        ).hexdigest(),
    }
    if role == "coordinator":
        print(
            json.dumps({"native": before, "boot_id": boot, "versions": versions}),
            flush=True,
        )
        return
    assert before["value"]["session_id"] == selected["session_id"]
    assert before["value"]["coordinator_id"] == selected["coordinator_id"]
    supervisor = AgentProcessSupervisorClient(
        root, _service_configuration(root / "supervisor")
    )
    retained = {
        "supervisor_id": supervisor.supervisor_id,
        "continuity_epoch": supervisor.continuity_epoch,
        "service_process_id": supervisor.service_process_id,
    }
    unit_request = {"root": str(root)}
    agent_unit, supervisor_unit = (
        unit_name(unit_request, "agent"),
        unit_name(unit_request, "supervisor"),
    )
    agent_group = systemctl("show", agent_unit, "--property=ControlGroup", "--value")
    supervisor_group = systemctl(
        "show", supervisor_unit, "--property=ControlGroup", "--value"
    )
    assert agent_group and supervisor_group and agent_group != supervisor_group
    assert (
        str(supervisor.service_process_id)
        in (Path("/sys/fs/cgroup") / supervisor_group.lstrip("/") / "cgroup.procs")
        .read_text()
        .split()
    )
    launch = None
    running = None
    encoded = None
    descriptors = []
    worker_fd = None
    if selected.get("assignment_id"):
        encoded = _ResidentAssignmentWorkspace(
            root, selected["assignment_id"]
        ).supervisor_launch_json()
        assert encoded is not None
        launch = _launch_from_value(json.loads(encoded))
        assert (
            launch.agent_id == expected and launch.session_id == selected["session_id"]
        )
        running = supervisor.query_wait(launch)
        assert running.state.value == "running" and running.process_id is not None
        pids = (
            (Path("/sys/fs/cgroup") / supervisor_group.lstrip("/") / "cgroup.procs")
            .read_text()
            .split()
        )
        assert str(running.process_id) in pids
        # These descriptors are owned observation handles, never PID adoption.
        descriptors = [
            os.pidfd_open(int(pid))
            for pid in pids
            if int(pid) != supervisor.service_process_id
        ]
        assert descriptors
        worker_fd = os.pidfd_open(running.process_id)
        descriptors.append(worker_fd)
        if request["case"] == "sif_agent_restart":
            assert launch.backend_kind == "apptainer"
            container = cast(dict[str, Any], launch.profile.container)
            assert (
                str(container["container"]["image"]["reference"]) == selected["image"]
            )
            image = Path(selected["image"])
            with image.open("rb") as image_stream:
                assert (
                    hashlib.file_digest(image_stream, "sha256").hexdigest()
                    == selected["image_sha256"]
                )
            versions["apptainer"] = subprocess.run(
                [container["options"]["command"], "--version"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
    snapshot = {
        "native": before,
        "boot_id": boot,
        "versions": versions,
        "supervisor": retained,
        "root": str(root),
        "agent_cgroup": agent_group,
        "supervisor_cgroup": supervisor_group,
        "launch": None if encoded is None else json.loads(encoded),
    }
    print(json.dumps({"ready": snapshot}), flush=True)
    instruction = json.loads(sys.stdin.readline())
    probe_fd = None
    if request["case"] in {"ssh_disconnect", "logout"}:
        probe_identity = instruction["probe_identity"]
        probe_root = Path("/proc") / str(probe_identity["pid"])
        assert probe_root.stat().st_uid == os.getuid()
        assert (
            probe_root.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19]
            == probe_identity["started"]
        )
        probe_fd = os.pidfd_open(probe_identity["pid"])
        descriptors.append(probe_fd)
        print(json.dumps({"probe_watched": True}), flush=True)
        instruction = json.loads(sys.stdin.readline())
    assert instruction["continue"] is True
    try:
        if probe_fd is not None:
            assert select.select([probe_fd], [], [], 15)[0], (
                "owned SSH probe process survived session closure"
            )
        if request["case"].endswith("agent_restart"):
            systemctl("restart", agent_unit)
        if "reboot" in request["case"]:
            # The caller has enforced both opt-ins and the exact disposable host.
            assert request.get("reboot_authorized") is True
            subprocess.run(["systemctl", "--no-ask-password", "reboot"], check=True)
            return
        deadline = time.monotonic() + selected["timeout_seconds"]
        after = observe(live=False)
        while (
            after["value"]["ownership"] != "live"
            or after["value"]["session_id"] != selected["session_id"]
            or (
                request["case"].endswith("agent_restart")
                and after["value"]["expected_process"]
                == before["value"]["expected_process"]
            )
        ):
            assert time.monotonic() < deadline, (
                "agent restart never restored retained session"
            )
            time.sleep(0.1)
            after = observe(live=False)
        current = AgentProcessSupervisorClient(
            root, _service_configuration(root / "supervisor")
        )
        assert (
            current.supervisor_id,
            current.continuity_epoch,
            current.service_process_id,
        ) == tuple(retained.values())
        assert Path("/proc/sys/kernel/random/boot_id").read_text().strip() == boot
        if launch is not None:
            assert running is not None
            still_running = current.query_wait(launch)
            assert still_running.process_id == running.process_id
            assert still_running.state.value == "running", (
                "worker did not survive selected lifecycle event"
            )
            assert (
                worker_fd is not None and not select.select([worker_fd], [], [], 0)[0]
            )
            pending = list(descriptors)
            while pending:
                assert time.monotonic() < deadline, (
                    "bounded fixture processes survived timeout; retain owners for inspection"
                )
                completed, _, _ = select.select(
                    pending, [], [], max(0.01, deadline - time.monotonic())
                )
                pending = [fd for fd in pending if fd not in completed]
            while True:
                final = cast(
                    dict[str, Any],
                    inspect_local_assignment(root, selected["assignment_id"]).to_dict(),
                )
                if final["value"].get("providers_released"):
                    break
                assert time.monotonic() < deadline, final
                time.sleep(0.1)
            assert (
                current.query_wait(launch).launch.launch_operation_id
                == launch.launch_operation_id
            )
            remaining = (
                (Path("/sys/fs/cgroup") / supervisor_group.lstrip("/") / "cgroup.procs")
                .read_text()
                .split()
            )
            assert set(remaining) == {str(supervisor.service_process_id)}, (
                "fixture descendants remain in supervisor cgroup"
            )
        else:
            final = None
        print(
            json.dumps(
                {
                    "before": snapshot,
                    "after": after,
                    "assignment": final,
                    "owned_process_cleanup": "all observed worker pidfds exited",
                    "duplicate_launch": False,
                }
            ),
            flush=True,
        )
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def argv(host, python):
    program = inspect.getsource(remote_program) + "\nremote_program()\n"
    assert Path(python).is_absolute()
    return ["ssh", "-T", host, shlex.join([python, "-c", program])]


def one_snapshot(item, entry, role):
    request = {
        "role": role,
        "selected": {k: str(v) if isinstance(v, Path) else v for k, v in item.items()},
        "config": str(entry.config),
        "env_file": item.get(role + "_env_file"),
    }
    result = subprocess.run(
        argv(entry.host, item[role + "_python"]),
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("case", CASES)
def test_managed_service_lifetime(case):
    item, agent, coordinator = selection(case)
    evidence = {
        "case": case,
        "agent_host": agent.host,
        "coordinator_host": coordinator.host,
        "selection": {k: str(v) if isinstance(v, Path) else v for k, v in item.items()},
        "outcome": "running",
    }

    def save():
        from loom.fleet._host import atomic

        atomic(item["report"], evidence)

    save()
    process = None
    try:
        evidence["coordinator_before"] = one_snapshot(item, coordinator, "coordinator")
        request = {
            "role": "agent",
            "selected": evidence["selection"],
            "config": str(agent.config),
            "env_file": item.get("agent_env_file"),
            "case": case,
            "reboot_authorized": "reboot" in case,
        }
        process = subprocess.Popen(
            argv(agent.host, item["agent_python"]),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert (
            process.stdin is not None
            and process.stdout is not None
            and process.stderr is not None
        )
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        assert line, process.stderr.read()
        evidence["agent_before"] = json.loads(line)["ready"]
        save()
        if case in {"ssh_disconnect", "logout"}:
            # This PTY login and transport are ours. Abrupt transport loss and
            # orderly login exit are distinct events; no other session is closed.
            probe_program = (
                "import json,os,subprocess; from pathlib import Path; "
                'r=subprocess.run(["loginctl","show-user",str(os.getuid()),"--property=Sessions","--value"],capture_output=True,text=True); '
                'print(json.dumps({"session":os.environ.get("XDG_SESSION_ID"),"logind_sessions":r.stdout.strip(),"pid":os.getpid(),"started":Path("/proc/self/stat").read_text().rsplit(")",1)[1].split()[19]}),flush=True); input()'
            )
            probe = subprocess.Popen(
                [
                    "ssh",
                    "-tt",
                    agent.host,
                    shlex.join([item["agent_python"], "-c", probe_program]),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert probe.stdout is not None
                evidence["closed_owned_ssh"] = json.loads(probe.stdout.readline())
                process.stdin.write(
                    json.dumps({"probe_identity": evidence["closed_owned_ssh"]}) + "\n"
                )
                process.stdin.flush()
                assert json.loads(process.stdout.readline())["probe_watched"] is True
                if case == "ssh_disconnect":
                    probe.terminate()
                    probe.communicate(timeout=15)
                else:
                    probe.communicate(input="\n", timeout=15)
                    assert probe.returncode == 0, "owned login did not exit normally"
                evidence["owned_login_event"] = (
                    "transport_disconnect"
                    if case == "ssh_disconnect"
                    else "orderly_ssh_logout"
                )
                evidence["last_logind_session"] = "not_qualified"
            finally:
                if probe.poll() is None:
                    probe.terminate()
                    probe.communicate(timeout=10)
        process.stdin.write(
            json.dumps(
                {
                    "continue": True,
                    "closed_session": evidence.get("closed_owned_ssh", {}).get(
                        "session"
                    ),
                }
            )
            + "\n"
        )
        process.stdin.flush()
        if "reboot" in case:
            process.communicate(timeout=60)
            evidence["reboot_dispatched"] = True
            # Reconnect only to this selected host; native startup owns recovery.
            deadline = time.monotonic() + item["timeout_seconds"]
            while True:
                try:
                    one_snapshot(item, coordinator, "coordinator")
                    # Agent post-reboot evidence is collected by a fresh fixed
                    # program below, without requiring a running interrupted job.
                    post = subprocess.run(
                        [
                            "ssh",
                            "-T",
                            agent.host,
                            shlex.join(
                                [
                                    item["agent_python"],
                                    "-c",
                                    'import json,sys; from pathlib import Path; from loom.queue.operations import inspect_native_service,inspect_local_assignment; r=json.load(sys.stdin); print(json.dumps({"boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"native":inspect_native_service(r["root"]).to_dict(),"assignment":inspect_local_assignment(r["root"],r["assignment"]).to_dict() if r["assignment"] else None}))',
                                ]
                            ),
                        ],
                        input=json.dumps(
                            {
                                "root": evidence["agent_before"]["root"],
                                "assignment": item.get("assignment_id"),
                            }
                        ),
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    assert post.returncode == 0
                    recovered = json.loads(post.stdout)
                    assert recovered["boot"] != evidence["agent_before"]["boot_id"]
                    assert recovered["native"]["owner"] == item["agent_root_id"]
                    assert (
                        recovered["native"]["value"]["session_id"] == item["session_id"]
                    )
                    if item.get("assignment_id"):
                        assert (
                            recovered["assignment"]["value"]["containment"]
                            == "contained"
                        )
                        assert recovered["assignment"]["value"]["providers_released"]
                    evidence["reboot_recovery"] = recovered
                    break
                except (AssertionError, subprocess.SubprocessError, ValueError):
                    assert time.monotonic() < deadline, (
                        "selected reboot did not reconcile before timeout"
                    )
                    time.sleep(1)
        else:
            stdout, stderr = process.communicate(timeout=item["timeout_seconds"] + 30)
            assert process.returncode == 0, stderr
            evidence["lifecycle"] = json.loads(stdout)
        from loom.coordinator import CoordinatorOperatorClient

        deadline = time.monotonic() + item["timeout_seconds"]
        with CoordinatorOperatorClient.from_connection_file(
            item["operator_connection"]
        ) as client:
            while True:
                observed = cast(
                    dict[str, Any], client.observe_agent(item["agent_id"]).to_dict()
                )
                if (
                    observed["value"].get("offer")
                    and observed["value"]["offer"]["freshness"] == "current"
                    and observed["value"].get("connected")
                ):
                    assert observed["value"]["session_id"] == item["session_id"]
                    evidence["reconciled_agent"] = observed
                    break
                assert time.monotonic() < deadline, (
                    "native reconciliation did not release fresh offers"
                )
                time.sleep(0.1)
        evidence["coordinator_after"] = one_snapshot(item, coordinator, "coordinator")
        assert (
            evidence["coordinator_after"]["native"]["owner"] == item["coordinator_id"]
        )
        evidence["outcome"] = "passed"
    except BaseException as exc:
        evidence["outcome"] = (
            "unavailable" if isinstance(exc, pytest.skip.Exception) else "failed"
        )
        evidence["reason"] = str(exc)
        raise
    finally:
        if process is not None and process.poll() is None:
            # Only the owned SSH observer is terminated; never a native service/job.
            process.terminate()
            process.communicate(timeout=10)
        save()
