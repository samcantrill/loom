"""Actual disposable SSH/native commands for retained setup and continuation."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import socket
import subprocess
import sys
import time
import zipfile
from typing import cast

import pytest

from loom.fleet.configuration import load_inventory
from loom.fleet.ssh_operations import apply, operation_status, plan

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def write(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind_environments(inventory):
    """Keep root declarations native while binding different machine roots."""
    authored = json.loads(inventory.path.read_text())
    for host in inventory.hosts:
        role = json.loads(host.config.read_text())
        key = "deployment_root" if host.name == "coordinator" else "agent_root"
        env = inventory.path.parent / (host.name + ".env")
        env.write_text("FLEET_NATIVE_ROOT=" + role[key] + "\n")
        env.chmod(0o600)
        role[key] = "${oc.env:FLEET_NATIVE_ROOT}"
        write(host.config, role)
        entry = (
            authored["coordinator"]
            if host.name == "coordinator"
            else authored["agents"][host.name]
        )
        entry["env_file"] = env.name
    write(inventory.path, authored)
    return load_inventory(inventory.path)


@pytest.fixture(scope="session")
def bundle(tmp_path_factory):
    """Repack the locked installed dependencies into real offline test wheels."""
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    root = tmp_path_factory.mktemp("bundle")
    wheels = root / "wheels"
    wheels.mkdir()
    pending = [("loom", {"fleet", "config"})]
    selected = {}
    while pending:
        name, extras = pending.pop()
        name = canonicalize_name(name)
        if name in selected:
            continue
        dist = importlib.metadata.distribution(name)
        selected[name] = dist
        for line in dist.requires or []:
            requirement = Requirement(line)
            if requirement.marker is None or any(
                requirement.marker.evaluate({"extra": extra}) for extra in extras | {""}
            ):
                pending.append((requirement.name, set(requirement.extras)))
    requirements, manifests = [], []
    for name, dist in selected.items():
        files = {}
        for entry in dist.files or []:
            relative = str(entry)
            if (
                ".." in Path(relative).parts
                or relative.endswith(("RECORD", "direct_url.json"))
                or relative.endswith(".pth")
            ):
                continue
            path = Path(dist.locate_file(entry))
            if path.is_file():
                files[relative] = path.read_bytes()
        if name == "loom":
            source = Path(__file__).resolve().parents[3] / "src"
            files.update(
                {
                    str(path.relative_to(source)): path.read_bytes()
                    for path in (source / "loom").rglob("*")
                    if path.is_file() and "__pycache__" not in path.parts
                }
            )
        metadata = next(path for path in files if path.endswith(".dist-info/WHEEL"))
        tag = next(
            line[5:]
            for line in files[metadata].decode().splitlines()
            if line.startswith("Tag: ")
        )
        wheel = wheels / f"{name.replace('-', '_')}-{dist.version}-{tag}.whl"
        record_path = metadata.rsplit("/", 1)[0] + "/RECORD"
        record = io.StringIO()
        writer = csv.writer(record)
        for path, content in sorted(files.items()):
            writer.writerow(
                (
                    path,
                    "sha256="
                    + base64.urlsafe_b64encode(hashlib.sha256(content).digest())
                    .decode()
                    .rstrip("="),
                    str(len(content)),
                )
            )
        writer.writerow((record_path, "", ""))
        files[record_path] = record.getvalue().encode()
        with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, content in files.items():
                archive.writestr(path, content)
        requirements.append(
            f"{name}{'[fleet]' if name == 'loom' else ''}=={dist.version} --hash=sha256:{sha(wheel)}"
        )
        manifests.append(f"{sha(wheel)}  {wheel.name}")
    lock = root / "requirements.txt"
    lock.write_text("\n".join(requirements) + "\n")
    manifest = root / "wheels.sha256"
    manifest.write_text("\n".join(manifests) + "\n")
    return write(
        root / "release.json",
        {
            "schema_version": 1,
            "kind": "loom.service-release",
            "release_id": "fixture",
            "python": "3.12",
            "requirements": {"path": lock.name, "sha256": sha(lock)},
            "wheelhouse": {
                "path": "wheels",
                "manifest": manifest.name,
                "sha256": sha(manifest),
            },
        },
    )


@pytest.fixture
def endpoint(tmp_path, monkeypatch):
    root = tmp_path / "ssh"
    root.mkdir(mode=0o700)
    for name in ("host", "client"):
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(root / name)],
            check=True,
        )
    with socket.socket() as selected:
        selected.bind(("127.0.0.1", 0))
        port = selected.getsockname()[1]
    key = (root / "client.pub").read_text()
    import tempfile

    authorization_root = Path(
        tempfile.mkdtemp(prefix="loom-ssh-fixture-", dir=Path.home() / ".cache")
    )
    authorized = authorization_root / "authorized_keys"
    authorized.write_text(key)
    authorized.chmod(0o600)
    configuration = root / "sshd_config"
    configuration.write_text(
        f"Port {port}\nListenAddress 127.0.0.1\nHostKey {root / 'host'}\nPidFile {root / 'pid'}\nAuthorizedKeysFile {authorized}\nStrictModes yes\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\nAllowUsers {pwd.getpwuid(os.getuid()).pw_name}\nLogLevel ERROR\n"
    )
    known = root / "known_hosts"
    known.write_text(f"[127.0.0.1]:{port} " + (root / "host.pub").read_text())
    config = root / "config"
    config.write_text(
        f"Host control worker worker2\n HostName 127.0.0.1\n Port {port}\n User {pwd.getpwuid(os.getuid()).pw_name}\n IdentityFile {root / 'client'}\n IdentitiesOnly yes\n UserKnownHostsFile {known}\n StrictHostKeyChecking yes\n"
    )
    executable = shutil.which("ssh")
    daemon_executable = shutil.which("sshd")
    assert executable is not None and daemon_executable is not None
    bindir = root / "bin"
    bindir.mkdir()
    wrapper = bindir / "ssh"
    import shlex

    wrapper.write_text(
        "#!/bin/sh\nexec "
        + shlex.quote(executable)
        + " -F "
        + shlex.quote(str(config))
        + ' "$@"\n'
    )
    wrapper.chmod(0o700)
    monkeypatch.setenv("PATH", str(bindir) + ":" + os.environ["PATH"])
    log = (root / "sshd.log").open("wb")
    process = subprocess.Popen(
        [daemon_executable, "-D", "-e", "-f", str(configuration)],
        stdout=log,
        stderr=log,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail((root / "sshd.log").read_text())
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.05)
        yield root
    finally:
        process.terminate()
        process.wait(timeout=10)
        log.close()
        assert process.poll() is not None
        shutil.rmtree(authorization_root)


@pytest.fixture
def site(tmp_path, bundle, endpoint, request):
    import tempfile
    from tests.integration.queue.test_preparation_operations import _service
    from loom.queue._remote_stage_execution import (
        ResidentExecutionProfile,
        ResidentProfileDescriptor,
    )
    from loom.queue.resident_readiness import (
        qualified_resident_profile,
        ResidentReadinessRequirements,
    )
    from loom.queue.operations import inspect_native_service

    base = Path(tempfile.mkdtemp(prefix="lf7-", dir="/tmp"))
    socket_bytes = getattr(request, "param", None)
    if socket_bytes is not None:
        tmux_socket_path = base / (".loom-fleet-" + "0" * 16) / "tmux.sock"
        padding = socket_bytes - len(os.fsencode(tmux_socket_path))
        assert padding > 0
        extended = base.with_name(base.name + "x" * padding)
        assert not extended.exists()
        base.rename(extended)
        base = extended
    _service(tmp_path)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "challenge").write_bytes(b"probe-output")
    roots = {
        "outputs": {
            "host_path": str(outputs),
            "container_path": "/loom/outputs",
            "access": "rw",
            "challenge": {"path": "challenge", "sha256": sha(outputs / "challenge")},
            "publication": {
                "max_members": 1024,
                "max_payload_bytes": 128 * 1024 * 1024,
                "max_manifest_bytes": 1024 * 1024,
            },
        }
    }
    profile = qualified_resident_profile(
        ResidentExecutionProfile(
            ResidentProfileDescriptor(
                "probe", "v1", "project", "environment", "executor"
            ),
            Path(__file__).resolve().parents[3],
            Path(sys.executable),
            cpu_capacity=2,
            readiness_requirements=ResidentReadinessRequirements(
                imports=("loom", "loom.preparation", "weave")
            ),
            shared_roots=roots,
            preparation_shared_roots={"projects": tmp_path / "snapshots"},
        )
    )
    with socket.socket() as selected:
        selected.bind(("127.0.0.1", 0))
        port = selected.getsockname()[1]
    coordinator = json.loads((tmp_path / "coordinator.json").read_text())
    coordinator.update(
        local_agent=None,
        deployment_root=str(base / "c"),
        shared_roots=roots,
        assignment_payload_root_id="outputs",
        remote_profiles=[profile.descriptor.to_dict()],
    )
    coordinator["agent_server"] = {
        "host": "127.0.0.1",
        "port": port,
        "certificate_path": str(base / "tls/server.crt"),
        "private_key_path": str(base / "tls/server.key"),
        "client_ca_path": str(base / "tls/ca.crt"),
        "credential_fingerprints": {},
    }
    coordinator["agent_policy"]["principals"] = [
        {
            "credential_id": "client",
            "principal_id": "client",
            "role": "client",
            "actions": [],
            "agent_ids": [],
            "pools": [],
        },
        {
            "credential_id": "operator",
            "principal_id": "operator",
            "role": "operator",
            "actions": ["drain", "maintenance"],
            "agent_ids": ["worker", "worker2"],
            "pools": ["default"],
        },
    ]
    coordinator["agent_policy"]["local_owner"] = {
        "actions": ["scheduling_reload"],
        "agent_ids": ["worker", "worker2"],
        "pools": ["default"],
    }
    coordinator["preparation"]["profiles"]["existing-project"].update(
        resident_profile_id="probe", configuration_policy="shared", shared_locations=[]
    )
    write(tmp_path / "coordinator.json", coordinator)
    capabilities = [
        "python",
        "remote-stage-execution-v3",
        "regular-file-relay-v1",
        "shared-execution-v1",
        "shared-assignment-reference-v1",
        "preparation-input-v2",
    ]
    for name in ("worker", "worker2"):
        write(
            tmp_path
            / ("worker 'quoted';.json" if name == "worker" else name + ".json"),
            {
                "schema_version": 3,
                "kind": "loom.outbound-agent-service",
                "agent_root": str(base / name),
                "url": f"https://localhost:{port}",
                "server_ca_path": str(base / name / "../" / (name + "-tls") / "ca.crt"),
                "certificate_path": str(base / (name + "-tls") / "agent.crt"),
                "private_key_path": str(base / (name + "-tls") / "agent.key"),
                "resident_profiles": [
                    {
                        "descriptor": profile.descriptor.to_dict(),
                        "project_root": str(Path(__file__).resolve().parents[3]),
                        "python_executable": sys.executable,
                        "cpu_capacity": 2,
                        "memory_capacity_bytes": 0,
                        "gpu_devices": [],
                        "environment": {},
                        "shared_roots": roots,
                        "preparation_shared_roots": {
                            "projects": str(tmp_path / "snapshots")
                        },
                        "readiness": {"imports": ["loom", "loom.preparation", "weave"]},
                    }
                ],
                "registration": {
                    "config_revision": "config-1",
                    "inventory_revision": "inventory-1",
                    "availability_revision": "availability-1",
                    "pools": ["default"],
                    "capabilities": capabilities,
                },
                "max_concurrent_assignments": 2,
                "reconnect_seconds": 0.1,
            },
        )
    inventory = write(
        tmp_path / "fleet.json",
        {
            "schema_version": 1,
            "name": "test",
            "service_manager": "tmux",
            "runtime_release": str(bundle),
            "coordinator": {"host": "control", "config": "coordinator.json"},
            "agents": {"worker": {"host": "worker", "config": "worker 'quoted';.json"}},
        },
    )
    deployment = write(
        tmp_path / "selection.json",
        {
            "schema_version": 1,
            "kind": "loom.deployment",
            "coordinator": {
                "service_config": "coordinator.json",
                "lifetime": "persistent",
            },
            "binding_path": str(base / "creation.json"),
            "preparation": {
                "source": {
                    "mode": "shared",
                    "root": "projects",
                    "path": ".",
                    "include": ["pipeline.yaml"],
                },
                "profile": "existing-project",
            },
        },
    )
    try:
        yield (
            load_inventory(inventory),
            base,
            {"deployment": str(deployment), "config": "pipeline.yaml"},
        )
    finally:
        for log_path in [
            *base.glob(".loom-fleet-*/last-native.json"),
            *base.glob(".loom-fleet-*/service.log"),
        ]:
            print(log_path.read_text())
        pids = []
        for native in (base / "worker", base / "worker2", base / "c/coordinator"):
            observed = inspect_native_service(native)
            pid = observed.value.get("expected_process")
            if observed.value.get("ownership") == "live" and pid:
                descriptor = os.pidfd_open(cast(int, pid))
                try:
                    signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                finally:
                    os.close(descriptor)
                pids.append(pid)
        deadline = time.monotonic() + 20

        def live(pid):
            path = Path(f"/proc/{pid}/stat")
            return (
                path.exists() and path.read_text().rsplit(")", 1)[1].split()[0] != "Z"
            )

        while any(live(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not any(live(pid) for pid in pids)
        from loom.queue._agent_process_supervisor import (
            AgentProcessSupervisorClient,
            _service_configuration,
            _endpoint_for_root,
        )

        for native in (base / "worker", base / "worker2"):
            if _endpoint_for_root(native / "supervisor").exists():
                client = AgentProcessSupervisorClient(
                    native, _service_configuration(native / "supervisor")
                )
                client.shutdown_for_test()
        # Kill only fixture-owned empty sessions left by startup failure, never
        # a global tmux server. Successful native processes have already exited.
        for sock in base.glob(".loom-fleet-*/tmux.sock"):
            subprocess.run(
                ["tmux", "-S", str(sock), "kill-session", "-t", "loom"],
                capture_output=True,
            )
        shutil.rmtree(base)


def test_fresh_setup_repeat_and_selected_add_host(site, capsys):
    inventory, base, selection = site
    preview = plan(inventory, issuer=base / "issuer")
    assert all("unavailable" not in row for row in preview["hosts"].values()), preview
    assert not (base / "c").exists() and not (base / "issuer").exists()
    result = apply(
        inventory,
        operation_id="fresh",
        issuer=base / "issuer",
        check_selection=selection,
    )
    assert result["outcome"] == "complete", json.dumps(result)
    from loom.deployment import load_deployment
    from loom.queue.deployment import load_coordinator_connection_file

    exported = load_deployment(result["deployment"])
    assert (
        exported.coordinator is None
        and exported.agent is None
        and exported.binding is None
    )
    assert not (base / "creation.json").exists()
    assert exported.connection is not None
    client = load_coordinator_connection_file(exported.connection)
    operator = load_coordinator_connection_file(result["operator_connection"])
    assert (
        client.expected_coordinator_id
        == operator.expected_coordinator_id
        == result["identities"]["coordinator"]
    )
    assert client.private_key_path != operator.private_key_path
    for retained in (inventory.path.parent / "operations/fresh/steps").glob(
        "*/intent.json"
    ):
        contents = retained.read_bytes()
        for key in (
            client.private_key_path,
            operator.private_key_path,
            base / "issuer/ca.key",
            base / "worker-tls/agent.key",
        ):
            assert key.read_bytes() not in contents
    first = result["identities"]
    repeated = apply(load_inventory(inventory.path), operation_id="fresh", resume=True)
    assert repeated["outcome"] == "complete" and repeated["identities"] == first
    assert (
        repeated["checks"]["worker"]["operation_id"]
        == result["checks"]["worker"]["operation_id"]
    )
    assert operation_status(inventory, "fresh")["outcome"] == "complete"
    from loom.queue.errors import QueueConflictError

    for field, replacement in (
        ("deployment", str(inventory.path.parent / "other-deployment.json")),
        ("config", "other.yaml"),
        ("operator_connection", str(inventory.path.parent / "other-operator.json")),
        ("client_credential_id", "other-client"),
        ("operator_credential_id", "other-operator"),
    ):
        with pytest.raises(QueueConflictError, match="different selected inputs"):
            apply(
                inventory,
                operation_id="fresh",
                check_selection={**selection, field: replacement},
            )
    different_environment = inventory.path.parent / "different.env"
    different_environment.write_text("UNUSED_FLEET_VALUE=changed\n")
    different_environment.chmod(0o600)
    with pytest.raises(QueueConflictError, match="different selected inputs"):
        apply(
            inventory,
            operation_id="fresh",
            check_selection=selection,
            env_file=different_environment,
        )
    value = json.loads(inventory.path.read_text())
    value["agents"]["worker2"] = {"host": "worker2", "config": "worker2.json"}
    write(inventory.path, value)
    updated = load_inventory(inventory.path)
    preview = plan(updated, hosts=["worker2"], issuer=base / "issuer")
    assert set(preview["hosts"]) == {"coordinator", "worker2"}
    assert preview["hosts"]["coordinator"]["dependency"] is True
    with pytest.raises(QueueConflictError, match="different selected inputs"):
        apply(updated, operation_id="fresh", hosts=["worker2"], check_selection=selection)
    assert not (base / "worker2").exists()
    from loom.fleet._credentials import ensure_ca

    wrong_issuer = base / "wrong-issuer"
    wrong_issuer.mkdir(mode=0o700)
    ensure_ca(wrong_issuer, create=True)
    ca_before = (base / "issuer/ca.crt").read_bytes()
    refused = apply(
        updated,
        operation_id="wrong-issuer",
        hosts=["worker2"],
        issuer=wrong_issuer,
        check_selection={
            "deployment": result["deployment"],
            "operator_connection": result["operator_connection"],
            "config": "pipeline.yaml",
        },
    )
    assert refused["outcome"] == "blocked" and "issuer differs" in refused["reason"]
    assert (base / "issuer/ca.crt").read_bytes() == ca_before
    assert not (base / "worker2").exists()
    added = apply(
        updated,
        operation_id="add",
        hosts=["worker2"],
        issuer=base / "issuer",
        check_selection={
            "deployment": result["deployment"],
            "operator_connection": result["operator_connection"],
            "config": "pipeline.yaml",
        },
    )
    assert added["outcome"] == "complete", json.dumps(added)
    assert added["identities"]["coordinator"] == first["coordinator"]
    assert added["identities"]["worker2"] != first["worker"]
    from loom.queue.operations import inspect_native_service

    assert inspect_native_service(base / "worker").owner == first["worker"]
    from loom.cli.main import main

    release_path = inventory.runtime_release
    original_release = release_path.read_bytes()
    release_path.write_bytes(original_release + b"\n")
    try:
        assert (
            main(["fleet", "plan", "--fleet", str(inventory.path), "--hosts", "worker"])
            == 0
        )
    finally:
        release_path.write_bytes(original_release)
    assert (
        "conflict: service release change requires explicit upgrade"
        in capsys.readouterr().out
    )
    shutil.rmtree(base / "worker-tls")
    refused = apply(
        updated,
        operation_id="missing-bound-credentials",
        hosts=["worker"],
        issuer=base / "issuer",
        check_selection={
            "deployment": result["deployment"],
            "operator_connection": result["operator_connection"],
            "config": "pipeline.yaml",
        },
    )
    assert (
        refused["outcome"] == "blocked"
        and "bound agent credentials" in refused["reason"]
    )
    assert not (base / "worker-tls").exists()
    assert inspect_native_service(base / "worker").owner == first["worker"]


def test_disposable_ssh_endpoint_observes_without_writes(endpoint, tmp_path):
    from loom.fleet.ssh_operations import ssh

    result = ssh(
        "control",
        {
            "action": "inspect",
            "root": str(tmp_path / "absent"),
            "release": {"descriptor_sha256": "a" * 64},
        },
    )
    assert result["local_storage"] and not result["root_exists"]
    assert not (tmp_path / "absent").exists()


def test_dispatch_faults_resume_original_ids_and_refuse_edits_missing_root(
    site, monkeypatch
):
    import loom.fleet.ssh_operations as operations
    from loom.queue.operations import inspect_native_service

    inventory, base, selection = site
    inventory = bind_environments(inventory)
    transport = operations.ssh
    before = True
    accepted = None
    native_initializations = []
    enrollment_epoch = None

    def interrupted(host, request):
        nonlocal before, accepted, enrollment_epoch
        if before and request["action"] == "install":
            before = False
            raise operations.SshUnavailable("fixture disconnect before dispatch")
        if request["action"] == "enroll" and enrollment_epoch is None:
            from loom.fleet import _host

            admin = plan(inventory)["hosts"]["coordinator"]["observation"]["admin"]
            original_atomic = _host.atomic

            def lose_host_receipt(path, value):
                nonlocal enrollment_epoch
                if path.name == "receipt.json":
                    _, client = _host.coordinator_client(request)
                    enrollment_epoch = client.status().scheduling_epoch
                    raise OSError(
                        "fixture loss after native reload before host receipt"
                    )
                original_atomic(path, value)

            with monkeypatch.context() as scoped:
                scoped.setattr(_host, "atomic", lose_host_receipt)
                scoped.setattr(
                    sys,
                    "stdin",
                    io.TextIOWrapper(
                        io.BytesIO(json.dumps({**request, "admin": admin}).encode())
                    ),
                )
                with pytest.raises(OSError, match="after native reload"):
                    _host.main()
            raise operations.SshUnavailable(
                "fixture native acceptance without host receipt"
            )
        reply = transport(host, request)
        if request["action"] == "initialize":
            native_initializations.append(request["name"])
            if request["name"] == "coordinator" and accepted is None:
                accepted = reply["owner"]
                raise operations.SshUnavailable(
                    "fixture lost reply after actual native acceptance"
                )
        return reply

    monkeypatch.setattr(operations, "ssh", interrupted)
    result = apply(
        inventory,
        operation_id="interrupted",
        issuer=base / "issuer",
        check_selection=selection,
    )
    assert result["outcome"] == "waiting" and not (base / "c").exists()
    environment = inventory.hosts[1].env_file
    assert environment is not None
    retained_environment = environment.read_bytes()
    # Even an unused edit changes retained intent and must block replay before SSH.
    environment.write_bytes(retained_environment + b"UNUSED_BINDING=changed\n")
    with monkeypatch.context() as scoped:
        scoped.setattr(
            operations,
            "ssh",
            lambda *a, **k: pytest.fail("changed environment dispatched"),
        )
        blocked = apply(inventory, operation_id="interrupted", resume=True)
    assert blocked["outcome"] == "blocked" and "input changed" in blocked["reason"]
    environment.write_bytes(retained_environment)
    result = apply(inventory, operation_id="interrupted", resume=True)
    assert result["outcome"] == "waiting" and accepted
    assert inspect_native_service(base / "c/coordinator").owner == accepted
    result = apply(inventory, operation_id="interrupted", resume=True)
    assert result["outcome"] == "waiting" and enrollment_epoch
    result = apply(inventory, operation_id="interrupted", resume=True)
    assert result["outcome"] == "complete", json.dumps(result)
    from loom.queue.deployment import load_coordinator_service_config
    from loom.queue import LocalDaemonSocketClient

    service = load_coordinator_service_config(inventory.hosts[0].config, env_file=inventory.hosts[0].env_file)
    assert (
        LocalDaemonSocketClient(service.daemon.endpoint).status().scheduling_epoch
        == enrollment_epoch
    )
    assert result["identities"]["coordinator"] == accepted
    assert native_initializations == ["coordinator", "worker"]
    check_id = result["checks"]["worker"]["operation_id"]
    result = apply(inventory, operation_id="interrupted", resume=True)
    assert result["checks"]["worker"]["operation_id"] == check_id
    coordinator = inventory.hosts[0].config
    retained = coordinator.read_bytes()
    value = json.loads(retained)
    value["poll_interval_seconds"] = 0.025
    write(coordinator, value)
    edited = coordinator.read_bytes()
    result = apply(inventory, operation_id="interrupted", resume=True)
    assert result["outcome"] == "blocked" and "input changed" in result["reason"]
    assert coordinator.read_bytes() == edited
    coordinator.write_bytes(retained)
    # A missing DB on a stopped fixture owner must never trigger initialization.
    fact = inspect_native_service(base / "worker")
    pid = fact.value["expected_process"]
    descriptor = os.pidfd_open(cast(int, pid))
    try:
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        import select

        poller = select.poll()
        poller.register(descriptor, select.POLLIN)
        assert poller.poll(20000)
    finally:
        os.close(descriptor)
    database = base / "worker/control.sqlite"
    database.rename(database.with_suffix(".retained"))
    result = apply(inventory, operation_id="interrupted", resume=True)
    assert result["outcome"] == "blocked" and "root missing" in result["reason"]
    assert not database.exists() and native_initializations == ["coordinator", "worker"]


def test_preflight_reachable_refusals_are_read_only(site):
    from loom.queue.errors import QueueConfigError

    inventory, base, selection = site
    with pytest.raises(QueueConfigError, match="--issuer"):
        apply(inventory, operation_id="missing-issuer", check_selection=selection)
    assert not (base / "c").exists() and not list(base.glob(".loom-fleet-*"))
    authored = json.loads(Path(selection["deployment"]).read_text())
    authored["preparation"]["profile"] = "wrong-profile"
    wrong = write(inventory.path.parent / "wrong-selection.json", authored)
    with pytest.raises(QueueConfigError, match="source/profile"):
        apply(
            inventory,
            operation_id="wrong-profile",
            issuer=base / "issuer",
            check_selection={"deployment": str(wrong), "config": "pipeline.yaml"},
        )
    authored = json.loads(Path(selection["deployment"]).read_text())
    authored["preparation"]["source"]["root"] = "undeclared-source"
    wrong = write(inventory.path.parent / "wrong-source.json", authored)
    with pytest.raises(QueueConfigError, match="source/profile"):
        apply(
            inventory,
            operation_id="wrong-source",
            issuer=base / "issuer",
            check_selection={"deployment": str(wrong), "config": "pipeline.yaml"},
        )
    assert not list(base.glob(".loom-fleet-*"))
    value = json.loads(inventory.path.read_text())
    value["agents"]["worker"]["host"] = "-oProxyCommand=touch"
    write(inventory.path, value)
    with pytest.raises(QueueConfigError, match="SSH alias"):
        plan(load_inventory(inventory.path))
    assert not list(base.glob(".loom-fleet-*"))


def test_unavailable_ssh_and_network_state_roots_create_nothing(site, endpoint, capsys):
    inventory, base, selection = site
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        absent_port = probe.getsockname()[1]
    with (endpoint / "config").open("a") as stream:
        stream.write(
            f"Host unavailable\n HostName 127.0.0.1\n Port {absent_port}\n StrictHostKeyChecking yes\n"
        )
    value = json.loads(inventory.path.read_text())
    value["agents"]["worker"]["host"] = "unavailable"
    write(inventory.path, value)
    unavailable = plan(load_inventory(inventory.path), hosts=["worker"])
    assert "unavailable" in unavailable["hosts"]["worker"]
    from loom.cli.main import main

    assert (
        main(["fleet", "plan", "--fleet", str(inventory.path), "--hosts", "worker"])
        == 0
    )
    assert "unavailable: SSH returned no native receipt" in capsys.readouterr().out
    assert not list(base.glob(".loom-fleet-*"))
    value["agents"]["worker"]["host"] = "worker"
    write(inventory.path, value)
    target = Path(__file__).resolve().parents[3] / "uncreated-fleet-native-root"
    fstype = subprocess.run(
        ["findmnt", "-n", "-o", "FSTYPE", "-T", str(target.parent)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if fstype not in {"nfs", "nfs4", "cifs", "smb3", "lustre"}:
        pytest.skip("no existing network filesystem for the actual target-host refusal")
    worker = inventory.hosts[1].config
    declaration = json.loads(worker.read_text())
    declaration["agent_root"] = str(target)
    write(worker, declaration)
    result = plan(load_inventory(inventory.path), hosts=["worker"])
    assert "host-local filesystem" in result["hosts"]["worker"]["unavailable"]
    assert not target.exists() and not list(base.glob(".loom-fleet-*"))


def test_native_enrollment_preserves_ceiling_and_declared_gpu_subset(site, monkeypatch):
    """A synthetic device declaration tests transfer; it does not qualify CUDA."""
    import loom.fleet.ssh_operations as operations

    inventory, base, selection = site
    agent = inventory.hosts[1].config
    authored = json.loads(agent.read_text())
    from loom.queue._remote_stage_execution import GpuDeviceDescriptor
    from loom.serialization import thaw_plain_data

    chosen = thaw_plain_data(
        GpuDeviceDescriptor("GPU-fixture-selected", "fixture", 1024 * 1024).to_dict()
    )
    authored["resident_profiles"][0]["gpu_devices"] = [
        {"descriptor": chosen, "binding_value": "GPU-fixture-selected"}
    ]
    authored["max_concurrent_assignments"] = 7
    write(agent, authored)
    transport = operations.ssh
    initialized = None
    enrolled = None

    def stop_after_enrollment(host, request):
        nonlocal initialized, enrolled
        reply = transport(host, request)
        if request["action"] == "initialize" and request["name"] == "worker":
            initialized = reply
        if request["action"] == "enroll":
            enrolled = reply
            raise operations.SshUnavailable(
                "fixture detaches after native enrollment before any GPU job"
            )
        return reply

    monkeypatch.setattr(operations, "ssh", stop_after_enrollment)
    result = apply(
        inventory,
        operation_id="subset",
        issuer=base / "issuer",
        check_selection=selection,
    )
    assert result["outcome"] == "waiting", result
    assert initialized is not None and enrolled is not None
    assert initialized["max_concurrent_assignments"] == 7
    assert initialized["gpu_devices"] == [chosen]
    assert enrolled["reload"]["state"] == "applied"
    policy = json.loads(inventory.hosts[0].config.read_text())["agent_policy"]["agents"]
    assert [row["gpu_devices"] for row in policy if row["agent_id"] == "worker"] == [
        [chosen]
    ]
    assert not list(
        (inventory.path.parent / "operations/subset/checks").glob(
            "*/checks/*/intent.json"
        )
    )


def test_included_role_edit_after_preparation_refuses_resume(site, monkeypatch, capsys):
    import loom.fleet.ssh_operations as operations
    from loom.cli.main import main

    inventory, base, selection = site
    worker = inventory.hosts[1].config
    authored = json.loads(worker.read_text())
    profile = authored["resident_profiles"][0]
    included = write(worker.parent / "included-agent.yaml", authored)
    write(worker, {"_include_": included.name})
    assert (
        main(["fleet", "plan", "--fleet", str(inventory.path), "--hosts", "worker"])
        == 0
    )
    rendered = capsys.readouterr().out
    assert "alias: control; dependency: True" in rendered
    assert "alias: worker; dependency: False" in rendered
    assert "actions: verify immutable candidate" in rendered
    transport = operations.ssh
    prepared = False

    def interrupted(host, request):
        nonlocal prepared
        reply = transport(host, request)
        if (
            request["action"] == "prepare"
            and request["name"] == "worker"
            and not prepared
        ):
            prepared = True
            raise operations.SshUnavailable("lost worker preparation reply")
        return reply

    monkeypatch.setattr(operations, "ssh", interrupted)
    result = apply(
        inventory,
        operation_id="included",
        issuer=base / "issuer",
        check_selection=selection,
    )
    assert result["outcome"] == "waiting" and prepared
    top_bytes = worker.read_bytes()
    profile["cpu_capacity"] += 1
    write(included, authored)
    result = apply(inventory, operation_id="included", resume=True)
    assert (
        result["outcome"] == "blocked" and "composed role changed" in result["reason"]
    )
    assert worker.read_bytes() == top_bytes and not (base / "worker").exists()
