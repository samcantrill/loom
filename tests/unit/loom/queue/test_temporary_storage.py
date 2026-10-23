"""Assignment storage uses durable ownership and positive containment."""

from dataclasses import replace
from collections.abc import Mapping
import errno
import json
from pathlib import Path

import pytest

from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisor,
    AgentProcessSupervisorError,
    SupervisorLaunchState,
    _launch_from_value,
    _launch_value,
    _receipt_from_value,
    _receipt_value,
    _SupervisorNoStartError,
)
from loom.queue import _temporary_storage as storage
from loom.queue._docker_worker import DockerWorker
from tests.unit.loom.queue.test_agent_process_supervisor import (
    _retain_shared_launch,
    _shared_container_request,
)
from tests.unit.loom.queue.test_docker_worker import Daemon


def _owned(tmp_path, monkeypatch, *, target="/loom/cache"):
    resident, request, _ = _shared_container_request(tmp_path, backend="docker")
    base = tmp_path / "local-cache"
    base.mkdir(mode=0o700)
    binding = resident.container
    assert binding is not None and isinstance(binding["container"], Mapping)
    resident = replace(
        resident,
        container={
            **binding,
            "container": {
                **binding["container"],
                "mounts": [{"source": str(base), "target": target, "mode": "rw"}],
            },
        },
        temporary_mounts=(target,),
    )
    daemon = Daemon()
    initialize = DockerWorker.__init__

    def installed(owner, *args, **kwargs):
        initialize(owner, *args, **kwargs, call=daemon)

    monkeypatch.setattr(DockerWorker, "__init__", installed)
    agent = tmp_path / "agent"
    agent.mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        agent, agent_id="agent-A", profiles=(resident.launch_profile,)
    )
    launch = _retain_shared_launch(supervisor, tmp_path, resident, request)
    directory = storage.assignment_mounts(
        launch.profile, workspace=launch.workspace_root, agent_id=launch.agent_id
    )[target]
    return supervisor, launch, daemon, base, directory


def test_missing_scratch_base_is_recreated_and_only_attempt_is_cleaned(
    tmp_path, monkeypatch
):
    supervisor, launch, daemon, base, directory = _owned(
        tmp_path, monkeypatch, target="/tmp"
    )
    base.rmdir()
    assert supervisor.launch(launch).state is SupervisorLaunchState.RUNNING
    assert base.stat().st_mode & 0o777 == 0o700
    assert directory.stat().st_mode & 0o777 == 0o700
    assert f"source={directory},target=/tmp" in " ".join(launch.container_command.argv)
    (directory / "scratch").write_bytes(b"temporary")
    (base / "keep").write_bytes(b"base-owned")
    daemon.finish()
    assert supervisor.contain(launch).qualified_success
    assert not directory.exists()
    assert (base / "keep").read_bytes() == b"base-owned"
    assert launch.workspace_root.is_dir()


@pytest.mark.parametrize("unsafe", ["symlink", "shared", "foreign"])
def test_unsafe_scratch_base_is_rejected_without_repair(tmp_path, monkeypatch, unsafe):
    supervisor, launch, daemon, base, directory = _owned(
        tmp_path, monkeypatch, target="/tmp"
    )
    if unsafe == "symlink":
        base.rmdir()
        other = tmp_path / "other"
        other.mkdir(mode=0o700)
        base.symlink_to(other, target_is_directory=True)
    elif unsafe == "shared":
        base.chmod(0o777)
    else:
        monkeypatch.setattr(storage.os, "getuid", lambda: base.stat().st_uid + 1)
    with pytest.raises((PermissionError, NotADirectoryError)):
        storage.prepare_assignment_storage(
            launch.profile, workspace=launch.workspace_root, agent_id=launch.agent_id
        )
    assert not directory.exists()
    assert daemon.calls == []
    if unsafe == "shared":
        assert base.stat().st_mode & 0o777 == 0o777
    elif unsafe == "symlink":
        assert base.is_symlink() and list(other.iterdir()) == []


def test_projection_and_retained_identity_do_not_allocate_storage(
    tmp_path, monkeypatch
):
    supervisor, launch, _daemon, base, directory = _owned(tmp_path, monkeypatch)
    assert not directory.exists()
    command = launch.container_command
    assert f"source={directory},target=/loom/cache" in " ".join(command.argv)
    saved = _launch_value(launch)

    def forbid(*args, **kwargs):
        raise AssertionError("retained launch identity must not touch storage")

    with monkeypatch.context() as pure:
        for name in ("stat", "lstat", "exists", "resolve", "mkdir"):
            pure.setattr(Path, name, forbid)
        restored = _launch_from_value(json.loads(json.dumps(saved)))
        assert restored.spec_digest == launch.spec_digest
        assert restored.profile.temporary_mounts == ("/loom/cache",)
    assert restored.command_argv == launch.command_argv
    assert list(base.iterdir()) == []
    assert supervisor.query(launch).state is SupervisorLaunchState.NOT_ACCEPTED
    other = storage.assignment_mounts(
        launch.profile,
        workspace=launch.workspace_root.with_name("another-attempt"),
        agent_id=launch.agent_id,
    )["/loom/cache"]
    assert other != directory and other.parent == directory.parent


def test_role_declaration_preserves_empty_identity_and_carries_temporary_targets(
    tmp_path,
):
    from loom.queue.deployment import _resident_profile_declaration
    from tests.unit.loom.queue.test_deployment import _resident_profile
    from tests.unit.loom.queue.test_container_worker import _binding

    value = _resident_profile(tmp_path, "installed")

    def declaration():
        return _resident_profile_declaration(
            value, tmp_path, "profile", preparation=False, preparation_staged=False
        )

    previous = declaration()
    value["temporary_mounts"] = []
    assert declaration() == previous
    value["container"] = {
        **_binding(),
        "container": {
            "image": {"reference": "sha256:" + "a" * 64},
            "mounts": [
                {"source": "/local/cache", "target": "/loom/cache", "mode": "rw"}
            ],
        },
    }
    value["temporary_mounts"] = ["/loom/cache"]
    assert declaration()["temporary_mounts"] == ["/loom/cache"]


@pytest.mark.parametrize("targets", [("/missing",), ("/loom/cache", "/loom/cache")])
def test_temporary_mount_requires_unique_installed_writable_target(
    tmp_path, monkeypatch, targets
):
    _supervisor, launch, _daemon, _base, _directory = _owned(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="temporary mount"):
        replace(launch.profile, temporary_mounts=targets)
    binding = launch.profile.container
    assert binding is not None and isinstance(binding["container"], Mapping)
    with pytest.raises(ValueError, match="writable"):
        replace(
            launch.profile,
            container={
                **binding,
                "container": {
                    **binding["container"],
                    "mounts": [
                        {
                            "source": str(tmp_path / "local-cache"),
                            "target": "/loom/cache",
                            "mode": "ro",
                        }
                    ],
                },
            },
        )


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_owned_storage_is_removed_only_after_containment(
    tmp_path, monkeypatch, outcome
):
    supervisor, launch, daemon, base, directory = _owned(tmp_path, monkeypatch)
    assert supervisor.launch(launch).state is SupervisorLaunchState.RUNNING
    (directory / "prepared.npz").write_bytes(b"worker-owned payload")
    sibling = directory.with_name("unrelated-attempt")
    sibling.mkdir()
    (sibling / "keep").write_bytes(b"other execution")
    retained = launch.workspace_root / "retained-result"
    retained.write_bytes(b"retained output")
    assert supervisor.query(launch).temporary_storage_pending
    if outcome == "cancel":
        supervisor._docker_reconcile(launch, cancel=True)
    else:
        daemon.finish(0 if outcome == "success" else 1)
    assert supervisor.query(launch).state is SupervisorLaunchState.EXITED
    assert directory.is_dir()
    receipt = supervisor.contain(launch)
    assert receipt.state is SupervisorLaunchState.CONTAINED
    assert receipt.qualified_success is (outcome == "success")
    assert not receipt.temporary_storage_pending
    assert receipt.temporary_storage_error is None
    assert not directory.exists()
    assert base.is_dir() and (sibling / "keep").read_bytes() == b"other execution"
    assert retained.read_bytes() == b"retained output"
    assert _receipt_from_value(_receipt_value(receipt)) == receipt
    assert supervisor.contain(launch).state is SupervisorLaunchState.CONTAINED


def test_cleanup_failure_is_terminal_and_restart_retries_owned_storage(
    tmp_path, monkeypatch
):
    supervisor, launch, daemon, _base, directory = _owned(tmp_path, monkeypatch)
    supervisor.launch(launch)
    (directory / "prepared.npz").write_bytes(b"payload")
    daemon.finish()

    def denied(*args, **kwargs):
        raise PermissionError("cannot remove owned payload")

    with monkeypatch.context() as failed:
        failed.setattr(storage, "cleanup_assignment_storage", denied)
        receipt = supervisor.contain(launch)
        assert receipt.state is SupervisorLaunchState.CONTAINED
        assert receipt.temporary_storage_pending
        assert receipt.temporary_storage_error is not None
        assert "PermissionError" in receipt.temporary_storage_error
        assert not receipt.qualified_success
        assert supervisor.quiescent()
        assert directory.is_dir()
        assert _receipt_from_value(_receipt_value(receipt)) == receipt
    reopened = AgentProcessSupervisor(
        supervisor.root, agent_id=launch.agent_id, profiles=(launch.profile,)
    )
    assert not directory.exists()
    replay = reopened.query(launch)
    assert replay.state is SupervisorLaunchState.CONTAINED
    assert not replay.temporary_storage_pending
    assert replay.temporary_storage_error is None
    assert replay.qualified_success
    assert sum(call[0] == "create" for call in daemon.calls) == 1


def test_unknown_backend_and_restart_preserve_live_storage(tmp_path, monkeypatch):
    supervisor, launch, daemon, _base, directory = _owned(tmp_path, monkeypatch)
    supervisor.launch(launch)
    (directory / "prepared.npz").write_bytes(b"payload")
    daemon.unavailable = True
    assert supervisor.contain(launch).state is SupervisorLaunchState.UNKNOWN
    reopened = AgentProcessSupervisor(
        supervisor.root, agent_id=launch.agent_id, profiles=(launch.profile,)
    )
    assert reopened.query(launch).state is SupervisorLaunchState.UNKNOWN
    assert directory.is_dir()
    daemon.unavailable = False
    daemon.finish()
    assert reopened.contain(launch).state is SupervisorLaunchState.CONTAINED
    assert not directory.exists()


def test_storage_failure_before_launch_is_journaled_cleaned_and_never_relaunched(
    tmp_path, monkeypatch
):
    supervisor, launch, daemon, _base, directory = _owned(tmp_path, monkeypatch)
    prepare = storage.prepare_assignment_storage

    def exhaust(*args, **kwargs):
        with supervisor._connect() as conn:
            row = conn.execute("SELECT * FROM launches").fetchone()
            assert row["temporary_storage_pending"] and row["state"] == "starting"
        prepare(*args, **kwargs)
        (directory / "partial").write_bytes(b"unfinished")
        raise OSError(errno.ENOSPC, "injected exhaustion")

    monkeypatch.setattr(storage, "prepare_assignment_storage", exhaust)
    with pytest.raises(AgentProcessSupervisorError, match="not created") as failure:
        supervisor.launch(launch)
    assert isinstance(failure.value.__cause__, OSError)
    assert failure.value.__cause__.errno == errno.ENOSPC
    assert not directory.exists()
    for receipt in (supervisor.query(launch), supervisor.contain(launch)):
        assert receipt.state is SupervisorLaunchState.NOT_ACCEPTED
        assert not receipt.qualified_success
        assert not receipt.temporary_storage_pending
    with pytest.raises(_SupervisorNoStartError, match="injected exhaustion"):
        supervisor.launch(launch)
    assert supervisor.reject_unstarted_assignment(launch.assignment_id)
    with pytest.raises(_SupervisorNoStartError, match="durably rejected"):
        supervisor.launch(launch)
    assert daemon.calls == []


def test_cleanup_refuses_replaced_attempt_directory(tmp_path, monkeypatch):
    supervisor, launch, daemon, base, directory = _owned(tmp_path, monkeypatch)
    supervisor.launch(launch)
    directory.rmdir()
    other = base / "unrelated"
    other.mkdir()
    (other / "keep").write_bytes(b"not owned")
    directory.symlink_to(other, target_is_directory=True)
    daemon.finish()
    receipt = supervisor.contain(launch)
    assert receipt.state is SupervisorLaunchState.CONTAINED
    assert receipt.temporary_storage_pending
    assert receipt.temporary_storage_error is not None
    assert "NotADirectoryError" in receipt.temporary_storage_error
    assert (other / "keep").read_bytes() == b"not owned"
    directory.unlink()
    assert not supervisor.query(launch).temporary_storage_pending
