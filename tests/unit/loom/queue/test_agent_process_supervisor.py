from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisor,
    AgentProcessSupervisorError,
    ResidentWorkerLaunch,
    ResidentWorkerLaunchProfile,
    SupervisorLaunchState,
)


def _profile() -> ResidentWorkerLaunchProfile:
    return ResidentWorkerLaunchProfile(
        project_root=Path.cwd(),
        python_executable=Path(sys.executable),
        descriptor={"kind": "test-resident", "version": 1},
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
        workspace_root=workspace,
        profile=_profile(),
        environment={},
    )


def test_launch_exact_replay_has_one_root_and_conflicting_identity_rejects(
    tmp_path: Path,
) -> None:
    (tmp_path / "agent").mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        tmp_path / "agent", agent_id="agent-A", profile=_profile()
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


def test_reopened_supervisor_does_not_adopt_nonterminal_pid(tmp_path: Path) -> None:
    profile = _profile()
    (tmp_path / "agent").mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        tmp_path / "agent", agent_id="agent-A", profile=profile
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launch = _launch(supervisor, workspace)
    supervisor.launch(launch)

    reopened = AgentProcessSupervisor(
        tmp_path / "agent" / "supervisor", agent_id="agent-A", profile=profile
    )

    assert reopened.query(launch).state is SupervisorLaunchState.UNKNOWN
