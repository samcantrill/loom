from __future__ import annotations

import os
import sqlite3
import sys
import subprocess
from dataclasses import replace
from pathlib import Path
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

    def start_root(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        return cast(
            Any,
            original_popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import signal, subprocess, sys, time; "
                        "subprocess.Popen([sys.executable, '-c', "
                        "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)']); "
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

    assert supervisor.contain(launch).state is SupervisorLaunchState.CONTAINED


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
        "\"import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(30)\"])\n"
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
    client = AgentProcessSupervisorService.initialize(agent, configuration=configuration)
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
    finally:
        if client._endpoint.exists():  # noqa: SLF001
            client.shutdown_for_test()

    deadline = monotonic() + 2
    while monotonic() < deadline:
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            break
        sleep(0.01)
    with pytest.raises(ProcessLookupError):
        os.kill(process_id, 0)

    restarted = AgentProcessSupervisorService.start_empty_initialized(
        agent, configuration=configuration
    )
    try:
        assert restarted.continuity_epoch != first_epoch
        restarted.shutdown_clean()
    finally:
        if restarted._endpoint.exists():  # noqa: SLF001
            restarted.shutdown_for_test()
