from __future__ import annotations

import os
import hashlib
import json
import sqlite3
import sys
import subprocess
from dataclasses import replace
from pathlib import Path
from multiprocessing.connection import Client
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
