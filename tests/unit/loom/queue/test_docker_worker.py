"""Stateful daemon evidence survives CLI and observer loss."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from loom.queue._docker_worker import DockerWorker


class Daemon:
    def __init__(self) -> None:
        self.container = None
        self.calls = []
        self.unavailable = False
        self.lose = None

    def __call__(self, argv):
        args = list(argv[3:])
        self.calls.append(args)
        if self.unavailable:
            raise OSError("daemon unavailable")
        command = args[0]
        if command == "create":
            assert self.container is None
            self.container = {
                "Id": "immutable-id",
                "Name": "/" + args[args.index("--name") + 1],
                "Config": {
                    "Labels": {
                        "org.loom.ownership": args[args.index("--label") + 1].split(
                            "=", 1
                        )[1]
                    }
                },
                "HostConfig": {"RestartPolicy": {"Name": "no"}, "AutoRemove": False},
                "State": {"Status": "created", "Running": False, "ExitCode": 0},
            }
        elif command == "start":
            assert self.container is not None
            assert self.container["State"]["Status"] == "created"
            self.container["State"].update(Status="running", Running=True)
        elif command == "kill":
            self.finish(137)
        elif command == "rm":
            assert self.container is not None
            assert self.container["State"]["Running"] is False
            self.container = None
        elif command == "inspect":
            if self.container is None:
                return subprocess.CompletedProcess(argv, 1, "", "No such container")
            return subprocess.CompletedProcess(
                argv, 0, json.dumps([self.container]), ""
            )
        else:
            raise AssertionError(args)
        if self.lose == command:
            self.lose = None
            raise subprocess.TimeoutExpired(argv, 10)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def finish(self, code=0):
        assert self.container is not None
        self.container["State"].update(
            Status="exited",
            Running=False,
            ExitCode=code,
            FinishedAt="2026-09-12T01:02:03Z",
        )


@pytest.fixture
def owner(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "supervisor.sqlite")
    DockerWorker.initialize(conn)
    daemon = Daemon()

    def reopen(**changes):
        return DockerWorker(
            conn,
            operation_id="attempt",
            ownership="a" * 64,
            command=("/docker", "run", "image", "python"),
            endpoint=changes.get("endpoint", "unix:///daemon"),
            call=daemon,
        )

    yield reopen, daemon
    conn.close()


@pytest.mark.parametrize("lost", ["create", "start"])
def test_lost_response_reconciles_same_container_without_repeat(owner, lost):
    reopen, daemon = owner
    daemon.lose = lost
    assert reopen().launch().container_id == "immutable-id"
    assert reopen().launch().state == "running"
    assert sum(call[0] == "create" for call in daemon.calls) == 1
    assert sum(call[0] == "start" for call in daemon.calls) == 1
    daemon.finish()
    result = reopen().observe()
    assert result.successful and result.contained
    assert reopen().remove().removed
    assert reopen().launch().successful
    assert sum(call[0] == "start" for call in daemon.calls) == 1


def test_helper_loss_and_daemon_absence_do_not_release_or_relaunch(owner):
    reopen, daemon = owner
    reopen().launch()
    assert reopen().observe().state == "running"
    daemon.unavailable = True
    assert not reopen().observe().contained
    daemon.unavailable = False
    daemon.container = None
    assert reopen().launch().state == "unknown"
    assert sum(call[0] == "create" for call in daemon.calls) == 1


def test_cancel_lost_response_retains_intent_and_requires_inspection(owner):
    reopen, daemon = owner
    reopen().launch()
    daemon.lose = "kill"
    assert not reopen().cancel().contained
    result = reopen().observe()
    assert result.contained and not result.successful
    assert reopen().remove().removed
    assert not reopen().observe().successful


def test_foreign_identity_never_cancelled_and_endpoint_conflicts(owner):
    reopen, daemon = owner
    reopen().launch()
    with pytest.raises(ValueError, match="intent conflicts"):
        reopen(endpoint="unix:///other").observe()
    daemon.container["Id"] = "foreign"
    assert reopen().cancel().state == "unknown"
    assert not any(call[0] == "kill" for call in daemon.calls)


@pytest.mark.parametrize("code,restart", [(1, "no"), (0, "always")])
def test_terminal_success_requires_zero_and_stable_lifecycle(owner, code, restart):
    reopen, daemon = owner
    reopen().launch()
    daemon.finish(code)
    daemon.container["HostConfig"]["RestartPolicy"]["Name"] = restart
    result = reopen().observe()
    assert not result.successful
    assert result.contained == (restart == "no")


def test_cancel_before_launch_is_durable_no_effect(owner):
    reopen, daemon = owner
    result = reopen().cancel()
    assert result.contained and not result.successful
    assert reopen().launch().contained
    assert not daemon.calls


def test_lost_removal_response_replays_retained_terminal_evidence(owner):
    reopen, daemon = owner
    reopen().launch()
    daemon.finish()
    assert reopen().observe().successful
    daemon.lose = "rm"
    assert not reopen().remove().removed
    assert reopen().remove().removed
    assert reopen().observe().successful
    assert sum(call[0] == "create" for call in daemon.calls) == 1


@pytest.mark.parametrize("after", [False, True])
def test_terminal_capture_loss_never_removes_the_only_evidence(
    owner, monkeypatch, after
):
    reopen, daemon = owner
    reopen().launch()
    daemon.finish()
    worker = reopen()
    original = worker._save

    def interrupted(value):
        if after:
            original(value)
        raise RuntimeError("capture interrupted")

    monkeypatch.setattr(worker, "_save", interrupted)
    with pytest.raises(RuntimeError, match="capture interrupted"):
        worker.observe()
    assert not any(call[0] == "rm" for call in daemon.calls)
    assert reopen().observe().successful
    assert reopen().remove().removed


def test_uncertain_start_before_effect_is_not_reissued(owner, monkeypatch):
    reopen, daemon = owner
    original = daemon.__class__.__call__

    def interrupted(self, argv):
        if argv[3] == "start":
            raise subprocess.TimeoutExpired(argv, 10)
        return original(self, argv)

    monkeypatch.setattr(daemon.__class__, "__call__", interrupted)
    reopen().launch()
    assert reopen().launch().state == "unknown"
    result = reopen().cancel()
    assert result.contained and not result.successful


def test_lost_create_before_effect_never_infers_absence_as_containment(
    owner, monkeypatch
):
    reopen, daemon = owner
    original = daemon.__class__.__call__

    def interrupted(self, argv):
        if argv[3] == "create":
            raise subprocess.TimeoutExpired(argv, 10)
        return original(self, argv)

    monkeypatch.setattr(daemon.__class__, "__call__", interrupted)
    assert reopen().launch().state == "unknown"
    assert reopen().cancel().state == "unknown"
    assert not reopen().launch().contained
    assert daemon.container is None


def test_cancel_before_effect_replays_only_owned_identity(owner, monkeypatch):
    reopen, daemon = owner
    reopen().launch()
    original = daemon.__class__.__call__

    def interrupted(self, argv):
        if argv[3] == "kill":
            raise subprocess.TimeoutExpired(argv, 10)
        return original(self, argv)

    with monkeypatch.context() as patch:
        patch.setattr(daemon.__class__, "__call__", interrupted)
        assert not reopen().cancel().contained
        assert not reopen().observe().successful
    assert not reopen().observe().contained
    result = reopen().observe()
    assert result.contained and not result.successful
    assert [call for call in daemon.calls if call[0] == "kill"] == [
        ["kill", "immutable-id"]
    ]


def test_supervisor_recovers_daemon_ownership_without_native_epoch_rotation(
    tmp_path,
    monkeypatch,
):
    from dataclasses import replace
    from types import SimpleNamespace
    from loom.queue._agent_process_supervisor import (
        AgentProcessSupervisor,
        ResidentWorkerLaunch,
        SupervisorLaunchState,
    )
    from tests.unit.loom.queue.test_agent_process_supervisor import _profile, _launch
    from tests.unit.loom.queue.test_container_worker import _binding

    daemon = Daemon()
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: daemon(argv))
    monkeypatch.setattr(
        ResidentWorkerLaunch,
        "container_command",
        property(
            lambda self: SimpleNamespace(
                argv=("/docker", "run", "image", "python"), metadata={}
            )
        ),
    )
    profile = replace(_profile(), container=_binding())
    agent_root = tmp_path / "agent"
    agent_root.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    original = AgentProcessSupervisor.initialize(
        agent_root, agent_id="agent-A", profiles=(profile,)
    )
    launch = replace(_launch(original, workspace), profile=profile)
    running = original.launch(launch)
    assert running.process_id is None and running.backend_id == "immutable-id"
    assert not running.qualified_success

    recovered = AgentProcessSupervisor(
        original.root, agent_id="agent-A", profiles=(profile,)
    )
    recovered.rotate_clean_continuity()
    assert recovered.continuity_epoch == original.continuity_epoch
    daemon.unavailable = True
    assert recovered.query(launch).state is SupervisorLaunchState.UNKNOWN
    assert not recovered.quiescent()
    daemon.unavailable = False
    assert recovered.query(launch).state is SupervisorLaunchState.RUNNING
    daemon.finish()
    result = recovered.contain(launch)
    assert result.state is SupervisorLaunchState.CONTAINED
    assert result.qualified_success and not result.successful_exit
    assert recovered.quiescent()
    assert sum(call[0] == "create" for call in daemon.calls) == 1
    assert sum(call[0] == "start" for call in daemon.calls) == 1
