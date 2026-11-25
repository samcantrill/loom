"""Contained, ephemeral probes for resident worker qualification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
from time import monotonic, sleep
from typing import TYPE_CHECKING, cast

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from ._process_group import OwnedProcessGroup, require_group_wait_support

if TYPE_CHECKING:
    from ._agent_process_supervisor import ResidentWorkerLaunchProfile
    from .preparation import PreparationChildInput


_MAX_OUTPUT_BYTES = 64 * 1024
MAX_RESIDENT_PROBE_TIMEOUT_SECONDS = 120


@dataclass(frozen=True, slots=True)
class ResidentProbeResult:
    """Redacted ephemeral outcome from one contained worker probe."""

    payload: Mapping[str, PlainData] | None
    failure: str | None
    contained: bool


def run_resident_probe(
    profile: ResidentWorkerLaunchProfile,
    script: str,
    payload: Mapping[str, PlainData],
    *,
    timeout_seconds: float,
    device_environment: Mapping[str, str] | None = None,
    runtime: Mapping[str, PlainData] | None = None,
    preparation: PreparationChildInput | None = None,
    _verified_image=None,
) -> ResidentProbeResult:
    """Run a fixed Python probe in the worker environment and contain its tree.

    The caller owns the meaning of its fixed script and mapping payload.  This
    helper owns only bounded process IO and descendant containment. An owned
    resource probe supplies its acquired resource intent through ``runtime``;
    software-readiness callers leave it absent. Preparation probes select the
    same captured input and read-only shared namespace as preparation workers.
    """
    if not isinstance(script, str) or not script:
        raise ValueError("resident probe script is invalid")
    if (
        not isinstance(timeout_seconds, float | int)
        or isinstance(timeout_seconds, bool)
        or not 0 < timeout_seconds <= MAX_RESIDENT_PROBE_TIMEOUT_SECONDS
    ):
        raise ValueError("resident probe timeout is invalid")
    request = thaw_plain_data(
        freeze_plain_data(payload, path="resident probe"), path="resident probe"
    )
    if not isinstance(
        request, Mapping
    ):  # pragma: no cover - freeze validates Mapping input.
        raise ValueError("resident probe payload is invalid")
    if device_environment is not None and any(
        not isinstance(key, str) or not key or not isinstance(value, str)
        for key, value in device_environment.items()
    ):
        raise ValueError("resident probe device environment is invalid")

    try:
        temporary_root = _probe_temporary_root(profile)
    except (OSError, ValueError):
        return ResidentProbeResult(None, "resident probe scratch creation failed", True)
    if profile.container is not None:
        return _container_probe(
            profile, script, request, float(timeout_seconds), device_environment, runtime, preparation,
            temporary_root, _verified_image,
        )

    try:
        scratch = tempfile.mkdtemp(prefix="loom-resident-probe-", dir=temporary_root)
    except OSError:
        return ResidentProbeResult(None, "resident probe scratch creation failed", True)
    result: ResidentProbeResult | None = None
    try:
        result = _run_probe_process(
            profile, script, request, timeout_seconds, device_environment, scratch
        )
        if result.contained:
            shutil.rmtree(scratch)
    except OSError:
        return ResidentProbeResult(
            None,
            "resident probe scratch creation or cleanup failed",
            False if result is None else result.contained,
        )
    return result


def _probe_temporary_root(profile: ResidentWorkerLaunchProfile) -> Path | None:
    """Select host scratch without interpreting container TMPDIR as a host path."""
    selected = os.environ.get("TMPDIR")
    if profile.container is None:
        selected = profile.environment.get("TMPDIR", selected)
    elif profile.temporary_mounts:
        from loom.pipeline.executors.containers import ContainerMount, parse_container_options

        mounts = cast(tuple[ContainerMount, ...], parse_container_options(profile.container["container"]).mounts)
        selected = next(mount.source for mount in mounts if mount.target == profile.temporary_mounts[0])
    if selected is None:
        return None  # Unselected deployments retain platform temporary defaults.
    path = Path(selected)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("probe temporary root must be absolute without '..'")
    path = path.resolve(strict=True)
    if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
        raise ValueError("probe temporary root must be an existing writable directory")
    return path


def _run_probe_process(
    profile: ResidentWorkerLaunchProfile,
    script: str,
    request: Mapping[str, PlainData],
    timeout_seconds: float,
    device_environment: Mapping[str, str] | None,
    scratch: str,
) -> ResidentProbeResult:
    # This remains the single worker-environment owner.  Empty resource
    # inputs describe the unassigned qualification path.
    from ._managed_local import _worker_environment

    environment = _worker_environment(profile, Path(scratch), (), {})
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": scratch,
            "TMP": scratch,
            "TEMP": scratch,
            "XDG_CACHE_HOME": scratch,
            "XDG_CONFIG_HOME": scratch,
            "CUDA_VISIBLE_DEVICES": "",
        }
    )
    if device_environment is not None:
        environment.update(device_environment)
    try:
        require_group_wait_support()
        child = subprocess.Popen(
            [
                str(profile.python_executable),
                "-c",
                script,
                json.dumps(request, sort_keys=True, separators=(",", ":")),
            ],
            cwd=profile.project_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        return ResidentProbeResult(None, "resident probe could not start", True)

    group = OwnedProcessGroup(child)
    try:
        stdout, stderr, timed_out, oversized, contained = _drain_and_contain(
            child, group, float(timeout_seconds)
        )
    except OSError:
        group.kill()
        contained = group.contain()
        for stream in (child.stdout, child.stderr):
            if stream is not None:
                stream.close()
        return ResidentProbeResult(
            None, "resident probe IO or cleanup failed", contained
        )
    if not contained:
        return ResidentProbeResult(None, "resident probe cleanup failed", False)
    if timed_out:
        return ResidentProbeResult(None, "resident probe timed out", True)
    if oversized:
        return ResidentProbeResult(
            None, "resident probe output exceeded its bound", True
        )
    if group.returncode != 0:
        return ResidentProbeResult(None, "resident probe failed", True)
    del stderr
    try:
        observed = json.loads(stdout)
        frozen = freeze_plain_data(observed, path="resident probe output")
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return ResidentProbeResult(
            None, "resident probe returned invalid evidence", True
        )
    if not isinstance(frozen, Mapping):
        return ResidentProbeResult(
            None, "resident probe returned invalid evidence", True
        )
    return ResidentProbeResult(
        cast(
            Mapping[str, PlainData],
            thaw_plain_data(frozen, path="resident probe output"),
        ),
        None,
        True,
    )


def _drain_and_contain(
    process: subprocess.Popen[bytes], group: OwnedProcessGroup, timeout_seconds: float
) -> tuple[bytes, bytes, bool, bool, bool]:
    """Drain both pipes under one budget, then contain before trusting EOF."""
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = monotonic() + timeout_seconds
    timed_out = False
    oversized = False
    contained = False
    try:
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                timed_out = True
                break
            events = selector.select(min(0.05, remaining)) if selector.get_map() else ()
            if not selector.get_map():
                sleep(min(0.01, remaining))
            for key, _ in events:
                data = os.read(key.fd, 8192)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                output[key.data].extend(data)
                if sum(len(value) for value in output.values()) > _MAX_OUTPUT_BYTES:
                    oversized = True
                    break
            if oversized or group.root_status() is not None:
                break
        # Root exit is not pipe settlement: terminate the owned group before
        # draining a descendant that inherited either pipe.
        group.kill()
        contained = group.contain()
        if contained and not oversized:
            # The root may have exited with more than one chunk still buffered.
            # Containment proves EOF can be reached without a live writer.
            for stream, name in (
                (process.stdout, "stdout"),
                (process.stderr, "stderr"),
            ):
                while True:
                    chunk = os.read(stream.fileno(), 8192)
                    if not chunk:
                        break
                    output[name].extend(chunk)
                    if sum(len(value) for value in output.values()) > _MAX_OUTPUT_BYTES:
                        oversized = True
                        break
                if oversized:
                    break
    finally:
        group.kill()
        if not contained:
            contained = group.contain()
        selector.close()
        process.stdout.close()
        process.stderr.close()
    return (
        bytes(output["stdout"]),
        bytes(output["stderr"]),
        timed_out,
        oversized,
        contained,
    )


def _container_probe(profile, script, request, timeout_seconds, device_environment, runtime, preparation, temporary_root, image_paths=None):
    """Use the same daemon evidence owner for installed-environment probes.

    Unknown Docker effects retain scratch and evidence for operator recovery; they
    never qualify an installation or cause an unsafe automatic cleanup.
    """
    import hashlib
    import sqlite3
    from loom.pipeline.errors import RuntimeResourceError
    from ._container_worker import build_container_worker
    from ._docker_worker import DockerWorker
    from ._managed_local import _worker_environment

    try:
        scratch = Path(tempfile.mkdtemp(prefix="loom-resident-probe-", dir=temporary_root))
    except OSError:
        return ResidentProbeResult(None, "resident probe scratch creation failed", True)
    workspace = scratch / "assignments" / "probe"
    workspace.mkdir(parents=True)
    output = workspace / "probe.json"
    binding = profile.container
    assert binding is not None
    # The timestamp is diagnostic only. Record it inside the real guest before
    # evaluating the selected workload so probe runtime is a separate quantity.
    wrapper = """import json, sys, time
from pathlib import Path
output = Path(sys.argv.pop(1))
sys.stdout = output.open("w")
try:
    output.with_suffix(".started").write_text(str(time.monotonic()))
except OSError:
    pass
exec(json.loads(sys.argv.pop(1)))
"""
    from contextlib import ExitStack
    from ._phase_timing import log_phases, observe_phases, phase
    from ._submitted_image_launch import image_for_launch, physical_command
    inputs = ExitStack()
    environment = _worker_environment(profile, workspace, (), {})
    environment.update(device_environment or {})
    try:
        if profile.temporary_mounts:
            from loom.pipeline.executors.containers import ContainerMount, parse_container_options

            container = parse_container_options(binding["container"])
            mounts = []
            for index, mount in enumerate(cast(tuple[ContainerMount, ...], container.mounts)):
                if mount.target in profile.temporary_mounts:
                    temporary = scratch / ("mount-" + str(index))
                    temporary.mkdir(mode=0o700)
                    mount = ContainerMount(source=str(temporary), target=mount.target, mode=mount.mode)
                mounts.append(mount)
            # Probes have no assignment journal. Their existing containment
            # owner retains/removes this entire scratch tree, including mounts.
            binding = {**binding, "container": replace(container, mounts=tuple(mounts)).to_dict()}
            profile = replace(profile, container=binding, temporary_mounts=())
        if profile.submitted_execution is not None and image_paths is None:
            with observe_phases(log_phases):
                image_paths = inputs.enter_context(image_for_launch(
                    profile.submitted_execution.image, profile.shared_roots, scratch.name,
                ))
        command = build_container_worker(
            profile,
            workspace=workspace,
            environment=environment,
            runtime=runtime,
            shared_scope=None if preparation is None else preparation.shared_scope,
            shared_snapshot=None if preparation is None else preparation.input_receipt,
            preparation_only=preparation is not None,
            worker=(
                str(binding["python_executable"]),
                "-c",
                f"exec({wrapper!r})",
                str(output),
                json.dumps(script),
                json.dumps(request, sort_keys=True, separators=(",", ":")),
            ),
        )
        if image_paths is not None:
            from loom.pipeline.executors.apptainer.commands import ApptainerExecCommand
            command = physical_command(cast(ApptainerExecCommand, command), image_paths)
    except (ValueError, OSError, RuntimeResourceError):
        inputs.close()
        shutil.rmtree(scratch)
        return ResidentProbeResult(
            None, "installed container probe command is invalid", True
        )
    except BaseException:
        inputs.close()
        shutil.rmtree(scratch)
        raise
    contained = False
    succeeded = False
    try:
        if binding["kind"] == "docker":
            with sqlite3.connect(scratch / "supervisor.sqlite") as conn:
                DockerWorker.initialize(conn)
                owner = DockerWorker(
                    conn,
                    operation_id="probe",
                    ownership=hashlib.sha256(str(scratch).encode()).hexdigest(),
                    command=command.argv,
                    endpoint=str(binding["daemon_endpoint"]),
                    environment=environment,
                )
                observation = owner.launch()
                deadline = monotonic() + timeout_seconds
                while not observation.contained and monotonic() < deadline:
                    sleep(0.05)
                    observation = owner.observe()
                if not observation.contained:
                    owner.cancel()
                    observation = owner.observe()
                contained = observation.contained
                succeeded = observation.successful
                if contained:
                    owner.remove()
        else:
            from loom.pipeline.executors.apptainer.commands import (
                ApptainerExecCommand,
                SubprocessApptainerExecRunner,
            )

            start = monotonic()
            with observe_phases(log_phases), phase("container_probe_exec", operation_id=scratch.name) as timing:
                result = SubprocessApptainerExecRunner().run(
                    cast(ApptainerExecCommand, command), timeout_seconds=timeout_seconds,
                    host_environment={
                        **os.environ,
                        **dict.fromkeys(("TMPDIR", "TMP", "TEMP", "APPTAINER_TMPDIR", "SINGULARITY_TMPDIR"), str(scratch)),
                    },
                )
                try:
                    stamp = output.with_suffix(".started")
                    if stamp.is_file() and stamp.stat().st_size <= 64:
                        elapsed = float(stamp.read_text()) - start
                        if 0 <= elapsed <= monotonic() - start:
                            timing["seconds_to_first_guest_work"] = elapsed
                except (ValueError, OSError):
                    pass
            # The built-in timeout runner owns the qualified namespace barrier.
            contained = result.error is None
            succeeded = contained and result.returncode == 0 and not result.timed_out
        if not contained:
            return ResidentProbeResult(
                None, "installed container probe containment is unknown", False
            )
        if (
            not succeeded
            or not output.is_file()
            or output.stat().st_size > _MAX_OUTPUT_BYTES
        ):
            return ResidentProbeResult(None, "installed container probe failed", True)
        value = json.loads(output.read_text())
        if not isinstance(value, Mapping):
            return ResidentProbeResult(
                None, "installed container probe returned invalid data", True
            )
        return ResidentProbeResult(
            cast(Mapping[str, PlainData], thaw_plain_data(freeze_plain_data(value))),
            None,
            True,
        )
    finally:
        inputs.close()
        if contained:
            shutil.rmtree(scratch)
