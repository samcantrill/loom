"""Integration tests for serial subprocess execution."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import time
from typing import cast

import pytest

from loom.pipeline import PipelineSpec
from loom.pipeline.execution import (
    ExecutionFailure,
    PipelineRunner,
    RunRequest,
    create_authority_backed_serial_run_store,
)
from loom.pipeline.executors import LocalExecutor, SubprocessExecutor
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalArtifactStore, path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.pipeline.stores.service_authority import LocalAuthorityService
from loom.provenance.models import ProvenanceCaptureOptions


def _spec(
    *,
    target: str = "tests.support.pipeline_execution_stages.JsonProducerStage",
    stage_config: dict[str, object] | None = None,
) -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "name": "demo",
            "stages": [
                {
                    "name": "build",
                    "factory": {"_target_": target},
                    "config": stage_config or {"value": 123},
                    "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
                }
            ],
        }
    )


def _request(target: str) -> RunRequest:
    return RunRequest(
        pipeline=_spec(target=target),
        options={"executor": "subprocess"},
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
            capture_command=False,
        ),
    )


def _request_with_executor(target: str, *, executor: str, run_uri: str) -> RunRequest:
    return RunRequest(
        pipeline=_spec(target=target),
        run_uri=run_uri,
        options={"executor": executor},
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
            capture_command=False,
        ),
    )


def _run_store(tmp_path: Path):
    return create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=SQLitePerRunAuthorityStore(),
    )


def test_local_and_subprocess_success_runs_are_equivalent(tmp_path: Path) -> None:
    local_store = _run_store(tmp_path)
    local_uri = path_to_run_uri(tmp_path / "runs" / "local")
    subprocess_uri = path_to_run_uri(tmp_path / "runs" / "subprocess")

    local = PipelineRunner(run_store=local_store, executor=LocalExecutor()).run(
        _request_with_executor(
            "tests.support.pipeline_execution_stages.JsonProducerStage",
            executor="local",
            run_uri=local_uri,
        )
    )
    with LocalAuthorityService.start() as service:
        subprocess_store = create_authority_backed_serial_run_store(
            tmp_path / "runs",
            authority_config=service.config(),
        )
        subprocess = PipelineRunner(
            run_store=subprocess_store,
            executor=SubprocessExecutor(run_store=subprocess_store),
        ).run(
            _request_with_executor(
                "tests.support.pipeline_execution_stages.JsonProducerStage",
                executor="subprocess",
                run_uri=subprocess_uri,
            )
        )

        local_outputs = local_store.read_stage_outputs(local.run_uri, "build")
        subprocess_outputs = subprocess_store.read_stage_outputs(
            subprocess.run_uri, "build"
        )
        assert local_outputs is not None
        assert subprocess_outputs is not None
        local_artifacts = LocalArtifactStore(
            local_store.local_artifact_root(local.run_uri)
        )
        subprocess_artifacts = LocalArtifactStore(
            subprocess_store.local_artifact_root(subprocess.run_uri)
        )

        assert local.status == subprocess.status == RunStatus.SUCCEEDED
        assert local.stage_results["build"].status == StageStatus.SUCCEEDED
        assert subprocess.stage_results["build"].status == StageStatus.SUCCEEDED
        assert local_artifacts.load(local_outputs["data"]) == subprocess_artifacts.load(
            subprocess_outputs["data"]
        )
        assert subprocess_store.read_stage_worker_result(
            subprocess.run_uri, "build", attempt=1
        )
    assert (
        local_store.read_stage_worker_result(local.run_uri, "build", attempt=1) is None
    )


def test_subprocess_executor_success_parent_finalizes_stage(tmp_path: Path) -> None:
    with LocalAuthorityService.start() as service:
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs",
            authority_config=service.config(),
        )

        result = PipelineRunner(
            run_store=store,
            executor=SubprocessExecutor(run_store=store),
        ).run(
            _request("tests.support.pipeline_execution_stages.JsonProducerStage")
        )

    assert result.status == RunStatus.SUCCEEDED


def test_subprocess_executor_runs_against_service_authority(
    tmp_path: Path,
) -> None:
    with LocalAuthorityService.start() as service:
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs",
            authority_config=service.config(),
        )

        result = PipelineRunner(
            run_store=store,
            executor=SubprocessExecutor(run_store=store),
        ).run(
            _request("tests.support.pipeline_execution_stages.JsonProducerStage")
        )

        assert result.status == RunStatus.SUCCEEDED
        snapshot = store.authority_store.snapshot(result.run_uri)
        assert snapshot.status == RunStatus.SUCCEEDED
        assert snapshot.stages[0].status == StageStatus.SUCCEEDED
        assert result.stage_results["build"].status == StageStatus.SUCCEEDED
        outputs = store.read_stage_outputs(result.run_uri, "build")
        assert outputs is not None
        artifact_store = LocalArtifactStore(store.local_artifact_root(result.run_uri))
        assert artifact_store.load(outputs["data"]) == {"value": 123}
        assert store.read_stage_worker_result(result.run_uri, "build", attempt=1) is not None
        provenance = store.read_stage_provenance(result.run_uri, "build")
        assert provenance is not None
        executor_metadata = cast(dict[str, object], provenance["executor_metadata"])
        assert executor_metadata["executor"] == "subprocess"
        assert executor_metadata["returncode"] == 0


def test_subprocess_executor_failure_parent_finalizes_failed_run(
    tmp_path: Path,
) -> None:
    with LocalAuthorityService.start() as service:
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs",
            authority_config=service.config(),
        )

        result = PipelineRunner(
            run_store=store,
            executor=SubprocessExecutor(run_store=store),
        ).run(
            _request("tests.support.pipeline_execution_stages.FailingStage")
        )

        assert result.status == RunStatus.FAILED
        assert result.stage_results["build"].status == StageStatus.FAILED
        worker_result = store.read_stage_worker_result(
            result.run_uri, "build", attempt=1
        )
        assert worker_result is not None
        persisted_failure = store.read_stage_failure(result.run_uri, "build")
        assert persisted_failure is not None
        failure = cast(ExecutionFailure, result.failure)
        assert failure.executor == "subprocess"
        assert failure.failure_type == "stage_exception"
        assert "stage failed intentionally" in failure.message
        assert failure.exit_code == 1
        status = store.read_run_status(result.run_uri)
        assert status is not None
        assert status.status == RunStatus.FAILED


def test_subprocess_timeout_kills_the_real_worker_before_failed_result(
    tmp_path: Path,
) -> None:
    pid_marker = tmp_path / "worker.pid"
    run_uri = path_to_run_uri(tmp_path / "runs" / "timeout")
    request = RunRequest(
        pipeline=_spec(
            target="tests.support.pipeline_execution_stages.SleepStage",
            stage_config={"seconds": 30, "pid_marker": str(pid_marker)},
        ),
        run_uri=run_uri,
        options={
            "executor": "subprocess",
            "reliability": {
                "timeout": {"enabled": True, "duration_seconds": 2}
            },
        },
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
            capture_command=False,
        ),
    )

    with LocalAuthorityService.start() as service:
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs", authority_config=service.config()
        )
        result = PipelineRunner(
            run_store=store,
            executor=SubprocessExecutor(run_store=store),
        ).run(request)

        deadline = time.monotonic() + 5
        while not pid_marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pid_marker.exists()
        worker_pid = int(pid_marker.read_text(encoding="utf-8"))
        try:
            os.kill(worker_pid, 0)
        except OSError as exc:
            assert exc.errno == errno.ESRCH
        else:
            pytest.fail("timed-out worker is still live")

        assert result.status is RunStatus.FAILED
        assert result.stage_results["build"].status is StageStatus.FAILED
        assert result.stage_results["build"].failure is not None
        timeout = result.stage_results["build"].failure.details["timeout"]
        assert timeout["timed_out"] is True
        assert store.read_stage_outputs(run_uri, "build") is None
        assert store.read_artifact_index(run_uri) == {}
