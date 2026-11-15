"""Opt-in owned-process acceptance; never pulls images or changes host settings."""

from dataclasses import replace
import os
from pathlib import Path
import select
import signal
import sys
from time import monotonic, sleep

import pytest

from loom.pipeline.executors.apptainer import (
    ApptainerExecOptions,
    SubprocessApptainerExecRunner,
    build_apptainer_exec_command,
)
from loom.pipeline.executors.apptainer import _timeout
from loom.pipeline.executors.containers import ContainerMount, ContainerOptions
from tests.container_acceptance.test_real_container_runtimes import (
    _required_apptainer_resource_command,
)


pytestmark = [pytest.mark.slow, pytest.mark.optional_dependency]


@pytest.fixture
def runtime() -> tuple[str, str]:
    if os.environ.get("LOOM_RUN_APPTAINER_TIMEOUT_ACCEPTANCE") != "1":
        pytest.skip(
            "set LOOM_RUN_APPTAINER_TIMEOUT_ACCEPTANCE=1 for namespace lifecycle acceptance"
        )
    image = os.environ.get("LOOM_APPTAINER_RESOURCE_IMAGE", "")
    assert image and Path(image).is_file(), (
        "set LOOM_APPTAINER_RESOURCE_IMAGE to an approved local SIF"
    )
    return _required_apptainer_resource_command(), image


def _command(runtime: tuple[str, str], workspace: Path, *, resistant: bool = True):  # noqa: ANN202
    child = (
        "trap '' TERM; " if resistant else ""
    ) + "printf ready > /fixture/ready; while :; do sleep 1; done"
    return build_apptainer_exec_command(
        container_options=ContainerOptions(
            image=runtime[1],
            mounts=(
                ContainerMount(source=str(workspace), target="/fixture", mode="rw"),
            ),
        ),
        apptainer_options=ApptainerExecOptions(command=runtime[0]),
        worker_command=("sh", "-c", 'setsid sh -c "$1" & wait', "sh", child),
    )


def _pin_tree(root: int) -> dict[int, int]:
    handles = {root: os.pidfd_open(root)}
    pending = [root]
    while pending:
        parent = pending.pop()
        for file in Path(f"/proc/{parent}/task").glob("*/children"):
            for value in file.read_text().split():
                pid = int(value)
                if pid not in handles:
                    try:
                        handles[pid] = os.pidfd_open(pid)
                        pending.append(pid)
                    except ProcessLookupError:
                        pass
    return handles


def _exited(fd: int) -> bool:
    return bool(select.select([fd], [], [], 0)[0])


def _cleanup(handles: dict[int, int]) -> None:
    for fd in handles.values():
        try:
            if not _exited(fd):
                signal.pidfd_send_signal(fd, signal.SIGKILL)
        except ProcessLookupError:
            pass
        finally:
            os.close(fd)


@pytest.mark.parametrize(
    "mode", ["timeout", "cooperative", "root_first", "interrupt", "uncertain"]
)
def test_real_direct_namespace_settlement(
    runtime: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    command = _command(runtime, tmp_path, resistant=mode != "cooperative")
    capture = _timeout._capture_init
    root_status = _timeout._root_status
    handles: dict[int, int] = {}
    did_interrupt = False
    topology_verified = False

    def observed_capture(process, group):  # noqa: ANN001, ANN202
        nonlocal topology_verified
        fd = capture(process, group)
        if fd is None:
            return None
        if not (tmp_path / "ready").exists():
            os.close(fd)
            return None
        if not handles:
            handles.update(_pin_tree(process.pid))
            assert len(handles) >= 4  # launcher, init, worker, separate-session child
            assert os.getpgid(process.pid) == os.getpgrp()
            facts = [Path(f"/proc/{pid}/status").read_text() for pid in handles]
            init_pids = [
                pid
                for pid, fact in zip(handles, facts, strict=True)
                if "Name:\tsinit\n" in fact
            ]
            assert len(init_pids) == 1
            assert os.getpgid(init_pids[0]) == group
            assert any(os.getpgid(pid) != group for pid in handles)
            topology_verified = True
            if mode == "root_first":
                signal.pidfd_send_signal(handles[process.pid], signal.SIGKILL)
        if mode == "uncertain":
            os.close(fd)
            return None  # deliberately unavailable direct identity, not fake settlement
        return fd

    def interrupt_once(process):  # noqa: ANN001, ANN202
        nonlocal did_interrupt
        if mode == "interrupt" and handles and not did_interrupt:
            did_interrupt = True
            raise KeyboardInterrupt
        return root_status(process)

    monkeypatch.setattr(_timeout, "_capture_init", observed_capture)
    monkeypatch.setattr(_timeout, "_root_status", interrupt_once)
    started = monotonic()
    try:
        if mode == "interrupt":
            with pytest.raises(KeyboardInterrupt):
                SubprocessApptainerExecRunner().run(command, timeout_seconds=1)
        else:
            result = SubprocessApptainerExecRunner().run(command, timeout_seconds=1)
            assert result.returncode != 0
            if mode != "root_first":
                assert result.timed_out
                assert result.error is not None
                assert result.error.startswith("container execution deadline exceeded")
            if mode == "uncertain":
                assert result.error is not None
                assert (
                    "namespace init identity unavailable; cleanup unresolved"
                    in result.error
                )
            elif mode != "root_first":
                assert "unresolved" not in (result.error or "")
        assert monotonic() - started < 6.5
        assert handles, "fixture must become ready before timeout"
        assert topology_verified
        # Uncertain direct observation is intentionally not a settlement claim;
        # fixture-owned pidfds wait for the actual PDEATH/namespace teardown.
        deadline = monotonic() + 2
        while (
            not all(_exited(fd) for fd in handles.values()) and monotonic() < deadline
        ):
            sleep(0.01)
        assert all(_exited(fd) for fd in handles.values())
    finally:
        _cleanup(handles)


def test_real_success_without_timeout_keeps_old_invocation(
    runtime: tuple[str, str],
) -> None:
    command = build_apptainer_exec_command(
        container_options=ContainerOptions(image=runtime[1]),
        apptainer_options=ApptainerExecOptions(command=runtime[0]),
        worker_command=("sh", "-c", "printf ready"),
    )
    result = SubprocessApptainerExecRunner().run(command)
    assert result.returncode == 0 and result.stdout == "ready"
    assert "--pid" not in result.argv
    assert "--cpus" not in result.argv and "--memory" not in result.argv


@pytest.mark.parametrize("exit_code", [0, 3])
def test_real_completed_command_with_timeout(
    runtime: tuple[str, str],
    exit_code: int,
) -> None:
    command = build_apptainer_exec_command(
        container_options=ContainerOptions(image=runtime[1]),
        apptainer_options=ApptainerExecOptions(command=runtime[0]),
        worker_command=("sh", "-c", f"sleep 0.1; printf ready; exit {exit_code}"),
    )
    result = SubprocessApptainerExecRunner().run(command, timeout_seconds=3)
    assert result.returncode == exit_code
    assert result.stdout == "ready" and result.error is None
    assert not result.timed_out


def test_deadline_during_runtime_startup_reports_missing_init(
    runtime: tuple[str, str],
    tmp_path: Path,
) -> None:
    from loom.pipeline.executors.apptainer import ApptainerExecCommand
    import shlex

    wrapper = tmp_path / "delayed-runtime"
    # Only delay the foreground launch; use the selected runtime's real version
    # probe. The wrapper's root is the runner's owned child, not a discovered PID.
    wrapper.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "--version" ]; then exec {shlex.quote(runtime[0])} "$@"; fi\n'
        "while :; do :; done\n",
    )
    wrapper.chmod(0o700)
    result = SubprocessApptainerExecRunner().run(
        ApptainerExecCommand.from_argv((str(wrapper), "exec", runtime[1], "sh")),
        timeout_seconds=0.2,
    )
    assert result.returncode == 124 and result.timed_out
    assert result.error is not None
    assert result.error.startswith("container execution deadline exceeded")
    assert "namespace init identity unavailable; cleanup unresolved" in result.error


def test_real_resident_query_then_contain_settles_namespace(
    runtime: tuple[str, str],
    tmp_path: Path,
) -> None:
    from loom.queue._agent_process_supervisor import (
        AgentProcessSupervisor,
        ResidentWorkerLaunchProfile,
        SupervisorLaunchState,
    )
    from tests.unit.loom.queue.test_agent_process_supervisor import _launch

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    command = _command(runtime, workspace)
    executable = tmp_path / "namespace-worker"
    executable.write_text(
        f"#!{sys.executable}\n"
        "from loom.pipeline.executors.apptainer import ApptainerExecCommand, SubprocessApptainerExecRunner\n"
        f"SubprocessApptainerExecRunner().run(ApptainerExecCommand.from_argv({tuple(command.argv)!r}), timeout_seconds=30)\n",
    )
    executable.chmod(0o700)
    profile = ResidentWorkerLaunchProfile(
        project_root=Path.cwd(),
        python_executable=executable,
        descriptor={
            "profile_id": "namespace-worker",
            "kind": "test-resident",
            "version": 1,
        },
    )
    agent = tmp_path / "agent"
    agent.mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        agent, agent_id="agent-A", profiles=(profile,)
    )
    launch = replace(_launch(supervisor, workspace), profile=profile)
    receipt = supervisor.launch(launch)
    root = receipt.process_id
    assert root is not None
    handles = {root: os.pidfd_open(root)}
    try:
        deadline = monotonic() + 5
        while not (workspace / "ready").exists():
            assert monotonic() < deadline
            sleep(0.01)
        os.close(handles.pop(root))
        handles.update(_pin_tree(root))
        init = next(
            pid
            for pid in handles
            if "Name:\tsinit\n" in Path(f"/proc/{pid}/status").read_text()
        )
        assert os.getpgid(init) == root
        assert any(os.getpgid(pid) != root for pid in handles)
        assert not supervisor.quiescent()
        signal.pidfd_send_signal(handles[root], signal.SIGKILL)
        deadline = monotonic() + 3
        while supervisor.query(launch).state is not SupervisorLaunchState.EXITED:
            assert monotonic() < deadline
            sleep(0.01)
        assert not supervisor.quiescent()  # EXITED is not a release receipt
        assert supervisor.contain(launch).state is SupervisorLaunchState.CONTAINED
        assert all(_exited(fd) for fd in handles.values())
        assert supervisor.contain(launch).state is SupervisorLaunchState.CONTAINED
        supervisor.mark_clean_shutdown()
    finally:
        _cleanup(handles)
        supervisor.contain(launch)


@pytest.mark.parametrize("cancel", [False, True])
def test_resident_delayed_namespace_and_normal_peer(
    runtime: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    """A real delayed runtime keeps one root and never grants an accepted stop."""
    import shlex
    from loom.pipeline.executors.apptainer import ApptainerExecCommand
    from loom.queue._agent_process_supervisor import (
        AgentProcessSupervisor, ResidentWorkerLaunch, SupervisorLaunchState,
    )
    from tests.unit.loom.queue.test_agent_process_supervisor import (
        _named_launch, _sleeping_profile,
    )

    wrapper = tmp_path / "delayed-runtime"
    wrapper.write_text(f"#!/bin/sh\nsleep 3\nexec {shlex.quote(runtime[0])} \"$@\"\n")
    wrapper.chmod(0o700)
    native = _sleeping_profile(tmp_path)
    profile = replace(native, descriptor={"profile_id": "delayed-container"}, container={
        "kind": "apptainer", "container": {"image": {"reference": runtime[1]}},
        "options": {"command": str(wrapper)},
        "python_executable": "/opt/rphys/venv/bin/python", "daemon_endpoint": None,
    })

    def command(launch):
        built = build_apptainer_exec_command(
            container_options=ContainerOptions(image=runtime[1], mounts=(
                ContainerMount(source=str(launch.workspace_root), target="/fixture", mode="rw"),
            )),
            apptainer_options=ApptainerExecOptions(command=str(wrapper)),
            worker_command=("sh", "-c", "while [ ! -f /fixture/run.grant ]; do sleep 0.05; done; "
                            "printf ready > /fixture/ready; sleep 60"),
        )
        return ApptainerExecCommand.from_argv(_timeout.namespace_argv(built.argv))

    monkeypatch.setattr(ResidentWorkerLaunch, "container_command", property(command))
    agent = tmp_path / "agent"
    agent.mkdir()
    owner = AgentProcessSupervisor.initialize(agent, agent_id="agent-A", profiles=(native, profile))
    delayed = replace(_named_launch(owner, tmp_path, profile, "delayed"),
                      environment={key: os.environ[key] for key in ("HOME", "PATH")})
    peer = _named_launch(owner, tmp_path, native, "peer")
    started = monotonic()
    assert owner.launch(delayed).state is SupervisorLaunchState.STARTING
    child = owner._children[delayed.launch_operation_id]
    try:
        assert owner.launch(peer).state is SupervisorLaunchState.RUNNING
        if cancel:
            assert owner.contain(delayed).state is SupervisorLaunchState.STARTING
        while monotonic() - started < 2.2:
            assert owner.query(delayed).state is SupervisorLaunchState.STARTING
            assert not (delayed.workspace_root / "run.grant").exists()
            sleep(0.05)
        deadline = monotonic() + 20
        while delayed.launch_operation_id not in owner._namespace_inits:
            assert monotonic() < deadline, owner.query(delayed)
            owner.query(delayed)
            sleep(0.05)
        assert owner._children[delayed.launch_operation_id] is child
        if cancel:
            assert owner.contain(delayed).state is SupervisorLaunchState.CONTAINED
            assert not (delayed.workspace_root / "run.grant").exists()
            assert not (delayed.workspace_root / "ready").exists()
        else:
            assert owner.query(delayed).state is SupervisorLaunchState.RUNNING
            while not (delayed.workspace_root / "ready").exists():
                assert monotonic() < deadline
                sleep(0.05)
        assert owner.query(peer).state is SupervisorLaunchState.RUNNING
    finally:
        owner.contain(peer)
        receipt = owner.contain(delayed)
        if receipt.state is not SupervisorLaunchState.CONTAINED:
            # This fixture owns the original child even if runtime setup failed.
            child.contain()
        assert receipt.state is SupervisorLaunchState.CONTAINED


@pytest.mark.parametrize("interrupted", [False, True])
def test_stranded_namespace_operator_recovery_preserves_peer(runtime, tmp_path, monkeypatch, interrupted):
    """Recover a gated real container after deliberately losing init capture."""
    import subprocess
    from typing import Any
    from loom.queue._agent_process_supervisor import (
        AgentProcessSupervisorClient, AgentProcessSupervisorService,
        SupervisorLaunchConfiguration, SupervisorLaunchState, _host_boot_evidence,
    )
    from loom.queue._namespace_recovery import ProcessIdentity, _facts, _recover, _children
    from loom.queue.errors import QueueConflictError
    from tests.unit.loom.queue.test_agent_process_supervisor import _sleeping_profile, _named_launch

    agent = tmp_path / "agent"
    agent.mkdir()
    profile = replace(_sleeping_profile(tmp_path), container={
        "kind": "apptainer", "container": {"image": {"reference": runtime[1]}},
        "options": {"command": runtime[0]}, "python_executable": "/opt/rphys/venv/bin/python",
        "daemon_endpoint": None,
    })
    configuration = SupervisorLaunchConfiguration("agent-A", (profile,))
    AgentProcessSupervisorService.initialize_process_free(agent, configuration=configuration)
    bootstrap = f'''
from pathlib import Path
from loom.queue._agent_process_supervisor import _serve, ResidentWorkerLaunch
from loom.pipeline.executors.apptainer import ApptainerExecCommand
from loom.pipeline.executors.apptainer import _timeout
_timeout._capture_init = lambda *args: None
def command(launch):
    return ApptainerExecCommand.from_argv(({runtime[0]!r}, 'exec', '--pid', '--no-init=false', '--cleanenv', '--bind', str(launch.workspace_root)+':/fixture', {runtime[1]!r}, 'sh', '-c', 'while [ ! -f /fixture/run.grant ]; do sleep 0.1; done; touch /fixture/ran; sleep 60'))
ResidentWorkerLaunch.container_command = property(command)
_serve(Path({str(agent / 'supervisor')!r}))
'''
    service = subprocess.Popen([sys.executable, "-c", bootstrap])
    peer = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
    owned_fds = []
    try:
        deadline = monotonic() + 20
        while True:
            try:
                client = AgentProcessSupervisorClient(agent, configuration)
                break
            except ValueError:
                assert monotonic() < deadline
                sleep(0.05)
        launch = replace(_named_launch(client, tmp_path, profile, "stranded"),
                         environment={key: os.environ[key] for key in ("HOME", "PATH")})
        receipt = client.launch_once(launch)
        while receipt.process_id is None:
            assert monotonic() < deadline
            sleep(0.05)
            receipt = client.query(launch)
        root_pid = receipt.process_id
        owned_fds.append(os.pidfd_open(root_pid))
        namespace_pid = None
        while namespace_pid is None:
            for pid in _children(root_pid):
                facts = _facts(pid)
                if len(facts["namespace_pids"]) > 1 and facts["namespace_pids"][-1] == 1:
                    namespace_pid = pid
                    break
            assert monotonic() < deadline
            sleep(0.05)
        owned_fds.append(os.pidfd_open(namespace_pid))
        def identity(pid):
            return ProcessIdentity(pid, _facts(pid)["start_ticks"])
        arguments: dict[str, Any] = dict(operation_id="recover-1", assignment_id=launch.assignment_id,
                         boot_id=_host_boot_evidence()["boot"], supervisor=identity(service.pid),
                         launcher=identity(root_pid), namespace=identity(namespace_pid))
        # A stale operator snapshot must not stop anything, including the owner.
        with pytest.raises(QueueConflictError, match="identity changed"):
            _recover(agent / "supervisor", "agent-A", **{
                **arguments, "namespace": ProcessIdentity(namespace_pid, 1),
            })
        assert peer.poll() is None and service.poll() is None
        assert not (launch.workspace_root / "run.grant").exists()
        if interrupted:
            from loom.queue._namespace_recovery import _PinnedProcess
            original = _PinnedProcess.kill_and_observe
            def fail_after_namespace_exit(self):
                original(self)
                raise QueueConflictError("controlled interrupted observation")
            monkeypatch.setattr(_PinnedProcess, "kill_and_observe", fail_after_namespace_exit)
            with pytest.raises(QueueConflictError, match="controlled interrupted"):
                _recover(agent / "supervisor", "agent-A", **arguments)
            with pytest.raises(QueueConflictError, match="interrupted; retain"):
                _recover(agent / "supervisor", "agent-A", **arguments)
            assert peer.poll() is None and service.poll() is None
            assert not (launch.workspace_root / "run.grant").exists()
            return
        result = _recover(agent / "supervisor", "agent-A", **arguments)
        assert result["state"] == "contained" and result["successful_exit"] is False
        assert _recover(agent / "supervisor", "agent-A", **arguments) == result
        with pytest.raises(QueueConflictError, match="conflicts"):
            _recover(agent / "supervisor", "agent-A", **{**arguments, "assignment_id": "different"})
        assert peer.poll() is None
        assert all(select.select([fd], [], [], 0)[0] for fd in owned_fds)
        assert not (launch.workspace_root / "ran").exists()
        service.wait(timeout=5)
        replacement = AgentProcessSupervisorService.start_empty_initialized(agent, configuration=configuration)
        try:
            retained = replacement.query(launch)
            assert retained.state is SupervisorLaunchState.CONTAINED
            assert not retained.qualified_success and retained.exit_code is None
            assert launch.launch_operation_id in replacement.operator_contained_launches
            assert replacement.launch(launch).process_id == root_pid
        finally:
            replacement.shutdown_clean()
    finally:
        for fd in reversed(owned_fds):
            if not select.select([fd], [], [], 0)[0]:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
            os.close(fd)
        service.kill() if service.poll() is None else None
        service.wait(timeout=5)
        peer.kill()
        peer.wait(timeout=5)
