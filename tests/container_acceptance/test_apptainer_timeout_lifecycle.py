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
from loom.queue.local import SubprocessLocalProcessRunner
from tests.container_acceptance.test_real_container_runtimes import (
    _required_apptainer_resource_command,
)
from tests.unit.loom.queue.test_local_adapter import (
    _active_amount,
    _adapter,
    _item,
    _store,
    _with_dispatch_handle,
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


@pytest.mark.parametrize("root_first", [False, True])
def test_real_legacy_capacity_waits_for_namespace_group_settlement(
    runtime: tuple[str, str],
    tmp_path: Path,
    root_first: bool,
) -> None:
    command = _command(runtime, tmp_path)
    code = (
        "from loom.pipeline.executors.apptainer import ApptainerExecCommand, SubprocessApptainerExecRunner; "
        f"SubprocessApptainerExecRunner().run(ApptainerExecCommand.from_argv({tuple(command.argv)!r}), timeout_seconds=30)"
    )
    store = _store()
    store.set_resource_limit("workspace-1", "cpu", limit=1)
    adapter = _adapter(store, SubprocessLocalProcessRunner())
    item = _item("namespace-fixture", resources={"cpu": 1})
    item = replace(
        item,
        admission_digest=None,
        launch_contract=replace(
            item.launch_contract,
            snapshot={"argv": [sys.executable, "-c", code]},
        ),
    )
    started = adapter.dispatch(item)
    assert started.handle_id is not None
    dispatched = _with_dispatch_handle(item, started.handle_id, started.evidence)
    root = adapter._active[started.handle_id].process.pid  # noqa: SLF001 - fixture's creation-owned handle
    handles = {root: os.pidfd_open(root)}
    try:
        deadline = monotonic() + 5
        while not (tmp_path / "ready").exists():
            assert monotonic() < deadline
            sleep(0.01)
        os.close(handles.pop(root))
        handles.update(_pin_tree(root))
        assert len(handles) >= 5
        assert any(os.getpgid(pid) != root for pid in handles)
        init = next(
            pid
            for pid in handles
            if "Name:\tsinit\n" in Path(f"/proc/{pid}/status").read_text()
        )
        assert os.getpgid(init) == root
        assert _active_amount(store, "cpu") == 1
        if root_first:
            signal.pidfd_send_signal(handles[root], signal.SIGKILL)
        else:
            cancellation = adapter.cancel(
                dispatched, requested_by="test", reason="fixture"
            )
            assert cancellation.evidence["exit_observed"] is False
        assert not adapter.inspect(dispatched).terminal
        assert _active_amount(store, "cpu") == 1
        deadline = monotonic() + 6
        while True:
            observation = adapter.inspect(dispatched)
            if observation.terminal:
                assert all(_exited(fd) for fd in handles.values())
                assert _active_amount(store, "cpu") == 0
                break
            assert _active_amount(store, "cpu") == 1
            assert monotonic() < deadline
            sleep(0.02)
    finally:
        _cleanup(handles)
        # Let the actual adapter reap its own root, including on assertion failure.
        adapter.cancel(dispatched, requested_by="test", reason="fixture cleanup")
        deadline = monotonic() + 5
        while not adapter.inspect(dispatched).terminal and monotonic() < deadline:
            sleep(0.02)


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
