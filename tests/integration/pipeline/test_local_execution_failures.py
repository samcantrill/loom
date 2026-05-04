"""Integration tests for local execution failure persistence."""

from pathlib import Path
from typing import cast

import pytest

from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.planning import PlanAction, PlanSelectors
from loom.pipeline.status import RunStatus, StageStatus, StageStatusRecord
from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores.errors import CorruptStoreDocumentError
from tests.support.pipeline_execution_configs import local_execution_config
from loom.serialization import PlainData

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


class SkipStatusFailingRunStore(LocalRunStore):
    def write_stage_status(
        self, run_id: str, stage_name: str, status: StageStatusRecord
    ) -> None:
        if status.status == StageStatus.SKIPPED:
            raise CorruptStoreDocumentError("skip status write failed")
        super().write_stage_status(run_id, stage_name, status)


class FailedStatusFailingRunStore(LocalRunStore):
    def write_stage_status(
        self, run_id: str, stage_name: str, status: StageStatusRecord
    ) -> None:
        if status.status == StageStatus.FAILED:
            raise CorruptStoreDocumentError("failed status write failed")
        super().write_stage_status(run_id, stage_name, status)


def _failure_config(target: str) -> dict[str, PlainData]:
    return cast(
        dict[str, PlainData],
        {
            "pipeline": {
                "name": "failure-demo",
                "stages": [
                    {
                        "name": "build",
                        "_target_": target,
                        "outputs": {
                            "data": {"artifact_type": "json", "codec_key": "json.v1"}
                        },
                    },
                    {
                        "name": "report",
                        "_target_": "tests.support.pipeline_execution_stages.TextConsumerStage",
                        "inputs": {"data": "build.data"},
                        "outputs": {
                            "text": {"artifact_type": "text", "codec_key": "text.v1"}
                        },
                    },
                ],
            }
        },
    )


def test_stage_exception_persists_failure_before_failed_status(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=_failure_config(
                "tests.support.pipeline_execution_stages.FailingStage"
            ),
            run_id="run1",
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.stage_results["build"].status == StageStatus.FAILED
    assert result.stage_results["report"].action == PlanAction.BLOCKED
    failure = run_store.read_stage_failure("run1", "build")
    status = run_store.read_stage_status("run1", "build")
    assert failure is not None
    assert status is not None
    assert failure["failure_type"] == "stage_exception"
    assert status.status == StageStatus.FAILED


def test_invalid_outputs_fail_with_inspectable_state(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=_failure_config(
                "tests.support.pipeline_execution_stages.BadOutputStage"
            ),
            run_id="run1",
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "output_validation"
    status = run_store.read_stage_status("run1", "build")
    assert status is not None
    assert status.started_at is not None
    assert (tmp_path / "runs" / "run1" / "stages" / "build" / "failure.json").is_file()


def test_failed_status_commit_failure_marks_root_run_failed(
    tmp_path: Path,
) -> None:
    run_store = FailedStatusFailingRunStore(tmp_path / "runs")
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=_failure_config(
                "tests.support.pipeline_execution_stages.BadOutputStage"
            ),
            run_id="run1",
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "store_commit"
    persisted_failure = run_store.read_stage_failure("run1", "build")
    assert persisted_failure is not None
    assert persisted_failure["failure_type"] == "output_validation"
    status = run_store.read_run_status("run1")
    assert status is not None
    assert status.status == RunStatus.FAILED


def test_stage_contract_failure_uses_stage_contract_type(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=_failure_config(
                "tests.support.pipeline_execution_stages.NotAStage"
            ),
            run_id="run1",
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "stage_contract"


def test_skip_status_commit_failure_keeps_run_failed(tmp_path: Path) -> None:
    run_store = SkipStatusFailingRunStore(tmp_path / "runs")
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=local_execution_config(),
            run_id="run1",
            selectors=PlanSelectors(skip_stages=("report",)),
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "store_commit"
    assert result.stage_results["report"].action == PlanAction.BLOCKED
    status = run_store.read_run_status("run1")
    assert status is not None
    assert status.status == RunStatus.FAILED
