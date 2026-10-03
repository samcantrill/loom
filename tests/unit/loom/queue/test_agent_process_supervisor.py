from __future__ import annotations

import os
import hashlib
import json
import sqlite3
import sys
import subprocess
import socket
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Event
from dataclasses import replace
from pathlib import Path
from multiprocessing.connection import Client, Connection, Listener
from time import monotonic, sleep
from typing import Any, cast

import pytest

from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisor,
    AgentProcessSupervisorClient,
    AgentProcessSupervisorError,
    AgentProcessSupervisorService,
    ResidentWorkerLaunch,
    ResidentWorkerLaunchProfile,
    SupervisorLaunchState,
    SupervisorLaunchConfiguration,
    _launch_from_value,
    _launch_value,
    _receipt_from_value,
    _receipt_value,
    SupervisorReceipt,
    _SupervisorCommunicationError,
    _SupervisorDispatch,
    _serve,
)


def _profile() -> ResidentWorkerLaunchProfile:
    return ResidentWorkerLaunchProfile(
        project_root=Path.cwd(),
        python_executable=Path(sys.executable),
        descriptor={"profile_id": "default", "kind": "test-resident", "version": 1},
    )


def _launch(
    supervisor: AgentProcessSupervisor | AgentProcessSupervisorClient, workspace: Path
) -> ResidentWorkerLaunch:
    return ResidentWorkerLaunch(
        supervisor_id=supervisor.supervisor_id,
        continuity_epoch=supervisor.continuity_epoch,
        agent_id="agent-A",
        session_id="session-A",
        assignment_id="assignment-A",
        process_execution_id="process-A",
        execution_fence="fence-A",
        launch_operation_id="launch-A",
        bundle_digest="a" * 64,
        workspace_root=workspace,
        profile=_profile(),
        environment={},
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_saved_container_launch_and_receipt_decode_without_storage_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy: bool,
) -> None:
    profile = replace(_profile(), container={
        "kind": "apptainer", "container": {"image": {"reference": "/original/image.sif"}},
        "options": {"command": "/usr/bin/singularity"},
        "python_executable": "/original/bin/python", "daemon_endpoint": None,
    }, preparation_shared_roots={"projects": Path("/original/snapshots")})
    launch = ResidentWorkerLaunch(
        "owner", "epoch", "agent-A", "session-A", "assignment-A", "execution-A",
        "fence-A", "operation-A", "a" * 64, tmp_path, profile, {},
        schema_version=None if legacy else 2,
    )
    saved = _launch_value(launch)
    digest = launch.spec_digest
    receipt = _receipt_value(SupervisorReceipt(SupervisorLaunchState.NOT_ACCEPTED, launch, 0))

    def forbid(*args, **kwargs):
        raise AssertionError("saved identity decoding must not inspect storage")

    with monkeypatch.context() as blocked:
        for name in ("resolve", "exists", "is_dir", "is_file", "stat", "lstat"):
            blocked.setattr(Path, name, forbid)
        restored = _launch_from_value(saved)
        restored_receipt = _receipt_from_value(receipt)
        assert _launch_value(restored) == saved
        assert restored.spec_digest == digest
        assert _receipt_value(restored_receipt) == receipt


@pytest.mark.parametrize("missing", ["workspace", "project", "python"])
def test_new_launch_qualifies_required_local_paths_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str,
) -> None:
    agent = tmp_path / "agent"
    agent.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    profile = replace(_profile(),
        project_root=tmp_path / "absent" if missing == "project" else Path.cwd(),
        python_executable=tmp_path / "absent" if missing == "python" else Path(sys.executable))
    supervisor = AgentProcessSupervisor.initialize(agent, agent_id="agent-A", profiles=(profile,))
    launch = replace(_launch(supervisor, workspace), profile=profile,
                     workspace_root=tmp_path / "absent" if missing == "workspace" else workspace)

    def forbid_spawn(*args, **kwargs):
        raise AssertionError("unqualified input must not spawn")

    monkeypatch.setattr(subprocess, "Popen", forbid_spawn)
    with pytest.raises(AgentProcessSupervisorError, match="unavailable"):
        supervisor.launch(launch)
    with supervisor._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 0


@contextmanager
def _ipc_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profiles, retained=None):
    """Real authenticated IPC with injectable backends and creation-owned groups."""
    agent = tmp_path / "agent"
    agent.mkdir()
    configuration = SupervisorLaunchConfiguration("agent-A", tuple(profiles))
    AgentProcessSupervisorService.initialize_process_free(agent, configuration=configuration)
    if retained is not None:
        retained(AgentProcessSupervisor(
            agent / "supervisor", agent_id=configuration.agent_id, profiles=configuration.profiles,
        ))
    dispatches = []

    def dispatch(supervisor):
        value = _SupervisorDispatch(supervisor)
        dispatches.append(value)
        return value

    monkeypatch.setattr("loom.queue._agent_process_supervisor._SupervisorDispatch", dispatch)
    server = threading.Thread(target=_serve, args=(agent / "supervisor",), daemon=True)
    server.start()
    deadline = monotonic() + 5
    while True:
        try:
            client = AgentProcessSupervisorClient(agent, configuration)
            break
        except AgentProcessSupervisorError:
            assert monotonic() < deadline
            sleep(0.01)
    owner = dispatches[0].supervisor
    try:
        yield client, owner, dispatches[0]
    finally:
        with owner._connect() as conn:
            launches = [_launch_from_value(json.loads(row[0])) for row in conn.execute(
                "SELECT launch_json FROM launches"
            )]
        for launch in launches:
            assert client.contain(launch).state is SupervisorLaunchState.CONTAINED
        for child in owner._children.values():
            assert child.settled()
            assert child._process.returncode is not None
        assert not owner._namespace_inits
        client._call("shutdown_clean", None)
        server.join(timeout=5)
        assert not server.is_alive()
        assert not client._endpoint.exists()


def _sleeping_profile(tmp_path: Path) -> ResidentWorkerLaunchProfile:
    executable = tmp_path / "held-worker"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    executable.chmod(0o700)
    return replace(_profile(), python_executable=executable)


def _named_launch(client, tmp_path, profile, name):
    workspace = tmp_path / name
    workspace.mkdir()
    return replace(
        _launch(client, workspace), profile=profile, assignment_id=name,
        launch_operation_id="launch-" + name, process_execution_id="process-" + name,
    )


def _shared_container_request(tmp_path, *, backend="apptainer"):
    from loom.pipeline.planning import StageFingerprintRecord
    from loom.queue.shared_execution import SHARED_EXECUTION_SCOPE, qualifications, stage_scope
    from tests.unit.loom.queue.test_remote_stage_execution import _profile as resident_profile, _request

    data = tmp_path / "input-tree"
    data.mkdir()
    (data / "challenge").write_bytes(b"shared")
    (data / "payload.bin").write_bytes(b"synthetic input")
    roots = {"data": {"host_path": str(data), "container_path": "/loom/data", "access": "ro",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"shared").hexdigest()}}}
    (tmp_path / "fixture.sif").write_bytes(b"synthetic container image")
    profile = replace(resident_profile(tmp_path), shared_roots=roots, container={
        "kind": backend, "container": {"image": {"reference": str(tmp_path / "fixture.sif")
            if backend == "apptainer" else "sha256:" + "a" * 64}},
        "options": {"command": sys.executable}, "python_executable": "/container/python",
        "daemon_endpoint": None if backend == "apptainer" else "unix:///fixture",
    })
    request = _request(profile)
    selection = {"input": {"kind": "loom.shared-location", "schema_version": 1,
                           "root_id": "data", "path": "."}}
    selected = stage_scope(selection, {}, {"roots": qualifications(roots)})
    fingerprint = StageFingerprintRecord.from_dict(request.fingerprint)
    request = replace(request, resolved_runtime={**request.resolved_runtime,
        "resources": {"schema_version": 2, "entries": {}}}, fingerprint=StageFingerprintRecord.create(
            algorithm=fingerprint.algorithm,
            payload=replace(fingerprint.payload, fingerprint_fields={SHARED_EXECUTION_SCOPE: selected}),
            inputs_summary=fingerprint.inputs_summary,
        ).to_dict())
    return profile, request, data


def _retain_shared_launch(client, tmp_path, resident, request, *, project_controls=True):
    from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace
    from loom.pipeline.runtime._resource_controls import _validated_resource_controls

    workspace = _ResidentAssignmentWorkspace(tmp_path / "agent", request.assignment_id)
    workspace.persist_request(request, resident)
    workspace.stage_input("input-1", b"input")
    workspace.accept()
    workspace.grant("fence-A")
    launch = replace(_launch(client, workspace.root), assignment_id=request.assignment_id,
                     profile=resident.launch_profile,
                     bundle_digest=hashlib.sha256(json.dumps(request.to_dict(), sort_keys=True,
                         separators=(",", ":")).encode()).hexdigest())
    if not project_controls:
        return launch
    return replace(launch, resource_controls=_validated_resource_controls(
        launch.container_command.metadata.get("resource_controls")))


@pytest.mark.parametrize("damage", ["missing", "challenge", "special", "controls", "gpu_binding"])
def test_shared_new_launch_qualification_rejects_before_spawning(tmp_path, monkeypatch, damage):
    resident, request, data = _shared_container_request(tmp_path)
    if damage == "gpu_binding":
        request = replace(request, resolved_runtime={**request.resolved_runtime,
            "resources": {"schema_version": 2, "entries": {
                "gpu": {"kind": "gpu", "amount": 1, "unit": "count", "attributes": {}}}},
            "resource_policy": {"account_for": "all", "enforce": ["gpu"]},
            "resource_selection": {"account_for": ["gpu"], "enforce": ["gpu"]}})
    agent = tmp_path / "agent"
    agent.mkdir()
    supervisor = AgentProcessSupervisor.initialize(agent, agent_id="agent-A", profiles=(resident.launch_profile,))
    launch = _retain_shared_launch(supervisor, tmp_path, resident, request,
                                  project_controls=damage != "gpu_binding")
    if damage == "missing":
        data.rename(tmp_path / "unavailable")
    elif damage == "challenge":
        (data / "challenge").write_bytes(b"changed")
    elif damage == "special":
        os.mkfifo(data / "unsupported-pipe")
    elif damage == "controls":
        launch = replace(launch, resource_controls=None)

    def forbid(*args, **kwargs):
        raise AssertionError("unqualified shared launch must not spawn")

    monkeypatch.setattr(subprocess, "Popen", forbid)
    from loom.queue._agent_process_supervisor import _SupervisorNoStartError
    with pytest.raises(_SupervisorNoStartError):
        supervisor.launch(launch)
    with supervisor._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 0


def test_shared_docker_replay_observes_without_original_inputs_or_new_container(tmp_path, monkeypatch):
    from loom.queue._docker_worker import DockerWorker
    from tests.unit.loom.queue.test_docker_worker import Daemon

    resident, request, data = _shared_container_request(tmp_path, backend="docker")
    daemon = Daemon()
    monkeypatch.setattr(DockerWorker, "_run", lambda owner, *args: daemon((*owner.prefix, *args)))
    agent = tmp_path / "agent"
    agent.mkdir()
    supervisor = AgentProcessSupervisor.initialize(agent, agent_id="agent-A", profiles=(resident.launch_profile,))
    launch = _retain_shared_launch(supervisor, tmp_path, resident, request)
    started = supervisor.launch(launch)
    assert started.state is SupervisorLaunchState.RUNNING
    data.rename(tmp_path / "unavailable")

    def forbid(*args, **kwargs):
        raise AssertionError("retained Docker observation must not qualify inputs")

    monkeypatch.setattr(os, "walk", forbid)
    assert supervisor.query(launch).backend_id == started.backend_id
    assert supervisor.launch(launch).backend_id == started.backend_id
    assert sum(call[0] == "create" for call in daemon.calls) == 1
    assert sum(call[0] == "start" for call in daemon.calls) == 1
    daemon.finish()
    assert supervisor.contain(launch).state is SupervisorLaunchState.CONTAINED


def test_accepted_docker_launch_without_backend_intent_never_creates_on_replay(tmp_path, monkeypatch):
    from loom.queue._docker_worker import DockerWorker
    from tests.unit.loom.queue.test_docker_worker import Daemon

    resident, request, data = _shared_container_request(tmp_path, backend="docker")
    daemon = Daemon()
    monkeypatch.setattr(DockerWorker, "_run", lambda owner, *args: daemon((*owner.prefix, *args)))
    agent = tmp_path / "agent"
    agent.mkdir()
    supervisor = AgentProcessSupervisor.initialize(agent, agent_id="agent-A", profiles=(resident.launch_profile,))
    launch = _retain_shared_launch(supervisor, tmp_path, resident, request)
    original = DockerWorker.launch

    def interrupted(owner):
        raise RuntimeError("owner interrupted before backend intent")

    monkeypatch.setattr(DockerWorker, "launch", interrupted)
    with pytest.raises(RuntimeError, match="before backend intent"):
        supervisor.launch(launch)
    monkeypatch.setattr(DockerWorker, "launch", original)
    data.rename(tmp_path / "unavailable")
    from loom.queue import _container_worker

    def forbid_preparation(*args, **kwargs):
        raise AssertionError("accepted Docker replay must not prepare writable paths")

    monkeypatch.setattr(_container_worker, "prepare_container_worker_paths", forbid_preparation)
    assert supervisor.query(launch).state is SupervisorLaunchState.STARTING
    assert supervisor.launch(launch).state is SupervisorLaunchState.STARTING
    assert supervisor.reject_unstarted_assignment(launch.assignment_id) is False
    assert daemon.calls == []


def test_real_shared_tree_qualification_does_not_block_other_ipc_control(tmp_path, monkeypatch):
    resident, request, _ = _shared_container_request(tmp_path)
    other_profile = _sleeping_profile(tmp_path)
    entered = Event()
    release = Event()
    original_walk = os.walk
    original_spawn = subprocess.Popen
    container_spawns = []

    def blocked_walk(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        yield from original_walk(*args, **kwargs)

    def spawn(argv, **kwargs):
        if argv[0] == sys.executable:
            container_spawns.append(tuple(argv))
            return original_spawn((str(other_profile.python_executable),), **kwargs)
        return original_spawn(argv, **kwargs)

    with _ipc_owner(tmp_path, monkeypatch, (other_profile, resident.launch_profile)) as (client, _, _):
        other = _named_launch(client, tmp_path, other_profile, "other")
        client.launch(other)
        launch = _retain_shared_launch(client, tmp_path, resident, request)
        monkeypatch.setattr(os, "walk", blocked_walk)
        monkeypatch.setattr(subprocess, "Popen", spawn)
        monkeypatch.setattr("loom.pipeline.executors.apptainer._timeout._capture_init",
                            lambda process, group: os.pidfd_open(process.pid))
        try:
            client._call("launch", _launch_value(launch))
            assert entered.wait(3)
            assert client.query(other).state is SupervisorLaunchState.RUNNING
            assert client.request_stop(other).state is SupervisorLaunchState.RUNNING
            assert not release.is_set()
            assert container_spawns == []
        finally:
            release.set()
        started = client.launch(launch)
        assert started.state is SupervisorLaunchState.RUNNING
        assert client.launch(launch).process_id == started.process_id
        assert len(container_spawns) == 1


@pytest.mark.parametrize("held", ["spawn", "namespace", "contain"])
def test_ipc_slow_saturation_preserves_query_stop_and_exact_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held: str,
) -> None:
    from types import SimpleNamespace
    from loom.pipeline.executors.apptainer import _timeout
    from loom.queue._process_group import OwnedProcessGroup

    profile = _sleeping_profile(tmp_path)
    container = replace(profile, descriptor={"profile_id": "container"}, container={
        "kind": "apptainer", "container": {"image": {"reference": "/fixture.sif"}},
        "options": {"command": "/fake-apptainer"},
        "python_executable": sys.executable, "daemon_endpoint": None,
    })
    monkeypatch.setattr(ResidentWorkerLaunch, "container_command", property(
        lambda self: SimpleNamespace(argv=(str(profile.python_executable),), metadata={})
    ))
    release = Event()
    reached = [Event(), Event()]
    calls = []
    original_spawn = subprocess.Popen
    original_contain = OwnedProcessGroup.contain
    held_pids = set()

    def hold():
        index = len(calls)
        calls.append(index)
        assert index < 2, "a third physical effect was submitted"
        reached[index].set()
        assert release.wait(10)

    def spawn(*args, **kwargs):
        if held == "spawn" and not release.is_set():
            hold()
        return original_spawn(*args, **kwargs)

    def capture(process, group):
        if held == "namespace":
            hold()
        return os.pidfd_open(process.pid)

    def contain(group):
        if held == "contain" and group.pid in held_pids and not release.is_set():
            hold()
        return original_contain(group)

    monkeypatch.setattr(_timeout, "_capture_init", capture)
    monkeypatch.setattr(OwnedProcessGroup, "contain", contain)
    with _ipc_owner(tmp_path, monkeypatch, (profile, container)) as (client, owner, dispatch):
        b = _named_launch(client, tmp_path, profile, "B")
        d = _named_launch(client, tmp_path, profile, "D")
        client.launch(b)
        client.launch(d)
        slow_profile = container if held == "namespace" else profile
        a = _named_launch(client, tmp_path, slow_profile, "A")
        c = _named_launch(client, tmp_path, slow_profile, "C")
        if held == "contain":
            held_pids.update((client.launch(a).process_id, client.launch(c).process_id))
        monkeypatch.setattr("loom.queue._agent_process_supervisor.subprocess.Popen", spawn)
        try:
            operation = "contain" if held == "contain" else "launch"
            client._call(operation, _launch_value(a))
            assert reached[0].wait(3)
            client._call(operation, _launch_value(c))
            assert reached[1].wait(3)
            assert dispatch.active == 2
            assert client.query(b).state is SupervisorLaunchState.RUNNING
            assert client.request_stop(b).state is SupervisorLaunchState.RUNNING
            assert client.query(d).state is SupervisorLaunchState.RUNNING
            assert owner._children[d.launch_operation_id].root_status() is None
            assert client.query(a).state is SupervisorLaunchState.STARTING
            if held == "spawn":
                assert a.launch_operation_id not in owner._children
            assert client.reject_unstarted_assignment(a.assignment_id) is False
            with pytest.raises(AgentProcessSupervisorError, match="conflicts"):
                client._call("launch", _launch_value(replace(a, execution_fence="other")))
            extra = _named_launch(client, tmp_path, profile, "unadmitted")
            for _ in range(12):
                assert _receipt_from_value(client._call("launch", _launch_value(extra))).state is SupervisorLaunchState.NOT_ACCEPTED
                assert client.request_stop(a).state is SupervisorLaunchState.STARTING
                assert _receipt_from_value(client._call("contain", _launch_value(b))).state is SupervisorLaunchState.STARTING
            assert len(calls) == 2
            assert extra.launch_operation_id not in dispatch.operations
            assert dispatch.active == 2
            with owner._connect() as conn:
                assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 4
            with pytest.raises(AgentProcessSupervisorError, match="in-flight"):
                client._call("shutdown_clean", None)
            with pytest.raises(AgentProcessSupervisorError, match="requires clean shutdown"):
                owner.rotate_clean_continuity()
        finally:
            release.set()
        # Joining happens outside dispatch, and duplicate launches retain one
        # creation-owned root even when stop won during accepted STARTING.
        if held != "contain":
            started = client.launch(a)
            assert started.process_id == owner._children[a.launch_operation_id].pid
            assert client.launch(a).process_id == started.process_id
        assert client.contain(a).state is SupervisorLaunchState.CONTAINED
        assert client.contain(b).state is SupervisorLaunchState.CONTAINED
        assert owner._children[d.launch_operation_id].root_status() is None


def test_ipc_request_admission_is_bounded_before_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.queue._agent_process_supervisor as module

    with _ipc_owner(tmp_path, monkeypatch, (_profile(),)) as (client, _, dispatch):
        original = module.deliver_challenge
        admitted = []
        release = Event()

        def hold(connection, secret):
            admitted.append(connection)
            assert release.wait(5)
            return original(connection, secret)

        monkeypatch.setattr(module, "deliver_challenge", hold)
        peers = []
        try:
            for _ in range(4):
                peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                peer.settimeout(2)
                peer.connect(str(client._endpoint))
                peers.append(peer)
            deadline = monotonic() + 3
            while len(admitted) != 4:
                assert monotonic() < deadline
                sleep(0.01)
            for _ in range(12):
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as extra:
                    extra.settimeout(2)
                    extra.connect(str(client._endpoint))
                    assert extra.recv(1) == b""
            assert len(admitted) == 4
            assert dispatch.active == 0
        finally:
            monkeypatch.setattr(module, "deliver_challenge", original)
            for peer in peers:
                peer.close()
            release.set()
        deadline = monotonic() + 3
        while True:
            try:
                assert client.status()["supervisor_id"] == client.supervisor_id
                break
            except AgentProcessSupervisorError:
                assert monotonic() < deadline
                sleep(0.01)


def test_ipc_docker_waits_use_slow_capacity_and_coalesce_exact_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from loom.queue._docker_worker import DockerWorker
    from tests.unit.loom.queue.test_docker_worker import Daemon

    native = _sleeping_profile(tmp_path)
    docker = replace(native, descriptor={"profile_id": "docker"}, container={
        "kind": "docker", "container": {"image": {"reference": "sha256:" + "a" * 64}},
        "options": {"command": "/docker"}, "python_executable": sys.executable,
        "daemon_endpoint": "unix:///fixture",
    })
    monkeypatch.setattr(ResidentWorkerLaunch, "container_command", property(
        lambda self: SimpleNamespace(argv=("/docker", "run", "image", "python"), metadata={})
    ))
    daemons = {}
    release = Event()
    reached = {"launch-A": Event(), "launch-C": Event()}
    holding = False
    held_calls = []

    def call(owner, *args):
        if holding and not release.is_set() and args[0] == "inspect":
            held_calls.append(owner.operation_id)
            assert owner.operation_id in reached, "third backend operation submitted"
            reached[owner.operation_id].set()
            assert release.wait(10)
        daemon = daemons.setdefault(owner.operation_id, Daemon())
        return daemon((*owner.prefix, *args))

    monkeypatch.setattr(DockerWorker, "_run", call)
    with _ipc_owner(tmp_path, monkeypatch, (native, docker)) as (client, owner, dispatch):
        launches = {name: _named_launch(client, tmp_path, docker, name) for name in ("A", "C", "E")}
        for launch in launches.values():
            assert client.launch(launch).backend_id == "immutable-id"
        b = _named_launch(client, tmp_path, native, "B")
        d = _named_launch(client, tmp_path, native, "D")
        client.launch(b)
        client.launch(d)
        holding = True
        try:
            assert client.query(launches["A"]).state is SupervisorLaunchState.STARTING
            assert reached["launch-A"].wait(3)
            assert client.request_stop(launches["C"]).state is SupervisorLaunchState.STARTING
            assert reached["launch-C"].wait(3)
            assert client.query(b).state is SupervisorLaunchState.RUNNING
            assert client.request_stop(b).state is SupervisorLaunchState.RUNNING
            assert client.query(d).state is SupervisorLaunchState.RUNNING
            for _ in range(12):
                assert client.request_stop(launches["E"]).state is SupervisorLaunchState.STARTING
                assert _receipt_from_value(client._call("contain", _launch_value(launches["C"]))).state is SupervisorLaunchState.STARTING
            assert dispatch.active == 2
            assert held_calls == ["launch-A", "launch-C"]
            assert dispatch.operations["launch-E"].stop
            assert not any(call[0] == "kill" for call in daemons["launch-E"].calls)
            with pytest.raises(AgentProcessSupervisorError, match="in-flight"):
                client._call("shutdown", None)
        finally:
            release.set()
        client.request_stop(launches["A"])
        for launch in launches.values():
            receipt = client.contain(launch)
            assert receipt.state is SupervisorLaunchState.CONTAINED
            assert not receipt.qualified_success
            daemon = daemons[launch.launch_operation_id]
            assert sum(call[0] == "create" for call in daemon.calls) == 1
            assert sum(call[0] == "start" for call in daemon.calls) == 1
            assert daemon.container is None
        assert owner._children[d.launch_operation_id].root_status() is None


def test_accepted_launch_lost_reply_keeps_owner_and_other_ipc_requests_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.queue._agent_process_supervisor as module

    profile = _sleeping_profile(tmp_path)
    with _ipc_owner(tmp_path, monkeypatch, (profile,)) as (client, owner, dispatch):
        a = _named_launch(client, tmp_path, profile, "A")
        b = _named_launch(client, tmp_path, profile, "B")
        client.launch(b)
        reply_held = Event()
        release = Event()
        send = module._send_supervisor_reply

        def lose_reply(connection, response):
            value = response.get("value")
            if (isinstance(value, dict) and value.get("process_id") is not None
                and value.get("launch", {}).get("launch_operation_id") == a.launch_operation_id
                and not reply_held.is_set()):
                reply_held.set()
                assert release.wait(5)
            send(connection, response)

        monkeypatch.setattr(module, "_send_supervisor_reply", lose_reply)
        impatient = AgentProcessSupervisorClient(tmp_path / "agent", client._configuration)
        impatient._EXCHANGE_TIMEOUT = 0.2
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                attempt = pool.submit(impatient.launch, a)
                assert reply_held.wait(3)
                with pytest.raises(_SupervisorCommunicationError) as failure:
                    attempt.result(timeout=2)
                assert failure.value.possibly_dispatched
            root = owner._children[a.launch_operation_id]
            assert root.root_status() is None
            assert client.query(b).state is SupervisorLaunchState.RUNNING
            assert client.request_stop(b).state is SupervisorLaunchState.RUNNING
            assert client.launch(a).process_id == root.pid
            assert len(owner._children) == 2
            assert dispatch.active == 0
            with pytest.raises(AgentProcessSupervisorError, match="in-flight requests"):
                client._call("shutdown_clean", None)
        finally:
            release.set()


@pytest.mark.parametrize("operation", ["query", "launch"])
def test_reopened_docker_pending_query_requires_fresh_backend_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    from types import SimpleNamespace
    from loom.queue._docker_worker import DockerWorker
    from tests.unit.loom.queue.test_docker_worker import Daemon

    profile = replace(_profile(), container={
        "kind": "docker", "container": {"image": {"reference": "sha256:" + "a" * 64}},
        "options": {"command": "/docker"}, "python_executable": sys.executable,
        "daemon_endpoint": "unix:///fixture",
    })
    monkeypatch.setattr(ResidentWorkerLaunch, "container_command", property(
        lambda self: SimpleNamespace(argv=("/docker", "run", "image", "python"), metadata={})
    ))
    daemon = Daemon()
    reached = Event()
    release = Event()
    unavailable = Event()
    launches = []

    def call(owner, *args):
        if launches and args[0] == "inspect" and not release.is_set():
            reached.set()
            assert release.wait(5)
        if unavailable.is_set():
            return None
        return daemon((*owner.prefix, *args))

    def retain(owner):
        launch = _named_launch(owner, tmp_path, profile, "retained")
        assert owner.launch(launch).state is SupervisorLaunchState.RUNNING
        launches.append(launch)

    monkeypatch.setattr(DockerWorker, "_run", call)
    with _ipc_owner(tmp_path, monkeypatch, (profile,), retained=retain) as (client, _, dispatch):
        launch = launches[0]
        unavailable.set()
        try:
            with pytest.raises(AgentProcessSupervisorError, match="pending without fresh ownership"):
                client._call(operation, _launch_value(launch))
            assert reached.wait(3)
            assert dispatch.active == 1
            with ThreadPoolExecutor(max_workers=1) as workers:
                joined = workers.submit(client.launch if operation == "launch" else client.query_wait, launch)
                try:
                    with pytest.raises(AgentProcessSupervisorError, match="pending without fresh ownership"):
                        client._call("launch", _launch_value(launch))
                    with pytest.raises(AgentProcessSupervisorError, match="pending without fresh ownership"):
                        client.query(launch)
                    assert not joined.done()
                finally:
                    release.set()
                receipt = joined.result(timeout=3)
            assert receipt.state is SupervisorLaunchState.UNKNOWN
            assert not dispatch.operations[launch.launch_operation_id].observed
            unavailable.clear()
            receipt = client.query_wait(launch)
            assert receipt.state is SupervisorLaunchState.RUNNING
            assert receipt.backend_id == "immutable-id"
            assert sum(call[0] == "create" for call in daemon.calls) == 1
            assert sum(call[0] == "start" for call in daemon.calls) == 1
        finally:
            release.set()
            unavailable.clear()
            client.request_stop_wait(launch)
            assert client.contain(launch).state is SupervisorLaunchState.CONTAINED


def test_failed_launch_with_owned_child_cannot_leave_a_live_starting_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from loom.pipeline.executors.apptainer import _timeout

    native = _sleeping_profile(tmp_path)
    profile = replace(native, descriptor={"profile_id": "container"}, container={
        "kind": "apptainer", "container": {"image": {"reference": "/fixture.sif"}},
        "options": {"command": "/fake-apptainer"},
        "python_executable": sys.executable, "daemon_endpoint": None,
    })
    monkeypatch.setattr(ResidentWorkerLaunch, "container_command", property(
        lambda self: SimpleNamespace(argv=(str(native.python_executable),), metadata={})
    ))
    monkeypatch.setattr(_timeout, "_capture_init", lambda process, group: os.pidfd_open(process.pid))
    write_text = Path.write_text

    def fail_grant(path, *args, **kwargs):
        if path.name == "run.grant" and path.parent.name == "A":
            raise PermissionError("workspace grant unavailable")
        return write_text(path, *args, **kwargs)

    with _ipc_owner(tmp_path, monkeypatch, (native, profile)) as (client, owner, dispatch):
        a = _named_launch(client, tmp_path, profile, "A")
        b = _named_launch(client, tmp_path, native, "B")
        client.launch(b)
        monkeypatch.setattr(Path, "write_text", fail_grant)
        with pytest.raises(_SupervisorCommunicationError):
            client.launch(a)
        assert dispatch.active == 0
        child = owner._children[a.launch_operation_id]
        assert child.root_status() is None
        assert client.request_stop_wait(a).state is SupervisorLaunchState.UNKNOWN
        assert client.query_wait(a).state is SupervisorLaunchState.UNKNOWN
        assert client.launch(a).state is SupervisorLaunchState.UNKNOWN
        assert owner._children[a.launch_operation_id] is child
        assert client.query(b).state is SupervisorLaunchState.RUNNING
        assert client.contain(a).state is SupervisorLaunchState.CONTAINED
        assert child.settled()


def test_legacy_launch_writer_shape_and_digest_are_preserved(tmp_path: Path) -> None:
    profile = _profile()
    legacy_profile = {
        "project_root": str(profile.project_root),
        "python_executable": str(profile.python_executable),
        "descriptor": dict(profile.descriptor),
        "environment": {},
        "readiness_identity": None,
    }
    legacy = {
        "supervisor_id": "supervisor-A",
        "continuity_epoch": "epoch-A",
        "agent_id": "agent-A",
        "session_id": "session-A",
        "assignment_id": "assignment-A",
        "process_execution_id": "process-A",
        "execution_fence": "fence-A",
        "launch_operation_id": "launch-A",
        "bundle_digest": "a" * 64,
        "workspace_root": str(tmp_path.resolve()),
        "profile": legacy_profile,
        "environment": {"LANG": "C.UTF-8"},
    }
    old_digest_input = {
        **legacy,
        "profile_id": profile.profile_id,
        "profile_fingerprint": profile.fingerprint,
    }
    old_digest = hashlib.sha256(
        json.dumps(
            old_digest_input, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()

    decoded = _launch_from_value(json.loads(json.dumps(legacy)))
    assert decoded.schema_version is None
    assert decoded.resource_controls is None
    assert _launch_value(decoded) == legacy
    assert decoded.spec_digest == old_digest

    controls = (
        {
            "resource": "gpu",
            "owner": "managed_provider",
            "mechanism": "provider_environment_binding",
            "disposition": "requested",
        },
    )
    current = replace(decoded, schema_version=2, resource_controls=controls)
    current_value = _launch_value(current)
    assert current_value["schema_version"] == 2
    assert _launch_from_value(current_value).spec_digest == current.spec_digest
    assert current.spec_digest != old_digest
    assert replace(current, resource_controls=()).spec_digest != current.spec_digest
    with pytest.raises(AgentProcessSupervisorError, match="legacy"):
        replace(decoded, resource_controls=controls)
    with pytest.raises(AgentProcessSupervisorError, match="invalid fields"):
        _launch_from_value(
            {
                **current_value,
                "resource_controls": [{**controls[0], "binding": "private-gpu"}],
            }
        )


def test_launch_exact_replay_has_one_root_and_conflicting_identity_rejects(
    tmp_path: Path,
) -> None:
    (tmp_path / "agent").mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        tmp_path / "agent", agent_id="agent-A", profiles=(_profile(),)
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launch = _launch(supervisor, workspace)

    # The fixed worker can fail without a real staged request; this test owns the
    # supervisor's one-root acceptance invariant, not worker semantics.
    first = supervisor.launch(launch)
    replay = supervisor.launch(launch)

    assert first.process_id == replay.process_id
    assert replay.state is SupervisorLaunchState.RUNNING
    with pytest.raises(AgentProcessSupervisorError, match="conflicts"):
        supervisor.launch(replace(launch, execution_fence="different-fence"))
    with pytest.raises(AgentProcessSupervisorError, match="conflicts"):
        supervisor.launch(replace(launch, bundle_digest="b" * 64))


def test_reopened_supervisor_does_not_adopt_nonterminal_pid(tmp_path: Path) -> None:
    profile = _profile()
    (tmp_path / "agent").mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        tmp_path / "agent", agent_id="agent-A", profiles=(profile,)
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launch = _launch(supervisor, workspace)
    supervisor.launch(launch)

    reopened = AgentProcessSupervisor(
        tmp_path / "agent" / "supervisor", agent_id="agent-A", profiles=(profile,)
    )

    assert reopened.query(launch).state is SupervisorLaunchState.UNKNOWN
    assert reopened.reject_unstarted_assignment(launch.assignment_id) is False
    with pytest.raises(AgentProcessSupervisorError, match="requires clean shutdown"):
        reopened.rotate_clean_continuity()
    assert supervisor.contain(launch).state is SupervisorLaunchState.CONTAINED
    assert supervisor.reject_unstarted_assignment(launch.assignment_id) is False


def test_rejection_is_durable_and_blocks_all_assignment_launches(tmp_path: Path) -> None:
    agent_root = tmp_path / "agent"
    agent_root.mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        agent_root, agent_id="agent-A", profiles=(_profile(),)
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launch = _launch(supervisor, workspace)
    assert supervisor.reject_unstarted_assignment(launch.assignment_id) is True
    reopened = AgentProcessSupervisor(
        agent_root / "supervisor", agent_id="agent-A", profiles=(_profile(),)
    )
    assert reopened.reject_unstarted_assignment(launch.assignment_id) is True
    for value in (launch, replace(launch, launch_operation_id="different-operation",
                                 execution_fence="different-fence")):
        with pytest.raises(AgentProcessSupervisorError, match="durably rejected"):
            reopened.launch(value)
    with sqlite3.connect(agent_root / "supervisor/supervisor.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 0


def test_supervisor_v4_migrates_rejection_state(tmp_path: Path) -> None:
    agent_root = tmp_path / "agent"
    agent_root.mkdir()
    original = AgentProcessSupervisor.initialize(
        agent_root, agent_id="agent-A", profiles=(_profile(),)
    )
    with sqlite3.connect(agent_root / "supervisor/supervisor.sqlite") as conn:
        conn.execute("DROP TABLE rejected_assignments")
        conn.execute("UPDATE metadata SET value = '4' WHERE key = 'schema_version'")
    migrated = AgentProcessSupervisor(
        agent_root / "supervisor", agent_id="agent-A", profiles=(_profile(),)
    )
    assert migrated.supervisor_id == original.supervisor_id
    assert migrated.continuity_epoch == original.continuity_epoch
    assert migrated.reject_unstarted_assignment("assignment-A") is True


def test_launch_and_rejection_have_only_one_winner(tmp_path: Path) -> None:
    agent_root = tmp_path / "agent"
    agent_root.mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        agent_root, agent_id="agent-A", profiles=(_profile(),)
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launch = _launch(supervisor, workspace)
    barrier = Barrier(2)

    def start():
        barrier.wait(timeout=5)
        try:
            return supervisor.launch(launch)
        except AgentProcessSupervisorError as exc:
            assert "durably rejected" in str(exc)
            return None

    def reject():
        barrier.wait(timeout=5)
        return supervisor.reject_unstarted_assignment(launch.assignment_id)

    with ThreadPoolExecutor(max_workers=2) as workers:
        started = workers.submit(start)
        rejected = workers.submit(reject)
        receipt, proof = started.result(timeout=10), rejected.result(timeout=10)
    assert (receipt is None) is proof
    if receipt is not None:
        deadline = monotonic() + 5
        while supervisor.contain(launch).state is not SupervisorLaunchState.CONTAINED:
            assert monotonic() < deadline
            sleep(0.01)


def test_rejection_service_requires_current_owner_identity(tmp_path: Path) -> None:
    agent_root = tmp_path / "agent"
    agent_root.mkdir()
    client = AgentProcessSupervisorService.initialize(
        agent_root, configuration=SupervisorLaunchConfiguration("agent-A", (_profile(),))
    )
    try:
        epoch = client.continuity_epoch
        client.continuity_epoch = "stale-epoch"
        with pytest.raises(AgentProcessSupervisorError, match="identity is stale"):
            client.reject_unstarted_assignment("assignment-A")
        with sqlite3.connect(agent_root / "supervisor/supervisor.sqlite") as conn:
            assert conn.execute("SELECT COUNT(*) FROM rejected_assignments").fetchone()[0] == 0
        client.continuity_epoch = epoch
        assert client.reject_unstarted_assignment("assignment-A") is True
        assert client.reject_unstarted_assignment("assignment-A") is True
        (tmp_path / "workspace").mkdir()
        with pytest.raises(AgentProcessSupervisorError, match="durably rejected"):
            client.launch(_launch(client, tmp_path / "workspace"))
    finally:
        client.shutdown_for_test()


def test_contain_reaps_its_leader_but_waits_for_a_term_ignoring_descendant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _profile()
    (tmp_path / "agent").mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        tmp_path / "agent", agent_id="agent-A", profiles=(profile,)
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launch = _launch(supervisor, workspace)
    original_popen = subprocess.Popen
    ready = workspace / "child-ready"
    child_code = (
        "import os, signal, time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"Path({str(ready)!r}).write_text(str(os.getpid())); time.sleep(30)"
    )

    def start_root(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        return cast(
            Any,
            original_popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import subprocess, sys, time; "
                        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
                        "time.sleep(30)"
                    ),
                ],
                **kwargs,
            ),
        )

    monkeypatch.setattr(
        "loom.queue._agent_process_supervisor.subprocess.Popen", start_root
    )
    supervisor.launch(launch)
    deadline = monotonic() + 3
    try:
        while not ready.exists():
            assert monotonic() < deadline
            sleep(0.01)
        child_fd = os.pidfd_open(int(ready.read_text()))
        try:
            import select

            assert not select.select([child_fd], [], [], 0)[0]
            assert supervisor.contain(launch).state is SupervisorLaunchState.CONTAINED
            assert select.select([child_fd], [], [], 0)[0]
            assert supervisor.contain(launch).state is SupervisorLaunchState.CONTAINED
        finally:
            os.close(child_fd)
    finally:
        supervisor.contain(launch)


@pytest.mark.parametrize("signal_error", [ProcessLookupError, PermissionError])
def test_apptainer_namespace_signal_race_preserves_supervisor_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signal_error: type[OSError]
) -> None:
    import select
    import signal
    from types import SimpleNamespace

    from examples.execution.containers.apptainer_fixture import fake_apptainer

    with fake_apptainer() as binding:
        profile = replace(_profile(), container=binding)
        monkeypatch.setattr(
            ResidentWorkerLaunch,
            "container_command",
            property(
                lambda self: SimpleNamespace(
                    argv=(sys.executable, "-c", "import time; time.sleep(60)"),
                    metadata={},
                )
            ),
        )
        (tmp_path / "agent").mkdir()
        supervisor = AgentProcessSupervisor.initialize(
            tmp_path / "agent", agent_id="agent-A", profiles=(profile,)
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        launch = replace(_launch(supervisor, workspace), profile=profile)
        supervisor.launch(launch)
        send_signal = signal.pidfd_send_signal

        def fail_after_observation(namespace: int, signum: int) -> None:
            if signal_error is ProcessLookupError:
                # The observed live namespace exits before the attempted signal.
                send_signal(namespace, signum)
                assert select.select([namespace], [], [], 2)[0]
            raise signal_error("namespace changed after observation")

        monkeypatch.setattr(signal, "pidfd_send_signal", fail_after_observation)
        try:
            receipt = supervisor.contain(launch)
            expected = (
                SupervisorLaunchState.CONTAINED
                if signal_error is ProcessLookupError
                else SupervisorLaunchState.UNKNOWN
            )
            assert receipt.state is expected
            assert not receipt.qualified_success
            if signal_error is PermissionError:
                assert supervisor.query(launch).state is SupervisorLaunchState.RUNNING
                assert not supervisor.quiescent()
        finally:
            monkeypatch.setattr(signal, "pidfd_send_signal", send_signal)
            assert supervisor.contain(launch).state is SupervisorLaunchState.CONTAINED
        assert supervisor.quiescent()


def test_clean_shutdown_accepts_an_exited_group_that_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "agent").mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        tmp_path / "agent", agent_id="agent-A", profiles=(_profile(),)
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launch = _launch(supervisor, workspace)
    original_popen = subprocess.Popen

    def start_root(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        return cast(Any, original_popen([sys.executable, "-c", "pass"], **kwargs))

    monkeypatch.setattr(
        "loom.queue._agent_process_supervisor.subprocess.Popen", start_root
    )
    supervisor.launch(launch)
    deadline = monotonic() + 2
    while supervisor.query(launch).state is not SupervisorLaunchState.EXITED:
        assert monotonic() < deadline
        sleep(0.01)

    supervisor.mark_clean_shutdown()
    supervisor.rotate_clean_continuity()


def test_clean_shutdown_contains_descendant_after_root_exits(tmp_path: Path) -> None:
    agent = tmp_path / "agent"
    agent.mkdir()
    executable = tmp_path / "exiting-root"
    executable.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        "import subprocess, sys\n"
        "workspace = Path(sys.argv[sys.argv.index('--workspace') + 1])\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        '"import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
        'time.sleep(30)"])\n'
        "(workspace / 'descendant.pid').write_text(str(child.pid))\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    profile = ResidentWorkerLaunchProfile(
        project_root=Path.cwd(),
        python_executable=executable,
        descriptor={
            "profile_id": "exiting-root",
            "kind": "test-resident",
            "version": 1,
        },
    )
    from loom.queue._agent_process_supervisor import SupervisorLaunchConfiguration

    configuration = SupervisorLaunchConfiguration("agent-A", (profile,))
    client = AgentProcessSupervisorService.initialize(
        agent, configuration=configuration
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launch = replace(_launch(client, workspace), profile=profile)
    try:
        client.launch(launch)
        descendant_file = workspace / "descendant.pid"
        deadline = monotonic() + 2
        while not descendant_file.exists() and monotonic() < deadline:
            sleep(0.01)
        descendant_pid = int(descendant_file.read_text(encoding="utf-8"))
        deadline = monotonic() + 2
        while client.query(launch).state is not SupervisorLaunchState.EXITED:
            assert monotonic() < deadline
            sleep(0.01)
        os.kill(descendant_pid, 0)

        # Query has published root exit, but must still retain the creation-owned
        # leader through request-stop and the final containment signal.
        assert client.request_stop(launch).state is SupervisorLaunchState.EXITED

        client.shutdown_clean()
        with sqlite3.connect(agent / "supervisor" / "supervisor.sqlite") as conn:
            state = conn.execute(
                "SELECT state FROM launches WHERE operation_id = ?",
                (launch.launch_operation_id,),
            ).fetchone()[0]
        assert state == SupervisorLaunchState.CONTAINED.value

        deadline = monotonic() + 2
        while monotonic() < deadline:
            try:
                os.kill(descendant_pid, 0)
            except ProcessLookupError:
                break
            sleep(0.01)
        with pytest.raises(ProcessLookupError):
            os.kill(descendant_pid, 0)
    finally:
        if client._endpoint.exists():  # noqa: SLF001
            client.shutdown_for_test()


def test_separate_service_is_profile_set_bound_and_continuous(tmp_path: Path) -> None:
    profile = _profile()
    second = ResidentWorkerLaunchProfile(
        project_root=Path.cwd(),
        python_executable=Path(sys.executable),
        descriptor={"profile_id": "other", "kind": "test-resident", "version": 2},
    )
    agent = tmp_path / "agent"
    agent.mkdir()
    from loom.queue._agent_process_supervisor import SupervisorLaunchConfiguration

    configuration = SupervisorLaunchConfiguration("agent-A", (second, profile))
    client = AgentProcessSupervisorService.initialize(
        agent, configuration=configuration
    )
    try:
        reopened = AgentProcessSupervisorClient(agent, configuration)
        assert reopened.supervisor_id == client.supervisor_id
        assert reopened.continuity_epoch == client.continuity_epoch
        changed = SupervisorLaunchConfiguration("agent-A", (profile,))
        with pytest.raises(AgentProcessSupervisorError, match="reinitialization"):
            AgentProcessSupervisorClient(agent, changed)
    finally:
        client.shutdown_for_test()


@pytest.mark.parametrize("snapshot_alias", ["projects", "unmapped-projects"])
def test_separate_service_accepts_shared_container_preparation(
    tmp_path: Path, snapshot_alias: str
) -> None:
    from examples.execution.containers.apptainer_fixture import fake_apptainer
    from loom.pipeline.planning import StageFingerprintRecord
    from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace
    from loom.queue._shared_publication import staging_tree
    from loom.queue.preparation import (
        PREPARATION_STAGE_TARGET,
        PreparationChildInput,
        SharedInputReceipt,
    )
    from loom.queue.shared_execution import SHARED_EXECUTION_SCOPE, qualifications
    from tests.unit.loom.queue.test_remote_stage_execution import _profile as resident_profile
    from tests.unit.loom.queue.test_remote_stage_execution import _request

    snapshots = tmp_path / "snapshots"
    (snapshots / "capture").mkdir(parents=True)
    (snapshots / "challenge").write_bytes(b"shared")
    roots = {"snapshots": {
        "host_path": str(snapshots), "container_path": "/loom/snapshots",
        "access": "ro", "challenge": {
            "path": "challenge", "sha256": hashlib.sha256(b"shared").hexdigest(),
        },
    }}
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "challenge").write_bytes(b"shared")
    roots["outputs"] = {
        "host_path": str(outputs), "container_path": "/loom/outputs",
        "access": "rw", "challenge": {
            "path": "challenge", "sha256": hashlib.sha256(b"shared").hexdigest(),
        },
        "publication": {
            "max_members": 1024, "max_payload_bytes": 268435456,
            "max_manifest_bytes": 1048576,
        },
    }
    scope = {"capability": "shared-execution-v1", "roots": qualifications(roots), "locations": []}
    with fake_apptainer() as container:
        # Exercise the real supervisor process and command construction. The
        # foreground stand-in only keeps its owned child alive; it is not a SIF.
        Path(container["options"]["command"]).write_text(
            f"#!{sys.executable}\nimport time\ntime.sleep(30)\n"
        )
        resident = replace(
            resident_profile(tmp_path), container=container, shared_roots=roots,
            preparation_shared_roots={"projects": snapshots},
        )
        request = _request(resident)
        binding = PreparationChildInput(
            "prepare-1", "existing", "pipeline.yaml",
            SharedInputReceipt("sha256:" + "a" * 64, snapshot_alias, "capture"),
            resident.descriptor.to_dict(), shared_scope=scope,
        )
        fingerprint = StageFingerprintRecord.from_dict(request.fingerprint)
        request = replace(request, resolved_runtime={**request.resolved_runtime, "resources": {"schema_version": 2, "entries": {}}}, fingerprint=StageFingerprintRecord.create(
            algorithm=fingerprint.algorithm,
            payload=replace(
                fingerprint.payload, factory_target=PREPARATION_STAGE_TARGET,
                stage_config=binding.to_dict(),
                fingerprint_fields={SHARED_EXECUTION_SCOPE: scope},
            ),
            inputs_summary=fingerprint.inputs_summary,
        ).to_dict())
        agent = tmp_path / "agent"
        agent.mkdir()
        workspace = _ResidentAssignmentWorkspace(agent, request.assignment_id)
        workspace.persist_request(request, resident)
        profile = resident.launch_profile
        configuration = SupervisorLaunchConfiguration("agent-A", (profile,))
        client = AgentProcessSupervisorService.initialize(agent, configuration=configuration)
        launch = None
        try:
            if snapshot_alias == "unmapped-projects":
                with pytest.raises(
                    AgentProcessSupervisorError, match="shared snapshot root is not mapped"
                ):
                    invalid = replace(
                        _launch(client, workspace.root),
                        assignment_id=request.assignment_id,
                        profile=profile,
                    )
                    client.launch(invalid)
                assert workspace.supervisor_launch_json() is None
                with sqlite3.connect(agent / "supervisor/supervisor.sqlite") as connection:
                    assert connection.execute(
                        "SELECT COUNT(*) FROM launches"
                    ).fetchone()[0] == 0
                return
            launch = replace(
                _launch(client, agent / "assignments" / request.assignment_id),
                assignment_id=request.assignment_id, profile=profile,
            )
            from loom.pipeline.runtime._resource_controls import _validated_resource_controls

            launch = replace(launch, resource_controls=_validated_resource_controls(
                launch.container_command.metadata.get("resource_controls")))
            staging = staging_tree(request, roots, "agent-A")
            assert not staging.exists()
            started = client.launch(launch)
            assert started.state is SupervisorLaunchState.RUNNING
            assert staging.is_dir()
            reopened = AgentProcessSupervisorClient(agent, configuration)
            assert reopened.service_process_id == client.service_process_id
            assert reopened.launch(launch).process_id == started.process_id
            assert reopened.query(launch).state is SupervisorLaunchState.RUNNING
            with sqlite3.connect(agent / "supervisor/supervisor.sqlite") as connection:
                assert connection.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 1
            assert client.contain(launch).state is SupervisorLaunchState.CONTAINED
            staging.rmdir()
            assert reopened.query(launch).state is SupervisorLaunchState.CONTAINED
            assert reopened.launch(launch).state is SupervisorLaunchState.CONTAINED
            assert not staging.exists()
        finally:
            if client._endpoint.exists():
                if launch is not None:
                    client.contain(launch)
                client.shutdown_for_test()


@pytest.mark.parametrize("before_request", [True, False])
def test_client_disconnect_preserves_supervisor_and_its_running_worker(
    tmp_path: Path, before_request: bool
) -> None:
    agent = tmp_path / "agent"
    agent.mkdir()
    executable = tmp_path / "sleeping-worker"
    executable.write_text(
        f"#!{sys.executable}\nimport time\ntime.sleep(30)\n", encoding="utf-8"
    )
    executable.chmod(0o700)
    profile = replace(_profile(), python_executable=executable)
    client = AgentProcessSupervisorService.initialize(
        agent, configuration=SupervisorLaunchConfiguration("agent-A", (profile,))
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launch = replace(_launch(client, workspace), profile=profile)
    try:
        started = client.launch(launch)
        identity = client.status()
        connection = Client(
            str(client._endpoint), family="AF_UNIX", authkey=client._secret
        )
        if before_request:
            connection.close()
        else:
            with sqlite3.connect(agent / "supervisor" / "supervisor.sqlite") as conn:
                # Hold query processing until the peer has closed its reply socket.
                conn.execute("BEGIN EXCLUSIVE")
                connection.send({"operation": "query", "value": _launch_value(launch)})
                connection.close()
                conn.rollback()
        assert client.status() == identity
        replay = client.launch(launch)
        assert replay.process_id == started.process_id
        assert client.query(launch).state is SupervisorLaunchState.RUNNING
        with sqlite3.connect(agent / "supervisor" / "supervisor.sqlite") as conn:
            assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 1
    finally:
        client.contain(launch)
        client.shutdown_for_test()


@pytest.mark.parametrize(
    "stall", ["connect", "auth", "mutual_auth", "send", "reply", "partial_reply", "shared_deadline"],
)
def test_client_deadline_interrupts_actual_transport_and_closes_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stall: str,
) -> None:
    agent = tmp_path / "agent"
    agent.mkdir()
    client = AgentProcessSupervisorService.initialize(
        agent, configuration=SupervisorLaunchConfiguration("agent-A", (_profile(),))
    )
    original_endpoint = client._endpoint
    release = Event()
    reached = Event()
    closed = Event()
    request = _launch_value(replace(
        _launch(client, tmp_path), environment={"PAYLOAD": "x" * (8 * 1024 * 1024)},
    ))
    try:
        with tempfile.TemporaryDirectory(prefix="loom-ipc-") as short_root:
            endpoint = str(Path(short_root) / "peer.sock")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(endpoint)
                listener.listen(0)
                listener.settimeout(3)
                monkeypatch.setattr(client, "_endpoint", Path(endpoint))
                monkeypatch.setattr(client, "_EXCHANGE_TIMEOUT", 0.6 if stall == "shared_deadline" else 0.2)

                def peer() -> None:
                    if stall == "connect":
                        reached.set()
                        assert release.wait(3)
                        return
                    transport, _ = listener.accept()
                    with transport:
                        if stall != "auth":
                            from multiprocessing.connection import (
                                answer_challenge, deliver_challenge,
                            )
                            with Connection(os.dup(transport.fileno())) as connection:
                                if stall == "shared_deadline":
                                    sleep(0.4)
                                deliver_challenge(connection, client._secret)
                                if stall != "mutual_auth":
                                    answer_challenge(connection, client._secret)
                                if stall in {"reply", "partial_reply", "shared_deadline"}:
                                    received = connection.recv()
                                    assert received == {"operation": "launch", "value": request}
                                if stall == "partial_reply":
                                    # An incomplete frame must obey the same deadline.
                                    transport.sendall(b"\x00\x00\x00\x40partial")
                                reached.set()
                                assert release.wait(3)
                        else:
                            reached.set()
                            assert release.wait(3)
                        transport.settimeout(3)
                        while transport.recv(65536):
                            pass
                        closed.set()

                filler = None
                if stall == "connect":
                    # Fill this real Unix listener's backlog without accepting.
                    filler = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    filler.connect(endpoint)
                try:
                    with ThreadPoolExecutor(max_workers=2) as workers:
                        serving = workers.submit(peer)

                        def call() -> tuple[float, _SupervisorCommunicationError]:
                            started = monotonic()
                            threads = set(threading.enumerate())
                            descriptors = len(tuple(Path("/proc/self/fd").iterdir()))
                            with pytest.raises(_SupervisorCommunicationError) as failure:
                                client._call("launch", request)
                            assert set(threading.enumerate()) == threads
                            if stall == "connect":
                                assert len(tuple(Path("/proc/self/fd").iterdir())) == descriptors
                            return monotonic() - started, failure.value

                        attempt = workers.submit(call)
                        try:
                            elapsed, failure = attempt.result(timeout=2)
                            assert reached.wait(1)
                            assert elapsed < (0.9 if stall == "shared_deadline" else 1)
                            assert failure.possibly_dispatched is (stall not in {"connect", "auth", "mutual_auth"})
                        finally:
                            release.set()
                        serving.result(timeout=3)
                    if stall != "connect":
                        assert closed.is_set()
                finally:
                    release.set()
                    if filler is not None:
                        filler.close()
    finally:
        monkeypatch.setattr(client, "_endpoint", original_endpoint)
        monkeypatch.setattr(client, "_EXCHANGE_TIMEOUT", 10)
        client.shutdown_for_test()


def test_accepted_launch_reply_timeout_replays_one_live_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import select

    agent = tmp_path / "agent"
    agent.mkdir()
    executable = tmp_path / "held-worker"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    executable.chmod(0o700)
    profile = replace(_profile(), python_executable=executable)
    client = AgentProcessSupervisorService.initialize(
        agent, configuration=SupervisorLaunchConfiguration("agent-A", (profile,))
    )
    launch = replace(_launch(client, tmp_path), profile=profile)
    original_endpoint = client._endpoint
    release = Event()
    accepted: dict[str, Any] = {}
    process_fd = None
    try:
        with tempfile.TemporaryDirectory(prefix="loom-ipc-") as short_root:
            endpoint = str(Path(short_root) / "peer.sock")
            with Listener(endpoint, family="AF_UNIX", authkey=client._secret) as listener:
                def lose_reply() -> None:
                    with listener.accept() as downstream:
                        request = downstream.recv()
                        while not accepted.get("value", {}).get("process_id"):
                            with Client(str(original_endpoint), family="AF_UNIX", authkey=client._secret) as upstream:
                                upstream.send(request)
                                accepted.update(upstream.recv())
                            assert accepted["ok"] is True
                            sleep(0.01)
                        assert release.wait(3)

                with ThreadPoolExecutor(max_workers=2) as workers:
                    peer = workers.submit(lose_reply)
                    monkeypatch.setattr(client, "_endpoint", Path(endpoint))
                    monkeypatch.setattr(client, "_EXCHANGE_TIMEOUT", 0.3)
                    attempt = workers.submit(client.launch, launch)
                    try:
                        with pytest.raises(_SupervisorCommunicationError) as failure:
                            attempt.result(timeout=2)
                        assert failure.value.possibly_dispatched
                    finally:
                        release.set()
                    peer.result(timeout=3)
        monkeypatch.setattr(client, "_endpoint", original_endpoint)
        monkeypatch.setattr(client, "_EXCHANGE_TIMEOUT", 10)
        assert accepted["ok"] is True
        pid = accepted["value"]["process_id"]
        process_fd = os.pidfd_open(pid)
        assert not select.select([process_fd], [], [], 0)[0]
        replay = client.launch(launch)
        assert replay.process_id == pid
        assert client.query(launch).state is SupervisorLaunchState.RUNNING
        with sqlite3.connect(agent / "supervisor/supervisor.sqlite") as connection:
            assert connection.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 1
        with pytest.raises(AgentProcessSupervisorError, match="non-quiescent"):
            client.shutdown_clean()
        assert not select.select([process_fd], [], [], 0)[0]
    finally:
        release.set()
        monkeypatch.setattr(client, "_endpoint", original_endpoint)
        monkeypatch.setattr(client, "_EXCHANGE_TIMEOUT", 10)
        client.contain(launch)
        client.shutdown_for_test()
        if process_fd is not None:
            assert select.select([process_fd], [], [], 3)[0]
            os.close(process_fd)


def test_process_free_initialization_requires_serve_and_clean_shutdown(
    tmp_path: Path,
) -> None:
    profile = _profile()
    agent = tmp_path / "agent"
    agent.mkdir()
    from loom.queue._agent_process_supervisor import SupervisorLaunchConfiguration

    configuration = SupervisorLaunchConfiguration("agent-A", (profile,))
    AgentProcessSupervisorService.initialize_process_free(
        agent, configuration=configuration
    )
    with pytest.raises(AgentProcessSupervisorError, match="endpoint is unavailable"):
        AgentProcessSupervisorClient(agent, configuration)
    client = AgentProcessSupervisorService.start_empty_initialized(
        agent, configuration=configuration
    )
    first_epoch = client.continuity_epoch
    process_value = client.status()["service_process_id"]
    assert isinstance(process_value, int)
    process_id = process_value
    workspace = tmp_path / "service-workspace"
    workspace.mkdir()
    launch = _launch(client, workspace)
    try:
        client.launch(launch)
        with pytest.raises(AgentProcessSupervisorError, match="non-quiescent"):
            client.shutdown_clean()
        assert client.contain(launch).state is SupervisorLaunchState.CONTAINED
        client.shutdown_clean()
        with pytest.raises(ProcessLookupError):
            os.kill(process_id, 0)
    finally:
        if client._endpoint.exists():  # noqa: SLF001
            client.shutdown_for_test()

    restarted = AgentProcessSupervisorService.start_empty_initialized(
        agent, configuration=configuration
    )
    try:
        assert restarted.continuity_epoch != first_epoch
        restarted_process_id = restarted.service_process_id
        restarted.shutdown_clean()
        with pytest.raises(ProcessLookupError):
            os.kill(restarted_process_id, 0)
    finally:
        if restarted._endpoint.exists():  # noqa: SLF001
            restarted.shutdown_for_test()


def test_preparation_root_mapping_is_retained_in_launch_identity(tmp_path: Path) -> None:
    from loom.queue._agent_process_supervisor import _profile_from_value, _profile_value

    original = _profile()
    legacy = _profile_value(original)
    assert "preparation_shared_roots" not in legacy
    assert original.fingerprint == hashlib.sha256(json.dumps(legacy, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    configured = replace(original, preparation_shared_roots={"projects": tmp_path / "first-mount"})
    retained = _profile_value(configured)
    assert retained["preparation_shared_roots"] == {"projects": str(tmp_path / "first-mount")}
    reopened = _profile_from_value(json.loads(json.dumps(retained)))
    assert reopened.fingerprint == configured.fingerprint
    assert reopened.preparation_shared_roots == configured.preparation_shared_roots
    changed = replace(configured, preparation_shared_roots={"projects": tmp_path / "different-mount"})
    assert changed.descriptor == configured.descriptor
    assert changed.fingerprint != configured.fingerprint
    assert _profile_from_value(retained).preparation_shared_roots == {"projects": tmp_path / "first-mount"}


@pytest.mark.parametrize("legacy", [False, True])
def test_successful_exit_qualification_is_durable_and_legacy_is_unqualified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy: bool,
) -> None:
    profile = _profile()
    (tmp_path / "agent").mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        tmp_path / "agent", agent_id="agent-A", profiles=(profile,)
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launch = _launch(supervisor, workspace)
    original_popen = subprocess.Popen

    def start_root(args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        if args[0] == "ps":
            return cast(Any, original_popen(args, **kwargs))
        return cast(Any, original_popen([sys.executable, "-c", "pass"], **kwargs))

    monkeypatch.setattr("loom.queue._agent_process_supervisor.subprocess.Popen", start_root)
    supervisor.launch(launch)
    deadline = monotonic() + 5
    while supervisor.query(launch).state is SupervisorLaunchState.RUNNING:
        assert monotonic() < deadline
        sleep(0.01)
    contained = supervisor.contain(launch)
    assert contained.state is SupervisorLaunchState.CONTAINED
    assert contained.successful_exit
    assert supervisor.contain(launch) == contained
    if legacy:
        with sqlite3.connect(tmp_path / "agent" / "supervisor" / "supervisor.sqlite") as conn:
            conn.execute("ALTER TABLE launches DROP COLUMN successful_exit")
            conn.execute("DROP TABLE rejected_assignments")
            conn.execute("UPDATE metadata SET value = '2' WHERE key = 'schema_version'")
    reopened = AgentProcessSupervisor(
        tmp_path / "agent" / "supervisor", agent_id="agent-A", profiles=(profile,)
    )
    retained = reopened.contain(launch)
    assert retained.state is SupervisorLaunchState.CONTAINED
    assert retained.successful_exit is (not legacy)


@pytest.mark.parametrize("exit_code", [0, 1])
def test_contained_missing_result_binds_late_bytes_without_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int,
) -> None:
    profile = _profile()
    (tmp_path / "agent").mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        tmp_path / "agent", agent_id="agent-A", profiles=(profile,)
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launch = _launch(supervisor, workspace)
    original_popen = subprocess.Popen

    def start_root(args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        if args[0] == "ps":
            return cast(Any, original_popen(args, **kwargs))
        return cast(Any, original_popen(
            [sys.executable, "-c", f"raise SystemExit({exit_code})"], **kwargs
        ))

    monkeypatch.setattr("loom.queue._agent_process_supervisor.subprocess.Popen", start_root)
    supervisor.launch(launch)
    deadline = monotonic() + 5
    while supervisor.query(launch).state is SupervisorLaunchState.RUNNING:
        assert monotonic() < deadline
        sleep(0.01)
    contained = supervisor.contain(launch)
    assert contained.state is SupervisorLaunchState.CONTAINED
    assert contained.worker_result_digest is None
    assert contained.successful_exit is (exit_code == 0)

    reopened = AgentProcessSupervisor(
        tmp_path / "agent" / "supervisor", agent_id="agent-A", profiles=(profile,)
    )
    result_path = workspace / "worker-result.json"
    result_path.write_text('{"status":"failed"}')
    repaired = reopened.contain(launch)
    assert repaired.state is SupervisorLaunchState.CONTAINED
    assert repaired.exit_code == exit_code
    assert repaired.worker_result_digest == hashlib.sha256(result_path.read_bytes()).hexdigest()
    assert not repaired.successful_exit
    assert repaired.supervisor_revision == contained.supervisor_revision + 1
    assert reopened.contain(launch) == repaired
    # Already bound bytes remain immutable evidence if the workspace changes.
    result_path.write_text('{"status":"succeeded"}')
    assert reopened.contain(launch) == repaired


@pytest.mark.parametrize("backend", ["native", "apptainer"])
def test_changed_boot_preserves_exact_historical_launch_and_terminal_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    from contextlib import nullcontext
    from types import SimpleNamespace
    from examples.execution.containers.apptainer_fixture import fake_apptainer

    boot = {"host": "enrolled-host", "boot": "boot-before"}
    monkeypatch.setattr(
        "loom.queue._agent_process_supervisor._host_boot_evidence", lambda: dict(boot)
    )
    with fake_apptainer() if backend == "apptainer" else nullcontext(None) as binding:
        profile = replace(_profile(), container=binding)
        if binding is not None:
            monkeypatch.setattr(
                ResidentWorkerLaunch,
                "container_command",
                property(
                    lambda self: SimpleNamespace(
                        argv=(sys.executable, "-c", "import time; time.sleep(60)"),
                        metadata={},
                    )
                ),
            )
        root = tmp_path / "agent"
        root.mkdir()
        owner = AgentProcessSupervisor.initialize(
            root, agent_id="agent-A", profiles=(profile,)
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        launch = replace(_launch(owner, workspace), profile=profile)
        started = owner.launch(launch)
        # Stop the fixture-owned process without updating the durable receipt:
        # this models the process/SQLite cut at kernel reboot, not PID adoption.
        child = owner._children[launch.launch_operation_id]
        assert child.contain()
        for fd in owner._namespace_inits.values():
            os.close(fd)
        owner._namespace_inits.clear()
        reopened = AgentProcessSupervisor(
            root / "supervisor", agent_id="agent-A", profiles=(profile,)
        )
        blocked = reopened.recover_reboot("same-boot")
        assert blocked["state"] == "blocked"
        assert reopened.query(launch).state is SupervisorLaunchState.UNKNOWN
        boot["boot"] = "boot-after"
        recovered = reopened.recover_reboot("reboot-1")
        assert recovered["state"] == "contained"
        assert recovered["previous_generation"] == launch.continuity_epoch
        assert recovered["generation"] != launch.continuity_epoch
        assert reopened.recover_reboot("reboot-1") == recovered
        receipt = reopened.launch(launch)
        assert receipt.process_id == started.process_id
        assert receipt.launch.spec_digest == launch.spec_digest
        assert receipt.state is SupervisorLaunchState.CONTAINED
        assert not receipt.qualified_success
        never_accepted = replace(launch, launch_operation_id="workspace-only-launch")
        late = reopened.launch(never_accepted)
        assert late.state is SupervisorLaunchState.CONTAINED
        assert not late.started
        assert reopened.launch(never_accepted) == late
        with pytest.raises(AgentProcessSupervisorError, match="conflicts"):
            reopened.recover_reboot("same-boot")


@pytest.mark.parametrize("fault", ["host", "legacy", "root"])
def test_reboot_requires_prelaunch_host_root_and_boot_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    boot = {"host": "host-a", "boot": "boot-a"}
    monkeypatch.setattr(
        "loom.queue._agent_process_supervisor._host_boot_evidence", lambda: dict(boot)
    )
    root = tmp_path / "agent"
    root.mkdir()
    owner = AgentProcessSupervisor.initialize(
        root, agent_id="agent-A", profiles=(_profile(),)
    )
    owner.bind_execution_host()
    if fault == "host":
        boot["host"] = "host-b"
    elif fault == "legacy":
        with owner._connect() as conn:
            conn.execute("DELETE FROM metadata WHERE key = 'boot_evidence'")
            conn.execute("DROP TABLE rejected_assignments")
            conn.execute("UPDATE metadata SET value = '3' WHERE key = 'schema_version'")
    else:
        destination = tmp_path / "moved"
        root.rename(destination)
        root = destination
    boot["boot"] = "boot-b"
    reopened = AgentProcessSupervisor(
        root / "supervisor", agent_id="agent-A", profiles=(_profile(),)
    )
    assert reopened.recover_reboot("reboot")["state"] == "blocked"


@pytest.mark.parametrize("historical", [False, True])
def test_idle_reboot_rotates_without_clean_shutdown_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    historical: bool,
) -> None:
    boot = {"host": "host-a", "boot": "boot-a"}
    monkeypatch.setattr(
        "loom.queue._agent_process_supervisor._host_boot_evidence", lambda: dict(boot)
    )
    root = tmp_path / "agent"
    root.mkdir()
    owner = AgentProcessSupervisor.initialize(
        root, agent_id="agent-A", profiles=(_profile(),)
    )
    launch = None
    terminal = None
    if historical:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        launch = _launch(owner, workspace)
        owner.launch(launch)
        terminal = owner.contain(launch)
    boot["boot"] = "boot-b"
    reopened = AgentProcessSupervisor(
        root / "supervisor", agent_id="agent-A", profiles=(_profile(),)
    )
    assert reopened.recover_reboot("idle-reboot")["state"] == "contained"
    reopened.rotate_clean_continuity()
    if historical:
        assert launch is not None and terminal is not None
        assert (
            reopened.query(launch).worker_result_digest == terminal.worker_result_digest
        )
        assert reopened.query(launch).qualified_success == terminal.qualified_success


def test_reboot_preserves_proven_success_and_result_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot = {"host": "host-a", "boot": "boot-a"}
    monkeypatch.setattr(
        "loom.queue._agent_process_supervisor._host_boot_evidence", lambda: dict(boot)
    )
    root = tmp_path / "agent"
    root.mkdir()
    owner = AgentProcessSupervisor.initialize(
        root, agent_id="agent-A", profiles=(_profile(),)
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launch = _launch(owner, workspace)
    real_popen = subprocess.Popen

    def terminal_worker(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        return cast(Any, real_popen([sys.executable, "-c", "pass"], **kwargs))

    monkeypatch.setattr(
        "loom.queue._agent_process_supervisor.subprocess.Popen", terminal_worker
    )
    owner.launch(launch)
    monkeypatch.setattr(
        "loom.queue._agent_process_supervisor.subprocess.Popen", real_popen
    )
    deadline = monotonic() + 5
    while owner._children[launch.launch_operation_id].root_status() is None:
        assert monotonic() < deadline
        sleep(0.01)
    result_path = workspace / "worker-result.json"
    result_path.write_text("retained worker bytes")
    terminal = owner.contain(launch)
    assert terminal.qualified_success
    boot["boot"] = "boot-b"
    reopened = AgentProcessSupervisor(
        root / "supervisor", agent_id="agent-A", profiles=(_profile(),)
    )
    assert reopened.recover_reboot("reboot")["state"] == "contained"
    assert reopened.query(launch) == terminal
    assert result_path.read_text() == "retained worker bytes"
