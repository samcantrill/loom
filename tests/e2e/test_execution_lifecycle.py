"""POSIX lifecycle proofs through the public ``loom run`` command."""

from __future__ import annotations

from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import authority_config_to_cli_args, path_to_run_uri
from loom.pipeline.stores.service_authority import LocalAuthorityService
from tests.support.processes import (
    OwnedProcessIdentity,
    capture_owned_process_identity,
    kill_owned_process,
    owned_process_is_live,
)


pytestmark = pytest.mark.e2e


def _wait_for_path(path: Path, *, timeout_seconds: float = 10) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path}")
        time.sleep(0.01)


def _run_command(
    config_path: Path,
    run_uri: str,
    authority_args: tuple[str, ...],
    *,
    executor: str = "local",
    max_parallel_stages: int | None = None,
) -> subprocess.Popen[str]:
    command = [
        sys.executable,
        "-c",
        "from loom.cli.main import main; raise SystemExit(main())",
        "run",
        str(config_path),
        "--run-uri",
        run_uri,
        "--executor",
        executor,
        "--format",
        "json",
        *authority_args,
    ]
    if max_parallel_stages is not None:
        command.extend(("--max-parallel-stages", str(max_parallel_stages)))
    return subprocess.Popen(
        command,
        cwd=Path(__file__).parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _finish_owned_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        return process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=10)


def _write_serial_config(path: Path, *, marker: Path, pid_marker: Path) -> None:
    path.write_text(
        "pipeline:\n"
        "  name: interrupted\n"
        "  stages:\n"
        "    - name: active\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.SleepStage\n"
        "      config:\n"
        "        seconds: 30\n"
        f"        started_marker: {marker}\n"
        f"        pid_marker: {pid_marker}\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: downstream\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      depends_on: [active]\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("executor", ["local", "subprocess"])
def test_cli_sigint_cancels_active_stage_and_exits_130(
    tmp_path: Path,
    executor: str,
) -> None:
    config_path = tmp_path / "pipeline.yaml"
    started = tmp_path / "active.started"
    pid_marker = tmp_path / "active.pid"
    _write_serial_config(config_path, marker=started, pid_marker=pid_marker)
    run_uri = path_to_run_uri(tmp_path / "runs" / executor)

    with LocalAuthorityService.start() as service:
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs", authority_config=service.config()
        )
        process = _run_command(
            config_path,
            run_uri,
            authority_config_to_cli_args(service.config()),
            executor=executor,
        )
        worker_identity: OwnedProcessIdentity | None = None
        try:
            _wait_for_path(started)
            _wait_for_path(pid_marker)
            worker_identity = capture_owned_process_identity(
                int(pid_marker.read_text(encoding="utf-8"))
            )
            process.send_signal(signal.SIGINT)
            _stdout, stderr = _finish_owned_process(process)
            assert not owned_process_is_live(worker_identity)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
            if worker_identity is not None:
                kill_owned_process(worker_identity, signal.SIGKILL)

        assert process.returncode == 130, stderr
        assert worker_identity is not None and not owned_process_is_live(worker_identity)
        run_status = store.read_run_status(run_uri)
        active_status = store.read_stage_status(run_uri, "active")
        downstream_status = store.read_stage_status(run_uri, "downstream")
        assert run_status is not None and run_status.status is RunStatus.CANCELLED
        assert active_status is not None and active_status.status is StageStatus.CANCELLED
        assert downstream_status is not None
        assert downstream_status.status is StageStatus.BLOCKED
        assert store.read_stage_outputs(run_uri, "active") is None
        assert store.read_artifact_index(run_uri) == {}


def test_parallel_cli_sigint_settles_active_stages_without_starting_downstream(
    tmp_path: Path,
) -> None:
    marker_dir = tmp_path / "markers"
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        "pipeline:\n"
        "  name: interrupted-parallel\n"
        "  stages:\n"
        "    - name: left\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.ReleaseStage\n"
        f"      config: {{marker_dir: {marker_dir}}}\n"
        "      outputs: {data: {artifact_type: json, codec_key: json.v1}}\n"
        "    - name: right\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.ReleaseStage\n"
        f"      config: {{marker_dir: {marker_dir}}}\n"
        "      outputs: {data: {artifact_type: json, codec_key: json.v1}}\n"
        "    - name: later\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      depends_on: [left]\n"
        "      outputs: {data: {artifact_type: json, codec_key: json.v1}}\n",
        encoding="utf-8",
    )
    run_uri = path_to_run_uri(tmp_path / "runs" / "parallel")

    with LocalAuthorityService.start() as service:
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs", authority_config=service.config()
        )
        process = _run_command(
            config_path,
            run_uri,
            authority_config_to_cli_args(service.config()),
            max_parallel_stages=2,
        )
        try:
            _wait_for_path(marker_dir / "left.started")
            _wait_for_path(marker_dir / "right.started")
            process.send_signal(signal.SIGINT)
            (marker_dir / "release").write_text("release", encoding="utf-8")
            _stdout, stderr = _finish_owned_process(process)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)

        assert process.returncode == 130, stderr
        run_status = store.read_run_status(run_uri)
        left_status = store.read_stage_status(run_uri, "left")
        right_status = store.read_stage_status(run_uri, "right")
        later_status = store.read_stage_status(run_uri, "later")
        assert run_status is not None and run_status.status is RunStatus.CANCELLED
        assert left_status is not None and left_status.status is StageStatus.SUCCEEDED
        assert right_status is not None and right_status.status is StageStatus.SUCCEEDED
        assert later_status is not None and later_status.status is StageStatus.BLOCKED
