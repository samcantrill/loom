"""Integration tests for local execution failure persistence."""

from pathlib import Path
from typing import cast

import pytest

from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution.authority_adapter import (
    AuthorityBackedSerialRunStore,
)
from loom.pipeline.planning import PlanAction, PlanSelectors
from loom.pipeline.status import RunStatus, StageStatus, StageStatusRecord
from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from loom.pipeline.stores.errors import CorruptStoreDocumentError
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.serialization import PlainData
from tests.support.pipeline_execution_configs import local_execution_config

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


class SkipStatusFailingRunStore(LocalRunStore):
    def write_stage_status(
        self, run_uri: str, stage_name: str, status: StageStatusRecord
    ) -> None:
        if status.status == StageStatus.SKIPPED:
            raise CorruptStoreDocumentError("skip status write failed")
        super().write_stage_status(run_uri, stage_name, status)


class FailedStatusFailingRunStore(LocalRunStore):
    def write_stage_status(
        self, run_uri: str, stage_name: str, status: StageStatusRecord
    ) -> None:
        if status.status == StageStatus.FAILED:
            raise CorruptStoreDocumentError("failed status write failed")
        super().write_stage_status(run_uri, stage_name, status)


def _failure_config(target: str) -> dict[str, PlainData]:
    return cast(
        dict[str, PlainData],
        {
            "pipeline": {
                "name": "failure-demo",
                "stages": [
                    {
                        "name": "build",
                        "factory": {"_target_": target},
                        "outputs": {
                            "data": {"artifact_type": "json", "codec_key": "json.v1"}
                        },
                    },
                    {
                        "name": "report",
                        "factory": {
                            "_target_": "tests.support.pipeline_execution_stages.TextConsumerStage"
                        },
                        "inputs": {"data": "build.data"},
                        "outputs": {
                            "text": {"artifact_type": "text", "codec_key": "text.v1"}
                        },
                    },
                ],
            }
        },
    )


def _run_uri(tmp_path: Path, name: str = "run1") -> str:
    return path_to_run_uri(tmp_path / "runs" / name)


def _run_store(
    tmp_path: Path,
    *,
    local_store: LocalRunStore | None = None,
) -> AuthorityBackedSerialRunStore:
    return AuthorityBackedSerialRunStore(
        local_store=local_store or LocalRunStore(tmp_path / "runs"),
        authority_store=SQLitePerRunAuthorityStore(
            clock=lambda: "2020-01-01T00:00:00Z"
        ),
    )


def test_stage_exception_persists_failure_before_failed_status(tmp_path: Path) -> None:
    run_store = _run_store(tmp_path)
    run_uri = _run_uri(tmp_path)
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=_failure_config(
                "tests.support.pipeline_execution_stages.FailingStage"
            ),
            run_uri=run_uri,
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.stage_results["build"].status == StageStatus.FAILED
    assert result.stage_results["report"].action == PlanAction.BLOCKED
    assert result.stage_results["report"].status == StageStatus.BLOCKED
    failure = run_store.read_stage_failure(run_uri, "build")
    status = run_store.read_stage_status(run_uri, "build")
    blocked_status = run_store.read_stage_status(run_uri, "report")
    assert failure is not None
    assert status is not None
    assert blocked_status is not None
    assert failure["failure_type"] == "stage_exception"
    assert status.status == StageStatus.FAILED
    assert blocked_status.status == StageStatus.BLOCKED
    assert blocked_status.metadata["blocked_by"] == ["build"]
    assert blocked_status.metadata["reason_code"] == "upstream_failed"
    blocked_dir = tmp_path / "runs" / "run1" / "stages" / "report"
    assert sorted(path.name for path in blocked_dir.iterdir()) == ["status.json"]
    assert run_store.read_run_lock(run_uri) is None
    assert any(
        event.event_type == "stage.failed" and event.scope.stage_name == "build"
        for event in run_store.read_events(run_uri)
    )
    assert any(
        event.event_type == "stage.blocked" and event.scope.stage_name == "report"
        for event in run_store.read_events(run_uri)
    )
    assert run_store.read_events(run_uri)[-1].event_type == "run.failed"


def test_invalid_outputs_fail_with_inspectable_state(tmp_path: Path) -> None:
    run_store = _run_store(tmp_path)
    run_uri = _run_uri(tmp_path)
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=_failure_config(
                "tests.support.pipeline_execution_stages.BadOutputStage"
            ),
            run_uri=run_uri,
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "output_validation"
    status = run_store.read_stage_status(run_uri, "build")
    assert status is not None
    assert status.started_at is not None
    assert (tmp_path / "runs" / "run1" / "stages" / "build" / "failure.json").is_file()


def test_failed_status_commit_failure_marks_root_run_failed(
    tmp_path: Path,
) -> None:
    run_store = _run_store(
        tmp_path,
        local_store=FailedStatusFailingRunStore(tmp_path / "runs"),
    )
    run_uri = _run_uri(tmp_path)
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=_failure_config(
                "tests.support.pipeline_execution_stages.BadOutputStage"
            ),
            run_uri=run_uri,
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "store_commit"
    persisted_failure = run_store.read_stage_failure(run_uri, "build")
    assert persisted_failure is not None
    assert persisted_failure["failure_type"] == "output_validation"
    status = run_store.read_run_status(run_uri)
    assert status is not None
    assert status.status == RunStatus.FAILED


def test_stage_contract_failure_uses_stage_contract_type(tmp_path: Path) -> None:
    run_store = _run_store(tmp_path)
    run_uri = _run_uri(tmp_path)
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=_failure_config("tests.support.pipeline_execution_stages.NotAStage"),
            run_uri=run_uri,
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "stage_contract"


def test_skip_status_commit_failure_keeps_run_failed(tmp_path: Path) -> None:
    run_store = _run_store(
        tmp_path,
        local_store=SkipStatusFailingRunStore(tmp_path / "runs"),
    )
    run_uri = _run_uri(tmp_path)
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=local_execution_config(),
            run_uri=run_uri,
            selectors=PlanSelectors(skip_stages=("report",)),
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "store_commit"
    assert result.stage_results["report"].action == PlanAction.BLOCKED
    status = run_store.read_run_status(run_uri)
    assert status is not None
    assert status.status == RunStatus.FAILED
