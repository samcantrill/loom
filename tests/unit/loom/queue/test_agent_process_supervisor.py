from __future__ import annotations

import sys
import subprocess
from dataclasses import replace
from pathlib import Path
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
    supervisor: AgentProcessSupervisor, workspace: Path
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
