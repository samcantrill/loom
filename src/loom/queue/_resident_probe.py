"""Contained, ephemeral probes for resident worker qualification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
from time import monotonic, sleep
from typing import TYPE_CHECKING, cast

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from ._process_group import OwnedProcessGroup, require_group_wait_support

if TYPE_CHECKING:
    from ._agent_process_supervisor import ResidentWorkerLaunchProfile


_MAX_OUTPUT_BYTES = 64 * 1024


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
) -> ResidentProbeResult:
    """Run a fixed Python probe in the worker environment and contain its tree.

    The caller owns the meaning of its fixed script and mapping payload.  This
    helper owns only bounded process IO and descendant containment.
    """
    if not isinstance(script, str) or not script:
        raise ValueError("resident probe script is invalid")
    if (
        not isinstance(timeout_seconds, float | int)
        or isinstance(timeout_seconds, bool)
        or not 0 < timeout_seconds <= 30
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
        temporary = tempfile.TemporaryDirectory(prefix="loom-resident-probe-")
    except OSError:
        return ResidentProbeResult(None, "resident probe scratch creation failed", True)
    result: ResidentProbeResult | None = None
    try:
        with temporary as scratch:
            result = _run_probe_process(
                profile, script, request, timeout_seconds, device_environment, scratch
            )
    except OSError:
        return ResidentProbeResult(
            None,
            "resident probe scratch creation or cleanup failed",
            False if result is None else result.contained,
        )
    return result


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
